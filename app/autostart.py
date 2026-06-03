"""Автозапуск приложения вместе с Windows через ключ реестра HKCU\\...\\Run."""
from __future__ import annotations

import os
import sys

from .config import APP_DIR

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "GorboCop"


def _launch_command() -> str:
    """Команда запуска: сам EXE (frozen) либо pythonw + main.py (разработка)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    main_py = os.path.join(APP_DIR, "main.py")
    return f'"{pyw}" "{main_py}"'


def is_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _APP_NAME)
        return True
    except OSError:
        return False


def set_enabled(enable: bool) -> bool:
    """Включить/выключить автозапуск. Возвращает фактическое состояние."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                winreg.SetValueEx(
                    key, _APP_NAME, 0, winreg.REG_SZ, _launch_command()
                )
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                except OSError:
                    pass
        return enable
    except OSError:
        return is_enabled()
