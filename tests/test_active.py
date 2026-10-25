import sqlite3
import json
import queue
import subprocess
import tempfile
import time
import unittest
import io
import threading
from unittest.mock import Mock, patch
from pathlib import Path
from contextlib import closing, contextmanager

from codex_rate.active import ActiveWatcher, resolve_titles
from codex_rate.app import Monitor


class HelperPipe:
    def __init__(self):
        self.lines = queue.Queue()
        self.closed = False

    def __iter__(self):
        while True:
            line = self.lines.get()
            if line is None:
                return
            yield line

    def close(self):
        self.closed = True


class HelperProcess:
    def __init__(self):
        self.stdout = HelperPipe()
        self.exited = threading.Event()
        self.terminated = False

    def emit(self, titles):
        self.stdout.lines.put(json.dumps({"window": 10, "titles": titles}) + "\n")

    def exit(self):
        self.exited.set()
        self.stdout.lines.put(None)

    def poll(self):
        return 0 if self.exited.is_set() else None

    def terminate(self):
        self.terminated = True
        self.exit()

    kill = terminate

    def wait(self, timeout):
        if not self.exited.wait(timeout):
            raise subprocess.TimeoutExpired("helper", timeout)
        return 0


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

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("watcher did not reach the expected state")

    @contextmanager
    def running_watcher(self, side_effect):
        watcher = ActiveWatcher(self.home)
        binary = Mock()
        binary.is_file.return_value = True
        with patch("codex_rate.active.helper_path", return_value=binary), patch(
                "codex_rate.active.subprocess.Popen", side_effect=side_effect) as create:
            watcher.start()
            try:
                yield watcher, create
            finally:
                watcher.close()
        self.assertFalse(watcher.thread.is_alive())

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
            monitor.value["measurement"].update(output=999, tps=20, cache_percent=75)
        monitor.active.observe({"window": 10, "titles": ["Current B"]})
        value = monitor.snapshot()
        self.assertEqual(value["thread"], "thread-b")
        for field in ("output", "tps", "cache_percent"):
            self.assertIsNone(value["measurement"][field])
        self.assertEqual(value["mode"], "loading")

    def test_loading_page_clears_all_numbers_without_background_fallback(self):
        monitor = Monitor(self.home)
        monitor.active.observe({"window": 10, "titles": ["Current A"]})
        monitor.update()
        with monitor.lock:
            monitor.value["measurement"].update(output=999, tps=20, cache_percent=75)
        monitor.active.observe({"window": 10, "titles": []})
        with patch.object(monitor.ipc.selection, "snapshot", return_value=(["thread-a"], True, None)):
            for value in (monitor.snapshot(), monitor.update(), monitor.update()):
                self.assertIsNone(value["thread"])
                for field in ("output", "tps", "cache_percent"):
                    self.assertIsNone(value["measurement"][field])

    def test_manual_selection_clears_old_numbers_immediately(self):
        monitor = Monitor(self.home)
        with monitor.lock:
            monitor.value["measurement"]["output"] = 999
        monitor.pin("thread-b")
        self.assertIsNone(monitor.snapshot()["measurement"]["output"])

    def test_exited_helper_restarts_and_resolves_only_the_new_page(self):
        first, second = HelperProcess(), HelperProcess()
        first.emit(["Current A"])
        second.emit(["Current B"])
        with self.running_watcher([first, second]) as (watcher, create):
            self.wait_for(lambda: watcher.snapshot()["thread"] == "thread-a")
            serial = watcher.snapshot()["serial"]
            first.exit()
            self.wait_for(lambda: watcher.snapshot()["error"] == "active-reader-stopped")
            self.assertIsNone(watcher.snapshot()["thread"])
            self.assertIsNone(watcher.snapshot()["path"])
            self.wait_for(lambda: watcher.snapshot()["thread"] == "thread-b")
            self.assertGreater(watcher.snapshot()["serial"], serial)
            self.assertEqual(create.call_count, 2)
            self.assertTrue(first.stdout.closed)
        self.assertTrue(second.terminated)
        self.assertTrue(second.stdout.closed)

    def test_stalled_helper_is_terminated_before_retry_and_never_uses_old_page(self):
        first, second = HelperProcess(), HelperProcess()
        first.emit(["Current A"])
        second.emit([])
        with patch("codex_rate.active._STALE_AFTER", 0.15), self.running_watcher(
                [first, second]) as (watcher, create):
            self.wait_for(lambda: watcher.snapshot()["thread"] == "thread-a")
            self.wait_for(lambda: watcher.snapshot()["error"] == "active-reader-stale")
            self.assertIsNone(watcher.snapshot()["thread"])
            self.wait_for(lambda: first.terminated)
            self.wait_for(lambda: create.call_count == 2)
            self.wait_for(lambda: watcher.snapshot()["error"] == "active-page-unavailable")
            self.assertTrue(first.stdout.closed)
            self.assertIsNone(watcher.snapshot()["thread"])
            self.assertIsNone(watcher.snapshot()["path"])
            second.emit(["Current B"])
            self.wait_for(lambda: watcher.snapshot()["thread"] == "thread-b")
        self.assertTrue(second.terminated)
        self.assertTrue(second.stdout.closed)

    def test_helper_that_hangs_before_first_record_is_replaced(self):
        first, second = HelperProcess(), HelperProcess()
        second.emit(["Current B"])
        with patch("codex_rate.active._STALE_AFTER", 0.15), self.running_watcher(
                [first, second]) as (watcher, create):
            self.wait_for(lambda: first.terminated)
            self.assertIsNone(watcher.snapshot()["thread"])
            self.wait_for(lambda: watcher.snapshot()["thread"] == "thread-b")
            self.assertEqual(create.call_count, 2)
            self.assertTrue(first.stdout.closed)
        self.assertTrue(second.stdout.closed)

    def test_launch_failure_recovers_in_background(self):
        process = HelperProcess()
        process.emit(["Current B"])
        with self.running_watcher([OSError("temporary launch failure"), process]) as (watcher, create):
            self.wait_for(lambda: watcher.snapshot()["error"] == "active-reader-unavailable")
            self.assertIsNone(watcher.snapshot()["thread"])
            self.wait_for(lambda: watcher.snapshot()["thread"] == "thread-b")
            self.assertEqual(create.call_count, 2)
        self.assertTrue(process.terminated)
        self.assertTrue(process.stdout.closed)

    def test_close_interrupts_retry_wait_without_launching_another_helper(self):
        process = HelperProcess()
        process.exit()
        with self.running_watcher([process]) as (watcher, create):
            self.wait_for(lambda: watcher.snapshot()["error"] == "active-reader-stopped")
            watcher.close()
            self.assertEqual(create.call_count, 1)
            self.assertFalse(watcher.thread.is_alive())
        self.assertTrue(process.stdout.closed)

    def test_failed_cleanup_does_not_spawn_duplicates_and_close_retries_cleanup(self):
        process = HelperProcess()
        process.stdout.lines.put(None)  # The child closes stdout but remains alive.
        terminate = process.terminate
        attempts = []

        def transient_failure():
            attempts.append(True)
            if len(attempts) == 1:
                raise OSError("temporary termination failure")
            terminate()

        process.terminate = transient_failure
        with self.running_watcher([process]) as (watcher, create):
            self.wait_for(lambda: not watcher.thread.is_alive())
            self.assertIsNone(watcher.snapshot()["thread"])
            watcher.close()
            self.assertEqual(create.call_count, 1)
        self.assertTrue(process.terminated)
        self.assertTrue(process.stdout.closed)

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

    def test_close_during_restart_creation_cleans_up_both_helpers(self):
        first, second = HelperProcess(), HelperProcess()
        first.exit()
        creating, release = threading.Event(), threading.Event()
        calls = []

        def create(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                return first
            creating.set()
            release.wait(2)
            return second

        with self.running_watcher(create) as (watcher, factory):
            self.assertTrue(creating.wait(2))
            closer = threading.Thread(target=watcher.close)
            closer.start()
            try:
                self.assertTrue(watcher.stop.wait(1))
            finally:
                release.set()
                closer.join(timeout=2)
            self.assertFalse(closer.is_alive())
            self.assertFalse(watcher.thread.is_alive())
            self.assertEqual(factory.call_count, 2)
        self.assertTrue(first.stdout.closed)
        self.assertTrue(second.terminated)
        self.assertTrue(second.stdout.closed)
