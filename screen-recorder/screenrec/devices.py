"""Lists of monitors, sound devices and webcams for the settings window."""

import glob
import re
import subprocess

from .winutil import IS_WINDOWS, NO_WINDOW


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def make_mss():
    import mss
    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def list_monitors():
    """[(mss monitor index, label)]; index 0 is all monitors together."""
    try:
        with make_mss() as sct:
            mons = sct.monitors
    except Exception:
        return [(1, "Основной монитор")]
    result = []
    for i, m in enumerate(mons):
        size = f"{m['width']}×{m['height']}"
        if i == 0:
            if len(mons) > 2:
                result.append((0, f"Все мониторы ({size})"))
        else:
            result.append((i, f"Монитор {i} ({size})"))
    return result or [(1, "Основной монитор")]


def _soundcard():
    try:
        import soundcard
        return soundcard
    except Exception:
        return None


def list_speakers():
    """[(device id, name)] — what plays the computer sound; default first."""
    sc = _soundcard()
    if sc is None:
        return []
    try:
        default = sc.default_speaker()
        items = [(default.id, f"{default.name} (по умолчанию)")]
        items += [(s.id, s.name) for s in sc.all_speakers() if s.id != default.id]
        return items
    except Exception:
        return []


def list_microphones():
    """[(device id, name)]; default first."""
    sc = _soundcard()
    if sc is None:
        return []
    try:
        mics = sc.all_microphones(include_loopback=False)
        try:
            default = sc.default_microphone()
        except Exception:
            default = None
        items = []
        if default is not None:
            items.append((default.id, f"{default.name} (по умолчанию)"))
        items += [(m.id, m.name) for m in mics if default is None or m.id != default.id]
        return items
    except Exception:
        return []


def parse_dshow_devices(text):
    """Names of video devices from `ffmpeg -list_devices true -f dshow` output."""
    names = []
    for line in text.splitlines():
        m = re.search(r'"([^"]+)"\s+\(([^)]*)\)', line)
        if m and "video" in m.group(2) and "Alternative name" not in line:
            names.append(m.group(1))
    return names


def list_cameras():
    """[(OpenCV index, name)]."""
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                [ffmpeg_exe(), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                capture_output=True, timeout=15, creationflags=NO_WINDOW,
            )
            text = (out.stderr + out.stdout).decode("utf-8", errors="replace")
            names = parse_dshow_devices(text)
            if names:
                return list(enumerate(names))
        except Exception:
            pass
        return [(i, f"Камера {i + 1}") for i in range(3)]
    devs = sorted(glob.glob("/dev/video*"))
    return [(int(re.sub(r"\D", "", d) or 0), d) for d in devs] or [(0, "Камера 1")]
