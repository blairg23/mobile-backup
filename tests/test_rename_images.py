from pathlib import Path

from rename_images import rename_images_in_directory


def test_renames_movie_file_by_filename_datetime(tmp_path: Path) -> None:
    src = tmp_path / "20250615_143022.mp4"
    src.write_bytes(b"fake video content")

    rename_images_in_directory(tmp_path)

    renamed = tmp_path / "2025-06-15 14.30.22.mp4"
    assert renamed.exists()
    assert not src.exists()


def test_collision_gets_numeric_suffix(tmp_path: Path) -> None:
    (tmp_path / "20250615_143022.mp4").write_bytes(b"first")
    (tmp_path / "2025-06-15 14.30.22.mp4").write_bytes(b"already here")

    rename_images_in_directory(tmp_path)

    assert (tmp_path / "2025-06-15 14.30.22.mp4").exists()
    assert (tmp_path / "2025-06-15 14.30.22.1.mp4").exists()


def test_ignores_files_that_do_not_match_expected_formats(tmp_path: Path) -> None:
    stray = tmp_path / "notes.txt"
    stray.write_text("hello")

    rename_images_in_directory(tmp_path)

    assert stray.exists()
