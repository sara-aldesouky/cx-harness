"""Small in-memory audit recorder for pure executor unit tests."""

from uuid import UUID, uuid4


class RecordingAuditRepository:
    """Record executor audit calls without requiring a database."""

    def __init__(self) -> None:
        self.started: list[dict[str, object]] = []
        self.finalized: list[dict[str, object]] = []

    def create_running(self, **values: object) -> UUID:
        tool_call_id = uuid4()
        self.started.append({"tool_call_id": tool_call_id, **values})
        return tool_call_id

    def finalize(self, tool_call_id: UUID, **values: object) -> None:
        self.finalized.append({"tool_call_id": tool_call_id, **values})
