"""Resolve the sidebar's aria-current page using unique local thread metadata."""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path


_STALE_AFTER = 3.0


def resolve_titles(home, titles):
    """No recency guesses: one exact local metadata match, or unknown."""
    names = tuple(dict.fromkeys(t for t in titles if isinstance(t, str) and t.strip()
                                and t not in ("首页", "Home")))
    if not names:
        return None, None, "active-page-unavailable"
    database = Path(home).resolve() / "state_5.sqlite"
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.2)) as connection:
            marks = ",".join("?" for _ in names)
            rows = connection.execute(
                f"SELECT id, rollout_path FROM threads WHERE name IN ({marks}) "
                f"OR ((name IS NULL OR name = '') AND title IN ({marks}))", names + names).fetchall()
    except (OSError, sqlite3.Error):
        return None, None, "thread-metadata-unavailable"
    if len(rows) != 1:
        return None, None, "ambiguous-active-page" if rows else "active-page-unavailable"
    thread, path = rows[0]
    return thread, path, None


def helper_path():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "native" / "ActiveConversation.exe"
    return Path(__file__).resolve().parent.parent / "build" / "ActiveConversation.exe"


class ActiveWatcher:
    def __init__(self, home):
        self.home = Path(home)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.thread = None
        self.updated = 0.0
        self.identity = None
        self.serial = 0
        self.value = {"thread": None, "path": None, "window": None,
                      "error": "active-page-loading", "serial": 0}

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def observe(self, row):
        if not isinstance(row, dict):
            return
        error = row.get("error")
        thread, path = None, None
        if not error:
            thread, path, error = resolve_titles(self.home, row.get("titles", []))
        identity = (row.get("window"), thread, error)
        with self.lock:
            if identity != self.identity:
                self.serial += 1
                self.identity = identity
            self.value = {"thread": thread, "path": path, "window": row.get("window"),
                          "error": error, "serial": self.serial}
            self.updated = time.monotonic()

    def snapshot(self):
        with self.lock:
            value = dict(self.value)
            if self.updated and time.monotonic() - self.updated > _STALE_AFTER:
                value.update(thread=None, path=None, error="active-reader-stale")
            return value

    def _read(self, process):
        try:
            for line in process.stdout:
                if self.stop.is_set():
                    break
                try:
                    self.observe(json.loads(line))
                except (ValueError, TypeError):
                    self.observe({"error": "invalid-active-metadata"})
        except (OSError, ValueError):
            pass  # The supervisor handles EOF and unreadable output alike.
        finally:
            process.stdout.close()

    def _run(self):
        binary = helper_path()
        if os.name != "nt" or not binary.is_file():
            self.observe({"error": "active-reader-unavailable"})
            return
        delay = 0.5
        while not self.stop.is_set():
            process, reader = None, None
            error = "active-reader-stopped"
            try:
                process = subprocess.Popen([str(binary)], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, encoding="utf-8-sig",
                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.process = process
                started = time.monotonic()
                if self.stop.is_set():
                    return
                reader = threading.Thread(target=self._read, args=(process,), daemon=True)
                reader.start()
                while not self.stop.wait(0.1):
                    if not reader.is_alive():
                        break
                    with self.lock:
                        updated = max(started, self.updated)
                    if time.monotonic() - updated > _STALE_AFTER:
                        error = "active-reader-stale"
                        break
                if time.monotonic() - started >= _STALE_AFTER:
                    delay = 0.5
            except OSError:
                error = "active-reader-unavailable"
            finally:
                if process:
                    self._terminate(process)
                    if reader:
                        reader.join(timeout=1)
                    elif process.stdout:
                        process.stdout.close()
                self.process = process if process and process.poll() is None else None
            # Do not accumulate helpers/readers if the OS could not release one.
            if (reader and reader.is_alive()) or (process and process.poll() is None):
                self.observe({"error": "active-reader-stopped"})
                return
            if not self.stop.is_set():
                self.observe({"error": error})
                if self.stop.wait(delay):
                    return
                delay = min(delay * 2, 5.0)

    @staticmethod
    def _terminate(process):
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def close(self):
        self.stop.set()
        process = self.process
        if process:
            self._terminate(process)
        if self.thread:
            self.thread.join(timeout=3)
