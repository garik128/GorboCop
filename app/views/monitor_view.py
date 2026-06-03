"""Экран мониторинга: статус, превью камеры, причина срабатывания, кнопки."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk


class MonitorView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Статус.
        status_box = ctk.CTkFrame(self, fg_color="transparent")
        status_box.grid(row=0, column=0, pady=(10, 4), sticky="n")
        self.status_label = ctk.CTkLabel(
            status_box, text="Остановлено",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        self.status_label.pack()
        self.metrics_label = ctk.CTkLabel(
            status_box, text="", font=ctk.CTkFont(size=12), text_color="#999999"
        )
        self.metrics_label.pack()

        # Причина срабатывания.
        self.reason_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=14, weight="bold")
        )
        self.reason_label.grid(row=1, column=0, pady=(0, 4))

        # Превью камеры.
        self.preview = tk.Label(self, bg="#1b1b1b")
        self.preview.grid(row=2, column=0, padx=16, pady=6, sticky="nsew")

        # Кнопки управления.
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, padx=16, pady=(6, 12), sticky="ew")
        for i in range(3):
            buttons.grid_columnconfigure(i, weight=1)

        self.start_btn = ctk.CTkButton(buttons, text="Старт", command=app.toggle_start)
        self.start_btn.grid(row=0, column=0, padx=6, sticky="ew")
        self.pause_btn = ctk.CTkButton(
            buttons, text="Пауза", command=app.toggle_pause, state="disabled"
        )
        self.pause_btn.grid(row=0, column=1, padx=6, sticky="ew")
        self.calib_btn = ctk.CTkButton(
            buttons, text="Калибровать", command=app.calibrate
        )
        self.calib_btn.grid(row=0, column=2, padx=6, sticky="ew")

    # ---- обновление из App --------------------------------------------------
    def set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, text_color=color)

    def set_metrics(self, text: str) -> None:
        self.metrics_label.configure(text=text)

    def set_reason(self, text: str, color: str = "#e0863b") -> None:
        self.reason_label.configure(text=text, text_color=color)

    def set_image(self, photo) -> None:
        self.preview.configure(image=photo)

    def set_controls(self, running: bool, paused: bool) -> None:
        self.start_btn.configure(text="Стоп" if running else "Старт")
        self.pause_btn.configure(
            state="normal" if running else "disabled",
            text="Возобновить" if paused else "Пауза",
        )
