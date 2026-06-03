"""Хранение истории срабатываний в history.json и агрегация для дашборда."""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta

from .config import APP_DIR

HISTORY_PATH = os.path.join(APP_DIR, "history.json")


class AlertHistory:
    def __init__(self, retention_days: int):
        self.retention_days = int(retention_days)
        self._events: list[dict] = []
        self._load()
        self.prune()

    # ---- хранение -----------------------------------------------------------
    def _load(self) -> None:
        if os.path.exists(HISTORY_PATH):
            try:
                with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._events = [e for e in data if isinstance(e, dict)]
            except (json.JSONDecodeError, OSError):
                self._events = []

    def _save(self) -> None:
        try:
            with open(HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump(self._events, f, ensure_ascii=False)
        except OSError:
            pass

    # ---- операции -----------------------------------------------------------
    def add(self, approach: bool, tilt: bool, size_ratio: float, y_delta: float) -> None:
        self._events.append({
            "ts": time.time(),
            "approach": bool(approach),
            "tilt": bool(tilt),
            "size_ratio": round(float(size_ratio), 3),
            "y_delta": round(float(y_delta), 3),
        })
        self.prune()
        self._save()

    def prune(self) -> None:
        cutoff = time.time() - self.retention_days * 86400
        before = len(self._events)
        self._events = [e for e in self._events if e.get("ts", 0) >= cutoff]
        if len(self._events) != before:
            self._save()

    def set_retention(self, days: int) -> None:
        self.retention_days = int(days)
        self.prune()

    def clear(self) -> None:
        self._events = []
        self._save()

    # ---- агрегаты для дашборда ---------------------------------------------
    def stats(self, days: int = 14) -> dict:
        now = datetime.now()
        today = now.date()
        week_ago = (now - timedelta(days=7)).timestamp()

        total = len(self._events)
        today_count = 0
        week_count = 0
        approach_count = 0
        tilt_count = 0

        # Счётчики по дням за последние `days` суток.
        by_day = {today - timedelta(days=i): 0 for i in range(days - 1, -1, -1)}

        for e in self._events:
            ts = e.get("ts", 0)
            d = datetime.fromtimestamp(ts).date()
            if d == today:
                today_count += 1
            if ts >= week_ago:
                week_count += 1
            if e.get("approach"):
                approach_count += 1
            if e.get("tilt"):
                tilt_count += 1
            if d in by_day:
                by_day[d] += 1

        ordered = sorted(by_day.items())
        return {
            "total": total,
            "today": today_count,
            "week": week_count,
            "approach": approach_count,
            "tilt": tilt_count,
            "by_day": [(d, c) for d, c in ordered],
            "last_events": list(reversed(self._events[-20:])),
        }
