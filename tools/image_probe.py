"""How does Claude Code hand an image to the model? Ask it.

    python tools/image_probe.py [ad page image]

Cuts test images of several sizes from an ad page (or noise, when no page is given), has a
headless `claude -p` Read each one, and reports what reached the model: the image in the tool
result as Claude Code sent it (format and pixel size) and what it cost in input tokens. Compare
the tokens with a 28x28-pixel patch count to see whether the model got the image unscaled.
"""

import base64
import io
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SIZES = [(1000, 1000), (1400, 2000), (1874, 1960), (1960, 1960), (2000, 2000), (2600, 1300)]


def main():
    work = ROOT / "work" / "probe"
    work.mkdir(parents=True, exist_ok=True)
    page = Image.open(sys.argv[1]).convert("RGB") if len(sys.argv) > 1 else None
    print("sent         file     reached the model      tokens  patches(28px)")
    for w, h in SIZES:
        for fmt in ("png", "jpg") if (w, h) == (1400, 2000) else ("png",):
            path = work / f"probe-{w}x{h}.{fmt}"
            image(page, w, h).save(path, quality=90)
            got, tokens = probe(path, work)
            print(f"{w}x{h} {fmt:4} {path.stat().st_size / 2**20:5.1f} MB  {got:22} {tokens:6}  {patches(w, h):6}")


def image(page, w, h):
    if page is None:
        return Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    scale = w / page.width
    return page.resize((w, round(page.height * scale)), Image.Resampling.LANCZOS).crop((0, 0, w, h))


def patches(w, h):
    return math.ceil(w / 28) * math.ceil(h / 28)


def probe(path, work):
    """Read one image in a headless session; return (what the tool result held, image tokens)."""
    out = subprocess.run(
        ["claude", "-p", f"Read {path.name}, then reply with only the word OK.", "--model", "opus",
         "--tools", "Read", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
         "--output-format", "stream-json", "--verbose"],
        cwd=work, capture_output=True, text=True, timeout=600,
    ).stdout  # fmt: skip
    usage, got = {}, "no image in the tool result"
    for line in out.splitlines():
        event = json.loads(line)
        message = event.get("message") or {}
        if event["type"] == "assistant":
            u = message["usage"]
            usage[message["id"]] = u["input_tokens"] + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        for block in message.get("content", []) if isinstance(message.get("content"), list) else []:
            for part in block.get("content", []) if isinstance(block.get("content"), list) else []:
                if part.get("type") == "image":
                    data = base64.b64decode(part["source"]["data"])
                    sent = Image.open(io.BytesIO(data))
                    got = f"{part['source']['media_type'].split('/')[1]} {sent.width}x{sent.height}"
    first, *_, last = usage.values()  # before and after the image entered the conversation
    return got, last - first


if __name__ == "__main__":
    main()
