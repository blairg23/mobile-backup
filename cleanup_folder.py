#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import argparse, os, sys, yaml, hashlib, shutil

# ---------- safe tee logger ----------
class _SafeStream:
    """Wraps a stream and ignores write/flush errors during shutdown."""
    def __init__(self, stream): self.stream = stream
    def write(self, data):
        try:
            self.stream.write(data)
        except Exception:
            pass
    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass

class LogTee:
    """
    Context manager that tees stdout/stderr to a file + console, restoring on exit.
    Prevents unraisablehook noise by swallowing write/flush errors during shutdown.
    """
    def __init__(self, logfile: Path, mode: str = "a"):
        self.logfile = logfile
        self.mode = mode
        self._f = None
        self._old_out = None
        self._old_err = None

    def __enter__(self):
        self.logfile.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.logfile, self.mode, encoding="utf-8", buffering=1)
        self._old_out, self._old_err = sys.stdout, sys.stderr
        sys.stdout = self._tee(sys.stdout, self._f)
        sys.stderr = self._tee(sys.stderr, self._f)
        return self.logfile

    def __exit__(self, exc_type, exc, tb):
        try:
            # Restore first, then close file.
            if self._old_out is not None:
                sys.stdout = self._old_out
            if self._old_err is not None:
                sys.stderr = self._old_err
        finally:
            try:
                if self._f:
                    self._f.flush()
                    self._f.close()
            except Exception:
                pass
        return False  # don't suppress exceptions

    @staticmethod
    def _tee(console_stream, file_stream):
        console = _SafeStream(console_stream)
        fileobj = _SafeStream(file_stream)
        class _Tee:
            def write(self, data):
                console.write(data); fileobj.write(data)
            def flush(self):
                console.flush(); fileobj.flush()
        return _Tee()

# ---------- junk filter (matches mobile_backup.py) ----------
UNWANTED_EXACT = {"contents.csv", "desktop.ini"}  # case-insensitive
CONFLICTS_DIR_NAME = "_conflicts"

def is_trashed_name(name: str) -> bool: return name.startswith(".trashed")
def is_thumbnails_name(name: str) -> bool: return name.lower() == ".thumbnails"
def is_unwanted_name(name: str) -> bool:
    return is_trashed_name(name) or is_thumbnails_name(name) or (name.lower() in UNWANTED_EXACT)

# ---------- hashing / identical checks ----------
def sha256sum(p: Path, chunk: int = 1024*1024) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
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

# ---------- utilities ----------
def count_files_in_path(p: Path) -> int:
    if not p.exists(): return 0
    if p.is_file(): return 1
    total = 0
    for _r, _d, files in os.walk(p):
        total += len(files)
    return total

def ensure_conflicts(dest: Path, apply: bool) -> Path:
    c = dest / CONFLICTS_DIR_NAME
    if apply:
        c.mkdir(parents=True, exist_ok=True)
    return c

# ---------- junk cleanup ----------
def cleanup_unwanted(root: Path, apply: bool) -> int:
    """Remove .trashed*, .thumbnails, Contents.csv, desktop.ini; return # files removed (counts files inside deleted dirs)."""
    if not root.exists(): return 0
    removed = 0
    trash_dirs, files_to_del = [], []
    for cur, dirs, files in os.walk(root, topdown=True):
        dels = [d for d in dirs if is_trashed_name(d) or is_thumbnails_name(d)]
        trash_dirs += [Path(cur)/d for d in dels]
        dirs[:] = [d for d in dirs if d not in dels]
        for f in files:
            if is_unwanted_name(f):
                files_to_del.append(Path(cur)/f)

    for f in files_to_del:
        removed += 1
        print(f"delete file: {f}")
        if apply:
            try: f.unlink(missing_ok=True)
            except Exception: pass

    for d in trash_dirs:
        c = count_files_in_path(d)
        removed += c
        print(f"delete dir:  {d}  (~{c} files)")
        if apply:
            shutil.rmtree(d, ignore_errors=True)

    return removed

# ---------- file & dir suffix (“_1”) fixers ----------
def base_name_for_suffix(name: str) -> str | None:
    """Return base name without `_1` suffix (before extension), else None."""
    if name.endswith("_1"):         # no extension
        return name[:-2] if len(name) > 2 else None
    if "_1." in name:
        return name.replace("_1.", ".", 1)  # only first occurrence
    return None

def fix_suffix_file(p1: Path, apply: bool) -> tuple[str, Path, Path | None]:
    """
    Handle a file like name_1.ext or name_1.
    Returns (action, src, target_or_none). Actions: 'delete_dupe', 'moved_to_base', 'conflict_quarantined', 'skipped_no_base'
    """
    base = base_name_for_suffix(p1.name)
    if not base:
        return ("skipped_no_base", p1, None)
    p0 = p1.with_name(base)
    if not p0.exists():
        print(f"rename file: {p1} -> {p0}")
        if apply:
            p1.rename(p0)
        return ("moved_to_base", p1, p0)
    if files_identical(p1, p0):
        print(f"delete duplicate file: {p1} (identical to {p0})")
        if apply:
            try: p1.unlink()
            except Exception: pass
        return ("delete_dupe", p1, p0)
    cdir = ensure_conflicts(p1.parent, apply)
    target = cdir / p1.name
    i = 1
    while target.exists():
        target = cdir / f"{p1.stem}_conflict{i}{p1.suffix}"
        i += 1
    print(f"conflict file -> quarantine: {p1} -> {target}")
    if apply:
        shutil.move(str(p1), str(target))
    return ("conflict_quarantined", p1, target)

def dedupe_merge_dir(src: Path, dst: Path, apply: bool) -> tuple[int, int, int]:
    """
    Merge src/ into dst/ recursively.
    Returns (moved, deleted_dupes, conflicts)
    """
    moved = deleted_dupes = conflicts = 0
    if apply:
        dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if is_unwanted_name(child.name):
            print(f"delete junk in dir: {child}")
            if apply:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            continue
        if child.is_file():
            target = dst / child.name
            if target.exists():
                if files_identical(child, target):
                    print(f"delete duplicate file: {child} (identical to {target})")
                    if apply:
                        try: child.unlink()
                        except Exception: pass
                    deleted_dupes += 1
                else:
                    cdir = ensure_conflicts(dst, apply)
                    q = cdir / child.name
                    i = 1
                    while q.exists():
                        q = cdir / f"{child.stem}_conflict{i}{child.suffix}"
                        i += 1
                    print(f"conflict file -> quarantine: {child} -> {q}")
                    if apply:
                        shutil.move(str(child), str(q))
                    conflicts += 1
            else:
                print(f"move file: {child} -> {target}")
                if apply:
                    shutil.move(str(child), str(target))
                moved += 1
        elif child.is_dir():
            m, d, c = dedupe_merge_dir(child, dst / child.name, apply)
            moved += m; deleted_dupes += d; conflicts += c
    if apply:
        try: src.rmdir()
        except OSError: pass
    return moved, deleted_dupes, conflicts

def fix_suffix_dir(src: Path, apply: bool) -> tuple[str, Path, Path]:
    """
    Handle a directory named *_1: merge into base dir name (without _1),
    or rename if base missing. Returns (action, src, base).
    Actions: 'renamed_to_base', 'merged_into_base'
    """
    assert src.is_dir()
    if not src.name.endswith("_1"):
        return ("skipped", src, src)
    base = src.with_name(src.name[:-2])
    if not base.exists():
        print(f"rename dir: {src} -> {base}")
        if apply:
            shutil.move(str(src), str(base))
        return ("renamed_to_base", src, base)
    print(f"merge dir: {src} -> {base}")
    moved, dups, confs = dedupe_merge_dir(src, base, apply)
    print(f"  merge summary for {src.name}: moved={moved}, deleted_dupes={dups}, conflicts={confs}")
    return ("merged_into_base", src, base)

# ---------- path resolution ----------
def resolve_month_path(cfg: dict, arg_path: str) -> Path:
    p = Path(arg_path)
    if p.is_absolute():
        return p
    base = Path(cfg["google_mobile_base"])
    return base / arg_path

# ---------- main ----------
def main():
    here = Path(__file__).resolve().parent
    cfg = yaml.safe_load((here/"config.yaml").read_text(encoding="utf-8"))
    if "google_mobile_base" not in cfg:
        print("config.yaml must include google_mobile_base", file=sys.stderr); sys.exit(2)

    ap = argparse.ArgumentParser(description="Clean junk and fix *_1 files/folders in a month folder.")
    ap.add_argument("folder", help="month folder name or full path (e.g., 202509_202510)")
    ap.add_argument("--apply", action="store_true", help="apply changes (default is dry-run)")
    args = ap.parse_args()

    month_path = resolve_month_path(cfg, args.folder).resolve()
    if not month_path.exists():
        print(f"No such folder: {month_path}", file=sys.stderr); sys.exit(2)

    log_path = month_path / "cleanup_log.txt"
    # use context manager so stdio is always restored before file close
    with LogTee(log_path, mode="a"):
        print("="*72)
        print(f"Cleanup run @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  (apply={args.apply})")
        print(f"Target: {month_path}")
        print(f"Log:    {log_path}")

        # 1) purge junk first
        removed = cleanup_unwanted(month_path, apply=args.apply)
        print(f"Junk removed: {removed} item(s)")

        # 2) fix *_1 files (rename/delete/quarantine-by-content)
        file_actions = {"delete_dupe":0, "moved_to_base":0, "conflict_quarantined":0}
        for dirpath, _dirs, files in os.walk(month_path):
            d = Path(dirpath)
            for f in files:
                base = base_name_for_suffix(f)
                if not base:
                    continue
                action, _src, _target = fix_suffix_file(d/f, apply=args.apply)
                if action in file_actions:
                    file_actions[action] += 1

        print(f"File suffix fixes: deleted_dupes={file_actions['delete_dupe']}, "
              f"moved_to_base={file_actions['moved_to_base']}, "
              f"conflicts_quarantined={file_actions['conflict_quarantined']}")

        # 3) fix *_1 directories (rename or merge)
        dir_renamed = 0
        dir_merged = 0
        # Walk top-down; operate on a copy of 'dirs' so os.walk remains stable
        for dirpath, dirs, _files in os.walk(month_path):
            for name in list(dirs):
                if not name.endswith("_1"):
                    continue
                src = Path(dirpath) / name
                action, _src, _base = fix_suffix_dir(src, apply=args.apply)
                if action == "renamed_to_base":
                    dir_renamed += 1
                elif action == "merged_into_base":
                    dir_merged += 1

        print(f"Dir suffix fixes: renamed={dir_renamed}, merged={dir_merged}")
        print("Done.")
        print("="*72)

if __name__ == "__main__":
    main()
