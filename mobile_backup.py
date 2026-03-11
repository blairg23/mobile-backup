#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import date, datetime
import subprocess, shutil, sys, os, yaml, hashlib

# optional pretty progress
try:
    from tqdm import tqdm
    HAVE_TQDM = True
except Exception:
    HAVE_TQDM = False

# ---------- logging ----------
VERBOSITY = 0
class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, data):
        for s in self.streams: s.write(data)
        for s in self.streams: s.flush()
    def flush(self):
        for s in self.streams: s.flush()

def event(msg: str): print(msg, flush=True)
def note(msg: str):  VERBOSITY >= 1 and print(msg, flush=True)
def debug(msg: str): VERBOSITY >= 2 and print(msg, flush=True)

# ---------- junk filter ----------
UNWANTED_EXACT = {"contents.csv", "desktop.ini"}  # case-insensitive
CONFLICTS_DIR_NAME = "_conflicts"

def is_trashed_name(name: str) -> bool:
    return name.startswith(".trashed")

def is_thumbnails_name(name: str) -> bool:
    return name.lower() == ".thumbnails"

def is_unwanted_name(name: str) -> bool:
    # remove .trashed*, .thumbnails, and specific junk files
    return is_trashed_name(name) or is_thumbnails_name(name) or (name.lower() in UNWANTED_EXACT)

# ---------- utils ----------
def month_span() -> str:
    t = date.today()
    prev_y, prev_m = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return f"{prev_y:04d}{prev_m:02d}_{t.year:04d}{t.month:02d}"

def resolve_destination_span(cfg: dict) -> tuple[str, bool]:
    """
    Resolve destination span folder name.
    Returns (span, overridden) where overridden indicates explicit config override.
    """
    override = cfg.get("destination_span_override")
    if override is None:
        return month_span(), False
    if not isinstance(override, str):
        raise ValueError("config.destination_span_override must be a string when set")
    override = override.strip()
    if not override:
        return month_span(), False
    return override, True

def ensure_dir(p: Path, dry: bool) -> None:
    debug(('[dry] ' if dry else '') + f'mkdir -p "{p}"')
    if not dry:
        p.mkdir(parents=True, exist_ok=True)

def run_cmd(cmd: list[str], cwd: Path | None, dry: bool) -> None:
    debug(f'run: {" ".join(cmd)}  (cwd="{cwd if cwd else os.getcwd()}")')
    if dry:
        debug("[dry] skipped")
        return
    rc = subprocess.run(cmd, cwd=str(cwd) if cwd else None).returncode
    if rc != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")

def list_children(p: Path) -> list[Path]:
    return list(p.iterdir()) if p.exists() else []

def has_any_content(p: Path) -> bool:
    return count_files_in_path(p, exclude_trashed=True) > 0

def count_files_in_path(p: Path, *, exclude_trashed: bool = True) -> int:
    """Count regular files under path. If exclude_trashed=True, excludes .trashed*, .thumbnails, Contents.csv, desktop.ini."""
    if not p.exists():
        return 0
    if p.is_file():
        return 0 if (exclude_trashed and is_unwanted_name(p.name)) else 1
    total = 0
    for _root, dirs, files in os.walk(p):
        if exclude_trashed:
            dirs[:]  = [d for d in dirs  if not (is_trashed_name(d) or is_thumbnails_name(d))]
            files    = [f for f in files if not is_unwanted_name(f)]
        total += len(files)
    return total

def count_files_in_children(dir_path: Path, *, exclude_trashed: bool = True, exclude_names: set[str] | None = None) -> int:
    if not dir_path.exists(): return 0
    total = 0
    for it in dir_path.iterdir():
        if exclude_names and it.name in exclude_names: continue
        total += count_files_in_path(it, exclude_trashed=exclude_trashed)
    return total

def count_unwanted_files(root: Path) -> int:
    """How many files would be removed by cleanup_unwanted(root)?"""
    if not root.exists(): return 0
    total = 0
    for cur, dirs, files in os.walk(root, topdown=True):
        del_dirs = [d for d in dirs if is_trashed_name(d) or is_thumbnails_name(d)]
        for d in del_dirs:
            total += count_files_in_path(Path(cur)/d, exclude_trashed=False)
        dirs[:] = [d for d in dirs if d not in del_dirs]
        total += sum(1 for f in files if is_unwanted_name(f))
    return total

def list_unwanted_files(root: Path) -> list[Path]:
    """List regular files that cleanup_unwanted(root) would remove."""
    if not root.exists(): return []
    out: list[Path] = []
    for cur, dirs, files in os.walk(root, topdown=True):
        del_dirs = [d for d in dirs if is_trashed_name(d) or is_thumbnails_name(d)]
        for d in del_dirs:
            dpath = Path(cur) / d
            for r2, _d2, f2 in os.walk(dpath):
                out.extend((Path(r2) / f) for f in f2)
        dirs[:] = [d for d in dirs if d not in del_dirs]
        out.extend((Path(cur) / f) for f in files if is_unwanted_name(f))
    return sorted(out, key=lambda p: str(p))

def delete_path(p: Path, dry: bool) -> int:
    """Delete file/dir; return number of regular files removed under it."""
    removed = count_files_in_path(p, exclude_trashed=False) if p.exists() else 0
    if dry:
        debug(f'[dry] rm -rf "{p}"')
        return removed
    try:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    except Exception:
        pass
    return removed

def cleanup_unwanted(root: Path, dry: bool) -> int:
    """Remove .trashed*, .thumbnails, Contents.csv, desktop.ini; return # files removed."""
    if not root.exists(): return 0
    trashed_dirs: list[Path] = []
    files_to_delete: list[Path] = []
    for cur, dirs, files in os.walk(root, topdown=True):
        del_dirs = [d for d in dirs if is_trashed_name(d) or is_thumbnails_name(d)]
        trashed_dirs += [Path(cur) / d for d in del_dirs]
        dirs[:] = [d for d in dirs if d not in del_dirs]
        for f in files:
            if is_unwanted_name(f):
                files_to_delete.append(Path(cur) / f)
    removed = 0
    for f in files_to_delete:
        removed += delete_path(f, dry)
    for d in trashed_dirs:
        removed += delete_path(d, dry)
    return removed

# ---------- dedupe helpers ----------
def sha256sum(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def files_identical(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
    except FileNotFoundError:
        return False
    if sa.st_size != sb.st_size:
        return False
    return sha256sum(a) == sha256sum(b)

class MoveStats:
    __slots__ = ("moved", "skipped_dupes", "conflicts")
    def __init__(self):
        self.moved = 0
        self.skipped_dupes = 0
        self.conflicts = 0

def ensure_conflicts_dir(dest_root: Path, dry: bool) -> Path:
    cdir = dest_root / CONFLICTS_DIR_NAME
    ensure_dir(cdir, dry)
    return cdir

def dedupe_move_file(src: Path, dest_dir: Path, dry: bool, stats: MoveStats) -> None:
    """Move file with dedupe: skip+delete src if identical, else send differing collisions to _conflicts/."""
    ensure_dir(dest_dir, dry)
    dst = dest_dir / src.name
    if dst.exists():
        if files_identical(src, dst):
            if not dry:
                try: src.unlink()
                except Exception: pass
            stats.skipped_dupes += 1
            return
        cdir = ensure_conflicts_dir(dest_dir, dry)
        target = cdir / src.name
        i = 1
        while target.exists():
            target = cdir / f"{src.stem}_conflict{i}{src.suffix}"
            i += 1
        if not dry:
            shutil.move(str(src), str(target))
        stats.conflicts += 1
        return
    if not dry:
        shutil.move(str(src), str(dst))
    stats.moved += 1

def dedupe_merge_dir(src_dir: Path, dest_dir: Path, dry: bool, stats: MoveStats, update_progress=lambda n: None) -> None:
    ensure_dir(dest_dir, dry)
    for child in list_children(src_dir):
        if is_unwanted_name(child.name):
            delete_path(child, dry)
            continue
        if child.is_file():
            dedupe_move_file(child, dest_dir, dry, stats)
            update_progress(1)
        elif child.is_dir():
            dedupe_merge_dir(child, dest_dir / child.name, dry, stats, update_progress)
    if not dry:
        try: src_dir.rmdir()
        except OSError: pass

# ---------- progress ----------
def progress_start(total_files: int, desc: str, enabled: bool):
    if not enabled or total_files <= 0:
        def _noop(_=0): pass
        return _noop, (lambda: None)
    if HAVE_TQDM:
        bar = tqdm(total=total_files, desc=desc, unit="file", leave=False)
        return bar.update, bar.close
    printed = {"next": 0}
    step = max(1, min(100, total_files // 20))
    moved = {"n": 0}
    def _upd(delta: int):
        moved["n"] += max(0, int(delta))
        if moved["n"] >= printed["next"] or moved["n"] == total_files:
            print(f"{desc}: {moved['n']}/{total_files} files", flush=True)
            printed["next"] = min(total_files, moved["n"] + step)
    def _close():
        if moved["n"] < total_files:
            print(f"{desc}: {moved['n']}/{total_files} files", flush=True)
    return _upd, _close

def dedupe_move_children_with_progress(src_dir: Path, dest_dir: Path, dry: bool, desc: str, total_files: int) -> MoveStats:
    stats = MoveStats()
    update, close = progress_start(total_files, desc, enabled=not dry)
    try:
        for it in list_children(src_dir):
            if is_unwanted_name(it.name):
                delete_path(it, dry)
                continue
            if it.is_file():
                dedupe_move_file(it, dest_dir, dry, stats)
                update(1)
            elif it.is_dir():
                dedupe_merge_dir(it, dest_dir / it.name, dry, stats, update_progress=update)
    finally:
        close()
    return stats

def moved_phrase(n: int, dry: bool) -> str:
    return f'{"would move" if dry else "moved"} {n} file{"s" if n != 1 else ""}'

def print_step6_unwanted_details(
    dry: bool,
    unwanted_groups: list[tuple[str, list[Path]]],
) -> None:
    emit = event if dry else note
    if dry:
        emit("  Step 6 details: source files that would be deleted before transfer (not destination files)")
    else:
        emit("  Step 6 details: source files deleted before transfer (not destination files)")

    any_lines = False

    for source, files in unwanted_groups:
        if not files:
            continue
        any_lines = True
        emit(f"    {source}:")
        for p in files:
            emit(f"      - {p}")

    if not any_lines:
        emit("    (none)")

def print_step_unwanted_details(
    step_label: str,
    dry: bool,
    source_label: str,
    files: list[Path],
) -> None:
    emit = event if dry else note
    if not files:
        return
    if dry:
        emit(f"  {step_label} details: source files that would be deleted before transfer (not destination files)")
    else:
        emit(f"  {step_label} details: source files deleted before transfer (not destination files)")
    emit(f"    {source_label}:")
    for p in files:
        emit(f"      - {p}")

# ---------- main ----------
def main():
    global VERBOSITY
    here = Path(__file__).resolve().parent
    cfg = yaml.safe_load((here / "config.yaml").read_text(encoding="utf-8"))

    VERBOSITY = int(cfg.get("verbosity", 0))
    DRY_RUN   = bool(cfg.get("dry_run", True))
    SHOW_DELETED_FILE_DETAILS = DRY_RUN or (VERBOSITY >= 1)

    # Config (using your alias dirs)
    STAGING             = Path(cfg["staging_root"])  # /mnt/c/Users/Neophile/Desktop/mobile
    IMAGE_RENAMER_DIR   = Path(cfg["image_renamer_dir"])
    FILES_IN_FOLDER_DIR = Path(cfg["files_in_folder_dir"])
    RENAME_IN           = Path(cfg["rename_tool_input"])
    DROPBOX_CU          = Path(cfg["dropbox_camera_uploads"])
    GDRIVE_BASE         = Path(cfg["google_mobile_base"])
    DESKTOP_CAM         = Path(cfg["desktop_mobile_camera"])
    IMG_CMD             = list(cfg["image_renamer_cmd"])
    FIF_CMD             = list(cfg["files_in_folder_cmd"])

    # Staging subdirs
    P_DCIM      = STAGING / "DCIM"
    P_DOWNLOAD  = STAGING / "Download"
    P_MOVIES    = STAGING / "Movies"
    P_PICTURES  = STAGING / "Pictures"

    # Destinations
    span, span_overridden = resolve_destination_span(cfg)
    dest_root     = GDRIVE_BASE / span
    dest_camera   = dest_root / "Camera"
    dest_pictures = dest_root / "Pictures"
    dest_movies   = dest_root / "Movies"

    # --- Logging location depends on DRY_RUN ---
    # dry run -> log alongside base (do NOT create month folder)
    # real run -> ensure month folder exists and log inside it
    if DRY_RUN:
        GDRIVE_BASE.mkdir(parents=True, exist_ok=True)
        log_dir = GDRIVE_BASE
    else:
        dest_root.mkdir(parents=True, exist_ok=True)
        log_dir = dest_root
    log_path = log_dir / f"mobile_backup_{span}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    with log_path.open("w", encoding="utf-8") as lf:
        sys.stdout = Tee(sys.__stdout__, lf)
        sys.stderr = Tee(sys.__stderr__, lf)

        if not DRY_RUN:
            ensure_dir(dest_camera, DRY_RUN)
            ensure_dir(dest_pictures, DRY_RUN)
            ensure_dir(dest_movies, DRY_RUN)

        if span_overridden:
            event(f'Destination span override: "{span}"')
        else:
            event(f'Destination span: "{span}" (auto)')
        event(f'Log: {log_path}')
        event(f'Destination: "{dest_root}"')

        # --- Step 1: DCIM/Camera/* -> RENAME_IN ---
        src_camera = P_DCIM / "Camera"
        unwanted1 = list_unwanted_files(src_camera) if SHOW_DELETED_FILE_DETAILS else []
        del1 = len(unwanted1) if DRY_RUN else cleanup_unwanted(src_camera, False)
        n1  = count_files_in_children(src_camera, exclude_trashed=True)
        ensure_dir(RENAME_IN, DRY_RUN)
        s1 = dedupe_move_children_with_progress(src_camera, RENAME_IN, DRY_RUN, desc="Step 1 transfer", total_files=n1)
        event(f"Step 1: {'would delete' if DRY_RUN else 'deleted'} {del1} unwanted; {moved_phrase(n1, DRY_RUN)} "
              f"(skipped {s1.skipped_dupes} dupes, conflicts {s1.conflicts}) from {src_camera} -> {RENAME_IN}")
        if SHOW_DELETED_FILE_DETAILS:
            print_step_unwanted_details("Step 1", DRY_RUN, str(src_camera), unwanted1)
        event("")

        # --- Step 2: run image_renamer.py ---
        run_cmd(IMG_CMD, cwd=IMAGE_RENAMER_DIR, dry=DRY_RUN)
        event("Step 2: image_renamer.py " + ("would run" if DRY_RUN else "ran"))
        event("")

        # --- Step 3: RENAME_IN/* -> Desktop/mobile/Camera ---
        unwanted3 = list_unwanted_files(RENAME_IN) if SHOW_DELETED_FILE_DETAILS else []
        del3 = len(unwanted3) if DRY_RUN else cleanup_unwanted(RENAME_IN, False)
        n3  = count_files_in_children(RENAME_IN, exclude_trashed=True)
        s3 = dedupe_move_children_with_progress(RENAME_IN, DESKTOP_CAM, DRY_RUN, desc="Step 3 transfer", total_files=n3)
        event(f"Step 3: {'would delete' if DRY_RUN else 'deleted'} {del3} unwanted; {moved_phrase(n3, DRY_RUN)} "
              f"(skipped {s3.skipped_dupes} dupes, conflicts {s3.conflicts}) from {RENAME_IN} -> {DESKTOP_CAM}")
        if SHOW_DELETED_FILE_DETAILS:
            print_step_unwanted_details("Step 3", DRY_RUN, str(RENAME_IN), unwanted3)
        event("")

        # --- Step 4: run files_in_folder.py ---
        run_cmd(FIF_CMD, cwd=FILES_IN_FOLDER_DIR, dry=DRY_RUN)
        event("Step 4: files_in_folder.py " + ("would run" if DRY_RUN else "ran"))
        event("")

        # --- Step 5: Dropbox/Camera Uploads/* -> dest Camera ---
        dropbox_cu = Path(DROPBOX_CU)
        unwanted5 = list_unwanted_files(dropbox_cu) if SHOW_DELETED_FILE_DETAILS else []
        del5 = len(unwanted5) if DRY_RUN else cleanup_unwanted(dropbox_cu, False)
        n5  = count_files_in_children(dropbox_cu, exclude_trashed=True)
        s5 = dedupe_move_children_with_progress(dropbox_cu, dest_camera, DRY_RUN, desc="Step 5 transfer", total_files=n5)
        event(f"Step 5: {'would delete' if DRY_RUN else 'deleted'} {del5} unwanted; {moved_phrase(n5, DRY_RUN)} "
              f"(skipped {s5.skipped_dupes} dupes, conflicts {s5.conflicts}) from {DROPBOX_CU} -> {dest_camera}")
        if SHOW_DELETED_FILE_DETAILS:
            print_step_unwanted_details("Step 5", DRY_RUN, str(dropbox_cu), unwanted5)
        event("")

        # --- Step 6: Pictures aggregation ---
        # 6a DCIM extras
        dcim_extras = [c for c in list_children(P_DCIM) if c.name != "Camera" and count_files_in_path(c, exclude_trashed=True) > 0]
        unwanted6a: list[tuple[str, list[Path]]] = []
        if SHOW_DELETED_FILE_DETAILS:
            unwanted6a = [(f"DCIM/{c.name}", list_unwanted_files(c)) for c in dcim_extras]
        if DRY_RUN:
            del6a = sum(len(files) for _src, files in unwanted6a)
        else:
            del6a = sum(cleanup_unwanted(c, False) for c in dcim_extras)
        n6a   = sum(count_files_in_path(c, exclude_trashed=True) for c in dcim_extras)

        s6a = MoveStats()
        upd, close = progress_start(n6a, "Step 6 transfer (DCIM extras)", enabled=not DRY_RUN)
        try:
            for c in dcim_extras:
                dedupe_merge_dir(c, dest_pictures / c.name, DRY_RUN, s6a, update_progress=upd)
        finally:
            close()

        # 6b Pictures/*
        unwanted6b = list_unwanted_files(P_PICTURES) if SHOW_DELETED_FILE_DETAILS else []
        del6b = len(unwanted6b) if DRY_RUN else cleanup_unwanted(P_PICTURES, False)
        n6b   = count_files_in_children(P_PICTURES, exclude_trashed=True)
        s6b   = dedupe_move_children_with_progress(P_PICTURES, dest_pictures, DRY_RUN, desc="Step 6 transfer (Pictures)", total_files=n6b)

        # 6c Download/*
        unwanted6c = list_unwanted_files(P_DOWNLOAD) if SHOW_DELETED_FILE_DETAILS else []
        del6c = len(unwanted6c) if DRY_RUN else cleanup_unwanted(P_DOWNLOAD, False)
        n6c   = count_files_in_children(P_DOWNLOAD, exclude_trashed=True)
        s6c   = dedupe_move_children_with_progress(P_DOWNLOAD, dest_pictures, DRY_RUN, desc="Step 6 transfer (Download)", total_files=n6c)

        total_del6 = del6a + del6b + del6c
        total_skip6 = s6a.skipped_dupes + s6b.skipped_dupes + s6c.skipped_dupes
        total_conf6 = s6a.conflicts + s6b.conflicts + s6c.conflicts
        event(
            f"Step 6: {'would delete' if DRY_RUN else 'deleted'} {total_del6} unwanted in source staging folders; "
            f"{'would move' if DRY_RUN else 'moved'} {n6a + n6b + n6c} files "
            f"(skipped {total_skip6} dupes, conflicts {total_conf6}) to {dest_pictures}"
        )
        if SHOW_DELETED_FILE_DETAILS and total_del6 > 0:
            unwanted_groups = unwanted6a + [("Pictures", unwanted6b), ("Download", unwanted6c)]
            print_step6_unwanted_details(
                DRY_RUN,
                unwanted_groups,
            )
        event("")

        # --- Step 7: Movies/* -> dest_movies ---
        unwanted7 = list_unwanted_files(P_MOVIES) if SHOW_DELETED_FILE_DETAILS else []
        del7 = len(unwanted7) if DRY_RUN else cleanup_unwanted(P_MOVIES, False)
        n7   = count_files_in_children(P_MOVIES, exclude_trashed=True)
        s7   = dedupe_move_children_with_progress(P_MOVIES, dest_movies, DRY_RUN, desc="Step 7 transfer (Movies)", total_files=n7)
        event(f"Step 7: {'would delete' if DRY_RUN else 'deleted'} {del7} unwanted; {moved_phrase(n7, DRY_RUN)} "
              f"(skipped {s7.skipped_dupes} dupes, conflicts {s7.conflicts}) from {P_MOVIES} -> {dest_movies}")
        if SHOW_DELETED_FILE_DETAILS:
            print_step_unwanted_details("Step 7", DRY_RUN, str(P_MOVIES), unwanted7)
        event("")

        event("Done." + (" (dry run)" if DRY_RUN else ""))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted"); sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}"); sys.exit(1)
