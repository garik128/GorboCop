"""Контроль единственного экземпляра.

Первый экземпляр создаёт скрытое окно-приёмник с уникальным классом. Вторая
запущенная копия находит это окно, посылает ему зарегистрированное сообщение
«покажись» и завершается — вместо открытия второй копии.
"""
from __future__ import annotations

import ctypes
import threading

import win32con
import win32gui

_CLASS_NAME = "GorboCopSingleInstanceWnd"
_MSG_NAME = "GorboCop_ShowWindow_Message"


def _registered_msg() -> int:
    return ctypes.windll.user32.RegisterWindowMessageW(_MSG_NAME)


def find_existing() -> int:
    """HWND запущенного экземпляра или 0."""
    try:
        return win32gui.FindWindow(_CLASS_NAME, None)
    except Exception:
        return 0


def signal_existing(hwnd: int) -> None:
    """Попросить запущенный экземпляр показать окно."""
    try:
        ctypes.windll.user32.PostMessageW(hwnd, _registered_msg(), 0, 0)
    except Exception:
        pass


class SingleInstanceListener:
    """Скрытое окно-приёмник в отдельном потоке. По сообщению зовёт on_show."""

    def __init__(self, on_show):
        self._on_show = on_show
        self._msg = _registered_msg()
        self._hwnd = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="SingleInstance", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            hinst = win32gui.GetModuleHandle(None)
            wc = win32gui.WNDCLASS()
            wc.hInstance = hinst
            wc.lpszClassName = _CLASS_NAME
            wc.lpfnWndProc = self._wnd_proc
            try:
                win32gui.RegisterClass(wc)
            except Exception:
                pass
            # Обычное (не message-only) скрытое окно, чтобы его находил FindWindow.
            self._hwnd = win32gui.CreateWindow(
                _CLASS_NAME, "GorboCopSingleInstance", 0,
                0, 0, 0, 0, 0, 0, hinst, None,
            )
            win32gui.PumpMessages()
        except Exception:
            pass

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == self._msg:
            try:
                self._on_show()
            except Exception:
                pass
            return 0
        if msg == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
