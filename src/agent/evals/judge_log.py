# src/agent/evals/judge_log.py
"""Append-only JSONL log of every RAGAS judge LLM call (prompt and raw reply)."""

from __future__ import annotations

import json
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_current_metric: ContextVar[str | None] = ContextVar("judge_log_metric", default=None)


@dataclass
class JudgeCallLog:
    """One JSON object per line: eval context, RAGAS metric, prompt, and the judge's reply text."""

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _eval_run_id: str = ""
    _scenario_id: str = ""
    _repeat: int = 0
    _judge_model: str = ""
    _call_index: int = 0

    def begin_scenario_run(
        self,
        *,
        eval_run_id: str,
        scenario_id: str,
        repeat: int,
        judge_model: str,
    ) -> None:
        self._eval_run_id = eval_run_id
        self._scenario_id = scenario_id
        self._repeat = repeat
        self._judge_model = judge_model
        self._call_index = 0

    def set_metric(self, metric: str | None):
        return _current_metric.set(metric)

    def reset_metric(self, token) -> None:
        _current_metric.reset(token)

    def record(self, *, prompt: str, response: str) -> None:
        self._call_index += 1
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "eval_run_id": self._eval_run_id,
            "scenario_id": self._scenario_id,
            "repeat": self._repeat,
            "judge_model": self._judge_model,
            "metric": _current_metric.get(),
            "call_index": self._call_index,
            "prompt": prompt,
            "response": response,
        }
        line = json.dumps(row, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")