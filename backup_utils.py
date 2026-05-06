#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys


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
    def __init__(self, logfile: Path, mode: str = "w"):
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
