import json
import tempfile
import unittest
from pathlib import Path

from codex_rate.reader import SessionIndex, SessionReader
from test_metrics import row, sample


def lines(*records):
    return b"".join(json.dumps(r, ensure_ascii=False).encode() + b"\n" for r in records)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rollout.jsonl"

    def test_incremental_partial_line_is_counted_once_after_completion(self):
        data = lines(sample())
        self.path.write_bytes(lines(row("task_started", turn_id="t1")) + data[:30])
        reader = SessionReader(self.path)
        self.assertIsNone(reader.poll().output)
        with self.path.open("ab") as stream:
            stream.write(data[30:])
        self.assertEqual(reader.poll().output, 100)
        self.assertEqual(reader.poll().samples, 1)

    def test_startup_selects_modern_before_processing_legacy(self):
        legacy = row("token_count", info={"last_token_usage": {"input_tokens": 1000,
                     "cached_input_tokens": 500, "output_tokens": 900},
                     "total_token_usage": {"input_tokens": 1000,
                     "cached_input_tokens": 500, "output_tokens": 900}})
        self.path.write_bytes(lines(row("task_started", turn_id="t1"), legacy, sample()))
        self.assertEqual(SessionReader(self.path).poll().output, 100)

    def test_tail_missing_start_does_not_show_rate(self):
        data = lines(sample())
        self.path.write_bytes(lines(row("task_started", turn_id="t1")) +
                              b'{"type":"response_item","payload":{"ignored":"' +
                              b"x" * 3000 + b'"}}\n' + data)
        result = SessionReader(self.path, tail_bytes=len(data) + 30).poll()
        self.assertFalse(result.complete_start)
        self.assertIsNone(result.tps)

    def test_truncation_resets_previous_turn(self):
        self.path.write_bytes(lines(row("task_started", turn_id="t1"), sample()))
        reader = SessionReader(self.path)
        self.assertEqual(reader.poll().output, 100)
        self.path.write_bytes(lines(row("task_started", turn_id="t2")))
        result = reader.poll()
        self.assertEqual(result.turn_id, "t2")
        self.assertIsNone(result.output)

    def test_missing_file_is_visible_as_error(self):
        reader = SessionReader(self.path)
        reader.poll()
        self.assertEqual(reader.error, "FileNotFoundError")

    def test_malformed_initial_row_cannot_leave_valid_rate(self):
        self.path.write_bytes(lines(row("task_started", turn_id="t1")) + b"{oops}\n" + lines(sample()))
        reader = SessionReader(self.path)
        result = reader.poll()
        self.assertEqual(reader.malformed, 1)
        self.assertIsNone(result.tps)

    def test_empty_file_and_unrelated_unicode_do_not_invent_data(self):
        self.path.write_bytes(b"")
        reader = SessionReader(self.path)
        self.assertIsNone(reader.poll().tps)
        with self.path.open("ab") as stream:
            stream.write(lines({"type": "response_item", "payload": {"unused": "中文🙂"}}))
        self.assertIsNone(reader.poll().output)
        self.assertEqual(reader.malformed, 0)

    def test_next_complete_turn_recovers_from_historical_bad_line(self):
        self.path.write_bytes(b"{oops}\n")
        reader = SessionReader(self.path)
        self.assertIn("malformed-jsonl", reader.poll().warnings)
        with self.path.open("ab") as stream:
            stream.write(lines(row("task_started", turn_id="t1"), sample()))
        result = reader.poll()
        self.assertEqual(reader.malformed, 1)
        self.assertNotIn("malformed-jsonl", result.warnings)
        self.assertEqual(result.tps, 100)

    def test_bad_line_after_measurement_invalidates_current_rate(self):
        self.path.write_bytes(lines(row("task_started", turn_id="t1"), sample()) + b"oops\n")
        reader = SessionReader(self.path)
        self.assertIsNone(reader.poll().tps)
        self.assertIn("malformed-jsonl", reader.poll().warnings)

    def test_index_finds_requested_archived_session(self):
        folder = Path(self.temp.name) / "archived_sessions"
        folder.mkdir()
        wanted = folder / "rollout-12345678-aaaa-bbbb-cccc-123456789abc.jsonl"
        wanted.write_bytes(b"")
        index = SessionIndex(self.temp.name)
        index.refresh(force=True)
        self.assertEqual(index.find("12345678-aaaa-bbbb-cccc-123456789abc"), wanted)
        self.assertIsNone(index.find("not-present"))
