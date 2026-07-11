#!/usr/bin/env python3
"""Verify that every file in one folder also exists (by content hash) in another,
optionally copying over whatever's missing.

Ported from files-in-folder's FilesInFolder class so mobile-backup can call it
in-process, driven by real config paths instead of the hardcoded example paths
that used to live in that repo's __main__ block.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil

# Filenames we don't want to check:
PROTECTED_FILENAMES = ["contents.csv", "missing.txt"]


class FilesInFolder:
    def __init__(
        self,
        left_folder=None,
        right_folder=None,
        write_mode=None,
        reference_side="left",
        hash_algorithm="md5",
        hash_type="contents",
        contents_filename="contents.json",
        missing_files_filename="missing.txt",
        fix_missing_files=False,
        verbose=False,
    ):
        self.verbose = verbose
        self.action_counter = 0
        # Which side is the reference/source folder whose contents must exist in the other.
        # Valid values: "left" (default) or "right"
        self.reference_side = reference_side
        self.write_mode = write_mode
        self.hash_algorithm = hash_algorithm
        self.hash_type = hash_type
        self.left_folder = left_folder
        self.right_folder = right_folder
        self.contents_filename = contents_filename
        self.missing_files_filename = missing_files_filename
        self.fix_missing_files = fix_missing_files

        try:
            if (
                self.left_folder is None
                or self.right_folder is None
                or not os.path.exists(self.left_folder)
                or not os.path.exists(self.right_folder)
            ):
                raise IOError(
                    "[ERROR] Please provide valid right and left directories."
                )
            print(f"[{self.action_counter}] Left Directory: {self.left_folder}")
            print(f"[{self.action_counter}] Right Directory: {self.right_folder}")
            print("\n")
        except Exception as e:
            print(e)

    def find_filenames(self, directory=None):
        """Finds all the filenames in a given directory."""
        filenames = []
        try:
            if directory is None or not os.path.exists(directory):
                raise IOError("[ERROR] Please provide a valid directory to search.")
            if self.verbose:
                print(f"[{self.action_counter}] Finding files in {directory}.\n")
            filenames = [
                f
                for f in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, f))
            ]
            self.action_counter += 1
        except Exception as e:
            print(e)
        return filenames

    def hash_file_contents(self, filepath=None, hash_algorithm="md5"):
        """Uses given hashing algorithm to hash the binary file, given a full filepath."""
        blocksize = 65536
        hash_value = 0x666
        try:
            if self.verbose:
                print(f"[{self.action_counter}] Hashing file contents of {filepath}.\n")
            if filepath is None or not os.path.exists(filepath):
                raise IOError("[ERROR] Please provide a valid filepath to hash.")
            with open(filepath, "rb") as infile:
                h = hashlib.new(hash_algorithm)
                buf = infile.read(blocksize)
                while len(buf) > 0:
                    h.update(buf)
                    buf = infile.read(blocksize)
            hash_value = h.hexdigest()
        except Exception as e:
            print(e)
        return hash_value

    def hash_filename(self, filename=None, hash_algorithm="md5"):
        """Uses given hashing algorithm to hash the given filename."""
        hash_value = 0x666
        try:
            if self.verbose:
                print(f"[{self.action_counter}] Hashing filename {filename}.\n")
            if filename is None:
                raise IOError("[ERROR] Please provide a filename to hash.")
            h = hashlib.new(hash_algorithm)
            h.update(filename)
            hash_value = h.hexdigest()
        except Exception as e:
            print(e)
        return hash_value

    def get_hashes(self, directory=None, hash_algorithm="md5", hash_type="contents"):
        """Populate a dictionary with filename:hash_value pairs for a directory."""
        hashlist = {"headers": ["hash_value", "filepath"]}
        try:
            if directory is None or not os.path.exists(directory):
                raise IOError("[ERROR] Please provide a valid directory to hash.")
            filenames = self.find_filenames(directory=directory)
            for filename in filenames:
                if filename not in PROTECTED_FILENAMES:
                    filepath = os.path.join(directory, filename)
                    if hash_type == "contents":
                        hash_value = self.hash_file_contents(
                            filepath=filepath, hash_algorithm=hash_algorithm
                        )
                    elif hash_type == "filenames":
                        hash_value = self.hash_filename(
                            filename=filename, hash_algorithm=hash_algorithm
                        )
                    hashlist[str(hash_value)] = str(filepath)
                    self.action_counter += 1
        except Exception as e:
            print(e)
        return hashlist

    def write_dictionary_contents(
        self, dictionary_contents=None, write_mode=None, contents_filepath=None
    ):
        """Writes contents of a given dictionary, using the specified write mode (JSON or CSV)."""
        valid_write_modes = ["json", "csv"]
        try:
            if not dictionary_contents:
                raise Exception(
                    "[ERROR] Need to provide a valid dictionary with contents."
                )
            if write_mode is None or write_mode.lower() not in valid_write_modes:
                raise Exception(
                    f"[ERROR] Need to provide a write mode from: {valid_write_modes}"
                )
            if contents_filepath is None:
                raise Exception(
                    "[ERROR] Need to provide a valid file to write contents."
                )
            with open(contents_filepath, "a+") as outfile:
                if write_mode.lower() == "json":
                    json.dump(dictionary_contents, outfile)
                else:
                    headers = ",".join(dictionary_contents["headers"])
                    outfile.write(headers + "\n")
                    for key, value in dictionary_contents.items():
                        if key != "headers":
                            outfile.write(key + "," + value + "\n")
        except Exception as e:
            print(e)

    def compare_hash_lists(self, left_hash_dict=None, right_hash_dict=None):
        """Return the filepaths from left_hash_dict whose hash is missing from right_hash_dict."""
        missing_hash_value_filepaths = []
        for hash_value, filepath in left_hash_dict.items():
            if hash_value == "headers":
                continue
            if hash_value not in right_hash_dict.keys():
                missing_hash_value_filepaths.append(filepath)
        return missing_hash_value_filepaths

    def write_list_contents(self, list_contents=None, missing_files_filepath=None):
        """Writes contents of a given list to a file."""
        try:
            if not list_contents:
                raise Exception("[ERROR] Need to provide a valid list with contents.")
            with open(missing_files_filepath, "a+") as outfile:
                for value in list_contents:
                    outfile.write(value + "\n")
        except Exception as e:
            print(e)

    def write_missing_files(self, missing_filepaths=None, destination_directory=None):
        """Writes missing files to the destination directory.

        A destination path that already exists (but under a different hash --
        that's why the source file is "missing" in the first place) is never
        overwritten; the source is quarantined into a _conflicts/ subdirectory
        instead, matching how the rest of the pipeline handles name collisions.

        Returns (copied, conflicts, errors): lists of source filepaths.
        """
        copied: list[str] = []
        conflicts: list[str] = []
        errors: list[str] = []
        if not missing_filepaths:
            print("[ERROR] Need to provide a valid list of missing files.")
            return copied, conflicts, errors
        for missing_filepath in missing_filepaths:
            missing_filename = os.path.basename(missing_filepath)
            destination_filepath = os.path.join(destination_directory, missing_filename)
            try:
                if os.path.exists(destination_filepath):
                    conflicts_dir = os.path.join(destination_directory, "_conflicts")
                    os.makedirs(conflicts_dir, exist_ok=True)
                    stem, ext = os.path.splitext(missing_filename)
                    target = os.path.join(conflicts_dir, missing_filename)
                    i = 1
                    while os.path.exists(target):
                        target = os.path.join(conflicts_dir, f"{stem}_conflict{i}{ext}")
                        i += 1
                    # Use copy2 to retain metadata such as creation and modification times
                    shutil.copy2(missing_filepath, target)
                    conflicts.append(missing_filepath)
                else:
                    shutil.copy2(missing_filepath, destination_filepath)
                    copied.append(missing_filepath)
            except Exception as e:
                print(e)
                errors.append(missing_filepath)
        return copied, conflicts, errors

    def cleanup(self):
        """Cleans up metadata files like contents.csv and missing.txt."""
        self.action_counter += 1
        for filename in PROTECTED_FILENAMES:
            left_file_to_delete = os.path.join(self.left_folder, filename)
            right_file_to_delete = os.path.join(self.right_folder, filename)

            if os.path.exists(left_file_to_delete):
                if self.verbose:
                    print(f"[{self.action_counter}] Deleting {left_file_to_delete}.\n")
                os.remove(left_file_to_delete)
                self.action_counter += 1

            if os.path.exists(right_file_to_delete):
                if self.verbose:
                    print(f"[{self.action_counter}] Deleting {right_file_to_delete}.\n")
                os.remove(right_file_to_delete)
                self.action_counter += 1

    def move_files_to_folder(self, folder_name):
        """Moves all found files to a new folder."""
        left_hash_dict = self.get_hashes(
            directory=self.left_folder,
            hash_algorithm=self.hash_algorithm,
            hash_type=self.hash_type,
        )
        right_hash_dict = self.get_hashes(
            directory=self.right_folder,
            hash_algorithm=self.hash_algorithm,
            hash_type=self.hash_type,
        )
        missing_hash_value_filepaths = self.compare_hash_lists(
            left_hash_dict=left_hash_dict, right_hash_dict=right_hash_dict
        )

        for hash_value, left_filepath in list(left_hash_dict.items())[1:]:
            right_filepath = right_hash_dict.get(hash_value)
            if left_filepath not in missing_hash_value_filepaths:
                destination_filepath = os.path.join(self.right_folder, folder_name)
                self.action_counter += 1
                print(
                    f"[{self.action_counter}] Moving {right_filepath} to {destination_filepath}.\n"
                )
                if not os.path.exists(destination_filepath):
                    self.action_counter += 1
                    print(
                        f"[{self.action_counter}] {destination_filepath} does not exist, creating.\n"
                    )
                    os.makedirs(destination_filepath)
                shutil.move(right_filepath, destination_filepath)

    def run(self):
        """Runs all the required functions to check whether two folders have identical content."""
        reran_after_copy = (
            False  # Prevent infinite recursion when fix_missing_files is True
        )

        while True:
            left_hash_dict = self.get_hashes(
                directory=self.left_folder,
                hash_algorithm=self.hash_algorithm,
                hash_type=self.hash_type,
            )
            right_hash_dict = self.get_hashes(
                directory=self.right_folder,
                hash_algorithm=self.hash_algorithm,
                hash_type=self.hash_type,
            )

            if str(self.reference_side).lower() == "right":
                source_hashes, target_hashes = right_hash_dict, left_hash_dict
                source_dir, target_dir = self.right_folder, self.left_folder
            else:
                source_hashes, target_hashes = left_hash_dict, right_hash_dict
                source_dir, target_dir = self.left_folder, self.right_folder

            missing_hash_value_filepaths = self.compare_hash_lists(
                left_hash_dict=source_hashes, right_hash_dict=target_hashes
            )

            if self.write_mode is not None:
                if len(missing_hash_value_filepaths) == 0:
                    print(f"All files from {source_dir} exist in {target_dir}.")
                    print("Left Folder:", self.left_folder)
                    print("Right Folder:", self.right_folder)
                    print("\n")

                    left_outfilepath = os.path.join(
                        self.left_folder, self.contents_filename
                    )
                    self.write_dictionary_contents(
                        dictionary_contents=left_hash_dict,
                        write_mode=self.write_mode,
                        contents_filepath=left_outfilepath,
                    )
                    self.action_counter += 1

                    right_outfilepath = os.path.join(
                        self.right_folder, self.contents_filename
                    )
                    self.write_dictionary_contents(
                        dictionary_contents=right_hash_dict,
                        write_mode=self.write_mode,
                        contents_filepath=right_outfilepath,
                    )
                    self.action_counter += 1
                else:
                    missing_files_filepath = os.path.join(
                        target_dir, self.missing_files_filename
                    )
                    self.write_list_contents(
                        list_contents=missing_hash_value_filepaths,
                        missing_files_filepath=missing_files_filepath,
                    )
                    self.action_counter += 1

                    if self.fix_missing_files and not reran_after_copy:
                        _copied, _conflicts, errors = self.write_missing_files(
                            missing_filepaths=missing_hash_value_filepaths,
                            destination_directory=target_dir,
                        )
                        self.action_counter += 1
                        if errors:
                            raise RuntimeError(
                                f"Failed to sync {len(errors)} file(s) to {target_dir}: {errors}"
                            )
                        self.cleanup()
                        reran_after_copy = True
                        continue  # Re-run the check once after copying files
            else:
                print("Files missing from left folder that exist in right folder:")
                print(missing_hash_value_filepaths)

            break


def verify_and_sync(left_folder, right_folder, *, verbose=False) -> FilesInFolder:
    """Verify left_folder's contents exist in right_folder, copying over anything missing."""
    checker = FilesInFolder(
        left_folder=str(left_folder),
        right_folder=str(right_folder),
        write_mode="csv",
        reference_side="left",
        hash_algorithm="md5",
        hash_type="contents",
        contents_filename="contents.csv",
        missing_files_filename="missing.txt",
        fix_missing_files=True,
        verbose=verbose,
    )
    checker.run()
    return checker
