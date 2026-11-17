# SPDX-License-Identifier: AGPL-3.0-or-later
"""Program icon: the "G" mark of the app header (white serif G on the accent blue,
rounded square) as Windows .ico (16–256 px) and PNG favicon for the UI.

    uv run python packaging/make_icon.py [path/to/serif-bold.ttf]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ACCENT = (47, 95, 158, 255)   # --accent #2f5f9e
FONTS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
]
OUT = Path(__file__).parent / "icon"
WEB = Path(__file__).parents[1] / "web" / "public"


def mark(size: int, font_path: str) -> Image.Image:
    s = 1024  # draw large, scale down for clean edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.21), fill=ACCENT)
    font = ImageFont.truetype(font_path, int(s * 0.70))
    box = d.textbbox((0, 0), "G", font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((s - w) / 2 - box[0], (s - h) / 2 - box[1] - s * 0.01), "G", font=font,
           fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    font = next((f for f in ([*sys.argv[1:]] + FONTS) if Path(f).exists()), None)
    if not font:
        raise SystemExit("no serif bold font found — pass a .ttf path")
    OUT.mkdir(exist_ok=True)
    big = mark(256, font)
    big.save(OUT / "gutachter.ico",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                    (256, 256)])
    mark(512, font).save(OUT / "gutachter-512.png")
    WEB.mkdir(parents=True, exist_ok=True)
    mark(64, font).save(WEB / "favicon.png")
    print("icon written:", OUT / "gutachter.ico")


if __name__ == "__main__":
    main()
