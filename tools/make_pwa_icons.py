"""
Render the PWA icon PNGs from the emoji of the site header.

The header says "📌 Pinterest Archive", and the icons are that same pin: the browser draws
the glyph the page shows, so the home screen, the task switcher and the tab match the header
on every platform. The PNGs are what `src/static/manifest.webmanifest` points at and what
`src/static/favicon.svg` draws; run this by hand after changing the emoji or a size, and
commit the output:

    python tools/make_pwa_icons.py

Only Pillow is used (it is already in `src/requirements-tools.txt`).

Layout follows the maskable icon rules (https://web.dev/articles/maskable-icon): the
`purpose: any` icons are transparent and tight, like the favicon; the maskable one is opaque
and keeps the pin inside the safe zone (a centred circle of radius 40% of the width), which is
what removes the white circle Android draws around a transparent PWA icon. The pin is scaled
so that its *silhouette* - not its bounding box - touches that circle: the glyph is a round
head with a needle, so the corners of the box are empty and fitting the box would make the pin
needlessly small. `apple-touch-icon-180.png` is opaque as well, because iOS paints the
transparent corners black.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "src" / "static" / "icons"

#: The emoji of the site header (`src/static/index.html`: <h1>📌 Pinterest Archive</h1>).
PIN = "📌"
#: The page background (`src/static/styles.css`, `body`) and the manifest's
#: `background_color`: the canvas of the opaque icons only.
BACKGROUND = "#f0f0f0"
#: The glyph is rasterised once, large, then scaled down (LANCZOS).
RENDER_SIZE = 1024
#: Pixels fainter than this are antialiasing, not the silhouette.
ALPHA_CUTOFF = 8
FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\seguiemj.ttf"),  # Segoe UI Emoji (scalable COLR glyphs)
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
)


@dataclass(frozen=True)
class Icon:
    """One output file: how much of the canvas the pin takes, and whether it is opaque."""

    name: str
    size: int
    height: float | None = None  # pin height / canvas (for transparent, box-fitted icons)
    safe_zone: float | None = None  # pin silhouette radius / canvas (maskable, mask-proof)
    opaque: bool = False


ICONS = (
    Icon("icon-192.png", 192, height=0.88),
    Icon("icon-512.png", 512, height=0.88),
    Icon("maskable-512.png", 512, safe_zone=0.38, opaque=True),  # the spec guarantees 0.40
    Icon("apple-touch-icon-180.png", 180, height=0.82, opaque=True),
)


def find_font(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    looked_at = ", ".join(map(str, FONT_CANDIDATES))
    raise SystemExit(f"no colour emoji font found, pass --font (looked at {looked_at})")


def render_pin(font_path: Path) -> Image.Image:
    """The emoji as a tight RGBA image: the glyph, cropped to its alpha."""
    font = ImageFont.truetype(str(font_path), RENDER_SIZE)
    canvas = Image.new("RGBA", (RENDER_SIZE * 2, RENDER_SIZE * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text(
        (canvas.width / 2, canvas.height / 2), PIN, font=font, embedded_color=True, anchor="mm"
    )
    box = canvas.getbbox()
    if box is None:
        raise SystemExit(f"{font_path} drew nothing for {PIN} (bitmap-only emoji font?)")
    return canvas.crop(box)


def silhouette_radius_ratio(glyph: Image.Image) -> float:
    """Max distance from the glyph's centre to an opaque pixel, in units of its height."""
    alpha = glyph.getchannel("A").load()
    cx, cy = glyph.width / 2, glyph.height / 2
    farthest = 0.0
    for y in range(glyph.height):
        for x in range(glyph.width):
            if alpha[x, y] > ALPHA_CUTOFF:
                distance = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
                farthest = max(farthest, distance)
    return farthest / glyph.height


def build_icon(glyph: Image.Image, radius_ratio: float, spec: Icon) -> Image.Image:
    if spec.height is not None:
        height = spec.height * spec.size
    else:
        height = spec.safe_zone * spec.size / radius_ratio
    width = round(glyph.width * height / glyph.height)
    pin = glyph.resize((width, round(height)), Image.LANCZOS)
    icon = Image.new("RGBA", (spec.size, spec.size), BACKGROUND if spec.opaque else (0, 0, 0, 0))
    icon.alpha_composite(pin, ((spec.size - width) // 2, (spec.size - pin.height) // 2))
    return icon.convert("RGB") if spec.opaque else icon


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, help="colour emoji font to draw the pin with")
    parser.add_argument("--out", type=Path, default=OUT_DIR,
                        help=f"where to write the icons (default: {OUT_DIR})")
    args = parser.parse_args()

    font_path = find_font(args.font)
    glyph = render_pin(font_path)
    radius_ratio = silhouette_radius_ratio(glyph)
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"font: {font_path} · pin {glyph.width}x{glyph.height} · "
          f"silhouette radius {radius_ratio:.3f} of height")
    for spec in ICONS:
        icon = build_icon(glyph, radius_ratio, spec)
        icon.save(args.out / spec.name)
        print(f"  {spec.name}: {icon.width}x{icon.height} {icon.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
