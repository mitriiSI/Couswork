"""Global hotkeys (work even when another window is active). Windows only."""

import ctypes
import queue
import threading

from .winutil import IS_WINDOWS

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
VK_F9 = 0x78
VK_F10 = 0x79


class GlobalHotkeys:
    """Puts the action name into self.events when a hotkey is pressed."""

    KEYS = {1: (VK_F9, "toggle"), 2: (VK_F10, "pause")}

    def __init__(self):
        self.events = queue.Queue()
        self.failed = []
        self._thread_id = None
        if IS_WINDOWS:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        for hid, (vk, action) in self.KEYS.items():
            if not user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk):
                self.failed.append(action)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in self.KEYS:
                self.events.put(self.KEYS[msg.wParam][1])
        for hid in self.KEYS:
            user32.UnregisterHotKey(None, hid)

    def close(self):
        if IS_WINDOWS and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
