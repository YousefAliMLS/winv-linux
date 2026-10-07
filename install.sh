#!/usr/bin/env bash
# WinV installer — clipboard history & emoji picker bound to Super+V.
#
#   ./install.sh                 full install (asks for sudo for packages + udev rule)
#   ./install.sh --no-deps       skip package installation
#   ./install.sh --no-uinput     skip the /dev/uinput rule (no auto-paste)
#   ./install.sh --no-keybinding don't touch desktop shortcuts
#
# Everything except system packages and the udev rule is installed per-user
# under ~/.local and ~/.config. Undo with ./uninstall.sh.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/lib/winv"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
UDEV_RULE="/etc/udev/rules.d/70-winv-uinput.rules"
APP_ID="io.github.winv.WinV"

DO_DEPS=1 DO_UINPUT=1 DO_KEYS=1
for arg in "$@"; do
    case "$arg" in
        --no-deps) DO_DEPS=0 ;;
        --no-uinput) DO_UINPUT=0 ;;
        --no-keybinding) DO_KEYS=0 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

c_blue=$'\e[1;34m' c_green=$'\e[1;32m' c_yellow=$'\e[1;33m' c_red=$'\e[1;31m' c_off=$'\e[0m'
step() { printf '%s==>%s %s\n' "$c_blue" "$c_off" "$*"; }
ok()   { printf '%s  ✔%s %s\n' "$c_green" "$c_off" "$*"; }
warn() { printf '%s  !%s %s\n' "$c_yellow" "$c_off" "$*"; }
die()  { printf '%s  ✘ %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }

[[ $EUID -eq 0 ]] && die "Run this as your normal user (it will call sudo when needed)."

SESSION="${XDG_SESSION_TYPE:-unknown}"
DESKTOP="${XDG_CURRENT_DESKTOP:-unknown}"
step "Detected session: $SESSION, desktop: $DESKTOP"

# --------------------------------------------------------------- dependencies
install_deps() {
    step "Checking and installing required system packages"
    if command -v apt-get >/dev/null; then
        local pkgs=(python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 python3-evdev libglib2.0-bin xwayland fonts-noto-color-emoji python3-nautilus)
        local missing=()
        for pkg in "${pkgs[@]}"; do
            dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
        done
        if [[ ${#missing[@]} -gt 0 ]]; then
            step "Installing missing packages: ${missing[*]}"
            # Do not let broken third-party repositories abort the installer
            sudo apt-get update || warn "Some apt repositories reported errors (ignoring broken third-party PPAs)..."
            sudo apt-get install -y --no-install-recommends "${missing[@]}" || sudo apt-get install -y "${missing[@]}" || {
                warn "Failed to install some packages via apt: ${missing[*]}"
            }
        else
            ok "All required packages are already installed"
        fi
    elif command -v dnf >/dev/null; then
        sudo dnf install -y python3 python3-gobject gtk4 libadwaita gdk-pixbuf2 \
            python3-evdev glib2 xorg-x11-server-Xwayland google-noto-color-emoji-fonts
    elif command -v pacman >/dev/null; then
        sudo pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita \
            gdk-pixbuf2 python-evdev glib2 xorg-xwayland noto-fonts-emoji
    elif command -v zypper >/dev/null; then
        sudo zypper install -y python3 python3-gobject python3-gobject-Gdk \
            typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 python3-evdev glib2-tools \
            xwayland google-noto-coloremoji-fonts
    else
        warn "Unsupported package manager. Install manually: Python ≥ 3.11, PyGObject,"
        warn "GTK 4, libadwaita, python-evdev, gdbus (glib2) and Xwayland."
    fi
}
[[ $DO_DEPS -eq 1 ]] && install_deps

step "Checking Python runtime"
python3 - <<'EOF' || die "Missing runtime dependencies (see above). Re-run without --no-deps."
import sys
if sys.version_info < (3, 11):
    sys.exit(f"Python >= 3.11 required, found {sys.version.split()[0]}")
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Adw, GdkPixbuf  # noqa
print(f"  Python {sys.version.split()[0]}, GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}, "
      f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}")
EOF
# No virtualenv is needed: WinV only depends on PyGObject/python-evdev, which
# must come from the distro so they match the system GTK and kernel headers.

# -------------------------------------------------------------------- files
step "Installing WinV to $LIB_DIR"
# Fix any root-owned folders in ~/.local or ~/.config created by past sudo/root installers (e.g. Cisco Packet Tracer)
sudo chown -R "$(id -u):$(id -g)" "$HOME/.local/share/icons" "$HOME/.local/share/applications" "$HOME/.local/lib" 2>/dev/null || true

mkdir -p "$BIN_DIR" "$LIB_DIR" "$APP_DIR" "$UNIT_DIR"
mkdir -p "$ICON_DIR" 2>/dev/null || true

rm -rf "${LIB_DIR:?}"/*
mkdir -p "$LIB_DIR/winv"
cp -r "$REPO_DIR/winv"/* "$LIB_DIR/winv/"
find "$LIB_DIR" -name '__pycache__' -prune -exec rm -rf {} +
sed "s|@WINV_HOME@|$LIB_DIR|" "$REPO_DIR/bin/winv" > "$BIN_DIR/winv"
chmod 755 "$BIN_DIR/winv"
sed "s|@BIN_DIR@|$BIN_DIR|g" "$REPO_DIR/data/$APP_ID.desktop" > "$APP_DIR/$APP_ID.desktop"

# Install icon to user directory and system directory
if [[ -d "$ICON_DIR" ]]; then
    cp "$REPO_DIR/data/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg" 2>/dev/null || true
fi
sudo mkdir -p /usr/share/icons/hicolor/scalable/apps 2>/dev/null || true
sudo cp "$REPO_DIR/data/$APP_ID.svg" /usr/share/icons/hicolor/scalable/apps/"$APP_ID.svg" 2>/dev/null || true

command -v update-desktop-database >/dev/null && update-desktop-database -q "$APP_DIR" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
ok "Launcher: $BIN_DIR/winv"
sudo ln -sf "$BIN_DIR/winv" /usr/local/bin/winv 2>/dev/null && ok "Symlinked to /usr/local/bin/winv" || true

# -------------------------------------------------------- nautilus integration
step "Installing Nautilus 'Copy as Path' extension & scripts"
NAUTILUS_EXT_DIR="$HOME/.local/share/nautilus-python/extensions"
NAUTILUS_SCRIPTS_DIR="$HOME/.local/share/nautilus/scripts"
mkdir -p "$NAUTILUS_EXT_DIR" "$NAUTILUS_SCRIPTS_DIR"
cp "$REPO_DIR/data/nautilus/copy_as_path.py" "$NAUTILUS_EXT_DIR/copy_as_path.py"
cp "$REPO_DIR/data/nautilus/scripts/"* "$NAUTILUS_SCRIPTS_DIR/"
chmod +x "$NAUTILUS_SCRIPTS_DIR/"*
ok "Nautilus integration installed"

# ------------------------------------------------------------ uinput (paste)
setup_uinput() {
    step "Enabling auto-paste (virtual keyboard via /dev/uinput)"
    sudo install -m 644 "$REPO_DIR/data/70-winv-uinput.rules" "$UDEV_RULE"
    echo uinput | sudo tee /etc/modules-load.d/winv-uinput.conf >/dev/null
    sudo modprobe uinput || warn "Could not load the uinput kernel module"
    sudo udevadm control --reload-rules
    sudo udevadm trigger --action=change --sysname-match=uinput || true
    sleep 0.5
    if [[ -w /dev/uinput ]]; then
        ok "/dev/uinput is writable — auto-paste ready"
    else
        warn "/dev/uinput not writable yet — log out and back in to activate auto-paste."
    fi
}
[[ $DO_UINPUT -eq 1 ]] && setup_uinput

# ----------------------------------------------------------------- autostart
step "Setting up autostart"
if systemctl --user show-environment >/dev/null 2>&1; then
    for unit in winv-watcher.service winv-ui.service; do
        sed "s|@BIN_DIR@|$BIN_DIR|g" "$REPO_DIR/data/$unit" > "$UNIT_DIR/$unit"
    done
    systemctl --user daemon-reload
    systemctl --user enable winv-watcher.service winv-ui.service >/dev/null 2>&1
    systemctl --user restart winv-watcher.service winv-ui.service
    ok "systemd user services enabled (winv-watcher, winv-ui)"
else
    mkdir -p "$AUTOSTART_DIR"
    for mode in watch "ui --hidden"; do
        name="winv-${mode%% *}"
        cat > "$AUTOSTART_DIR/$name.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=WinV ($mode)
Exec=$BIN_DIR/winv $mode
X-GNOME-Autostart-enabled=true
NoDisplay=true
EOF
    done
    nohup "$BIN_DIR/winv" watch >/dev/null 2>&1 &
    nohup "$BIN_DIR/winv" ui --hidden >/dev/null 2>&1 &
    ok "No systemd user session — installed XDG autostart entries instead"
fi

# --------------------------------------------------------------- keybinding
gnome_keybinding() {
    local schema="org.gnome.settings-daemon.plugins.media-keys"
    local base="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

    # GNOME binds Super+V to the notification list by default; free it.
    local tray new_tray
    tray="$(gsettings get org.gnome.shell.keybindings toggle-message-tray)"
    new_tray="$(python3 -c '
import ast, sys
raw = sys.argv[1].replace("@as ", "")
keys = [k for k in ast.literal_eval(raw) if k.lower() != "<super>v"]
print(str(keys))' "$tray")"
    if [[ "$tray" != "$new_tray" ]]; then
        gsettings set org.gnome.shell.keybindings toggle-message-tray "$new_tray"
        ok "Removed Super+V from GNOME's notification list (Super+M still opens it)"
    fi

    # Append our two custom shortcuts without clobbering existing ones.
    local list new_list
    list="$(gsettings get "$schema" custom-keybindings)"
    new_list="$(python3 -c '
import ast, sys
raw, base = sys.argv[1].replace("@as ", ""), sys.argv[2]
paths = ast.literal_eval(raw)
for name in ("winv", "winv-emoji"):
    p = f"{base}/{name}/"
    if p not in paths:
        paths.append(p)
print(str(paths))' "$list" "$base")"
    gsettings set "$schema" custom-keybindings "$new_list"

    local kb="$schema.custom-keybinding:$base/winv/"
    gsettings set "$kb" name "WinV clipboard history"
    gsettings set "$kb" command "$BIN_DIR/winv toggle"
    gsettings set "$kb" binding "<Super>v"
    kb="$schema.custom-keybinding:$base/winv-emoji/"
    gsettings set "$kb" name "WinV emoji picker"
    gsettings set "$kb" command "$BIN_DIR/winv emoji"
    gsettings set "$kb" binding "<Super>period"
    ok "GNOME shortcuts set: Super+V (clipboard), Super+. (emoji)"
}

print_manual_keybinding() {
    warn "Automatic shortcut setup isn't available for '$DESKTOP'. Add one of these:"
    cat <<EOF
    Hyprland  (~/.config/hypr/hyprland.conf):
        bind = SUPER, V, exec, $BIN_DIR/winv toggle
        bind = SUPER, period, exec, $BIN_DIR/winv emoji
        windowrulev2 = float, class:^($APP_ID)\$
    Sway / i3 (~/.config/sway/config or ~/.config/i3/config):
        bindsym Mod4+v exec $BIN_DIR/winv toggle
        bindsym Mod4+period exec $BIN_DIR/winv emoji
        for_window [app_id="$APP_ID"] floating enable   # i3: [class="$APP_ID"]
    KDE Plasma:
        System Settings → Keyboard → Shortcuts → Add New → Command or Script
        Command: $BIN_DIR/winv toggle    Shortcut: Meta+V
        (first remove Meta+V from "Klipper → Show Items at Mouse Position")
EOF
}

if [[ $DO_KEYS -eq 1 ]]; then
    step "Configuring the Super+V shortcut"
    if [[ "${DESKTOP^^}" == *GNOME* || "${DESKTOP^^}" == *UNITY* ]] && command -v gsettings >/dev/null; then
        gnome_keybinding
    else
        print_manual_keybinding
    fi
fi

echo
ok "WinV installed. Press ${c_green}Super+V${c_off} for clipboard history, ${c_green}Super+.${c_off} for emoji."
echo "    Health check:  $BIN_DIR/winv doctor"
echo "    Config file:   ~/.config/winv/config.toml"
