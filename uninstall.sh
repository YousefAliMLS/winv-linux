#!/usr/bin/env bash
# Remove WinV.  ./uninstall.sh [--purge]   (--purge also deletes history & config)
set -uo pipefail

BIN_DIR="$HOME/.local/bin"
APP_ID="io.github.winv.WinV"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

echo "==> Stopping services"
systemctl --user disable --now winv-watcher.service winv-ui.service 2>/dev/null
rm -f "$UNIT_DIR/winv-watcher.service" "$UNIT_DIR/winv-ui.service"
systemctl --user daemon-reload 2>/dev/null
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/winv-watch.desktop" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/winv-ui.desktop"
pkill -f "python3 -m winv" 2>/dev/null

echo "==> Removing files"
rm -rf "$HOME/.local/lib/winv"
rm -f "$BIN_DIR/winv" "$HOME/.local/share/applications/$APP_ID.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/$APP_ID.svg"

if command -v gsettings >/dev/null && gsettings list-schemas | grep -q org.gnome.settings-daemon.plugins.media-keys; then
    echo "==> Removing GNOME shortcuts"
    schema="org.gnome.settings-daemon.plugins.media-keys"
    base="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    list="$(gsettings get "$schema" custom-keybindings)"
    new_list="$(python3 -c '
import ast, sys
paths = ast.literal_eval(sys.argv[1].replace("@as ", ""))
print(str([p for p in paths if not p.rstrip("/").endswith(("/winv", "/winv-emoji"))]))' "$list")"
    gsettings set "$schema" custom-keybindings "$new_list"
    for name in winv winv-emoji; do
        gsettings reset-recursively "$schema.custom-keybinding:$base/$name/" 2>/dev/null
    done
    gsettings reset org.gnome.shell.keybindings toggle-message-tray 2>/dev/null
    echo "    Super+V restored to GNOME's notification list"
fi

if [[ -f /etc/udev/rules.d/70-winv-uinput.rules ]]; then
    echo "==> Removing udev rule (sudo)"
    sudo rm -f /etc/udev/rules.d/70-winv-uinput.rules /etc/modules-load.d/winv-uinput.conf
    sudo udevadm control --reload-rules
fi

if [[ $PURGE -eq 1 ]]; then
    echo "==> Deleting history and config"
    rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/winv" "${XDG_CONFIG_HOME:-$HOME/.config}/winv"
fi
echo "WinV removed."
