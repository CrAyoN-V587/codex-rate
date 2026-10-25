import os
import queue
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from codex_rate.app import Strip


class PopupMenu:
    """Model a native menu whose command is delivered after popup returns."""

    def __init__(self, parent, **_):
        self.entries = {}
        self.destroyed = False
        self.grab_release = Mock()

    def add_command(self, **entry):
        self.entries[entry["label"]] = entry

    add_cascade = add_command

    def add_separator(self):
        pass

    def tk_popup(self, x, y):
        pass

    def destroy(self):
        self.destroyed = True

    def invoke(self, label):
        if self.destroyed:
            raise RuntimeError("menu destroyed before command delivery")
        entry = self.entries[label]
        if entry.get("state") != "disabled":
            entry["command"]()


class StripTests(unittest.TestCase):
    def setUp(self):
        self.strip = strip = Strip.__new__(Strip)
        strip.tk = SimpleNamespace(Menu=Mock(side_effect=PopupMenu), TclError=RuntimeError)
        strip.root = Mock()
        strip.root.winfo_reqwidth.return_value = 480
        strip.root.winfo_reqheight.return_value = 48
        strip.root.winfo_pointerx.return_value = 120
        strip.root.winfo_pointery.return_value = 160
        strip.native = Mock()
        strip.native.host.return_value = (10, (0, 0, 1200, 800), False)
        strip.native.menu_active.return_value = False
        strip.hwnd = 20
        strip.args = SimpleNamespace(preview=False, demo=False, diagnostics=None)
        strip.monitor = Mock()
        strip.monitor_running = True
        strip.startup = Mock()
        strip.startup.is_enabled.return_value = False
        self.threads = ["12345678-aaaa-bbbb-cccc-123456789abc",
                        "87654321-aaaa-bbbb-cccc-abcdef123456"]
        strip.monitor.index.paths = [Path("rollout-" + t + ".jsonl") for t in self.threads]
        strip.closed = False
        strip.menu = None
        strip.menu_open = False
        strip.menu_check_handle = None
        strip.detail = None
        strip.detail_text = None
        strip.tick_handle = strip.exit_handle = None
        strip.drag = None
        strip.force_show_until = 0
        strip.host_rect = (0, 0, 1200, 800)
        strip.settings = {"theme": "light", "right": 26, "bottom": 66}
        strip.accent = "#111111"
        strip.fields = [Mock(), Mock(), Mock()]
        strip.status = Mock()
        strip.last_detection = Mock()
        strip.tray = Mock(events=queue.SimpleQueue())
        strip.paint = Mock()
        strip.save = Mock()
        strip.show_details = Mock()
        strip.describe = Mock(return_value="details")
        strip.data = Mock(return_value={
            "thread": self.threads[0], "error": None, "mode": "ipc",
            "measurement": {"tps": 100, "state": "completed", "output": 200,
                            "cache_percent": 50}})

    def test_tool_and_agent_status_retain_trusted_values_but_loading_clears(self):
        strip = self.strip
        data = strip.data.return_value
        data["measurement"]["state"] = "active"
        for activity, label in (("tool", "工具"), ("agent", "代理"), ("waiting-response", "等待")):
            data["measurement"]["activity"] = activity
            strip.tick()
            self.assertEqual(strip.fields[0].configure.call_args.kwargs["text"], "~100.0 tok/s")
            self.assertEqual(strip.fields[1].configure.call_args.kwargs["text"], "200")
            self.assertEqual(strip.fields[2].configure.call_args.kwargs["text"], "50%")
            self.assertEqual(strip.status.configure.call_args.kwargs["text"], label)
        data["error"] = "conversation-loading"
        strip.tick()
        self.assertEqual(strip.fields[0].configure.call_args.kwargs["text"], "-- tok/s")
        self.assertEqual(strip.fields[1].configure.call_args.kwargs["text"], "--")
        self.assertEqual(strip.fields[2].configure.call_args.kwargs["text"], "--")

    def test_footer_age_advances_between_checks_and_clears_when_unavailable(self):
        strip = self.strip
        strip.data.return_value["detected_at"] = 1
        strip.data.return_value["measurement"]["state"] = "active"
        for now, expected in ((2, "上次检测：1秒之前"), (8, "上次检测：7秒之前"), (0, "上次检测：0秒之前")):
            with patch("codex_rate.app.time.monotonic", return_value=now):
                strip.tick()
            self.assertEqual(strip.last_detection.configure.call_args.kwargs["text"], expected)
        strip.data.return_value["error"] = "conversation-loading"
        strip.tick()
        self.assertEqual(strip.last_detection.configure.call_args.kwargs["text"], "上次检测：--")
        strip.data.return_value["error"] = None
        strip.data.return_value["detected_at"] = None
        strip.tick()
        self.assertEqual(strip.last_detection.configure.call_args.kwargs["text"], "上次检测：--")

    def test_completed_or_cancelled_turn_hides_detection_age(self):
        strip = self.strip
        strip.data.return_value["detected_at"] = 1
        for state in ("completed", "aborted", "idle"):
            strip.data.return_value["measurement"]["state"] = state
            strip.tick()
            self.assertEqual(strip.last_detection.configure.call_args.kwargs["text"], "上次检测：--")

    def test_details_explain_activity_age_and_missing_data_in_chinese(self):
        from codex_rate.metrics import Meter
        strip = self.strip
        strip.tray.error = None
        measurement = Meter().snapshot().to_dict()
        measurement.update(activity="agent", sampled_at_ms=1000)
        data = dict(mode="active", thread="test", error="active-reader-stale", measurement=measurement)
        with patch("codex_rate.app.time.time", return_value=4):
            description = Strip.describe(strip, data)
        self.assertIn("最近活动：子代理调度", description)
        self.assertIn("距最近计量：3 秒", description)
        self.assertIn("页面识别暂未响应", description)
        self.assertIn("子代理用量不并入主会话", description)

    def test_menu_commands_can_run_after_popup_returns(self):
        strip = self.strip
        strip.close = Mock()
        menus = []

        def make_menu(*args, **kwargs):
            menu = PopupMenu(*args, **kwargs)
            menus.append(menu)
            return menu

        strip.tk.Menu.side_effect = make_menu
        strip.popup()
        menu = menus[0]
        menu.invoke("指标详情")
        strip.show_details.assert_called_once()
        menu.invoke("自动跟随会话")
        strip.monitor.pin.assert_called_with(None)
        menu.invoke("固定到此会话")
        strip.monitor.pin.assert_called_with(self.threads[0])
        recent = menu.entries["选择最近会话"]["menu"]
        for thread in self.threads:
            recent.invoke(thread[:8] + "…" + thread[-6:])
            strip.monitor.pin.assert_called_with(thread)
        menu.invoke("切换明暗主题")
        self.assertEqual(strip.settings["theme"], "dark")
        strip.paint.assert_called_once()
        strip.settings.update(right=300, bottom=200)
        menu.invoke("重置位置")
        self.assertEqual(strip.settings["right"], 26)
        self.assertEqual(strip.settings["bottom"], 66)
        strip.native.place.assert_called_with(strip.root, 694, 686)
        self.assertEqual(strip.save.call_count, 2)
        menu.invoke("退出 Codex Rate")
        strip.close.assert_called_once()

    def test_startup_menu_enables_and_disables_only_via_startup_module(self):
        strip = self.strip
        strip.popup()
        strip.menu.invoke("启用开机自启动")
        strip.startup.enable.assert_called_once()
        strip.startup.disable.assert_not_called()
        strip.startup.is_enabled.return_value = True
        strip.menu_open = False
        strip.popup()
        strip.menu.invoke("关闭开机自启动")
        strip.startup.disable.assert_called_once()

    def test_tray_startup_query_error_keeps_exit_and_next_tick_available(self):
        strip = self.strip
        strip.close = Mock()
        for error in (PermissionError("denied"), OSError("registry unavailable")):
            with self.subTest(error=type(error).__name__):
                strip.startup.is_enabled.side_effect = error
                strip.tray.events.put("menu")
                strip.root.after.reset_mock()
                strip.tick()
                self.assertTrue(strip.menu_open)
                self.assertEqual(strip.menu.entries["自启动状态不可用"]["state"], "disabled")
                strip.menu.invoke("自启动状态不可用")
                strip.startup.enable.assert_not_called()
                strip.startup.disable.assert_not_called()
                strip.menu.invoke("指标详情")
                strip.menu.invoke("退出 Codex Rate")
                strip.root.after.assert_called_once_with(400, strip.tick)
                self.assertIs(strip.tick_handle, strip.root.after.return_value)
                strip.check_menu()
        self.assertEqual(strip.show_details.call_count, 2)
        self.assertEqual(strip.close.call_count, 2)

    def test_background_waits_without_starting_readers_then_attaches(self):
        strip = self.strip
        strip.monitor_running = False
        strip.native.host.return_value = (None, None, True)
        strip.tick()
        strip.monitor.start.assert_not_called()
        strip.root.withdraw.assert_called_once()
        strip.root.deiconify.assert_not_called()
        strip.native.host.return_value = (10, (0, 0, 1200, 800), True)
        strip.tick()
        strip.monitor.start.assert_called_once()
        self.assertTrue(strip.monitor_running)
        strip.tick()
        strip.monitor.start.assert_called_once()

    def test_host_exit_stops_readers_and_a_new_host_restarts_cleanly(self):
        strip = self.strip
        strip.args.home = Path("codex-home")
        old = strip.monitor
        old.pinned = None
        replacement = Mock()
        with patch("codex_rate.app.Monitor", return_value=replacement):
            strip.sync_monitor(False)
        old.close.assert_called_once()
        self.assertFalse(strip.monitor_running)
        replacement.start.assert_not_called()
        strip.sync_monitor(True)
        replacement.start.assert_called_once()
        self.assertTrue(strip.monitor_running)

    def test_dismissal_restores_nonactivating_strip_and_allows_reopen(self):
        strip = self.strip
        strip.popup()
        first_menu = strip.menu
        strip.native.interactive.assert_called_with(strip.hwnd, True)
        strip.native.menu_active.return_value = True
        strip.check_menu()
        self.assertTrue(strip.menu_open)
        first_menu.grab_release.assert_not_called()
        strip.native.menu_active.return_value = False
        strip.check_menu()
        self.assertFalse(strip.menu_open)
        strip.native.interactive.assert_called_with(strip.hwnd, False)
        # A queued native selection remains callable even after tracking ends.
        first_menu.invoke("指标详情")
        strip.popup()
        self.assertTrue(first_menu.destroyed)
        self.assertIsNot(first_menu, strip.menu)
        strip.menu.invoke("指标详情")
        self.assertEqual(strip.show_details.call_count, 2)

    def test_no_session_disables_pin_and_empty_recent_menu(self):
        strip = self.strip
        strip.data.return_value["thread"] = None
        strip.monitor.index.paths = []
        strip.popup()
        strip.menu.invoke("固定到此会话")
        strip.monitor.pin.assert_not_called()
        self.assertEqual(strip.menu.entries["选择最近会话"]["state"], "disabled")

    def test_open_menu_details_and_drag_survive_host_losing_foreground(self):
        strip = self.strip
        for interaction in ("menu", "details", "drag"):
            with self.subTest(interaction=interaction):
                strip.root.reset_mock()
                strip.menu_open = interaction == "menu"
                strip.detail = Mock() if interaction == "details" else None
                strip.detail_text = Mock()
                strip.drag = (10, 10) if interaction == "drag" else None
                strip.tick()
                strip.root.deiconify.assert_called_once()
                strip.root.withdraw.assert_not_called()
        strip.root.reset_mock()
        strip.menu_open = False
        strip.detail = None
        strip.drag = None
        strip.tick()
        strip.root.withdraw.assert_called_once()

    def test_reset_position_without_host_moves_to_visible_default(self):
        strip = self.strip
        strip.host_rect = None
        strip.reset_position()
        strip.native.place.assert_called_once_with(strip.root, 100, 100)

    def test_initial_hidden_layout_matches_painted_surface_size(self):
        strip = self.strip
        strip.frame = Mock()
        strip.frame.winfo_reqwidth.return_value = 480
        strip.frame.winfo_reqheight.return_value = 50
        strip.surface = Mock()
        strip.outline, strip.body = 1, 2
        strip.frame_window = 3
        strip.layout()
        requested = strip.surface.configure.call_args.kwargs
        geometry = strip.root.geometry.call_args.args[0]
        self.assertEqual(geometry, f"{requested['width']}x{requested['height']}")

    def test_exit_cancels_menu_checks_before_destroying_window(self):
        strip = self.strip
        strip.menu_check_handle = "menu-check"
        strip.close()
        self.assertTrue(strip.closed)
        strip.root.after_cancel.assert_called_once_with("menu-check")
        strip.root.destroy.assert_called_once()
        strip.native.menu_active.reset_mock()
        strip.check_menu()
        strip.native.menu_active.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Win32 boundary")
class NativeInteractionTests(unittest.TestCase):
    def test_menu_activation_preserves_other_extended_window_styles(self):
        from codex_rate.windows import Native

        native = Native.__new__(Native)
        native.user = Mock()
        other_styles = 0x80000 | 0x80  # Layered transparent corners and tool window.
        native.user.GetWindowLongPtrW.return_value = other_styles | 0x08000000
        native.interactive(30, True)
        native.user.SetWindowLongPtrW.assert_called_with(30, -20, other_styles)
        native.user.SetForegroundWindow.assert_called_once_with(30)
        native.user.GetWindowLongPtrW.return_value = other_styles
        native.interactive(30, False)
        native.user.SetWindowLongPtrW.assert_called_with(30, -20, other_styles | 0x08000000)
        native.user.SetForegroundWindow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
