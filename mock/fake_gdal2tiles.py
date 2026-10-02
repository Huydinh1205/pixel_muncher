#!/usr/bin/env python3
"""DEMO ONLY. Mimics `gdal2tiles.py` output so the GUI can be tried without GDAL.

Writes <output>/<zoom>/<x>/<y>.png, openlayers.html and tilemapresource.xml,
printing progress the same way gdal2tiles does ("0...10...20 ... - done.").
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _synth as S  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--tilesize", type=int, default=256)
p.add_argument("-z", "--zoom", default="23")
p.add_argument("-w", "--webviewer", default="all")
p.add_argument("-x", "--exclude", action="store_true")
p.add_argument("--processes", type=int, default=1)
p.add_argument("-a", "--srcnodata", default=None)
p.add_argument("-r", "--resampling", default="near")
p.add_argument("input")
p.add_argument("output")
args = p.parse_args()

if not os.path.isfile(args.input):
    print(f"ERROR 4: {args.input}: No such file or directory", file=sys.stderr)
    sys.exit(1)

zoom = int(str(args.zoom).split("-")[0])
size = min(args.tilesize, 256)
tiles = [(x, y) for x in range(S.GRID_X) for y in range(S.GRID_Y)]
print("Generating Base Tiles:", flush=True)
step = max(1, len(tiles) // 10)
for i, (x, y) in enumerate(tiles):
    d = os.path.join(args.output, str(zoom), str(x))
    os.makedirs(d, exist_ok=True)
    rows = S.render(S.tile_cells(x, S.GRID_Y - 1 - y), size, S.ortho_colour)
    S.write_png(os.path.join(d, f"{y}.png"), size, size, rows)
    if i % step == 0:
        print(f"{min(100, i * 100 // len(tiles))}...", end="", flush=True)
    time.sleep(0.08)
print("100 - done.", flush=True)

with open(os.path.join(args.output, "openlayers.html"), "w") as fh:
    fh.write(S.viewer_html(os.path.basename(args.input), zoom, size))
with open(os.path.join(args.output, "tilemapresource.xml"), "w") as fh:
    fh.write(f'<?xml version="1.0"?><TileMap><Title>{os.path.basename(args.input)}</Title></TileMap>\n')
