"""Tiny helpers shared by the mock tools: a PNG writer and a fake landscape.

Pure standard library so the demo runs anywhere Python runs.
"""
from __future__ import annotations

import math
import struct
import zlib

GRID_X, GRID_Y = 8, 5          # tiles across / down in the fake orthomosaic
CELLS = 16                     # low-res cells per tile (upscaled, blocky on purpose)

# Demo class colours (placeholder names, not the real classes)
CLASSES = [
    ("None", (0, 0, 0)),
    ("Class A", (230, 159, 0)),
    ("Class B", (86, 180, 233)),
    ("Class C", (0, 158, 115)),
    ("Class D", (240, 228, 66)),
    ("Class E", (204, 121, 167)),
    ("Other", (120, 120, 120)),
]


def write_png(path, width: int, height: int, rows: list[bytes]) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + r for r in rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def field(gx: float, gy: float) -> tuple[float, float]:
    """Two smooth pseudo-random fields in [0,1] at global cell coords."""
    a = (math.sin(gx * 0.11) + math.sin(gy * 0.13 + 1.7) + math.sin((gx + gy) * 0.07 + 0.4)) / 6 + 0.5
    b = (math.sin(gx * 0.31 + 2.1) * math.cos(gy * 0.27) + 1) / 2
    return a, b


def tile_cells(tx: int, ty: int):
    """Yield (row, [ (a,b) per cell ]) for one tile."""
    for cy in range(CELLS):
        yield [field(tx * CELLS + cx, ty * CELLS + cy) for cx in range(CELLS)]


def render(cell_rows, size: int, colour_fn) -> list[bytes]:
    scale = size // CELLS
    rows: list[bytes] = []
    for cells in cell_rows:
        line = b"".join(bytes(colour_fn(a, b)) * scale for a, b in cells)
        line = line.ljust(size * 3, b"\x00")
        rows.extend([line] * scale)
    while len(rows) < size:
        rows.append(rows[-1])
    return rows


def ortho_colour(a: float, b: float) -> tuple[int, int, int]:
    g = 90 + int(110 * a)
    return (int(60 + 70 * b * (1 - a)), g, int(40 + 50 * b))


def class_index(a: float, b: float, threshold: float) -> int:
    confidence = 0.75 + 0.25 * abs(math.sin(a * 9 + b * 5))
    if confidence < threshold:
        return 0
    return 1 + min(int(a * 5.999), 5) if b > 0.15 else 6


def class_colour_fn(threshold: float):
    return lambda a, b: CLASSES[class_index(a, b, threshold)][1]


def viewer_html(title: str, zoom: int, size: int) -> str:
    """Self-contained stand-in for gdal2tiles' openlayers.html (no internet needed)."""
    cells = "".join(
        f'<img src="{zoom}/{x}/{GRID_Y - 1 - y}.png" onerror="this.style.visibility=\'hidden\'">'
        for y in range(GRID_Y) for x in range(GRID_X)
    )
    legend = "".join(
        f'<span><i style="background:rgb{c}"></i>{n}</span>' for n, c in CLASSES
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{margin:0;font:14px system-ui;background:#1d2125;color:#eee}}
header{{padding:10px 16px;background:#111}} .g{{display:grid;grid-template-columns:repeat({GRID_X},1fr);
max-width:{GRID_X * 128}px;margin:16px auto}} .g img{{width:100%;display:block}}
.l{{text-align:center;padding:8px}} .l span{{margin:0 8px;white-space:nowrap}}
.l i{{display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:middle}}</style>
</head><body><header>DEMO viewer (stand-in for gdal2tiles openlayers.html) - {title}</header>
<div class="g">{cells}</div><div class="l">{legend}</div></body></html>"""
