"""Уведомления о плохой позе: звук + Windows-тост, с cooldown.

Звук предзагружается в память через pygame.mixer (нулевая латентность при
срабатывании) и усиливается на sound_gain поверх уровня файла.
"""
from __future__ import annotations

import os
import time

import numpy as np

from .config import RESOURCE_DIR


class Notifier:
    def __init__(self, config):
        self.config = config
        self._last_alert = 0.0
        self._toaster = None
        self._mixer_ok = False
        self._raw_samples = None  # исходные сэмплы (int16) для пересчёта gain
        self._sound = None        # текущий усиленный pygame.Sound
        self._init_toaster()
        self._init_sound()

    # ---- инициализация ------------------------------------------------------
    def _init_toaster(self) -> None:
        # Создаём независимо от toast_enabled: переключатель в настройках
        # может включить тосты в любой момент без перезапуска.
        try:
            from windows_toasts import WindowsToaster
            self._toaster = WindowsToaster("GorboCop")
        except Exception:
            self._toaster = None

    def _init_sound(self) -> None:
        path = self.config.resolved_sound_path()
        if not path or not os.path.exists(path):
            return
        try:
            import pygame
            pygame.mixer.init()
            base = pygame.mixer.Sound(path)
            self._raw_samples = pygame.sndarray.array(base)
            self._mixer_ok = True
            self._apply_gain(self.config.sound_gain)
        except Exception:
            self._mixer_ok = False

    def _apply_gain(self, gain: float) -> None:
        """Пересобрать звук с заданным усилением (с защитой от клиппинга)."""
        if not self._mixer_ok or self._raw_samples is None:
            return
        try:
            import pygame
            amplified = np.clip(
                self._raw_samples.astype(np.float32) * float(gain),
                -32768, 32767,
            ).astype(np.int16)
            self._sound = pygame.sndarray.make_sound(np.ascontiguousarray(amplified))
        except Exception:
            pass

    def set_gain(self, gain: float) -> None:
        self.config.sound_gain = float(gain)
        self._apply_gain(gain)

    def set_sound_path(self, path: str) -> bool:
        """Сменить звуковой файл и перезагрузить буфер. True при успехе."""
        self.config.sound_path = path
        self._raw_samples = None
        self._sound = None
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            base = pygame.mixer.Sound(self.config.resolved_sound_path())
            self._raw_samples = pygame.sndarray.array(base)
            self._mixer_ok = True
            self._apply_gain(self.config.sound_gain)
            return True
        except Exception:
            self._mixer_ok = self._sound is not None
            return False

    def play_test(self) -> None:
        """Проиграть текущий звук (кнопка проверки в настройках)."""
        self._play_sound()

    # ---- срабатывание -------------------------------------------------------
    def _in_cooldown(self) -> bool:
        return (time.time() - self._last_alert) < self.config.cooldown_seconds

    def alert(self) -> bool:
        """Сработать тревогой, если не в cooldown. Возвращает True, если сработала."""
        if self._in_cooldown():
            return False
        self._last_alert = time.time()
        if self.config.sound_enabled:
            self._play_sound()
        if self.config.toast_enabled:
            self._show_toast()
        return True

    def reset_cooldown(self) -> None:
        self._last_alert = 0.0

    # ---- звук ---------------------------------------------------------------
    def _play_sound(self) -> None:
        if self._mixer_ok and self._sound is not None:
            try:
                self._sound.play()
                return
            except Exception:
                pass
        # Фолбэк на системный звук.
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:
            pass

    # ---- тост ---------------------------------------------------------------
    def _show_toast(self) -> None:
        if self._toaster is None:
            self._init_toaster()
        if self._toaster is None:
            return
        try:
            from windows_toasts import Toast
            toast = Toast()
            toast.text_fields = [
                self.config.alert_title or "Поза!",
                self.config.alert_text or "Вы наклонились к клавиатуре.",
            ]
            # Логотип в теле уведомления.
            icon = os.path.join(RESOURCE_DIR, "icon.png")
            if os.path.exists(icon):
                try:
                    from windows_toasts import ToastDisplayImage, ToastImagePosition
                    toast.AddImage(ToastDisplayImage.fromPath(
                        icon, position=ToastImagePosition.AppLogo
                    ))
                except Exception:
                    pass
            self._toaster.show_toast(toast)
        except Exception:
            pass
