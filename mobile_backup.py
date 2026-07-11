#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from datetime import date, datetime
import shutil
import sys
import os
import yaml
import hashlib
from backup_utils import LogTee
from rename_images import rename_images_in_directory
from organize_files import verify_and_sync

# optional pretty progress
try:
    from tqdm import tqdm

    HAVE_TQDM = True
except Exception:
    HAVE_TQDM = False

# ---------- logging ----------
VERBOSITY = 0
AUDIT_LEVEL = "summary"  # "summary" | "deletions" | "actions"
AUDIT_ROOT: Path | None = None


def event(msg: str):
    print(msg, flush=True)


def note(msg: str):
    VERBOSITY >= 1 and print(msg, flush=True)


def debug(msg: str):
    VERBOSITY >= 2 and print(msg, flush=True)


def _rel(p: Path) -> str:
    if AUDIT_ROOT is None:
        return str(p)
    try:
        return str(p.relative_to(AUDIT_ROOT))
    except ValueError:
        return str(p)


def audit_log(
    action: str, src: Path, dst: Path | None = None, dry: bool = False
) -> None:
    if AUDIT_LEVEL == "summary":
        return
    if AUDIT_LEVEL == "deletions" and action != "DELETE":
        return
    prefix = "[dry] " if dry else ""
    dst_str = f" -> {_rel(dst)}" if dst else ""
    note(f"  {prefix}{action}: {_rel(src)}{dst_str}")


# ---------- junk filter ----------
UNWANTED_EXACT = {"contents.csv", "desktop.ini"}  # case-insensitive
CONFLICTS_DIR_NAME = "_conflicts"


def is_trashed_name(name: str) -> bool:
    return name.startswith(".trashed")


def is_thumbnails_name(name: str) -> bool:
    return name.lower() == ".thumbnails"


def is_unwanted_name(name: str) -> bool:
    # remove .trashed*, .thumbnails, and specific junk files
    return (
        is_trashed_name(name)
        or is_thumbnails_name(name)
        or (name.lower() in UNWANTED_EXACT)
    )


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
    debug(("[dry] " if dry else "") + f'mkdir -p "{p}"')
    if not dry:
        p.mkdir(parents=True, exist_ok=True)


def list_children(p: Path) -> list[Path]:
    return list(p.iterdir()) if p.exists() else []


def collect_step6_picture_sources(staging_root: Path) -> list[tuple[str, Path, Path]]:
    """
    Build Step 6 source routing for destination Pictures/.
    Rules:
      - DCIM/Camera is excluded (handled by Steps 1-5)
      - Movies is excluded (handled by Step 7)
      - DCIM/<other-subdirs> -> Pictures/<subdir>
      - Any other top-level staging dir -> Pictures/<dir-name>
    """
    sources: list[tuple[str, Path, Path]] = []

    p_dcim = staging_root / "DCIM"
    for c in sorted(list_children(p_dcim), key=lambda p: p.name.lower()):
        if not c.is_dir() or c.name == "Camera":
            continue
        if count_files_in_path(c, exclude_trashed=True) <= 0:
            continue
        sources.append((f"DCIM/{c.name}", c, Path(c.name)))

    for it in sorted(list_children(staging_root), key=lambda p: p.name.lower()):
        if not it.is_dir():
            continue
        if it.name in {"DCIM", "Movies"}:
            continue
        if count_files_in_path(it, exclude_trashed=True) <= 0:
            continue
        target_rel = Path(".") if it.name == "Pictures" else Path(it.name)
        sources.append((it.name, it, target_rel))

    return sources


def count_files_in_path(p: Path, *, exclude_trashed: bool = True) -> int:
    """Count regular files under path. If exclude_trashed=True, excludes .trashed*, .thumbnails, Contents.csv, desktop.ini."""
    if not p.exists():
        return 0
    if p.is_file():
        return 0 if (exclude_trashed and is_unwanted_name(p.name)) else 1
    total = 0
    for _root, dirs, files in os.walk(p):
        if exclude_trashed:
            dirs[:] = [
                d for d in dirs if not (is_trashed_name(d) or is_thumbnails_name(d))
            ]
            files = [f for f in files if not is_unwanted_name(f)]
        total += len(files)
    return total


def count_files_in_children(
    dir_path: Path,
    *,
    exclude_trashed: bool = True,
    exclude_names: set[str] | None = None,
) -> int:
    if not dir_path.exists():
        return 0
    total = 0
    for it in dir_path.iterdir():
        if exclude_names and it.name in exclude_names:
            continue
        total += count_files_in_path(it, exclude_trashed=exclude_trashed)
    return total


def delete_path(p: Path, dry: bool, *, log: bool = True) -> int:
    """Delete file/dir; return number of regular files removed under it."""
    removed = count_files_in_path(p, exclude_trashed=False) if p.exists() else 0
    if log:
        audit_log("DELETE", p, dry=dry)
    if dry:
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
    if not root.exists():
        return 0
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
    for file_to_delete in files_to_delete:
        removed += delete_path(file_to_delete, dry)
    for d in trashed_dirs:
        removed += delete_path(d, dry)
    return removed


# ---------- dedupe helpers ----------
def sha256sum(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
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
    __slots__ = ("moved", "skipped_dupes", "conflicts", "deleted_unwanted")

    def __init__(self):
        self.moved = 0
        self.skipped_dupes = 0
        self.conflicts = 0
        self.deleted_unwanted = 0


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
            audit_log("SKIP", src, dst, dry=dry)
            if not dry:
                try:
                    src.unlink()
                except Exception:
                    pass
            stats.skipped_dupes += 1
            return
        cdir = ensure_conflicts_dir(dest_dir, dry)
        target = cdir / src.name
        i = 1
        while target.exists():
            target = cdir / f"{src.stem}_conflict{i}{src.suffix}"
            i += 1
        audit_log("CONFLICT", src, target, dry=dry)
        if not dry:
            shutil.move(str(src), str(target))
        stats.conflicts += 1
        return
    audit_log("MOVE", src, dst, dry=dry)
    if not dry:
        shutil.move(str(src), str(dst))
    stats.moved += 1


def dedupe_merge_dir(
    src_dir: Path,
    dest_dir: Path,
    dry: bool,
    stats: MoveStats,
    update_progress=lambda n: None,
) -> None:
    ensure_dir(dest_dir, dry)
    for child in list_children(src_dir):
        if is_unwanted_name(child.name):
            delete_path(child, dry, log=False)
            continue
        if child.is_file():
            dedupe_move_file(child, dest_dir, dry, stats)
            update_progress(1)
        elif child.is_dir():
            dedupe_merge_dir(child, dest_dir / child.name, dry, stats, update_progress)
    if not dry:
        try:
            src_dir.rmdir()
        except OSError:
            pass


# ---------- progress ----------
def progress_start(total_files: int, desc: str, enabled: bool):
    if not enabled or total_files <= 0:

        def _noop(_=0):
            pass

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


def dedupe_move_children_with_progress(
    src_dir: Path, dest_dir: Path, dry: bool, desc: str, total_files: int
) -> MoveStats:
    stats = MoveStats()
    update, close = progress_start(total_files, desc, enabled=not dry)
    try:
        for it in list_children(src_dir):
            if is_unwanted_name(it.name):
                delete_path(it, dry, log=False)
                continue
            if it.is_file():
                dedupe_move_file(it, dest_dir, dry, stats)
                update(1)
            elif it.is_dir():
                dedupe_merge_dir(
                    it, dest_dir / it.name, dry, stats, update_progress=update
                )
    finally:
        close()
    return stats


def moved_phrase(stats: MoveStats, processed: int, dry: bool) -> str:
    verb = "would move" if dry else "moved"
    return f"{verb} {stats.moved}/{processed} files"


# ---------- main ----------
def load_config() -> dict:
    here = Path(__file__).resolve().parent
    return yaml.safe_load((here / "config.yaml").read_text(encoding="utf-8"))


def main():
    global VERBOSITY, AUDIT_LEVEL, AUDIT_ROOT
    cfg = load_config()

    VERBOSITY = int(cfg.get("verbosity", 0))
    DRY_RUN = bool(cfg.get("dry_run", True))
    WRITE_RUN_SUMMARY_JSON = bool(cfg.get("write_run_summary_json", False))
    AUDIT_LEVEL = cfg.get("audit_detail_level", "summary")

    # Config (using your alias dirs)
    STAGING = Path(cfg["staging_root"])
    AUDIT_ROOT = STAGING  # /mnt/c/Users/Neophile/Desktop/mobile
    RENAME_IN = Path(cfg["rename_tool_input"])
    DROPBOX_CU = Path(cfg["dropbox_camera_uploads"])
    GDRIVE_BASE = Path(cfg["google_mobile_base"])
    DESKTOP_CAM = Path(cfg["desktop_mobile_camera"])

    # Staging subdirs
    P_DCIM = STAGING / "DCIM"
    P_MOVIES = STAGING / "Movies"

    # Destinations
    span, span_overridden = resolve_destination_span(cfg)
    dest_root = GDRIVE_BASE / span
    dest_camera = dest_root / "Camera"
    dest_pictures = dest_root / "Pictures"
    dest_movies = dest_root / "Movies"

    # --- Logging location depends on DRY_RUN ---
    # dry run -> log alongside base (do NOT create month folder)
    # real run -> ensure month folder exists and log inside it
    if DRY_RUN:
        GDRIVE_BASE.mkdir(parents=True, exist_ok=True)
        log_dir = GDRIVE_BASE
    else:
        dest_root.mkdir(parents=True, exist_ok=True)
        log_dir = dest_root
    log_path = (
        log_dir / f"mobile_backup_{span}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    with LogTee(log_path, mode="w"):
        if not DRY_RUN:
            ensure_dir(dest_camera, DRY_RUN)
            ensure_dir(dest_pictures, DRY_RUN)
            ensure_dir(dest_movies, DRY_RUN)

        if span_overridden:
            event(f'Destination span override: "{span}"')
        else:
            event(f'Destination span: "{span}" (auto)')
        event(f"Log: {log_path}")
        event(f'Destination: "{dest_root}"')

        # --- Step 1: DCIM/Camera/* -> RENAME_IN ---
        src_camera = P_DCIM / "Camera"
        del1 = cleanup_unwanted(src_camera, DRY_RUN)
        n1 = count_files_in_children(src_camera, exclude_trashed=True)
        ensure_dir(RENAME_IN, DRY_RUN)
        s1 = dedupe_move_children_with_progress(
            src_camera, RENAME_IN, DRY_RUN, desc="Step 1 transfer", total_files=n1
        )
        s1.deleted_unwanted = del1
        event(
            f"Step 1: {'would delete' if DRY_RUN else 'deleted'} {del1} unwanted; {moved_phrase(s1, n1, DRY_RUN)} "
            f"(skipped {s1.skipped_dupes} dupes, conflicts {s1.conflicts}) from {src_camera} -> {RENAME_IN}"
        )
        event("")

        # --- Step 2: rename images in RENAME_IN by EXIF/filename datetime ---
        if not DRY_RUN:
            rename_images_in_directory(RENAME_IN)
        event("Step 2: image renaming " + ("would run" if DRY_RUN else "ran"))
        event("")

        # --- Step 3: RENAME_IN/* -> Desktop/mobile/Camera ---
        del3 = cleanup_unwanted(RENAME_IN, DRY_RUN)
        n3 = count_files_in_children(RENAME_IN, exclude_trashed=True)
        s3 = dedupe_move_children_with_progress(
            RENAME_IN, DESKTOP_CAM, DRY_RUN, desc="Step 3 transfer", total_files=n3
        )
        s3.deleted_unwanted = del3
        event(
            f"Step 3: {'would delete' if DRY_RUN else 'deleted'} {del3} unwanted; {moved_phrase(s3, n3, DRY_RUN)} "
            f"(skipped {s3.skipped_dupes} dupes, conflicts {s3.conflicts}) from {RENAME_IN} -> {DESKTOP_CAM}"
        )
        event("")

        # --- Step 4: verify DESKTOP_CAM files exist in Dropbox Camera Uploads ---
        if not DRY_RUN:
            verify_and_sync(DESKTOP_CAM, DROPBOX_CU)
        event(
            "Step 4: verify/sync against Dropbox Camera Uploads "
            + ("would run" if DRY_RUN else "ran")
        )
        event("")

        # --- Step 5: Dropbox/Camera Uploads/* -> dest Camera ---
        dropbox_cu = Path(DROPBOX_CU)
        del5 = cleanup_unwanted(dropbox_cu, DRY_RUN)
        n5 = count_files_in_children(dropbox_cu, exclude_trashed=True)
        s5 = dedupe_move_children_with_progress(
            dropbox_cu, dest_camera, DRY_RUN, desc="Step 5 transfer", total_files=n5
        )
        s5.deleted_unwanted = del5
        event(
            f"Step 5: {'would delete' if DRY_RUN else 'deleted'} {del5} unwanted; {moved_phrase(s5, n5, DRY_RUN)} "
            f"(skipped {s5.skipped_dupes} dupes, conflicts {s5.conflicts}) from {DROPBOX_CU} -> {dest_camera}"
        )
        event("")

        # --- Step 6: catch-all Pictures routing ---
        step6_sources = collect_step6_picture_sources(STAGING)
        if step6_sources:
            event(
                "  Step 6 routed sources -> Pictures: "
                + ", ".join(label for label, _src, _target in step6_sources)
            )
        else:
            event("  Step 6 routed sources -> Pictures: (none)")

        total_del6 = sum(
            cleanup_unwanted(src, DRY_RUN) for _label, src, _target in step6_sources
        )
        n6_total = sum(
            count_files_in_path(src, exclude_trashed=True)
            for _label, src, _target in step6_sources
        )

        s6 = MoveStats()
        upd, close = progress_start(
            n6_total, "Step 6 transfer (Pictures aggregate)", enabled=not DRY_RUN
        )
        try:
            for _label, src, target_rel in step6_sources:
                dedupe_merge_dir(
                    src, dest_pictures / target_rel, DRY_RUN, s6, update_progress=upd
                )
        finally:
            close()

        s6.deleted_unwanted = total_del6
        event(
            f"Step 6: {'would delete' if DRY_RUN else 'deleted'} {total_del6} unwanted in source staging folders; "
            f"{moved_phrase(s6, n6_total, DRY_RUN)} "
            f"(skipped {s6.skipped_dupes} dupes, conflicts {s6.conflicts}) to {dest_pictures}"
        )
        event("")

        # --- Step 7: Movies/* -> dest_movies ---
        del7 = cleanup_unwanted(P_MOVIES, DRY_RUN)
        n7 = count_files_in_children(P_MOVIES, exclude_trashed=True)
        s7 = dedupe_move_children_with_progress(
            P_MOVIES,
            dest_movies,
            DRY_RUN,
            desc="Step 7 transfer (Movies)",
            total_files=n7,
        )
        s7.deleted_unwanted = del7
        event(
            f"Step 7: {'would delete' if DRY_RUN else 'deleted'} {del7} unwanted; {moved_phrase(s7, n7, DRY_RUN)} "
            f"(skipped {s7.skipped_dupes} dupes, conflicts {s7.conflicts}) from {P_MOVIES} -> {dest_movies}"
        )
        event("")

        # --- Run summary ---
        move_steps = [s1, s3, s5, s6, s7]
        total_processed = n1 + n3 + n5 + n6_total + n7
        total_moved = sum(s.moved for s in move_steps)
        total_skipped_dupes = sum(s.skipped_dupes for s in move_steps)
        total_conflicts = sum(s.conflicts for s in move_steps)
        total_deleted = sum(s.deleted_unwanted for s in move_steps)
        prefix = "would " if DRY_RUN else ""
        event("Run summary:")
        event(f"  {prefix}processed:        {total_processed}")
        event(f"  {prefix}moved:            {total_moved}")
        event(f"  {prefix}skipped dupes:    {total_skipped_dupes}")
        event(f"  {prefix}conflicts:        {total_conflicts}")
        event(f"  {prefix}deleted unwanted: {total_deleted}")

        if WRITE_RUN_SUMMARY_JSON and not DRY_RUN:
            import json

            summary = {
                "span": span,
                "dry_run": DRY_RUN,
                "processed": total_processed,
                "moved": total_moved,
                "skipped_dupes": total_skipped_dupes,
                "conflicts": total_conflicts,
                "deleted_unwanted": total_deleted,
            }
            summary_path = log_dir / f"run_summary_{span}.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            event(f"  summary JSON: {summary_path}")

        event("")
        event("Done." + (" (dry run)" if DRY_RUN else ""))


def cmd_run(_args: argparse.Namespace) -> None:
    main()


def cmd_rename(_args: argparse.Namespace) -> None:
    """Standalone: rename images in the configured rename_tool_input directory."""
    cfg = load_config()
    rename_images_in_directory(Path(cfg["rename_tool_input"]))


def cmd_organize(_args: argparse.Namespace) -> None:
    """Standalone: verify desktop_mobile_camera files exist in dropbox_camera_uploads."""
    cfg = load_config()
    verify_and_sync(
        Path(cfg["desktop_mobile_camera"]), Path(cfg["dropbox_camera_uploads"])
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mobile-backup")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="Run the full backup pipeline").set_defaults(
        func=cmd_run
    )
    subparsers.add_parser(
        "rename", help="Rename images by EXIF/filename datetime"
    ).set_defaults(func=cmd_rename)
    subparsers.add_parser(
        "organize", help="Verify/sync files against Dropbox Camera Uploads"
    ).set_defaults(func=cmd_organize)
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
