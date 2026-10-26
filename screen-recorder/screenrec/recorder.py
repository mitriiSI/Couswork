"""Starts the capture threads and glues the tracks into the final file."""

import dataclasses
import datetime
import os
import shutil
import subprocess
import tempfile
import wave

from . import winutil
from .capture import AudioCapture, Clock, VideoCapture, WebcamCapture
from .devices import ffmpeg_exe


class RecorderError(Exception):
    pass


@dataclasses.dataclass
class Settings:
    screen: bool = True
    monitor: int = 1
    system_audio: bool = True
    speaker_id: str = ""
    microphone: bool = False
    mic_id: str = ""
    webcam: bool = False
    camera_index: int = 0
    cam_position: str = "br"  # tl, tr, bl, br
    cam_size: float = 0.25    # share of the video width
    fps: int = 30
    max_height: int = 0       # 0 = original size
    draw_cursor: bool = True
    hide_window: bool = True
    output_dir: str = ""

    @property
    def has_video(self):
        return self.screen or self.webcam

    @property
    def has_audio(self):
        return self.system_audio or self.microphone

    def describe(self):
        parts = []
        if self.screen:
            parts.append("экран")
        if self.webcam:
            parts.append("веб-камера")
        if self.system_audio:
            parts.append("звук компьютера")
        if self.microphone:
            parts.append("микрофон")
        return " + ".join(parts)


_mp3_supported = {}


def audio_format(ffmpeg):
    """('.mp3', [codec args]) or AAC in .m4a if this ffmpeg has no MP3 encoder."""
    if ffmpeg not in _mp3_supported:
        try:
            out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                 timeout=20, creationflags=winutil.NO_WINDOW)
            _mp3_supported[ffmpeg] = b"libmp3lame" in out.stdout
        except Exception:
            _mp3_supported[ffmpeg] = False
    if _mp3_supported[ffmpeg]:
        return ".mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]
    return ".m4a", ["-c:a", "aac", "-b:a", "192k"]


def wav_has_data(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() > 0
    except Exception:
        return False


def mux(ffmpeg, video_path, audio_paths, out_path, log_path=None):
    """Join the video track and the sound tracks (mixed together) into out_path."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    inputs = ([video_path] if video_path else []) + list(audio_paths)
    for p in inputs:
        cmd += ["-i", p]
    first_audio = 1 if video_path else 0
    if video_path:
        cmd += ["-map", "0:v", "-c:v", "copy"]
    if len(audio_paths) == 1:
        cmd += ["-map", f"{first_audio}:a"]
    elif len(audio_paths) > 1:
        labels = "".join(f"[{first_audio + i}:a]" for i in range(len(audio_paths)))
        cmd += ["-filter_complex",
                f"{labels}amix=inputs={len(audio_paths)}:duration=longest:dropout_transition=0:normalize=0[a]",
                "-map", "[a]"]
    if audio_paths:
        if video_path:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += audio_format(ffmpeg)[1]
        cmd += ["-ac", "2", "-ar", "48000"]
    if out_path.lower().endswith(".mp4"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(out_path)
    res = subprocess.run(cmd, capture_output=True, creationflags=winutil.NO_WINDOW)
    if log_path:
        with open(log_path, "ab") as f:
            f.write(b"$ " + " ".join(cmd).encode("utf-8", "replace") + b"\n" + res.stderr)
    if res.returncode != 0 or not os.path.exists(out_path):
        raise RecorderError("Не удалось сохранить файл: " +
                            res.stderr.decode("utf-8", "replace")[-600:])
    return out_path


def unique_path(folder, ext):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(folder, f"Запись_{stamp}{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"Запись_{stamp}_{n}{ext}")
        n += 1
    return path


class Recorder:
    def __init__(self, settings: Settings):
        if not settings.has_video and not settings.has_audio:
            raise RecorderError("Включите хотя бы один источник: экран, звук компьютера, микрофон или веб-камеру.")
        self.s = settings
        self.ffmpeg = ffmpeg_exe()
        self.clock = Clock()
        self.stop_event = None
        self.tmp = None
        self.video = None
        self.webcam = None
        self.audio = []
        self.warnings = []

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        os.makedirs(self.s.output_dir, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="screenrec_")
        import threading
        self.stop_event = threading.Event()
        try:
            if self.s.webcam:
                self.webcam = WebcamCapture(self.s.camera_index, self.stop_event)
                self._start_and_wait(self.webcam, 15)
            if self.s.system_audio:
                self.audio.append(AudioCapture("system", self.s.speaker_id,
                                               os.path.join(self.tmp, "system.wav"),
                                               self.clock, self.stop_event))
            if self.s.microphone:
                self.audio.append(AudioCapture("mic", self.s.mic_id,
                                               os.path.join(self.tmp, "mic.wav"),
                                               self.clock, self.stop_event))
            for a in self.audio:
                self._start_and_wait(a, 10)
            if self.s.has_video:
                self.video = VideoCapture(self.s, os.path.join(self.tmp, "video.mkv"),
                                          os.path.join(self.tmp, "ffmpeg.log"),
                                          self.clock, self.stop_event, self.webcam, self.ffmpeg)
                self._start_and_wait(self.video, 15)
        except Exception:
            self.stop_event.set()
            self._join()
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise
        self.clock.start()

    def _start_and_wait(self, thread, timeout):
        thread.start()
        if not thread.ready.wait(timeout):
            raise RecorderError("Устройство не отвечает. Попробуйте ещё раз или выберите другое.")
        if thread.error:
            raise RecorderError(thread.error)

    def _join(self):
        for t in [self.video, self.webcam, *self.audio]:
            if t is not None and t.is_alive():
                t.join(timeout=30)

    @property
    def paused(self):
        return self.clock.paused

    def pause(self):
        self.clock.pause()

    def resume(self):
        self.clock.resume()

    def elapsed(self):
        return self.clock.active_time()

    def fatal_error(self):
        """Error that makes further recording pointless (video stopped)."""
        if self.video is not None and self.video.error:
            return self.video.error
        if not self.s.has_video and self.audio and all(a.error for a in self.audio):
            return self.audio[0].error
        return None

    def stop(self):
        """Stop and save. Returns the path of the saved file."""
        self.clock.pause()  # freeze every track at the same moment
        self.stop_event.set()
        self._join()
        for t in [self.webcam, *self.audio]:
            if t is not None and t.error:
                self.warnings.append(t.error)
        if self.video is not None and self.video.error:
            if not (os.path.exists(self.video.path) and self.video.frames > 0):
                raise RecorderError(self.video.error)
            self.warnings.append(self.video.error)

        audio_files = [a.path for a in self.audio if wav_has_data(a.path)]
        log = os.path.join(self.tmp, "ffmpeg.log")
        if self.video is not None:
            out = unique_path(self.s.output_dir, ".mp4")
            mux(self.ffmpeg, self.video.path, audio_files, out, log)
        else:
            if not audio_files:
                raise RecorderError("Звук не записался: устройство не передало данных.")
            out = unique_path(self.s.output_dir, audio_format(self.ffmpeg)[0])
            mux(self.ffmpeg, None, audio_files, out, log)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return out
