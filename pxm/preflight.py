"""Checks run before a job is queued and again right before it starts.

Messages are written for analysts: say what is wrong and what to do.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config

OK, WARN, ERROR = "ok", "warn", "error"


@dataclass
class Check:
    label: str
    status: str
    message: str


_gpu_cache: tuple[float, tuple[bool, str]] | None = None


def gpu_status(max_age: float = 30.0) -> tuple[bool, str]:
    """(available, description) from nvidia-smi, cached for a few seconds."""
    global _gpu_cache
    now = time.time()
    if _gpu_cache and now - _gpu_cache[0] < max_age:
        return _gpu_cache[1]
    exe = shutil.which("nvidia-smi")
    if not exe:
        result = (False, "nvidia-smi not found (NVIDIA driver missing?)")
    else:
        try:
            out = subprocess.run(
                [exe, "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            line = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
            if line:
                name, used, total = [x.strip() for x in line.split(",")]
                result = (True, f"{name} ({int(used) / 1024:.1f} / {int(total) / 1024:.1f} GB used)")
            else:
                result = (False, "nvidia-smi found no GPU")
        except Exception as exc:  # noqa: BLE001
            result = (False, f"nvidia-smi failed: {exc}")
    _gpu_cache = (now, result)
    return result


def _file(label: str, p: Path | None, what: str) -> Check:
    if p is None:
        return Check(label, ERROR, f"{what} is not set in config.yaml.")
    if not p.exists():
        return Check(label, ERROR, f"{what} not found: {p}. Ask the processing lead to fix config.yaml.")
    return Check(label, OK, str(p))


_module_cache: dict[tuple[str, str], tuple[float, Check]] = {}


def _module(label: str, python: Path, module: str) -> Check:
    """Can `python` import `module`? Cached for a minute (it spawns a process)."""
    key, now = (str(python), module), time.time()
    if key in _module_cache and now - _module_cache[key][0] < 60:
        return _module_cache[key][1]
    if not Path(python).exists():
        check = Check(label, ERROR, f"Python not found: {python}")
    else:
        try:
            r = subprocess.run([str(python), "-c", f"import {module}"], capture_output=True,
                               text=True, timeout=60)
            check = Check(label, OK, module) if r.returncode == 0 else Check(
                label, ERROR, f"{python} cannot import {module}. Is GDAL installed in this "
                f"environment? ({(r.stderr.strip().splitlines() or ['?'])[-1]})")
        except Exception as exc:  # noqa: BLE001
            check = Check(label, ERROR, f"Could not test {module}: {exc}")
    _module_cache[key] = (now, check)
    return check


def _free_gb(path: Path) -> float | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free / 1024**3
    except OSError:
        return None


def run_checks(cfg: Config, *, input_tif: Path | None, model_json: Path | None,
               threshold: float | None, retile: bool, tile_count: int,
               result_dir: Path | None = None) -> list[Check]:
    checks: list[Check] = []

    # 1. input
    if input_tif is None:
        checks.append(Check("Orthomosaic", ERROR, "Choose an orthomosaic."))
    elif not input_tif.is_file():
        checks.append(Check("Orthomosaic", ERROR, f"File not found: {input_tif}"))
    elif not os.access(input_tif, os.R_OK):
        checks.append(Check("Orthomosaic", ERROR, f"No permission to read {input_tif}"))
    else:
        checks.append(Check("Orthomosaic", OK, input_tif.name))

    # 2. tiles / tiling tool
    if retile:
        t = cfg.tiling
        if isinstance(t.script, str) and t.script.startswith("module:"):
            c1 = _module("Tiling tool", t.python, t.script.split(":", 1)[1])
        else:
            c1 = _file("Tiling tool", t.script, "gdal2tiles.py")
        c2 = _file("Tiling environment", t.python, "Tiling Python")
        checks += [c for c in (c1, c2) if c.status != OK] or [Check("Tiling tool", OK, "gdal2tiles ready")]
        if tile_count:
            checks.append(Check("Existing tiles", WARN,
                                f"{tile_count:,} existing tiles will be moved aside and rebuilt."))
    else:
        if tile_count == 0:
            checks.append(Check("Tiles", ERROR, "No tiles found. Turn on 'Make tiles' so they are created."))
        else:
            checks.append(Check("Tiles", OK, f"Reusing {tile_count:,} existing tiles"))

    # 3. inference environment
    i = cfg.inference
    env_checks = [
        _file("Pixel Muncher folder", i.workdir, "Pixel Muncher folder"),
        _file("Pixel Muncher environment", i.python, "Inference Python"),
        _file("inference.py", i.script, "inference.py"),
        _file("Post-processing config", i.postprocessing, "Post-processing config"),
    ]
    bad = [c for c in env_checks if c.status != OK]
    checks += bad or [Check("Pixel Muncher", OK, "Environment ready")]

    # 4. model
    if model_json is None:
        checks.append(Check("Model", ERROR, "Choose a model."))
    elif not model_json.is_file():
        checks.append(Check("Model", ERROR, f"Model config not found: {model_json}"))
    else:
        checks.append(Check("Model", OK, model_json.stem))

    # 5. threshold
    if threshold is not None:
        if not 0 < threshold <= 1:
            checks.append(Check("Confidence", ERROR, "Confidence must be between 0 and 1."))
        elif threshold < 0.8:
            checks.append(Check("Confidence", WARN,
                                f"{threshold:.2f} is below the recommended 0.80 to 0.99 range."))
        else:
            checks.append(Check("Confidence", OK, f"{threshold:.2f} (recorded in the run manifest)"))
    else:
        checks.append(Check("Confidence", OK, "Model default"))

    # 6. GPU
    if i.require_gpu:
        ok, desc = gpu_status()
        checks.append(Check("GPU", OK if ok else ERROR,
                            desc if ok else f"{desc}. Inference cannot run without the GPU."))

    # 7. disk space
    free = _free_gb(cfg.data_root)
    if free is not None:
        if free < cfg.min_free_gb:
            checks.append(Check("Disk space", WARN, f"Only {free:.0f} GB free in the data folder."))
        else:
            checks.append(Check("Disk space", OK, f"{free:.0f} GB free"))

    # 8. destination
    if result_dir is not None and result_dir.exists() and cfg.results_layout == "manual":
        checks.append(Check("Result folder", ERROR,
                            f"{result_dir} already exists. Rename or move it first."))
    return checks


def has_errors(checks: list[Check]) -> bool:
    return any(c.status == ERROR for c in checks)


def environment_report(cfg: Config) -> list[Check]:
    """Everything that can be checked without choosing a file or model (./run.sh --check)."""
    from .catalog import find_inputs, find_models
    checks: list[Check] = [Check("Config file", OK, str(cfg.path))]
    if cfg.data_root.is_dir():
        n = len(find_inputs(cfg))
        checks.append(Check("Data folder", OK if n else WARN,
                            f"{cfg.data_root} ({n} orthomosaic(s) found)"))
    else:
        checks.append(Check("Data folder", ERROR, f"Not found: {cfg.data_root}"))
    t = cfg.tiling
    if isinstance(t.script, str) and t.script.startswith("module:"):
        checks.append(_module("Tiling tool", t.python, t.script.split(":", 1)[1]))
    else:
        checks.append(_file("Tiling tool", t.script, "gdal2tiles.py"))
    checks.append(_file("Tiling Python", t.python, "Tiling Python"))
    i = cfg.inference
    checks += [
        _file("Pixel Muncher folder", i.workdir, "Pixel Muncher folder"),
        _file("Inference Python", i.python, "Inference Python"),
        _file("inference.py", i.script, "inference.py"),
        _file("Post-processing config", i.postprocessing, "Post-processing config"),
    ]
    models = find_models(cfg)
    if not models:
        checks.append(Check("Models", ERROR, f"No .json model configs in {i.models_dir}"))
    else:
        rec = any(m.recommended for m in models)
        checks.append(Check("Models", OK if rec else WARN,
                            f"{len(models)} found" + ("" if rec else
                            f"; recommended model '{cfg.recommended_model}' is missing")))
    res = i.results_dir
    probe = res if res.exists() else res.parent
    if not probe.exists():
        checks.append(Check("Results folder", ERROR, f"Not found: {res}"))
    elif not os.access(probe, os.W_OK):
        checks.append(Check("Results folder", ERROR, f"{res} is not writable by this user"))
    else:
        checks.append(Check("Results folder", OK, str(res)))
    if i.require_gpu:
        ok, desc = gpu_status(max_age=0)
        checks.append(Check("GPU", OK if ok else ERROR, desc))
    free = _free_gb(cfg.data_root)
    if free is not None:
        checks.append(Check("Disk space", OK if free >= cfg.min_free_gb else WARN, f"{free:.0f} GB free"))
    return checks
