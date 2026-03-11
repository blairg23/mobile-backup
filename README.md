# mobile-backup

Move your phone’s photos/videos from a desktop **staging area** into a **month-span** Google Drive folder, with:
- file renaming (via your existing tool),
- duplicate-aware moves (no more `_1` junk),
- conflict quarantine,
- junk sweeping (`.trashed*`, `.thumbnails`, `Contents.csv`, `desktop.ini`),
- clean logs,
- progress bars.

## Why this exists

Manual shuffles suck. This script codifies the flow you already do:
1) Drop `DCIM`, `Download`/`Downloads`, `Movies`, `Pictures` from your phone into a staging folder.
2) Rename the camera files by EXIF datetime.
3) Verify the files exist in Dropbox Camera Uploads.
4) Move everything into a Google Drive month folder named like `202509_202510`.

## What it does (the short version)

- **Dedupes by content**: if the same file already exists at the destination → skip and delete the source copy.
- **Merges folders**: no blind renames—existing folder wins; new content merges in.
- **Conflicts**: if names collide but bytes differ → file goes to `_conflicts/`.
- **Sweeps junk**: deletes `.trashed*`, `.thumbnails`, `Contents.csv`, `desktop.ini` along the way.
- **Dry-run first**: prints exactly what would happen, no changes.
- **Logs**: writes a log file so you can see the receipts later.

---

## Requirements

- Python 3.10+
- Poetry (https://python-poetry.org/)
- Your two helper repos/scripts:
  - `rename-images-to-datetime` (exposes `image_renamer.py`)
  - `files-in-folder` (exposes `files_in_folder.py`)
- (Optional) `tqdm` for pretty progress bars.

WSL users: Windows paths like `C:\Users\...` become `/mnt/c/Users/...`.

---

## Install

poetry install
# (optional) pretty progress bars:
poetry add tqdm

## Configure

This repo does not track your real config. Copy the sample and fill in your own paths (no personal info in the repo).

Command: `cp config.example.yaml config.yaml`

`config.example.yaml` (safe template):

Copy to config.yaml and replace all /path/to/... with absolute paths for YOUR machine.

### Staging

where you drop DCIM, Download/Downloads, Movies, Pictures from the phone

staging_root: `/path/to/Desktop/mobile`

### Tools
image_renamer_dir: `/path/to/rename-images-to-datetime`

files_in_folder_dir: `/path/to/files-in-folder`

### Renamer input dir
rename_tool_input: `/path/to/rename-images-to-datetime/input`

### Dropbox camera uploads
dropbox_camera_uploads: `/path/to/Dropbox/Camera Uploads`

### Google Drive "Mobile" base (script writes into `{prev}_{curr}` here)
google_mobile_base: `/path/to/Google Drive/Multimedia/Pictures/Personal/Mobile`

### Optional destination span override
destination_span_override: `null`            # auto month span
destination_span_override: `202601_202603`   # explicit override

### Where Camera files sit after rename (Desktop/mobile/DCIM/Camera)
desktop_mobile_camera: `/path/to/Desktop/mobile/DCIM/Camera`

### Commands for your tools
image_renamer_cmd: [`poetry`, `run`, `python`, `image_renamer.py`]

files_in_folder_cmd: [`poetry`, `run`, `python`, `files_in_folder.py`]

### Defaults
`dry_run: true`      # start safe; prints “would move/delete …” lines
`verbosity: 0`       # 0=quiet, 1=notes (includes deleted-file details in real run), 2=debug

Note: If `destination_span_override` is null/empty, month folder names are automatically computed as `{previous_year}{previous_month}_{current_year}{current_month}` (e.g., `202509_202510`).

---

## Usage

### 1) Dry-run (recommended)

Run: `poetry run python mobile_backup.py`

Expected output (example):
Destination span: `202509_202510` (auto)
Destination: `/path/to/.../Mobile/202509_202510`
Step 5: would delete 14 unwanted; would move 3438 files (skipped 98 dupes, conflicts 2) from /path/to/.../Camera Uploads -> .../Camera
Done. (dry run)

- No changes are made.
- A log file is written:
  - Dry run → in `google_mobile_base/` (won’t create the month folder)
  - Real run → in the month folder (e.g., .../202509_202510/mobile_backup_*.log)

### 2) Real run

Flip `dry_run: false` in `config.yaml`, then run: `poetry run python mobile_backup.py`

You’ll get progress bars and a full log inside the month folder.

### 3) Post-run cleanup / audits

Preview (no changes): `poetry run python cleanup_folder.py 202509_202510`
Apply (fix `*_1` files/dirs; purge junk): `poetry run python cleanup_folder.py 202509_202510 --apply`

What `cleanup_folder.py` does:
- Delete `.trashed*`, `.thumbnails`, `Contents.csv`, `desktop.ini`
- Fix `*_1` files:
  - identical to base → delete `_1`
  - base missing → rename to base
  - different → quarantine to `_conflicts/`
- Fix `*_1` folders:
  - if base missing → rename to base
  - if base exists → merge contents (dedupe identicals, quarantine conflicts), then remove the `_1` dir
- Writes/appends `cleanup_log.txt` in the month folder.

---

## How safe is “safe”?

- We never overwrite existing files.
- If a destination file with the same name exists:
  - Identical content → source is skipped and deleted.
  - Different content → source is moved to `_conflicts/` for manual review.
- Junk is deleted before moves (in dry-run we just count what would be deleted).
- The scripts print counts for:
  - would delete / deleted
  - moved
  - skipped dupes
  - conflicts

---

## Typical staging layout

```
staging_root/
├─ DCIM/
│  ├─ Camera/
│  └─ <other DCIM subfolders>/
├─ Download/ or Downloads/
├─ Movies/
└─ Pictures/
```

You manually drop the phone’s exported folders here (via MTP, Android File Transfer, etc.). The script handles the rest.

---

## Troubleshooting

- WSL paths: Windows paths must be `/mnt/c/...`, `/mnt/d/...`, etc.
- Progress bars: install tqdm with `poetry add tqdm` for pretty bars; otherwise you’ll see periodic “X/N files” lines.
- Conflicts in `_conflicts/`: legit name collisions with different content—review and file them where you want.
- Accidentally created `_1` junk earlier: run the cleaner with `poetry run python cleanup_folder.py 202509_202510 --apply`
- Logs location:
  - Dry run → `google_mobile_base/`
  - Real run → month folder (e.g., .../202509_202510/mobile_backup_*.log)

---

## Development

Install: `poetry install`
Run tests (if/when they exist): `poetry run python -m pytest`

Housekeeping:
- Keep `config.yaml` local (ignored by git).
- Commit only `config.example.yaml`.

---

## License

MIT. See `LICENSE`.
