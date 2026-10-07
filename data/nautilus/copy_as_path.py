"""Nautilus Python extension: adds 'Copy as Path' to right-click context menu."""
from __future__ import annotations

import os
import subprocess
from urllib.parse import unquote, urlparse
from gi.repository import GObject, Nautilus


class CopyAsPathExtension(GObject.GObject, Nautilus.MenuProvider):
    """Nautilus extension providing Windows-style 'Copy as Path' context menu items."""

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def _get_path(file_info: Nautilus.FileInfo) -> str:
        """Extract absolute path from Nautilus FileInfo."""
        location = file_info.get_location()
        if location:
            p = location.get_path()
            if p:
                return p
        uri = file_info.get_uri()
        if uri.startswith("file://"):
            return unquote(urlparse(uri).path)
        return uri

    def _copy_paths(self, files: list[Nautilus.FileInfo], quoted: bool = False) -> None:
        """Invoke winv copy-path to copy paths and trigger notification."""
        paths = [self._get_path(f) for f in files if f]
        paths = [p for p in paths if p]
        if not paths:
            return

        cmd = ["winv", "copy-path"]
        if quoted:
            cmd.append("-q")
        cmd.extend(paths)

        try:
            subprocess.run(cmd, check=False, timeout=3)
        except Exception:
            # Fallback if winv CLI is not in PATH
            home = os.path.expanduser("~")
            bin_path = os.path.join(home, ".local", "bin", "winv")
            if os.path.exists(bin_path):
                cmd[0] = bin_path
                subprocess.run(cmd, check=False, timeout=3)

    def get_file_items(self, *args) -> list[Nautilus.MenuItem]:
        """Right-click menu on selected files/folders."""
        files = args[-1]
        if not files:
            return []

        item_normal = Nautilus.MenuItem(
            name="WinV::copy_as_path",
            label="Copy as Path",
            tip="Copy selected path(s) to clipboard",
            icon="edit-copy-symbolic",
        )
        item_normal.connect("activate", lambda *_: self._copy_paths(files, quoted=False))

        item_quoted = Nautilus.MenuItem(
            name="WinV::copy_as_path_quoted",
            label="Copy as Path (quoted)",
            tip="Copy path(s) wrapped in double quotes",
            icon="edit-copy-symbolic",
        )
        item_quoted.connect("activate", lambda *_: self._copy_paths(files, quoted=True))

        return [item_normal, item_quoted]

    def get_background_items(self, *args) -> list[Nautilus.MenuItem]:
        """Right-click menu on folder empty background."""
        folder = args[-1]
        if not folder:
            return []

        item_bg = Nautilus.MenuItem(
            name="WinV::copy_bg_path",
            label="Copy Folder Path",
            tip="Copy current folder path to clipboard",
            icon="edit-copy-symbolic",
        )
        item_bg.connect("activate", lambda *_: self._copy_paths([folder], quoted=False))

        item_bg_quoted = Nautilus.MenuItem(
            name="WinV::copy_bg_path_quoted",
            label="Copy Folder Path (quoted)",
            tip="Copy current folder path wrapped in double quotes",
            icon="edit-copy-symbolic",
        )
        item_bg_quoted.connect("activate", lambda *_: self._copy_paths([folder], quoted=True))

        return [item_bg, item_bg_quoted]
