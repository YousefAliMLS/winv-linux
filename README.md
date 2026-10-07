# WinV: Clipboard History and Emoji Palette for Linux

Windows-style Win+V clipboard manager for Linux with full text history, image previews, and integrated emoji picker.

![WinV Preview](assets/clipboard.png)

> **Demo Preview**: An animated walkthrough is available at [docs/demo.gif](docs/demo.gif). High-fidelity visual demonstrations help users preview hotkey interactions and clipboard workflows before installing.

---

## Overview

WinV delivers a lightweight, responsive alternative to the Windows clipboard history panel on Linux desktops. Built using native GTK 4 and Libadwaita, it supports both Wayland and X11 sessions with sub-30ms popup responsiveness via D-Bus activation.

---

## Features

* **Continuous Text and Image Capture**: Captures text clippings and image copies from browsers, terminals, code editors, and graphics tools.
* **Image Previews and Dimensions**: Displays scaled visual thumbnails alongside image dimensions in pixels.
* **Integrated Emoji Picker**: Instant searchable palette of over 1,900 Unicode emojis categorized with CLDR keywords and dynamic recent usage tracking.
* **Auto-Paste into Focused Windows**: Selecting an item or pressing Enter copies the content and simulates Ctrl+V into your previous active application.
* **Item Pinning and Cleanup**: Pin vital commands and code snippets with Ctrl+P to protect them when clearing history.
* **Privacy Conscious**: Automatically detects and ignores sensitive entries marked by password managers such as KeePassXC and Bitwarden.
* **Deduplication**: Re-copying previously saved items promotes them to the top without storing duplicates.
* **Right-Click Copy as Path**: Adds Windows-style Copy as Path to the Nautilus file manager context menu, supporting single and multiple selections, quoted paths, and desktop notifications.

---

## Compatibility Matrix

| Desktop Environment | Display Server | Status | Notes |
| :--- | :--- | :--- | :--- |
| GNOME Shell 45+ | Wayland | Supported | Integrated via Mutter Xwayland sync and systemd user services |
| GNOME Shell 45+ | X11 | Supported | Native XFixes clipboard notifications |
| KDE Plasma 5 / 6 | Wayland | Supported | Global shortcut configuration in System Settings |
| KDE Plasma 5 / 6 | X11 | Supported | Full support with auto-paste fallbacks |
| Hyprland | Wayland | Supported | Direct execution via hyprland keybindings |
| Sway / i3 | Wayland / X11 | Supported | Floating window rules applied via config file |

---

## Quick Installation

Run the automated installation script from the project root:

```bash
git clone https://github.com/YousefAliMLS/winv-linux.git
cd winv-linux
chmod +x install.sh
./install.sh
```

The installer performs dependency verification, deploys systemd user units, enables rootless virtual keyboard input permissions, and configures native desktop shortcuts.

---

## Keyboard Shortcuts

| Shortcut | Description |
| :--- | :--- |
| Super+V | Toggle clipboard history popup |
| Super+Period | Toggle emoji picker popup |
| Up / Down Arrows | Navigate through history entries or emoji list |
| Enter | Select item, copy to clipboard, and paste into active window |
| Shift+Enter | Copy item to clipboard without triggering auto-paste |
| Ctrl+P | Toggle pinned state for highlighted entry |
| Delete | Remove selected entry from history |
| Ctrl+Tab | Switch between Clipboard and Emoji views |
| Esc | Close popup window |

---

## Configuration

WinV reads its configuration from `~/.config/winv/config.toml`. Key options include:

* `max_items`: Maximum number of unpinned entries to retain (default: 100).
* `auto_paste`: Simulate paste keystrokes automatically on item selection (default: true).
* `paste_keys`: Key combination for auto-paste, such as "ctrl+v" or "ctrl+shift+v".
* `paste_delay_ms`: Focus delay in milliseconds before injecting keystrokes (default: 180).
* `hide_on_focus_loss`: Dismiss the popup when clicking outside (default: true).

To apply configuration changes, restart the background services:

```bash
systemctl --user restart winv-ui winv-watcher
```

---

## System Diagnostics

Verify runtime health, daemon processes, and keybindings at any time:

```bash
winv doctor
```

---

## Contributing

Community contributions, issue reports, and feature requests are welcome.

1. Fork the repository.
2. Create a dedicated feature branch.
3. Submit a pull request detailing your improvements or bug fixes.

---

## License

This software is released under the [MIT License](LICENSE).
