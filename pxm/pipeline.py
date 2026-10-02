"""Runs queued jobs one at a time (the GPU can only handle one).

Steps follow Manual 8.4: checks -> tiling (8.4.2) -> inference (8.4.3)
-> organise results (8.4.6) + run_manifest.json for traceability (8.8).
"""
from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import signal
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import __version__
from .catalog import count_tiles, guess_architecture
from .commands import inference_command, pretty, tiling_command, venv_environment
from .config import Config
from .jobs import CANCELLED, DONE, FAILED, Job, JobStore, now
from .preflight import has_errors, run_checks

VIEWER_FILES = ("*.html", "tilemapresource.xml", "*.kml")


class JobCancelled(Exception):
    pass


class StepFailed(Exception):
    pass


def result_dir_for(cfg: Config, job: Job, when: datetime | None = None) -> Path:
    project_dir = Path(job.input_tif).parent
    base = project_dir.parent / f"{job.project}_Result"
    if cfg.results_layout == "manual":
        return base
    when = when or datetime.now()
    conf = "default" if job.threshold is None else f"c{job.threshold:.2f}"
    name = f"{when:%Y-%m-%d_%H%M}_{job.model_name}_{conf}"
    dest, n = base / name, 2
    while dest.exists():  # two runs in the same minute never overwrite each other
        dest, n = base / f"{name}_{n}", n + 1
    return dest


def run_process(cmd: list[str], *, cwd: Path, env: dict, log: Callable[[str], None],
                cancel: threading.Event, on_output: Callable[[str], None] | None = None,
                on_tick: Callable[[], None] | None = None) -> int:
    """Run a command, streaming output into the job log as it arrives.

    Reads raw bytes (not lines) because gdal2tiles prints progress as
    "0...10...20" without newlines.
    """
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    last_tick = 0.0
    try:
        while True:
            if cancel.is_set():
                _terminate(proc)
                raise JobCancelled()
            for key, _ in sel.select(timeout=0.5):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    log(text)
                    if on_output:
                        on_output(text)
            if on_tick and time.time() - last_tick > 1.5:
                last_tick = time.time()
                on_tick()
            if proc.poll() is not None:
                rest = proc.stdout.read()
                if rest:
                    text = rest.decode("utf-8", errors="replace")
                    log(text)
                    if on_output:
                        on_output(text)
                return proc.returncode
    finally:
        sel.close()


def _terminate(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=15)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class Worker:
    """Single background thread that processes the queue in order."""

    def __init__(self, cfg: Config, store: JobStore):
        self.cfg = cfg
        self.store = store
        self._cancel: dict[int, threading.Event] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current_job: int | None = None

    # public API -----------------------------------------------------------
    def start(self) -> None:
        recovered = self.store.recover_interrupted()
        if recovered:
            print(f"[pxm] marked {recovered} interrupted job(s) as failed")
        self._thread = threading.Thread(target=self._loop, name="pxm-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for ev in self._cancel.values():
            ev.set()

    def notify(self) -> None:
        self._wake.set()

    def cancel(self, job_id: int) -> bool:
        if self.store.cancel_if_queued(job_id):
            return True
        ev = self._cancel.get(job_id)
        if ev:
            ev.set()
            return True
        return False

    def log_path(self, job_id: int) -> Path:
        return self.cfg.logs_dir / f"job_{job_id:05d}.log"

    # internals ------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next()
            if job is None:
                self._wake.wait(timeout=2)
                self._wake.clear()
                continue
            ev = threading.Event()
            self._cancel[job.id] = ev
            self.current_job = job.id
            try:
                JobRun(self, job, ev).run()
            finally:
                self._cancel.pop(job.id, None)
                self.current_job = None


class JobRun:
    def __init__(self, worker: Worker, job: Job, cancel: threading.Event):
        self.w, self.cfg, self.store = worker, worker.cfg, worker.store
        self.job, self.cancel = job, cancel
        self.steps = job.steps
        self.cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        self._log_fh = open(worker.log_path(job.id), "a", encoding="utf-8")
        self.commands: dict[str, str] = {}
        self.pxm_run_folder: Path | None = None

    # logging / progress ---------------------------------------------------
    def log(self, text: str) -> None:
        self._log_fh.write(text)
        self._log_fh.flush()

    def say(self, msg: str) -> None:
        self.log(f"\n[{datetime.now():%H:%M:%S}] {msg}\n")

    def set_step(self, idx: int, status: str, detail: str | None = None) -> None:
        s = self.steps[idx]
        s["status"] = status
        if status == "running":
            s["started"] = now()
        elif status in ("done", "failed", "cancelled"):
            s["finished"] = now()
        if detail is not None:
            s["detail"] = detail
        self.store.update(self.job.id, steps=self.steps,
                          stage=self.steps[idx]["name"] if status == "running" else self.job.stage)

    def progress(self, value: float, stage: str | None = None) -> None:
        fields = {"progress": max(0.0, min(1.0, value))}
        if stage:
            fields["stage"] = stage
            self.job.stage = stage
        self.store.update(self.job.id, **fields)

    # main -----------------------------------------------------------------
    def run(self) -> None:
        j = self.job
        self.say(f"Job #{j.id} started on {socket.gethostname()} (Pixel Muncher GUI v{__version__}"
                 f"{', DEMO MODE' if self.cfg.mock else ''})")
        current = 0
        try:
            current = 0
            self._step_checks()
            current = 1
            if j.retile:
                self._step_tiles()
            current = 2
            self._step_classify()
            current = 3
            self._step_save()
            self.progress(1.0, "Finished")
            self.store.update(j.id, status=DONE, finished_at=now())
            self.say("Job finished successfully.")
        except JobCancelled:
            self.set_step(current, "cancelled")
            self.store.update(j.id, status=CANCELLED, finished_at=now(), stage="Cancelled")
            self.say("Job cancelled by user.")
        except StepFailed as exc:
            self.set_step(current, "failed", str(exc))
            self.store.update(j.id, status=FAILED, finished_at=now(), error=str(exc), stage="Failed")
            self.say(f"FAILED: {exc}")
        except Exception as exc:  # noqa: BLE001 - never kill the worker thread
            msg = f"Unexpected error: {type(exc).__name__}: {exc}"
            self.set_step(current, "failed", msg)
            self.store.update(j.id, status=FAILED, finished_at=now(), error=msg, stage="Failed")
            self.say(msg)
        finally:
            self._log_fh.close()

    # step 1 ---------------------------------------------------------------
    def _step_checks(self) -> None:
        self.set_step(0, "running")
        self.progress(0.01, "Checks")
        j = self.job
        tiles_dir = Path(j.input_tif).parent / str(self.cfg.tiling.zoom)
        checks = run_checks(self.cfg, input_tif=Path(j.input_tif), model_json=Path(j.model_path),
                            threshold=j.threshold, retile=j.retile,
                            tile_count=count_tiles(tiles_dir))
        for c in checks:
            self.log(f"  [{c.status.upper():5}] {c.label}: {c.message}\n")
        if has_errors(checks):
            first = next(c for c in checks if c.status == "error")
            raise StepFailed(f"{first.label}: {first.message}")
        self.set_step(0, "done")

    # step 2 ---------------------------------------------------------------
    def _step_tiles(self) -> None:
        self.set_step(1, "running")
        j, t = self.job, self.cfg.tiling
        project_dir = Path(j.input_tif).parent
        tiles_dir = project_dir / str(t.zoom)
        if tiles_dir.exists():
            aside = project_dir / f"{t.zoom}_previous_{datetime.now():%Y%m%d-%H%M%S}"
            tiles_dir.rename(aside)
            self.say(f"Moved existing tiles to {aside.name}")
        cmd = tiling_command(self.cfg, Path(j.input_tif), project_dir)
        self.commands["tiling"] = pretty(cmd)
        self.say(f"Making tiles (Manual 8.4.2):\n$ {pretty(cmd)}")
        base, span = 0.02, 0.28
        pct_re = re.compile(r"(\d{1,3})(?=\.{3}|\s*-\s*done)")

        def on_output(text: str) -> None:
            nums = [int(n) for n in pct_re.findall(text) if int(n) <= 100]
            if nums:
                self.progress(base + span * nums[-1] / 100)

        rc = run_process(cmd, cwd=project_dir, env=venv_environment(t.python), log=self.log,
                         cancel=self.cancel, on_output=on_output)
        if rc != 0:
            raise StepFailed(f"Tiling failed (exit code {rc}). See the log for details.")
        n = count_tiles(tiles_dir)
        if n == 0:
            raise StepFailed(f"Tiling finished but no tiles were found in {tiles_dir}.")
        self.store.update(j.id, tile_count=n)
        self.job.tile_count = n
        self.set_step(1, "done", f"{n:,} tiles")

    # step 3 ---------------------------------------------------------------
    def _step_classify(self) -> None:
        self.set_step(2, "running")
        j, inf = self.job, self.cfg.inference
        tiles_dir = Path(j.input_tif).parent / str(self.cfg.tiling.zoom)
        total = j.tile_count or count_tiles(tiles_dir)
        inf.results_dir.mkdir(parents=True, exist_ok=True)
        before = {p.name for p in inf.results_dir.iterdir()}
        cmd = inference_command(self.cfg, Path(j.model_path), tiles_dir, j.threshold)
        self.commands["inference"] = pretty(cmd)
        self.say(f"Classifying {total:,} tiles (Manual 8.4.3):\n$ cd {inf.workdir}\n$ {pretty(cmd)}")
        base = 0.30 if j.retile else 0.02
        span = 0.93 - base
        self.progress(base, "Classify")

        def new_run_folder() -> Path | None:
            new = [p for p in inf.results_dir.iterdir() if p.name not in before and p.is_dir()]
            return max(new, key=lambda p: p.stat().st_mtime) if new else None

        def on_tick() -> None:
            folder = new_run_folder()
            if folder and total:
                done = count_tiles(folder / inf.output_subfolder)
                self.progress(base + span * min(done / total, 1.0))

        rc = run_process(cmd, cwd=inf.workdir, env=venv_environment(inf.python), log=self.log,
                         cancel=self.cancel, on_tick=on_tick)
        if rc != 0:
            raise StepFailed(f"Pixel Muncher failed (exit code {rc}). Common causes: GPU out of "
                             "memory, wrong environment, missing model file. See the log.")
        folder = new_run_folder()
        if folder is None:
            raise StepFailed(f"Pixel Muncher finished but no new results folder appeared in "
                             f"{inf.results_dir}.")
        self.pxm_run_folder = folder
        self.say(f"Pixel Muncher output: {folder}")
        self.set_step(2, "done", folder.name)

    # step 4 ---------------------------------------------------------------
    def _step_save(self) -> None:
        self.set_step(3, "running")
        self.progress(0.95, "Save results")
        j, inf, zoom = self.job, self.cfg.inference, str(self.cfg.tiling.zoom)
        run = self.pxm_run_folder
        assert run is not None
        src = run / inf.output_subfolder
        if not src.is_dir():
            found = [p.name for p in run.iterdir()]
            raise StepFailed(f"Expected folder '{inf.output_subfolder}' inside {run}, found: {found}")
        dest = result_dir_for(self.cfg, j)
        if self.cfg.results_layout == "manual" and (dest / zoom).exists():
            raise StepFailed(f"{dest / zoom} already exists. Move it, then re-run.")
        dest.mkdir(parents=True, exist_ok=True)

        # Manual 8.4.6: segmentation folder renamed to the tile batch (23/)
        shutil.copytree(src, dest / zoom)
        self.say(f"Copied {src.name}/ -> {dest / zoom}")
        # log.log
        logs = [run / inf.log_name] if (run / inf.log_name).exists() else sorted(run.glob("*.log"))
        for lf in logs:
            shutil.copy2(lf, dest / lf.name)
        # map viewer files produced by gdal2tiles
        project_dir = Path(j.input_tif).parent
        viewers = [p for pat in VIEWER_FILES for p in project_dir.glob(pat)]
        for v in viewers:
            shutil.copy2(v, dest / v.name)
        # model config kept with the results (Manual 8.4.4, 8.8)
        (dest / "model_config").mkdir(exist_ok=True)
        shutil.copy2(j.model_path, dest / "model_config" / Path(j.model_path).name)
        self._write_manifest(dest, run)

        self.store.update(j.id, result_dir=str(dest))
        self.set_step(3, "done", str(dest))

    def _write_manifest(self, dest: Path, run: Path) -> None:
        j = self.store.get(self.job.id)
        inp = Path(j.input_tif)
        st = inp.stat()
        manifest = {
            "manifest_version": 1,
            "app": {"name": "pixel-muncher-gui", "version": __version__, "demo_mode": self.cfg.mock,
                    "host": socket.gethostname(), "config": str(self.cfg.path)},
            "job": {"id": j.id, "submitted_by": j.submitted_by, "created_at": j.created_at,
                    "started_at": j.started_at, "finished_at": now(), "note": j.note},
            "input": {"orthomosaic": str(inp), "size_bytes": st.st_size,
                      "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                      "project": j.project},
            "tiles": {"folder": str(inp.parent / str(self.cfg.tiling.zoom)), "count": j.tile_count,
                      "zoom": self.cfg.tiling.zoom, "tile_size": self.cfg.tiling.tile_size,
                      "rebuilt_this_run": j.retile},
            "model": {"name": j.model_name, "architecture": guess_architecture(j.model_name),
                      "config_path": j.model_path,
                      "copied_to": f"model_config/{Path(j.model_path).name}"},
            "confidence_threshold": j.threshold,
            "commands": self.commands,
            "pixel_muncher_run_folder": str(run),
            "results_layout": self.cfg.results_layout,
        }
        (dest / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
        self.say("Wrote run_manifest.json")
