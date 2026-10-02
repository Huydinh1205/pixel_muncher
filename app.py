"""Pixel Muncher GUI - web front end for Chapter 8 of the processing manual.

Run:  ./run.sh            production on the GPU workstation (config.yaml)
      ./run.sh --check    check config.yaml paths, models and GPU, then exit
      ./run.sh --mock     demo with fake data and fake tools (config.mock.yaml)
      ./run.sh --local    your own .tif files, real tiling, fake classification
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from fastapi import Request
from nicegui import app, ui

from pxm import __version__
from pxm.catalog import InputInfo, ModelInfo, find_inputs, find_models, tile_bounds, tile_info
from pxm.config import load_config
from pxm.jobs import ACTIVE, CANCELLED, DONE, FAILED, QUEUED, RUNNING, Job, JobStore
from pxm.pipeline import Worker, result_dir_for
from pxm.preflight import ERROR, OK, WARN, Check, gpu_status, has_errors, run_checks

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- bootstrap
parser = argparse.ArgumentParser(add_help=False)
# config.yaml is git-ignored (internal paths). It is created from config.example.yaml.
parser.add_argument("--config", default=os.environ.get("PXM_CONFIG", str(HERE / "config.yaml")))
parser.add_argument("--mock", action="store_true")
parser.add_argument("--check", action="store_true")
ARGS, _ = parser.parse_known_args()
CONFIG_PATH = HERE / "config.mock.yaml" if ARGS.mock else Path(ARGS.config)

if not Path(CONFIG_PATH).exists():
    raise SystemExit(f"Config file not found: {CONFIG_PATH}\n"
                     "Create it first:  cp config.example.yaml config.yaml  (then edit the paths)")
cfg = load_config(CONFIG_PATH)
if ARGS.check:
    from pxm.preflight import environment_report
    report = environment_report(cfg)
    for c in report:
        print(f"[{c.status.upper():5}] {c.label:24} {c.message}")
    bad = sum(c.status == ERROR for c in report)
    print(f"\n{'All checks passed.' if not bad else f'{bad} problem(s). Fix config.yaml and run again.'}")
    raise SystemExit(1 if bad else 0)
cfg.state_dir.mkdir(parents=True, exist_ok=True)
cfg.data_root.mkdir(parents=True, exist_ok=True)
store = JobStore(cfg.db_path)
worker = Worker(cfg, store)
app.on_startup(worker.start)
app.on_shutdown(worker.stop)
app.add_static_files("/files", cfg.data_root)
app.add_static_files("/assets", HERE / "assets")

APP_HEAD = """
<link rel="manifest" href="/assets/manifest.webmanifest">
<link rel="apple-touch-icon" href="/assets/icon-180.png">
<meta name="theme-color" content="#2f6b4f">
<meta name="application-name" content="Pixel Muncher">
<meta name="apple-mobile-web-app-title" content="Pixel Muncher">
"""

STATUS_COLOR = {QUEUED: "grey-7", RUNNING: "blue-7", DONE: "positive", FAILED: "negative",
                CANCELLED: "orange-8"}
STATUS_TEXT = {QUEUED: "Waiting", RUNNING: "Running", DONE: "Done", FAILED: "Failed",
               CANCELLED: "Cancelled"}
STEP_ICON = {"pending": ("radio_button_unchecked", "grey-5"), "running": ("autorenew", "blue-7"),
             "done": ("check_circle", "positive"), "failed": ("error", "negative"),
             "cancelled": ("block", "orange-8"), "skipped": ("remove_circle_outline", "grey-5")}
CHECK_ICON = {OK: ("check_circle", "text-positive"), WARN: ("warning", "text-warning"),
              ERROR: ("cancel", "text-negative")}


# ---------------------------------------------------------------- helpers
def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


def fmt_time(iso: str | None) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso)
    return d.strftime("%H:%M") if d.date() == datetime.now().date() else d.strftime("%d %b %H:%M")


def url_for(path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(cfg.data_root)
    except ValueError:
        return None
    return "/files/" + "/".join(rel.parts)


def map_url(*, result: Path | None = None, project: Path | None = None) -> str | None:
    from urllib.parse import quote
    target = result or project
    try:
        rel = target.resolve().relative_to(cfg.data_root)
    except (ValueError, AttributeError):
        return None
    return f"/map?{'result' if result else 'project'}={quote(rel.as_posix())}"


def safe_data_path(rel: str) -> Path | None:
    """Resolve a user-supplied relative path, refusing anything outside the data folder."""
    p = (cfg.data_root / rel).resolve()
    return p if p.is_relative_to(cfg.data_root) and p.is_dir() else None


def eta_text(job: Job) -> str:
    el = job.duration_seconds()
    if job.status != RUNNING or not el or job.progress < 0.05:
        return ""
    remaining = el / job.progress * (1 - job.progress)
    return f"about {fmt_duration(remaining)} left"


def job_rows() -> list[dict]:
    rows = []
    for j in store.list():
        rows.append({
            "id": j.id, "project": j.project, "model": j.model_name,
            "confidence": j.threshold_label, "status": j.status,
            "status_text": STATUS_TEXT.get(j.status, j.status),
            "status_color": STATUS_COLOR.get(j.status, "grey"),
            "progress": round(j.progress * 100), "stage": j.stage,
            "submitted": fmt_time(j.created_at), "duration": fmt_duration(j.duration_seconds()),
        })
    return rows


# ---------------------------------------------------------------- page
@ui.page("/")
def index(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    ui.add_head_html(APP_HEAD)
    ui.colors(primary="#2f6b4f", secondary="#5b7f6e", accent="#c9a227")
    ui.add_head_html("""<style>
      body { background: #f4f6f4; }
      .pxm-card { width: 100%; }
      .pxm-step-num { width: 28px; height: 28px; border-radius: 50%; background: #2f6b4f;
                      color: white; display:flex; align-items:center; justify-content:center;
                      font-weight: 600; flex-shrink: 0; }
      .pxm-log { height: 320px; font-size: 12px; background: #1d2125; color: #d9e1dc; }
      .pxm-muted { color: #6b7570; font-size: 13px; }
    </style>""")

    # ---- header
    with ui.header().classes("items-center justify-between bg-primary px-4 py-2"):
        with ui.row().classes("items-center gap-3"):
            ui.image("/assets/icon-64.png").classes("w-8 h-8")
            ui.label(cfg.title).classes("text-lg font-semibold")
            ui.label(f"v{__version__}").classes("text-xs opacity-70")
            if cfg.mock:
                ui.badge("DEMO MODE: classification is fake", color="accent") \
                    .classes("text-black")
        with ui.row().classes("items-center gap-2"):
            gpu_chip = ui.chip("", icon="memory").props("outline dense").classes("text-white")
            queue_chip = ui.chip("", icon="schedule").props("outline dense").classes("text-white")
            if cfg.mock:  # laptop modes: let the user stop the server from the window
                ui.button(icon="power_settings_new", on_click=lambda: confirm_quit()) \
                    .props("flat round dense color=white").tooltip("Quit Pixel Muncher")

    def confirm_quit() -> None:
        with ui.dialog() as dlg, ui.card():
            ui.label("Quit Pixel Muncher?").classes("text-lg font-semibold")
            ui.label("This stops the app on this computer. Running jobs are stopped too.") \
                .classes("pxm-muted")
            with ui.row().classes("w-full justify-end"):
                ui.button("Keep open", on_click=dlg.close).props("flat")
                ui.button("Quit", color="negative", on_click=lambda: (
                    ui.notify("Pixel Muncher stopped. You can close this window."), app.shutdown()))
        dlg.open()

    def refresh_header() -> None:
        if cfg.inference.require_gpu:
            ok, desc = gpu_status()
            gpu_chip.text = f"GPU: {desc}" if ok else "GPU not available"
            gpu_chip.props(f"color={'white' if ok else 'red-3'}")
        else:
            gpu_chip.text = "GPU check off (demo)"
        jobs = store.list(50)
        running = sum(j.status == RUNNING for j in jobs)
        waiting = sum(j.status == QUEUED for j in jobs)
        queue_chip.text = f"{running} running, {waiting} waiting"

    ready = {"ok": False}

    def on_tab_change(e) -> None:
        if ready["ok"] and e.value == "New run":
            load_inputs()  # refresh file list, tile counts and checks

    with ui.tabs(on_change=on_tab_change).classes("w-full bg-white text-primary shadow-sm") as tabs:
        tab_new = ui.tab("New run", icon="play_circle")
        tab_runs = ui.tab("Runs", icon="list_alt")
        tab_help = ui.tab("Help", icon="help_outline")

    selected = {"job": None}

    with ui.tab_panels(tabs, value=tab_new).classes("w-full bg-transparent"):
        # =========================================================== NEW RUN
        with ui.tab_panel(tab_new):
            with ui.column().classes("w-full max-w-3xl mx-auto gap-4"):
                state: dict = {"inputs": [], "models": [], "tiles": None}

                # 1. orthomosaic
                with ui.card().classes("pxm-card"):
                    with ui.row().classes("items-center gap-3 w-full no-wrap"):
                        ui.html('<div class="pxm-step-num">1</div>')
                        ui.label("Choose the orthomosaic").classes("text-base font-semibold")
                        ui.space()
                        ui.button(icon="refresh", on_click=lambda: load_inputs()) \
                            .props("flat round dense").tooltip("Look for new files")
                    ui.label(f"Files are listed from {cfg.data_root}").classes("pxm-muted")
                    sel_input = ui.select({}, label="Orthomosaic (.tif)", with_input=True,
                                          on_change=lambda: on_input_change()) \
                        .classes("w-full").props("outlined")
                    tiles_label = ui.label("").classes("pxm-muted")
                    with ui.row().classes("items-center gap-4"):
                        sw_retile = ui.switch("Make tiles", on_change=lambda: update_checks())
                        orig_link = ui.link("View original map", "#", new_tab=True).classes("text-sm")
                    orig_link.visible = False

                # 2. model
                with ui.card().classes("pxm-card"):
                    with ui.row().classes("items-center gap-3"):
                        ui.html('<div class="pxm-step-num">2</div>')
                        ui.label("Choose the model").classes("text-base font-semibold")
                    sel_model = ui.select({}, label="Model", on_change=lambda: on_model_change()) \
                        .classes("w-full").props("outlined")
                    model_note = ui.label("").classes("pxm-muted")

                # 3. confidence
                with ui.card().classes("pxm-card"):
                    with ui.row().classes("items-center gap-3"):
                        ui.html('<div class="pxm-step-num">3</div>')
                        ui.label("Confidence (optional)").classes("text-base font-semibold")
                    sw_conf = ui.switch("Use a custom confidence threshold",
                                        on_change=lambda: (conf_row.set_visibility(sw_conf.value),
                                                           update_checks()))
                    with ui.row().classes("items-center w-full gap-4 no-wrap") as conf_row:
                        slider = ui.slider(min=0.80, max=0.99, step=0.01, value=0.95,
                                           on_change=lambda: update_checks()).classes("grow")
                        ui.label().bind_text_from(slider, "value", lambda v: f"{v:.2f}") \
                            .classes("text-lg font-mono w-12")
                    conf_row.visible = False
                    ui.label("Higher values only label pixels the model is very sure about, so "
                             "more pixels stay unclassified. Recommended range 0.80 to 0.99. "
                             "The value is saved with the results automatically.") \
                        .classes("pxm-muted")
                    note_input = ui.input("Note for this run (optional)",
                                          placeholder="e.g. comparison run for the team") \
                        .classes("w-full").props("outlined dense")

                # 4. checks + submit
                with ui.card().classes("pxm-card"):
                    with ui.row().classes("items-center gap-3"):
                        ui.html('<div class="pxm-step-num">4</div>')
                        ui.label("Check and start").classes("text-base font-semibold")
                    checks_box = ui.column().classes("w-full gap-1")
                    dest_label = ui.label("").classes("pxm-muted")
                    with ui.row().classes("w-full justify-end"):
                        submit_btn = ui.button("Add to queue", icon="play_arrow",
                                               on_click=lambda: submit()).props("size=lg")

                def current_input() -> InputInfo | None:
                    return next((i for i in state["inputs"] if str(i.path) == sel_input.value), None)

                def current_model() -> ModelInfo | None:
                    return next((m for m in state["models"] if str(m.path) == sel_model.value), None)

                def load_inputs(keep: str | None = None) -> None:
                    state["inputs"] = find_inputs(cfg)
                    sel_input.options = {str(i.path): i.label for i in state["inputs"]}
                    sel_input.update()
                    keep = keep or sel_input.value
                    if keep in sel_input.options:
                        sel_input.value = keep
                    elif state["inputs"]:
                        sel_input.value = str(state["inputs"][0].path)
                    on_input_change()

                def load_models() -> None:
                    state["models"] = find_models(cfg)
                    sel_model.options = {str(m.path): m.label for m in state["models"]}
                    sel_model.update()
                    if state["models"] and sel_model.value not in sel_model.options:
                        sel_model.value = str(state["models"][0].path)
                    on_model_change()

                def on_input_change() -> None:
                    inp = current_input()
                    if not inp:
                        tiles_label.text = "No orthomosaic selected." if state["inputs"] else \
                            f"No .tif files found in {cfg.data_root}."
                        state["tiles"] = None
                        orig_link.visible = False
                        update_checks()
                        return
                    ti = tile_info(cfg, inp)
                    state["tiles"] = ti
                    if ti.count:
                        when = ti.modified.strftime("%d %b %Y %H:%M") if ti.modified else ""
                        tiles_label.text = (f"Tiles already exist: {ti.count:,} tiles in "
                                            f"{inp.project}/{ti.path.name}/ (made {when}). "
                                            "Leave 'Make tiles' off to reuse them.")
                        sw_retile.value = False
                    else:
                        tiles_label.text = "No tiles yet. They will be made first (Manual 8.4.2)."
                        sw_retile.value = True
                    u = map_url(project=inp.project_dir) if ti.count else None
                    orig_link.visible = bool(u)
                    if u:
                        orig_link._props["href"] = u
                        orig_link.update()
                    update_checks()

                def on_model_change() -> None:
                    m = current_model()
                    if m:
                        parts = [m.architecture]
                        if m.note:
                            parts.append(m.note)
                        model_note.text = " · ".join(parts)
                    else:
                        model_note.text = f"No models found in {cfg.inference.models_dir}."
                    update_checks()

                def planned_job_dest(inp: InputInfo, m: ModelInfo, thr: float | None) -> Path:
                    fake = Job(id=0, created_at="", started_at=None, finished_at=None, status="",
                               project=inp.project, input_tif=str(inp.path), model_name=m.name,
                               model_path=str(m.path), threshold=thr, retile=False, tile_count=0,
                               progress=0, stage="")
                    return result_dir_for(cfg, fake)

                def update_checks() -> None:
                    inp, m = current_input(), current_model()
                    thr = round(slider.value, 2) if sw_conf.value else None
                    ti = state["tiles"]
                    dest = planned_job_dest(inp, m, thr) if inp and m else None
                    checks = run_checks(cfg, input_tif=inp.path if inp else None,
                                        model_json=m.path if m else None, threshold=thr,
                                        retile=bool(sw_retile.value),
                                        tile_count=ti.count if ti else 0,
                                        result_dir=dest)
                    if inp:
                        active = store.active_for_input(str(inp.path))
                        if active:
                            ids = ", ".join(f"#{j.id}" for j in active)
                            checks.append(Check(
                                "Already queued", WARN if not sw_retile.value else ERROR,
                                f"Job {ids} is already using this orthomosaic."
                                + (" Rebuilding tiles now would break it." if sw_retile.value else "")))
                    checks_box.clear()
                    with checks_box:
                        for c in checks:
                            icon, cls = CHECK_ICON[c.status]
                            with ui.row().classes("items-start gap-2 no-wrap"):
                                ui.icon(icon).classes(f"{cls} text-lg")
                                ui.label(c.label).classes("font-medium w-48 shrink-0")
                                ui.label(c.message).classes("pxm-muted break-all")
                    if dest:
                        rel = dest.relative_to(cfg.data_root) if dest.is_relative_to(cfg.data_root) else dest
                        dest_label.text = f"Results will be saved to: {rel}/ (exact time is set when the job starts)"
                    else:
                        dest_label.text = ""
                    submit_btn.enabled = not has_errors(checks)

                def submit() -> None:
                    inp, m = current_input(), current_model()
                    if not inp or not m:
                        return
                    update_checks()
                    if not submit_btn.enabled:
                        ui.notify("Fix the red items first.", type="negative")
                        return
                    thr = round(slider.value, 2) if sw_conf.value else None
                    ti = state["tiles"]
                    jid = store.add(project=inp.project, input_tif=str(inp.path), model_name=m.name,
                                    model_path=str(m.path), threshold=thr,
                                    retile=bool(sw_retile.value),
                                    tile_count=0 if sw_retile.value else (ti.count if ti else 0),
                                    submitted_by=client_ip, note=note_input.value or None)
                    worker.notify()
                    pos = store.queue_position(jid)
                    ui.notify(f"Job #{jid} added. Position in queue: {pos}.", type="positive")
                    note_input.value = ""
                    selected["job"] = jid
                    tabs.set_value(tab_runs)
                    refresh_runs(force=True)
                    show_details()

                def prefill(job: Job) -> None:
                    load_inputs(keep=job.input_tif)
                    if job.model_path in sel_model.options:
                        sel_model.value = job.model_path
                    sw_conf.value = job.threshold is not None
                    if job.threshold is not None:
                        slider.value = job.threshold
                    tabs.set_value(tab_new)
                    ui.notify(f"Settings copied from job #{job.id}. Check them and press Add to queue.")

        # =========================================================== RUNS
        with ui.tab_panel(tab_runs):
            with ui.column().classes("w-full max-w-6xl mx-auto gap-4"):
                columns = [
                    {"name": "id", "label": "#", "field": "id", "align": "left"},
                    {"name": "project", "label": "Project", "field": "project", "align": "left"},
                    {"name": "model", "label": "Model", "field": "model", "align": "left"},
                    {"name": "confidence", "label": "Confidence", "field": "confidence"},
                    {"name": "status", "label": "Status", "field": "status_text", "align": "left"},
                    {"name": "progress", "label": "Progress", "field": "progress", "align": "left"},
                    {"name": "submitted", "label": "Added", "field": "submitted"},
                    {"name": "duration", "label": "Time", "field": "duration"},
                ]
                table = ui.table(columns=columns, rows=[], row_key="id", pagination=10) \
                    .classes("w-full").props("flat bordered")
                table.add_slot("body-cell-status", """
                    <q-td :props="props"><q-badge :color="props.row.status_color"
                      :label="props.row.status_text" /></q-td>""")
                table.add_slot("body-cell-progress", """
                    <q-td :props="props" style="min-width:160px">
                      <q-linear-progress :value="props.row.progress/100" size="14px" rounded
                        :color="props.row.status_color" track-color="grey-3">
                        <div class="absolute-full flex flex-center">
                          <span style="font-size:10px">{{ props.row.progress }}%</span></div>
                      </q-linear-progress>
                      <div style="font-size:11px;color:#6b7570">{{ props.row.stage }}</div>
                    </q-td>""")
                table.on("rowClick", lambda e: select_job(e.args[1]["id"]))
                empty_label = ui.label("No runs yet. Start one from the 'New run' tab.") \
                    .classes("pxm-muted")
                details = ui.card().classes("pxm-card")
                details.visible = False

                runs_state = {"rows": None, "sig": None, "log_job": None, "offset": 0, "buf": ""}

                def refresh_runs(force: bool = False) -> None:
                    rows = job_rows()
                    if force or rows != runs_state["rows"]:
                        runs_state["rows"] = rows
                        table.rows = rows
                        table.update()
                    empty_label.visible = not rows

                def select_job(job_id: int) -> None:
                    selected["job"] = job_id
                    show_details()

                def show_details() -> None:
                    runs_state["sig"] = None
                    runs_state["log_job"] = None
                    details.clear()
                    jid = selected["job"]
                    job = store.get(jid) if jid else None
                    details.visible = bool(job)
                    if not job:
                        return
                    with details:
                        runs_state["status_box"] = ui.column().classes("w-full gap-2")
                        with ui.expansion("Log", icon="terminal", value=job.status != DONE) \
                                .classes("w-full"):
                            runs_state["log"] = ui.log(max_lines=3000).classes("pxm-log w-full")
                    tick_details()

                def render_status(job: Job) -> None:
                    box = runs_state["status_box"]
                    box.clear()
                    with box:
                        with ui.row().classes("items-center gap-3 w-full"):
                            ui.label(f"Job #{job.id}").classes("text-lg font-semibold")
                            ui.badge(STATUS_TEXT[job.status], color=STATUS_COLOR[job.status])
                            ui.space()
                            if job.status in ACTIVE:
                                ui.button("Cancel", icon="stop", color="negative",
                                          on_click=lambda j=job: confirm_cancel(j)).props("outline")
                            ui.button("Run again", icon="replay",
                                      on_click=lambda j=job: prefill(j)).props("flat")
                        with ui.grid(columns=2).classes("w-full gap-x-6 gap-y-1 text-sm"):
                            for k, v in [("Orthomosaic", job.input_tif), ("Model", job.model_name),
                                         ("Confidence", job.threshold_label),
                                         ("Tiles", f"{job.tile_count:,}" if job.tile_count else "-"),
                                         ("Added", f"{fmt_time(job.created_at)} from {job.submitted_by}"),
                                         ("Time", fmt_duration(job.duration_seconds()) or "-")]:
                                with ui.row().classes("gap-2 no-wrap"):
                                    ui.label(k).classes("pxm-muted w-24 shrink-0")
                                    ui.label(v).classes("break-all")
                            if job.note:
                                with ui.row().classes("gap-2 no-wrap"):
                                    ui.label("Note").classes("pxm-muted w-24 shrink-0")
                                    ui.label(job.note)
                        if job.status == QUEUED:
                            ui.label(f"Waiting in queue, position {store.queue_position(job.id)}. "
                                     "Jobs run one at a time because they share the GPU.") \
                                .classes("pxm-muted")
                        # steps
                        with ui.row().classes("w-full gap-6 items-center"):
                            for s in job.steps:
                                icon, color = STEP_ICON.get(s["status"], STEP_ICON["pending"])
                                with ui.row().classes("items-center gap-1 no-wrap"):
                                    i = ui.icon(icon, color=color).classes("text-xl")
                                    if s["status"] == "running":
                                        i.classes("animate-spin")
                                    ui.label(s["name"]).classes(
                                        "font-medium" if s["status"] == "running" else "")
                        if job.status == RUNNING:
                            with ui.row().classes("w-full items-center gap-3 no-wrap"):
                                ui.linear_progress(value=job.progress, show_value=False, size="12px") \
                                    .classes("grow")
                                ui.label(f"{job.progress * 100:.0f}%").classes("font-mono")
                                ui.label(eta_text(job)).classes("pxm-muted w-40")
                        if job.status == FAILED and job.error:
                            with ui.card().classes("w-full bg-red-1"):
                                with ui.row().classes("items-start gap-2 no-wrap"):
                                    ui.icon("error", color="negative").classes("text-xl")
                                    ui.label(job.error).classes("text-red-10")
                        if job.status == DONE and job.result_dir:
                            rd = Path(job.result_dir)
                            with ui.card().classes("w-full bg-green-1"):
                                ui.label("Results saved").classes("font-semibold")
                                ui.label(str(rd)).classes("font-mono text-xs break-all")
                                with ui.row().classes("gap-2"):
                                    u = map_url(result=rd)
                                    if u:
                                        ui.button("Open map", icon="map",
                                                  on_click=lambda u=u: ui.navigate.to(u, new_tab=True)) \
                                            .tooltip("Classification over the orthomosaic, with an "
                                                     "opacity slider. Works offline.")
                                    ol = url_for(rd / "openlayers.html") \
                                        if (rd / "openlayers.html").exists() else None
                                    if ol:
                                        ui.button("OpenLayers viewer", icon="public",
                                                  on_click=lambda u=ol: ui.navigate.to(u, new_tab=True)) \
                                            .props("outline").tooltip("gdal2tiles viewer (needs internet)")
                                    um = url_for(rd / "run_manifest.json")
                                    if um:
                                        ui.button("Run record", icon="description",
                                                  on_click=lambda u=um: ui.navigate.to(u, new_tab=True)) \
                                            .props("flat")
                                    ui.button("Copy folder path", icon="content_copy",
                                              on_click=lambda p=str(rd): (ui.clipboard.write(p),
                                                                          ui.notify("Path copied"))) \
                                        .props("flat")

                def tick_details() -> None:
                    jid = selected["job"]
                    if not jid or "status_box" not in runs_state:
                        return
                    job = store.get(jid)
                    if not job:
                        return
                    sig = (job.status, round(job.progress, 3), job.stage, str(job.steps), job.error,
                           job.result_dir, store.queue_position(jid) if job.status == QUEUED else 0,
                           int((job.duration_seconds() or 0) // 5))
                    if sig != runs_state["sig"]:
                        runs_state["sig"] = sig
                        render_status(job)
                    tail_log(jid)

                def tail_log(jid: int) -> None:
                    path = worker.log_path(jid)
                    log = runs_state.get("log")
                    if log is None:
                        return
                    if runs_state["log_job"] != jid:
                        runs_state.update(log_job=jid, offset=0, buf="")
                        log.clear()
                        if path.exists() and path.stat().st_size > 400_000:
                            runs_state["offset"] = path.stat().st_size - 400_000
                            log.push("... (older lines hidden, full log in "
                                     f"{path})")
                    if not path.exists():
                        return
                    with open(path, "rb") as fh:
                        fh.seek(runs_state["offset"])
                        data = fh.read(400_000)
                    if not data:
                        return
                    runs_state["offset"] += len(data)
                    text = runs_state["buf"] + data.decode("utf-8", errors="replace")
                    lines = text.split("\n")
                    runs_state["buf"] = lines.pop()
                    for line in lines:
                        if line.strip():
                            log.push(line)

                def confirm_cancel(job: Job) -> None:
                    with ui.dialog() as dlg, ui.card():
                        ui.label(f"Cancel job #{job.id}?").classes("text-lg font-semibold")
                        ui.label("A running job is stopped immediately. Partial output stays in "
                                 "the Pixel Muncher results folder and is not copied.") \
                            .classes("pxm-muted")
                        with ui.row().classes("w-full justify-end"):
                            ui.button("Keep running", on_click=dlg.close).props("flat")
                            ui.button("Cancel job", color="negative",
                                      on_click=lambda: (worker.cancel(job.id), dlg.close(),
                                                        ui.notify(f"Cancelling job #{job.id}")))
                    dlg.open()

        # =========================================================== HELP
        with ui.tab_panel(tab_help):
            with ui.column().classes("w-full max-w-3xl mx-auto gap-4"):
                with ui.card().classes("pxm-card"):
                    ui.markdown(HELP_TEXT)
                with ui.card().classes("pxm-card"):
                    ui.label("System").classes("text-base font-semibold")
                    ok, desc = gpu_status()
                    rows = [
                        ("Config file", str(cfg.path)),
                        ("Data folder", str(cfg.data_root)),
                        ("Models folder", str(cfg.inference.models_dir)),
                        ("Pixel Muncher", str(cfg.inference.workdir)),
                        ("Raw results", str(cfg.inference.results_dir)),
                        ("Result layout", cfg.results_layout),
                        ("GPU", desc if cfg.inference.require_gpu else "check disabled"),
                        ("Job history", str(cfg.db_path)),
                        ("Mode", "DEMO (fake tools)" if cfg.mock else "Production"),
                    ]
                    for k, v in rows:
                        with ui.row().classes("gap-2 no-wrap text-sm"):
                            ui.label(k).classes("pxm-muted w-32 shrink-0")
                            ui.label(v).classes("font-mono break-all")

    def tick() -> None:
        refresh_header()
        refresh_runs()
        tick_details()

    load_inputs()
    load_models()
    refresh_header()
    refresh_runs()
    ready["ok"] = True
    ui.timer(1.0, tick)


@ui.page("/map")
def map_page(result: str = "", project: str = "") -> None:
    import json as _json
    ui.add_head_html(APP_HEAD)
    ui.colors(primary="#2f6b4f")
    zoom = cfg.tiling.zoom
    class_dir = safe_data_path(result) if result else None
    ortho_dir = safe_data_path(project) if project else None
    title = ""
    if class_dir:
        title = class_dir.name
        manifest = class_dir / "run_manifest.json"
        if manifest.exists():
            inp = Path(_json.loads(manifest.read_text())["input"]["orthomosaic"])
            cand = inp.parent.resolve()
            if cand.is_relative_to(cfg.data_root):
                ortho_dir = cand
    elif ortho_dir:
        title = f"{ortho_dir.name} (orthomosaic tiles)"
    bounds = None
    for d in (ortho_dir, class_dir):
        if d and bounds is None:
            bounds = tile_bounds(d / str(zoom), zoom)
    with ui.header().classes("items-center bg-primary px-4 py-2 gap-3"):
        ui.icon("map", size="24px")
        ui.label(title or "Map").classes("text-base font-semibold")
    if bounds is None:
        ui.label("No tiles found for this map.").classes("p-6 text-lg")
        return
    s, w, n, e = bounds
    tile_opts = {"tms": True, "minNativeZoom": zoom, "maxNativeZoom": zoom,
                 "minZoom": zoom - 6, "maxZoom": zoom + 2, "bounds": [[s, w], [n, e]]}
    with ui.row().classes("w-full items-center gap-6 px-2"):
        sw_base = ui.switch("Street map background (needs internet)", value=False)
        sw_ortho = ui.switch("Orthomosaic", value=bool(ortho_dir))
        if class_dir:
            ui.label("Classification opacity").classes("text-sm")
            op = ui.slider(min=0, max=1, step=0.05, value=0.7).classes("w-48")
    m = ui.leaflet(center=((s + n) / 2, (w + e) / 2), zoom=zoom - 3,
                   options={"maxZoom": zoom + 2, "minZoom": zoom - 6, "zoomSnap": 0.25}) \
        .classes("w-full").style("height: calc(100vh - 150px)")
    m.clear_layers()
    base = m.tile_layer(url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                        options={"maxNativeZoom": 19, "maxZoom": zoom + 2, "opacity": 0,
                                 "attribution": "&copy; OpenStreetMap contributors"})
    ortho = m.tile_layer(url_template=url_for(ortho_dir) + "/{z}/{x}/{y}.png",
                         options=tile_opts) if ortho_dir else None
    cls = m.tile_layer(url_template=url_for(class_dir) + "/{z}/{x}/{y}.png",
                       options={**tile_opts, "opacity": 0.7}) if class_dir else None
    sw_base.on_value_change(lambda e: base.run_method("setOpacity", 1 if e.value else 0))
    if ortho:
        sw_ortho.on_value_change(lambda e: ortho.run_method("setOpacity", 1 if e.value else 0))
    if cls:
        op.on_value_change(lambda e: cls.run_method("setOpacity", e.value))
    ui.timer(0.8, lambda: m.run_map_method("fitBounds", [[s, w], [n, e]]), once=True)
    if cfg.mock and class_dir:
        with ui.row().classes("w-full gap-4 px-2 text-xs items-center"):
            ui.label("Demo legend (fake classes):").classes("font-semibold")
            for name, colour in DEMO_CLASSES:
                with ui.row().classes("items-center gap-1"):
                    ui.element("div").style(f"width:12px;height:12px;background:rgb{colour}")
                    ui.label(name)


DEMO_CLASSES = [("Class A", (230, 159, 0)), ("Class B", (86, 180, 233)),
                ("Class C", (0, 158, 115)), ("Class D", (240, 228, 66)),
                ("Class E", (204, 121, 167)), ("Other", (120, 120, 120))]


HELP_TEXT = """
### How a run works

1. **Choose the orthomosaic.** Any `.tif` inside the data folder is listed. The project name
   is the folder it sits in, for example `SiteA`.
2. **Tiles.** The image is cut into small tiles (Manual 8.4.2). If tiles already exist they are
   reused, which saves time. Turn on *Make tiles* only if the orthomosaic changed.
3. **Choose the model.** The recommended model is selected by default (Manual 8.4.5).
4. **Confidence** is optional. Leave it off to use the model's own default.
5. **Add to queue.** Jobs run one at a time because they share one GPU. You can close the
   browser; the job keeps running on the workstation.

### Where results go

`<Project>_Result/<date>_<model>_<confidence>/` next to the project folder, containing:

* `23/` classified tiles
* `openlayers.html` gdal2tiles map viewer (needs internet). *Open map* in the app works offline
* `log.log` from Pixel Muncher
* `model_config/` copy of the model file used
* `run_manifest.json` full record of the run: who, when, which model, which settings and the
  exact commands (Manual 8.8 traceability)

### Put Pixel Muncher on your desktop

In **Microsoft Edge**: menu `...` > *Apps* > *Install this site as an app* > *Install*, then tick
*Pin to taskbar* and *Create desktop shortcut*. In **Google Chrome**: menu `⋮` >
*Cast, save and share* > *Create shortcut*, tick *Open as window*. Pixel Muncher then opens in its
own window from the Start menu, taskbar or desktop.

### When something fails

* Red items in step 4 explain what to fix before starting.
* If a running job fails, the red box in *Runs* says why and the *Log* shows the details.
* GPU out of memory: wait for other GPU work to finish, then use *Run again*.
* Tell the processing lead if a path in the System box below is wrong.
"""


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(host=cfg.host, port=cfg.port, title=cfg.title, reload=False, show=False,
           favicon=HERE / "assets" / "icon-64.png", show_welcome_message=True)
