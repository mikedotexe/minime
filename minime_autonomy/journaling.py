"""Journal persistence and hygiene ownership contract."""

from pathlib import Path
from typing import Dict, Protocol


class JournalRuntime(Protocol):
    def _last_journal_entry(self) -> str: ...

    def _write_journal_entry(
        self,
        kind: str,
        reflection: str,
        state: Dict[str, float],
        file_path: str | None = None,
    ) -> Path | None: ...


__all__ = ["JournalRuntime"]
