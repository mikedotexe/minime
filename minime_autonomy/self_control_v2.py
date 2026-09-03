"""Authenticated owner-side transport for Minime Self-Control V2.

The Rust CLI owns keys, signing, protocol negotiation, and receipt validation.
This module gives the Python autonomy loop a small typed boundary around that
authority instead of duplicating cryptography or writing anonymous control
packets to the sensory socket.
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


SELF_CONTROL_FAMILY_BY_FIELD = {
    "semantic_strand_retention_turns": "semantic-continuity",
    "memory_mode": "memory",
    "journal_resonance": "memory",
    "checkpoint_interval": "memory",
    "embedding_strength": "memory",
    "memory_decay_rate": "memory",
    "transition_cushion": "memory",
    "checkpoint_annotation": "memory",
    "checkpoint_now": "memory",
    "semantic_companion_mix": "sensory-intake",
    "semantic_intake_gain": "sensory-intake",
    "receptivity": "sensory-intake",
    "local_sensory_admission": "sensory-intake",
    "live_audio_enabled": "sensory-intake",
    "live_video_enabled": "sensory-intake",
    "synth_gain": "reservoir-regulation",
    "keep_bias": "reservoir-regulation",
    "exploration_noise": "reservoir-regulation",
    "fill_target": "reservoir-regulation",
    "regulation_strength": "reservoir-regulation",
    "smoothing_preference": "reservoir-regulation",
    "penalty_sensitivity": "reservoir-regulation",
    "breathing_rate_scale": "reservoir-regulation",
    "deep_breathing": "reservoir-regulation",
    "synth_noise_level": "reservoir-regulation",
    "pure_tone": "reservoir-regulation",
    "legacy_audio_synth": "reservoir-regulation",
    "legacy_video_synth": "reservoir-regulation",
    "geom_curiosity": "reservoir-geometry",
    "target_lambda_bias": "reservoir-geometry",
    "geom_drive": "reservoir-geometry",
    "pi_kp": "pi-controller",
    "pi_ki": "pi-controller",
    "pi_max_step": "pi-controller",
    "pi_geom_weight": "pi-controller",
    "pi_integrator_leak": "pi-controller",
    "porosity": "local-topology",
    "esn_leak_override": "local-topology",
    "esn_leak_override_ticks": "local-topology",
    "mode_disperse": "local-topology",
    "mode_disperse_duration_ticks": "local-topology",
    "mode_disperse_decay_ticks": "local-topology",
}

SELF_CONTROL_FAMILY_ORDER = (
    "semantic-continuity",
    "memory",
    "sensory-intake",
    "reservoir-regulation",
    "reservoir-geometry",
    "pi-controller",
    "local-topology",
)

ONE_SHOT_FIELDS = {
    "checkpoint_now",
    "porosity",
    "esn_leak_override",
    "esn_leak_override_ticks",
    "mode_disperse",
    "mode_disperse_duration_ticks",
    "mode_disperse_decay_ticks",
}

SELF_CONTROL_NUMERIC_RANGES = {
    "journal_resonance": (0.0, 1.0),
    "checkpoint_interval": (10.0, 600.0),
    "embedding_strength": (0.0, 1.0),
    "memory_decay_rate": (0.01, 0.5),
    "transition_cushion": (0.0, 1.0),
    "semantic_companion_mix": (0.0, 1.0),
    "semantic_intake_gain": (0.0, 2.0),
    "receptivity": (0.0, 1.0),
    "local_sensory_admission": (0.05, 1.0),
    "synth_gain": (0.2, 3.0),
    "keep_bias": (-0.08, 0.10),
    "exploration_noise": (0.0, 0.2),
    "fill_target": (0.25, 0.75),
    "regulation_strength": (0.0, 1.0),
    "smoothing_preference": (0.1, 0.9),
    "penalty_sensitivity": (0.0, 2.0),
    "breathing_rate_scale": (0.5, 2.0),
    "synth_noise_level": (0.0, 1.0),
    "geom_curiosity": (0.0, 0.3),
    "target_lambda_bias": (-0.5, 0.5),
    "geom_drive": (0.0, 1.0),
    "pi_kp": (0.1, 2.0),
    "pi_ki": (0.005, 0.5),
    "pi_max_step": (0.01, 0.2),
    "pi_geom_weight": (0.0, 2.0),
    "pi_integrator_leak": (0.001, 0.05),
    "porosity": (0.0, 1.0),
    "esn_leak_override": (0.2, 0.9),
    "mode_disperse": (0.0, 1.0),
}

SELF_CONTROL_INTEGER_RANGES = {
    "semantic_strand_retention_turns": (0, 32),
    "memory_mode": (0, 2),
    "esn_leak_override_ticks": (1, 12),
    "mode_disperse_duration_ticks": (1, 64),
    "mode_disperse_decay_ticks": (1, 256),
}

SELF_CONTROL_BOOLEAN_FIELDS = {
    "checkpoint_now",
    "deep_breathing",
    "pure_tone",
    "legacy_audio_synth",
    "legacy_video_synth",
    "live_audio_enabled",
    "live_video_enabled",
}

SELF_CONTROL_TEXT_FIELDS = {"checkpoint_annotation"}

APPLIED_RECEIPT_STATUSES = {"applied", "duplicate"}
TERMINAL_RECEIPT_STATUSES = {
    "expired",
    "withdrawn",
    "safety_held",
    "rolled_back",
}


class SelfControlV2Error(RuntimeError):
    """A fail-closed owner transport or receipt validation error."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.details = details


def _effective_numeric_bounds(
    field: str, compiled_lower: float, compiled_upper: float, registry: Any
) -> tuple[float, float]:
    """Constitution C3a: the envelope registry is consulted first, with the
    compiled table as the outermost python-side backstop (effective =
    intersection, so a registry edit can NARROW here but never widen past
    compiled; widening past compiled remains a deliberate code change until
    the engine-side backstops close in C3c). Registry absent, field
    uncovered, or a degenerate intersection -> compiled bounds exactly, so
    today's behavior is byte-identical (the seeds record compiled values).
    """
    if registry is None:
        return compiled_lower, compiled_upper
    try:
        from .envelope_registry import envelope_for

        envelope = envelope_for(field, registry)
    except Exception:  # noqa: BLE001 - any registry fault falls closed
        return compiled_lower, compiled_upper
    if envelope is None:
        return compiled_lower, compiled_upper
    lower = max(compiled_lower, envelope[0])
    upper = min(compiled_upper, envelope[1])
    if lower > upper:
        return compiled_lower, compiled_upper
    return lower, upper


def _load_envelope_registry() -> Any:
    try:
        from .envelope_registry import load_registry

        return load_registry()
    except Exception:  # noqa: BLE001 - any registry fault falls closed
        return None


def validate_exact_self_control_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate owner-selected values without clamping or coercion."""
    clean_values = dict(values)
    if not clean_values:
        raise SelfControlV2Error("self-control issue requires at least one value")
    _assert_json_value(clean_values)
    unknown = sorted(set(clean_values) - set(SELF_CONTROL_FAMILY_BY_FIELD))
    if unknown:
        raise SelfControlV2Error(
            "unsupported or peer-impacting self-control fields: " + ", ".join(unknown)
        )
    registry = _load_envelope_registry()
    for field, value in clean_values.items():
        if field in SELF_CONTROL_BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise SelfControlV2Error(f"{field} requires a boolean")
            continue
        if field in SELF_CONTROL_TEXT_FIELDS:
            if not isinstance(value, str) or len(value.encode("utf-8")) > 4_096:
                raise SelfControlV2Error(
                    f"{field} requires UTF-8 text no longer than 4096 bytes"
                )
            continue
        if field in SELF_CONTROL_INTEGER_RANGES:
            compiled_lower, compiled_upper = SELF_CONTROL_INTEGER_RANGES[field]
            bounds = _effective_numeric_bounds(
                field, float(compiled_lower), float(compiled_upper), registry
            )
            lower, upper = int(bounds[0]), int(bounds[1])
            if isinstance(value, bool) or not isinstance(value, int):
                raise SelfControlV2Error(f"{field} requires an integer")
            if not lower <= value <= upper:
                raise SelfControlV2Error(
                    f"{field} must be within the exact range [{lower}, {upper}]"
                )
            continue
        if field in SELF_CONTROL_NUMERIC_RANGES:
            compiled_lower, compiled_upper = SELF_CONTROL_NUMERIC_RANGES[field]
            lower, upper = _effective_numeric_bounds(
                field, compiled_lower, compiled_upper, registry
            )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SelfControlV2Error(f"{field} requires a finite number")
            numeric = float(value)
            if not math.isfinite(numeric) or not lower <= numeric <= upper:
                raise SelfControlV2Error(
                    f"{field} must be within the exact range [{lower}, {upper}]"
                )
            # Every numeric dial is f32 on the wire (SelfControlValuesV2), so
            # "exact" means exact IN THAT DOMAIN: quantize the owner's choice
            # to f32 before sending so the receipt's echo can — and must —
            # match it byte-for-byte. Comparing raw f64 claimed a precision
            # the channel never had: a non-f32-exact choice like 0.08 was
            # APPLIED by the engine, then wrongly rolled back as
            # "substituted" (first seen live 2026-09-01, the first receipt
            # this validator ever processed).
            clean_values[field] = struct.unpack("<f", struct.pack("<f", numeric))[0]
            continue
        raise SelfControlV2Error(f"{field} has no exact-value validator")
    if "porosity" in clean_values and "mode_disperse" in clean_values:
        raise SelfControlV2Error("porosity and mode_disperse are aliases; choose exactly one")
    if "esn_leak_override_ticks" in clean_values and "esn_leak_override" not in clean_values:
        raise SelfControlV2Error(
            "esn_leak_override_ticks requires esn_leak_override in the same choice"
        )
    if (
        {
            "mode_disperse_duration_ticks",
            "mode_disperse_decay_ticks",
        }
        & clean_values.keys()
        and not {"mode_disperse", "porosity"} & clean_values.keys()
    ):
        raise SelfControlV2Error(
            "mode-disperse timing requires mode_disperse or porosity in the same choice"
        )
    return clean_values


def _default_binary() -> Path:
    configured = os.environ.get("MINIME_SELF_CONTROL_BIN")
    if configured:
        return Path(configured).expanduser()
    repo = Path(__file__).resolve().parents[1]
    release = repo / "minime" / "target" / "release" / "minime"
    if release.exists():
        return release
    return repo / "minime" / "target" / "debug" / "minime"


def _assert_json_value(value: Any, *, path: str = "values") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SelfControlV2Error(f"{path} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_json_value(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_json_value(item, path=f"{path}[{index}]")
        return
    raise SelfControlV2Error(f"{path} contains unsupported type {type(value).__name__}")


def _final_receipt(
    payload: Mapping[str, Any],
    *,
    expected_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if payload.get("felt_effect_established") is not False:
        raise SelfControlV2Error(
            "self-control result must not assert a felt effect",
            details=payload,
        )
    attempts = payload.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise SelfControlV2Error("self-control result omitted delivery attempts", details=payload)
    final = attempts[-1]
    if not isinstance(final, Mapping):
        raise SelfControlV2Error("self-control result contains a malformed final attempt")
    receipt = final.get("self_control_receipt")
    if not isinstance(receipt, Mapping):
        raise SelfControlV2Error("self-control result omitted its typed receipt", details=payload)
    receipt = dict(receipt)
    if receipt.get("schema") != "self_control.receipt.v2":
        raise SelfControlV2Error("self-control result returned an unknown receipt schema")
    if receipt.get("target_being") != "minime":
        raise SelfControlV2Error("self-control receipt target is not Minime")
    if receipt.get("felt_effect_established") is not False:
        raise SelfControlV2Error(
            "self-control receipt must keep felt effect unestablished",
            details=payload,
        )
    if expected_values is not None:
        requested_values = receipt.get("requested_values")
        if not isinstance(requested_values, Mapping) or dict(
            requested_values
        ) != dict(expected_values):
            raise SelfControlV2Error(
                "self-control receipt substituted or omitted requested values",
                details=payload,
            )
        if expected_values and receipt.get("status") in APPLIED_RECEIPT_STATUSES:
            for field in ("clamped_values", "applied_values"):
                observed = receipt.get(field)
                if not isinstance(observed, Mapping) or dict(observed) != dict(
                    expected_values
                ):
                    raise SelfControlV2Error(
                        f"self-control receipt {field} differs from the exact owner choice",
                        details=payload,
                    )
    server_deployment = payload.get("server_deployment_identity")
    if (
        not isinstance(server_deployment, str)
        or not server_deployment
        or receipt.get("server_deployment_identity") != server_deployment
        or receipt.get("target_deployment_identity") != server_deployment
    ):
        raise SelfControlV2Error("self-control receipt deployment identity mismatch")
    return receipt


class MinimeSelfControlV2Client:
    """Issue Minime-owned commands through the receipt-validating Rust CLI."""

    def __init__(
        self,
        *,
        binary: str | os.PathLike[str] | None = None,
        sensory_url: str | None = None,
        root: str | os.PathLike[str] | None = None,
        timeout_secs: float = 15.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.binary = Path(binary) if binary is not None else _default_binary()
        self.sensory_url = sensory_url or os.environ.get(
            "MINIME_SELF_CONTROL_SENSORY_URL", "ws://127.0.0.1:7879"
        )
        self.root = Path(root).expanduser() if root is not None else None
        self.timeout_secs = timeout_secs
        self._runner = runner

    def issue(
        self,
        values: Mapping[str, Any],
        *,
        duration_secs: int = 120,
        durability: str = "lease",
        actor_process_identity: str | None = None,
        evidence_refs: Iterable[str] = (),
        success_conditions: Iterable[str] = (),
        stop_conditions: Iterable[str] = (),
        expected_revisions: Mapping[str, int] | None = None,
        retry_revision_conflict: bool = True,
    ) -> dict[str, Any]:
        clean_values = validate_exact_self_control_values(values)
        durability = durability.strip().lower().replace("_", "-")
        if durability not in {"standing", "lease", "one-shot"}:
            raise SelfControlV2Error(f"unsupported self-control durability {durability!r}")
        if isinstance(duration_secs, bool) or not isinstance(duration_secs, int):
            raise SelfControlV2Error("self-control duration_secs requires an integer")
        if duration_secs <= 0:
            raise SelfControlV2Error("self-control duration_secs must be positive")
        one_shot = sorted(set(clean_values) & ONE_SHOT_FIELDS)
        if one_shot and durability != "one-shot":
            raise SelfControlV2Error(
                "one-shot fields require one-shot durability: " + ", ".join(one_shot)
            )

        groups = {
            family: {
                field: clean_values[field]
                for field in clean_values
                if SELF_CONTROL_FAMILY_BY_FIELD[field] == family
            }
            for family in SELF_CONTROL_FAMILY_ORDER
        }
        groups = {family: group for family, group in groups.items() if group}
        revisions = dict(expected_revisions or {})
        for family, revision in revisions.items():
            if family not in groups:
                raise SelfControlV2Error(f"unexpected revision binding for {family}")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise SelfControlV2Error(f"invalid expected revision for {family}")
        if revisions and set(revisions) != set(groups):
            raise SelfControlV2Error("every selected family requires an expected revision")
        actor = actor_process_identity or f"minime-autonomy:pid:{os.getpid()}"
        evidence = [str(item) for item in evidence_refs if str(item).strip()]
        success = [str(item) for item in success_conditions if str(item).strip()]
        stops = [str(item) for item in stop_conditions if str(item).strip()]
        deliveries: list[dict[str, Any]] = []
        deployment_identity: str | None = None
        try:
            for family, family_values in groups.items():
                args = [
                    "self-control",
                    "issue",
                    "--sensory-url",
                    self.sensory_url,
                    "--family",
                    family,
                    "--durability",
                    durability,
                    "--values-json",
                    json.dumps(
                        family_values,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                    "--lease-secs",
                    str(duration_secs),
                    "--actor-process-identity",
                    actor,
                ]
                if revisions:
                    args.extend(["--expected-revision", str(revisions[family])])
                args.extend(
                    [
                        "--retry-revision-conflict",
                        "true" if retry_revision_conflict else "false",
                    ]
                )
                self._append_root(args)
                self._append_repeated(args, "--evidence-ref", evidence)
                self._append_repeated(args, "--success-condition", success)
                self._append_repeated(args, "--stop-condition", stops)
                payload = self._run(args)
                try:
                    receipt = _final_receipt(
                        payload,
                        expected_values=family_values,
                    )
                except SelfControlV2Error:
                    # If the runtime says it applied something but changed the
                    # being's exact values, include that current family in the
                    # rollback set as well as every earlier family.
                    try:
                        applied_receipt = _final_receipt(payload)
                    except SelfControlV2Error:
                        applied_receipt = None
                    if (
                        applied_receipt is not None
                        and applied_receipt.get("status") in APPLIED_RECEIPT_STATUSES
                    ):
                        deliveries.append(
                            {
                                "family": family,
                                "values": family_values,
                                "result": payload,
                                "receipt": applied_receipt,
                            }
                        )
                    raise
                if receipt.get("status") not in APPLIED_RECEIPT_STATUSES:
                    raise SelfControlV2Error(
                        f"{family} self-control was not applied: "
                        f"{receipt.get('status')} ({receipt.get('reason') or 'no reason'})",
                        details=payload,
                    )
                current_deployment = receipt["server_deployment_identity"]
                if deployment_identity is None:
                    deployment_identity = current_deployment
                elif current_deployment != deployment_identity:
                    raise SelfControlV2Error(
                        "multi-family self-control crossed deployment identities"
                    )
                deliveries.append(
                    {
                        "family": family,
                        "values": family_values,
                        "result": payload,
                        "receipt": receipt,
                    }
                )
        except Exception as error:
            rollback = self._withdraw_deliveries(deliveries, actor)
            if isinstance(error, SelfControlV2Error):
                raise SelfControlV2Error(
                    str(error),
                    details={"cause": error.details, "partial_rollback": rollback},
                ) from error
            raise SelfControlV2Error(
                f"self-control issue failed: {error}",
                details={"partial_rollback": rollback},
            ) from error

        receipts = [delivery["receipt"] for delivery in deliveries]
        expiries = [
            int(receipt["control_expires_at_unix_ms"])
            for receipt in receipts
            if isinstance(receipt.get("control_expires_at_unix_ms"), int)
        ]
        return {
            "schema": "minime.self_control.autonomy_delivery.v2",
            "target_being": "minime",
            "server_deployment_identity": deployment_identity,
            "families": list(groups),
            "deliveries": deliveries,
            "receipts": receipts,
            "intent_ids": [receipt["intent_id"] for receipt in receipts],
            "receipt_ids": [receipt["receipt_id"] for receipt in receipts],
            "control_expires_at_unix_ms": min(expiries) if expiries else None,
            "felt_effect_established": False,
        }

    def withdraw(
        self,
        family: str,
        related_intent_id: str,
        *,
        actor_process_identity: str | None = None,
    ) -> dict[str, Any]:
        args = [
            "self-control",
            "withdraw",
            "--sensory-url",
            self.sensory_url,
            "--family",
            family,
            "--related-intent-id",
            related_intent_id,
            "--actor-process-identity",
            actor_process_identity or f"minime-autonomy:pid:{os.getpid()}",
        ]
        self._append_root(args)
        payload = self._run(args)
        receipt = _final_receipt(payload, expected_values={})
        if receipt.get("status") not in {"withdrawn", "duplicate"}:
            raise SelfControlV2Error(
                f"self-control withdrawal was not accepted: {receipt.get('status')}",
                details=payload,
            )
        return {"result": payload, "receipt": receipt}

    def status(self) -> dict[str, Any]:
        args = ["self-control", "status"]
        self._append_root(args)
        payload = self._run(args)
        if (
            payload.get("schema") != "minime.self_control.status.v2"
            or payload.get("target_being") != "minime"
            or payload.get("integrity_verified") is not True
            or payload.get("pending_transition") is not False
        ):
            raise SelfControlV2Error(
                "self-control status did not return a settled hash-verified state",
                details=payload,
            )
        return payload

    @staticmethod
    def terminal_receipts(
        status: Mapping[str, Any], intent_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        wanted = set(intent_ids)
        found: dict[str, dict[str, Any]] = {}
        receipts = status.get("recent_receipts")
        if not isinstance(receipts, list):
            return found
        for receipt in receipts:
            if (
                isinstance(receipt, Mapping)
                and receipt.get("intent_id") in wanted
                and receipt.get("status") in TERMINAL_RECEIPT_STATUSES
            ):
                found[str(receipt["intent_id"])] = dict(receipt)
        return found

    def _withdraw_deliveries(
        self, deliveries: Iterable[Mapping[str, Any]], actor: str
    ) -> list[dict[str, Any]]:
        results = []
        for delivery in reversed(list(deliveries)):
            receipt = delivery.get("receipt")
            if not isinstance(receipt, Mapping):
                continue
            try:
                results.append(
                    {
                        "family": delivery.get("family"),
                        "intent_id": receipt.get("intent_id"),
                        "withdrawal": self.withdraw(
                            str(delivery.get("family")),
                            str(receipt.get("intent_id")),
                            actor_process_identity=actor,
                        ),
                    }
                )
            except Exception as error:
                results.append(
                    {
                        "family": delivery.get("family"),
                        "intent_id": receipt.get("intent_id"),
                        "withdrawal_error": str(error),
                    }
                )
        return results

    def _append_root(self, args: list[str]) -> None:
        if self.root is not None:
            args.extend(["--root", str(self.root)])

    @staticmethod
    def _append_repeated(args: list[str], flag: str, values: Iterable[str]) -> None:
        for value in values:
            args.extend([flag, value])

    def _run(self, args: list[str]) -> dict[str, Any]:
        command = [str(self.binary), *args]
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_secs,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SelfControlV2Error(
                f"could not execute Minime self-control CLI: {error}"
            ) from error
        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "").strip()
            raise SelfControlV2Error(
                f"Minime self-control CLI exited {completed.returncode}: "
                f"{error_text[:800] or 'no diagnostic'}"
            )
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise SelfControlV2Error(
                "Minime self-control CLI returned non-JSON output"
            ) from error
        if not isinstance(payload, dict):
            raise SelfControlV2Error("Minime self-control CLI returned a non-object result")
        return payload
