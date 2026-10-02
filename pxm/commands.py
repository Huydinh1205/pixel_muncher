"""Build the exact command lines from Manual 8.4.2 and 8.4.4.

Commands are argument lists (never shell strings), so paths with spaces or
odd characters cannot break or inject anything.

Instead of `source <env>/bin/activate`, we call the environment's own python
and set PATH / VIRTUAL_ENV the same way `activate` does. The result is the
same environment without needing a shell.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .config import Config


def venv_environment(python: Path) -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = Path(python).parent
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    venv_root = bin_dir.parent
    if (venv_root / "pyvenv.cfg").exists():
        env["VIRTUAL_ENV"] = str(venv_root)
    env.pop("PYTHONHOME", None)
    env["PYTHONUNBUFFERED"] = "1"  # so progress reaches the log immediately
    return env


def script_args(script) -> list[str]:
    """'module:x.y' -> ['-m', 'x.y'];  a path -> [path]."""
    if isinstance(script, str) and script.startswith("module:"):
        return ["-m", script.split(":", 1)[1]]
    return [str(script)]


def tiling_command(cfg: Config, input_tif: Path, output_dir: Path) -> list[str]:
    t = cfg.tiling
    cmd = [str(t.python), *script_args(t.script),
        f"--tilesize={t.tile_size}",
        "-w", t.webviewer,
    ]
    if t.exclude_transparent:
        cmd.append("-x")
    cmd += [
        "--processes", str(t.processes),
        "-a", str(t.nodata),
        "-r", t.resampling,
        "-z", str(t.zoom),
        str(input_tif), str(output_dir),
    ]
    return cmd


def inference_command(cfg: Config, model_json: Path, tiles_dir: Path,
                      threshold: float | None) -> list[str]:
    i = cfg.inference
    cmd = [
        str(i.python), str(i.script),
        "-p", str(model_json),
        "-i", str(tiles_dir).rstrip("/") + "/",
        "-pp", str(i.postprocessing),
    ]
    if threshold is not None:
        cmd += ["-a", json.dumps({i.threshold_key: round(float(threshold), 4)})]
    cmd += list(i.extra_args)
    return cmd


def pretty(cmd: list[str]) -> str:
    """Human-readable version for logs and the manifest."""
    import shlex
    return " ".join(shlex.quote(c) for c in cmd)
