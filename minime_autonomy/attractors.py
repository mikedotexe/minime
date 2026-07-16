"""Attractor parsing and lifecycle ownership contract."""

from typing import Any, Dict, Protocol

from .parsing import (
    clean_gesture_label,
    parse_bridge_trace_next_request,
    parse_reconvergence_next_request,
)


class AttractorRuntime(Protocol):
    def _build_attractor_atlas(self) -> Dict[str, Any]: ...

    def _attractor_intent(self, state: Dict[str, float]) -> None: ...

    def _release_attractor(self, state: Dict[str, float]) -> None: ...


__all__ = [
    "AttractorRuntime",
    "clean_gesture_label",
    "parse_bridge_trace_next_request",
    "parse_reconvergence_next_request",
]
