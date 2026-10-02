"""Load config.yaml into typed settings with every path resolved."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _resolve(value: str | None, base: Path) -> Path | None:
    if value in (None, ""):
        return None
    p = Path(str(value)).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def _script(value: str | None, base: Path) -> Path | str | None:
    """A script path, or 'module:<python.module>' to run with `python -m`."""
    if isinstance(value, str) and value.startswith("module:"):
        return value
    return _resolve(value, base)


def _python(value: str | None, base: Path) -> Path:
    if value in (None, "", "auto"):
        return Path(sys.executable)
    return _resolve(value, base)


@dataclass
class TilingCfg:
    python: Path
    script: Path | str  # a file path, or "module:osgeo_utils.gdal2tiles"
    zoom: int = 23
    tile_size: int = 512
    processes: int = 16
    nodata: int = 0
    resampling: str = "near"
    webviewer: str = "all"
    exclude_transparent: bool = True


@dataclass
class InferenceCfg:
    workdir: Path
    python: Path
    script: Path
    models_dir: Path
    postprocessing: Path
    results_dir: Path
    output_subfolder: str = "segmentation_rgb"
    log_name: str = "log.log"
    threshold_key: str = "pytorchseg_confidence_threshold"
    extra_args: list[str] = field(default_factory=list)
    require_gpu: bool = True


@dataclass
class Config:
    path: Path
    title: str
    host: str
    port: int
    state_dir: Path
    mock: bool
    data_root: Path
    scan_depth: int
    min_free_gb: float
    tiling: TilingCfg
    inference: InferenceCfg
    results_layout: str
    recommended_model: str
    model_notes: dict[str, str]

    @property
    def db_path(self) -> Path:
        return self.state_dir / "jobs.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(path.read_text()) or {}
    base = path.parent
    a, d, t, i = (raw.get(k, {}) or {} for k in ("app", "data", "tiling", "inference"))
    r, m = raw.get("results", {}) or {}, raw.get("models", {}) or {}

    workdir = _resolve(i.get("workdir"), base)
    tiling = TilingCfg(
        python=_python(t.get("python"), base),
        script=_script(t.get("script"), base),
        zoom=int(t.get("zoom", 23)),
        tile_size=int(t.get("tile_size", 512)),
        processes=int(t.get("processes", 16)),
        nodata=int(t.get("nodata", 0)),
        resampling=str(t.get("resampling", "near")),
        webviewer=str(t.get("webviewer", "all")),
        exclude_transparent=bool(t.get("exclude_transparent", True)),
    )
    inference = InferenceCfg(
        workdir=workdir,
        python=_python(i.get("python"), base),
        script=_resolve(i.get("script"), workdir),
        models_dir=_resolve(i.get("models_dir"), base),
        postprocessing=_resolve(i.get("postprocessing"), workdir),
        results_dir=_resolve(i.get("results_dir"), base),
        output_subfolder=str(i.get("output_subfolder", "segmentation_rgb")),
        log_name=str(i.get("log_name", "log.log")),
        threshold_key=str(i.get("threshold_key", "pytorchseg_confidence_threshold")),
        extra_args=[str(x) for x in (i.get("extra_args") or [])],
        require_gpu=bool(i.get("require_gpu", True)),
    )
    layout = str(r.get("layout", "per_run"))
    if layout not in ("per_run", "manual"):
        raise ValueError(f"results.layout must be 'per_run' or 'manual', got {layout!r}")
    return Config(
        path=path,
        title=str(a.get("title", "Pixel Muncher")),
        host=str(a.get("host", "0.0.0.0")),
        port=int(a.get("port", 8080)),
        state_dir=_resolve(a.get("state_dir", "~/.pxm_gui"), base),
        mock=bool(a.get("mock", False)),
        data_root=_resolve(d.get("root", "~/data"), base),
        scan_depth=int(d.get("scan_depth", 2)),
        min_free_gb=float(d.get("min_free_gb", 20)),
        tiling=tiling,
        inference=inference,
        results_layout=layout,
        recommended_model=str(m.get("recommended", "")),
        model_notes={str(k): str(v) for k, v in (m.get("notes") or {}).items()},
    )
