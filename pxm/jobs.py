"""Persistent job queue (SQLite). Survives server restarts."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
ACTIVE = (QUEUED, RUNNING)

STEP_NAMES = ["Checks", "Make tiles", "Classify", "Save results"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    status        TEXT NOT NULL,
    project       TEXT NOT NULL,
    input_tif     TEXT NOT NULL,
    model_name    TEXT NOT NULL,
    model_path    TEXT NOT NULL,
    threshold     REAL,
    retile        INTEGER NOT NULL,
    tile_count    INTEGER NOT NULL DEFAULT 0,
    progress      REAL NOT NULL DEFAULT 0,
    stage         TEXT NOT NULL DEFAULT '',
    steps         TEXT NOT NULL DEFAULT '[]',
    result_dir    TEXT,
    error         TEXT,
    submitted_by  TEXT,
    note          TEXT
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Job:
    id: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    status: str
    project: str
    input_tif: str
    model_name: str
    model_path: str
    threshold: float | None
    retile: bool
    tile_count: int
    progress: float
    stage: str
    steps: list[dict] = field(default_factory=list)
    result_dir: str | None = None
    error: str | None = None
    submitted_by: str | None = None
    note: str | None = None

    @property
    def threshold_label(self) -> str:
        return "default" if self.threshold is None else f"{self.threshold:.2f}"

    def duration_seconds(self) -> float | None:
        if not self.started_at:
            return None
        end = datetime.fromisoformat(self.finished_at) if self.finished_at else datetime.now()
        return (end - datetime.fromisoformat(self.started_at)).total_seconds()


def _row_to_job(row: sqlite3.Row) -> Job:
    d = dict(row)
    d["retile"] = bool(d["retile"])
    d["steps"] = json.loads(d["steps"] or "[]")
    return Job(**d)


class JobStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def add(self, *, project: str, input_tif: str, model_name: str, model_path: str,
            threshold: float | None, retile: bool, tile_count: int,
            submitted_by: str | None = None, note: str | None = None) -> int:
        steps = [{"name": n, "status": "pending"} for n in STEP_NAMES]
        if not retile:
            steps[1]["status"] = "skipped"
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO jobs (created_at, status, project, input_tif, model_name, model_path,"
                " threshold, retile, tile_count, steps, submitted_by, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (now(), QUEUED, project, input_tif, model_name, model_path, threshold,
                 int(retile), tile_count, json.dumps(steps), submitted_by, note),
            )
            return int(cur.lastrowid)

    def get(self, job_id: int) -> Job | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list(self, limit: int = 200) -> list[Job]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_job(r) for r in rows]

    def active_for_input(self, input_tif: str) -> list[Job]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM jobs WHERE input_tif=? AND status IN (?,?)", (input_tif, *ACTIVE)
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def queue_position(self, job_id: int) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status=? AND id<?", (QUEUED, job_id)
            ).fetchone()
        return int(row[0]) + 1

    def claim_next(self) -> Job | None:
        """Atomically move the oldest queued job to running."""
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM jobs WHERE status=? ORDER BY id LIMIT 1", (QUEUED,)
            ).fetchone()
            if not row:
                return None
            self._db.execute(
                "UPDATE jobs SET status=?, started_at=?, stage=? WHERE id=?",
                (RUNNING, now(), "Starting", row["id"]),
            )
        return self.get(row["id"])

    def update(self, job_id: int, **fields) -> None:
        if not fields:
            return
        if "steps" in fields:
            fields["steps"] = json.dumps(fields["steps"])
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def cancel_if_queued(self, job_id: int) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE jobs SET status=?, finished_at=?, stage=? WHERE id=? AND status=?",
                (CANCELLED, now(), "Cancelled before start", job_id, QUEUED),
            )
            return cur.rowcount > 0

    def recover_interrupted(self) -> int:
        """Jobs left 'running' by a crash or restart are marked failed."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE jobs SET status=?, finished_at=?, error=? WHERE status=?",
                (FAILED, now(), "Interrupted: the app was restarted while this job was running. "
                 "Re-run it.", RUNNING),
            )
            return cur.rowcount
