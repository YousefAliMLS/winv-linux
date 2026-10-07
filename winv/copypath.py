"""Copy as Path utility: formats file/folder paths and copies them to the clipboard."""
from __future__ import annotations

import os

# Must be set before GTK is initialized so headless clipboard write works on Wayland
os.environ.setdefault("GDK_BACKEND", "x11")

import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk


def copy_paths_to_clipboard(
    paths: list[str] | None = None,
    quoted: bool = False,
    notify: bool = True,
) -> bool:
    """Format file or directory paths and set them on the system clipboard."""
    resolved_paths: list[str] = []

    if paths:
        for p in paths:
            if p.strip():
                clean = p.strip()
                if clean.startswith("file://"):
                    clean = unquote(urlparse(clean).path)
                try:
                    resolved_paths.append(str(Path(clean).resolve()))
                except Exception:
                    resolved_paths.append(clean)
    else:
        # Check Nautilus script environment variables
        nautilus_selected = os.environ.get("NAUTILUS_SCRIPT_SELECTED_FILE_PATHS", "").strip()
        if nautilus_selected:
            for line in nautilus_selected.splitlines():
                if line.strip():
                    try:
                        resolved_paths.append(str(Path(line.strip()).resolve()))
                    except Exception:
                        resolved_paths.append(line.strip())
        else:
            current_uri = os.environ.get("NAUTILUS_SCRIPT_CURRENT_URI", "").strip()
            if current_uri:
                clean = unquote(urlparse(current_uri).path) if current_uri.startswith("file://") else current_uri
                try:
                    resolved_paths.append(str(Path(clean).resolve()))
                except Exception:
                    resolved_paths.append(clean)

    if not resolved_paths:
        return False

    if quoted:
        clipboard_text = "\n".join(f'"{p}"' for p in resolved_paths)
    else:
        clipboard_text = "\n".join(resolved_paths)

    from gi.repository import Gio

    # 1. Try D-Bus activation to the resident WinV UI (instant & persistent on native Wayland)
    dbus_ok = False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        param = GLib.Variant("s", clipboard_text)
        bus.call_sync(
            "io.github.winv.WinV",
            "/io/github/winv/WinV",
            "org.gtk.Actions",
            "Activate",
            GLib.Variant("(sava{sv})", ("copy-text", [param], {})),
            None,
            Gio.DBusCallFlags.NONE,
            500,
            None,
        )
        dbus_ok = True
    except Exception:
        pass

    # 2. Fallback to direct GTK clipboard
    if not dbus_ok:
        Gtk.init()
        display = Gdk.Display.get_default()
        if display:
            cb = display.get_clipboard()
            cb.set(clipboard_text)
            loop = GLib.MainLoop()
            GLib.timeout_add(300, loop.quit)
            loop.run()

    # 3. Ensure entry is in WinV history
    try:
        import hashlib
        from .storage import Store
        store = Store()
        digest = "t:" + hashlib.sha1(clipboard_text.encode("utf-8", "surrogatepass")).hexdigest()
        store.add("text", clipboard_text, digest)
    except Exception:
        pass

    if notify:
        count = len(resolved_paths)
        title = "Copied as Path" if count == 1 else f"Copied {count} Paths"
        body = resolved_paths[0] if count == 1 else f"{resolved_paths[0]} (+{count - 1} more)"
        try:
            subprocess.run(
                ["notify-send", "-a", "WinV", "-i", "edit-copy-symbolic", title, body],
                check=False,
                timeout=2,
            )
        except Exception:
            pass

    return True


def run(args: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="winv copy-path",
        description="Copy file or directory paths to the clipboard (Windows-style Copy as Path).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to copy (defaults to Nautilus selected files or current directory).",
    )
    parser.add_argument(
        "-q",
        "--quoted",
        action="store_true",
        help="Wrap each path in double quotes.",
    )
    parser.add_argument(
        "--no-notify",
        dest="notify",
        action="store_false",
        default=True,
        help="Do not display a desktop notification.",
    )
    opts = parser.parse_args(args)

    success = copy_paths_to_clipboard(
        paths=opts.paths,
        quoted=opts.quoted,
        notify=opts.notify,
    )
    if success:
        return 0
    print("No paths specified or detected from environment.", file=sys.stderr)
    return 1
