"""End-to-end tests of the job engine using the mock tools. Run: python -m pytest -q"""
import json
import os
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pxm.catalog import find_inputs, find_models, tile_info  # noqa: E402
from pxm.commands import inference_command, tiling_command  # noqa: E402
from pxm.config import load_config  # noqa: E402
from pxm.jobs import CANCELLED, DONE, FAILED, JobStore  # noqa: E402
from pxm.pipeline import Worker  # noqa: E402
from pxm.preflight import ERROR, run_checks  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data" / "SiteA"
    data.mkdir(parents=True)
    (data / "ortho.tif").write_bytes(b"II*\x00" + b"\x00" * 1000)
    work = tmp_path / "pxm" / "pixel_muncher"
    (work / "post_processing_configurations").mkdir(parents=True)
    (work / "post_processing_configurations" / "SegmentationRGBOnly.json").write_text("{}")
    models = tmp_path / "pxm" / "models"
    models.mkdir()
    (models / "unet_demo_best.json").write_text("{}")
    (models / "segformer_demo.json").write_text("{}")
    raw = yaml.safe_load((ROOT / "config.mock.yaml").read_text())
    raw["app"]["state_dir"] = str(tmp_path / "state")
    raw["data"]["root"] = str(tmp_path / "data")
    raw["tiling"]["script"] = str(ROOT / "mock" / "fake_gdal2tiles.py")
    raw["inference"].update(workdir=str(work), script=str(ROOT / "mock" / "fake_inference.py"),
                            models_dir=str(models), results_dir=str(work / "results"))
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(raw))
    cfg = load_config(cfg_path)
    store = JobStore(cfg.db_path)
    worker = Worker(cfg, store)
    worker.start()
    yield cfg, store, worker
    worker.stop()


def submit(cfg, store, worker, *, retile=True, threshold=0.9, model_idx=0):
    inp = find_inputs(cfg)[0]
    m = find_models(cfg)[model_idx]
    jid = store.add(project=inp.project, input_tif=str(inp.path), model_name=m.name,
                    model_path=str(m.path), threshold=threshold, retile=retile,
                    tile_count=0 if retile else tile_info(cfg, inp).count)
    worker.notify()
    return jid


def wait(store, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = store.get(jid)
        if j.status not in ("queued", "running"):
            return j
        time.sleep(0.3)
    raise TimeoutError


def test_commands_match_manual(env):
    cfg, *_ = env
    t = tiling_command(cfg, Path("/d/in.tif"), Path("/d"))
    assert t[2:] == ["--tilesize=256", "-w", "all", "-x", "--processes", "4", "-a", "0",
                     "-r", "near", "-z", "23", "/d/in.tif", "/d"]
    i = inference_command(cfg, Path("/m/model.json"), Path("/d/23"), 0.95)
    assert i[2:8] == ["-p", "/m/model.json", "-i", "/d/23/", "-pp", str(cfg.inference.postprocessing)]
    assert json.loads(i[i.index("-a") + 1]) == {"pytorchseg_confidence_threshold": 0.95}
    assert "-a" not in inference_command(cfg, Path("/m.json"), Path("/d/23"), None)


def test_full_run_produces_manual_structure(env):
    cfg, store, worker = env
    j = wait(store, submit(cfg, store, worker))
    assert j.status == DONE, j.error
    rd = Path(j.result_dir)
    assert rd.parent.name == "SiteA_Result"
    assert (rd / "23").is_dir() and any((rd / "23").rglob("*.png"))
    assert (rd / "log.log").exists() and (rd / "openlayers.html").exists()
    man = json.loads((rd / "run_manifest.json").read_text())
    assert man["confidence_threshold"] == 0.9
    assert man["model"]["name"] == j.model_name
    assert (rd / man["model"]["copied_to"]).exists()
    assert "inference" in man["commands"] and "tiling" in man["commands"]


def test_reuse_tiles_and_queue_order(env):
    cfg, store, worker = env
    first = wait(store, submit(cfg, store, worker))
    a = submit(cfg, store, worker, retile=False, threshold=None)
    b = submit(cfg, store, worker, retile=False, threshold=0.8, model_idx=1)
    ja, jb = wait(store, a), wait(store, b)
    assert first.status == ja.status == jb.status == DONE
    assert ja.steps[1]["status"] == "skipped"
    assert jb.started_at >= ja.finished_at  # strictly one at a time
    assert ja.result_dir != jb.result_dir


def test_retile_moves_old_tiles_aside(env):
    cfg, store, worker = env
    wait(store, submit(cfg, store, worker))
    j = wait(store, submit(cfg, store, worker, retile=True))
    assert j.status == DONE
    proj = Path(j.input_tif).parent
    assert any(p.name.startswith("23_previous_") for p in proj.iterdir())


def test_failure_is_reported(env, monkeypatch):
    cfg, store, worker = env
    monkeypatch.setenv("MOCK_FAIL", "1")
    j = wait(store, submit(cfg, store, worker))
    assert j.status == FAILED
    assert "exit code 1" in j.error
    assert j.steps[2]["status"] == "failed"
    assert "CUDA out of memory" in worker.log_path(j.id).read_text()


def test_cancel_running_and_queued(env):
    cfg, store, worker = env
    a = submit(cfg, store, worker)
    b = submit(cfg, store, worker)
    while store.get(a).status != "running":
        time.sleep(0.1)
    time.sleep(1.0)
    assert worker.cancel(b)          # queued -> cancelled immediately
    assert worker.cancel(a)          # running -> process group killed
    assert wait(store, a).status == CANCELLED
    assert store.get(b).status == CANCELLED


def test_preflight_blocks_missing_model_and_tiles(env):
    cfg, *_ = env
    inp = find_inputs(cfg)[0]
    checks = run_checks(cfg, input_tif=inp.path, model_json=Path("/nope.json"), threshold=None,
                        retile=False, tile_count=0)
    errors = {c.label for c in checks if c.status == ERROR}
    assert {"Model", "Tiles"} <= errors


def test_restart_marks_running_jobs_failed(env):
    cfg, store, worker = env
    jid = submit(cfg, store, worker)
    store.update(jid, status="running")
    worker.stop()
    assert store.recover_interrupted() >= 1
    assert "Interrupted" in store.get(jid).error


def test_tile_bounds_and_module_tiling_command(env):
    from pxm.catalog import tile_bounds
    from pxm.commands import script_args
    cfg, store, worker = env
    j = wait(store, submit(cfg, store, worker))
    s, w, n, e = tile_bounds(Path(j.input_tif).parent / "23", 23)
    assert s < n and w < e
    assert script_args("module:osgeo_utils.gdal2tiles") == ["-m", "osgeo_utils.gdal2tiles"]
