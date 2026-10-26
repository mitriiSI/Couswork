"""Small Windows helpers (all of them are no-ops on other systems)."""

import ctypes
import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

# Hide console windows of child processes (ffmpeg) in the windowed .exe.
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def set_dpi_aware():
    """Work in real pixels, so a 4K/150% screen is recorded in full size."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def com_init_sta():
    """Make the GUI thread a normal single-threaded COM apartment."""
    if IS_WINDOWS:
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass


def com_init_mta():
    """Join the multi-threaded COM apartment (used by audio threads)."""
    if IS_WINDOWS:
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)
        except Exception:
            pass


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor_pos():
    """Mouse position in virtual-screen pixels, or None."""
    if not IS_WINDOWS:
        return None
    pt = _POINT()
    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return pt.x, pt.y
    return None


def exclude_from_capture(tk_root, exclude=True):
    """Keep our own window visible on the monitor but invisible in the video.

    Works on Windows 10 2004+ and Windows 11 (WDA_EXCLUDEFROMCAPTURE).
    """
    if not IS_WINDOWS:
        return False
    try:
        hwnd = ctypes.windll.user32.GetParent(tk_root.winfo_id()) or tk_root.winfo_id()
        affinity = 0x11 if exclude else 0x0
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity))
    except Exception:
        return False


def open_folder(path):
    if IS_WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_explorer(file_path):
    if IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(file_path)])
    else:
        open_folder(os.path.dirname(file_path))


def default_output_dir():
    home = os.path.expanduser("~")
    videos = os.path.join(home, "Videos")
    if not os.path.isdir(videos):
        videos = home
    return os.path.join(videos, "Записи экрана")


def settings_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "ScreenRecorder", "settings.json")


def dpi_scale():
    """System scale factor: 1.0 at 100%, 1.5 at 150% and so on."""
    if not IS_WINDOWS:
        return 1.0
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0
