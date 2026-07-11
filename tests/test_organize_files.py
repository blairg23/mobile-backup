from pathlib import Path

import pytest

import organize_files
from organize_files import FilesInFolder, verify_and_sync


def test_compare_hash_lists_finds_missing(tmp_path: Path) -> None:
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    checker = FilesInFolder(left_folder=str(left_dir), right_folder=str(right_dir))

    left = {"headers": [], "abc": "/left/a.jpg", "def": "/left/b.jpg"}
    right = {"headers": [], "abc": "/right/a.jpg"}

    missing = checker.compare_hash_lists(left_hash_dict=left, right_hash_dict=right)

    assert missing == ["/left/b.jpg"]


def test_verify_and_sync_copies_missing_files(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "photo.jpg").write_bytes(b"same bytes")

    verify_and_sync(left, right)

    assert (right / "photo.jpg").exists()
    assert (right / "photo.jpg").read_bytes() == b"same bytes"


def test_verify_and_sync_no_op_when_already_present(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "photo.jpg").write_bytes(b"same bytes")
    (right / "photo.jpg").write_bytes(b"same bytes")

    verify_and_sync(left, right)

    assert not (right / "missing.txt").exists()
    assert (right / "photo.jpg").read_bytes() == b"same bytes"


def test_verify_and_sync_quarantines_conflicting_destination_file(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "photo.jpg").write_bytes(b"left bytes")
    (right / "photo.jpg").write_bytes(b"different right bytes")

    verify_and_sync(left, right)

    # The existing Dropbox file is never overwritten.
    assert (right / "photo.jpg").read_bytes() == b"different right bytes"
    # The source file is quarantined instead of silently dropped.
    assert (right / "_conflicts" / "photo.jpg").read_bytes() == b"left bytes"


def test_verify_and_sync_raises_on_copy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "photo.jpg").write_bytes(b"left bytes")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("destination unavailable")

    monkeypatch.setattr(organize_files.shutil, "copy2", _boom)

    with pytest.raises(RuntimeError, match="Failed to sync"):
        verify_and_sync(left, right)
