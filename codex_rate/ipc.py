"""Codex's internal length-prefixed IPC: initialize, then listen only."""

import ctypes
import json
import os
import struct
import threading
import uuid
from ctypes import wintypes as w


class Frames:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        rows = []
        while len(self.buffer) >= 4:
            size = struct.unpack_from("<I", self.buffer)[0]
            if size > 8 * 1024 * 1024:
                raise ValueError("invalid-frame-size")
            if len(self.buffer) < size + 4:
                break
            row = json.loads(self.buffer[4:size + 4])
            del self.buffer[:size + 4]
            if isinstance(row, dict):
                rows.append(row)
        return rows


class Selection:
    def __init__(self):
        self.thread_id = None
        self.source_id = None
        self.host_id = None
        self.followed = set()
        self.connected = False
        self.error = None
        self.lock = threading.Lock()

    def observe(self, row):
        if row.get("method") != "thread-stream-following-changed":
            return
        p = row.get("params")
        if not isinstance(p, dict):
            return
        thread = p.get("conversationId")
        if not isinstance(thread, str):
            return
        try:
            uuid.UUID(thread)
        except ValueError:
            return
        with self.lock:
            identity = (p.get("hostId"), row.get("sourceClientId"), thread)
            if p.get("following") is True:
                self.followed.add(identity)
            elif p.get("following") is False:
                self.followed.discard(identity)
            identities = {(host, thread) for host, _, thread in self.followed}
            if len(identities) == 1:
                self.host_id, self.thread_id = next(iter(identities))
                self.error = None if self.host_id == "local" else "remote-session-unsupported"
            else:
                self.thread_id = None
                self.error = "multiple-followed-sessions" if identities else None

    def snapshot(self):
        with self.lock:
            return self.thread_id, self.connected, self.error

    def local_threads(self):
        with self.lock:
            return {thread for host, _, thread in self.followed if host == "local"}


class IpcWatcher:
    def __init__(self):
        self.selection = Selection()
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        if os.name == "nt":
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _run(self):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
                                  w.DWORD, w.DWORD, w.HANDLE]
        k.CreateFileW.restype = w.HANDLE
        k.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]
        k.WriteFile.argtypes = k.ReadFile.argtypes
        k.PeekNamedPipe.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, w.LPVOID,
                                    ctypes.POINTER(w.DWORD), w.LPVOID]
        k.CloseHandle.argtypes = [w.HANDLE]
        while not self.stop.is_set():
            handle = k.CreateFileW(r"\\.\pipe\codex-ipc", 0xC0000000, 0, None, 3, 0, None)
            if handle == ctypes.c_void_p(-1).value:
                with self.selection.lock:
                    self.selection.connected = False
                    self.selection.thread_id = None
                    self.selection.followed.clear()
                    self.selection.error = "ipc-unavailable"
                self.stop.wait(3)
                continue
            try:
                body = json.dumps({"type": "request", "requestId": str(uuid.uuid4()),
                                   "sourceClientId": "codex-rate-" + str(os.getpid()),
                                   "version": 0, "method": "initialize",
                                   "params": {"clientType": "codex-rate"}}).encode()
                data = struct.pack("<I", len(body)) + body
                count = w.DWORD()
                if not k.WriteFile(handle, data, len(data), ctypes.byref(count), None):
                    raise OSError("ipc-write-failed")
                with self.selection.lock:
                    self.selection.connected = True
                    self.selection.error = None
                frames = Frames()
                while not self.stop.wait(0.2):
                    available = w.DWORD()
                    if not k.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                        raise OSError("ipc-disconnected")
                    if not available.value:
                        continue
                    buffer = ctypes.create_string_buffer(min(available.value, 65536))
                    if not k.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                        raise OSError("ipc-read-failed")
                    for row in frames.feed(buffer.raw[:count.value]):
                        self.selection.observe(row)
            except (OSError, ValueError):
                with self.selection.lock:
                    self.selection.connected = False
                    self.selection.thread_id = None
                    self.selection.followed.clear()
                    self.selection.error = "ipc-disconnected"
            finally:
                k.CloseHandle(handle)
            self.stop.wait(2)
