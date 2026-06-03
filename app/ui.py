"""Главное окно (customtkinter, тёмная тема): сайдбар + экраны монитора,
истории и настроек. Здесь же — оркестрация камеры/детектора в потоке-воркере.
"""
from __future__ import annotations

import dataclasses
import os
import threading
import time
import tkinter as tk

import cv2
import customtkinter as ctk
from PIL import Image, ImageTk

from . import autostart, single_instance
from .config import RESOURCE_DIR, Config
from .detector import DetectionResult, PostureDetector, PostureState
from .history import AlertHistory
from .notifier import Notifier
from .power_monitor import PowerMonitor
from .tray_icon import TrayIcon
from .views.history_view import HistoryView
from .views.monitor_view import MonitorView
from .views.settings_view import SettingsView


class AppState:
    STOPPED = "Остановлено"
    CALIBRATING = "Калибровка"
    MONITORING = "Мониторинг"
    ALERT = "Плохая поза!"
    PAUSED = "Пауза"
    SLEEPING = "Пропуск (экран спит)"
    IDLE = "Пропуск (нет активности)"
    NO_CAMERA = "Нет камеры"
    NO_FACE = "Лицо не найдено"
    NEED_CALIB = "Нужна калибровка"


_STATUS_COLORS = {
    AppState.STOPPED: "#888888",
    AppState.CALIBRATING: "#d8a200",
    AppState.MONITORING: "#2fa84f",
    AppState.ALERT: "#e03b3b",
    AppState.PAUSED: "#888888",
    AppState.SLEEPING: "#5577aa",
    AppState.IDLE: "#5577aa",
    AppState.NO_CAMERA: "#e03b3b",
    AppState.NO_FACE: "#b0902a",
    AppState.NEED_CALIB: "#d8a200",
}


class GorboCopApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config_data = Config.load()
        self.detector = PostureDetector(self.config_data)
        self.notifier = Notifier(self.config_data)
        self.history = AlertHistory(self.config_data.history_retention_days)
        self.power = PowerMonitor()

        # Рантайм-состояние.
        self._running = False
        self._paused = False
        self._bad_since: float | None = None
        self._last_bad = 0.0
        self._skip_reason: str | None = None  # None | "power" | "idle"
        self._alert_streak = 0  # тревог подряд без возврата к норме
        self._ui_visible = True
        self._alert_pending = False
        self._pending_reason = (False, False, 1.0, 0.0)
        self._latest: DetectionResult | None = None
        self._latest_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._preview_imgtk = None
        self._settings_imgtk = None
        self._current_view = "monitor"

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("GorboCop")
        self.geometry("840x660")
        self.minsize(760, 600)
        self._set_window_icon()

        self._build_layout()
        self.power.start()

        self.tray = TrayIcon(
            on_toggle_pause=lambda: self.after(0, self.toggle_pause),
            on_show=lambda: self.after(0, self.show_window),
            on_exit=lambda: self.after(0, self.exit_app),
            is_paused=lambda: self._paused,
        )
        self.tray.start()

        # Приёмник для контроля единственного экземпляра: вторая копия
        # попросит показать это окно.
        self._single = single_instance.SingleInstanceListener(
            on_show=lambda: self.after(0, self.show_window)
        )
        self._single.start()

        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self._poll_ui()

        if self.config_data.start_minimized:
            self.after(100, self.hide_to_tray)
        # Сразу включаем камеру и живое превью (без тревог до калибровки).
        self.after(200, self.start_monitoring)

    def _set_window_icon(self) -> None:
        ico = os.path.join(RESOURCE_DIR, "icon.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    # ---- разметка: сайдбар + контент ---------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=170, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        logo_path = os.path.join(RESOURCE_DIR, "icon.png")
        if os.path.exists(logo_path):
            self._logo_img = ctk.CTkImage(
                Image.open(logo_path), size=(110, 110)
            )
            ctk.CTkLabel(sidebar, image=self._logo_img, text="").pack(
                pady=(20, 16)
            )
        else:
            ctk.CTkLabel(
                sidebar, text="GorboCop",
                font=ctk.CTkFont(size=20, weight="bold"),
            ).pack(pady=(20, 16))

        self._nav_buttons = {}
        for key, label in [
            ("monitor", "Монитор"),
            ("history", "История"),
            ("settings", "Настройки"),
        ]:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w",
                command=lambda k=key: self.show_view(k),
            )
            btn.pack(fill="x", padx=12, pady=4)
            self._nav_buttons[key] = btn

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.monitor_view = MonitorView(self.container, self)
        self.history_view = HistoryView(self.container, self)
        self.settings_view = SettingsView(self.container, self)
        self._views = {
            "monitor": self.monitor_view,
            "history": self.history_view,
            "settings": self.settings_view,
        }

        self.show_view("monitor")

    def show_view(self, key: str) -> None:
        self._current_view = key
        # Показываем только активный экран (grid/grid_remove надёжнее tkraise,
        # особенно для CTkScrollableFrame настроек).
        for k, view in self._views.items():
            if k == key:
                view.grid(row=0, column=0, sticky="nsew")
            else:
                view.grid_remove()
        if key == "history":
            self.history_view.refresh()
        for k, btn in self._nav_buttons.items():
            btn.configure(fg_color=("#1f6aa5" if k == key else "#2b2b2b"))

    # ---- управление мониторингом -------------------------------------------
    def toggle_start(self) -> None:
        if self._running:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self) -> None:
        if self._running:
            return
        if not self.detector.open_camera():
            self._set_state(AppState.NO_CAMERA)
            return
        self._running = True
        self._paused = False
        self._bad_since = None
        self._worker = threading.Thread(
            target=self._worker_loop, name="GorboCopWorker", daemon=True
        )
        self._worker.start()
        self.monitor_view.set_controls(True, False)
        self.tray.refresh()

    def stop_monitoring(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self.detector.release_camera()
        self._paused = False
        self._set_state(AppState.STOPPED)
        self.monitor_view.set_reason("")
        self.monitor_view.set_metrics("")
        self.monitor_view.set_controls(False, False)
        self.tray.refresh()

    def toggle_pause(self) -> None:
        if not self._running:
            return
        self._paused = not self._paused
        self.monitor_view.set_controls(True, self._paused)
        if self._paused:
            self._set_state(AppState.PAUSED)
        self.tray.refresh()

    def calibrate(self) -> None:
        if not self._running:
            self.start_monitoring()
        if not self._running:
            return
        self._paused = False
        self.monitor_view.set_controls(True, False)
        self.detector.start_calibration()

    # ---- настройки: действия ------------------------------------------------
    def apply_autostart(self, enable: bool) -> None:
        actual = autostart.set_enabled(bool(enable))
        self.config_data.autostart = actual
        self.config_data.save()

    def reset_defaults(self) -> None:
        defaults = Config()
        for f in dataclasses.fields(Config):
            setattr(self.config_data, f.name, getattr(defaults, f.name))
        self.config_data.save()
        self.notifier.set_sound_path(self.config_data.sound_path)
        self.notifier.set_gain(self.config_data.sound_gain)
        self.history.set_retention(self.config_data.history_retention_days)
        autostart.set_enabled(self.config_data.autostart)
        # Работающий детектор держит копии baseline и порога уверенности —
        # синхронизируем, иначе сброс подействует только после перезапуска.
        self.detector.apply_config_baseline()
        self.detector.request_confidence(self.config_data.min_detection_confidence)
        self.settings_view.build()

    # ---- воркер -------------------------------------------------------------
    def _worker_loop(self) -> None:
        while self._running:
            if self._paused:
                time.sleep(0.1)
                continue

            skip = None
            if self.power.should_skip():
                skip = "power"
            else:
                idle_min = float(self.config_data.idle_skip_minutes or 0)
                if idle_min > 0 and PowerMonitor.idle_seconds() >= idle_min * 60:
                    skip = "idle"
            if skip:
                with self._latest_lock:
                    self._latest = DetectionResult(state=PostureState.NO_FACE)
                self._skip_reason = skip
                self._bad_since = None
                self._alert_streak = 0
                time.sleep(0.5)
                continue
            self._skip_reason = None

            result = self.detector.process_frame()
            with self._latest_lock:
                self._latest = result

            now = time.time()
            if result.state == PostureState.BAD:
                self._last_bad = now
                if self._bad_since is None:
                    self._bad_since = now
                elif now - self._bad_since >= self.config_data.alert_after_seconds:
                    self._pending_reason = (
                        result.approach, result.tilt,
                        result.size_ratio, result.y_delta,
                    )
                    self._alert_pending = True
            else:
                if self._bad_since is not None and (now - self._last_bad) > 0.5:
                    self._bad_since = None
                # Серия тревог сбрасывается только после устойчивого возврата
                # к норме: короткие «моргания» детекции лимит не обнуляют.
                if self._alert_streak and (now - self._last_bad) > 60.0:
                    self._alert_streak = 0

            # Свёрнутым в трей хватает ~8 кадров/с — экономим CPU.
            time.sleep(0.03 if self._ui_visible else 0.12)

    # ---- опрос UI -----------------------------------------------------------
    def _window_visible(self) -> bool:
        try:
            return self.state() in ("normal", "zoomed")
        except Exception:
            return True

    def _settings_muted(self) -> bool:
        """Тревоги глушатся, только пока настройки реально видны на экране."""
        return self._current_view == "settings" and self._ui_visible

    def _poll_ui(self) -> None:
        self._ui_visible = self._window_visible()

        # Тревога (звук + WinRT-тост) — из главного потока; запись в историю.
        # На видимом экране настроек тревоги глушим, чтобы крутить пороги.
        # Лимит серии: после max_consecutive_alerts тревог без возврата к норме
        # молчим — страховка от ложной «плохой позы» в пустой комнате.
        if self._alert_pending:
            self._alert_pending = False
            cap = int(self.config_data.max_consecutive_alerts or 0)
            allowed = cap <= 0 or self._alert_streak < cap
            if not self._settings_muted() and allowed and self.notifier.alert():
                self._alert_streak += 1
                self.history.add(*self._pending_reason)

        if self._running and not self._paused and self._ui_visible:
            with self._latest_lock:
                result = self._latest
            if self._current_view == "settings":
                if result is not None:
                    self._render_settings_live(result)
            elif self._skip_reason:
                self._set_state(
                    AppState.SLEEPING if self._skip_reason == "power"
                    else AppState.IDLE
                )
                self.monitor_view.set_reason("")
            elif result is not None:
                self._render_result(result)
        self.after(33, self._poll_ui)

    def _render_result(self, result: DetectionResult) -> None:
        if result.state == PostureState.CALIBRATING:
            pct = int(result.calibration_progress * 100)
            self._set_state(f"{AppState.CALIBRATING} {pct}%", AppState.CALIBRATING)
            self.monitor_view.set_reason(
                "Сидите ровно и не двигайтесь...", "#d8a200"
            )
        elif result.state == PostureState.NO_FACE:
            if result.camera_error:
                self._set_state(AppState.NO_CAMERA)
                self.monitor_view.set_reason("")
            else:
                self._set_state(AppState.NO_FACE)
                self.monitor_view.set_reason(
                    "Неподвижный объект в кадре — игнорируется"
                    if result.static_scene else ""
                )
        elif result.state == PostureState.BAD:
            self._set_state(AppState.ALERT)
            text = self._reason_text(result)
            cap = int(self.config_data.max_consecutive_alerts or 0)
            if cap > 0 and self._alert_streak >= cap:
                text += " (лимит тревог подряд исчерпан — тихо)"
            self.monitor_view.set_reason(text)
        elif not self.detector.is_calibrated:
            self._set_state(AppState.NEED_CALIB)
            self.monitor_view.set_reason(
                "Калибровка не удалась: лицо не было видно. Повторите."
                if self._calib_failed_recently() else
                "Сядьте ровно, откиньтесь на спинку — затем нажмите «Калибровать»",
                "#d8a200",
            )
        else:
            self._set_state(AppState.MONITORING)
            if self._calib_failed_recently():
                self.monitor_view.set_reason(
                    "Калибровка не удалась — действует прежняя", "#d8a200"
                )
            else:
                self.monitor_view.set_reason("Поза в норме", "#2fa84f")

        if self.detector.is_calibrated and result.state in (
            PostureState.GOOD, PostureState.BAD
        ):
            st = self.config_data.size_threshold
            yt = self.config_data.y_drop_threshold
            self.monitor_view.set_metrics(
                f"размер x{result.size_ratio:.2f} (порог {st:.2f})    "
                f"наклон Δy {result.y_delta:+.3f} (порог {yt:.3f})"
            )
        else:
            self.monitor_view.set_metrics("")

        if result.frame is not None:
            self._show_frame(result.frame)

    def _calib_failed_recently(self) -> bool:
        t = self.detector.calibration_failed_at
        return t is not None and (time.time() - t) < 10.0

    @staticmethod
    def _reason_text(result: DetectionResult) -> str:
        reasons = []
        if result.tilt:
            reasons.append("наклон вниз")
        if result.approach:
            reasons.append("приближение")
        return "Сработало: " + (" + ".join(reasons) if reasons else "—")

    def _render_settings_live(self, result: DetectionResult) -> None:
        """Живой индикатор на экране настроек: видно, сработало бы сейчас."""
        if result.state == PostureState.CALIBRATING:
            pct = int(result.calibration_progress * 100)
            state, color = f"Калибровка {pct}% — сидите ровно", "#d8a200"
        elif result.state == PostureState.NO_FACE:
            if result.camera_error:
                state, color = "Нет камеры", "#e03b3b"
            elif result.static_scene:
                state, color = "Неподвижный объект — игнорируется", "#888888"
            else:
                state, color = "Лицо не найдено", "#888888"
        elif not self.detector.is_calibrated:
            state, color = "Нужна калибровка", "#d8a200"
        elif result.approach or result.tilt:
            state = "Сработало бы: " + self._reason_text(result).replace(
                "Сработало: ", ""
            )
            color = "#e03b3b"
        else:
            state, color = "Поза в норме", "#2fa84f"

        if self.detector.is_calibrated and result.state in (
            PostureState.GOOD, PostureState.BAD
        ):
            st = self.config_data.size_threshold
            yt = self.config_data.y_drop_threshold
            metrics = (
                f"размер x{result.size_ratio:.2f} / порог {st:.2f}\n"
                f"наклон Δy {result.y_delta:+.3f} / порог {yt:.3f}"
            )
        else:
            metrics = ""

        photo = None
        if result.frame is not None:
            self._settings_imgtk = self._make_photo(result.frame, 200, 150)
            photo = self._settings_imgtk
        self.settings_view.update_live(state, color, metrics, photo)

    def _show_frame(self, frame_bgr) -> None:
        w = max(self.monitor_view.preview.winfo_width(), 320)
        h = max(self.monitor_view.preview.winfo_height(), 240)
        self._preview_imgtk = self._make_photo(frame_bgr, w, h)
        self.monitor_view.set_image(self._preview_imgtk)

    @staticmethod
    def _make_photo(frame_bgr, w, h):
        fh, fw = frame_bgr.shape[:2]
        scale = min(w / fw, h / fh)
        new_size = (max(int(fw * scale), 1), max(int(fh * scale), 1))
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize(new_size)
        return ImageTk.PhotoImage(img)

    def _set_state(self, text, color_key=None) -> None:
        key = color_key or text
        color = _STATUS_COLORS.get(key, "#dddddd")
        self.monitor_view.set_status(text, color)

    # ---- окно / трей / выход ------------------------------------------------
    def hide_to_tray(self) -> None:
        self.withdraw()

    def show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def exit_app(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self.detector.close()
        self.power.stop()
        self.tray.stop()
        self._single.stop()
        self.config_data.save()
        self.destroy()

    def run(self) -> None:
        self.mainloop()
