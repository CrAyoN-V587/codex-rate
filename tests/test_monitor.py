import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_rate.app import Monitor
from test_metrics import row, sample, usage
from test_reader import lines


class MonitorRecoveryTests(unittest.TestCase):
    def test_large_tool_output_keeps_all_three_metrics_and_next_response_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            sessions = home / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-thread-a.jsonl"
            path.write_bytes(lines(row("task_started", turn_id="t1"), sample()))
            monitor = Monitor(home, "thread-a")
            with patch("codex_rate.reader.MAX_LINE", 2048), patch("codex_rate.reader.CHUNK_BYTES", 512):
                monitor.update()  # A selection transition must clear old numbers.
                initial = monitor.update()
                self.assertIsNone(initial["error"])
                # Use small polling budgets to exercise the same cross-poll path
                # as a multi-megabyte output, without allocating large fixtures.
                monitor.readers[path].tail_bytes = 1024
                call = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec"}}
                output = {"type": "response_item", "payload": {
                    "type": "custom_tool_call_output", "output": "x" * 5000}}
                with path.open("ab") as stream:
                    stream.write(lines(call, output))
                for _ in range(10):
                    value = monitor.update()
                    self.assertIsNone(value["error"])
                    result = value["measurement"]
                    self.assertEqual((result["tps"], result["output"], result["cache_percent"]), (100, 100, 50))
                    if value["reader"]["backlog_bytes"] == 0:
                        break
                else:
                    self.fail("log backlog did not drain")
                self.assertEqual(value["reader"]["skipped_non_metric"], 1)
                with path.open("ab") as stream:
                    stream.write(lines(sample(ms=2000, response="r2", total=usage(200, 2000, 1000))))
                updated = monitor.update()
                self.assertIsNone(updated["error"])
                self.assertEqual(updated["measurement"]["output"], 200)
                self.assertEqual(updated["measurement"]["tps"], 100)

    def test_recovery_diagnostics_do_not_expose_historical_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            sessions = home / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-thread-a.jsonl"
            path.write_bytes(lines(row("task_started", turn_id="t1"), sample()) +
                             lines({"type": "response_item", "payload": {"ignored": "x" * 5000}}))
            monitor = Monitor(home, "thread-a")
            monitor.update()
            from codex_rate.reader import SessionReader
            monitor.readers[path] = SessionReader(path, tail_bytes=1024)
            saw_recovery = False
            for _ in range(30):
                value = monitor.update()
                if value["reader"]["recovering"]:
                    saw_recovery = True
                    self.assertEqual(value["error"], "log-recovering")
                    self.assertIsNone(value["measurement"]["output"])
                    self.assertIsNone(value["measurement"]["tps"])
                else:
                    break
            else:
                self.fail("recovery did not finish")
            self.assertTrue(saw_recovery)
            self.assertEqual(value["measurement"]["output"], 100)
            # Diagnostics contain only progress metadata, never response text.
            self.assertNotIn("ignored", json.dumps(value))
