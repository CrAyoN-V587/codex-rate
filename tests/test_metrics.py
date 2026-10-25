import unittest
from datetime import datetime, timezone

from codex_rate.metrics import Meter, Usage, union_ms

BASE = 1792195200000


def row(event, ms=0, **payload):
    modern = event == "token_usage_record"
    return {"type": event if modern else "event_msg",
            "timestamp": datetime.fromtimestamp((BASE + ms) / 1000, timezone.utc).isoformat(),
            "payload": payload if modern else dict(type=event, **payload)}


def usage(output=100, input=1000, cached=500):
    return dict(input_tokens=input, cached_input_tokens=cached, output_tokens=output)


def sample(output=100, ms=1000, response="r1", turn="t1", total=None, thread=None):
    value = usage(output)
    return row("token_usage_record", ms, turn_id=turn, response_id=response,
               usage=value, turn_token_usage=total or value,
               thread_token_usage=thread or total or value)


def item(kind, start, end, turn="t1"):
    return row("item_completed", end, turn_id=turn, item={"type": kind},
               started_at_ms=BASE + start, completed_at_ms=BASE + end)


def started(modern=True):
    meter = Meter(modern)
    meter.observe(row("task_started", turn_id="t1"))
    return meter


class MeterTests(unittest.TestCase):
    def test_tools_and_agent_dispatch_keep_last_measurement(self):
        meter = started()
        meter.observe(sample())
        original = meter.snapshot()
        for name, expected in (("functions.exec", "tool"), ("spawn_agent", "agent"), ("wait_agent", "agent")):
            meter.observe({"type": "response_item", "payload": {
                "type": "function_call", "name": name, "call_id": "call-a"}})
            result = meter.snapshot()
            self.assertEqual(result.activity, expected)
            self.assertEqual((result.tps, result.output, result.cache_percent),
                             (original.tps, original.output, original.cache_percent))
            self.assertEqual(result.sampled_at_ms, BASE + 1000)
        meter.observe({"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-a"}})
        self.assertEqual(meter.snapshot().activity, "waiting-response")
        self.assertEqual(meter.snapshot().samples, 1)

    def test_call_before_usage_record_keeps_activity_and_zero_agent_timing(self):
        meter = started()
        meter.observe({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec"}})
        meter.observe(sample())
        self.assertEqual(meter.snapshot().activity, "tool")
        meter.observe(item("SubAgentActivity", 1000, 1000))
        self.assertEqual(meter.snapshot().activity, "agent")
        self.assertEqual(meter.snapshot().tps, 100)
        meter.observe(item("Reasoning", 1000, 2000))
        self.assertEqual(meter.snapshot().activity, "model")

    def test_activity_does_not_leak_from_previous_turn_or_late_tool_output(self):
        meter = started()
        meter.observe(sample())
        meter.observe(row("task_complete", 2000, turn_id="t1"))
        meter.observe({"type": "response_item", "payload": {"type": "function_call_output"}})
        self.assertEqual(meter.snapshot().activity, "completed")
        meter.observe(row("task_started", 3000, turn_id="t2"))
        self.assertEqual(meter.snapshot().activity, "waiting")
        self.assertIsNone(meter.snapshot().sampled_at_ms)
        self.assertIsNone(meter.snapshot().output)

    def test_output_and_cache_are_distinct_from_total_and_reasoning(self):
        meter = started()
        record = sample()
        record["payload"]["usage"].update(reasoning_output_tokens=40, total_tokens=1100)
        meter.observe(record)
        result = meter.snapshot()
        self.assertEqual((result.output, result.cache_percent, result.tps), (100, 50, 100))

    def test_tool_arguments_without_model_items_still_have_time(self):
        meter = started()
        meter.observe(sample(100, 1000))
        meter.observe(sample(100, 3000, "r2", total=usage(200, 2000, 1000)))
        self.assertAlmostEqual(meter.snapshot().tps, 200 / 3)

    def test_tool_time_is_excluded_once_even_when_overlapping(self):
        meter = started()
        meter.observe(item("CommandExecution", 1000, 3000))
        meter.observe(item("McpToolCall", 2000, 4000))
        meter.observe(sample(200, 5000))
        self.assertEqual(meter.snapshot().tps, 100)

    def test_model_work_overlapping_tool_remains_in_denominator(self):
        meter = started()
        meter.observe(item("CommandExecution", 1000, 4000))
        meter.observe(item("Reasoning", 2000, 3000))
        meter.observe(sample(300, 5000))
        self.assertEqual(meter.snapshot().tps, 100)

    def test_zero_length_item_is_resolution_noise(self):
        meter = started()
        meter.observe(item("AgentMessage", 100, 100))
        meter.observe(sample())
        self.assertEqual(meter.snapshot().tps, 100)

    def test_negative_item_timing_suppresses_tps(self):
        meter = started()
        meter.observe(item("Reasoning", 200, 100))
        meter.observe(sample())
        self.assertIsNone(meter.snapshot().tps)

    def test_modern_deduplicates_same_response_but_not_equal_usage(self):
        meter = started()
        meter.observe(sample())
        meter.observe(sample())
        meter.observe(sample(ms=2000, response="r2", total=usage(200, 2000, 1000)))
        self.assertEqual((meter.snapshot().output, meter.snapshot().samples), (200, 2))

    def test_conflicting_response_id_invalidates_timing(self):
        meter = started()
        meter.observe(sample())
        meter.observe(sample(200))
        self.assertIsNone(meter.snapshot().tps)

    def test_lagging_legacy_events_do_not_replace_modern(self):
        meter = started()
        meter.observe(sample(200))
        meter.observe(row("token_count", 2000, info={"last_token_usage": usage(70),
                                                    "total_token_usage": usage(70)}))
        self.assertEqual(meter.snapshot().output, 200)

    def test_legacy_dedup_uses_cumulative_identity(self):
        meter = started(False)
        first = row("token_count", 1000, info={"last_token_usage": usage(),
                                               "total_token_usage": usage()})
        second = row("token_count", 2000, info={"last_token_usage": usage(),
                                                "total_token_usage": usage(200, 2000, 1000)})
        for record in (first, first, second):
            meter.observe(record)
        self.assertEqual((meter.snapshot().output, meter.snapshot().tps), (200, 100))

    def test_partial_tail_uses_official_turn_but_no_rate(self):
        meter = Meter(True)
        meter.observe(sample(20, total=usage(120, 1000, 500), thread=usage(1000, 10000, 5000)))
        result = meter.snapshot()
        self.assertEqual((result.output, result.cache_percent), (120, 50))
        self.assertIsNone(result.tps)
        self.assertIn("partial-turn", result.warnings)

    def test_partial_tail_thread_copy_does_not_pretend_to_be_turn(self):
        meter = Meter(True)
        total = usage(1000, 10000, 5000)
        meter.observe(sample(20, total=total, thread=total))
        self.assertIsNone(meter.snapshot().output)

    def test_full_turn_rejects_thread_copy_and_uses_response_sum(self):
        meter = started()
        total = usage(1000, 10000, 5000)
        meter.observe(sample(20, total=total, thread=total))
        self.assertEqual(meter.snapshot().output, 20)

    def test_mismatch_with_official_turn_suppresses_rate(self):
        meter = started()
        meter.observe(sample(20, total=usage(120), thread=usage(1000)))
        self.assertEqual(meter.snapshot().output, 120)
        self.assertIsNone(meter.snapshot().tps)

    def test_cancel_is_latched_across_late_usage_and_completion(self):
        meter = started()
        meter.observe(sample())
        meter.observe(row("turn_aborted", 1100, turn_id="t1"))
        meter.observe(sample(ms=2000, response="r2", total=usage(200, 2000, 1000)))
        meter.observe(row("task_complete", 2200, turn_id="t1"))
        self.assertEqual(meter.snapshot().state, "aborted")
        self.assertIsNone(meter.snapshot().tps)

    def test_next_turn_clears_cancel_and_previous_values(self):
        meter = started()
        meter.observe(sample())
        meter.observe(row("turn_aborted", turn_id="t1"))
        meter.observe(row("task_started", 2000, turn_id="t2"))
        self.assertIsNone(meter.snapshot().output)
        meter.observe(sample(50, 3000, "r2", "t2"))
        self.assertEqual(meter.snapshot().tps, 50)

    def test_completion_retains_last_response_boundary_not_tail_wait(self):
        meter = started()
        meter.observe(sample())
        meter.observe(row("task_complete", 9000, turn_id="t1"))
        self.assertEqual(meter.snapshot().tps, 100)
        self.assertEqual(meter.snapshot().state, "completed")

    def test_missing_timestamp_and_short_windows_do_not_show_rate(self):
        for record in (dict(type="event_msg", payload=dict(type="task_started", turn_id="t1")),
                       row("task_started", turn_id="t1")):
            meter = Meter(True)
            meter.observe(record)
            meter.observe(sample(ms=200))
            self.assertIsNone(meter.snapshot().tps)

    def test_zero_input_cache_is_unavailable(self):
        meter = started()
        record = sample()
        record["payload"]["usage"] = usage(100, 0, 0)
        record["payload"]["turn_token_usage"] = usage(100, 0, 0)
        meter.observe(record)
        self.assertIsNone(meter.snapshot().cache_percent)

    def test_invalid_usage_types_and_cache_are_rejected(self):
        for value in (usage(-1), usage(input=True), usage(input=10, cached=20), {}):
            self.assertIsNone(Usage.parse(value))

    def test_union_handles_nested_adjacent_and_disjoint_intervals(self):
        self.assertEqual(union_ms([(0, 5), (1, 3), (4, 10), (10, 11), (15, 17)]), 13)
