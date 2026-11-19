# src/agent/memory/episodic.py
"""
Episodic memory — persists every agent run to a local SQLite DB.

Each row in `runs` captures: what the user asked, what the agent answered,
which tools were called, token usage, cost, and the run outcome.
A row with a thread_id is its Conversation's one entry, replaced each time it is logged again.
Past runs are searched with FTS5 (BM25 ranking) over user_input and final_output.
"""

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent.config import settings

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class RunRecord:
    user_input: str
    final_output: str
    tools_called: list[str] = field(default_factory=list)
    token_usage: dict | None = None  # keys: prompt, completion, total
    cost_usd: float | None = None
    outcome: str = "completed"  # completed | error | rejected | step limit (ticket 20)
    error_message: str | None = None
    thread_id: str | None = None  # the Conversation's; its entry is replaced at each session's exit
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _fts_match_query(terms: str) -> str | None:
    """Turn agent-written search terms into an FTS5 MATCH expression (whole tokens, quoted)."""
    terms = terms.strip()
    if not terms:
        return None
    parts = []
    for token in terms.split():
        escaped = token.replace('"', '""')
        parts.append(f'"{escaped}"')
    return " ".join(parts)


def _normalize_since(value: str | None) -> str | None:
    if value is None or not (value := value.strip()):
        return None
    if _DATE_ONLY.match(value):
        return f"{value}T00:00:00+00:00"
    return value


def _normalize_until(value: str | None) -> str | None:
    if value is None or not (value := value.strip()):
        return None
    if _DATE_ONLY.match(value):
        return f"{value}T23:59:59.999999+00:00"
    return value


class EpisodicMemory:
    def __init__(self, db_path: str | None = None):
        path = Path(db_path or settings.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_table()
        self._migrate_schema()
        self._ensure_fts()

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
        if "thread_id" not in cols:
            # Rows logged before Conversations had ids keep NULL: each stays its own entry.
            self._conn.execute("ALTER TABLE runs ADD COLUMN thread_id TEXT")
            self._conn.commit()

    def _ensure_fts(self) -> None:
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS runs_fts USING fts5(
                user_input,
                final_output
            )
        """)
        self._conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS runs_ai AFTER INSERT ON runs BEGIN
              INSERT INTO runs_fts(rowid, user_input, final_output)
              VALUES (new.rowid, new.user_input, new.final_output);
            END;
            -- runs_fts keeps its own content, so the FTS5 'delete' command fails on it: delete
            -- the row instead. Recreated so databases with the old trigger get this one.
            DROP TRIGGER IF EXISTS runs_ad;
            CREATE TRIGGER runs_ad AFTER DELETE ON runs BEGIN
              DELETE FROM runs_fts WHERE rowid = old.rowid;
            END;
        """)
        run_count = self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        fts_count = self._conn.execute("SELECT COUNT(*) FROM runs_fts").fetchone()[0]
        if run_count > fts_count:
            for row in self._conn.execute(
                "SELECT rowid, user_input, final_output FROM runs"
            ):
                self._conn.execute(
                    "INSERT INTO runs_fts(rowid, user_input, final_output) VALUES (?, ?, ?)",
                    tuple(row),
                )
        self._conn.commit()

    def log_run(self, run: RunRecord) -> str:
        """Insert a new run record, replacing its Conversation's earlier entry. Returns the run_id.

        The replacing entry keeps the errors of the Conversation's earlier sessions: they are not
        in the thread, so the new record could not know them."""
        if run.thread_id is not None:
            earlier = self._conn.execute(
                "SELECT error_message FROM runs WHERE thread_id = ? AND error_message IS NOT NULL",
                (run.thread_id,),
            ).fetchone()
            if earlier is not None:
                run.error_message = "; ".join(e for e in (earlier[0], run.error_message) if e)
                run.outcome = "error"
            self._conn.execute("DELETE FROM runs WHERE thread_id = ?", (run.thread_id,))
        self._conn.execute(
            """INSERT INTO runs
               (id, timestamp, user_input, final_output, tools_called,
                token_usage, cost_usd, outcome, error_message, thread_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                run.thread_id,
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

    def search_runs(
        self,
        terms: str,
        n: int = 5,
        since: str | None = None,
        until: str | None = None,
    ) -> list[RunRecord]:
        """FTS5 search over user_input and final_output, ranked by BM25, optional date bounds."""
        match = _fts_match_query(terms)
        if match is None:
            return []

        since_bound = _normalize_since(since)
        until_bound = _normalize_until(until)
        clauses = ["runs_fts MATCH ?"]
        params: list[object] = [match]
        if since_bound is not None:
            clauses.append("r.timestamp >= ?")
            params.append(since_bound)
        if until_bound is not None:
            clauses.append("r.timestamp <= ?")
            params.append(until_bound)
        params.append(n)

        cursor = self._conn.execute(
            f"""SELECT r.* FROM runs r
                INNER JOIN runs_fts ON runs_fts.rowid = r.rowid
                WHERE {" AND ".join(clauses)}
                ORDER BY bm25(runs_fts)
                LIMIT ?""",
            params,
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        keys = row.keys()
        outcome = row["outcome"] if "outcome" in keys else "completed"
        if outcome is None and "success" in keys:
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
            thread_id=row["thread_id"] if "thread_id" in keys else None,
        )

    def close(self) -> None:
        self._conn.close()
