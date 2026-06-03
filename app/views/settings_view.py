"""Экран настроек: детекция, звук, текст уведомления, история, поведение."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk


class SettingsView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._save_job = None
        self.grid_columnconfigure(0, weight=1)
        self.build()

    # ---- отложенная запись конфига ------------------------------------------
    def _schedule_save(self) -> None:
        """Писать config.json один раз после серии изменений, а не на каждый
        тик слайдера при перетаскивании."""
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.after(600, self._do_save)

    def _do_save(self) -> None:
        self._save_job = None
        self.app.config_data.save()

    # ---- построение (вызывается заново при сбросе к дефолтам) ---------------
    def build(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._row = 0

        self._tuning_panel()

        self._section("Детекция")
        self._slider("Чувствительность к приближению", "size_threshold",
                     1.02, 1.6, invert=True)
        self._slider("Чувствительность к наклону вниз", "y_drop_threshold",
                     0.01, 0.25, invert=True)
        self._slider("Порог детекции лица (выше = строже)",
                     "min_detection_confidence", 0.3, 0.9, fmt="{:.2f}",
                     on_set=self.app.detector.request_confidence)
        self._slider("Задержка до тревоги (сек)", "alert_after_seconds",
                     0.5, 10.0, fmt="{:.1f}")
        self._slider("Пауза между тревогами (сек)", "cooldown_seconds",
                     5.0, 120.0, fmt="{:.0f}")

        self._section("Защита от ложных тревог")
        self._slider("Макс. тревог подряд (0 = без лимита)",
                     "max_consecutive_alerts", 0, 30, fmt="{:.0f}", as_int=True)
        self._slider("Пропуск, если нет активности (мин, 0 = выкл)",
                     "idle_skip_minutes", 0.0, 30.0, fmt="{:.0f}")

        self._section("Звук")
        self._sound_file_row()
        # Слайдер показывает усиление от 0 (без усиления) до 2x;
        # внутренний множитель = 1 + значение (offset=1.0).
        self._slider("Усиление громкости", "sound_gain", 0.0, 2.0,
                     fmt="{:.1f}x", offset=1.0, on_set=self.app.notifier.set_gain)
        self._switch("Звук включён", "sound_enabled")
        self._switch("Всплывающие уведомления", "toast_enabled")

        self._section("Текст уведомления")
        self._entry("Заголовок", "alert_title")
        self._entry("Текст", "alert_text")

        self._section("История")
        self._slider("Срок хранения истории (дней)", "history_retention_days",
                     1, 365, fmt="{:.0f}", as_int=True,
                     on_set=lambda v: self.app.history.set_retention(int(v)))

        self._section("Поведение")
        self._switch("Автозапуск с Windows", "autostart",
                     on_set=self.app.apply_autostart)
        self._switch("Запускать свёрнутым в трей", "start_minimized")

        # Сброс.
        reset = ctk.CTkButton(
            self, text="Сбросить к значениям по умолчанию",
            fg_color="#5a5a5a", hover_color="#6e6e6e",
            command=self.app.reset_defaults,
        )
        reset.grid(row=self._row, column=0, sticky="ew", padx=12, pady=(16, 8))

    # ---- живая панель настройки порогов ------------------------------------
    def _tuning_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=self._row, column=0, sticky="ew", padx=12, pady=(4, 8))
        panel.grid_columnconfigure(1, weight=1)
        self._row += 1

        # Превью слева.
        self.live_preview = tk.Label(panel, bg="#1b1b1b", width=200, height=150)
        self.live_preview.grid(row=0, column=0, rowspan=3, padx=10, pady=10)

        self.live_state = ctk.CTkLabel(
            panel, text="Настройка порогов",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.live_state.grid(row=0, column=1, sticky="w", padx=8, pady=(10, 0))

        self.live_metrics = ctk.CTkLabel(
            panel, text="", font=ctk.CTkFont(size=12), text_color="#999999",
            justify="left", anchor="w",
        )
        self.live_metrics.grid(row=1, column=1, sticky="w", padx=8)

        ctk.CTkButton(
            panel, text="Калибровать", width=130, command=self.app.calibrate
        ).grid(row=2, column=1, sticky="w", padx=8, pady=(4, 10))

        hint = ctk.CTkLabel(
            self,
            text="Двигайте ползунки и следите за индикатором. Пока открыты "
                 "настройки, звук и тосты не срабатывают.",
            font=ctk.CTkFont(size=11), text_color="#888888",
            wraplength=560, justify="left",
        )
        hint.grid(row=self._row, column=0, sticky="w", padx=14, pady=(0, 4))
        self._row += 1

    def update_live(self, state_text, color, metrics_text, photo) -> None:
        """Вызывается из App, пока экран настроек активен."""
        if not hasattr(self, "live_state"):
            return
        self.live_state.configure(text=state_text, text_color=color)
        self.live_metrics.configure(text=metrics_text)
        if photo is not None:
            self.live_preview.configure(image=photo)

    # ---- кирпичики ----------------------------------------------------------
    def _section(self, title: str) -> None:
        lbl = ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        )
        lbl.grid(row=self._row, column=0, sticky="ew", padx=12, pady=(14, 2))
        self._row += 1

    def _slider(self, label, attr, lo, hi, fmt="{:.2f}", invert=False,
                offset=0.0, on_set=None, as_int=False):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=self._row, column=0, sticky="ew", padx=12, pady=4)
        frame.grid_columnconfigure(1, weight=1)
        self._row += 1

        ctk.CTkLabel(frame, text=label, anchor="w").grid(
            row=0, column=0, padx=(0, 10), sticky="w"
        )
        value_lbl = ctk.CTkLabel(frame, text="", width=56)
        value_lbl.grid(row=0, column=2, padx=(8, 0))

        # invert: положение слайдера зеркалит порог (вправо = чувствительнее).
        # offset: сохранённое значение = значение слайдера + offset.
        def to_threshold(v):
            return (lo + hi - v) if invert else (v + offset)

        def to_slider(t):
            return (lo + hi - t) if invert else (t - offset)

        def fmt_value(v):
            if invert:
                return f"{(v - lo) / (hi - lo) * 100:.0f}%"
            return fmt.format(v)

        def on_change(v):
            t = to_threshold(float(v))
            if as_int:
                t = int(round(t))
            setattr(self.app.config_data, attr, t)
            value_lbl.configure(text=fmt_value(float(v)))
            self._schedule_save()
            if on_set is not None:
                on_set(t)

        slider = ctk.CTkSlider(frame, from_=lo, to=hi, command=on_change)
        start_v = to_slider(getattr(self.app.config_data, attr))
        slider.set(start_v)
        slider.grid(row=0, column=1, sticky="ew")
        value_lbl.configure(text=fmt_value(start_v))

    def _switch(self, label, attr, on_set=None):
        var = ctk.BooleanVar(value=bool(getattr(self.app.config_data, attr)))

        def on_change():
            val = var.get()
            setattr(self.app.config_data, attr, val)
            self.app.config_data.save()
            if on_set is not None:
                on_set(val)

        sw = ctk.CTkSwitch(self, text=label, variable=var, command=on_change)
        sw.grid(row=self._row, column=0, sticky="w", padx=12, pady=5)
        self._row += 1

    def _entry(self, label, attr):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=self._row, column=0, sticky="ew", padx=12, pady=4)
        frame.grid_columnconfigure(1, weight=1)
        self._row += 1

        ctk.CTkLabel(frame, text=label, width=90, anchor="w").grid(
            row=0, column=0, padx=(0, 10), sticky="w"
        )
        entry = ctk.CTkEntry(frame)
        entry.insert(0, str(getattr(self.app.config_data, attr)))
        entry.grid(row=0, column=1, sticky="ew")

        def on_key(_event=None):
            setattr(self.app.config_data, attr, entry.get())
            self._schedule_save()

        entry.bind("<KeyRelease>", on_key)

    def _sound_file_row(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=self._row, column=0, sticky="ew", padx=12, pady=4)
        frame.grid_columnconfigure(0, weight=1)
        self._row += 1

        name = os.path.basename(self.app.config_data.sound_path)
        self._sound_lbl = ctk.CTkLabel(frame, text=f"Файл: {name}", anchor="w")
        self._sound_lbl.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(frame, text="Выбрать...", width=90,
                      command=self._choose_sound).grid(row=0, column=1, padx=4)
        ctk.CTkButton(frame, text="Проверить", width=90,
                      command=self.app.notifier.play_test).grid(row=0, column=2)

    def _choose_sound(self):
        path = filedialog.askopenfilename(
            title="Выберите звук тревоги",
            filetypes=[("Аудио", "*.mp3 *.wav *.ogg"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        ok = self.app.notifier.set_sound_path(path)
        self.app.config_data.save()
        name = os.path.basename(path)
        self._sound_lbl.configure(
            text=f"Файл: {name}" if ok else f"Не удалось загрузить: {name}"
        )
