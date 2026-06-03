"""Загрузка и сохранение параметров приложения в config.json."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field


def _data_dir() -> str:
    """Каталог для записываемых данных (config.json, history.json).

    Для собранного EXE — рядом с самим EXE, иначе — корень проекта.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_dir() -> str:
    """Каталог с упакованными ресурсами (иконки, звук по умолчанию).

    В one-file EXE PyInstaller распаковывает ресурсы во временную папку _MEIPASS.
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_DIR = _data_dir()           # записываемые данные
RESOURCE_DIR = _resource_dir()  # упакованные ресурсы только для чтения
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


@dataclass
class Config:
    """Все настраиваемые параметры мониторинга позы."""

    camera_index: int = 0

    # Калибровка
    calibration_seconds: float = 5.0

    # Сохранённый baseline последней калибровки (None — калибровки ещё не было).
    # Подхватывается при старте, чтобы не калиброваться заново после перезапуска.
    baseline_height: float | None = None
    baseline_y: float | None = None

    # Пороги срабатывания (относительно baseline)
    size_threshold: float = 1.12      # во сколько раз лицо должно увеличиться
    y_drop_threshold: float = 0.04    # насколько центр лица опустился (доля высоты кадра)

    # Тайминги
    alert_after_seconds: float = 2.5  # сколько держится плохая поза до тревоги
    cooldown_seconds: float = 30.0    # пауза между тревогами

    # Детектор
    min_detection_confidence: float = 0.65

    # Защита от ложных тревог
    idle_skip_minutes: float = 5.0     # нет ввода дольше N минут — пропуск мониторинга (0 = выкл)
    max_consecutive_alerts: int = 10   # лимит тревог подряд без возврата к норме (0 = без лимита)
    static_scene_minutes: float = 3.0  # рамка лица неподвижна дольше N минут — это не лицо (0 = выкл)

    # Звук
    sound_path: str = "alert.mp3"
    sound_enabled: bool = True
    sound_gain: float = 1.0   # множитель сэмпла (1.0 = как в файле, без усиления)
    toast_enabled: bool = True

    # Текст уведомления
    alert_title: str = "Поза!"
    alert_text: str = "Вы наклонились к клавиатуре. Выпрямитесь."

    # История и поведение
    history_retention_days: int = 30
    start_minimized: bool = False
    autostart: bool = False

    def resolved_sound_path(self) -> str:
        """Абсолютный путь к звуковому файлу.

        Пользовательский файл задаётся абсолютным путём; звук по умолчанию
        (alert.mp3) ищется среди упакованных ресурсов.
        """
        if os.path.isabs(self.sound_path):
            return self.sound_path
        return os.path.join(RESOURCE_DIR, self.sound_path)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, value)
            except (json.JSONDecodeError, OSError):
                # Битый конфиг — работаем на значениях по умолчанию.
                pass
        return cfg

    def save(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass
