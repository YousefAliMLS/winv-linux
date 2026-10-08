# Project Contributors

This project was built and refined through human and AI collaborative engineering.

## Maintainer and Lead

* **Yousef Ali** ([@YousefAliMLS](https://github.com/YousefAliMLS))
  * Project founder, requirements architect, lead developer, and maintainer.

## AI Engineering Collaborators

* **Gemini Flash 3.8 High** ([@gemini-code-assist](https://github.com/gemini-code-assist)) (Google DeepMind)
  * System-level clipboard synchronization architecture (Wayland and X11 / Xwayland bridge).
  * Reliable background D-Bus IPC service (`io.github.winv.Watcher`).
  * Right-click Copy as Path implementation and Nautilus integration.
  * System clipboard memory clearing and daemon lifecycle management.
  * Automated Debian packaging (`.deb`) and release engineering.

* **Claude Opus 5.5 (Medium and High)** ([@claude](https://github.com/claude)) (Anthropic)
  * Initial application foundation and project scaffolding.
  * GTK 4 and Libadwaita user interface design and styling.
  * SQLite persistent storage engine and LRU caching mechanism.
  * Rootless virtual keyboard input simulation via `/dev/uinput` and `python-evdev`.
  * Unicode emoji database parsing and keyword indexing.
