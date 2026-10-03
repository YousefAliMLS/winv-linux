#!/usr/bin/env python3
"""Regenerate winv/data/emoji.json from official Unicode + CLDR sources.

Usage:  python3 tools/gen_emoji.py

Output format: a JSON list of [emoji, name, group, keywords] entries, in the
official Unicode ordering. Skin-tone variants and "component" entries are
skipped to keep the picker compact.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

EMOJI_TEST_URL = "https://unicode.org/Public/emoji/latest/emoji-test.txt"
CLDR_URL = (
    "https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/"
    "cldr-annotations-full/annotations/en/annotations.json"
)
OUT = Path(__file__).resolve().parent.parent / "winv" / "data" / "emoji.json"

SKIN_TONES = {chr(c) for c in range(0x1F3FB, 0x1F400)}
LINE_RE = re.compile(r"^([0-9A-F ]+);\s*fully-qualified\s*#\s*(\S+)\s+E[\d.]+\s+(.+)$")


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def main() -> int:
    print("Downloading", EMOJI_TEST_URL)
    test = fetch(EMOJI_TEST_URL)
    print("Downloading", CLDR_URL)
    cldr = json.loads(fetch(CLDR_URL))["annotations"]["annotations"]

    entries: list[list[str]] = []
    group = ""
    for line in test.splitlines():
        if line.startswith("# group:"):
            group = line.split(":", 1)[1].strip()
            continue
        if group == "Component":
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        char, name = m.group(2), m.group(3).strip()
        if any(ch in SKIN_TONES for ch in char):
            continue
        ann = cldr.get(char) or cldr.get(char.replace("\ufe0f", "")) or {}
        keywords = [k for k in ann.get("default", []) if k.lower() != name.lower()]
        entries.append([char, name, group, " ".join(keywords)])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(entries, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"Wrote {len(entries)} emoji to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
