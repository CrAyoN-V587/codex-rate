"""Pure accounting. Effective TPS includes first-token/queue latency, not tool-only time."""

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class Usage:
    input: int = 0
    cached: int = 0
    output: int = 0

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            return None
        numbers = [value.get(k) for k in
                   ("input_tokens", "cached_input_tokens", "output_tokens")]
        if any(type(v) is not int or v < 0 for v in numbers):
            return None
        if numbers[1] > numbers[0]:
            return None
        return cls(*numbers)

    def __add__(self, other):
        return Usage(self.input + other.input, self.cached + other.cached,
                     self.output + other.output)


def union_ms(intervals):
    end = None
    total = 0
    for start, stop in sorted(intervals):
        if end is None or start >= end:
            total += stop - start
        elif stop > end:
            total += stop - end
        end = stop if end is None else max(end, stop)
    return total


def timestamp_ms(row):
    value = row.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return round(parsed.timestamp() * 1000) if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


@dataclass(frozen=True)
class Measurement:
    turn_id: str | None
    state: str
    output: int | None
    input: int | None
    cached: int | None
    cache_percent: float | None
    tps: float | None
    elapsed_ms: int | None
    complete_start: bool
    carrier: str
    samples: int
    warnings: tuple[str, ...]
    activity: str
    sampled_at_ms: int | None

    def to_dict(self):
        return asdict(self)


class Meter:
    TOOL_TYPES = {"CommandExecution", "FileChange", "McpToolCall", "WebSearch",
                  "ImageView", "Extension", "SubAgentActivity", "RequestUserInput"}
    MODEL_TYPES = {"Reasoning", "AgentMessage"}

    def __init__(self, modern=False):
        self.modern = modern
        self.turn_id = None
        self.started = False
        self.state = "idle"
        self.usage = Usage()
        self.official_turn = None
        self.seen = {}
        self.models = set()
        self.tools = set()
        self.samples = 0
        self.bad = False
        self.warnings = set()
        self.start_ms = None
        self.end_ms = None
        self.measured_ms = None
        self.activity = "idle"

    def begin(self, turn_id, started, start_ms=None):
        if self.turn_id == turn_id and self.started and started:
            return
        modern = self.modern
        self.__init__(modern)
        self.turn_id = turn_id
        self.started = started
        self.state = "waiting"
        self.activity = "waiting"
        self.start_ms = start_ms

    def _align(self, turn_id):
        if turn_id and turn_id != self.turn_id:
            self.begin(turn_id, False)

    def _publish(self):
        self.measured_ms = None
        if (self.start_ms is None or self.end_ms is None or
                self.end_ms <= self.start_ms):
            return
        def clip(intervals):
            return [(max(a, self.start_ms), min(b, self.end_ms)) for a, b in intervals
                    if min(b, self.end_ms) > max(a, self.start_ms)]
        models, tools = clip(self.models), clip(self.tools)
        # Exclude only tool time with no observed overlapping model activity.
        tool_only = union_ms(models + tools) - union_ms(models)
        self.measured_ms = self.end_ms - self.start_ms - tool_only

    def observe(self, row):
        if not isinstance(row, dict):
            return
        kind = row.get("type")
        p = row.get("payload")
        if not isinstance(p, dict):
            return
        event = p.get("type") if kind == "event_msg" else kind
        if event == "response_item":
            # Only read control metadata, never tool arguments or message bodies.
            # This describes the last observed activity, not child-agent usage.
            if not self.started or self.state in ("aborted", "completed"):
                return
            item_type = p.get("type")
            if item_type in ("function_call", "custom_tool_call"):
                name = str(p.get("name", "")).rsplit(".", 1)[-1]
                self.activity = "agent" if name in {
                    "spawn_agent", "wait_agent", "send_message", "followup_task",
                    "interrupt_agent", "list_agents"} else "tool"
            elif item_type in ("function_call_output", "custom_tool_call_output"):
                self.activity = "waiting-response"
            elif item_type == "reasoning" or (item_type == "message" and p.get("role") == "assistant"):
                self.activity = "model"
        elif event == "reader_error":
            self.bad = True
            self.warnings.add("malformed-jsonl")
        elif event == "task_started":
            self.begin(p.get("turn_id"), True, timestamp_ms(row))
        elif event == "item_completed":
            self._align(p.get("turn_id"))
            item = p.get("item")
            item_type = item.get("type") if isinstance(item, dict) else None
            if item_type not in self.MODEL_TYPES | self.TOOL_TYPES:
                return
            if self.state not in ("aborted", "completed"):
                if item_type in self.MODEL_TYPES:
                    self.activity = "model"
                elif item_type == "SubAgentActivity":
                    self.activity = "agent"
            start, end = p.get("started_at_ms"), p.get("completed_at_ms")
            if type(start) is not int or type(end) is not int or start <= 0 or end < start:
                self.bad = True
                self.warnings.add("invalid-item-timing")
            elif end > start:
                target = self.models if item_type in self.MODEL_TYPES else self.tools
                target.add((start, end))
        elif event == "token_usage_record":
            self._align(p.get("turn_id"))
            if not self.modern and self.samples:
                self.usage = Usage()
                self.seen.clear()
                self.samples = 0
                self.bad = True
                self.warnings.add("carrier-changed-mid-turn")
            self.modern = True
            key = p.get("response_id")
            if not isinstance(key, str) or not key:
                self.bad = True
                self.warnings.add("missing-response-id")
                return
            if self._sample(key, p.get("usage"), timestamp_ms(row)):
                turn = Usage.parse(p.get("turn_token_usage"))
                thread = Usage.parse(p.get("thread_token_usage"))
                if turn is not None and (turn == self.usage or (thread is not None and turn != thread)):
                    self.official_turn = turn
                    if self.started and turn != self.usage:
                        self.bad = True
                        self.warnings.add("turn-usage-mismatch")
                else:
                    # Some Codex versions copy thread totals into turn_token_usage.
                    self.official_turn = None
        elif event == "token_count" and not self.modern:
            info = p.get("info")
            if not isinstance(info, dict) or info.get("last_token_usage") is None:
                return
            total = Usage.parse(info.get("total_token_usage"))
            if total is None:
                self.bad = True
                self.warnings.add("missing-legacy-cumulative")
                return
            self._sample(total, info.get("last_token_usage"), timestamp_ms(row))
        elif event in ("task_complete", "turn_aborted"):
            self._align(p.get("turn_id"))
            self._publish()
            if event == "turn_aborted" or self.state == "aborted":
                self.state = "aborted"
            else:
                self.state = "completed"
            self.activity = self.state

    def _sample(self, key, raw, end_ms):
        usage = Usage.parse(raw)
        if usage is None:
            self.bad = True
            self.warnings.add("invalid-usage")
            return False
        if key in self.seen:
            if self.seen[key] != usage:
                self.bad = True
                self.warnings.add("conflicting-response-usage")
            return False
        self.seen[key] = usage
        self.samples += 1
        self.usage += usage
        if self.state not in ("aborted", "completed"):
            self.state = "active"
            if self.activity in ("idle", "waiting"):
                self.activity = "model"
        self.end_ms = end_ms
        self._publish()
        return True

    def snapshot(self):
        usage = self.official_turn or (self.usage if self.started and self.samples else None)
        warnings = set(self.warnings)
        if self.samples and not self.started:
            warnings.add("partial-turn")
        if self.samples and (self.measured_ms is None or self.measured_ms < 500):
            warnings.add("insufficient-timing")
        tps = None
        if (self.started and not self.bad and self.state != "aborted" and usage is not None
                and self.measured_ms is not None and self.measured_ms >= 500):
            tps = usage.output * 1000 / self.measured_ms
        return Measurement(
            self.turn_id, self.state,
            usage.output if usage else None, usage.input if usage else None,
            usage.cached if usage else None,
            usage.cached * 100 / usage.input if usage and usage.input else None,
            tps, self.measured_ms, self.started,
            "token_usage_record" if self.modern else "token_count",
            self.samples, tuple(sorted(warnings)), self.activity, self.end_ms)


def compact(value):
    if value is None:
        return "--"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)
