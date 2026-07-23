"""Tests for the playground generator (issue #56).

Everything here operates under pytest's tmp_path fixture -- generate_playground()
must never read or write any real staging/Dropbox/Google Drive path.
"""

from pathlib import Path

import pytest
import yaml

from mobile_backup import generate_playground, load_config, run_pipeline


def test_generate_playground_creates_expected_structure(tmp_path: Path) -> None:
    target = tmp_path / "playground"

    result = generate_playground(target)

    staging = result["staging"]
    assert (staging / "DCIM" / "Camera").is_dir()
    assert (staging / "DCIM" / "OtherAlbum" / "pic1.jpg").exists()
    assert (staging / "Movies" / "clip1.mp4").exists()
    assert (staging / "Downloads" / "doc1.pdf").exists()
    assert result["config_path"].exists()
    assert result["target"] == target / "target"


def test_generate_playground_camera_files_span_multiple_months(
    tmp_path: Path,
) -> None:
    result = generate_playground(tmp_path / "playground")

    camera = result["staging"] / "DCIM" / "Camera"
    months = {p.name[:6] for p in camera.glob("*.mp4")}

    assert len(months) >= 2


def test_generate_playground_includes_junk_to_be_swept(tmp_path: Path) -> None:
    result = generate_playground(tmp_path / "playground")

    camera = result["staging"] / "DCIM" / "Camera"
    assert (camera / "desktop.ini").exists()
    assert any(camera.glob(".trashed-*"))


def test_generate_playground_refuses_nonempty_dir_without_force(
    tmp_path: Path,
) -> None:
    target = tmp_path / "playground"
    target.mkdir()
    (target / "existing.txt").write_text("keep me")

    with pytest.raises(FileExistsError, match="--force"):
        generate_playground(target)

    # Refusal must not have touched the existing content.
    assert (target / "existing.txt").read_text() == "keep me"


def test_generate_playground_force_overwrites_nonempty_dir(tmp_path: Path) -> None:
    target = tmp_path / "playground"
    target.mkdir()
    (target / "existing.txt").write_text("stale")

    result = generate_playground(target, force=True)

    assert result["config_path"].exists()


def test_generate_playground_config_is_fully_self_contained(tmp_path: Path) -> None:
    target = tmp_path / "playground"

    result = generate_playground(target)

    config = result["config"]
    for key in (
        "staging_root",
        "rename_tool_input",
        "dropbox_camera_uploads",
        "google_mobile_base",
        "desktop_mobile_camera",
    ):
        assert str(target) in config[key], f"{key} escapes the playground directory"
    assert config["dry_run"] is True
    assert config["destination_span_mode"] == "file_date_range"


def test_load_config_reads_an_explicit_path(tmp_path: Path) -> None:
    config_path = tmp_path / "scratch_config.yaml"
    config_path.write_text(yaml.safe_dump({"staging_root": "/somewhere"}))

    cfg = load_config(config_path)

    assert cfg["staging_root"] == "/somewhere"


def test_playground_config_round_trips_through_run_pipeline(tmp_path: Path) -> None:
    """The generator's whole point: its own config should be immediately
    runnable end-to-end, producing a browsable target/ directory."""
    result = generate_playground(tmp_path / "playground")
    cfg = load_config(result["config_path"])
    cfg["dry_run"] = False

    run_pipeline(cfg)

    camera_dest = result["target"].glob("*/Camera/*.mp4")
    assert list(
        camera_dest
    ), "expected renamed camera files in the target Camera folder"
    assert not any((result["staging"] / "DCIM" / "Camera").glob("*.mp4"))
