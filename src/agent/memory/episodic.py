# src/agent/memory/episodic.py
"""
Episodic memory — persists every agent run to a local SQLite DB.

Each row in `runs` captures: what the user asked, what the agent answered,
which tools were called, token usage, cost, and the run outcome.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent.config import settings


@dataclass
class RunRecord:
    user_input: str
    final_output: str
    tools_called: list[str] = field(default_factory=list)
    token_usage: dict | None = None  # keys: prompt, completion, total
    cost_usd: float | None = None
    outcome: str = "completed"  # completed | error | rejected (step_limit in ticket 20)
    error_message: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EpisodicMemory:
    def __init__(self, db_path: str | None = None):
        path = Path(db_path or settings.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_table()
        self._migrate_schema()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id            TEXT PRIMARY KEY,
                timestamp     TEXT NOT NULL,
                user_input    TEXT NOT NULL,
                final_output  TEXT NOT NULL,
                tools_called  TEXT NOT NULL DEFAULT '[]',
                token_usage   TEXT,
                cost_usd      REAL,
                outcome       TEXT NOT NULL DEFAULT 'completed',
                error_message TEXT
            )
        """)
        self._conn.commit()

    def _migrate_schema(self) -> None:
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
        if "outcome" not in cols:
            self._conn.execute(
                "ALTER TABLE runs ADD COLUMN outcome TEXT NOT NULL DEFAULT 'completed'"
            )
            if "success" in cols:
                self._conn.execute(
                    """UPDATE runs SET outcome = CASE WHEN success = 0 THEN 'error' ELSE 'completed' END"""
                )
            self._conn.commit()

    def log_run(self, run: RunRecord) -> str:
        """Insert a new run record. Returns the run_id."""
        self._conn.execute(
            """INSERT INTO runs
               (id, timestamp, user_input, final_output, tools_called,
                token_usage, cost_usd, outcome, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.id,
                run.timestamp,
                run.user_input,
                run.final_output,
                json.dumps(run.tools_called),
                json.dumps(run.token_usage) if run.token_usage is not None else None,
                run.cost_usd,
                run.outcome,
                run.error_message,
            ),
        )
        self._conn.commit()
        return run.id

    def get_recent_runs(self, n: int = 10) -> list[RunRecord]:
        """Return the n most recent runs, newest first."""
        cursor = self._conn.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (n,)
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def search_runs(self, query: str, n: int = 5) -> list[RunRecord]:
        """LIKE search over user_input and final_output, newest first."""
        like = f"%{query}%"
        cursor = self._conn.execute(
            """SELECT * FROM runs
               WHERE user_input LIKE ? OR final_output LIKE ?
               ORDER BY timestamp DESC LIMIT ?""",
            (like, like, n),
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        outcome = row["outcome"] if "outcome" in row.keys() else "completed"
        if outcome is None and "success" in row.keys():
            outcome = "completed" if row["success"] else "error"
        return RunRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            user_input=row["user_input"],
            final_output=row["final_output"],
            tools_called=json.loads(row["tools_called"]),
            token_usage=json.loads(row["token_usage"]) if row["token_usage"] else None,
            cost_usd=row["cost_usd"],
            outcome=outcome or "completed",
            error_message=row["error_message"],
        )

    def close(self) -> None:
        self._conn.close()
