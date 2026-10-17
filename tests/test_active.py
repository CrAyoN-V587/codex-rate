import sqlite3
import tempfile
import time
import unittest
import io
import threading
from unittest.mock import Mock, patch
from pathlib import Path
from contextlib import closing

from codex_rate.active import ActiveWatcher, resolve_titles
from codex_rate.app import Monitor


class ActiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        with closing(sqlite3.connect(self.home / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT, rollout_path TEXT)")
            db.executemany("INSERT INTO threads VALUES (?,?,?,?)", [
                ("thread-a", "Current A", "Raw initial prompt A", str(self.home / "a.jsonl")),
                ("thread-b", "Current B", "Raw initial prompt B", str(self.home / "b.jsonl"))])
            db.commit()

    def test_display_name_maps_even_when_raw_title_differs(self):
        thread, path, error = resolve_titles(self.home, ["首页", "Current A"])
        self.assertEqual(thread, "thread-a")
        self.assertTrue(path.endswith("a.jsonl"))
        self.assertIsNone(error)

    def test_duplicate_names_are_unknown_not_most_recent(self):
        with closing(sqlite3.connect(self.home / "state_5.sqlite")) as db:
            db.execute("INSERT INTO threads VALUES ('duplicate','Current A','x','x')")
            db.commit()
        thread, _, error = resolve_titles(self.home, ["Current A"])
        self.assertIsNone(thread)
        self.assertEqual(error, "ambiguous-active-page")

    def test_home_or_loading_page_does_not_choose_active_background(self):
        with closing(sqlite3.connect(self.home / "state_5.sqlite")) as db:
            db.execute("INSERT INTO threads VALUES ('home-thread','首页','x','x')")
            db.commit()
        for titles in ([], ["首页"], ["Unrecognized chat"]):
            thread, _, error = resolve_titles(self.home, titles)
            self.assertIsNone(thread)
            self.assertEqual(error, "active-page-unavailable")

    def test_switch_increments_generation_but_same_page_does_not(self):
        watcher = ActiveWatcher(self.home)
        watcher.observe({"window": 10, "titles": ["Current A"]})
        serial = watcher.snapshot()["serial"]
        watcher.observe({"window": 10, "titles": ["Current A"]})
        self.assertEqual(watcher.snapshot()["serial"], serial)
        watcher.observe({"window": 10, "titles": ["Current B"]})
        self.assertGreater(watcher.snapshot()["serial"], serial)
        self.assertEqual(watcher.snapshot()["thread"], "thread-b")

    def test_stalled_reader_does_not_leave_old_conversation_visible(self):
        watcher = ActiveWatcher(self.home)
        watcher.observe({"window": 10, "titles": ["Current A"]})
        watcher.updated = time.monotonic() - 4
        self.assertIsNone(watcher.snapshot()["thread"])
        self.assertEqual(watcher.snapshot()["error"], "active-reader-stale")

    def test_switch_clears_cached_metrics_before_next_log_read(self):
        monitor = Monitor(self.home)
        monitor.active.observe({"window": 10, "titles": ["Current A"]})
        first = monitor.update()
        self.assertEqual(first["mode"], "loading")
        with monitor.lock:
            monitor.value["measurement"]["output"] = 999
        monitor.active.observe({"window": 10, "titles": ["Current B"]})
        value = monitor.snapshot()
        self.assertEqual(value["thread"], "thread-b")
        self.assertIsNone(value["measurement"]["output"])
        self.assertEqual(value["mode"], "loading")

    def test_manual_selection_clears_old_numbers_immediately(self):
        monitor = Monitor(self.home)
        with monitor.lock:
            monitor.value["measurement"]["output"] = 999
        monitor.pin("thread-b")
        self.assertIsNone(monitor.snapshot()["measurement"]["output"])

    def test_close_during_process_creation_still_terminates_helper(self):
        watcher = ActiveWatcher(self.home)
        creating, terminated = threading.Event(), threading.Event()
        process = Mock()
        process.stdout = io.StringIO("")
        process.poll.side_effect = lambda: 0 if terminated.is_set() else None
        process.terminate.side_effect = terminated.set
        def create(*args, **kwargs):
            creating.set()
            time.sleep(0.05)
            return process
        binary = Mock()
        binary.is_file.return_value = True
        with patch("codex_rate.active.helper_path", return_value=binary), patch(
                "codex_rate.active.subprocess.Popen", side_effect=create):
            watcher.start()
            self.assertTrue(creating.wait(1))
            watcher.close()
        self.assertTrue(terminated.is_set())
        self.assertTrue(process.stdout.closed)
