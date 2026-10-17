import json
import struct
import unittest

from codex_rate.ipc import Frames, Selection


class IpcTests(unittest.TestCase):
    def test_partial_and_concatenated_frames(self):
        def frame(value):
            data = json.dumps(value).encode()
            return struct.pack("<I", len(data)) + data
        data = frame({"a": 1}) + frame({"b": 2})
        frames = Frames()
        self.assertEqual(frames.feed(data[:3]), [])
        self.assertEqual(frames.feed(data[3:8]), [])
        self.assertEqual(frames.feed(data[8:]), [{"a": 1}, {"b": 2}])

    def test_implausible_size_is_rejected(self):
        with self.assertRaises(ValueError):
            Frames().feed(struct.pack("<I", 9 * 1024 * 1024))

    def test_only_valid_followed_conversations_change_selection(self):
        selection = Selection()
        thread = "12345678-aaaa-bbbb-cccc-123456789abc"
        def follow(value, following):
            selection.observe({"method": "thread-stream-following-changed",
                               "params": {"conversationId": value, "following": following, "hostId": "local"}})
        follow("bad", True)
        self.assertIsNone(selection.snapshot()[0])
        follow(thread, True)
        self.assertEqual(selection.snapshot()[0], thread)
        follow("11111111-aaaa-bbbb-cccc-123456789abc", False)
        self.assertEqual(selection.snapshot()[0], thread)
        follow(thread, False)
        self.assertIsNone(selection.snapshot()[0])

    def test_remote_host_cannot_masquerade_as_local_same_id(self):
        selection = Selection()
        thread = "12345678-aaaa-bbbb-cccc-123456789abc"
        selection.observe({"method": "thread-stream-following-changed", "params": {
            "conversationId": thread, "following": True, "hostId": "remote-host"}})
        self.assertEqual(selection.snapshot()[2], "remote-session-unsupported")
        selection.observe({"method": "thread-stream-following-changed", "params": {
            "conversationId": thread, "following": False, "hostId": "remote-host"}})
        selection.observe({"method": "thread-stream-following-changed", "params": {
            "conversationId": thread, "following": True, "hostId": "local"}})
        self.assertIsNone(selection.snapshot()[2])

    def test_multiple_followed_streams_are_not_claimed_as_current_tab(self):
        selection = Selection()
        for thread in ("12345678-aaaa-bbbb-cccc-123456789abc", "11111111-aaaa-bbbb-cccc-123456789abc"):
            selection.observe({"method": "thread-stream-following-changed", "sourceClientId": "one-window",
                               "params": {"conversationId": thread, "hostId": "local", "following": True}})
        self.assertIsNone(selection.snapshot()[0])
        self.assertEqual(selection.snapshot()[2], "multiple-followed-sessions")
        self.assertEqual(len(selection.local_threads()), 2)
