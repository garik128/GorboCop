"""Иконка в системном трее (нативный Shell_NotifyIcon через win32).

Поведение:
- одиночный клик левой кнопкой — пауза/возобновление; иконка становится серой
  со значком паузы;
- двойной клик — развернуть окно приложения;
- правая кнопка — меню (показать окно, пауза/возобновление, выход).

Одиночный и двойной клик разделяются таймером на время двойного клика Windows.
"""
from __future__ import annotations

import ctypes
import os
import tempfile
import threading

import win32con
import win32gui
from PIL import Image, ImageDraw, ImageEnhance

from .config import RESOURCE_DIR

# Сообщение-callback от иконки трея и команды обновления.
_CALLBACK_MSG = win32con.WM_USER + 20
_MSG_SET_PAUSED = win32con.WM_USER + 21
_TIMER_SINGLE_CLICK = 1

# Идентификаторы пунктов меню.
_ID_SHOW = 1
_ID_PAUSE = 2
_ID_EXIT = 3


def _make_icon_files() -> tuple[str, str]:
    """Создать .ico для обычного и приостановленного состояний; вернуть пути."""
    tmp = tempfile.gettempdir()
    normal_path = os.path.join(tmp, "gorbocop_tray.ico")
    paused_path = os.path.join(tmp, "gorbocop_tray_paused.ico")

    src = os.path.join(RESOURCE_DIR, "icon.png")
    try:
        base = Image.open(src).convert("RGBA")
    except Exception:
        base = Image.new("RGBA", (64, 64), (40, 120, 200, 255))

    base = base.resize((64, 64))
    try:
        base.save(normal_path, format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])
    except Exception:
        normal_path = os.path.join(RESOURCE_DIR, "icon.ico")

    # Приостановленная версия: обесцветить, притушить, нарисовать значок паузы.
    gray = base.convert("L").convert("RGBA")
    gray.putalpha(base.getchannel("A"))
    gray = ImageEnhance.Brightness(gray).enhance(0.55)
    draw = ImageDraw.Draw(gray)
    bar_w, bar_h = 9, 30
    gap = 8
    cx, cy = 32, 32
    x0 = cx - gap // 2 - bar_w
    y0 = cy - bar_h // 2
    for bx in (x0, x0 + bar_w + gap):
        draw.rectangle([bx, y0, bx + bar_w, y0 + bar_h], fill=(255, 255, 255, 230))
    try:
        gray.save(paused_path, format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])
    except Exception:
        paused_path = normal_path

    return normal_path, paused_path


class TrayIcon:
    def __init__(self, on_toggle_pause, on_show, on_exit, is_paused):
        self._on_toggle_pause = on_toggle_pause
        self._on_show = on_show
        self._on_exit = on_exit
        self._is_paused = is_paused

        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._hicon_normal = None
        self._hicon_paused = None
        self._paused = False
        self._double_click_ms = ctypes.windll.user32.GetDoubleClickTime() or 500
        self._ignore_next_up = False

    # ---- публичный API ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="TrayIcon", daemon=True
        )
        self._thread.start()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if self._hwnd:
            try:
                win32gui.PostMessage(
                    self._hwnd, _MSG_SET_PAUSED, int(self._paused), 0
                )
            except Exception:
                pass

    # Совместимость со старыми вызовами.
    def refresh(self) -> None:
        self.set_paused(self._is_paused())

    def stop(self) -> None:
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    # ---- поток с окном и циклом сообщений -----------------------------------
    def _run(self) -> None:
        try:
            normal_path, paused_path = _make_icon_files()
            flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
            self._hicon_normal = win32gui.LoadImage(
                0, normal_path, win32con.IMAGE_ICON, 0, 0, flags
            )
            self._hicon_paused = win32gui.LoadImage(
                0, paused_path, win32con.IMAGE_ICON, 0, 0, flags
            )

            hinst = win32gui.GetModuleHandle(None)
            wc = win32gui.WNDCLASS()
            wc.hInstance = hinst
            wc.lpszClassName = "GorboCopTrayWnd"
            wc.lpfnWndProc = self._wnd_proc
            try:
                win32gui.RegisterClass(wc)
            except Exception:
                pass
            self._hwnd = win32gui.CreateWindow(
                "GorboCopTrayWnd", "GorboCopTray", 0,
                0, 0, 0, 0, 0, 0, hinst, None,
            )

            nid = (self._hwnd, 0,
                   win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                   _CALLBACK_MSG, self._hicon_normal, "GorboCop")
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

            win32gui.PumpMessages()
        except Exception:
            pass

    def _update_icon(self) -> None:
        hicon = self._hicon_paused if self._paused else self._hicon_normal
        tip = "GorboCop — пауза" if self._paused else "GorboCop"
        try:
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_MODIFY,
                (self._hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_TIP,
                 _CALLBACK_MSG, hicon, tip),
            )
        except Exception:
            pass

    def _show_menu(self) -> None:
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, _ID_SHOW, "Показать окно")
        pause_text = "Возобновить" if self._is_paused() else "Пауза"
        win32gui.AppendMenu(menu, win32con.MF_STRING, _ID_PAUSE, pause_text)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, _ID_EXIT, "Выход")

        win32gui.SetForegroundWindow(self._hwnd)
        x, y = win32gui.GetCursorPos()
        cmd = win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_RIGHTALIGN | win32con.TPM_BOTTOMALIGN
            | win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
            x, y, 0, self._hwnd, None,
        )
        win32gui.PostMessage(self._hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

        if cmd == _ID_SHOW:
            self._on_show()
        elif cmd == _ID_PAUSE:
            self._on_toggle_pause()
        elif cmd == _ID_EXIT:
            self._on_exit()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == _CALLBACK_MSG:
            if lparam == win32con.WM_LBUTTONUP:
                if self._ignore_next_up:
                    self._ignore_next_up = False
                else:
                    # Ждём, не будет ли двойного клика.
                    ctypes.windll.user32.SetTimer(
                        hwnd, _TIMER_SINGLE_CLICK, self._double_click_ms, 0
                    )
            elif lparam == win32con.WM_LBUTTONDBLCLK:
                ctypes.windll.user32.KillTimer(hwnd, _TIMER_SINGLE_CLICK)
                self._ignore_next_up = True
                self._on_show()
            elif lparam == win32con.WM_RBUTTONUP:
                self._show_menu()
            return 0

        if msg == win32con.WM_TIMER and wparam == _TIMER_SINGLE_CLICK:
            ctypes.windll.user32.KillTimer(hwnd, _TIMER_SINGLE_CLICK)
            self._on_toggle_pause()
            return 0

        if msg == _MSG_SET_PAUSED:
            self._paused = bool(wparam)
            self._update_icon()
            return 0

        if msg == win32con.WM_CLOSE:
            try:
                win32gui.Shell_NotifyIcon(
                    win32gui.NIM_DELETE, (hwnd, 0, 0, 0, 0, "")
                )
            except Exception:
                pass
            win32gui.DestroyWindow(hwnd)
            return 0

        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
