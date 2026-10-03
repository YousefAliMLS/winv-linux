"""Clipboard watcher daemon.

GNOME's compositor (Mutter) does not implement the wlr/ext data-control
Wayland protocols, so a Wayland client cannot observe the clipboard unless it
has keyboard focus. Mutter does, however, mirror the Wayland clipboard into
Xwayland's CLIPBOARD selection, and X11 clients get XFixes notifications for
every change. So this daemon deliberately runs GTK on the X11 backend: it sees
every copy made by native Wayland apps and XWayland apps alike, without
needing focus and without a visible window.

The same code works on X11 sessions and on KDE Plasma (Wayland or X11).
"""
from __future__ import annotations

import os

# Must be set before GTK is imported.
os.environ["GDK_BACKEND"] = "x11"

import hashlib
import logging
import signal
import sys

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk  # noqa: E402

from . import config  # noqa: E402
from .storage import Store  # noqa: E402

log = logging.getLogger("winv.watcher")

DEBOUNCE_MS = 120
THUMB_SIZE = 320
TEXT_MIMES = ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING", "TEXT")
# Password managers (KeePassXC, Bitwarden, ...) flag secrets with these targets.
SECRET_MIMES = ("x-kde-passwordManagerHint", "application/x-nspasteboard-concealed-type")
# Set by the WinV emoji picker so inserted emoji don't pollute the history.
TRANSIENT_MIME = "application/x-winv-transient"


class Watcher:
    def __init__(self) -> None:
        self.cfg = config.load_config()
        self.store = Store()
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError(
                "Cannot open an X11/Xwayland display. Is DISPLAY set? "
                "(On GNOME Wayland, Xwayland must be available.)"
            )
        self.clipboard = display.get_clipboard()
        self.clipboard.connect("changed", self._on_changed)
        self._pending: int = 0
        log.info("Watching clipboard on display %s", display.get_name())
        # Record whatever is already on the clipboard at startup.
        self._schedule()

    # -- change detection -----------------------------------------------------
    def _on_changed(self, _clipboard: Gdk.Clipboard) -> None:
        self._schedule()

    def _schedule(self) -> None:
        # Some apps set the clipboard several times in a row; coalesce.
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(DEBOUNCE_MS, self._capture)

    def _capture(self) -> bool:
        self._pending = 0
        formats = self.clipboard.get_formats()
        mimes = set(formats.get_mime_types() or [])
        log.debug("Clipboard formats: %s", sorted(mimes))

        if not mimes and not formats.get_gtypes():
            return GLib.SOURCE_REMOVE  # clipboard was cleared
        if mimes.intersection(SECRET_MIMES):
            log.info("Skipping clipboard content flagged as a password")
            return GLib.SOURCE_REMOVE
        if TRANSIENT_MIME in mimes:
            return GLib.SOURCE_REMOVE

        has_text = bool(mimes.intersection(TEXT_MIMES)) or formats.contain_gtype(GObject.TYPE_STRING)
        has_image = any(m.startswith("image/") for m in mimes)

        # Prefer text: office suites put a rendered PNG next to copied text.
        if has_text:
            self.clipboard.read_text_async(None, self._on_text)
        elif has_image:
            self.clipboard.read_texture_async(None, self._on_texture)
        return GLib.SOURCE_REMOVE

    # -- text -----------------------------------------------------------------
    def _on_text(self, clipboard: Gdk.Clipboard, result) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error as exc:
            log.warning("Could not read text from clipboard: %s", exc.message)
            return
        if not text or not text.strip():
            return
        if len(text) > self.cfg.max_text_chars:
            log.info("Skipping %d-character text (limit %d)", len(text), self.cfg.max_text_chars)
            return
        digest = "t:" + hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()
        self._commit("text", text, digest)

    # -- images ---------------------------------------------------------------
    def _on_texture(self, clipboard: Gdk.Clipboard, result) -> None:
        try:
            texture = clipboard.read_texture_finish(result)
        except GLib.Error as exc:
            log.warning("Could not read image from clipboard: %s", exc.message)
            return
        if texture is None:
            return
        w, h = texture.get_width(), texture.get_height()
        if w * h > self.cfg.max_image_megapixels * 1_000_000:
            log.info("Skipping %dx%d image (limit %d MP)", w, h, self.cfg.max_image_megapixels)
            return

        # Hash decoded pixels (not encoded bytes) so re-copying a stored image
        # bumps the existing entry instead of creating a duplicate.
        try:
            downloader = Gdk.TextureDownloader.new(texture)
            downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
            pixels, _stride = downloader.download_bytes()
            digest = "i:" + hashlib.sha1(f"{w}x{h}".encode() + pixels.get_data()).hexdigest()
        except Exception as exc:  # noqa: BLE001 - fall back to encoded bytes
            log.debug("TextureDownloader failed (%s); hashing PNG bytes", exc)
            digest = "i:" + hashlib.sha1(texture.save_to_png_bytes().get_data()).hexdigest()

        if self.store.has_hash(digest):
            self._commit("image", "", digest, w, h)  # just bump it
            return

        name = digest[2:] + ".png"
        image_path = config.IMAGE_DIR / name
        thumb_path = config.THUMB_DIR / name
        try:
            config.ensure_dirs()
            if not texture.save_to_png(str(image_path)):
                raise OSError("save_to_png returned FALSE")
            thumb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(image_path), THUMB_SIZE, THUMB_SIZE, True)
            thumb.savev(str(thumb_path), "png", [], [])
        except (OSError, GLib.Error) as exc:
            log.error("Failed to store image: %s", exc)
            image_path.unlink(missing_ok=True)
            return
        self._commit("image", name, digest, w, h)

    # -- persistence ----------------------------------------------------------
    def _commit(self, kind: str, content: str, digest: str, w: int = 0, h: int = 0) -> None:
        try:
            if self.store.add(kind, content, digest, w, h):
                log.info("Recorded %s entry", kind)
            self.store.prune(self.cfg.max_items)
        except Exception:  # noqa: BLE001 - never let one bad entry kill the daemon
            log.exception("Failed to save clipboard entry")


def main() -> int:
    if not Gtk.init_check():
        log.error("GTK could not initialise the X11 backend (DISPLAY=%s)", os.environ.get("DISPLAY"))
        return 1
    try:
        Watcher()
    except Exception as exc:  # noqa: BLE001
        log.error("%s", exc)
        return 1

    loop = GLib.MainLoop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, loop.quit)
    loop.run()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
