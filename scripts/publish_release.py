import json
import os
import sys
import urllib.parse
import urllib.request

def main() -> int:
    cred_path = os.path.expanduser("~/.git-credentials")
    if not os.path.exists(cred_path):
        print("Error: ~/.git-credentials not found", file=sys.stderr)
        return 1

    with open(cred_path) as f:
        line = f.readline().strip()
    token = urllib.parse.urlparse(line).password
    if not token:
        print("Error: Token not found in ~/.git-credentials", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "WinV-Release-Builder",
        "Accept": "application/vnd.github.v3+json",
    }

    body = """### Overview

WinV delivers a fast, lightweight Linux alternative to the Windows Win+V clipboard history panel and emoji picker, built natively with GTK 4 and Libadwaita for Wayland and X11 desktop sessions.

### Features

* Continuous Text and Image History: Captures text clippings and graphics across browsers, terminals, code editors, and desktop applications.
* Image Previews: Renders image thumbnails alongside pixel dimensions.
* Integrated Emoji Palette: Instant searchable database of over 1,900 Unicode emojis with keyword search and recent usage tracking.
* Auto-Paste Keystroke Injection: Selecting an item simulates Ctrl+V into the previous focused application window.
* Windows-style Copy as Path: Right-click Nautilus file manager integration for copying resolved file and folder paths with single, multiple, and quoted modes.
* Privacy Aware: Automatically ignores entries flagged by password managers such as KeePassXC and Bitwarden.
* Complete Memory Flush: Clear all unpinned items while protecting pinned clippings and flushing live operating system clipboard buffers.

### Installation

Install the Debian / Ubuntu package attached below:

```bash
sudo apt install ./winv_1.0.0_all.deb
```

Or install from source:

```bash
git clone https://github.com/YousefAliMLS/winv-linux.git
cd winv-linux && ./install.sh
```
"""

    payload = {
        "tag_name": "v1.0.0",
        "name": "WinV v1.0.0: Windows-style Win+V Clipboard Manager for Linux",
        "body": body,
        "draft": False,
        "prerelease": False,
    }

    print("Creating release v1.0.0 on GitHub...")
    req = urllib.request.Request(
        "https://api.github.com/repos/YousefAliMLS/winv-linux/releases",
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            rel = json.loads(resp.read().decode())
            print(f"Release created successfully! URL: {rel['html_url']}")
            upload_url = rel["upload_url"].split("{")[0]

            deb_path = os.path.expanduser("~/Documents/WinV/dist/winv_1.0.0_all.deb")
            if os.path.exists(deb_path):
                print(f"Uploading release asset: {deb_path}...")
                with open(deb_path, "rb") as f:
                    deb_data = f.read()

                asset_req = urllib.request.Request(
                    f"{upload_url}?name=winv_1.0.0_all.deb",
                    data=deb_data,
                    headers={
                        "Authorization": f"token {token}",
                        "User-Agent": "WinV-Release-Builder",
                        "Content-Type": "application/vnd.debian.binary-package",
                        "Content-Length": str(len(deb_data)),
                    },
                )
                with urllib.request.urlopen(asset_req) as a_resp:
                    asset_data = json.loads(a_resp.read().decode())
                    print(f"Asset uploaded successfully! Download URL: {asset_data.get('browser_download_url')}")
            return 0
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode()}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
