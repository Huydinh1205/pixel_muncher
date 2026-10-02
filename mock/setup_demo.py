#!/usr/bin/env python3
"""Create demo_data/ and demo_pxm/ so the demo config has something to work on."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODELS = {
    "old_models/unet_demo_prototype": "unet",
    "unet_demo_best": "unet",
    "segformer_demo": "segformer",
}


def main() -> None:
    import sys
    if "--models-only" in sys.argv:
        (ROOT / "local_data").mkdir(exist_ok=True)
    for project in (() if "--models-only" in sys.argv else ("SiteA", "SiteB")):
        d = ROOT / "demo_data" / project
        d.mkdir(parents=True, exist_ok=True)
        tif = d / f"{project}_orthomosaic.tif"
        if not tif.exists():
            # Not a real GeoTIFF: the demo tiler only checks that the file exists.
            tif.write_bytes(b"II*\x00" + b"\x00" * (3 * 1024 * 1024))
    pxm = ROOT / "demo_pxm"
    work = pxm / "pixel_muncher"
    (work / "results").mkdir(parents=True, exist_ok=True)
    pp = work / "post_processing_configurations" / "SegmentationRGBOnly.json"
    pp.parent.mkdir(parents=True, exist_ok=True)
    pp.write_text(json.dumps({"outputs": ["segmentation_rgb"]}, indent=2))
    for rel, arch in MODELS.items():
        f = pxm / "models" / f"{rel}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"architecture": arch, "weights": f"{Path(rel).name}.pt"}, indent=2))
    print("Demo models ready in demo_pxm/")


if __name__ == "__main__":
    main()
