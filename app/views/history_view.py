"""Экран истории: сводка, столбчатый график по дням, список последних событий."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime

import customtkinter as ctk


class HistoryView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        title = ctk.CTkLabel(
            self, text="История срабатываний",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        title.grid(row=0, column=0, pady=(10, 8), sticky="w", padx=16)

        # Карточки сводки.
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="ew", padx=12)
        for i in range(5):
            cards.grid_columnconfigure(i, weight=1)
        self._cards = {}
        for i, (key, label) in enumerate([
            ("today", "Сегодня"),
            ("week", "За неделю"),
            ("total", "Всего"),
            ("tilt", "Наклон"),
            ("approach", "Приближение"),
        ]):
            self._cards[key] = self._make_card(cards, i, label)

        # График.
        chart_box = ctk.CTkFrame(self)
        chart_box.grid(row=2, column=0, sticky="nsew", padx=16, pady=10)
        chart_box.grid_columnconfigure(0, weight=1)
        chart_box.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            chart_box, text="Срабатываний по дням",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))
        self.canvas = tk.Canvas(chart_box, bg="#1f1f1f", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.canvas.bind("<Configure>", lambda e: self._draw_chart())

        # Нижняя панель.
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        bottom.grid_columnconfigure(0, weight=1)
        self.last_label = ctk.CTkLabel(bottom, text="", anchor="w", justify="left")
        self.last_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            bottom, text="Очистить историю", width=140,
            fg_color="#7a2e2e", hover_color="#933",
            command=self._clear,
        ).grid(row=0, column=1, sticky="e")

        self._stats = None

    def _make_card(self, parent, col, label):
        card = ctk.CTkFrame(parent)
        card.grid(row=0, column=col, padx=6, pady=4, sticky="ew")
        value = ctk.CTkLabel(card, text="0", font=ctk.CTkFont(size=26, weight="bold"))
        value.pack(pady=(10, 0))
        ctk.CTkLabel(
            card, text=label, font=ctk.CTkFont(size=12), text_color="#999999"
        ).pack(pady=(0, 10))
        return value

    # ---- обновление ---------------------------------------------------------
    def refresh(self) -> None:
        self._stats = self.app.history.stats()
        for key, widget in self._cards.items():
            widget.configure(text=str(self._stats.get(key, 0)))
        self._draw_chart()
        self._draw_last()

    def _draw_last(self) -> None:
        if not self._stats:
            return
        events = self._stats.get("last_events", [])
        if not events:
            self.last_label.configure(text="Последние события: пока нет")
            return
        lines = ["Последние события:"]
        for e in events[:6]:
            t = datetime.fromtimestamp(e.get("ts", 0)).strftime("%d.%m %H:%M")
            reason = []
            if e.get("tilt"):
                reason.append("наклон")
            if e.get("approach"):
                reason.append("приближение")
            lines.append(f"  {t} — {' + '.join(reason) or '—'}")
        self.last_label.configure(text="\n".join(lines))

    def _draw_chart(self) -> None:
        c = self.canvas
        c.delete("all")
        if not self._stats:
            return
        by_day = self._stats.get("by_day", [])
        if not by_day:
            return
        w = c.winfo_width() or 600
        h = c.winfo_height() or 200
        pad_l, pad_b, pad_t = 30, 22, 12
        max_v = max((v for _, v in by_day), default=0)
        max_v = max(max_v, 1)
        n = len(by_day)
        avail_w = w - pad_l - 10
        bar_w = avail_w / n
        base_y = h - pad_b

        # Горизонтальная база.
        c.create_line(pad_l, base_y, w - 6, base_y, fill="#444")

        for i, (d, v) in enumerate(by_day):
            x0 = pad_l + i * bar_w + bar_w * 0.15
            x1 = pad_l + (i + 1) * bar_w - bar_w * 0.15
            bar_h = (h - pad_b - pad_t) * (v / max_v)
            y0 = base_y - bar_h
            color = "#3a7bd5" if v == 0 else "#e0863b" if v >= max_v else "#4a90e2"
            if v > 0:
                c.create_rectangle(x0, y0, x1, base_y, fill=color, outline="")
                c.create_text(
                    (x0 + x1) / 2, y0 - 8, text=str(v),
                    fill="#ddd", font=("TkDefaultFont", 8),
                )
            # Подпись дня (число месяца) для каждого 2-го столбца.
            if n <= 16 or i % 2 == 0:
                c.create_text(
                    (x0 + x1) / 2, base_y + 10, text=d.strftime("%d"),
                    fill="#888", font=("TkDefaultFont", 7),
                )

    def _clear(self) -> None:
        self.app.history.clear()
        self.refresh()
