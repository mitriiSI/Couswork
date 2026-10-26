"""Build check used by CI: records the screen for a few seconds without a GUI."""

import math
import os
import re
import subprocess
import time
import traceback
import wave

import numpy as np

from . import devices, winutil
from .recorder import Recorder, Settings, audio_format, mux


def _probe(ffmpeg, path):
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True,
                         creationflags=winutil.NO_WINDOW).stderr.decode("utf-8", "replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    return duration, "Video:" in out, "Audio:" in out


def _sine_wav(path, seconds, freq, channels):
    t = np.arange(int(48000 * seconds)) / 48000
    tone = (0.3 * np.sin(2 * math.pi * freq * t) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.repeat(tone[:, None], channels, axis=1).tobytes())


def run_selftest(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    report = []
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok = ok and bool(cond)
        report.append(f"[{'OK' if cond else 'FAIL'}] {name} {info}".rstrip())

    try:
        winutil.set_dpi_aware()
        ffmpeg = devices.ffmpeg_exe()
        check("ffmpeg", os.path.exists(ffmpeg), ffmpeg)
        check("monitors", devices.list_monitors(), str(devices.list_monitors()))
        import cv2  # noqa: F401
        check("opencv", True)
        try:
            import soundcard  # noqa: F401
            report.append(f"[INFO] speakers: {devices.list_speakers()}")
            report.append(f"[INFO] microphones: {devices.list_microphones()}")
        except Exception as e:  # CI machines may have no sound devices at all
            report.append(f"[INFO] soundcard: {e!r}")
        report.append(f"[INFO] cameras: {devices.list_cameras()}")

        s = Settings(screen=True, system_audio=False, microphone=False, webcam=False,
                     fps=15, output_dir=out_dir)
        rec = Recorder(s)
        rec.start()
        time.sleep(2)
        rec.pause()
        time.sleep(1)
        rec.resume()
        time.sleep(1)
        video = rec.stop()
        duration, has_v, _ = _probe(ffmpeg, video)
        check("screen recording", has_v and 2.5 < duration < 3.6, f"{video} {duration:.2f}s")

        a1, a2 = os.path.join(out_dir, "a1.wav"), os.path.join(out_dir, "a2.wav")
        _sine_wav(a1, 3, 440, 2)
        _sine_wav(a2, 2, 660, 1)
        mixed = mux(ffmpeg, video, [a1, a2], os.path.join(out_dir, "mixed.mp4"))
        duration, has_v, has_a = _probe(ffmpeg, mixed)
        check("video + 2 audio tracks", has_v and has_a, f"{duration:.2f}s")
        ext = audio_format(ffmpeg)[0]
        audio_only = mux(ffmpeg, None, [a1, a2], os.path.join(out_dir, "audio" + ext))
        duration, has_v, has_a = _probe(ffmpeg, audio_only)
        check("audio only", has_a and not has_v and 2.8 < duration < 3.3, f"{ext} {duration:.2f}s")
    except Exception:
        ok = False
        report.append(traceback.format_exc())

    report.append("RESULT: " + ("PASS" if ok else "FAIL"))
    with open(os.path.join(out_dir, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    return 0 if ok else 1
