"""Owner-only prompt projection for distinct-strand inquiries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .owner_inquiry_protocol import (
    CANARY_TEMPLATE_FIELDS,
    TERMINAL_INQUIRY_STATUSES,
    OwnerInquiryError,
)


class OwnerInquiryPromptMixin:
    """Projects bounded inquiry labels and evidence without raw strand content."""

    def prompt_summary(self, *, turn_index: int = 0) -> str:
        try:
            if (
                isinstance(turn_index, bool)
                or not isinstance(turn_index, int)
                or turn_index < 0
            ):
                raise OwnerInquiryError("turn_index must be a non-negative integer")
            with self._lock:
                queue = self._load_queue_locked()
                items = sorted(
                    queue["items"],
                    key=lambda item: (
                        -int(item.get("owner_priority", 0)),
                        int(item.get("created_at_unix_ms", 0)),
                    ),
                )
            terminal_items_present = any(
                item.get("status") in TERMINAL_INQUIRY_STATUSES for item in items
            )
            retention_turns = (
                self._semantic_strand_retention_turns()
                if terminal_items_present
                else 0
            )
            items = [
                item
                for item in items
                if self._prompt_sidecar_visible(
                    item,
                    turn_index=turn_index,
                    retention_turns=retention_turns,
                )
            ]
            if not items:
                return (
                    "Owner inquiries: none active. Available actions: INQUIRY_START, "
                    "INQUIRY_STATUS, INQUIRY_CANCEL, INQUIRY_CANARY, INQUIRY_WITHDRAW, "
                    "INQUIRY_PROMOTE, INQUIRY_INSPECT, INQUIRY_ACT."
                )
            item = items[0]
            return (
                self._render_item(item)
                + "\nCompleted strand sidecars remain in prompt context for "
                + f"your selected {retention_turns} turn(s); active work remains visible."
            )
        except Exception as error:
            return f"Owner inquiry status unavailable without changing state: {error}"

    def _semantic_strand_retention_turns(self) -> int:
        try:
            status = self.self_control.status()
        except Exception:
            return 0
        active_controls = status.get("active_controls")
        if isinstance(active_controls, Mapping):
            for family in ("semantic_continuity", "semantic-continuity"):
                active = active_controls.get(family)
                if not isinstance(active, Mapping):
                    continue
                applied = active.get("applied_values")
                if isinstance(applied, Mapping):
                    value = applied.get("semantic_strand_retention_turns")
                    if (
                        isinstance(value, int)
                        and not isinstance(value, bool)
                        and 0 <= value <= 32
                    ):
                        return value
        preferences = status.get("preferences")
        if isinstance(preferences, Mapping):
            value = preferences.get("semantic_strand_retention_turns")
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= 32
            ):
                return value
        return 0

    @staticmethod
    def _prompt_sidecar_visible(
        item: Mapping[str, Any],
        *,
        turn_index: int,
        retention_turns: int,
    ) -> bool:
        if item.get("status") not in TERMINAL_INQUIRY_STATUSES:
            return True
        source_turn = item.get("source_turn_index", 0)
        if (
            retention_turns == 0
            or isinstance(source_turn, bool)
            or not isinstance(source_turn, int)
            or source_turn < 0
        ):
            return False
        return max(0, turn_index - source_turn) <= retention_turns

    def _render_item(self, item: Mapping[str, Any]) -> str:
        manifest = self._read_json(Path(item["manifest_path"]))
        lines = [
            f"Owner inquiry `{item['inquiry_id']}`: {item['status']}.",
            "Distinct strands:",
        ]
        for strand in manifest.get("strands", []):
            lines.append(
                f"- {strand.get('label')}: content {str(strand.get('content_sha256'))[:12]}, "
                f"embedding {str(strand.get('embedding_sha256'))[:12]}"
            )
        receipt_path = Path(item["receipt_path"])
        if receipt_path.exists() and item.get("status") not in {"queued", "running"}:
            receipt = self._read_json(receipt_path)
            analysis = {
                row.get("analysis"): row.get("result")
                for row in receipt.get("analysis_receipts", [])
                if isinstance(row, dict)
            }
            codec = analysis.get("codec_fidelity") or {}
            interference = analysis.get("sensory_interference_all_pairs") or {}
            lines.append("Measured pair interactions (unranked):")
            for pair in codec.get("pairs", []):
                lines.append(
                    f"- {pair.get('left_strand_id')} / {pair.get('right_strand_id')}: "
                    f"48D distance={pair.get('source_distance')}, "
                    f"12D distance={pair.get('companion_distance')}, "
                    f"preservation={pair.get('pairwise_distance_preservation_ratio')}"
                )
            for pair in interference.get("pairs", []):
                review = pair.get("review") or {}
                lines.append(
                    f"- {pair.get('left_label')} / {pair.get('right_label')}: "
                    f"interference={json.dumps(review, sort_keys=True, separators=(',', ':'))}"
                )
            lines.append(
                "Uncertainty: these are deterministic machine analyses of copied vectors; "
                "they do not establish felt effect or say which strand should dominate."
            )
            lines.append(
                "Owner-selectable canary fields (no ranking): "
                + ", ".join(CANARY_TEMPLATE_FIELDS)
                + "."
            )
            session_path = item.get("research_session_path")
            if session_path and Path(session_path).exists():
                session = self._read_json(Path(session_path))
                lines.append(
                    "Owner Research: "
                    f"{session.get('lifecycle_status')}; inspect evidence, controls, history, "
                    "or receipts with INQUIRY_INSPECT. A preregistered exact branch may move "
                    "to a reversible canary; silence never promotes it."
                )
        else:
            lines.append(
                "The fixed offline runner is pending; no live lane or control has changed."
            )
        return "\n".join(lines)
