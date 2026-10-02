#!/usr/bin/env python3
"""DEMO ONLY. Mimics Pixel Muncher `inference.py` (Manual 8.4.3 / 8.7.6).

Creates results/<date_time>/segmentation_rgb/<x>/<y>.png plus log.log, one
tile at a time, so the GUI's progress tracking can be exercised.
With Pillow + numpy installed it reads each real tile and colours pixels by
greenness (Excess Green index). This is NOT a trained model: it only exists so
the whole workflow can be tested on a real orthomosaic without a GPU.
Without Pillow it draws a synthetic pattern instead.
Set MOCK_FAIL=1 to simulate a crash halfway through.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _synth as S  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("-p", required=True, help="model configuration json")
p.add_argument("-i", required=True, help="tiled dataset folder")
p.add_argument("-pp", required=True, help="post-processing configuration")
p.add_argument("-a", default=None, help="json overrides")
args, unknown = p.parse_known_args()

for label, path in (("model config", args.p), ("post-processing config", args.pp)):
    if not os.path.isfile(path):
        print(f"FileNotFoundError: {label} not found: {path}", file=sys.stderr)
        sys.exit(2)

threshold = 0.5
if args.a:
    threshold = float(json.loads(args.a).get("pytorchseg_confidence_threshold", threshold))

tiles = []
for root, _, files in os.walk(args.i):
    for f in files:
        if f.endswith(".png"):
            tiles.append(os.path.join(root, f))
tiles.sort()
if not tiles:
    print(f"No tiles found in {args.i}", file=sys.stderr)
    sys.exit(3)

def classify_real(src, dst, threshold):
    """Pseudo-classification of a real tile by greenness. Returns False if unavailable."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return False
    a = np.asarray(Image.open(src).convert("RGBA")).astype(np.float32)
    r, g, b, alpha = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    exg = (2 * g - r - b) / (r + g + b + 1e-6)          # Excess Green, vegetation > 0
    edges = np.array([0.04, 0.10, 0.16, 0.22, 0.30])
    cls = np.where(exg > edges[0], np.digitize(exg, edges), 6)   # 1..5 vegetation, 6 Other
    dist = np.min(np.abs(exg[..., None] - edges[None, None, :]), axis=-1)
    confidence = 0.5 + 0.5 * np.clip(dist / 0.03, 0, 1)
    cls = np.where(confidence < threshold, 0, cls)               # 0 = None (not confident)
    lut = np.array([c for _, c in S.CLASSES], dtype=np.uint8)
    out = np.zeros(a.shape, dtype=np.uint8)
    out[..., :3] = lut[cls]
    out[..., 3] = np.where((alpha > 0) & (cls > 0), 255, 0)      # nodata and None stay clear
    Image.fromarray(out, "RGBA").save(dst)
    return True


run = os.path.join("results", datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
out = os.path.join(run, "segmentation_rgb")
os.makedirs(out, exist_ok=True)
log = open(os.path.join(run, "log.log"), "w")
log.write(f"model={args.p}\nthreshold={threshold}\nextra={unknown}\n")
print(f"Loading model {os.path.basename(args.p)} (demo)", flush=True)
print(f"CUDA device: DEMO-GPU", flush=True)
time.sleep(0.5)

for n, tile in enumerate(tiles, 1):
    rel = os.path.relpath(tile, args.i)
    x = int(rel.split(os.sep)[0])
    y = int(os.path.splitext(os.path.basename(rel))[0])
    dest = os.path.join(out, str(x))
    os.makedirs(dest, exist_ok=True)
    if not classify_real(tile, os.path.join(dest, f"{y}.png"), threshold):
        size = 256
        rows = S.render(S.tile_cells(x, S.GRID_Y - 1 - y), size, S.class_colour_fn(threshold))
        S.write_png(os.path.join(dest, f"{y}.png"), size, size, rows)
    print(f"[inference] tile {n}/{len(tiles)} {rel}", flush=True)
    log.write(f"processed {rel}\n")
    if os.environ.get("MOCK_FAIL") and n == len(tiles) // 2:
        print("RuntimeError: CUDA out of memory (simulated)", file=sys.stderr, flush=True)
        sys.exit(1)
    time.sleep(0.12)

log.write("done\n")
log.close()
print(f"Results written to {run}", flush=True)
