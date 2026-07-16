"""Memory-admission ownership surface."""

from typing import Any, Dict, Protocol

from .research import (
    quality_flags_indicate_noise,
    research_entry_allowed_for_memory,
    research_memory_keywords,
)


class MemoryRuntime(Protocol):
    def _get_relevant_research(self, topic: str, limit: int = 1) -> str: ...

    def _latest_journal_excerpt(self, max_chars: int = 220) -> str | None: ...

    def _load_sovereignty_state(self) -> Dict[str, Any]: ...


__all__ = [
    "MemoryRuntime",
    "quality_flags_indicate_noise",
    "research_entry_allowed_for_memory",
    "research_memory_keywords",
]
