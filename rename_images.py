#!/usr/bin/env python3
"""Rename photos/videos in a directory to their EXIF/file-name datetime.

Ported from rename-images-to-datetime's image_renamer.py so mobile-backup
can call it in-process instead of shelling out to a sibling repo.
"""
from __future__ import annotations

import datetime
import glob
import os
from pathlib import Path

import exifread
from PIL.ExifTags import GPSTAGS

FROM_DATETIME_FORMAT = "%Y%m%d_%H%M%S"
TO_DATETIME_FORMAT = "%Y-%m-%d %H.%M.%S"  # Dropbox Camera Uploads naming format

IMAGE_FILE_FORMATS = ["*.JPG", "*.jpg", "*.png", "*.dng", "*.NEF"]
MOVIE_FILE_FORMATS = ["*.mp4", "*.mov"]


class ExifReadWorker:
    def __init__(self, filepath: str, debug: bool = False):
        self.filepath = filepath
        self.exif_data = self.get_exif_data()
        self.date = self.get_date_time(debug=debug)

    def get_exif_data(self) -> dict[str, object]:
        exif_data: dict[str, object] = {}
        with open(self.filepath, "rb") as infile:
            tags = exifread.process_file(infile)
            for tag, value in tags.items():
                # exifread already yields human-readable string tag names (unlike
                # PIL's numeric EXIF tag ids), so there's no TAGS mapping to apply here.
                decoded = tag
                if decoded == "GPSInfo":
                    gps_data = {}
                    for t in value:
                        sub_decoded = GPSTAGS.get(t, t)
                        gps_data[sub_decoded] = value[t]
                    exif_data[decoded] = gps_data
                else:
                    exif_data[decoded] = str(value)
        return exif_data

    def get_date_time(
        self, datetime_key: str = "Image DateTime", debug: bool = False
    ) -> datetime.datetime | None:
        if datetime_key not in self.exif_data:
            if debug:
                print("DateTime not found...")
            return None
        date_and_time = str(self.exif_data[datetime_key])
        # For those weird cases where midnight is portrayed as 24:00:00 instead of 00:00:00
        date_and_time = date_and_time.replace(" 24:", " 00:")
        return datetime.datetime.strptime(date_and_time, "%Y:%m:%d %H:%M:%S")


def rename_images_in_directory(input_dir: Path, debug: bool = False) -> None:
    """Rename every image/movie file in input_dir to its EXIF/filename datetime."""
    for file_format in IMAGE_FILE_FORMATS + MOVIE_FILE_FORMATS:
        glob_path = os.path.join(input_dir, file_format)
        filepaths = glob.glob(glob_path)

        for filepath in filepaths:
            filename, extension = os.path.splitext(filepath)
            filename = os.path.basename(filename)

            try:
                if f"*{extension}" in IMAGE_FILE_FORMATS:
                    image = ExifReadWorker(filepath, debug=debug)
                    date_taken = image.date
                else:
                    date_taken = None

                if date_taken is None:
                    date_taken = datetime.datetime.strptime(
                        filename, FROM_DATETIME_FORMAT
                    )

                new_filename = date_taken.strftime(TO_DATETIME_FORMAT)
                new_filepath = os.path.join(input_dir, new_filename + extension)

                number = 0
                filepath_before_renaming = new_filepath
                file_does_exist = os.path.isfile(new_filepath)
                if file_does_exist:
                    while os.path.isfile(new_filepath):
                        number += 1
                        new_new_filename = new_filename + "." + str(number)
                        new_filepath = os.path.join(
                            input_dir, new_new_filename + extension
                        )

                    os.rename(filepath, new_filepath)

                    file_still_exists = os.path.isfile(filepath_before_renaming)
                    if not file_still_exists:
                        # This is caused by rerunning this script on files that have
                        # already been renamed -- revert the rename.
                        os.rename(new_filepath, filepath_before_renaming)
                else:
                    os.rename(filepath, new_filepath)

            except Exception as e:
                print(f"filename: {filename}")
                print(e)


if __name__ == "__main__":
    rename_images_in_directory(Path(os.getcwd()) / "input", debug=False)
