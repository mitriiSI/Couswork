"""Main window."""

import dataclasses
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, APP_VERSION, devices, winutil
from .hotkeys import GlobalHotkeys
from .recorder import Recorder, RecorderError, Settings

FPS_CHOICES = [15, 24, 30, 60]
POSITION_CHOICES = [("br", "Справа внизу"), ("bl", "Слева внизу"), ("tr", "Справа вверху"), ("tl", "Слева вверху")]
CAM_SIZE_CHOICES = [(0.18, "Маленькая"), (0.25, "Средняя"), (0.35, "Большая")]
SIZE_CHOICES = [(0, "Как на экране"), (1080, "1080p (Full HD)"), (720, "720p (HD)")]

RED = "#d93a3a"
RED_ACTIVE = "#b82f2f"
GREY = "#5b6470"
GREY_ACTIVE = "#4a525c"


def load_settings():
    s = Settings(output_dir=winutil.default_output_dir())
    try:
        with open(winutil.settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        for field in dataclasses.fields(Settings):
            if field.name in data and isinstance(data[field.name], type(getattr(s, field.name))):
                setattr(s, field.name, data[field.name])
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        path = winutil.settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(s), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class DeviceCombo(ttk.Combobox):
    """Combobox that keeps (value, label) pairs."""

    def __init__(self, master, width=42):
        super().__init__(master, state="readonly", width=width)
        self.items = []

    def set_items(self, items, selected=None):
        self.items = list(items)
        self["values"] = [label for _, label in self.items]
        index = 0
        for i, (value, _) in enumerate(self.items):
            if value == selected:
                index = i
                break
        if self.items:
            self.current(index)
        else:
            self.set("")

    def value(self, default=None):
        i = self.current()
        if 0 <= i < len(self.items):
            return self.items[i][0]
        return default


class App:
    def __init__(self, root):
        self.root = root
        self.s = load_settings()
        self.recorder = None
        self.state = "idle"  # idle, starting, recording, saving
        self.events = queue.Queue()
        self.last_file = None
        self.hotkeys = GlobalHotkeys()

        root.title(f"{APP_NAME} {APP_VERSION}")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._set_icon()
        self._build()
        self.reload_devices()
        self._update_summary()
        self.root.after(100, self._tick)

    # -- layout --------------------------------------------------------------

    def _set_icon(self):
        import sys
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico = os.path.join(base, "icon.ico")
        if winutil.IS_WINDOWS and os.path.exists(ico):
            try:
                self.root.iconbitmap(default=ico)
            except Exception:
                pass

    def _build(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Timer.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Src.TCheckbutton", font=("Segoe UI", 10, "bold"))

        main = ttk.Frame(self.root, padding=14)
        main.grid(sticky="nsew")

        ttk.Label(main, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(main, text="Отметьте, что записывать. Всё включается отдельно и в любых сочетаниях.",
                  style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))

        src = ttk.LabelFrame(main, text=" Что записывать ", padding=10)
        src.grid(row=2, column=0, sticky="ew")
        src.columnconfigure(1, weight=1)

        self.v_screen = tk.BooleanVar(value=self.s.screen)
        self.v_system = tk.BooleanVar(value=self.s.system_audio)
        self.v_mic = tk.BooleanVar(value=self.s.microphone)
        self.v_cam = tk.BooleanVar(value=self.s.webcam)

        rows = [
            (self.v_screen, "Экран", "видео с монитора"),
            (self.v_system, "Звук компьютера", "то, что играет в колонках/наушниках"),
            (self.v_mic, "Микрофон", "ваш голос (диктофон)"),
            (self.v_cam, "Веб-камера", "картинка с камеры"),
        ]
        self.combos = []
        self.source_checks = []
        for r, (var, title, hint) in enumerate(rows):
            box = ttk.Frame(src)
            box.grid(row=r * 2, column=0, sticky="w", pady=(6 if r else 0, 0))
            cb = ttk.Checkbutton(box, text=title, variable=var, style="Src.TCheckbutton",
                                 command=self._update_summary)
            cb.pack(anchor="w")
            ttk.Label(box, text=hint, style="Hint.TLabel").pack(anchor="w", padx=(22, 0))
            self.source_checks.append(cb)
            combo = DeviceCombo(src)
            combo.grid(row=r * 2, column=1, sticky="e", padx=(16, 0))
            self.combos.append(combo)
        self.c_monitor, self.c_speaker, self.c_mic, self.c_cam = self.combos

        cam_opts = ttk.Frame(src)
        cam_opts.grid(row=8, column=1, sticky="e", pady=(4, 0))
        ttk.Label(cam_opts, text="Где на экране:").pack(side="left")
        self.c_cam_pos = DeviceCombo(cam_opts, width=14)
        self.c_cam_pos.set_items(POSITION_CHOICES, self.s.cam_position)
        self.c_cam_pos.pack(side="left", padx=(4, 10))
        ttk.Label(cam_opts, text="Размер:").pack(side="left")
        self.c_cam_size = DeviceCombo(cam_opts, width=10)
        self.c_cam_size.set_items(CAM_SIZE_CHOICES, self.s.cam_size)
        self.c_cam_size.pack(side="left", padx=(4, 0))

        ttk.Button(src, text="Обновить список устройств", command=self.reload_devices).grid(
            row=9, column=1, sticky="e", pady=(8, 0))

        self.summary = ttk.Label(main, text="", foreground="#1f6f3f", font=("Segoe UI", 10, "bold"))
        self.summary.grid(row=3, column=0, sticky="w", pady=(8, 0))

        opts = ttk.LabelFrame(main, text=" Настройки ", padding=10)
        opts.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(opts, text="Кадров в секунду:").grid(row=0, column=0, sticky="w")
        self.c_fps = DeviceCombo(opts, width=6)
        self.c_fps.set_items([(f, str(f)) for f in FPS_CHOICES], self.s.fps)
        self.c_fps.grid(row=0, column=1, sticky="w", padx=(6, 20))
        ttk.Label(opts, text="Размер видео:").grid(row=0, column=2, sticky="w")
        self.c_size = DeviceCombo(opts, width=16)
        self.c_size.set_items(SIZE_CHOICES, self.s.max_height)
        self.c_size.grid(row=0, column=3, sticky="w", padx=(6, 0))
        self.v_cursor = tk.BooleanVar(value=self.s.draw_cursor)
        self.v_hide = tk.BooleanVar(value=self.s.hide_window)
        ttk.Checkbutton(opts, text="Показывать курсор мыши", variable=self.v_cursor).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(opts, text="Не показывать это окно на записи", variable=self.v_hide).grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))

        folder = ttk.LabelFrame(main, text=" Куда сохранять ", padding=10)
        folder.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        folder.columnconfigure(0, weight=1)
        self.v_folder = tk.StringVar(value=self.s.output_dir)
        ttk.Entry(folder, textvariable=self.v_folder, state="readonly").grid(row=0, column=0, sticky="ew")
        ttk.Button(folder, text="Изменить…", command=self.choose_folder).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(folder, text="Открыть папку", command=self.open_folder).grid(row=0, column=2, padx=(6, 0))

        ctl = ttk.Frame(main)
        ctl.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        ctl.columnconfigure(3, weight=1)
        btn = {"font": ("Segoe UI", 11, "bold"), "fg": "white", "relief": "flat",
               "padx": 14, "pady": 8, "cursor": "hand2", "bd": 0, "activeforeground": "white"}
        self.b_start = tk.Button(ctl, text="●  Начать запись", bg=RED, activebackground=RED_ACTIVE,
                                 command=self.toggle, **btn)
        self.b_start.grid(row=0, column=0)
        self.b_pause = tk.Button(ctl, text="❚❚  Пауза", bg=GREY, activebackground=GREY_ACTIVE,
                                 command=self.toggle_pause, state="disabled", **btn)
        self.b_pause.grid(row=0, column=1, padx=(8, 0))
        self.timer = ttk.Label(ctl, text="00:00:00", style="Timer.TLabel")
        self.timer.grid(row=0, column=3, sticky="e")

        ttk.Label(main, text="Горячие клавиши: F9 — начать / остановить, F10 — пауза",
                  style="Hint.TLabel").grid(row=7, column=0, sticky="w", pady=(8, 0))

        status = ttk.Frame(main)
        status.grid(row=8, column=0, sticky="ew", pady=(6, 0))
        status.columnconfigure(0, weight=1)
        self.status = ttk.Label(status, text="Готово к записи.", wraplength=520)
        self.status.grid(row=0, column=0, sticky="w")
        self.b_show = ttk.Button(status, text="Показать файл", command=self.show_file)
        self.b_show.grid(row=0, column=1, sticky="e")
        self.b_show.grid_remove()

        for var in (self.v_screen, self.v_system, self.v_mic, self.v_cam):
            var.trace_add("write", lambda *_: self._update_summary())

    # -- devices -------------------------------------------------------------

    def reload_devices(self):
        self.c_monitor.set_items(devices.list_monitors(), self.s.monitor)
        speakers = devices.list_speakers()
        self.c_speaker.set_items(speakers or [("", "Устройство по умолчанию")], self.s.speaker_id)
        mics = devices.list_microphones()
        self.c_mic.set_items(mics or [("", "Микрофон не найден")], self.s.mic_id)
        self.c_cam.set_items([(self.s.camera_index, "Поиск камер…")], self.s.camera_index)

        def find_cameras():
            cams = devices.list_cameras()
            self.events.put(("cameras", cams))

        threading.Thread(target=find_cameras, daemon=True).start()

    # -- settings ------------------------------------------------------------

    def collect_settings(self):
        s = Settings(
            screen=self.v_screen.get(),
            monitor=self.c_monitor.value(1),
            system_audio=self.v_system.get(),
            speaker_id=self.c_speaker.value("") or "",
            microphone=self.v_mic.get(),
            mic_id=self.c_mic.value("") or "",
            webcam=self.v_cam.get(),
            camera_index=self.c_cam.value(0),
            cam_position=self.c_cam_pos.value("br"),
            cam_size=self.c_cam_size.value(0.25),
            fps=self.c_fps.value(30),
            max_height=self.c_size.value(0),
            draw_cursor=self.v_cursor.get(),
            hide_window=self.v_hide.get(),
            output_dir=self.v_folder.get() or winutil.default_output_dir(),
        )
        self.s = s
        return s

    def _update_summary(self):
        s = Settings(screen=self.v_screen.get(), system_audio=self.v_system.get(),
                     microphone=self.v_mic.get(), webcam=self.v_cam.get())
        if not s.has_video and not s.has_audio:
            text, color = "Ничего не выбрано — отметьте хотя бы один пункт.", "#b02a2a"
        elif s.has_video:
            extra = ""
            if s.screen and s.webcam:
                extra = " (камера — в углу экрана)"
            text, color = f"Будет записано видео MP4: {s.describe()}{extra}", "#1f6f3f"
        else:
            text, color = f"Будет записан только звук (MP3): {s.describe()}", "#1f6f3f"
        self.summary.configure(text=text, foreground=color)

    def choose_folder(self):
        path = filedialog.askdirectory(initialdir=self.v_folder.get() or None,
                                       title="Папка для записей")
        if path:
            self.v_folder.set(os.path.normpath(path))

    def open_folder(self):
        path = self.v_folder.get()
        os.makedirs(path, exist_ok=True)
        winutil.open_folder(path)

    def show_file(self):
        if self.last_file and os.path.exists(self.last_file):
            winutil.show_in_explorer(self.last_file)

    # -- recording -----------------------------------------------------------

    def toggle(self):
        if self.state == "idle":
            self.start()
        elif self.state == "recording":
            self.stop()

    def start(self):
        s = self.collect_settings()
        save_settings(s)
        try:
            rec = Recorder(s)
        except RecorderError as e:
            messagebox.showwarning(APP_NAME, str(e))
            return
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Не удалось подготовить запись:\n{e}")
            return
        self.recorder = rec
        self._set_state("starting")
        self.b_show.grid_remove()
        self.status.configure(text="Включаю устройства…")

        def work():
            try:
                rec.start()
                self.events.put(("started", None))
            except Exception as e:
                self.events.put(("start_failed", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        if self.state != "recording":
            return
        rec = self.recorder
        self._set_state("saving")
        self.status.configure(text="Сохраняю файл…")

        def work():
            try:
                path = rec.stop()
                self.events.put(("saved", (path, rec.warnings)))
            except Exception as e:
                self.events.put(("save_failed", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def toggle_pause(self):
        if self.state != "recording":
            return
        if self.recorder.paused:
            self.recorder.resume()
            self.b_pause.configure(text="❚❚  Пауза")
            self.status.configure(text="Идёт запись…")
        else:
            self.recorder.pause()
            self.b_pause.configure(text="▶  Продолжить")
            self.status.configure(text="Пауза. Нажмите «Продолжить» или F10.")

    def _set_state(self, state):
        self.state = state
        idle = state == "idle"
        widget_state = "normal" if idle else "disabled"
        for cb in self.source_checks:
            cb.configure(state=widget_state)
        for c in self.combos + [self.c_cam_pos, self.c_cam_size, self.c_fps, self.c_size]:
            c.configure(state="readonly" if idle else "disabled")
        if state == "recording":
            self.b_start.configure(text="■  Остановить", state="normal", bg=GREY, activebackground=GREY_ACTIVE)
            self.b_pause.configure(state="normal", text="❚❚  Пауза")
        else:
            self.b_start.configure(text="●  Начать запись", bg=RED, activebackground=RED_ACTIVE,
                                   state="normal" if idle else "disabled")
            self.b_pause.configure(state="disabled", text="❚❚  Пауза")
        hide = state in ("starting", "recording") and self.s.hide_window and self.s.screen
        winutil.exclude_from_capture(self.root, hide)

    def _tick(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                self._handle(kind, data)
        except queue.Empty:
            pass
        try:
            while True:
                action = self.hotkeys.events.get_nowait()
                if action == "toggle":
                    self.toggle()
                elif action == "pause":
                    self.toggle_pause()
        except queue.Empty:
            pass
        if self.state == "recording":
            t = int(self.recorder.elapsed())
            self.timer.configure(text=f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}",
                                 foreground="#999999" if self.recorder.paused else RED)
            err = self.recorder.fatal_error()
            if err:
                self.stop()
        self.root.after(200, self._tick)

    def _handle(self, kind, data):
        if kind == "cameras":
            self.c_cam.set_items(data or [(0, "Камера не найдена")], self.s.camera_index)
        elif kind == "started":
            self._set_state("recording")
            self.status.configure(text=f"Идёт запись: {self.recorder.s.describe()}.")
        elif kind == "start_failed":
            self._set_state("idle")
            self.timer.configure(text="00:00:00", foreground="")
            self.status.configure(text="Запись не началась.")
            messagebox.showerror(APP_NAME, data)
        elif kind == "saved":
            path, warnings = data
            self.last_file = path
            self._set_state("idle")
            self.timer.configure(foreground="")
            self.status.configure(text=f"Сохранено: {path}")
            self.b_show.grid()
            if warnings:
                messagebox.showwarning(APP_NAME, "Файл сохранён, но были проблемы:\n\n" + "\n".join(warnings))
        elif kind == "save_failed":
            self._set_state("idle")
            self.timer.configure(foreground="")
            self.status.configure(text="Не удалось сохранить запись.")
            messagebox.showerror(APP_NAME, data)

    def on_close(self):
        if self.state in ("recording", "starting", "saving"):
            if not messagebox.askyesno(APP_NAME, "Идёт запись. Остановить и сохранить её перед выходом?"):
                return
            if self.state == "recording":
                self.stop()
            self._close_when_idle()
            return
        self._quit()

    def _close_when_idle(self):
        if self.state == "idle":
            self._quit()
        else:
            if self.state == "recording":
                self.stop()
            self.root.after(300, self._close_when_idle)

    def _quit(self):
        try:
            save_settings(self.collect_settings())
        except Exception:
            pass
        self.hotkeys.close()
        self.root.destroy()


def run():
    winutil.set_dpi_aware()
    winutil.com_init_sta()
    root = tk.Tk()
    App(root)
    root.mainloop()
