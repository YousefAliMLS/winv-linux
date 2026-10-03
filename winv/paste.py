"""Keystroke injection used to auto-paste into the previously focused window.

Wayland deliberately does not let one client send input to another. The
reliable, compositor-agnostic way around that is a virtual keyboard created
through the kernel's ``/dev/uinput`` (the same approach ydotool uses). The
installer adds a udev rule that grants the logged-in seat user access to
``/dev/uinput`` via systemd-logind's ``uaccess`` ACL — no root daemon and no
``input`` group membership required.

Backends, tried in order when ``paste_backend = "auto"``:
  uinput   python-evdev virtual keyboard (any session type)
  ydotool  needs a running ydotoold
  xdotool  X11 sessions only
  wtype    wlroots compositors (Sway, Hyprland, ...)
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

# Linux input event codes (linux/input-event-codes.h)
KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V, KEY_INSERT = 29, 42, 47, 110

COMBOS: dict[str, list[int]] = {
    "ctrl+v": [KEY_LEFTCTRL, KEY_V],
    "ctrl+shift+v": [KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V],
    "shift+insert": [KEY_LEFTSHIFT, KEY_INSERT],
}
XDO_NAMES = {"ctrl+v": "ctrl+v", "ctrl+shift+v": "ctrl+shift+v", "shift+insert": "shift+Insert"}


class PasteError(RuntimeError):
    pass


class Backend:
    name = "base"

    def send(self, codes: list[int], combo: str) -> None:
        raise NotImplementedError


class UinputBackend(Backend):
    """Persistent virtual keyboard. Created once at startup because the
    compositor needs a moment to pick up a new input device; creating one per
    paste would drop the first keystrokes."""

    name = "uinput"

    def __init__(self) -> None:
        try:
            from evdev import UInput, ecodes
        except ImportError as exc:
            raise PasteError("python-evdev is not installed") from exc
        if not os.access("/dev/uinput", os.W_OK):
            raise PasteError(
                "no write access to /dev/uinput (run install.sh, then log out and back in)"
            )
        self._ecodes = ecodes
        keys = sorted({c for combo in COMBOS.values() for c in combo})
        self._dev = UInput({ecodes.EV_KEY: keys}, name="WinV virtual keyboard")

    def send(self, codes: list[int], combo: str) -> None:
        ev_key = self._ecodes.EV_KEY
        for code in codes:
            self._dev.write(ev_key, code, 1)
            self._dev.syn()
            time.sleep(0.008)
        for code in reversed(codes):
            self._dev.write(ev_key, code, 0)
            self._dev.syn()
            time.sleep(0.008)


class YdotoolBackend(Backend):
    name = "ydotool"

    def __init__(self) -> None:
        if not shutil.which("ydotool"):
            raise PasteError("ydotool not found")

    def send(self, codes: list[int], combo: str) -> None:
        args = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
        _run(["ydotool", "key", *args])


class XdotoolBackend(Backend):
    name = "xdotool"

    def __init__(self) -> None:
        if os.environ.get("XDG_SESSION_TYPE") != "x11":
            raise PasteError("xdotool only works in X11 sessions")
        if not shutil.which("xdotool"):
            raise PasteError("xdotool not found")

    def send(self, codes: list[int], combo: str) -> None:
        _run(["xdotool", "key", "--clearmodifiers", XDO_NAMES[combo]])


class WtypeBackend(Backend):
    name = "wtype"

    def __init__(self) -> None:
        if not shutil.which("wtype"):
            raise PasteError("wtype not found")

    def send(self, codes: list[int], combo: str) -> None:
        mods = {"ctrl+v": ["ctrl"], "ctrl+shift+v": ["ctrl", "shift"], "shift+insert": ["shift"]}[combo]
        key = "Insert" if combo == "shift+insert" else "v"
        args: list[str] = []
        for m in mods:
            args += ["-M", m]
        args += ["-k", key]
        for m in reversed(mods):
            args += ["-m", m]
        _run(["wtype", *args])


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, timeout=3, capture_output=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PasteError(f"{cmd[0]} failed: {exc}") from exc


BACKENDS: dict[str, type[Backend]] = {
    "uinput": UinputBackend,
    "ydotool": YdotoolBackend,
    "xdotool": XdotoolBackend,
    "wtype": WtypeBackend,
}


class Paster:
    def __init__(self, backend: str = "auto", combo: str = "ctrl+v") -> None:
        if combo not in COMBOS:
            log.warning("Unknown paste_keys %r; using ctrl+v", combo)
            combo = "ctrl+v"
        self.combo = combo
        self.backend: Backend | None = None
        self.error: str | None = None

        if backend == "none":
            self.error = "auto-paste disabled (paste_backend = \"none\")"
            return
        names = list(BACKENDS) if backend == "auto" else [backend]
        errors = []
        for name in names:
            cls = BACKENDS.get(name)
            if cls is None:
                errors.append(f"{name}: unknown backend")
                continue
            try:
                self.backend = cls()
                log.info("Paste backend: %s", name)
                return
            except PasteError as exc:
                errors.append(f"{name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
        self.error = "; ".join(errors)
        log.warning("No paste backend available: %s", self.error)

    @property
    def available(self) -> bool:
        return self.backend is not None

    def paste(self) -> bool:
        if not self.backend:
            return False
        try:
            self.backend.send(COMBOS[self.combo], self.combo)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("Paste via %s failed: %s", self.backend.name, exc)
            return False
