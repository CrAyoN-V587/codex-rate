"""Bounded startup replay and incremental JSONL reads. Never writes Codex files."""

import json
import os
import time
from pathlib import Path

from .metrics import Meter

TAIL_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
MAX_LINE = 8 * 1024 * 1024


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


class SessionReader:
    def __init__(self, path, tail_bytes=TAIL_BYTES):
        self.path = Path(path)
        self.tail_bytes = tail_bytes
        self.offset = 0
        self.pending = b""
        self.dropping = False
        self.meter = Meter()
        self.initialized = False
        self.error = None
        self.malformed = 0
        self.fingerprint = None

    def poll(self):
        try:
            stat = self.path.stat()
            fingerprint = (stat.st_dev, stat.st_ino)
            if self.fingerprint not in (None, fingerprint) or stat.st_size < self.offset:
                self.initialized = False
            self.fingerprint = fingerprint
            with self.path.open("rb") as stream:
                if not self.initialized:
                    self.offset = max(0, stat.st_size - self.tail_bytes)
                    self.pending = b""
                    self.dropping = False
                    self.malformed = 0
                    stream.seek(self.offset)
                    if self.offset:
                        stream.readline(MAX_LINE)
                        self.offset = stream.tell()
                    data = stream.read(self.tail_bytes)
                    rows = self._decode(data)
                    self.meter = Meter(any(r.get("type") == "token_usage_record" for r in rows))
                    for row in rows:
                        self.meter.observe(row)
                    self.offset = stream.tell()
                    self.initialized = True
                else:
                    stream.seek(self.offset)
                    data = stream.read(CHUNK_BYTES)
                    for row in self._decode(data):
                        self.meter.observe(row)
                    self.offset = stream.tell()
            self.error = None
        except OSError as exc:
            self.error = type(exc).__name__
        return self.meter.snapshot()

    def _decode(self, data):
        combined = self.pending + data
        if self.dropping:
            if b"\n" not in combined:
                return []
            combined = combined.split(b"\n", 1)[1]
            self.dropping = False
        lines = combined.split(b"\n")
        self.pending = lines.pop()
        rows = []
        def damaged():
            self.malformed += 1
            rows.append({"type": "reader_error", "payload": {}})
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    damaged()
            except (ValueError, UnicodeError):
                damaged()
        if len(self.pending) > MAX_LINE:
            self.pending = b""
            self.dropping = True
            damaged()
        return rows


class SessionIndex:
    def __init__(self, home):
        self.home = Path(home)
        self.paths = []
        self.scanned = 0.0
        self.error = None

    def refresh(self, force=False):
        if not force and time.monotonic() - self.scanned < 8:
            return
        self.scanned = time.monotonic()
        found = []
        try:
            for folder in ("sessions", "archived_sessions"):
                for path in (self.home / folder).rglob("*.jsonl"):
                    try:
                        found.append((path.stat().st_mtime_ns, path))
                    except OSError:
                        continue
            self.paths = [p for _, p in sorted(found, reverse=True)]
            self.error = None
        except OSError as exc:
            self.error = type(exc).__name__

    def find(self, thread_id):
        return next((p for p in self.paths if thread_id in p.stem), None)

    def latest_desktop(self, candidates=None):
        paths = self.paths
        if candidates:
            paths = [p for p in paths if any(t in p.stem for t in candidates)]
        for path in paths[:20]:
            try:
                with path.open("rb") as stream:
                    row = json.loads(stream.readline(MAX_LINE))
                meta = row.get("payload") or {}
                source = meta.get("source")
                origin = str(meta.get("originator", "")).lower()
                if (isinstance(source, str) and
                        ("desktop" in origin or source in ("vscode", "cli"))):
                    return path
            except (OSError, ValueError, AttributeError):
                continue
        return None
