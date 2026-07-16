"""Peer-correspondence ownership contract."""

from typing import Any, Dict, Protocol


class CorrespondenceRuntime(Protocol):
    def _correspondence_status_text(self) -> str: ...

    def _correspondence_record_read_receipt(
        self, message: Dict[str, Any]
    ) -> Dict[str, Any]: ...

    def _peer_correspondence(self, state: Dict[str, float]) -> None: ...


__all__ = ["CorrespondenceRuntime"]
