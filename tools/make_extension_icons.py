"""
Render the extension PNG icons from the SVG master.

Chrome does not accept SVG icons, so the master art in `extension/icon.svg`
is rasterized into the PNG sizes referenced by `extension/manifest.json`.
Run this by hand after editing the SVG and commit the output:

    python tools/make_extension_icons.py

Only Pillow (already a project dependency) is used. The SVG is read with a
small reader that understands `viewBox`, `circle` and filled `path` elements
with the commands used by the master file (M L H V C S Q T Z, absolute and
relative). Strokes, gradients and arc commands are not supported.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"
SVG_PATH = EXTENSION_DIR / "icon.svg"
SIZES = (16, 32, 48, 128)

#: Render at this multiple of the target size, then downscale for smooth edges.
SUPERSAMPLE = 8
#: How closely the flattened curves follow the path, in final output pixels.
FLATNESS = 0.15
#: Recursion limit for curve flattening.
MAX_DEPTH = 18

ELEMENT_RE = re.compile(r"<(circle|path)\b([^>]*?)/?>")
ATTRIBUTE_RE = re.compile(r'([A-Za-z-]+)="([^"]*)"')
VIEWBOX_RE = re.compile(r'viewBox="([^"]+)"')
TOKEN_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
COLOR_NAMES = {
    "black": (0, 0, 0, 255),
    "white": (255, 255, 255, 255),
    "none": (0, 0, 0, 0),
}


def parse_color(value: str) -> tuple[int, int, int, int]:
    """Turn an SVG fill into an RGBA tuple."""
    value = value.strip().lower()
    if value in COLOR_NAMES:
        return COLOR_NAMES[value]

    match = re.fullmatch(r"#([0-9a-f]{6})", value)
    if match:
        number = int(match.group(1), 16)
        return (number >> 16 & 0xFF, number >> 8 & 0xFF, number & 0xFF, 255)

    raise ValueError(f"unsupported fill: {value!r}")


def parse_view_box(svg: str) -> tuple[float, float, float, float]:
    """Return the viewBox of the SVG as (x, y, width, height)."""
    match = VIEWBOX_RE.search(svg)
    if not match:
        raise ValueError("the SVG has no viewBox")
    values = [float(part) for part in re.split(r"[,\s]+", match.group(1).strip())]
    if len(values) != 4:
        raise ValueError(f"unexpected viewBox: {match.group(1)!r}")
    return values[0], values[1], values[2], values[3]


def _tokenize(data: str) -> list:
    """Split path data into command letters and numbers."""
    tokens = []
    for match in TOKEN_RE.finditer(data):
        tokens.append(match.group(1) if match.group(1) else float(match.group(2)))
    return tokens


def _midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Return the point halfway between two points."""
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _is_flat(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    tolerance: float,
) -> bool:
    """Check whether a cubic curve is close enough to the chord p0-p3."""
    dx = p3[0] - p0[0]
    dy = p3[1] - p0[1]
    length = math.hypot(dx, dy)

    if length == 0:
        return (
            math.hypot(p1[0] - p0[0], p1[1] - p0[1]) <= tolerance
            and math.hypot(p2[0] - p0[0], p2[1] - p0[1]) <= tolerance
        )

    first = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) / length
    second = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) / length
    return first <= tolerance and second <= tolerance


def _flatten_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    tolerance: float,
    out: list[tuple[float, float]],
    depth: int = 0,
) -> None:
    """Append the end point of a cubic curve, splitting it until it is flat."""
    if depth >= MAX_DEPTH or _is_flat(p0, p1, p2, p3, tolerance):
        out.append(p3)
        return

    p01 = _midpoint(p0, p1)
    p12 = _midpoint(p1, p2)
    p23 = _midpoint(p2, p3)
    p012 = _midpoint(p01, p12)
    p123 = _midpoint(p12, p23)
    center = _midpoint(p012, p123)

    _flatten_cubic(p0, p01, p012, center, tolerance, out, depth + 1)
    _flatten_cubic(center, p123, p23, p3, tolerance, out, depth + 1)


class _PathReader:
    """Walks SVG path data and collects flattened polygons."""

    def __init__(self, data: str, tolerance: float) -> None:
        self.tokens = _tokenize(data)
        self.tolerance = tolerance
        self.polygons: list[list[tuple[float, float]]] = []
        self.points: list[tuple[float, float]] = []
        self.x = 0.0
        self.y = 0.0
        self.start = (0.0, 0.0)
        self.control: tuple[float, float] | None = None
        self.command = ""
        self.previous = ""
        self.index = 0

    def read(self, count: int) -> list[float]:
        """Consume and return the next numbers of a command."""
        values = self.tokens[self.index:self.index + count]
        if len(values) < count:
            raise ValueError("truncated path data")
        self.index += count
        return values

    def move_to(self, x: float, y: float) -> None:
        """Start a new subpath."""
        if self.points:
            self.polygons.append(self.points)
        self.points = [(x, y)]
        self.start = (x, y)
        self.x, self.y = x, y
        self.control = None

    def line_to(self, x: float, y: float) -> None:
        """Append a straight segment."""
        self.points.append((x, y))
        self.x, self.y = x, y
        self.control = None

    def cubic_to(self, x1: float, y1: float, x2: float, y2: float, x: float, y: float) -> None:
        """Append a cubic curve from the current point."""
        _flatten_cubic(
            (self.x, self.y), (x1, y1), (x2, y2), (x, y), self.tolerance, self.points
        )
        self.x, self.y = x, y
        self.control = (x2, y2)

    def quadratic_to(self, x1: float, y1: float, x: float, y: float) -> None:
        """Append a quadratic curve, elevated to a cubic."""
        start = (self.x, self.y)
        first = (start[0] + 2 / 3 * (x1 - start[0]), start[1] + 2 / 3 * (y1 - start[1]))
        second = (x + 2 / 3 * (x1 - x), y + 2 / 3 * (y1 - y))
        self.cubic_to(first[0], first[1], second[0], second[1], x, y)

    def reflected_control(self) -> tuple[float, float]:
        """Return the control point a smooth curve continues from."""
        if self.previous in ("C", "S", "Q", "T") and self.control:
            return (2 * self.x - self.control[0], 2 * self.y - self.control[1])
        return (self.x, self.y)

    def close(self) -> None:
        """Close the current subpath."""
        if self.points:
            self.points.append(self.start)
            self.polygons.append(self.points)
            self.points = []
        self.x, self.y = self.start
        self.control = None


def flatten_path(data: str, tolerance: float) -> list[list[tuple[float, float]]]:
    """
    Flatten SVG path data into polygons.

    Args:
        data: The `d` attribute of a path element.
        tolerance: Allowed deviation from the curves, in user units.

    Returns:
        One list of points per subpath.
    """
    reader = _PathReader(data, tolerance)

    while reader.index < len(reader.tokens):
        token = reader.tokens[reader.index]
        if isinstance(token, str):
            reader.command = token
            reader.index += 1

        command = reader.command
        if not command:
            raise ValueError("path data must start with a command")

        relative = command.islower()
        code = command.upper()
        x, y = reader.x, reader.y

        if code == "M":
            px, py = reader.read(2)
            reader.move_to(px + x if relative else px, py + y if relative else py)
            reader.command = "l" if relative else "L"
        elif code == "L":
            px, py = reader.read(2)
            reader.line_to(px + x if relative else px, py + y if relative else py)
        elif code == "H":
            (px,) = reader.read(1)
            reader.line_to(px + x if relative else px, y)
        elif code == "V":
            (py,) = reader.read(1)
            reader.line_to(x, py + y if relative else py)
        elif code == "C":
            x1, y1, x2, y2, px, py = reader.read(6)
            if relative:
                x1, y1, x2, y2, px, py = x1 + x, y1 + y, x2 + x, y2 + y, px + x, py + y
            reader.cubic_to(x1, y1, x2, y2, px, py)
        elif code == "S":
            x2, y2, px, py = reader.read(4)
            if relative:
                x2, y2, px, py = x2 + x, y2 + y, px + x, py + y
            x1, y1 = reader.reflected_control()
            reader.cubic_to(x1, y1, x2, y2, px, py)
        elif code == "Q":
            x1, y1, px, py = reader.read(4)
            if relative:
                x1, y1, px, py = x1 + x, y1 + y, px + x, py + y
            reader.quadratic_to(x1, y1, px, py)
        elif code == "T":
            px, py = reader.read(2)
            if relative:
                px, py = px + x, py + y
            x1, y1 = reader.reflected_control()
            reader.quadratic_to(x1, y1, px, py)
        elif code == "Z":
            reader.close()
        else:
            raise ValueError(f"unsupported path command: {command!r}")

        reader.previous = code

    if reader.points:
        reader.polygons.append(reader.points)

    return reader.polygons


def render(svg: str, size: int) -> Image.Image:
    """
    Rasterize the SVG at the requested size.

    Args:
        svg: Contents of the SVG file.
        size: Width and height of the resulting square image, in pixels.

    Returns:
        The rendered RGBA image.
    """
    view_x, view_y, view_width, view_height = parse_view_box(svg)
    scale = size * SUPERSAMPLE / max(view_width, view_height)
    tolerance = FLATNESS * view_width / size

    canvas = Image.new("RGBA", (size * SUPERSAMPLE, size * SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    def to_pixels(px: float, py: float) -> tuple[float, float]:
        return ((px - view_x) * scale, (py - view_y) * scale)

    for element, attributes in ELEMENT_RE.findall(svg):
        attributes = dict(ATTRIBUTE_RE.findall(attributes))
        fill = parse_color(attributes.get("fill", "black"))

        if element == "circle":
            cx = float(attributes["cx"])
            cy = float(attributes["cy"])
            radius = float(attributes["r"])
            draw.ellipse(
                [*to_pixels(cx - radius, cy - radius), *to_pixels(cx + radius, cy + radius)],
                fill=fill,
            )
        else:
            for polygon in flatten_path(attributes["d"], tolerance):
                draw.polygon([to_pixels(px, py) for px, py in polygon], fill=fill)

    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Entry point."""
    svg = SVG_PATH.read_text(encoding="utf-8")

    for size in SIZES:
        target = EXTENSION_DIR / f"icon{size}.png"
        render(svg, size).save(target)
        print(f"wrote {target.relative_to(EXTENSION_DIR.parent)}")


if __name__ == "__main__":
    main()
