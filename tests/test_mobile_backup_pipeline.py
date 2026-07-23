"""End-to-end tests for mobile_backup.run_pipeline().

Everything here operates on synthetic directories under pytest's tmp_path
fixture -- never a real staging/Dropbox/Google Drive directory -- so the full
7-step pipeline can be exercised with confidence before ever pointing it at
real data.
"""

from pathlib import Path

from mobile_backup import run_pipeline

SPAN = "TESTSPAN"


def _base_cfg(tmp_path: Path, *, dry_run: bool) -> dict[str, object]:
    root = tmp_path
    cfg: dict[str, object] = {
        "staging_root": str(root / "staging"),
        "rename_tool_input": str(root / "rename_tool_input"),
        "dropbox_camera_uploads": str(root / "dropbox_camera_uploads"),
        "google_mobile_base": str(root / "google_mobile_base"),
        "desktop_mobile_camera": str(root / "desktop_mobile_camera"),
        "destination_span_override": SPAN,
        "dry_run": dry_run,
        "verbosity": 0,
        "write_run_summary_json": False,
        "audit_detail_level": "summary",
    }
    for key in (
        "staging_root",
        "rename_tool_input",
        "dropbox_camera_uploads",
        "desktop_mobile_camera",
    ):
        Path(str(cfg[key])).mkdir(parents=True, exist_ok=True)
    (Path(str(cfg["staging_root"])) / "DCIM" / "Camera").mkdir(
        parents=True, exist_ok=True
    )
    (Path(str(cfg["staging_root"])) / "Movies").mkdir(parents=True, exist_ok=True)
    return cfg


def _dest_root(cfg: dict[str, object]) -> Path:
    return Path(str(cfg["google_mobile_base"])) / SPAN


def _p(cfg: dict[str, object], key: str) -> Path:
    return Path(str(cfg[key]))


def test_dry_run_makes_no_filesystem_changes(tmp_path: Path) -> None:
    cfg = _base_cfg(tmp_path, dry_run=True)
    camera_src = _p(cfg, "staging_root") / "DCIM" / "Camera" / "20260101_120000.mp4"
    camera_src.write_bytes(b"camera1")
    movie_src = _p(cfg, "staging_root") / "Movies" / "movie1.mp4"
    movie_src.write_bytes(b"movie1")

    run_pipeline(cfg)

    # Nothing moved out of staging.
    assert camera_src.exists()
    assert movie_src.exists()
    # Nothing landed anywhere downstream.
    assert not any(_p(cfg, "rename_tool_input").iterdir())
    assert not any(_p(cfg, "desktop_mobile_camera").iterdir())
    # Dry run never creates the month-span destination folder.
    assert not _dest_root(cfg).exists()


def test_real_run_routes_camera_file_through_full_pipeline(tmp_path: Path) -> None:
    cfg = _base_cfg(tmp_path, dry_run=False)
    camera_src = _p(cfg, "staging_root") / "DCIM" / "Camera" / "20260101_120000.mp4"
    camera_src.write_bytes(b"camera1")

    run_pipeline(cfg)

    renamed_name = "2026-01-01 12.00.00.mp4"
    # Step 1-2-3: staging camera file renamed and staged in the local mirror.
    assert not camera_src.exists()
    assert not (_p(cfg, "rename_tool_input") / "20260101_120000.mp4").exists()
    mirror_file = _p(cfg, "desktop_mobile_camera") / renamed_name
    assert mirror_file.exists()
    assert mirror_file.read_bytes() == b"camera1"
    # Step 4-5: copied into Dropbox inbox, then moved on into the archive.
    assert not (_p(cfg, "dropbox_camera_uploads") / renamed_name).exists()
    archived_file = _dest_root(cfg) / "Camera" / renamed_name
    assert archived_file.exists()
    assert archived_file.read_bytes() == b"camera1"


def test_dedupe_skips_identical_file_and_deletes_source(tmp_path: Path) -> None:
    cfg = _base_cfg(tmp_path, dry_run=False)
    dest_movies = _dest_root(cfg) / "Movies"
    dest_movies.mkdir(parents=True)
    (dest_movies / "same.mp4").write_bytes(b"identical bytes")
    src = _p(cfg, "staging_root") / "Movies" / "same.mp4"
    src.write_bytes(b"identical bytes")

    run_pipeline(cfg)

    # Identical content: source removed, destination untouched, no conflict quarantine.
    assert not src.exists()
    assert (dest_movies / "same.mp4").read_bytes() == b"identical bytes"
    assert not (dest_movies / "_conflicts").exists()


def test_conflict_quarantines_differing_same_name_file(tmp_path: Path) -> None:
    cfg = _base_cfg(tmp_path, dry_run=False)
    dest_movies = _dest_root(cfg) / "Movies"
    dest_movies.mkdir(parents=True)
    (dest_movies / "collide.mp4").write_bytes(b"original bytes")
    src = _p(cfg, "staging_root") / "Movies" / "collide.mp4"
    src.write_bytes(b"different bytes")

    run_pipeline(cfg)

    # Existing destination file is never overwritten...
    assert (dest_movies / "collide.mp4").read_bytes() == b"original bytes"
    # ...the differing source is quarantined instead of silently dropped or lost.
    assert (
        dest_movies / "_conflicts" / "collide.mp4"
    ).read_bytes() == b"different bytes"
    assert not src.exists()


def test_junk_sweep_removes_trashed_and_desktop_ini(tmp_path: Path) -> None:
    cfg = _base_cfg(tmp_path, dry_run=False)
    camera_dir = _p(cfg, "staging_root") / "DCIM" / "Camera"
    (camera_dir / "desktop.ini").write_bytes(b"junk")
    trashed_dir = camera_dir / ".trashed-1234"
    trashed_dir.mkdir()
    (trashed_dir / "deleted.jpg").write_bytes(b"junk")

    run_pipeline(cfg)

    # Junk never reaches any destination.
    assert not list(_p(cfg, "desktop_mobile_camera").glob("desktop.ini"))
    assert not list(_dest_root(cfg).glob("**/desktop.ini"))
    assert not list(_dest_root(cfg).glob("**/.trashed*"))


def test_step6_catch_all_routes_non_camera_staging_dirs_to_pictures(
    tmp_path: Path,
) -> None:
    cfg = _base_cfg(tmp_path, dry_run=False)
    other_album = _p(cfg, "staging_root") / "DCIM" / "OtherAlbum"
    other_album.mkdir(parents=True)
    (other_album / "pic1.jpg").write_bytes(b"pic1")

    downloads = _p(cfg, "staging_root") / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "doc1.txt").write_bytes(b"doc1")

    run_pipeline(cfg)

    dest_pictures = _dest_root(cfg) / "Pictures"
    # DCIM/<non-Camera subdir> -> Pictures/<subdir-name> (DCIM/ prefix dropped).
    assert (dest_pictures / "OtherAlbum" / "pic1.jpg").read_bytes() == b"pic1"
    # Any other top-level staging dir -> Pictures/<dir-name>.
    assert (dest_pictures / "Downloads" / "doc1.txt").read_bytes() == b"doc1"
    assert not other_album.exists() or not any(other_album.iterdir())
    assert not downloads.exists() or not any(downloads.iterdir())
