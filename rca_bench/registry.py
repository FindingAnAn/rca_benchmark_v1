"""Local lifecycle registry. It records review; it never deploys or remediates."""
import sqlite3
from contextlib import contextmanager
from .io import canonical, stamp


@contextmanager
def connect(path):
    db = sqlite3.connect(path)
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, status TEXT, manifest TEXT, updated_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY, run_id TEXT, decision TEXT, reviewer TEXT, reason TEXT, created_at TEXT)")
            yield db
    finally:
        db.close()


def record(path, run_id, status, manifest):
    with connect(path) as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, manifest=excluded.manifest, updated_at=excluded.updated_at",
                   (run_id, status, canonical(manifest), stamp()))


def review(path, run_id, decision, reviewer, reason):
    if decision not in ["research", "shadow_requested", "rejected"] or not reviewer.strip() or not reason.strip():
        raise ValueError("Review requires reviewer/reason and research/shadow_requested/rejected")
    with connect(path) as db:
        row = db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row or row[0] not in ["COMPLETED", "PARTIAL"]:
            raise ValueError("Review a completed run only")
        db.execute("INSERT INTO reviews (run_id,decision,reviewer,reason,created_at) VALUES (?,?,?,?,?)",
                   (run_id,decision,reviewer,reason,stamp()))


def list_runs(path):
    with connect(path) as db:
        return [dict(zip(["run_id","status","updated_at"],r)) for r in db.execute("SELECT run_id,status,updated_at FROM runs ORDER BY updated_at DESC")]
