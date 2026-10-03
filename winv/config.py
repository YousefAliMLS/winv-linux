"""Paths and user configuration (``~/.config/winv/config.toml``)."""
from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "winv"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "winv"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DB_FILE = DATA_DIR / "history.db"
IMAGE_DIR = DATA_DIR / "images"
THUMB_DIR = DATA_DIR / "thumbs"
RECENT_EMOJI_FILE = DATA_DIR / "recent_emoji.json"
PACKAGE_DATA = Path(__file__).resolve().parent / "data"

DEFAULT_CONFIG = """\
# WinV configuration. Restart after editing:
#   systemctl --user restart winv-watcher winv-ui

# Maximum number of unpinned history entries to keep.
max_items = 100

# Largest text (in characters) that will be recorded.
max_text_chars = 500000

# Largest image (in megapixels) that will be recorded.
max_image_megapixels = 40

# Automatically paste into the focused window after picking an item.
auto_paste = true

# Key combo sent to paste: "ctrl+v", "ctrl+shift+v" (terminals) or "shift+insert".
paste_keys = "ctrl+v"

# Delay (ms) between hiding the popup and sending the paste keystroke, so the
# previously focused window has time to regain focus.
paste_delay_ms = 180

# Keystroke backend: "auto", "uinput", "ydotool", "xdotool", "wtype" or "none".
paste_backend = "auto"

# Hide the popup when it loses focus.
hide_on_focus_loss = true
"""


@dataclass
class Config:
    max_items: int = 100
    max_text_chars: int = 500_000
    max_image_megapixels: int = 40
    auto_paste: bool = True
    paste_keys: str = "ctrl+v"
    paste_delay_ms: int = 180
    paste_backend: str = "auto"
    hide_on_focus_loss: bool = True


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, IMAGE_DIR, THUMB_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """Load the config file, creating it with defaults on first run.

    Unknown keys and values of the wrong type are ignored with a warning so a
    typo never prevents the app from starting.
    """
    ensure_dirs()
    if not CONFIG_FILE.exists():
        try:
            CONFIG_FILE.write_text(DEFAULT_CONFIG, "utf-8")
        except OSError as exc:
            log.warning("Could not write default config: %s", exc)

    cfg = Config()
    try:
        raw = tomllib.loads(CONFIG_FILE.read_text("utf-8"))
    except FileNotFoundError:
        return cfg
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.error("Invalid config %s (%s); using defaults", CONFIG_FILE, exc)
        return cfg

    types = {f.name: type(getattr(cfg, f.name)) for f in fields(cfg)}
    for key, value in raw.items():
        expected = types.get(key)
        if expected is None:
            log.warning("Unknown config key %r ignored", key)
        elif not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            log.warning("Config key %r should be %s; ignored", key, expected.__name__)
        else:
            setattr(cfg, key, value)
    return cfg
