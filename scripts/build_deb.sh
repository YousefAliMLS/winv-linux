#!/usr/bin/env bash
# Build script for Debian/Ubuntu package (.deb)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
VERSION="1.0.0"
PKG_NAME="winv"
BUILD_DIR="$REPO_DIR/build/deb"
DIST_DIR="$REPO_DIR/dist"
APP_ID="io.github.winv.WinV"

echo "==> Preparing build tree for ${PKG_NAME}_${VERSION}..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/lib/winv/winv"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$BUILD_DIR/usr/lib/systemd/user"
mkdir -p "$BUILD_DIR/usr/lib/udev/rules.d"
mkdir -p "$BUILD_DIR/usr/share/nautilus-python/extensions"
mkdir -p "$DIST_DIR"

# 1. Launcher binary
cat << 'EOF' > "$BUILD_DIR/usr/bin/winv"
#!/usr/bin/env bash
set -u
APP_ID="io.github.winv.WinV"
OBJECT_PATH="/io/github/winv/WinV"
WINV_HOME="/usr/lib/winv"

cmd="${1:-toggle}"
case "$cmd" in
    toggle) action="toggle" ;;
    emoji)  action="show-emoji" ;;
    *)      action="" ;;
esac

if [[ -n "$action" ]] && command -v gdbus >/dev/null 2>&1; then
    token="${XDG_ACTIVATION_TOKEN:-${DESKTOP_STARTUP_ID:-}}"
    platform="{}"
    if [[ -n "$token" ]]; then
        platform="{'activation-token': <'${token}'>, 'desktop-startup-id': <'${token}'>}"
    fi
    if gdbus call --session --timeout 2 --dest "$APP_ID" --object-path "$OBJECT_PATH" \
            --method org.gtk.Actions.Activate "$action" "[]" "$platform" >/dev/null 2>&1; then
        exit 0
    fi
fi

export PYTHONPATH="${WINV_HOME}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m winv "$@"
EOF
chmod 755 "$BUILD_DIR/usr/bin/winv"

# 2. Python package
cp -r "$REPO_DIR/winv"/* "$BUILD_DIR/usr/lib/winv/winv/"
find "$BUILD_DIR/usr/lib/winv" -name '__pycache__' -prune -exec rm -rf {} +

# 3. Desktop entry & icon
sed "s|@BIN_DIR@|/usr/bin|g" "$REPO_DIR/data/$APP_ID.desktop" > "$BUILD_DIR/usr/share/applications/$APP_ID.desktop"
cp "$REPO_DIR/data/$APP_ID.svg" "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"

# 4. Systemd user services
cat << 'EOF' > "$BUILD_DIR/usr/lib/systemd/user/winv-watcher.service"
[Unit]
Description=WinV clipboard history watcher
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/winv watch
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF

cat << 'EOF' > "$BUILD_DIR/usr/lib/systemd/user/winv-ui.service"
[Unit]
Description=WinV clipboard popup (preloaded so Super+V opens instantly)
PartOf=graphical-session.target
After=graphical-session.target winv-watcher.service

[Service]
Type=dbus
BusName=io.github.winv.WinV
ExecStart=/usr/bin/winv ui --hidden
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF

# 5. Udev uinput rule
cp "$REPO_DIR/data/70-winv-uinput.rules" "$BUILD_DIR/usr/lib/udev/rules.d/70-winv-uinput.rules"

# 6. Nautilus integration
cp "$REPO_DIR/data/nautilus/copy_as_path.py" "$BUILD_DIR/usr/share/nautilus-python/extensions/copy_as_path.py"

# 7. Package metadata (DEBIAN/control)
cat << EOF > "$BUILD_DIR/DEBIAN/control"
Package: $PKG_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: Yousef Ali <yousm99@gmail.com>
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-gdkpixbuf-2.0, python3-evdev, libglib2.0-bin, xwayland
Recommends: fonts-noto-color-emoji, python3-nautilus
Homepage: https://github.com/YousefAliMLS/winv-linux
Description: Windows-style Win+V clipboard manager and emoji picker for Linux
 WinV delivers a lightweight, responsive alternative to the Windows
 clipboard history panel on Linux desktops. Built with native GTK 4 and
 Libadwaita, it supports both Wayland and X11 sessions with full text
 history, image previews, and integrated emoji picker.
EOF

# 8. Post-installation script (DEBIAN/postinst)
cat << 'EOF' > "$BUILD_DIR/DEBIAN/postinst"
#!/bin/sh
set -e

if [ "$1" = "configure" ]; then
    # Reload udev rules so logged-in users get /dev/uinput access
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules || true
        udevadm trigger --action=change --sysname-match=uinput || true
    fi
    # Ensure uinput kernel module is loaded
    modprobe uinput 2>/dev/null || true
    echo uinput > /etc/modules-load.d/winv-uinput.conf 2>/dev/null || true

    # Update desktop and icon databases
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true
    fi
fi
exit 0
EOF
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# 9. Build .deb package
DEB_FILE="$DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$BUILD_DIR" "$DEB_FILE"

echo "==> Package successfully created: $DEB_FILE"
dpkg-deb --info "$DEB_FILE"
