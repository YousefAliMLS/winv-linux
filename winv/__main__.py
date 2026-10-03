"""Command-line entry point: ``python3 -m winv <command>``."""
from __future__ import annotations

import argparse
import logging
import sys

from . import __version__


def main() -> int:
    parser = argparse.ArgumentParser(prog="winv", description="Clipboard history & emoji picker (Win+V for Linux)")
    parser.add_argument("--version", action="version", version=f"winv {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("watch", help="run the clipboard watcher daemon")
    ui = sub.add_parser("ui", help="run the popup application (resident)")
    ui.add_argument("--hidden", action="store_true", help="start without showing the window")
    sub.add_parser("toggle", help="show/hide the clipboard popup")
    sub.add_parser("emoji", help="show/hide the emoji picker")
    clear = sub.add_parser("clear", help="delete clipboard history")
    clear.add_argument("--all", action="store_true", help="also delete pinned items")
    sub.add_parser("doctor", help="diagnose the setup")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    cmd = args.command or "toggle"
    if cmd == "watch":
        from .watcher import main as watch_main
        return watch_main()
    if cmd in ("ui", "toggle", "emoji"):
        from .ui import main as ui_main
        flag = {"ui": "--hidden" if getattr(args, "hidden", False) else None,
                "toggle": "--toggle", "emoji": "--emoji"}[cmd]
        return ui_main([sys.argv[0]] + ([flag] if flag else []))
    if cmd == "clear":
        from .storage import Store
        Store().clear(keep_pinned=not args.all)
        print("History cleared.")
        return 0
    if cmd == "doctor":
        from .doctor import run
        return run()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
