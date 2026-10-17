import os
import queue
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
        strip.tray = Mock(events=queue.SimpleQueue())
        strip.paint = Mock()
        strip.save = Mock()
        strip.show_details = Mock()
        strip.describe = Mock(return_value="details")
        strip.data = Mock(return_value={
            "thread": self.threads[0], "error": None, "mode": "ipc",
            "measurement": {"tps": 100, "state": "completed", "output": 200,
                            "cache_percent": 50}})

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
