"""Tests for destination span resolution (issue #18).

Covers the three modes (prev_curr_month, file_date_range, override), the
filename/mtime/exif fallback chain used to date a file in file_date_range
mode, and the fail/fallback_prev_curr parse-failure policy -- all against
synthetic tmp_path directories, never real staging data.
"""

import os
import time
from datetime import date
from pathlib import Path

import pytest

import mobile_backup
from mobile_backup import (
    compute_file_date_range_span,
    extract_file_date,
    month_span,
    resolve_destination_span,
)


def _cfg(tmp_path: Path, **overrides: object) -> dict[str, object]:
    cfg: dict[str, object] = {"staging_root": str(tmp_path)}
    cfg.update(overrides)
    return cfg


def test_defaults_to_prev_curr_month_when_unconfigured(tmp_path: Path) -> None:
    span, overridden, diagnostics = resolve_destination_span(_cfg(tmp_path))

    assert span == month_span()
    assert overridden is False
    assert diagnostics["mode"] == "prev_curr_month"


def test_legacy_override_string_infers_override_mode(tmp_path: Path) -> None:
    span, overridden, diagnostics = resolve_destination_span(
        _cfg(tmp_path, destination_span_override="202601_202603")
    )

    assert span == "202601_202603"
    assert overridden is True
    assert diagnostics["mode"] == "override"


def test_explicit_mode_wins_over_leftover_override_string(tmp_path: Path) -> None:
    # An explicit mode always takes precedence over an incidental override value.
    span, overridden, _ = resolve_destination_span(
        _cfg(
            tmp_path,
            destination_span_mode="prev_curr_month",
            destination_span_override="202601_202603",
        )
    )

    assert span == month_span()
    assert overridden is False


def test_override_mode_without_override_value_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="destination_span_override"):
        resolve_destination_span(_cfg(tmp_path, destination_span_mode="override"))


def test_invalid_mode_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="destination_span_mode"):
        resolve_destination_span(_cfg(tmp_path, destination_span_mode="whenever"))


def test_file_date_range_spans_non_adjacent_months(tmp_path: Path) -> None:
    (tmp_path / "20260105_090000.jpg").write_bytes(b"jan")
    (tmp_path / "20260620_090000.jpg").write_bytes(b"jun")

    span, overridden, diagnostics = resolve_destination_span(
        _cfg(tmp_path, destination_span_mode="file_date_range")
    )

    assert span == "202601_202606"
    assert overridden is True
    assert diagnostics["min"] == date(2026, 1, 5)
    assert diagnostics["max"] == date(2026, 6, 20)
    assert diagnostics["failed"] == 0


def test_file_date_range_backfill_uses_file_dates_not_todays_date(
    tmp_path: Path,
) -> None:
    # Simulates a backlog: files from months ago, processed "today". The span
    # must reflect when the photos were taken, not when the script runs.
    (tmp_path / "20250301_120000.jpg").write_bytes(b"old1")
    (tmp_path / "20250315_120000.jpg").write_bytes(b"old2")

    span, _, _ = resolve_destination_span(
        _cfg(tmp_path, destination_span_mode="file_date_range")
    )

    assert span == "202503_202503"
    assert span != month_span()


def test_file_date_range_falls_back_to_mtime_when_filename_unparseable(
    tmp_path: Path,
) -> None:
    f = tmp_path / "IMG_random_name.jpg"
    f.write_bytes(b"data")
    target_ts = time.mktime((2026, 4, 10, 0, 0, 0, 0, 0, -1))
    os.utime(f, (target_ts, target_ts))

    result = extract_file_date(f, primary_source="filename")

    assert result == date(2026, 4, 10)


def test_extract_file_date_returns_none_when_all_sources_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "IMG_random_name.jpg"
    f.write_bytes(b"data")
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "filename", lambda _p: None)
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "mtime", lambda _p: None)
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "exif", lambda _p: None)

    assert extract_file_date(f, primary_source="filename") is None


def test_parse_failure_fail_policy_raises_when_most_files_undated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.jpg").write_bytes(b"a")
    (tmp_path / "b.jpg").write_bytes(b"b")
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "filename", lambda _p: None)
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "mtime", lambda _p: None)
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "exif", lambda _p: None)

    with pytest.raises(RuntimeError, match="could not determine dates"):
        compute_file_date_range_span(
            tmp_path, date_source="filename", on_parse_failure="fail"
        )


def test_parse_failure_fallback_policy_uses_auto_month_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.jpg").write_bytes(b"a")
    (tmp_path / "b.jpg").write_bytes(b"b")
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "filename", lambda _p: None)
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "mtime", lambda _p: None)
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "exif", lambda _p: None)

    span, diagnostics = compute_file_date_range_span(
        tmp_path, date_source="filename", on_parse_failure="fallback_prev_curr"
    )

    assert span == month_span()
    assert diagnostics["fallback"] is True
    assert diagnostics["failed"] == 2


def test_parse_failure_policy_tolerates_a_minority_of_undated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "20260105_090000.jpg").write_bytes(b"dated")
    (tmp_path / "20260110_090000.jpg").write_bytes(b"dated")
    (tmp_path / "no_date_here.jpg").write_bytes(b"undated")
    # Force a genuine failure for the third file: filename won't match, and
    # mtime/exif are disabled so there's no fallback -- otherwise mtime alone
    # (every real file has one) would "successfully" date it as today.
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "mtime", lambda _p: None)
    monkeypatch.setitem(mobile_backup._DATE_EXTRACTORS, "exif", lambda _p: None)

    span, diagnostics = compute_file_date_range_span(
        tmp_path, date_source="filename", on_parse_failure="fail"
    )

    # 1/3 undated is a minority -- computed from the 2 dated files, no failure raised.
    assert span == "202601_202601"
    assert diagnostics["failed"] == 1
    assert diagnostics["fallback"] is False


def test_file_date_range_excludes_junk_files(tmp_path: Path) -> None:
    (tmp_path / "20260105_090000.jpg").write_bytes(b"dated")
    (tmp_path / "desktop.ini").write_bytes(b"junk")

    _span, diagnostics = compute_file_date_range_span(
        tmp_path, date_source="filename", on_parse_failure="fail"
    )

    assert diagnostics["total"] == 1
