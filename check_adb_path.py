#!/usr/bin/env python3
# check_adb_path.py — simple, reliable ADB listing
import argparse, subprocess, shutil, sys, os
from pathlib import Path
import yaml

def resolve_adb(cfg):
    p = (cfg or {}).get("adb_path", "").strip()
    if p: return p
    found = shutil.which("adb")
    if found: return found
    default = "/mnt/c/Android/platform-tools/adb.exe"
    if Path(default).exists(): return default
    print("ERROR: adb not found. Set 'adb_path' in config.yaml.", file=sys.stderr); sys.exit(2)

def adb(adb_exec, adb_device, *args, **kw):
    cmd = [adb_exec] + (["-s", adb_device] if adb_device else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def ensure_device(adb_exec, adb_device):
    out = adb(adb_exec, adb_device, "devices")
    lines = [l for l in out.stdout.splitlines() if l.strip() and not l.startswith("List of")]
    if not lines: print("No devices visible to adb."); sys.exit(2)
    if "unauthorized" in lines[0]: print("Device unauthorized. Revoke & re-approve USB debugging."); sys.exit(2)

def adb_list(adb_exec, adb_device, path: str, include_hidden: bool):
    import shlex
    q = shlex.quote(path)
    # Try "cd PATH && ls" (directory case), else "ls PATH" (file case). If both fail, echo marker.
    shell_cmd = f'cd {q} 2>/dev/null && ls -1 || (ls -1 {q} 2>/dev/null) || echo __NO__'
    out = subprocess.run([adb_exec] + (["-s", adb_device] if adb_device else []) +
                         ["shell", "sh", "-c", shell_cmd],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return [], f"adb error {out.returncode}: {out.stderr.strip()}"
    lines = [x.strip("\r") for x in out.stdout.splitlines() if x.strip()]
    if "__NO__" in lines:
        return [], f"Path does not exist or not readable: {path}"
    if not include_hidden:
        lines = [x for x in lines if not x.startswith(".")]
    return lines, None


def main():
    here = Path(__file__).resolve().parent
    cfg_path = here / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="/sdcard", help="device path to list (default: /sdcard)")
    ap.add_argument("-a", "--all", action="store_true", help="include hidden entries")
    ap.add_argument("-n", "--limit", type=int, default=10, help="how many names to show")
    args = ap.parse_args()

    adb_exec = resolve_adb(cfg)
    adb_device = cfg.get("adb_device", "")

    print("Using adb:", adb_exec)
    if os.environ.get("ADB_SERVER_SOCKET"):
        print("ADB_SERVER_SOCKET:", os.environ["ADB_SERVER_SOCKET"])

    ensure_device(adb_exec, adb_device)

    entries, err = adb_list(adb_exec, adb_device, args.path, include_hidden=args.all)
    if err:
        print(err); sys.exit(1)

    print(f"✅ {len(entries)} entries under {args.path}")
    for name in entries[:args.limit]:
        print("  " + name)
    if len(entries) > args.limit:
        print(f"  …and {len(entries)-args.limit} more")

if __name__ == "__main__":
    main()
