# src/agent/evals/outcome.py
"""Outcome metrics: what actually happened (uploads recorded, failure reported), not just tool calls."""

import base64
import json
from pathlib import Path

from agent.evals.records import OutcomeScore, TrajectoryScore
from agent.evals.scenarios import Scenario


def read_upload_log(path: Path | None) -> list[tuple[str, bytes]]:
    """Successful Purchase invoice uploads appended by the Fixture world's hand-over log."""
    if path is None or not path.is_file():
        return []
    uploads: list[tuple[str, bytes]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        uploads.append((record["file_name"], base64.b64decode(record["content_b64"])))
    return uploads


def score_outcome(
    scenario: Scenario,
    uploads: list[tuple[str, bytes]],
    *,
    final_answer: str,
    expected_bytes: dict[str, bytes] | None = None,
) -> OutcomeScore:
    """Grade uploads and, when required, whether the answer reports a hand-over failure."""
    expected = scenario.expected_outcome
    if expected is None:
        return OutcomeScore(applicable=False, passed=True)

    passed = len(uploads) == expected.upload_count
    detail_parts: list[str] = []
    if not passed:
        detail_parts.append(f"expected {expected.upload_count} upload(s), got {len(uploads)}")

    if expected.upload_file is not None and len(uploads) == 1:
        name, content = uploads[0]
        if name != expected.upload_file:
            passed = False
            detail_parts.append(f"expected file {expected.upload_file!r}, got {name!r}")
        elif expected_bytes and (want := expected_bytes.get(expected.upload_file)) is not None:
            if content != want:
                passed = False
                detail_parts.append("upload bytes do not match the expected file")

    if expected.require_failure_reported:
        answer = final_answer.lower()
        if not any(fragment.lower() in answer for fragment in scenario.expected_facts):
            passed = False
            detail_parts.append("final answer does not report the upload failure")

    return OutcomeScore(
        applicable=True,
        passed=passed,
        upload_count=len(uploads),
        uploads=[name for name, _ in uploads],
        detail="; ".join(detail_parts),
    )


def run_passed(scenario: Scenario, trajectory: TrajectoryScore, outcome: OutcomeScore) -> bool:
    """Whether the run passes trajectory checks and, when declared, the outcome grade."""
    if not trajectory.passed:
        return False
    if scenario.expected_outcome is not None:
        return outcome.passed
    return True
