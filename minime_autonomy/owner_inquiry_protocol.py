"""Pure action grammar and disclosed catalog for owner inquiries."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Mapping


OWNER_INQUIRY_ACTIONS = {
    "INQUIRY_START",
    "INQUIRY_STATUS",
    "INQUIRY_CANCEL",
    "INQUIRY_CANARY",
    "INQUIRY_WITHDRAW",
    "INQUIRY_PROMOTE",
    "INQUIRY_INSPECT",
    "INQUIRY_ACT",
}
TERMINAL_INQUIRY_STATUSES = {
    "completed",
    "cancelled",
    "failed",
    "rolled_back",
    "promoted",
}
ACTIVE_CANARY_STATUSES = {"active", "withdrawing"}
CANARY_MIN_SECONDS = 30
CANARY_MAX_SECONDS = 900
CANARY_DEFAULT_SECONDS = 600
MAX_INQUIRY_OUTPUT_BYTES = 1_048_576
FIXED_ANALYSES = (
    "viscous_persistence_source_separation",
    "codec_fidelity",
    "sensory_interference_all_pairs",
)
CANARY_TEMPLATE_FIELDS = (
    "semantic_strand_retention_turns",
    "memory_mode",
    "journal_resonance",
    "checkpoint_interval",
    "embedding_strength",
    "memory_decay_rate",
    "transition_cushion",
    "checkpoint_annotation",
    "semantic_companion_mix",
    "semantic_intake_gain",
    "receptivity",
    "local_sensory_admission",
    "live_audio_enabled",
    "live_video_enabled",
    "synth_gain",
    "keep_bias",
    "exploration_noise",
    "fill_target",
    "regulation_strength",
    "smoothing_preference",
    "penalty_sensitivity",
    "breathing_rate_scale",
    "deep_breathing",
    "synth_noise_level",
    "pure_tone",
    "legacy_audio_synth",
    "legacy_video_synth",
    "geom_curiosity",
    "target_lambda_bias",
    "geom_drive",
    "pi_kp",
    "pi_ki",
    "pi_max_step",
    "pi_geom_weight",
    "pi_integrator_leak",
    "porosity",
    "esn_leak_override",
    "esn_leak_override_ticks",
    "mode_disperse",
    "mode_disperse_duration_ticks",
    "mode_disperse_decay_ticks",
)


class OwnerInquiryError(RuntimeError):
    """A fail-closed inquiry, extraction, queue, or canary error."""

    def __init__(self, message: str, *, clarification: str | None = None):
        super().__init__(message)
        self.clarification = clarification


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _safe_identifier(value: str, fallback: str = "inquiry") -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value).strip())[:128]
    return clean or fallback


def _json_tail(action_text: str, action: str) -> dict[str, Any]:
    tail = str(action_text)[len(action) :].strip().lstrip(":").strip()
    if not tail.startswith("{"):
        raise OwnerInquiryError(
            f"{action} requires a JSON object",
            clarification=f"Use `NEXT: {action} {{...}}` with exact values.",
        )
    try:
        payload = json.loads(tail)
    except json.JSONDecodeError as error:
        raise OwnerInquiryError(
            f"{action} JSON is invalid: {error.msg}",
            clarification=f"Use one valid JSON object after `NEXT: {action}`.",
        ) from error
    if not isinstance(payload, dict):
        raise OwnerInquiryError(f"{action} payload must be a JSON object")
    return payload


def _byte_span(response: str, start_char: int, end_char: int) -> tuple[int, int]:
    return (
        len(response[:start_char].encode("utf-8")),
        len(response[:end_char].encode("utf-8")),
    )


def _start_recipe(action_text: str, response: str) -> dict[str, Any]:
    tail = str(action_text)[len("INQUIRY_START") :].strip().lstrip(":").strip()
    if tail.startswith("{"):
        try:
            payload = json.loads(tail)
        except json.JSONDecodeError as error:
            raise OwnerInquiryError(
                f"INQUIRY_START JSON is invalid: {error.msg}",
                clarification=(
                    "Use exact byte spans: `NEXT: INQUIRY_START "
                    '{"question":"...","strands":[{"label":"A","start_byte":0,'
                    '"end_byte":12},{"label":"B","start_byte":20,"end_byte":31}]}`.'
                ),
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("strands"), list):
            raise OwnerInquiryError("INQUIRY_START requires a strands array")
        strands = []
        for index, strand in enumerate(payload["strands"]):
            if not isinstance(strand, dict):
                raise OwnerInquiryError(f"strand {index + 1} must be an object")
            start = strand.get("start_byte")
            end = strand.get("end_byte")
            if isinstance(start, bool) or not isinstance(start, int):
                raise OwnerInquiryError(f"strand {index + 1} start_byte must be an integer")
            if isinstance(end, bool) or not isinstance(end, int):
                raise OwnerInquiryError(f"strand {index + 1} end_byte must be an integer")
            strands.append(
                {
                    "label": str(strand.get("label") or f"strand-{index + 1}"),
                    "response_start_byte": start,
                    "response_end_byte": end,
                }
            )
        return {
            "question": str(payload.get("question") or "How do these strands remain distinct?"),
            "owner_priority": payload.get("owner_priority", 0),
            "dependency_inquiry_ids": payload.get("dependency_inquiry_ids", []),
            "decision_plan": payload.get("decision_plan"),
            "strands": strands,
        }

    quoted = [
        match.group(1) if match.group(1) is not None else match.group(2)
        for match in re.finditer(r'"([^"\\]*(?:\\.[^"\\]*)*)"|“([^”]+)”', tail)
    ]
    if not 2 <= len(quoted) <= 8:
        raise OwnerInquiryError(
            "natural-language inquiry extraction needs two to eight quoted strands",
            clarification=(
                "Name two to eight exact quoted passages, or provide explicit UTF-8 byte spans."
            ),
        )
    next_offset = response.rfind("NEXT:")
    search_text = response[:next_offset] if next_offset >= 0 else response
    strands = []
    for index, raw in enumerate(quoted):
        text = bytes(raw, "utf-8").decode("unicode_escape") if "\\\"" in raw else raw
        matches = [match.start() for match in re.finditer(re.escape(text), search_text)]
        if len(matches) != 1:
            raise OwnerInquiryError(
                f"quoted strand {index + 1} occurs {len(matches)} times before the NEXT line",
                clarification=(
                    "Use explicit UTF-8 byte spans for the repeated or missing passage."
                ),
            )
        start_char = matches[0]
        start_byte, end_byte = _byte_span(
            response, start_char, start_char + len(text)
        )
        strands.append(
            {
                "label": f"strand-{index + 1}",
                "response_start_byte": start_byte,
                "response_end_byte": end_byte,
            }
        )
    question = tail[: tail.find('"')].strip(" :-") or "How do these strands remain distinct?"
    return {
        "question": question,
        "owner_priority": 0,
        "dependency_inquiry_ids": [],
        "decision_plan": None,
        "strands": strands,
    }


def _validate_owner_inquiry_receipt_v2(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> None:
    expected_ids = sorted(strand["strand_id"] for strand in manifest.get("strands", []))
    expected_pairs = [
        f"{left}::{right}"
        for index, left in enumerate(expected_ids)
        for right in expected_ids[index + 1 :]
    ]
    coverage = receipt.get("coverage") or {}
    privacy = receipt.get("privacy") or {}
    identity = receipt.get("execution_identity") or {}
    plan = manifest.get("analysis_plan") or []
    first = plan[0] if plan else {}
    if (
        receipt.get("schema") != "volition.owner_inquiry_receipt.v2"
        or receipt.get("inquiry_id") != manifest.get("inquiry_id")
        or receipt.get("inquiry_revision") != manifest.get("revision")
        or receipt.get("owner_being") != "minime"
        or receipt.get("manifest_sha256") != _canonical_sha256(manifest)
        or receipt.get("analysis_plan_sha256") != manifest.get("analysis_plan_sha256")
        or identity.get("analyzer_identity") != first.get("implementation_identity")
        or identity.get("analyzer_source_sha256") != first.get("implementation_source_sha256")
        or identity.get("analyzer_artifact_sha256") != first.get("implementation_artifact_sha256")
        or receipt.get("owner_selected_values_only") is not True
        or receipt.get("silence_means_assent") is not False
        or receipt.get("candidate_merge_performed") is not False
        or receipt.get("live_mutation_during_inquiry") is not False
        or receipt.get("machine_status") != "established"
        or receipt.get("felt_status") != "unreported"
        or coverage.get("expected_strand_ids") != expected_ids
        or coverage.get("evaluated_strand_ids") != expected_ids
        or coverage.get("expected_pair_keys") != expected_pairs
        or coverage.get("evaluated_pair_keys") != expected_pairs
        or privacy.get("owner_manifest_contains_raw_content") is not True
        or privacy.get("public_receipt_contains_raw_content") is not False
        or privacy.get("raw_content_owner_only") is not True
        or privacy.get("result_sharing_requires_correspondence") is not True
        or privacy.get("network_and_socket_access_denied") is not True
    ):
        raise OwnerInquiryError("V2 inquiry receipt violates evidence or authority boundaries")
    analyses = receipt.get("analysis_receipts")
    if not isinstance(analyses, list) or len(analyses) != len(plan):
        raise OwnerInquiryError("V2 inquiry receipt changed the preregistered analysis plan")
    for row, entry in zip(analyses, plan):
        if (
            not isinstance(row, Mapping)
            or row.get("analysis") != entry.get("analysis")
            or row.get("plan_entry_sha256") != _canonical_sha256(entry)
            or row.get("input_sha256") != _canonical_sha256(manifest)
            or row.get("output_sha256") != _canonical_sha256(row.get("result"))
            or row.get("deterministic_run_output_sha256s")
            != [row.get("output_sha256")] * 2
            or row.get("all_inputs_copied") is not True
            or row.get("network_accessed") is not False
            or row.get("socket_accessed") is not False
            or row.get("private_source_accessed") is not False
            or row.get("candidate_merge_performed") is not False
            or row.get("live_runtime_mutation") is not False
        ):
            raise OwnerInquiryError("V2 inquiry analysis crossed its preregistered boundary")
    if receipt.get("result_sha256") != _canonical_sha256(analyses):
        raise OwnerInquiryError("V2 inquiry aggregate result hash does not match")
    if _contains_key(receipt, "content"):
        raise OwnerInquiryError("V2 inquiry receipt leaked raw strand content")


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def _delivery_receipt_ids(*deliveries: dict[str, Any] | None) -> list[str]:
    return [
        value
        for delivery in deliveries
        if delivery
        for value in delivery.get("receipt_ids") or []
        if isinstance(value, str)
    ]


def _validate_owner_inquiry_receipt(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> None:
    strands = manifest.get("strands") or []
    expected_pairs = len(strands) * (len(strands) - 1) // 2
    manifest_hash = _canonical_sha256(manifest)
    if (
        receipt.get("schema") != "volition.owner_inquiry_receipt.v1"
        or receipt.get("inquiry_id") != manifest.get("inquiry_id")
        or receipt.get("owner_being") != "minime"
        or receipt.get("manifest_sha256") != manifest_hash
        or receipt.get("owner_selected_values_only") is not True
        or receipt.get("silence_means_assent") is not False
        or receipt.get("candidate_merge_performed") is not False
        or receipt.get("live_mutation_during_inquiry") is not False
        or receipt.get("expected_pair_count") != expected_pairs
        or receipt.get("evaluated_pair_count") != expected_pairs
        or receipt.get("machine_status") != "established"
        or receipt.get("felt_status") != "unreported"
    ):
        raise OwnerInquiryError("inquiry receipt violates identity or authority boundaries")
    analyses = receipt.get("analysis_receipts")
    if not isinstance(analyses, list) or [
        row.get("analysis") for row in analyses if isinstance(row, Mapping)
    ] != list(FIXED_ANALYSES):
        raise OwnerInquiryError("inquiry receipt changed the fixed analysis set")
    for row in analyses:
        if (
            not isinstance(row, Mapping)
            or row.get("input_sha256") != manifest_hash
            or row.get("output_sha256") != _canonical_sha256(row.get("result"))
            or row.get("deterministic_rerun_match") is not True
            or row.get("all_inputs_copied") is not True
            or row.get("network_accessed") is not False
            or row.get("socket_accessed") is not False
            or row.get("private_source_accessed") is not False
            or row.get("candidate_merge_performed") is not False
            or row.get("live_runtime_mutation") is not False
        ):
            raise OwnerInquiryError("inquiry analysis crossed a declared boundary")
    if receipt.get("result_sha256") != _canonical_sha256(analyses):
        raise OwnerInquiryError("inquiry aggregate result hash does not match")
    if _contains_key(receipt, "content"):
        raise OwnerInquiryError("inquiry receipt leaked raw strand content")
