import argparse
import json
import os
import threading
import time
from pathlib import Path

from .ipc import IpcWatcher
from .active import ActiveWatcher
from .metrics import Meter, compact
from .reader import SessionIndex, SessionReader, codex_home
from . import startup
from . import __version__


STATUS_MESSAGES = {
    "conversation-loading": "正在切换或加载对话",
    "active-page-loading": "正在识别选中对话",
    "active-page-changing": "页面正在更新，等待重新识别",
    "active-page-unavailable": "未找到可识别的选中对话，请确认侧栏可见",
    "ambiguous-active-page": "选中名称对应多个本地会话，请手动固定会话",
    "thread-metadata-unavailable": "无法读取本地会话索引",
    "active-reader-stale": "页面识别暂未响应，正在恢复",
    "active-reader-stopped": "页面识别程序已退出，正在恢复",
    "active-reader-unavailable": "页面识别程序不可用",
    "invalid-active-metadata": "页面识别返回的数据不可用",
    "no-codex-window": "等待 Codex 窗口",
    "selected-log-unavailable": "选中会话的本地日志尚不可用",
    "no-session": "等待选中本地会话",
    "log-recovering": "正在恢复长日志中的本轮记录",
    "malformed-jsonl": "本轮存在损坏或无法安全解析的计量记录",
    "partial-turn": "仅取得本轮部分记录，暂不计算 TPS",
    "insufficient-timing": "缺少完整计时或有效耗时不足 0.5 秒",
    "invalid-item-timing": "活动计时无效，暂不计算 TPS",
    "turn-usage-mismatch": "响应总量与本轮累计量不一致",
    "carrier-changed-mid-turn": "本轮计量格式发生切换",
    "missing-response-id": "计量记录缺少响应标识",
    "invalid-usage": "Token 计数无效",
    "conflicting-response-usage": "同一响应出现矛盾计数",
    "missing-legacy-cumulative": "旧格式缺少累计计数",
    "tray-unavailable": "系统托盘不可用",
    "ElementNotAvailableException": "页面正在更新，等待重新识别",
    "COMException": "无障碍接口暂时不可用，等待重新识别",
}

ACTIVITY_NAMES = {
    "idle": "等待数据", "waiting": "等待本轮首个响应",
    "model": "模型响应", "tool": "工具调用", "agent": "子代理调度",
    "waiting-response": "工具已返回，等待后续响应",
    "completed": "本轮完成", "aborted": "本轮已取消",
}


class Monitor:
    def __init__(self, home, thread_id=None):
        self.index = SessionIndex(home)
        self.ipc = IpcWatcher()
        self.active = ActiveWatcher(home)
        self.pinned = thread_id
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.readers = {}
        self.missing_target = None
        self.selected_key = None
        self.value = {"mode": "starting", "thread": None,
                      "measurement": Meter().snapshot().to_dict(), "error": None}
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.ipc.start()
        self.active.start()
        self.thread.start()

    def update(self):
        self.index.refresh()
        selected, connected, ipc_error = self.ipc.selection.snapshot()
        active = self.active.snapshot()
        with self.lock:
            pinned = self.pinned
        target = pinned or active["thread"]
        mode = "pinned" if pinned else "active"
        key = (pinned, active["serial"] if not pinned else None, target)
        if key != self.selected_key:
            self.selected_key = key
            value = {"mode": "loading", "thread": target, "active_serial": active["serial"],
                     "measurement": Meter().snapshot().to_dict(), "error": "conversation-loading",
                     "ipc_connected": connected, "ipc_error": None}
            with self.lock:
                self.value = value
            return value
        path = Path(active["path"]) if not pinned and active["path"] else self.index.find(target) if target else None
        if target and path is None and self.missing_target != target:
            self.index.refresh(force=True)
            path = self.index.find(target)
        self.missing_target = target if path is None else None
        error = active["error"] if not pinned else self.index.error
        reader_status = None
        if path:
            reader = self.readers.get(path)
            if reader is None:
                if len(self.readers) >= 8:
                    self.readers.pop(next(iter(self.readers)))
                reader = self.readers[path] = SessionReader(path)
            measurement = reader.poll().to_dict()
            reader_status = {name: getattr(reader, name) for name in (
                "recovering", "recovery_state", "recovery_bytes", "recovery_limited",
                "skipped_non_metric", "backlog_bytes")}
            error = reader.error or ("log-recovering" if reader.recovering else
                "malformed-jsonl" if "malformed-jsonl" in measurement["warnings"] else error)
            thread_id = target
        else:
            measurement = Meter().snapshot().to_dict()
            thread_id = target
            error = error or ("selected-log-unavailable" if target else "no-session")
        value = {"mode": mode, "thread": thread_id, "measurement": measurement,
                 "error": error, "ipc_connected": connected, "ipc_error": None,
                 "active_serial": active["serial"], "reader": reader_status}
        with self.lock:
            self.value = value
        return value

    def _run(self):
        while not self.stop.is_set():
            try:
                self.update()
            except Exception as exc:
                with self.lock:
                    self.value = dict(self.value, error=type(exc).__name__)
            self.stop.wait(0.5)

    def snapshot(self):
        with self.lock:
            value = dict(self.value)
            pinned = self.pinned
        active = self.active.snapshot()
        if ((not pinned and (active["serial"] != value.get("active_serial") or active["error"]
                             or value["mode"] == "pinned"))
                or (pinned and value["thread"] != pinned)):
            value.update(mode="loading", thread=active["thread"],
                         measurement=Meter().snapshot().to_dict(),
                         error=active["error"] or "conversation-loading", reader=None)
        return value

    def pin(self, thread_id):
        with self.lock:
            self.pinned = thread_id
            self.value = dict(self.value, mode="loading", thread=thread_id,
                              measurement=Meter().snapshot().to_dict(), error="conversation-loading", reader=None)

    def close(self):
        self.stop.set()
        self.ipc.stop.set()
        self.active.close()
        if self.thread.is_alive():
            self.thread.join(timeout=2)


def load_settings(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {}
        return {k: v for k, v in value.items() if
                (k == "theme" and v in ("dark", "light")) or
                (k in ("right", "bottom") and type(v) is int and 0 <= v <= 4000)}
    except (OSError, ValueError):
        return {}


class Strip:
    def __init__(self, args, native):
        import tkinter as tk
        from .windows import Tray

        self.tk, self.native, self.args = tk, native, args
        self.startup = startup
        self.settings_path = args.settings
        self.settings = {"theme": "light", "right": 26, "bottom": 66}
        self.settings.update(load_settings(self.settings_path))
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Codex Rate")
        self.root.overrideredirect(not args.preview)
        self.root.attributes("-topmost", True)
        self.transparent = "#ff00ff"
        self.root.configure(bg=self.transparent)
        self.root.attributes("-transparentcolor", self.transparent)
        self.root.resizable(False, False)
        self.root.geometry("+100+100")
        self.surface = tk.Canvas(self.root, bg=self.transparent, bd=0, highlightthickness=0)
        self.surface.pack(fill="both", expand=True)
        self.outline = self.surface.create_polygon(0, 0, 1, 0, 1, 1, 0, 1,
            smooth=True, splinesteps=24, width=0)
        self.body = self.surface.create_polygon(0, 0, 1, 0, 1, 1, 0, 1,
            smooth=True, splinesteps=24, width=0)
        self.frame = tk.Frame(self.surface, bd=0)
        self.frame_window = self.surface.create_window(12, 8, anchor="nw", window=self.frame)
        self.frame.bind("<Configure>", self.layout)
        self.metric_row = tk.Frame(self.frame, bd=0)
        self.metric_row.pack(fill="x")
        self.status = tk.Label(self.metric_row, text="●", font=("Segoe UI", 10), padx=5)
        self.status.pack(side="left")
        self.fields = []
        for label, initial in (("有效TPS", "-- tok/s"), ("本轮输出", "--"), ("缓存", "--")):
            group = tk.Frame(self.metric_row)
            group.pack(side="left", padx=(0, 15), pady=7)
            caption = tk.Label(group, text=label, font=("Microsoft YaHei UI", 9))
            caption.pack(side="left", padx=(0, 6))
            value = tk.Label(group, text=initial, font=("Segoe UI Semibold", 11))
            value.pack(side="left")
            self.fields.append(value)
        self.menu_button = tk.Label(self.metric_row, text="⋮", font=("Segoe UI", 13),
                                    padx=8, cursor="hand2")
        self.menu_button.pack(side="right", fill="y")
        self.last_detection = tk.Label(self.frame, text="上次检测：--", anchor="w",
            font=("Microsoft YaHei UI", 8), padx=5)
        self.last_detection.pack(fill="x", pady=(0, 3))
        self.detail = None
        self.detail_text = None
        self.menu = None
        self.menu_open = False
        self.menu_check_handle = None
        self.closed = False
        self.tick_handle = None
        self.exit_handle = None
        self.drag = None
        self.dragged = False
        self.host_rect = None
        self.force_show_until = 0.0
        self.paint()
        self.root.update_idletasks()
        self.layout()
        self.root.update_idletasks()
        self.hwnd = (native.user.GetAncestor(self.root.winfo_id(), 2)
                     if args.preview else native.tool_window(self.root))
        self.monitor = Monitor(args.home, args.thread)
        self.monitor_running = False
        self.tray = Tray(native)
        self.tray.start()
        self.bind_children(self.surface)
        self.menu_button.bind("<Button-1>", self.popup)
        self.menu_button.unbind("<Double-Button-1>")
        self.menu_button.bind("<Enter>", lambda _: self.menu_button.configure(bg=self.hover))
        self.menu_button.bind("<Leave>", lambda _: self.menu_button.configure(bg=self.bg))
        self.root.bind("<Escape>", lambda _: self.hide_details())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if args.exit_after:
            self.exit_handle = self.root.after(int(args.exit_after * 1000), self.close)
        self.tick()

    def bind_children(self, widget):
        widget.bind("<ButtonPress-1>", self.drag_start)
        widget.bind("<B1-Motion>", self.drag_move)
        widget.bind("<ButtonRelease-1>", self.drag_end)
        widget.bind("<Button-3>", self.popup)
        widget.bind("<Double-Button-1>", lambda _: self.show_details())
        for child in widget.winfo_children():
            self.bind_children(child)

    def layout(self, _=None):
        width = max(620, self.frame.winfo_reqwidth() + 24)
        height = self.frame.winfo_reqheight() + 16
        radius = min(16, height / 2)
        self.surface.configure(width=width, height=height)
        self.surface.itemconfigure(self.frame_window, width=width - 24)
        # A withdrawn Tk window otherwise retains Canvas's large default size
        # when its first native host-placement event arrives before mapping.
        self.root.geometry(f"{width}x{height}")
        # A filled outer silhouette remains continuous behind native child windows.
        for shape, inset in ((self.outline, 0), (self.body, 3)):
            left, top, right, bottom = inset, inset, width - inset, height - inset
            r = max(0, radius - inset)
            self.surface.coords(shape,
                left + r, top, right - r, top, right, top,
                right, top + r, right, bottom - r, right, bottom,
                right - r, bottom, left + r, bottom, left, bottom,
                left, bottom - r, left, top + r, left, top)

    def paint(self):
        dark = self.settings["theme"] == "dark"
        self.bg = "#202020" if dark else "#ffffff"
        self.fg = "#f5f5f5" if dark else "#111111"
        self.muted = "#d0d0d0" if dark else "#222222"
        self.accent = self.fg
        self.hover = "#3b3b3b" if dark else "#eeeeee"

        def color(widget):
            widget.configure(bg=self.bg)
            if isinstance(widget, self.tk.Label):
                widget.configure(fg=self.muted)
            for child in widget.winfo_children():
                color(child)

        color(self.frame)
        self.surface.itemconfigure(self.outline, fill="#a0a0a0" if dark else "#111111", outline="")
        self.surface.itemconfigure(self.body, fill=self.bg, outline="")
        for field in self.fields:
            field.configure(fg=self.fg)
        self.menu_button.configure(fg=self.fg)
        self.status.configure(fg=self.accent)
        if self.detail and self.detail.winfo_exists():
            self.detail.configure(bg=self.bg)
            self.detail_text.configure(bg=self.bg, fg=self.fg)

    def data(self):
        if self.args.demo:
            return {"mode": "demo", "thread": "demo-only", "error": None,
                    "ipc_connected": False, "ipc_error": None,
                    "measurement": {"tps": 128.4, "output": 3248, "input": 24000,
                                    "cached": 21600, "cache_percent": 90.0,
                                    "state": "completed", "elapsed_ms": 25296,
                                    "carrier": "synthetic", "samples": 4,
                                    "complete_start": True, "warnings": [],
                                    "sampled_at_ms": int((time.time() - 2) * 1000)}}
        return self.monitor.snapshot()

    def tick(self):
        if self.closed:
            return
        _, rect, visible = self.native.host()
        self.host_rect = rect
        self.sync_monitor(rect is not None)
        value = self.data()
        m = value["measurement"]
        unavailable = bool(value["error"])
        tps = m["tps"] if not unavailable else None
        marker = "~" if m["state"] == "active" else ""
        self.fields[0].configure(text=f"{marker}{tps:.1f} tok/s" if tps is not None else "-- tok/s")
        self.fields[1].configure(text=compact(m["output"]) if not unavailable else "--")
        cache = m["cache_percent"] if not unavailable else None
        self.fields[2].configure(text=f"{cache:.0f}%" if cache is not None else "--")
        sampled_at = m.get("sampled_at_ms")
        age = max(0, int(time.time() - sampled_at / 1000)) if sampled_at is not None and not unavailable else None
        self.last_detection.configure(text=f"上次检测：{age}秒之前" if age is not None else "上次检测：--")
        activity = {"tool": "工具", "agent": "代理", "waiting-response": "等待"}.get(m.get("activity"), "●")
        self.status.configure(text="演示" if self.args.demo else "●" if unavailable else activity,
            fg="#e9b86e" if unavailable or value["mode"] == "recent" else self.accent)
        self.root.update_idletasks()
        force_show = time.monotonic() < self.force_show_until
        interacting = (self.menu_open or self.drag is not None or
                       (self.detail is not None and self.detail.winfo_exists()))
        if self.args.demo or self.args.preview or force_show or interacting:
            self.root.deiconify()
        elif rect and visible:
            self.root.deiconify()
            if not self.drag:
                self.place_at_host()
        elif rect:
            self.root.withdraw()
        else:
            # Logon starts quietly; the tray remains the entry point while waiting.
            self.root.withdraw()
        if self.detail and self.detail.winfo_exists():
            self.detail_text.configure(text=self.describe(value))
        while not self.tray.events.empty():
            action = self.tray.events.get()
            self.force_show_until = time.monotonic() + 3
            self.root.deiconify()
            self.native.user.SetForegroundWindow(self.hwnd)
            if action == "details":
                self.show_details()
            else:
                self.popup()
        if not self.closed:
            self.tick_handle = self.root.after(400 if rect or interacting else 1000, self.tick)

    def sync_monitor(self, host_present):
        if self.args.demo:
            return
        if host_present and not self.monitor_running:
            self.monitor.start()
            self.monitor_running = True
        elif not host_present and self.monitor_running:
            pinned = self.monitor.pinned
            self.monitor.close()
            self.monitor = Monitor(self.args.home, pinned)
            self.monitor_running = False

    def describe(self, value):
        m = value["measurement"]
        names = {"active": "自动跟随左侧选中对话", "loading": "正在加载当前对话",
                 "ipc": "IPC 跟随会话", "pinned": "手动固定会话",
                 "recent": "最近活动 · 降级模式", "remote": "远程会话 · 暂不支持",
                 "starting": "正在连接", "demo": "演示数据"}
        states = {"idle": "等待数据", "waiting": "等待本轮首个响应",
                  "active": "本轮进行中 · 响应结束后刷新", "completed": "本轮完成",
                  "aborted": "本轮已取消 · 不显示 TPS"}
        number = lambda n: "--" if n is None else f"{n:,}"
        lines = [f"CODEX RATE  /  {__version__}", "",
                 names[value["mode"]], f"会话：{value['thread'] or '--'}",
                 states.get(m["state"], m["state"]), "",
                 f"本轮输出：{number(m['output'])} token（含推理）",
                 f"本轮输入：{number(m['input'])} token",
                 f"缓存输入：{number(m['cached'])} token（输入的子集）",
                 f"有效计时：{m['elapsed_ms'] / 1000:.3f} 秒" if m['elapsed_ms'] is not None else "有效计时：--",
                 f"已记录响应：{m['samples']}  ·  来源：{m['carrier']}", "",
                 "有效TPS = 本轮输出 / 扣除已知工具独占时间的耗时",
                 "含首 token 等待与队列延迟；响应完成后刷新。",
                 "含生成工具参数的时间，不是纯解码速度。",
                 "~ 表示本轮尚未结束，保留最近一次测量。",
                 "缓存命中率 = 本轮缓存输入 / 本轮输入。",
                 "统计范围：当前会话；子代理用量不并入主会话。",
                 "左键拖动位置 · 双击详情 · 右键菜单"]
        activity = m.get("activity")
        if activity:
            lines += ["", "最近活动：" + ACTIVITY_NAMES.get(activity, activity)]
        if m.get("sampled_at_ms") is not None:
            age = max(0, int(time.time() - m["sampled_at_ms"] / 1000))
            lines.append(f"距最近计量：{age} 秒（响应完成后更新）")
        reader_status = value.get("reader")
        if reader_status:
            if reader_status["recovering"]:
                phase = {"pending": "准备读取", "searching": "查找本轮起点", "replaying": "恢复本轮计量"}.get(reader_status["recovery_state"], "读取中")
                lines.append(f"恢复阶段：{phase} · 已读取 {reader_status['recovery_bytes'] / 1024**2:.1f} MiB")
            if reader_status["recovery_limited"]:
                lines.append("已达到本轮起点回溯上限，缺失起点时不计算 TPS。")
            if reader_status["skipped_non_metric"]:
                lines.append(f"已跳过 {reader_status['skipped_non_metric']} 条超大非计量内容记录。")
            if reader_status["backlog_bytes"]:
                lines.append(f"日志追赶中：尚有 {reader_status['backlog_bytes'] / 1024**2:.1f} MiB 待读。")
        issues = list(m["warnings"])
        if value["error"]:
            issues.append(value["error"])
        if value.get("ipc_error"):
            issues.append(value["ipc_error"])
        if self.tray.error:
            issues.append("tray-unavailable")
        if issues:
            lines += ["", "数据状态："] + [STATUS_MESSAGES.get(issue, issue) for issue in dict.fromkeys(issues)]
        return "\n".join(lines)

    def show_details(self):
        if self.detail and self.detail.winfo_exists():
            self.detail.lift()
            self.detail.focus_force()
            return
        self.root.deiconify()
        self.detail = self.tk.Toplevel(self.root)
        self.detail.title("Codex Rate · 指标详情")
        self.detail.protocol("WM_DELETE_WINDOW", self.hide_details)
        self.detail.attributes("-topmost", True)
        self.detail.resizable(False, False)
        self.detail_text = self.tk.Label(self.detail, justify="left", anchor="w",
            font=("Microsoft YaHei UI", 10), padx=22, pady=18,
            text=self.describe(self.data()))
        self.detail_text.pack()
        self.detail.update_idletasks()
        height = self.detail.winfo_reqheight() + 40
        y = self.root.winfo_y() - height - 12
        if y < 0:
            y = self.root.winfo_y() + self.root.winfo_height() + 12
        self.native.place(self.detail, self.root.winfo_x(), y)
        self.detail.bind("<Escape>", lambda _: self.hide_details())
        self.paint()
        self.detail.focus_force()

    def hide_details(self):
        if self.detail and self.detail.winfo_exists():
            self.detail.destroy()
        self.detail = None
        self.detail_text = None

    def popup(self, event=None):
        if self.closed or self.menu_open:
            return "break"
        if self.menu is not None:
            self.menu.destroy()
        menu = self.menu = self.tk.Menu(self.root, tearoff=False)
        menu.add_command(label="指标详情", command=self.show_details)
        menu.add_separator()
        menu.add_command(label="自动跟随会话", command=lambda: self.monitor.pin(None))
        thread_id = self.data()["thread"]
        menu.add_command(label="固定到此会话", state="normal" if thread_id else "disabled",
                         command=lambda: self.monitor.pin(thread_id))
        recent = self.tk.Menu(menu, tearoff=False)
        for path in self.monitor.index.paths[:8]:
            candidate = path.stem[-36:]
            recent.add_command(label=candidate[:8] + "…" + candidate[-6:],
                               command=lambda t=candidate: self.monitor.pin(t))
        menu.add_cascade(label="选择最近会话", menu=recent,
                         state="normal" if self.monitor.index.paths else "disabled")
        menu.add_separator()
        menu.add_command(label="切换明暗主题", command=self.toggle_theme)
        menu.add_command(label="重置位置", command=self.reset_position)
        try:
            startup_enabled = self.startup.is_enabled()
        except OSError:
            menu.add_command(label="自启动状态不可用", state="disabled")
        else:
            menu.add_command(label="关闭开机自启动" if startup_enabled else "启用开机自启动",
                             command=self.toggle_startup)
        menu.add_separator()
        menu.add_command(label="退出 Codex Rate", command=self.close)
        x = event.x_root if event else self.root.winfo_pointerx()
        y = event.y_root if event else self.root.winfo_pointery()
        self.root.deiconify()
        self.menu_open = True
        if not self.args.preview:
            self.native.interactive(self.hwnd, True)
        else:
            self.native.user.SetForegroundWindow(self.hwnd)
        try:
            menu.tk_popup(x, y)
        except self.tk.TclError:
            if not self.closed:
                raise
        finally:
            if not self.closed:
                # Windows can dispatch the chosen command after tk_popup returns.
                # Keep the menu alive, and wait until native menu tracking ends
                # before restoring the strip's non-activating window style.
                self.menu_check_handle = self.root.after_idle(self.check_menu)
        return "break"

    def check_menu(self):
        self.menu_check_handle = None
        if self.closed:
            return
        if self.native.menu_active():
            self.menu_check_handle = self.root.after(50, self.check_menu)
            return
        self.menu_open = False
        self.menu.grab_release()
        if not self.args.preview:
            self.native.interactive(self.hwnd, False)

    def toggle_theme(self):
        self.settings["theme"] = "light" if self.settings["theme"] == "dark" else "dark"
        self.paint()
        self.save()

    def toggle_startup(self):
        from tkinter import messagebox
        try:
            if self.startup.is_enabled():
                self.startup.disable()
            else:
                self.startup.enable()
        except OSError as exc:
            messagebox.showerror("Codex Rate", f"自启动设置失败：{type(exc).__name__}", parent=self.root)

    def reset_position(self):
        self.settings.update(right=26, bottom=66)
        if self.host_rect:
            self.place_at_host()
        else:
            self.native.place(self.root, 100, 100)
        self.save()

    def place_at_host(self):
        rect = self.host_rect
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = max(rect[0] + 8, rect[2] - width - self.settings["right"])
        y = max(rect[1] + 8, rect[3] - height - self.settings["bottom"])
        self.native.place(self.root, x, y)

    def drag_start(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self.dragged = False

    def drag_move(self, event):
        if self.drag:
            self.dragged = True
            self.native.place(self.root, event.x_root-self.drag[0], event.y_root-self.drag[1])

    def drag_end(self, _):
        if self.dragged and self.host_rect:
            self.settings["right"] = max(0, self.host_rect[2] - self.root.winfo_x() - self.root.winfo_width())
            self.settings["bottom"] = max(0, self.host_rect[3] - self.root.winfo_y() - self.root.winfo_height())
            self.save()
        self.drag = None

    def save(self):
        from tkinter import messagebox
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
            temporary.replace(self.settings_path)
        except OSError as exc:
            messagebox.showerror("Codex Rate", f"设置保存失败：{type(exc).__name__}", parent=self.root)

    def close(self):
        if self.closed:
            return
        self.closed = True
        for handle in (self.tick_handle, self.exit_handle, self.menu_check_handle):
            if handle:
                self.root.after_cancel(handle)
        if not self.args.demo:
            self.monitor.close()
        self.tray.close()
        if self.args.diagnostics:
            value = self.data()
            value["gui"] = {"width": self.root.winfo_width(), "height": self.root.winfo_height(),
                            "tray_available": self.tray.error is None,
                            "host_detected": self.host_rect is not None}
            self.args.diagnostics.parent.mkdir(parents=True, exist_ok=True)
            self.args.diagnostics.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        self.root.destroy()
        self.native.close()


def main():
    parser = argparse.ArgumentParser(description="Codex Rate — local Windows throughput strip")
    parser.add_argument("--home", type=Path, default=codex_home(), help="Codex home directory")
    parser.add_argument("--thread", help="Pin an exact conversation UUID")
    parser.add_argument("--snapshot", action="store_true", help="Read-only numeric JSON snapshot")
    parser.add_argument("--demo", action="store_true", help="Clearly labelled synthetic UI preview")
    parser.add_argument("--preview", action="store_true", help="Show as an independent titled window")
    parser.add_argument("--background", action="store_true", help="Wait quietly in tray until Codex appears")
    startup_flags = parser.add_mutually_exclusive_group()
    startup_flags.add_argument("--install-startup", action="store_true", help="Enable current-user logon startup")
    startup_flags.add_argument("--uninstall-startup", action="store_true", help="Disable current-user logon startup")
    parser.add_argument("--exit-after", type=float, help="Close after N seconds (GUI smoke checks)")
    parser.add_argument("--diagnostics", type=Path, help="Write numeric-only state on GUI exit")
    parser.add_argument("--settings", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CodexRate" / "settings.json")
    args = parser.parse_args()
    if args.install_startup or args.uninstall_startup:
        try:
            result = startup.enable() if args.install_startup else startup.disable()
        except OSError as exc:
            parser.exit(1, f"Startup change failed: {exc}\n")
        print(result)
        return
    if args.thread:
        import uuid
        try:
            uuid.UUID(args.thread)
        except ValueError:
            parser.error("--thread requires a conversation UUID")
    if args.snapshot:
        monitor = Monitor(args.home, args.thread)
        monitor.ipc.start()
        monitor.active.start()
        try:
            for _ in range(30):
                if monitor.active.snapshot()["thread"] or args.thread:
                    break
                time.sleep(0.1)
            deadline = time.monotonic() + 15
            while True:
                value = monitor.update()
                if value["error"] not in ("conversation-loading", "log-recovering") or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            print(json.dumps(value, ensure_ascii=False, indent=2))
        finally:
            monitor.ipc.stop.set()
            monitor.active.close()
        return
    if os.name != "nt":
        parser.error("The strip requires Windows 10/11; --snapshot can run elsewhere.")
    from .windows import Native
    from tkinter import messagebox
    native = Native()
    native.dpi()
    if not native.single_instance("-demo" if args.demo else ""):
        if not args.background:
            messagebox.showinfo("Codex Rate", "状态条已在运行。请使用托盘图标查看详情或退出。")
        native.close()
        return
    strip = Strip(args, native)
    strip.root.mainloop()
