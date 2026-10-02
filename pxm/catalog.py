"""Discover input orthomosaics, existing tiles and available models."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config

SKIP_SUFFIXES = ("_Result",)


@dataclass
class TileInfo:
    path: Path
    count: int
    modified: datetime | None


@dataclass
class InputInfo:
    path: Path
    project: str
    size_bytes: int

    @property
    def project_dir(self) -> Path:
        return self.path.parent

    @property
    def label(self) -> str:
        return f"{self.project} / {self.path.name}  ({human_size(self.size_bytes)})"


@dataclass
class ModelInfo:
    name: str
    path: Path
    architecture: str
    note: str
    recommended: bool

    @property
    def label(self) -> str:
        star = "  (recommended)" if self.recommended else ""
        return f"{self.name}{star}"


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def find_inputs(cfg: Config) -> list[InputInfo]:
    """All .tif/.tiff files under data root, skipping result and tile folders."""
    root = cfg.data_root
    found: list[InputInfo] = []
    if not root.is_dir():
        return found
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        depth = len(here.parts) - root_depth
        # do not descend into results, tile pyramids (folders named by digits) or hidden dirs
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and not d.endswith(SKIP_SUFFIXES) and not d.isdigit()
        )
        if depth >= cfg.scan_depth:
            dirnames[:] = []
        for f in sorted(filenames):
            if f.lower().endswith((".tif", ".tiff")):
                p = here / f
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                project = here.name if here != root else p.stem
                found.append(InputInfo(path=p, project=project, size_bytes=size))
    return found


def tiles_dir_for(cfg: Config, inp: InputInfo) -> Path:
    """Manual 8.4.2: gdal2tiles writes <project>/<zoom>/ next to the orthomosaic."""
    return inp.project_dir / str(cfg.tiling.zoom)


def count_tiles(tiles_dir: Path) -> int:
    n = 0
    if tiles_dir.is_dir():
        for _, _, files in os.walk(tiles_dir):
            n += sum(1 for f in files if f.lower().endswith((".png", ".jpg", ".jpeg")))
    return n


def tile_info(cfg: Config, inp: InputInfo) -> TileInfo:
    d = tiles_dir_for(cfg, inp)
    n = count_tiles(d)
    mod = datetime.fromtimestamp(d.stat().st_mtime) if d.is_dir() else None
    return TileInfo(path=d, count=n, modified=mod)


def guess_architecture(name: str) -> str:
    low = name.lower()
    if low.startswith("segformer"):
        return "SegFormer"
    if low.startswith("unet"):
        return "UNet"
    return "Unknown"


def find_models(cfg: Config) -> list[ModelInfo]:
    d = cfg.inference.models_dir
    models: list[ModelInfo] = []
    if not d.is_dir():
        return models
    for p in sorted(d.rglob("*.json")):
        name = p.stem
        models.append(ModelInfo(
            name=name, path=p, architecture=guess_architecture(name),
            note=cfg.model_notes.get(name, ""),
            recommended=(name == cfg.recommended_model),
        ))
    models.sort(key=lambda m: (not m.recommended, m.architecture, m.name))
    return models


def tile_bounds(tiles_dir: Path, zoom: int) -> tuple[float, float, float, float] | None:
    """(south, west, north, east) in degrees from TMS tile folder names <x>/<y>.png."""
    import math
    if not tiles_dir.is_dir():
        return None
    xs, ys = [], []
    for xd in os.scandir(tiles_dir):
        if xd.is_dir() and xd.name.isdigit():
            names = [f.name.split(".")[0] for f in os.scandir(xd.path) if f.name.endswith(".png")]
            nums = [int(v) for v in names if v.isdigit()]
            if nums:
                xs.append(int(xd.name))
                ys += [min(nums), max(nums)]
    if not xs:
        return None
    n = 2 ** zoom

    def lat(y_xyz: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y_xyz / n))))

    west, east = min(xs) / n * 360 - 180, (max(xs) + 1) / n * 360 - 180
    north = lat(n - 1 - max(ys))       # TMS y counts from the south
    south = lat(n - 1 - min(ys) + 1)
    return south, west, north, east
