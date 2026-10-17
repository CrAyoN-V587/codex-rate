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
            if self.updated and time.monotonic() - self.updated > 3:
                value.update(thread=None, path=None, error="active-reader-stale")
            return value

    def _run(self):
        binary = helper_path()
        if os.name != "nt" or not binary.is_file():
            self.observe({"error": "active-reader-unavailable"})
            return
        process = None
        try:
            self.process = subprocess.Popen([str(binary)], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, encoding="utf-8-sig",
                creationflags=subprocess.CREATE_NO_WINDOW)
            process = self.process
            if self.stop.is_set():
                return
            for line in self.process.stdout:
                if self.stop.is_set():
                    break
                try:
                    self.observe(json.loads(line))
                except (ValueError, TypeError):
                    self.observe({"error": "invalid-active-metadata"})
            if not self.stop.is_set():
                self.observe({"error": "active-reader-stopped"})
        except OSError:
            self.observe({"error": "active-reader-unavailable"})
        finally:
            if process:
                self._terminate(process)
                if process.stdout:
                    process.stdout.close()

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            except OSError:
                pass

    def close(self):
        self.stop.set()
        process = self.process
        if process:
            self._terminate(process)
        if self.thread:
            self.thread.join(timeout=1)
