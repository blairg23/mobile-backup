"""Tests for the mobile_backup.py CLI's dry/run mode argument.

Every subcommand (run, rename, organize) must default to a dry preview and
only make real changes when "run" is passed explicitly as the mode arg --
matching the dry/run convention used by every other ToolShed tool.
"""

from pathlib import Path

import pytest

import mobile_backup
from mobile_backup import build_parser, cmd_organize, cmd_rename, cmd_run


def test_all_subcommands_default_mode_to_dry() -> None:
    parser = build_parser()
    for command in ("run", "rename", "organize"):
        args = parser.parse_args([command])
        assert args.mode == "dry"


def test_all_subcommands_accept_explicit_run_mode() -> None:
    parser = build_parser()
    for command in ("run", "rename", "organize"):
        args = parser.parse_args([command, "run"])
        assert args.mode == "run"


@pytest.mark.parametrize(
    ("cli_args", "config_dry_run", "expected_dry_run"),
    [
        (["run"], False, True),
        (["run", "run"], True, False),
    ],
)
def test_cmd_run_mode_overrides_config_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    cli_args: list[str],
    config_dry_run: bool,
    expected_dry_run: bool,
) -> None:
    """The CLI mode arg always wins over whatever dry_run happens to be in config.yaml."""
    monkeypatch.setattr(
        mobile_backup,
        "load_config",
        lambda _config_path=None: {"dry_run": config_dry_run},
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(mobile_backup, "run_pipeline", lambda cfg: captured.update(cfg))

    cmd_run(build_parser().parse_args(cli_args))

    assert captured["dry_run"] is expected_dry_run


def test_cmd_rename_dry_by_default_makes_no_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rename_input = tmp_path / "rename_tool_input"
    rename_input.mkdir()
    src = rename_input / "20250615_143022.mp4"
    src.write_bytes(b"fake video content")
    monkeypatch.setattr(
        mobile_backup,
        "load_config",
        lambda _config_path=None: {"rename_tool_input": str(rename_input)},
    )

    cmd_rename(build_parser().parse_args(["rename"]))

    assert src.exists()
    assert not (rename_input / "2025-06-15 14.30.22.mp4").exists()


def test_cmd_rename_run_mode_makes_real_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rename_input = tmp_path / "rename_tool_input"
    rename_input.mkdir()
    src = rename_input / "20250615_143022.mp4"
    src.write_bytes(b"fake video content")
    monkeypatch.setattr(
        mobile_backup,
        "load_config",
        lambda _config_path=None: {"rename_tool_input": str(rename_input)},
    )

    cmd_rename(build_parser().parse_args(["rename", "run"]))

    assert not src.exists()
    assert (rename_input / "2025-06-15 14.30.22.mp4").exists()


def test_cmd_organize_dry_by_default_makes_no_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = tmp_path / "desktop_mobile_camera"
    right = tmp_path / "dropbox_camera_uploads"
    left.mkdir()
    right.mkdir()
    (left / "photo.jpg").write_bytes(b"same bytes")
    monkeypatch.setattr(
        mobile_backup,
        "load_config",
        lambda _config_path=None: {
            "desktop_mobile_camera": str(left),
            "dropbox_camera_uploads": str(right),
        },
    )

    cmd_organize(build_parser().parse_args(["organize"]))

    assert not (right / "photo.jpg").exists()


def test_cmd_organize_run_mode_makes_real_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = tmp_path / "desktop_mobile_camera"
    right = tmp_path / "dropbox_camera_uploads"
    left.mkdir()
    right.mkdir()
    (left / "photo.jpg").write_bytes(b"same bytes")
    monkeypatch.setattr(
        mobile_backup,
        "load_config",
        lambda _config_path=None: {
            "desktop_mobile_camera": str(left),
            "dropbox_camera_uploads": str(right),
        },
    )

    cmd_organize(build_parser().parse_args(["organize", "run"]))

    assert (right / "photo.jpg").exists()
