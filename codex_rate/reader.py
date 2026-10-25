"""Bounded startup replay and incremental JSONL reads. Never writes Codex files."""

import codecs
import json
import os
import time
from pathlib import Path

from .metrics import Meter

TAIL_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
MAX_LINE = 8 * 1024 * 1024
RECOVERY_BYTES = 64 * 1024 * 1024
HEADER_BYTES = 64 * 1024
NON_METRIC_TYPES = frozenset({"response_item", "compacted", "world_state",
                              "session_meta", "turn_context"})


def _top_level_type(line):
    """Read an envelope prefix, never a nested or quoted payload's type."""
    try:
        prefix = codecs.getincrementaldecoder("utf-8")().decode(line[:HEADER_BYTES])
        decoder = json.JSONDecoder()
        pos = len(prefix) - len(prefix.lstrip(" \t\r"))
        if prefix[pos:pos + 1] != "{":
            return None
        pos += 1
        while True:
            while pos < len(prefix) and prefix[pos] in " \t\r":
                pos += 1
            key, pos = decoder.raw_decode(prefix, pos)
            if not isinstance(key, str):
                return None
            while pos < len(prefix) and prefix[pos] in " \t\r":
                pos += 1
            if prefix[pos:pos + 1] != ":":
                return None
            pos += 1
            while pos < len(prefix) and prefix[pos] in " \t\r":
                pos += 1
            value, pos = decoder.raw_decode(prefix, pos)
            while pos < len(prefix) and prefix[pos] in " \t\r":
                pos += 1
            delimiter = prefix[pos:pos + 1]
            if delimiter not in (",", "}"):
                return None
            if key == "type":
                return value if isinstance(value, str) else None
            if delimiter == "}":
                return None
            pos += 1
    except (ValueError, UnicodeError, RecursionError):
        return None


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


class SessionReader:
    def __init__(self, path, tail_bytes=TAIL_BYTES, recovery_bytes=RECOVERY_BYTES):
        self.path = Path(path)
        # Keep each poll bounded, including the backward search and its replay.
        self.tail_bytes = max(1, tail_bytes)
        self.recovery_limit = max(1, recovery_bytes)
        self.offset = 0
        self.pending = b""
        self.dropping = False
        self.meter = Meter()
        self.initialized = False
        self.error = None
        self.malformed = 0
        self.fingerprint = None
        self.recovering = False
        self.recovery_state = "pending"
        self.recovery_bytes = 0
        self.recovery_limited = False
        self.skipped_non_metric = 0
        self.backlog_bytes = 0

    def _begin_recovery(self, size):
        self.offset = 0
        self.pending = b""
        self.dropping = False
        self.malformed = 0
        self.skipped_non_metric = 0
        self.meter = Meter()
        self.initialized = False
        self.recovering = True
        self.recovery_state = "searching"
        self.recovery_bytes = 0
        self.recovery_limited = False
        self._recovery_end = size
        self._search_floor = max(0, size - self.recovery_limit)
        self._search_cursor = size
        self._search_pending = b""
        # The final fragment is incomplete unless there is a trailing newline.
        self._search_dropping = True
        self._search_modern = False

    def _start_replay(self, stream, offset, found_start):
        self.offset = offset
        self.pending = b""
        self.dropping = False
        if offset and not found_start:
            stream.seek(offset - 1)
            self.dropping = stream.read(1) != b"\n"
        self._search_pending = b""
        self.meter = Meter(self._search_modern)
        self.recovery_state = "replaying"
        self.recovery_limited = not found_start and self._search_floor > 0

    def _search_line(self, line):
        if not line.strip() or _top_level_type(line) in NON_METRIC_TYPES:
            return False
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            return False
        if not isinstance(record, dict):
            return False
        kind = record.get("type")
        if kind == "token_usage_record":
            self._search_modern = True
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return False
        event = payload.get("type") if kind == "event_msg" else kind
        return event == "task_started"

    def _search(self, stream, budget):
        size = min(CHUNK_BYTES, budget, self._search_cursor - self._search_floor)
        start = self._search_cursor - size
        stream.seek(start)
        data = stream.read(size)
        self.recovery_bytes += len(data)
        self._search_cursor = start
        parts = data.split(b"\n")
        position = start + len(data)
        for index in range(len(parts) - 1, -1, -1):
            part = parts[index]
            position -= len(part)
            if not self._search_dropping:
                if len(part) + len(self._search_pending) > MAX_LINE:
                    self._search_pending = b""
                    self._search_dropping = True
                else:
                    self._search_pending = part + self._search_pending
            if index or start == 0:
                if (not self._search_dropping and
                        self._search_line(self._search_pending)):
                    self._start_replay(stream, position, True)
                    return len(data)
                self._search_pending = b""
                self._search_dropping = False
            position -= 1
        if start == self._search_floor:
            self._start_replay(stream, start, False)
        return len(data)

    def poll(self):
        try:
            with self.path.open("rb") as stream:
                stat = os.fstat(stream.fileno())
                fingerprint = (stat.st_dev, stat.st_ino)
                if (self.fingerprint != fingerprint or stat.st_size < self.offset or
                        (self.recovering and stat.st_size < self._recovery_end)):
                    self._begin_recovery(stat.st_size)
                self.fingerprint = fingerprint
                budget = self.tail_bytes
                while budget:
                    if self.recovery_state == "searching":
                        budget -= self._search(stream, budget)
                        continue
                    end = self._recovery_end if self.recovering else stat.st_size
                    remaining = end - self.offset
                    if remaining <= 0:
                        if self.recovering:
                            self.recovering = False
                            self.initialized = True
                            continue
                        break
                    stream.seek(self.offset)
                    data = stream.read(min(CHUNK_BYTES, budget, remaining))
                    if not data:
                        break
                    for row in self._decode(data):
                        self.meter.observe(row)
                    self.offset = stream.tell()
                    budget -= len(data)
                    if self.recovering:
                        self.recovery_bytes += len(data)
                self.backlog_bytes = max(0, stat.st_size - self.offset)
                if self.initialized:
                    self.recovery_state = ("complete" if self.meter.started or
                                           not self.meter.samples and not self.recovery_limited
                                           else "partial")
            self.error = None
        except OSError as exc:
            self.error = type(exc).__name__
        return (Meter() if self.recovering else self.meter).snapshot()

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
        def oversized(line):
            if _top_level_type(line) in NON_METRIC_TYPES:
                self.skipped_non_metric += 1
            else:
                damaged()
        for line in lines:
            if len(line) > MAX_LINE:
                oversized(line)
                continue
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    damaged()
            except (ValueError, UnicodeError, RecursionError):
                damaged()
        if len(self.pending) > MAX_LINE:
            oversized(self.pending)
            self.pending = b""
            self.dropping = True
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
