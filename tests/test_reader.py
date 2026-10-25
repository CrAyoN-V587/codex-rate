import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_rate.reader import HEADER_BYTES, TAIL_BYTES, SessionIndex, SessionReader
from test_metrics import item, row, sample, usage


def lines(*records):
    return b"".join(json.dumps(r, ensure_ascii=False).encode() + b"\n" for r in records)


def large_record(stream, kind, size):
    stream.write(b'{"type":"' + kind.encode() + b'","payload":{"ignored":"')
    block = b"x" * min(size, 1024 * 1024)
    while size:
        count = min(size, len(block))
        stream.write(block[:count])
        size -= count
    stream.write(b'"}}\n')


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rollout.jsonl"

    def drain(self, reader):
        for _ in range(1000):
            before = reader.recovery_bytes
            result = reader.poll()
            self.assertLessEqual(reader.recovery_bytes - before, reader.tail_bytes)
            if not reader.recovering and not reader.backlog_bytes:
                return result
            if reader.recovering:
                self.assertIsNone(result.output)
                self.assertIsNone(result.tps)
        self.fail("reader did not finish its bounded recovery")

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

    def test_start_before_initial_tail_is_recovered_across_polls(self):
        data = lines(sample())
        self.path.write_bytes(lines(row("task_started", turn_id="t1")) +
                              b'{"type":"response_item","payload":{"ignored":"' +
                              b"x" * 3000 + b'"}}\n' + data)
        reader = SessionReader(self.path, tail_bytes=len(data) + 30)
        self.assertIsNone(reader.poll().output)
        self.assertTrue(reader.recovering)
        result = self.drain(reader)
        self.assertTrue(result.complete_start)
        self.assertEqual(result.tps, 100)
        self.assertEqual(reader.recovery_state, "complete")
        self.assertFalse(reader.recovery_limited)

    def test_tail_missing_start_at_recovery_limit_does_not_show_rate(self):
        data = lines(sample())
        self.path.write_bytes(lines(row("task_started", turn_id="t1")) +
                              b'{"type":"response_item","payload":{"ignored":"' +
                              b"x" * 3000 + b'"}}\n' + data)
        reader = SessionReader(self.path, recovery_bytes=len(data) + 30)
        result = self.drain(reader)
        self.assertFalse(result.complete_start)
        self.assertIsNone(result.tps)
        self.assertIn("partial-turn", result.warnings)
        self.assertTrue(reader.recovery_limited)
        self.assertEqual(reader.recovery_state, "partial")
        self.assertEqual(reader.malformed, 0)
        with self.path.open("ab") as stream:
            stream.write(lines(row("task_started", 2000, turn_id="t2"),
                               sample(ms=3000, turn="t2")))
        self.assertEqual(self.drain(reader).tps, 100)
        self.assertEqual(reader.recovery_state, "complete")

    def test_recovery_limit_at_line_boundary_keeps_first_complete_record(self):
        data = lines(sample(20, total=usage(120), thread=usage(1000)))
        self.path.write_bytes(lines(row("task_started", turn_id="t1")) + data)
        reader = SessionReader(self.path, recovery_bytes=len(data))
        result = self.drain(reader)
        self.assertEqual(result.output, 120)
        self.assertFalse(result.complete_start)
        self.assertIsNone(result.tps)

    def test_large_tool_and_compaction_rows_match_startup_and_incremental(self):
        self.path.write_bytes(lines(row("task_started", turn_id="t1"), sample()))
        incremental = SessionReader(self.path)
        self.assertEqual(incremental.poll().output, 100)
        with self.path.open("ab") as stream:
            large_record(stream, "response_item", 11 * 1024 * 1024)
            large_record(stream, "compacted", 32 * 1024 * 1024)
            stream.write(lines(item("McpToolCall", 1000, 3000),
                               sample(200, 5000, "r2", total=usage(300, 2000, 1000)),
                               row("task_complete", 6000, turn_id="t1")))
        current = self.drain(incremental)
        startup = SessionReader(self.path)
        restored = self.drain(startup)
        self.assertEqual(restored.to_dict(), current.to_dict())
        self.assertEqual((restored.output, restored.tps), (300, 100))
        self.assertTrue(restored.complete_start)
        for reader in (incremental, startup):
            self.assertEqual(reader.malformed, 0)
            self.assertEqual(reader.skipped_non_metric, 2)
            self.assertLessEqual(len(reader.pending), HEADER_BYTES)
        self.assertGreater(startup.recovery_bytes, TAIL_BYTES)

    def test_other_known_non_metric_envelopes_are_skipped_when_oversized(self):
        with patch("codex_rate.reader.MAX_LINE", 1024), patch("codex_rate.reader.CHUNK_BYTES", 8192):
            with self.path.open("wb") as stream:
                stream.write(lines(row("task_started", turn_id="t1")))
                for kind in ("world_state", "session_meta", "turn_context"):
                    large_record(stream, kind, 4000)
                stream.write(lines(sample()))
            reader = SessionReader(self.path)
            self.assertEqual(self.drain(reader).tps, 100)
            self.assertEqual(reader.skipped_non_metric, 3)
            self.assertEqual(reader.malformed, 0)

    def test_payload_types_and_unknown_or_invalid_headers_do_not_hide_damage(self):
        prefixes = [
            b'{"type":"future_record","payload":{"type":"compacted","ignored":"',
            b'{"type":"event_msg","payload":{"type":"response_item","ignored":"',
            b'{"payload":{"type":"response_item","ignored":"',
            b'{"payload":{"type":"compacted"},"type":"token_usage_record","ignored":"',
            b'{"quoted":"\\"type\\":\\"compacted\\"","ignored":"',
            b'{"type":"response_item"x,"payload":{"ignored":"',
            b'{"type":"response_item","payload":{"ignored":"\xff',
        ]
        with patch("codex_rate.reader.MAX_LINE", 1024), patch("codex_rate.reader.CHUNK_BYTES", 127):
            for prefix in prefixes:
                with self.subTest(prefix=prefix):
                    self.path.write_bytes(lines(row("task_started", turn_id="t1")) +
                                          prefix + b"x" * 4000 + b'"}}\n' + lines(sample()))
                    reader = SessionReader(self.path)
                    result = self.drain(reader)
                    self.assertEqual(reader.malformed, 1)
                    self.assertEqual(reader.skipped_non_metric, 0)
                    self.assertIn("malformed-jsonl", result.warnings)
                    self.assertIsNone(result.tps)

    def test_unicode_cut_at_header_limit_does_not_damage_known_giant_line(self):
        prefix = b'{"type":"response_item","payload":{"ignored":"'
        # The bounded header ends after the first byte of this four-byte codepoint.
        body = prefix + b"x" * (HEADER_BYTES - len(prefix) - 1) + "🙂".encode() + b"x" * 4000
        self.path.write_bytes(lines(row("task_started", turn_id="t1")) + body + b'"}}\n' + lines(sample()))
        with patch("codex_rate.reader.MAX_LINE", HEADER_BYTES + 1024), patch("codex_rate.reader.CHUNK_BYTES", 4096):
            reader = SessionReader(self.path)
            self.assertEqual(self.drain(reader).tps, 100)
        self.assertEqual(reader.skipped_non_metric, 1)
        self.assertEqual(reader.malformed, 0)

    def test_known_giant_half_line_is_skipped_once_until_its_newline(self):
        self.path.write_bytes(lines(row("task_started", turn_id="t1"), sample()))
        reader = SessionReader(self.path)
        self.assertEqual(reader.poll().output, 100)
        with patch("codex_rate.reader.MAX_LINE", 1024), patch("codex_rate.reader.CHUNK_BYTES", 127):
            with self.path.open("ab") as stream:
                stream.write(b'{"type":"response_item","payload":{"ignored":"' + b"x" * 4000)
            self.assertEqual(reader.poll().output, 100)
            self.assertTrue(reader.dropping)
            self.assertEqual(reader.pending, b"")
            with self.path.open("ab") as stream:
                stream.write(b"x" * 4000 + b'"}}\r\n' +
                             lines(sample(ms=2000, response="r2", total=usage(200, 2000, 1000))))
            self.assertEqual(self.drain(reader).tps, 100)
        self.assertFalse(reader.dropping)
        self.assertEqual(reader.malformed, 0)
        self.assertEqual(reader.skipped_non_metric, 1)

    def test_small_response_item_is_passed_through_to_meter(self):
        record = {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1",
                                                        "name": "exec", "namespace": "functions"}}
        reader = SessionReader(self.path)
        self.assertEqual(reader._decode(lines(record)), [record])

    def test_modern_carrier_is_selected_before_cross_chunk_replay(self):
        legacy = row("token_count", 1000, info={"last_token_usage": usage(900),
                                               "total_token_usage": usage(900)})
        with self.path.open("wb") as stream:
            stream.write(lines(row("task_started", turn_id="t1"), legacy))
            large_record(stream, "response_item", 4000)
            stream.write(lines(sample()))
        reader = SessionReader(self.path, tail_bytes=256)
        result = self.drain(reader)
        self.assertEqual((result.output, result.tps), (100, 100))
        self.assertNotIn("carrier-changed-mid-turn", result.warnings)

    def test_rotation_clears_an_unfinished_dropped_line(self):
        self.path.write_bytes(lines(row("task_started", turn_id="t1")))
        reader = SessionReader(self.path)
        reader.poll()
        with patch("codex_rate.reader.MAX_LINE", 1024):
            with self.path.open("ab") as stream:
                stream.write(b'{"type":"compacted","payload":"' + b"x" * 4000)
            reader.poll()
            self.assertTrue(reader.dropping)
            replacement = self.path.with_suffix(".new")
            replacement.write_bytes(lines(row("task_started", turn_id="t2"), sample(turn="t2")))
            replacement.replace(self.path)
            result = self.drain(reader)
        self.assertEqual((result.turn_id, result.tps), ("t2", 100))
        self.assertEqual(reader.skipped_non_metric, 0)
        self.assertFalse(reader.dropping)

    def test_truncation_during_backward_search_restarts_recovery(self):
        with self.path.open("wb") as stream:
            stream.write(lines(row("task_started", turn_id="t1")))
            large_record(stream, "response_item", 4000)
        reader = SessionReader(self.path, tail_bytes=256)
        reader.poll()
        self.assertTrue(reader.recovering)
        self.path.write_bytes(lines(row("task_started", turn_id="t2"), sample(turn="t2")))
        result = self.drain(reader)
        self.assertEqual((result.turn_id, result.tps), ("t2", 100))
        self.assertFalse(reader.recovery_limited)

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
