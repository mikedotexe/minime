"""Restart-safe sampling and rollback reconciliation for owner canaries."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from .owner_inquiry_protocol import (
    OwnerInquiryError,
    _canonical_sha256,
    _delivery_receipt_ids,
)
from .self_control_v2 import SelfControlV2Error


class OwnerInquiryCanaryRuntimeMixin:
    """Reconciles machine evidence without inferring felt status or promotion."""

    def _reconcile_canaries(self, state: Mapping[str, Any]) -> None:
        for canary_path in sorted((self.root / "canaries").glob("*.json")):
            canary = self._read_json(canary_path)
            if canary.get("status") != "active":
                continue
            now = self._clock_ms()
            changed = False
            if (
                len(canary.get("observations", [])) < 3
                and now >= int(canary.get("sample_two_at_unix_ms", 0))
            ):
                receipt_ids = _delivery_receipt_ids(
                    canary.get("lease_delivery"), canary.get("pulse_delivery")
                )
                observation = self._observation(
                    canary["inquiry_id"],
                    "during_sample_two",
                    state,
                    receipt_ids,
                    "established",
                )
                canary["observations"].append(observation)
                self._update_receipt_for_canary(
                    self._receipt_path_for(canary["inquiry_id"]),
                    observations=[observation],
                    rollback_state="scheduled",
                    machine_status="established",
                )
                changed = True
            lease = canary.get("lease_delivery") or {}
            terminal = {}
            if lease.get("intent_ids"):
                try:
                    terminal = self.self_control.terminal_receipts(
                        self.self_control.status(), lease["intent_ids"]
                    )
                except SelfControlV2Error:
                    terminal = {}
            expired = now >= int(canary.get("expires_at_unix_ms", 0))
            all_terminal = bool(lease.get("intent_ids")) and len(terminal) == len(
                lease["intent_ids"]
            )
            if expired or all_terminal:
                if lease.get("intent_ids") and not all_terminal:
                    withdrawal = self._withdraw_delivery(lease)
                    if any(
                        isinstance(result, dict) and result.get("error")
                        for result in withdrawal
                    ):
                        canary["status"] = "rollback_failed"
                        canary["withdrawal"] = withdrawal
                        self._update_receipt_for_canary(
                            self._receipt_path_for(canary["inquiry_id"]),
                            observations=[],
                            rollback_state="failed",
                            machine_status="failed",
                        )
                        self._set_item_status(canary["inquiry_id"], "failed")
                        self._research_canary_terminal(
                            canary["inquiry_id"], "failed", "failed"
                        )
                        self._write_json(canary_path, canary)
                        continue
                expiry = self._observation(
                    canary["inquiry_id"],
                    "expiry",
                    state,
                    [
                        receipt.get("receipt_id")
                        for receipt in terminal.values()
                        if isinstance(receipt.get("receipt_id"), str)
                    ],
                    "rolled_back",
                )
                post = self._observation(
                    canary["inquiry_id"],
                    "post_rollback",
                    state,
                    [],
                    "rolled_back",
                )
                canary["observations"].extend([expiry, post])
                canary["status"] = "expired"
                canary["expired_at_unix_ms"] = now
                self._update_receipt_for_canary(
                    self._receipt_path_for(canary["inquiry_id"]),
                    observations=[expiry, post],
                    rollback_state="rolled_back",
                    machine_status="rolled_back",
                )
                self._set_item_status(canary["inquiry_id"], "rolled_back")
                self._research_canary_terminal(
                    canary["inquiry_id"], "rolled_back", "rolled_back"
                )
                changed = True
            if changed:
                self._write_json(canary_path, canary)

    def _observation(
        self,
        inquiry_id: str,
        phase: str,
        state: Mapping[str, Any],
        receipt_ids: list[str],
        machine_status: str,
    ) -> dict[str, Any]:
        observed_at = self._clock_ms()
        evidence = {
            "source": "minime_runtime_state_copy",
            "state": {
                str(key): value
                for key, value in sorted(state.items())
                if isinstance(value, (bool, int, float))
                and (not isinstance(value, float) or math.isfinite(value))
            },
            "telemetry_selected_values": False,
            "felt_effect_established": False,
        }
        return {
            "schema": "volition.inquiry_observation.v1",
            "observation_id": f"{inquiry_id}-{phase}-{observed_at}",
            "inquiry_id": inquiry_id,
            "phase": phase,
            "observed_at_unix_ms": observed_at,
            "self_control_receipt_ids": receipt_ids,
            "machine_evidence": evidence,
            "machine_evidence_sha256": _canonical_sha256(evidence),
            "machine_status": machine_status,
            "felt_status": "unreported",
        }

    def _update_receipt_for_canary(
        self,
        path: Path,
        *,
        observations: list[dict[str, Any]],
        rollback_state: str,
        machine_status: str,
    ) -> None:
        receipt = self._read_json(path)
        existing = receipt.setdefault("observations", [])
        existing_ids = {
            row.get("observation_id")
            for row in existing
            if isinstance(row, Mapping)
        }
        existing.extend(
            observation
            for observation in observations
            if observation.get("observation_id") not in existing_ids
        )
        receipt["rollback_state"] = rollback_state
        receipt["machine_status"] = machine_status
        receipt["felt_status"] = "unreported"
        self._write_json(path, receipt)

    def _withdraw_delivery(
        self, delivery: Mapping[str, Any] | None
    ) -> list[dict[str, Any]]:
        if not delivery:
            return []
        results = []
        for row in reversed(list(delivery.get("deliveries") or [])):
            receipt = row.get("receipt") or {}
            intent_id = receipt.get("intent_id")
            family = row.get("family")
            if not isinstance(intent_id, str) or not isinstance(family, str):
                continue
            try:
                results.append(self.self_control.withdraw(family, intent_id))
            except SelfControlV2Error as error:
                results.append(
                    {
                        "family": family,
                        "intent_id": intent_id,
                        "error": str(error),
                    }
                )
        return results

    def _select_canary(self, selector: str) -> tuple[Path, dict[str, Any]]:
        candidates = []
        for path in (self.root / "canaries").glob("*.json"):
            canary = self._read_json(path)
            if selector in {"", "latest"} or selector in {
                canary.get("canary_id"),
                canary.get("inquiry_id"),
            }:
                candidates.append((path, canary))
        if not candidates:
            raise OwnerInquiryError(f"no canary matches `{selector}`")
        return max(
            candidates,
            key=lambda pair: int(pair[1].get("started_at_unix_ms", 0)),
        )

    def _receipt_path_for(self, inquiry_id: str) -> Path:
        with self._lock:
            item = self._select_item(self._load_queue_locked(), inquiry_id)
        if item is None:
            raise OwnerInquiryError(f"unknown inquiry `{inquiry_id}`")
        return Path(item["receipt_path"])

    def _set_item_status(self, inquiry_id: str, status: str) -> None:
        with self._lock:
            queue = self._load_queue_locked()
            item = self._select_item(queue, inquiry_id)
            if item is None:
                raise OwnerInquiryError(f"unknown inquiry `{inquiry_id}`")
            item["status"] = status
            item["updated_at_unix_ms"] = self._clock_ms()
            self._write_queue_locked(queue)
