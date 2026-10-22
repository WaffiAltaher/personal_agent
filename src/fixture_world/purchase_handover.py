# src/fixture_world/purchase_handover.py
"""Recording fake for Purchase invoice hand-over in the Fixture world."""


class RecordingHandover:
    """Keeps successful uploads and can be told to fail on the next attempt."""

    def __init__(self, fail_with: str | None = None) -> None:
        self.fail_with = fail_with
        self.uploads: list[tuple[str, bytes]] = []
        self.attempts = 0

    async def hand_over(self, file_name: str, content: bytes) -> None:
        self.attempts += 1
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        self.uploads.append((file_name, content))
