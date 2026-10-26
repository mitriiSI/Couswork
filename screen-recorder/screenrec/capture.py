"""Capture threads: system sound / microphone, webcam and the video itself.

All sources share one Clock. Audio and video only keep data while the clock
is running and not paused, so the tracks stay in sync after pauses.
"""

import subprocess
import threading
import time
import wave

import numpy as np

from . import winutil
from .devices import make_mss

SAMPLE_RATE = 48000


class Clock:
    """Recording time without pauses."""

    def __init__(self):
        self._lock = threading.Lock()
        self.started = threading.Event()
        self._t0 = 0.0
        self._paused_total = 0.0
        self._pause_start = None

    def start(self):
        with self._lock:
            self._t0 = time.perf_counter()
        self.started.set()

    @property
    def running(self):
        return self.started.is_set() and self._pause_start is None

    @property
    def paused(self):
        return self._pause_start is not None

    def pause(self):
        with self._lock:
            if self._pause_start is None:
                self._pause_start = time.perf_counter()

    def resume(self):
        with self._lock:
            if self._pause_start is not None:
                self._paused_total += time.perf_counter() - self._pause_start
                self._pause_start = None

    def active_time(self):
        with self._lock:
            if not self.started.is_set():
                return 0.0
            now = self._pause_start if self._pause_start is not None else time.perf_counter()
            return max(0.0, now - self._t0 - self._paused_total)


class CaptureThread(threading.Thread):
    def __init__(self, stop_event):
        super().__init__(daemon=True)
        self.stop_event = stop_event
        self.ready = threading.Event()
        self.error = None

    def fail(self, message):
        self.error = message
        self.ready.set()


class AudioCapture(CaptureThread):
    """Records the computer sound (loopback of a speaker) or a microphone to WAV."""

    def __init__(self, kind, device_id, path, clock, stop_event):
        super().__init__(stop_event)
        self.kind = kind  # "system" or "mic"
        self.device_id = device_id
        self.path = path
        self.clock = clock
        self.frames = 0

    def _open_device(self):
        import soundcard as sc
        if self.kind == "system":
            speaker_id = self.device_id or sc.default_speaker().id
            return sc.get_microphone(speaker_id, include_loopback=True), None
        mic = sc.get_microphone(self.device_id) if self.device_id else sc.default_microphone()
        return mic, 1

    def run(self):
        winutil.com_init_mta()
        name = "звук компьютера" if self.kind == "system" else "микрофон"
        try:
            device, channels = self._open_device()
            # Half a second of device buffer: the video thread may hold the GIL for a while.
            recorder = device.recorder(samplerate=SAMPLE_RATE, channels=channels,
                                       blocksize=SAMPLE_RATE // 2)
            recorder.__enter__()
        except Exception as e:
            self.fail(f"Не удалось включить {name}: {e}")
            return
        wav = None
        try:
            self.ready.set()
            while not self.stop_event.is_set():
                data = recorder.record(numframes=None)
                if not self.clock.running or data.size == 0:
                    continue
                if data.ndim == 1:
                    data = data[:, None]
                if wav is None:
                    wav = wave.open(self.path, "wb")
                    wav.setnchannels(data.shape[1])
                    wav.setsampwidth(2)
                    wav.setframerate(SAMPLE_RATE)
                pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
                wav.writeframes(pcm.tobytes())
                self.frames += data.shape[0]
        except Exception as e:
            self.error = f"Запись ({name}) прервалась: {e}"
        finally:
            if wav is not None:
                wav.close()
            try:
                recorder.__exit__(None, None, None)
            except Exception:
                pass


class WebcamCapture(CaptureThread):
    """Keeps the latest webcam frame (BGR) in self.frame."""

    def __init__(self, index, stop_event):
        super().__init__(stop_event)
        self.index = index
        self.frame = None

    def _open(self):
        import cv2
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF] if winutil.IS_WINDOWS else [cv2.CAP_ANY]
        for backend in backends:
            cap = cv2.VideoCapture(self.index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 30)
                return cap
            cap.release()
        return None

    def run(self):
        try:
            cap = self._open()
        except Exception as e:
            self.fail(f"Не удалось включить веб-камеру: {e}")
            return
        if cap is None:
            self.fail("Веб-камера не найдена или занята другой программой.")
            return
        try:
            deadline = time.time() + 8
            while self.frame is None and time.time() < deadline and not self.stop_event.is_set():
                ok, frame = cap.read()
                if ok and frame is not None:
                    self.frame = frame
                else:
                    time.sleep(0.05)
            if self.frame is None:
                self.fail("Веб-камера не отдаёт изображение (возможно, она занята).")
                return
            self.ready.set()
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if ok and frame is not None:
                    self.frame = frame
                else:
                    time.sleep(0.01)
        finally:
            cap.release()


# Mouse arrow, drawn by hand because screen grabs do not contain the cursor.
_ARROW = np.array([(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)], dtype=np.float32)


def draw_cursor(img, x, y, scale):
    import cv2
    h, w = img.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return
    pts = (_ARROW * scale + (x, y)).astype(np.int32)
    color = (255, 255, 255, 255)[: img.shape[2]]
    edge = (0, 0, 0, 255)[: img.shape[2]]
    cv2.fillPoly(img, [pts], color, lineType=cv2.LINE_AA)
    cv2.polylines(img, [pts], True, edge, max(1, int(scale)), lineType=cv2.LINE_AA)


def overlay_webcam(img, cam, position, size):
    """Put the webcam picture into a corner of the screen frame."""
    import cv2
    h, w = img.shape[:2]
    cw = max(2, int(w * size)) // 2 * 2
    ch = max(2, int(cw * cam.shape[0] / cam.shape[1])) // 2 * 2
    if cw >= w or ch >= h:
        return
    small = cv2.resize(cam, (cw, ch), interpolation=cv2.INTER_AREA)
    if img.shape[2] == 4:
        small = cv2.cvtColor(small, cv2.COLOR_BGR2BGRA)
    margin = max(8, w // 80)
    x = margin if position in ("tl", "bl") else w - cw - margin
    y = margin if position in ("tl", "tr") else h - ch - margin
    img[y:y + ch, x:x + cw] = small
    border = max(2, w // 640)
    white = (255, 255, 255, 255)[: img.shape[2]]
    cv2.rectangle(img, (x - border, y - border), (x + cw + border - 1, y + ch + border - 1), white, border)


class VideoCapture(CaptureThread):
    """Grabs the screen and/or webcam and pipes frames into ffmpeg (H.264)."""

    def __init__(self, settings, path, log_path, clock, stop_event, webcam, ffmpeg):
        super().__init__(stop_event)
        self.s = settings
        self.path = path
        self.log_path = log_path
        self.clock = clock
        self.webcam = webcam
        self.ffmpeg = ffmpeg
        self.frames = 0
        self.size = None

    def _ffmpeg_cmd(self, w, h, pix_fmt):
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", pix_fmt, "-video_size", f"{w}x{h}",
               "-framerate", str(self.s.fps), "-i", "-"]
        max_h = self.s.max_height
        if max_h and h > max_h:
            out_w = int(round(w * max_h / h / 2)) * 2
            cmd += ["-vf", f"scale={out_w}:{max_h}:flags=bicubic"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", self.path]
        return cmd

    def run(self):
        sct = None
        proc = None
        log = None
        try:
            if self.s.screen:
                sct = make_mss()
                mons = sct.monitors
                mon = mons[self.s.monitor] if 0 <= self.s.monitor < len(mons) else mons[1 if len(mons) > 1 else 0]
                w, h = mon["width"] // 2 * 2, mon["height"] // 2 * 2
                region = {"left": mon["left"], "top": mon["top"], "width": w, "height": h}
                pix_fmt = "bgra"
                first = np.asarray(sct.grab(region))
            else:
                cam = self.webcam.frame
                h, w = cam.shape[0] // 2 * 2, cam.shape[1] // 2 * 2
                region = None
                pix_fmt = "bgr24"
                first = None
            self.size = (w, h)
            log = open(self.log_path, "wb")
            proc = subprocess.Popen(self._ffmpeg_cmd(w, h, pix_fmt), stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=log,
                                    creationflags=winutil.NO_WINDOW)
        except Exception as e:
            self.fail(f"Не удалось начать запись видео: {e}")
            if log:
                log.close()
            return

        self.ready.set()
        cursor_scale = winutil.dpi_scale()
        fps = self.s.fps
        last = first
        try:
            self.clock.started.wait()
            while not self.stop_event.is_set():
                if self.clock.paused:
                    time.sleep(0.02)
                    continue
                wait = self.frames / fps - self.clock.active_time()
                if wait > 0:
                    time.sleep(min(wait, 0.05))
                    continue
                frame = self._compose(sct, region, w, h, last, cursor_scale)
                last = frame
                # Write as many frames as the wall clock asks for, so the video
                # is exactly as long as the sound even on a slow computer.
                due = int(self.clock.active_time() * fps) + 1
                count = max(1, due - self.frames)
                buf = frame.tobytes()
                for _ in range(count):
                    proc.stdin.write(buf)
                self.frames += count
        except (BrokenPipeError, OSError) as e:
            self.error = "Кодировщик видео остановился: " + (self._log_tail() or str(e))
        except Exception as e:
            self.error = f"Ошибка записи видео: {e}"
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.wait()
            log.close()
            if sct is not None:
                sct.close()
            if proc.returncode not in (0, None) and not self.error:
                self.error = "Кодировщик видео завершился с ошибкой: " + self._log_tail()

    def _compose(self, sct, region, w, h, last, cursor_scale):
        import cv2
        if sct is None:
            cam = self.webcam.frame
            if cam.shape[0] != h or cam.shape[1] != w:
                cam = cv2.resize(cam, (w, h))
            return cam
        try:
            img = np.asarray(sct.grab(region))
            if not img.flags.writeable:
                img = img.copy()
        except Exception:
            # e.g. the UAC prompt (secure desktop) cannot be captured
            img = last
        if self.s.draw_cursor:
            pos = winutil.cursor_pos()
            if pos:
                if img is last:
                    img = img.copy()
                draw_cursor(img, pos[0] - region["left"], pos[1] - region["top"], cursor_scale)
        if self.webcam is not None and self.webcam.frame is not None:
            if img is last:
                img = img.copy()
            overlay_webcam(img, self.webcam.frame, self.s.cam_position, self.s.cam_size)
        return img

    def _log_tail(self):
        try:
            with open(self.log_path, "rb") as f:
                return f.read()[-600:].decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
