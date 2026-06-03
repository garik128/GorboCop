"""Определение состояний Windows, при которых мониторинг нужно пропускать:
скринсейвер активен, монитор спит, рабочая станция заблокирована.

Состояние дисплея отслеживаем через RegisterPowerSettingNotification
(GUID_CONSOLE_DISPLAY_STATE) в скрытом message-only окне в отдельном потоке.
Если что-то из WinAPI недоступно — деградируем мягко (считаем дисплей включённым).
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

import win32con
import win32gui

# --- константы WinAPI -------------------------------------------------------
WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000

# GUID_CONSOLE_DISPLAY_STATE {6FE69556-704A-47A0-8F24-C28D936FDA47}
SPI_GETSCREENSAVERRUNNING = 0x0072

DISPLAY_OFF = 0
DISPLAY_ON = 1
DISPLAY_DIMMED = 2


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [
        ("PowerSetting", _GUID),
        ("DataLength", wintypes.DWORD),
        ("Data", ctypes.c_ubyte * 1),
    ]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def _guid_console_display_state() -> _GUID:
    g = _GUID()
    g.Data1 = 0x6FE69556
    g.Data2 = 0x704A
    g.Data3 = 0x47A0
    for i, b in enumerate((0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)):
        g.Data4[i] = b
    return g


class PowerMonitor:
    """Отслеживает состояние дисплея и скринсейвера.

    Метод should_skip() возвращает True, когда мониторинг позы нужно пропустить.
    """

    def __init__(self):
        self._display_on = True
        self._lock = threading.Lock()
        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._running = False

    # ---- публичный API ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="PowerMonitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    def should_skip(self) -> bool:
        """True, если дисплей выключен, идёт скринсейвер или сессия заблокирована."""
        with self._lock:
            if not self._display_on:
                return True
        if self._screensaver_running():
            return True
        if self._session_locked():
            return True
        return False

    @staticmethod
    def idle_seconds() -> float:
        """Сколько секунд не было ввода с клавиатуры/мыши (0 при ошибке WinAPI)."""
        try:
            info = _LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return 0.0
            tick = ctypes.windll.kernel32.GetTickCount()
            # GetTickCount — DWORD с переполнением раз в ~49 дней.
            return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0
        except Exception:
            return 0.0

    # ---- проверки через прямые вызовы --------------------------------------
    @staticmethod
    def _screensaver_running() -> bool:
        try:
            running = ctypes.c_int(0)
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETSCREENSAVERRUNNING, 0, ctypes.byref(running), 0
            )
            return bool(ok and running.value)
        except Exception:
            return False

    @staticmethod
    def _session_locked() -> bool:
        """Заблокированный ввод-десктоп нельзя открыть — признак блокировки."""
        try:
            user32 = ctypes.windll.user32
            DESKTOP_SWITCHDESKTOP = 0x0100
            hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
            if not hdesk:
                return True
            user32.CloseDesktop(hdesk)
            return False
        except Exception:
            return False

    # ---- поток с окном и сообщениями о питании ------------------------------
    def _run(self) -> None:
        try:
            self._create_window()
            win32gui.PumpMessages()
        except Exception:
            # Без оконного потока остаёмся на проверках screensaver/lock.
            pass

    def _create_window(self) -> None:
        hinst = win32gui.GetModuleHandle(None)
        class_name = "GorboCopPowerWnd"

        wc = win32gui.WNDCLASS()
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        wc.lpfnWndProc = self._wnd_proc
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        # message-only окно (родитель HWND_MESSAGE = -3)
        self._hwnd = win32gui.CreateWindowEx(
            0, class_name, "GorboCopPower", 0, 0, 0, 0, 0,
            -3, 0, hinst, None,
        )

        guid = _guid_console_display_state()
        ctypes.windll.user32.RegisterPowerSettingNotification(
            wintypes.HANDLE(self._hwnd),
            ctypes.byref(guid),
            DEVICE_NOTIFY_WINDOW_HANDLE,
        )

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_POWERBROADCAST and wparam == PBT_POWERSETTINGCHANGE:
            try:
                setting = ctypes.cast(
                    lparam, ctypes.POINTER(_POWERBROADCAST_SETTING)
                ).contents
                value = setting.Data[0]
                with self._lock:
                    self._display_on = value != DISPLAY_OFF
            except Exception:
                pass
            return True
        if msg == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
