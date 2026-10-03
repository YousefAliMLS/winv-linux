"""``winv doctor`` — print a quick health report of the installation."""
from __future__ import annotations

import os
import shutil
import subprocess

from . import config

OK, WARN, BAD = "\033[32m✔\033[0m", "\033[33m!\033[0m", "\033[31m✘\033[0m"


def _check(label: str, good: bool, hint: str = "", warn_only: bool = False) -> bool:
    mark = OK if good else (WARN if warn_only else BAD)
    print(f" {mark} {label}" + ("" if good or not hint else f"\n     → {hint}"))
    return good or warn_only


def _service_active(name: str) -> bool:
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", name]).returncode == 0
    except OSError:
        return False


def run() -> int:
    ok = True
    session = os.environ.get("XDG_SESSION_TYPE", "?")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "?")
    print(f"Session: {session}   Desktop: {desktop}\n")

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
        ok &= _check("GTK 4 + libadwaita", True)
    except Exception as exc:  # noqa: BLE001
        ok &= _check("GTK 4 + libadwaita", False, f"install PyGObject/GTK4/libadwaita ({exc})")

    ok &= _check("DISPLAY set (needed by the watcher via Xwayland)", bool(os.environ.get("DISPLAY")),
                 "Xwayland is required for clipboard monitoring on GNOME")

    try:
        import evdev  # noqa: F401
        has_evdev = True
    except ImportError:
        has_evdev = False
    ok &= _check("python-evdev installed", has_evdev, "sudo apt install python3-evdev", warn_only=True)
    ok &= _check("/dev/uinput writable (auto-paste)", os.access("/dev/uinput", os.W_OK),
                 "re-run install.sh, then log out/in (udev uaccess rule)", warn_only=True)
    for tool in ("ydotool", "xdotool", "wtype"):
        if shutil.which(tool):
            print(f" {OK} optional paste helper: {tool}")

    ok &= _check("winv-watcher.service running", _service_active("winv-watcher.service"),
                 "systemctl --user enable --now winv-watcher.service")
    ok &= _check("winv-ui.service running", _service_active("winv-ui.service"),
                 "systemctl --user enable --now winv-ui.service", warn_only=True)

    if "GNOME" in desktop.upper():
        try:
            out = subprocess.run(
                ["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"],
                capture_output=True, text=True).stdout
            ok &= _check("GNOME Super+V shortcut configured", "winv" in out, "re-run install.sh")
        except OSError:
            pass

    cfg = config.load_config()
    print(f"\nConfig: {config.CONFIG_FILE}\nData:   {config.DATA_DIR}")
    print(f"auto_paste={cfg.auto_paste} paste_backend={cfg.paste_backend} paste_keys={cfg.paste_keys}")
    return 0 if ok else 1
