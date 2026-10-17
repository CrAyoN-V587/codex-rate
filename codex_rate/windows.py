"""Small Win32 boundary: host discovery, non-activating strip and tray icon."""

import ctypes as c
import os
import queue
import threading
import time
from ctypes import wintypes as w

LRESULT = c.c_ssize_t
WNDPROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WindowClass(c.Structure):
    _fields_ = [("style", w.UINT), ("proc", WNDPROC), ("cls_extra", c.c_int),
                ("wnd_extra", c.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
                ("cursor", w.HANDLE), ("background", w.HBRUSH),
                ("menu", w.LPCWSTR), ("name", w.LPCWSTR)]


class NotifyIcon(c.Structure):
    _fields_ = [("size", w.DWORD), ("hwnd", w.HWND), ("id", w.UINT),
                ("flags", w.UINT), ("callback", w.UINT), ("icon", w.HICON),
                ("tip", w.WCHAR * 128), ("state", w.DWORD), ("mask", w.DWORD),
                ("info", w.WCHAR * 256), ("version", w.UINT),
                ("title", w.WCHAR * 64), ("info_flags", w.DWORD),
                ("guid", c.c_byte * 16), ("balloon", w.HICON)]


class GuiThreadInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("flags", w.DWORD),
                ("active", w.HWND), ("focus", w.HWND), ("capture", w.HWND),
                ("menu_owner", w.HWND), ("move_size", w.HWND),
                ("caret", w.HWND), ("caret_rect", w.RECT)]


class Native:
    def __init__(self):
        self.user = c.WinDLL("user32", use_last_error=True)
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.shell = c.WinDLL("shell32", use_last_error=True)
        self._bind(self.user, "GetForegroundWindow", [], w.HWND)
        self._bind(self.user, "GetWindowThreadProcessId", [w.HWND, c.POINTER(w.DWORD)], w.DWORD)
        self._bind(self.user, "GetAncestor", [w.HWND, w.UINT], w.HWND)
        self._bind(self.user, "GetWindowRect", [w.HWND, c.POINTER(w.RECT)], w.BOOL)
        self._bind(self.user, "IsWindowVisible", [w.HWND], w.BOOL)
        self._bind(self.user, "IsIconic", [w.HWND], w.BOOL)
        self._bind(self.user, "GetWindowLongPtrW", [w.HWND, c.c_int], c.c_ssize_t)
        self._bind(self.user, "SetWindowLongPtrW", [w.HWND, c.c_int, c.c_ssize_t], c.c_ssize_t)
        self._bind(self.user, "GetGUIThreadInfo", [w.DWORD, c.POINTER(GuiThreadInfo)], w.BOOL)
        self._bind(self.kernel, "GetCurrentThreadId", [], w.DWORD)
        self._bind(self.kernel, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
        self._bind(self.kernel, "CloseHandle", [w.HANDLE], w.BOOL)
        self._bind(self.kernel, "GetPackageFamilyName",
                   [w.HANDLE, c.POINTER(w.UINT), w.LPWSTR], w.LONG)
        self._bind(self.user, "EnumWindows", [c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM), w.LPARAM], w.BOOL)
        self._bind(self.user, "SetForegroundWindow", [w.HWND], w.BOOL)
        self._bind(self.user, "SetWindowPos", [w.HWND, w.HWND, c.c_int, c.c_int,
                   c.c_int, c.c_int, w.UINT], w.BOOL)
        self._bind(self.user, "PostMessageW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL)
        self._bind(self.user, "DefWindowProcW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], LRESULT)
        self._bind(self.user, "LoadIconW", [w.HINSTANCE, c.c_void_p], w.HICON)
        self._bind(self.user, "CreateWindowExW", [w.DWORD, w.LPCWSTR, w.LPCWSTR,
                   w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND,
                   w.HMENU, w.HINSTANCE, w.LPVOID], w.HWND)
        self._bind(self.kernel, "GetModuleHandleW", [w.LPCWSTR], w.HMODULE)
        self._bind(self.shell, "Shell_NotifyIconW", [w.DWORD, c.POINTER(NotifyIcon)], w.BOOL)
        self._bind(self.kernel, "CreateMutexW", [w.LPVOID, w.BOOL, w.LPCWSTR], w.HANDLE)
        self.pid_cache = {}
        self.hosts = []
        self.scan_at = 0.0
        self.previous_host = None
        self.mutex = None

    @staticmethod
    def _bind(lib, name, args, result):
        method = getattr(lib, name)
        method.argtypes, method.restype = args, result

    def dpi(self):
        try:
            self.user.SetProcessDpiAwarenessContext(c.c_void_p(-4))
        except (AttributeError, OSError):
            pass

    def single_instance(self, suffix=""):
        self.mutex = self.kernel.CreateMutexW(None, False,
            "Local\\CodexRate-" + os.environ.get("USERNAME", "user") + suffix)
        if not self.mutex:
            raise c.WinError(c.get_last_error())
        return c.get_last_error() != 183

    def pid(self, hwnd):
        value = w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, c.byref(value))
        return value.value

    def is_codex(self, pid):
        if pid in self.pid_cache:
            return self.pid_cache[pid]
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        valid = False
        if handle:
            try:
                size = w.UINT(256)
                family = c.create_unicode_buffer(size.value)
                valid = (self.kernel.GetPackageFamilyName(handle, c.byref(size), family) == 0
                         and family.value.startswith("OpenAI.Codex_"))
            finally:
                self.kernel.CloseHandle(handle)
        self.pid_cache[pid] = valid
        return valid

    def host(self):
        if time.monotonic() - self.scan_at > 3:
            self.scan_at = time.monotonic()
            self.pid_cache.clear()
            windows = []

            @c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
            def collect(hwnd, _):
                if self.user.IsWindowVisible(hwnd) and self.is_codex(self.pid(hwnd)):
                    rect = w.RECT()
                    self.user.GetWindowRect(hwnd, c.byref(rect))
                    if rect.right - rect.left > 300 and rect.bottom - rect.top > 200:
                        windows.append(hwnd)
                return True

            self.user.EnumWindows(collect, 0)
            self.hosts = windows
        foreground = self.user.GetForegroundWindow()
        chosen = foreground if foreground in self.hosts else self.previous_host
        if chosen not in self.hosts:
            chosen = self.hosts[0] if self.hosts else None
        self.previous_host = chosen
        if not chosen:
            return None, None, True
        rect = w.RECT()
        if not self.user.GetWindowRect(chosen, c.byref(rect)):
            return chosen, None, False
        visible = not self.user.IsIconic(chosen) and (
            foreground == chosen or self.pid(foreground) == os.getpid())
        return chosen, (rect.left, rect.top, rect.right, rect.bottom), visible

    def tool_window(self, widget):
        widget.update_idletasks()
        hwnd = self.user.GetAncestor(widget.winfo_id(), 2)
        style = self.user.GetWindowLongPtrW(hwnd, -20)
        self.user.SetWindowLongPtrW(hwnd, -20, style | 0x08000000 | 0x80)
        return hwnd

    def interactive(self, hwnd, enabled):
        style = self.user.GetWindowLongPtrW(hwnd, -20)
        style = style & ~0x08000000 if enabled else style | 0x08000000
        self.user.SetWindowLongPtrW(hwnd, -20, style)
        if enabled:
            self.user.SetForegroundWindow(hwnd)

    def menu_active(self):
        info = GuiThreadInfo(size=c.sizeof(GuiThreadInfo))
        return bool(self.user.GetGUIThreadInfo(self.kernel.GetCurrentThreadId(), c.byref(info))
                    and info.flags & 0x14)  # GUI_INMENUMODE | GUI_POPUPMENUMODE

    def place(self, widget, x, y):
        hwnd = self.user.GetAncestor(widget.winfo_id(), 2)
        # Native screen coordinates also work on monitors left/above the primary.
        self.user.SetWindowPos(hwnd, c.c_void_p(-1), int(x), int(y), 0, 0, 0x15)

    def close(self):
        if self.mutex:
            self.kernel.CloseHandle(self.mutex)
            self.mutex = None


class Tray:
    def __init__(self, native):
        self.native = native
        self.events = queue.SimpleQueue()
        self.hwnd = None
        self.icon = None
        self.error = None
        self.callback = WNDPROC(self._dispatch)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _dispatch(self, hwnd, message, wp, lp):
        if message == 0x8001 and lp in (0x205, 0x202):
            self.events.put("menu" if lp == 0x205 else "details")
            return 0
        if message == 2:
            self.native.user.PostQuitMessage(0)
            return 0
        return self.native.user.DefWindowProcW(hwnd, message, wp, lp)

    def _run(self):
        n = self.native
        try:
            instance = n.kernel.GetModuleHandleW(None)
            name = "CodexRateTray" + str(os.getpid())
            cls = WindowClass(proc=self.callback, instance=instance, name=name)
            n.user.RegisterClassW.argtypes = [c.POINTER(WindowClass)]
            if not n.user.RegisterClassW(c.byref(cls)):
                raise c.WinError(c.get_last_error())
            self.hwnd = n.user.CreateWindowExW(0, name, "Codex Rate", 0,
                                               0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise c.WinError(c.get_last_error())
            self.icon = NotifyIcon(size=c.sizeof(NotifyIcon), hwnd=self.hwnd,
                id=1, flags=7, callback=0x8001,
                icon=n.user.LoadIconW(None, c.c_void_p(32512)),
                tip="Codex Rate · 左键详情 / 右键菜单")
            if not n.shell.Shell_NotifyIconW(0, c.byref(self.icon)):
                raise OSError("tray-icon-unavailable")
            msg = w.MSG()
            while n.user.GetMessageW(c.byref(msg), None, 0, 0) > 0:
                n.user.TranslateMessage(c.byref(msg))
                n.user.DispatchMessageW(c.byref(msg))
        except OSError as exc:
            self.error = type(exc).__name__
        finally:
            if self.icon:
                n.shell.Shell_NotifyIconW(2, c.byref(self.icon))

    def close(self):
        if self.hwnd:
            self.native.user.PostMessageW(self.hwnd, 0x10, 0, 0)
        self.thread.join(timeout=1)
