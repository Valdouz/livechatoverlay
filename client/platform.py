"""Ce qui diffère d'un système à l'autre : clic-traversant, premier plan, démarrage auto.

Tout passe par ctypes, sans dépendance supplémentaire — un paquet de moins à installer
pour ceux qui lancent depuis les sources.
"""

from __future__ import annotations

import logging
import os
import shlex
import sys
from pathlib import Path

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MAC

APP_NAME = "LiveChat"
_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# -- constantes Win32 --------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

#: Renvoyé par SHQueryUserNotificationState quand une application occupe l'écran
#: en plein écran exclusif Direct3D. Dans ce cas DWM est court-circuité et aucune
#: fenêtre ne peut composer par-dessus, quels que soient ses attributs.
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4


def launch_command(tray: bool = False) -> list[str]:
    """Comment relancer l'application, exécutable compilé ou script.

    `tray` ajoute l'option de démarrage discret : lancé avec la session, LiveChat
    se range dans la zone de notification ; lancé à la main, il ouvre son panneau.
    """
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "client"]
    return (base + ["--tray"]) if tray else base


# -- clic-traversant et premier plan -----------------------------------------


def make_click_through(window) -> bool:
    """Rend la fenêtre invisible aux clics. `Qt.WindowTransparentForInput` fait le
    gros du travail ; sous Windows on ajoute NOACTIVATE pour ne jamais voler le
    focus à ce qui tourne devant.
    """
    if not IS_WINDOWS:
        # X11 et macOS sont couverts par le drapeau Qt posé à la construction.
        if IS_MAC:
            return _mac_ignore_mouse(window)
        return True

    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(window.winId())
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_long.restype = ctypes.c_ssize_t
        set_long.restype = ctypes.c_ssize_t

        style = get_long(hwnd, GWL_EXSTYLE)
        set_long(
            hwnd,
            GWL_EXSTYLE,
            style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        )
        return True
    except Exception as exc:
        log.warning("Clic-traversant indisponible : %s", exc)
        return False


def _mac_ignore_mouse(window) -> bool:
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        ns_window = objc.objc_msgSend(
            ctypes.c_void_p(int(window.winId())), objc.sel_registerName(b"window")
        )
        send = objc.objc_msgSend
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        send.restype = None
        send(ns_window, objc.sel_registerName(b"setIgnoresMouseEvents:"), True)
        return True
    except Exception as exc:
        log.warning("Clic-traversant indisponible : %s", exc)
        return False


def reassert_topmost(window) -> None:
    """Remet la fenêtre au premier plan sans l'activer.

    « Toujours au premier plan » n'est pas un état stable sous Windows : une autre
    fenêtre topmost qui s'active passe devant, et on n'y revient jamais tout seul.
    """
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.user32.SetWindowPos(
            int(window.winId()), HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except Exception:
        pass


def exclusive_fullscreen_active() -> bool:
    """Une application occupe-t-elle l'écran en plein écran exclusif ?

    Renvoie toujours `False` hors Windows : ni macOS ni Linux n'exposent
    l'information de façon fiable, et deviner mal serait pire que ne pas savoir.
    """
    if not IS_WINDOWS:
        return False
    try:
        import ctypes

        state = ctypes.c_int()
        result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        if result != 0:
            return False
        return state.value in (QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)
    except Exception:
        return False


# -- démarrage automatique ---------------------------------------------------


def autostart_enabled() -> bool:
    try:
        if IS_WINDOWS:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        return _autostart_file().exists()
    except Exception:
        return False


def set_autostart(enabled: bool) -> bool:
    try:
        if IS_WINDOWS:
            return _windows_autostart(enabled)
        if IS_MAC:
            return _mac_autostart(enabled)
        return _linux_autostart(enabled)
    except Exception as exc:
        log.warning("Démarrage automatique : %s", exc)
        return False


def _autostart_file() -> Path:
    if IS_MAC:
        return Path.home() / "Library" / "LaunchAgents" / "fr.livechat.overlay.plist"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / "livechat.desktop"


def _windows_autostart(enabled: bool) -> bool:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            command = subprocess_quote(launch_command(tray=True))
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    return True


def _mac_autostart(enabled: bool) -> bool:
    target = _autostart_file()
    if not enabled:
        target.unlink(missing_ok=True)
        return True
    arguments = "".join(f"    <string>{part}</string>\n" for part in launch_command(tray=True))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        "  <key>Label</key><string>fr.livechat.overlay</string>\n"
        f"  <key>ProgramArguments</key><array>\n{arguments}  </array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    return True


def _linux_autostart(enabled: bool) -> bool:
    target = _autostart_file()
    if not enabled:
        target.unlink(missing_ok=True)
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={subprocess_quote(launch_command(tray=True))}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=true\n",
        encoding="utf-8",
    )
    return True


def subprocess_quote(parts: list[str]) -> str:
    if IS_WINDOWS:
        return " ".join(f'"{part}"' if " " in part else part for part in parts)
    return shlex.join(parts)
