"""Persistent, append-audited human labels for one frozen screening batch."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

VERDICTS = {"correct", "missing", "incorrect", "uncertain"}


class ReviewStore:
    def __init__(self, path: Path, allowed_targets: dict[str, str]) -> None:
        self.path = path
        self.allowed_targets = allowed_targets
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS reviews (
                    target_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    note TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (target_id, reviewer)
                );
                CREATE TABLE IF NOT EXISTS review_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def list(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT target_id,item_id,reviewer,verdict,note,updated_at "
                "FROM reviews ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def save(self, target_id: str, item_id: str, reviewer: str,
             verdict: str, note: str) -> dict:
        target_id = target_id.strip()
        item_id = item_id.strip()
        reviewer = reviewer.strip()
        note = note.strip()
        if self.allowed_targets.get(target_id) != item_id:
            raise ValueError("unknown_review_target")
        if not item_id or not reviewer or len(reviewer) > 80:
            raise ValueError("item_id_and_reviewer_required")
        if verdict not in VERDICTS:
            raise ValueError("invalid_verdict")
        if len(note) > 2000:
            raise ValueError("note_too_long")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO reviews VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(target_id,reviewer) DO UPDATE SET "
                "verdict=excluded.verdict,note=excluded.note,updated_at=excluded.updated_at",
                (target_id, item_id, reviewer, verdict, note, now),
            )
            db.execute(
                "INSERT INTO review_audit(target_id,item_id,reviewer,verdict,note,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (target_id, item_id, reviewer, verdict, note, now),
            )
        return {"target_id": target_id, "item_id": item_id, "reviewer": reviewer,
                "verdict": verdict, "note": note, "updated_at": now}
