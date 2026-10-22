# src/fixture_world/purchase_handover.py
"""Recording fake for Purchase invoice hand-over in the Fixture world."""

import base64
import json
from pathlib import Path

UPLOAD_LOG_ENV = "FIXTURE_WORLD_PURCHASE_UPLOAD_LOG"
HANDOVER_FAIL_ENV = "FIXTURE_WORLD_PURCHASE_HANDOVER_FAIL"


class RecordingHandover:
    """Keeps successful uploads and can be told to fail on the next attempt."""

    def __init__(
        self,
        fail_with: str | None = None,
        *,
        log_path: Path | None = None,
    ) -> None:
        self.fail_with = fail_with
        self.log_path = log_path
        self.uploads: list[tuple[str, bytes]] = []
        self.attempts = 0

    async def hand_over(self, file_name: str, content: bytes) -> None:
        self.attempts += 1
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        self.uploads.append((file_name, content))
        if self.log_path is not None:
            line = json.dumps({"file_name": file_name, "content_b64": base64.b64encode(content).decode()})
            with self.log_path.open("a") as handle:
                handle.write(line + "\n")


def handover_from_environment() -> RecordingHandover:
    """Hand-over fake for one Informer MCP process (may share a log file across processes)."""
    import os

    log = os.environ.get(UPLOAD_LOG_ENV)
    fail = os.environ.get(HANDOVER_FAIL_ENV)
    return RecordingHandover(fail_with=fail, log_path=Path(log) if log else None)
