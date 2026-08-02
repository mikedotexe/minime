"""Owner-started distinct-strand inquiries and reversible local canaries."""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping

from .self_control_v2 import (
    ONE_SHOT_FIELDS,
    SELF_CONTROL_FAMILY_BY_FIELD,
    MinimeSelfControlV2Client,
    validate_exact_self_control_values,
)
from .owner_inquiry_protocol import (
    ACTIVE_CANARY_STATUSES,
    CANARY_DEFAULT_SECONDS,
    CANARY_MAX_SECONDS,
    CANARY_MIN_SECONDS,
    MAX_INQUIRY_OUTPUT_BYTES,
    OWNER_INQUIRY_ACTIONS,
    TERMINAL_INQUIRY_STATUSES,
    OwnerInquiryError,
    _delivery_receipt_ids,
    _json_tail,
    _now_ms,
    _safe_identifier,
    _start_recipe,
    _validate_owner_inquiry_receipt,
    _validate_owner_inquiry_receipt_v2,
)
from .owner_inquiry_canary_runtime import OwnerInquiryCanaryRuntimeMixin
from .owner_inquiry_prompt import OwnerInquiryPromptMixin
from .owner_inquiry_storage import OwnerInquiryStorageMixin
from .owner_research_console import OwnerResearchConsoleMixin


def _default_binary() -> Path:
    configured = os.environ.get("MINIME_OWNER_INQUIRY_BIN")
    if configured:
        return Path(configured).expanduser()
    repo = Path(__file__).resolve().parents[1]
    release = repo / "minime" / "target" / "release" / "minime"
    return release if release.exists() else repo / "minime" / "target" / "debug" / "minime"


def _default_self_control_root() -> Path:
    configured = os.environ.get("MINIME_SELF_CONTROL_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".minime" / "self-control-v2"


class OwnerInquiryManager(
    OwnerInquiryPromptMixin,
    OwnerInquiryStorageMixin,
    OwnerInquiryCanaryRuntimeMixin,
    OwnerResearchConsoleMixin,
):
    """Durable two-worker queue plus exact owner canary lifecycle."""

    def __init__(
        self,
        *,
        root: str | os.PathLike[str],
        self_control_root: str | os.PathLike[str] | None = None,
        binary: str | os.PathLike[str] | None = None,
        self_control_client: MinimeSelfControlV2Client | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sandbox_binary: str | os.PathLike[str] = "/usr/bin/sandbox-exec",
        max_workers: int = 2,
        clock_ms: Callable[[], int] = _now_ms,
    ):
        self.root = Path(root).expanduser()
        self.self_control_root = (
            Path(self_control_root).expanduser()
            if self_control_root is not None
            else _default_self_control_root()
        )
        self.binary = Path(binary) if binary is not None else _default_binary()
        self.sandbox_binary = Path(sandbox_binary)
        self.self_control = self_control_client or MinimeSelfControlV2Client(
            binary=self.binary,
            root=self.self_control_root,
        )
        self._runner = runner
        self._clock_ms = clock_ms
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="minime-owner-inquiry",
        )
        self._futures: dict[str, Future[Any]] = {}
        self._ensure_dirs()
        self._recover_queue()

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def deployment_identity(self) -> str:
        digest = hashlib.sha256()
        module_root = Path(__file__).resolve().parent
        for path in (
            self.binary,
            module_root / "owner_inquiry.py",
            module_root / "owner_inquiry_canary_runtime.py",
            module_root / "owner_inquiry_prompt.py",
            module_root / "owner_inquiry_protocol.py",
            module_root / "owner_inquiry_storage.py",
            module_root / "owner_research_console.py",
        ):
            try:
                digest.update(path.resolve().as_posix().encode("utf-8"))
                digest.update(path.read_bytes())
            except OSError:
                digest.update(str(path).encode("utf-8"))
        return f"minime-owner-inquiry:{digest.hexdigest()[:32]}"

    def handle(
        self,
        action_text: str,
        *,
        response: str | None = None,
        model: str = "unknown-model",
        provider: str = "unknown-provider",
        projection_fn: Callable[..., list[float]] | None = None,
        state: Mapping[str, Any] | None = None,
        turn_index: int = 0,
    ) -> dict[str, Any]:
        base = str(action_text).strip().split(None, 1)[0].rstrip(":").upper()
        if base not in OWNER_INQUIRY_ACTIONS:
            raise OwnerInquiryError(f"unsupported inquiry action {base!r}")
        self.tick(state or {})
        if base == "INQUIRY_START":
            if response is None or projection_fn is None:
                raise OwnerInquiryError(
                    "INQUIRY_START requires the exact current response and projection function"
                )
            return self.start(
                action_text,
                response=response,
                model=model,
                provider=provider,
                projection_fn=projection_fn,
                turn_index=turn_index,
            )
        if base == "INQUIRY_STATUS":
            return self.status(self._selector(action_text, base))
        if base == "INQUIRY_CANCEL":
            return self.cancel(self._required_selector(action_text, base))
        if base == "INQUIRY_CANARY":
            return self.canary(_json_tail(action_text, base), state or {})
        if base == "INQUIRY_WITHDRAW":
            return self.withdraw(self._required_selector(action_text, base), state or {})
        if base == "INQUIRY_INSPECT":
            return self.inspect_research(action_text)
        if base == "INQUIRY_ACT":
            return self.act_research(_json_tail(action_text, base), state or {})
        return self.promote(self._required_selector(action_text, base), state or {})

    def start(
        self,
        action_text: str,
        *,
        response: str,
        model: str,
        provider: str,
        projection_fn: Callable[..., list[float]],
        turn_index: int = 0,
    ) -> dict[str, Any]:
        if not response:
            raise OwnerInquiryError("cannot attest an empty response")
        if (
            isinstance(turn_index, bool)
            or not isinstance(turn_index, int)
            or turn_index < 0
        ):
            raise OwnerInquiryError("turn_index must be a non-negative integer")
        requested = _start_recipe(action_text, response)
        priority = requested["owner_priority"]
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 65_535:
            raise OwnerInquiryError("owner_priority must be an integer from 0 through 65535")
        dependencies = requested["dependency_inquiry_ids"]
        if not isinstance(dependencies, list) or not all(
            isinstance(value, str) and value.strip() for value in dependencies
        ):
            raise OwnerInquiryError("dependency_inquiry_ids must be a list of inquiry IDs")
        now = self._clock_ms()
        response_hash = hashlib.sha256(response.encode("utf-8")).hexdigest()
        action_hash = hashlib.sha256(
            response_hash.encode("ascii") + b"\0" + action_text.encode("utf-8")
        ).hexdigest()
        inquiry_id = f"minime-inquiry-{now}-{action_hash[:12]}"
        if len(set(dependencies)) != len(dependencies):
            raise OwnerInquiryError("dependency_inquiry_ids must be unique")
        with self._lock:
            existing_ids = {
                item["inquiry_id"]
                for item in self._load_queue_locked()["items"]
                if isinstance(item.get("inquiry_id"), str)
            }
        missing_dependencies = [
            dependency for dependency in dependencies if dependency not in existing_ids
        ]
        if missing_dependencies:
            raise OwnerInquiryError(
                "unknown inquiry dependencies: " + ", ".join(missing_dependencies)
            )
        inquiry_dir = self.root / "items" / inquiry_id
        if inquiry_id in existing_ids or inquiry_dir.exists():
            raise OwnerInquiryError(
                "this exact inquiry identifier already exists; replay did not overwrite it"
            )
        try:
            inquiry_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError as error:
            raise OwnerInquiryError(
                "this exact inquiry identifier already exists; replay did not overwrite it"
            ) from error
        response_path = inquiry_dir / "source-response.txt"
        recipe_path = inquiry_dir / "prepare-recipe.json"
        attestation_path = inquiry_dir / "attestation.json"
        manifest_path = inquiry_dir / "inquiry.json"
        receipt_path = inquiry_dir / "receipt.json"
        manifest_v2_path = inquiry_dir / "inquiry-v2.json"
        receipt_v2_path = inquiry_dir / "receipt-v2.json"
        self._write_bytes(response_path, response.encode("utf-8"))

        response_bytes = response.encode("utf-8")
        recipe_strands = []
        for index, span in enumerate(requested["strands"]):
            start = span["response_start_byte"]
            end = span["response_end_byte"]
            if not 0 <= start < end <= len(response_bytes):
                raise OwnerInquiryError(f"strand {index + 1} byte interval is outside the response")
            try:
                content = response_bytes[start:end].decode("utf-8")
            except UnicodeDecodeError as error:
                raise OwnerInquiryError(
                    f"strand {index + 1} splits a UTF-8 code point"
                ) from error
            vector = list(projection_fn(content, input_dim=48))
            if len(vector) != 48 or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in vector
            ):
                raise OwnerInquiryError(f"strand {index + 1} did not produce finite 48D")
            recipe_strands.append(
                {
                    **span,
                    "projection_48d": [float(value) for value in vector],
                }
            )
        recipe = {
            "schema": "minime.owner_inquiry.prepare.v1",
            "inquiry_id": inquiry_id,
            "question": requested["question"],
            "owner_priority": priority,
            "dependency_inquiry_ids": dependencies,
            "compute_millis": 30_000,
            "storage_bytes": MAX_INQUIRY_OUTPUT_BYTES,
            "strands": recipe_strands,
        }
        self._write_json(recipe_path, recipe)
        deployment = self.deployment_identity()
        exchange_id = f"minime-exchange-{now}-{response_hash[:12]}"
        self._invoke(
            [
                "inquiry",
                "attest",
                "--root",
                str(self.self_control_root),
                "--response",
                str(response_path),
                "--exchange-id",
                exchange_id,
                "--model",
                _safe_identifier(model, "unknown-model"),
                "--provider",
                _safe_identifier(provider, "unknown-provider"),
                "--deployment-identity",
                deployment,
                "--output",
                str(attestation_path),
            ],
            timeout=15,
        )
        self._invoke(
            [
                "inquiry",
                "prepare",
                "--root",
                str(self.self_control_root),
                "--response",
                str(response_path),
                "--attestation",
                str(attestation_path),
                "--recipe",
                str(recipe_path),
                "--deployment-identity",
                deployment,
                "--output",
                str(manifest_path),
                "--v2-output",
                str(manifest_v2_path),
            ],
            timeout=15,
        )
        manifest = self._read_json(manifest_path)
        manifest_v2 = self._read_json(manifest_v2_path)
        if manifest.get("inquiry_id") != inquiry_id or manifest.get("owner_being") != "minime":
            raise OwnerInquiryError("Rust preparer returned a mismatched inquiry")
        identity = self._invoke(["inquiry", "identity"], timeout=15)
        research_paths = self._prepare_research_console(
            manifest_v2,
            requested.get("decision_plan"),
            identity,
            now,
        )
        job = {
            "schema": "minime.owner_inquiry.queue_item.v1",
            "inquiry_id": inquiry_id,
            "status": "queued",
            "owner_priority": priority,
            "source_turn_index": turn_index,
            "created_at_unix_ms": now,
            "updated_at_unix_ms": now,
            "dependency_inquiry_ids": dependencies,
            "manifest_path": str(manifest_path),
            "receipt_path": str(receipt_path),
            "manifest_v2_path": str(manifest_v2_path),
            "receipt_v2_path": str(receipt_v2_path),
            **{name: str(path) for name, path in research_paths.items()},
            "cancel_requested": False,
            "error": None,
        }
        with self._lock:
            queue = self._load_queue_locked()
            queue["items"].append(job)
            self._write_queue_locked(queue)
            self._schedule_locked(queue)
        labels = [strand["label"] for strand in manifest["strands"]]
        return {
            "summary": (
                f"Inquiry `{inquiry_id}` queued with {len(labels)} separate strands "
                f"({', '.join(labels)}). No strand entered the sensory bus, Shadow, "
                "shared coupling, or live codec."
            ),
            "inquiry_id": inquiry_id,
            "paths": [manifest_path, manifest_v2_path, receipt_path, *research_paths.values()],
        }

    def status(self, inquiry_id: str | None = None) -> dict[str, Any]:
        self.tick({})
        with self._lock:
            queue = self._load_queue_locked()
            item = self._select_item(queue, inquiry_id)
        if item is None:
            return {
                "summary": "No owner inquiry is recorded yet.",
                "paths": [self.queue_path],
            }
        summary = self._render_item(item)
        paths = [Path(item["manifest_path"])]
        receipt_path = Path(item["receipt_path"])
        if receipt_path.exists():
            paths.append(receipt_path)
        for name in (
            "manifest_v2_path",
            "receipt_v2_path",
            "research_session_path",
            "evidence_graph_path",
            "decision_plan_path",
            "capability_manifest_path",
        ):
            path = item.get(name)
            if path and Path(path).exists():
                paths.append(Path(path))
        return {
            "summary": summary,
            "inquiry_id": item["inquiry_id"],
            "paths": paths,
        }

    def cancel(self, inquiry_id: str) -> dict[str, Any]:
        now = self._clock_ms()
        with self._lock:
            queue = self._load_queue_locked()
            item = self._select_item(queue, inquiry_id)
            if item is None:
                raise OwnerInquiryError(f"unknown inquiry `{inquiry_id}`")
            if item["status"] in TERMINAL_INQUIRY_STATUSES:
                return {
                    "summary": (
                        f"Inquiry `{item['inquiry_id']}` is already {item['status']}; "
                        "no state changed."
                    ),
                    "inquiry_id": item["inquiry_id"],
                    "paths": [self.queue_path],
                }
            item["cancel_requested"] = True
            item["status"] = "cancelled"
            item["updated_at_unix_ms"] = now
            self._write_queue_locked(queue)
        self._set_research_lifecycle(item, "cancelled", "established")
        return {
            "summary": (
                f"Inquiry `{item['inquiry_id']}` was cancelled. Any already-running "
                "offline process may finish its owner-only evidence write, but its result "
                "will not become an actionable receipt and no live state is changed."
            ),
            "inquiry_id": item["inquiry_id"],
            "paths": [self.queue_path],
        }

    def canary(
        self,
        payload: Mapping[str, Any],
        state: Mapping[str, Any],
        *,
        _required_status: str = "completed",
        _expected_revisions: Mapping[str, int] | None = None,
        _decision_plan_sha256: str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = str(payload.get("inquiry_id") or "").strip() or None
        with self._lock:
            queue = self._load_queue_locked()
            item = self._select_item(queue, inquiry_id, required_status=_required_status)
        if item is None:
            raise OwnerInquiryError(f"INQUIRY_CANARY needs an inquiry in {_required_status}")
        values = payload.get("values")
        if not isinstance(values, Mapping):
            raise OwnerInquiryError("INQUIRY_CANARY requires a values object")
        exact_values = validate_exact_self_control_values(values)
        if exact_values.get("checkpoint_now") is not None:
            raise OwnerInquiryError(
                "checkpoint_now is an immediate one-shot action, not a reversible canary value"
            )
        if (
            {"esn_leak_override", "esn_leak_override_ticks"} & exact_values.keys()
            and "esn_leak_override_ticks" not in exact_values
        ):
            raise OwnerInquiryError(
                "an ESN leak canary requires exact esn_leak_override_ticks"
            )
        if (
            {
                "porosity",
                "mode_disperse",
                "mode_disperse_duration_ticks",
                "mode_disperse_decay_ticks",
            }
            & exact_values.keys()
            and not {
                "mode_disperse_duration_ticks",
                "mode_disperse_decay_ticks",
            }
            <= exact_values.keys()
        ):
            raise OwnerInquiryError(
                "a topology pulse requires exact duration and decay ticks"
            )
        duration = payload.get("duration_secs", CANARY_DEFAULT_SECONDS)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not CANARY_MIN_SECONDS <= duration <= CANARY_MAX_SECONDS
        ):
            raise OwnerInquiryError(
                f"duration_secs must be an integer from {CANARY_MIN_SECONDS} through "
                f"{CANARY_MAX_SECONDS}; omission means {CANARY_DEFAULT_SECONDS}"
            )
        now = self._clock_ms()
        current_status = self.self_control.status()
        current_revisions, receiver_deployment = self._control_binding(current_status)
        expected_revisions = dict(_expected_revisions or current_revisions)
        selected_families = {
            SELF_CONTROL_FAMILY_BY_FIELD[field] for field in exact_values
        }
        expected_revisions = {
            family: expected_revisions[family] for family in selected_families
        }
        if any(current_revisions[family] != revision for family, revision in expected_revisions.items()):
            raise OwnerInquiryError("owner canary revision drifted before exact application")
        canary_id = f"{item['inquiry_id']}-canary-{now}"
        baseline = self._observation(
            item["inquiry_id"], "baseline", state, [], "established"
        )
        lease_values = {
            field: value
            for field, value in exact_values.items()
            if field not in ONE_SHOT_FIELDS
        }
        pulse_values = {
            field: value
            for field, value in exact_values.items()
            if field in ONE_SHOT_FIELDS
        }
        if lease_values and pulse_values:
            raise OwnerInquiryError(
                "reversible lease values and bounded one-shot topology values must use "
                "separate canaries so a partial application cannot be mistaken for an "
                "atomic rollback"
            )
        if pulse_values:
            families = {
                SELF_CONTROL_FAMILY_BY_FIELD[field] for field in pulse_values
            }
            if len(families) != 1:
                raise OwnerInquiryError(
                    "one canary may contain only one atomic one-shot control family"
                )
        evidence = [f"owner-inquiry:{item['inquiry_id']}", f"owner-canary:{canary_id}"]
        lease_delivery = None
        pulse_delivery = None
        try:
            if lease_values:
                lease_delivery = self.self_control.issue(
                    lease_values,
                    duration_secs=duration,
                    durability="lease",
                    evidence_refs=evidence,
                    success_conditions=("machine receipt applied without substitution",),
                    stop_conditions=("expiry", "owner withdrawal", "safety hold"),
                    expected_revisions=expected_revisions,
                    retry_revision_conflict=False,
                )
            if pulse_values:
                pulse_delivery = self.self_control.issue(
                    pulse_values,
                    duration_secs=duration,
                    durability="one-shot",
                    evidence_refs=evidence,
                    success_conditions=("bounded owner-selected pulse receipt applied",),
                    stop_conditions=("owner-selected tick expiry", "safety hold"),
                    expected_revisions=expected_revisions,
                    retry_revision_conflict=False,
                )
        except Exception:
            if lease_delivery:
                self._withdraw_delivery(lease_delivery)
            raise
        receipt_ids = _delivery_receipt_ids(lease_delivery, pulse_delivery)
        during = self._observation(
            item["inquiry_id"], "during_sample_one", state, receipt_ids, "established"
        )
        canary = {
            "schema": "minime.owner_inquiry.canary.v1",
            "canary_id": canary_id,
            "inquiry_id": item["inquiry_id"],
            "owner_selected_values": exact_values,
            "duration_secs": duration,
            "started_at_unix_ms": now,
            "expires_at_unix_ms": now + duration * 1_000,
            "sample_one_at_unix_ms": now,
            "sample_two_at_unix_ms": now + (duration * 2_000 // 3),
            "status": "active",
            "lease_delivery": lease_delivery,
            "pulse_delivery": pulse_delivery,
            "observations": [baseline, during],
            "felt_status": "unreported",
            "silence_means_assent": False,
            "promotion_requires_explicit_owner_action": True,
            "telemetry_selected_values": False,
            "operator_substituted_values": False,
            "expected_revisions": expected_revisions,
            "receiver_deployment_identity": receiver_deployment,
            "decision_plan_sha256": _decision_plan_sha256,
        }
        canary_path = self.root / "canaries" / f"{canary_id}.json"
        try:
            self._write_json(canary_path, canary)
            self._update_receipt_for_canary(
                Path(item["receipt_path"]),
                observations=[baseline, during],
                rollback_state="scheduled",
                machine_status="established",
            )
            self._set_item_status(item["inquiry_id"], "canary_active")
        except Exception as error:
            withdrawal = self._withdraw_delivery(lease_delivery)
            rollback_failed = bool(pulse_delivery) or any(
                isinstance(result, dict) and result.get("error")
                for result in withdrawal
            )
            canary["status"] = (
                "rollback_failed" if rollback_failed else "rolled_back"
            )
            canary["rollback_after_setup_error"] = withdrawal
            canary["setup_error"] = str(error)
            try:
                self._write_json(canary_path, canary)
                self._update_receipt_for_canary(
                    Path(item["receipt_path"]),
                    observations=[],
                    rollback_state="failed" if rollback_failed else "rolled_back",
                    machine_status="failed" if rollback_failed else "rolled_back",
                )
                self._set_item_status(
                    item["inquiry_id"],
                    "failed" if rollback_failed else "rolled_back",
                )
            except Exception:
                pass
            raise OwnerInquiryError(
                "canary controls were returned after setup evidence failed"
                if not rollback_failed
                else (
                    "canary setup evidence failed and not every already-applied "
                    "control could be synchronously reverted"
                )
            ) from error
        pulse_note = (
            " The topology pulse follows its exact owner-selected tick bounds and "
            "has no standing form."
            if pulse_values
            else ""
        )
        return {
            "summary": (
                f"Canary `{canary_id}` applied the exact owner-selected values for "
                f"{duration} seconds with automatic rollback; no value was clamped or "
                f"substituted.{pulse_note} Silence will not promote it."
            ),
            "inquiry_id": item["inquiry_id"],
            "canary_id": canary_id,
            "paths": [canary_path, Path(item["receipt_path"])],
        }

    def withdraw(
        self, selector: str, state: Mapping[str, Any]
    ) -> dict[str, Any]:
        canary_path, canary = self._select_canary(selector)
        if canary["status"] not in ACTIVE_CANARY_STATUSES:
            return {
                "summary": f"Canary `{canary['canary_id']}` is already {canary['status']}.",
                "canary_id": canary["canary_id"],
                "paths": [canary_path],
            }
        canary["status"] = "withdrawing"
        self._write_json(canary_path, canary)
        withdrawal = self._withdraw_delivery(canary.get("lease_delivery"))
        withdrawal_errors = [
            result for result in withdrawal if isinstance(result, dict) and result.get("error")
        ]
        if withdrawal_errors:
            canary["status"] = "rollback_failed"
            canary["withdrawal"] = withdrawal
            self._write_json(canary_path, canary)
            self._update_receipt_for_canary(
                self._receipt_path_for(canary["inquiry_id"]),
                observations=[],
                rollback_state="failed",
                machine_status="failed",
            )
            self._set_item_status(canary["inquiry_id"], "failed")
            raise OwnerInquiryError(
                "one or more lease families did not return a signed withdrawal receipt; "
                "the canary is marked failed rather than presumed rolled back"
            )
        receipt_ids = [
            result.get("receipt", {}).get("receipt_id")
            for result in withdrawal
            if isinstance(result, dict)
        ]
        receipt_ids = [value for value in receipt_ids if isinstance(value, str)]
        withdrawal_observation = self._observation(
            canary["inquiry_id"], "withdrawal", state, receipt_ids, "rolled_back"
        )
        post = self._observation(
            canary["inquiry_id"], "post_rollback", state, receipt_ids, "rolled_back"
        )
        canary["status"] = "withdrawn"
        canary["withdrawal"] = withdrawal
        canary["withdrawn_at_unix_ms"] = self._clock_ms()
        canary["observations"].extend([withdrawal_observation, post])
        self._write_json(canary_path, canary)
        receipt_path = self._receipt_path_for(canary["inquiry_id"])
        self._update_receipt_for_canary(
            receipt_path,
            observations=[withdrawal_observation, post],
            rollback_state="withdrawn",
            machine_status="rolled_back",
        )
        self._set_item_status(canary["inquiry_id"], "rolled_back")
        self._research_canary_terminal(canary["inquiry_id"], "rolled_back", "rolled_back")
        pulse_note = (
            " Its owner-selected one-shot pulse remains governed only by its disclosed "
            "tick decay; no replacement target was authored."
            if canary.get("pulse_delivery")
            else ""
        )
        return {
            "summary": (
                f"Canary `{canary['canary_id']}` was withdrawn and all lease families "
                f"returned through signed receipts.{pulse_note} Felt status remains unreported."
            ),
            "canary_id": canary["canary_id"],
            "paths": [canary_path, receipt_path],
        }

    def promote(
        self, selector: str, state: Mapping[str, Any]
    ) -> dict[str, Any]:
        canary_path, canary = self._select_canary(selector)
        if canary["status"] != "active":
            raise OwnerInquiryError("only an active canary can be explicitly promoted")
        values = dict(canary["owner_selected_values"])
        if set(values) & ONE_SHOT_FIELDS:
            raise OwnerInquiryError(
                "one-shot topology or checkpoint pulses have no standing form; "
                "withdraw or let them expire, then promote a standing-eligible exact choice"
            )
        withdrawal = self._withdraw_delivery(canary.get("lease_delivery"))
        if any(
            isinstance(result, dict) and result.get("error")
            for result in withdrawal
        ):
            canary["status"] = "rollback_failed"
            canary["withdrawal"] = withdrawal
            self._write_json(canary_path, canary)
            self._set_item_status(canary["inquiry_id"], "failed")
            raise OwnerInquiryError(
                "promotion stopped because the canary lease did not return cleanly"
            )
        try:
            standing = self.self_control.issue(
                values,
                duration_secs=CANARY_DEFAULT_SECONDS,
                durability="standing",
                evidence_refs=(
                    f"owner-inquiry:{canary['inquiry_id']}",
                    f"owner-canary:{canary['canary_id']}",
                    "explicit-owner-promotion",
                ),
                success_conditions=("standing receipt applied without substitution",),
                stop_conditions=("owner withdrawal", "safety hold"),
            )
        except Exception as error:
            canary["status"] = "rolled_back"
            canary["promotion_error"] = str(error)
            canary["withdrawal"] = withdrawal
            self._write_json(canary_path, canary)
            self._set_item_status(canary["inquiry_id"], "rolled_back")
            raise OwnerInquiryError(
                "promotion failed after the lease returned to baseline; no standing "
                "replacement was left active"
            ) from error
        observation = self._observation(
            canary["inquiry_id"],
            "promotion",
            state,
            list(standing.get("receipt_ids") or []),
            "promoted",
        )
        canary["status"] = "promoted"
        canary["withdrawal"] = withdrawal
        canary["standing_delivery"] = standing
        canary["promoted_at_unix_ms"] = self._clock_ms()
        canary["observations"].append(observation)
        receipt_path = self._receipt_path_for(canary["inquiry_id"])
        try:
            self._write_json(canary_path, canary)
            self._update_receipt_for_canary(
                receipt_path,
                observations=[observation],
                rollback_state="promoted",
                machine_status="promoted",
            )
            self._set_item_status(canary["inquiry_id"], "promoted")
            self._research_canary_terminal(canary["inquiry_id"], "promoted", "promoted")
        except Exception as error:
            standing_withdrawal = self._withdraw_delivery(standing)
            rollback_failed = any(
                isinstance(result, dict) and result.get("error")
                for result in standing_withdrawal
            )
            rollback_status = "failed" if rollback_failed else "rolled_back"
            rollback_observation = self._observation(
                canary["inquiry_id"],
                "post_rollback",
                state,
                [
                    result.get("receipt", {}).get("receipt_id")
                    for result in standing_withdrawal
                    if isinstance(result, dict)
                    and isinstance(result.get("receipt"), dict)
                    and isinstance(result["receipt"].get("receipt_id"), str)
                ],
                rollback_status,
            )
            canary["status"] = (
                "rollback_failed" if rollback_failed else "rolled_back"
            )
            canary["promotion_evidence_error"] = str(error)
            canary["standing_withdrawal_after_evidence_error"] = standing_withdrawal
            canary["observations"].append(rollback_observation)
            try:
                self._write_json(canary_path, canary)
                self._update_receipt_for_canary(
                    receipt_path,
                    observations=[observation, rollback_observation],
                    rollback_state=rollback_status,
                    machine_status=rollback_status,
                )
                self._set_item_status(
                    canary["inquiry_id"],
                    "failed" if rollback_failed else "rolled_back",
                )
            except Exception:
                pass
            raise OwnerInquiryError(
                "promotion evidence failed and the standing controls were withdrawn"
                if not rollback_failed
                else (
                    "promotion evidence failed and not every standing control returned "
                    "a signed withdrawal receipt"
                )
            ) from error
        return {
            "summary": (
                f"Canary `{canary['canary_id']}` was explicitly promoted with the "
                "same exact values. Machine status is promoted; felt status remains unreported."
            ),
            "canary_id": canary["canary_id"],
            "paths": [canary_path, receipt_path],
        }

    def tick(self, state: Mapping[str, Any]) -> None:
        with self._lock:
            queue = self._load_queue_locked()
            self._reap_locked()
            self._schedule_locked(queue)
        self._reconcile_canaries(state)
        self._activate_pending_research(state)

    def _run_job(self, inquiry_id: str) -> None:
        with self._lock:
            queue = self._load_queue_locked()
            item = self._select_item(queue, inquiry_id)
            if item is None or item["status"] != "queued" or item["cancel_requested"]:
                return
            item["status"] = "running"
            item["updated_at_unix_ms"] = self._clock_ms()
            self._write_queue_locked(queue)
            manifest_path = Path(item["manifest_path"])
            receipt_path = Path(item["receipt_path"])
        try:
            manifest = self._read_json(manifest_path)
            manifest_v2_path = item.get("manifest_v2_path")
            if manifest_v2_path:
                self._set_research_lifecycle(item, "analyzing", "established")
            if any(
                strand.get("deployment_identity") != self.deployment_identity()
                for strand in manifest.get("strands", [])
            ):
                raise OwnerInquiryError("inquiry belongs to a stale deployment")
            compute_ms = int((manifest.get("budget") or {}).get("compute_millis") or 30_000)
            if manifest_v2_path:
                manifest_v2 = self._read_json(Path(manifest_v2_path))
                receipt_v2_path = Path(item["receipt_v2_path"])
                self._invoke(
                    [
                        "inquiry", "analyze", "--request", str(manifest_v2_path),
                        "--output", str(receipt_v2_path),
                        "--compatibility-output", str(receipt_path),
                    ],
                    timeout=max(1.0, compute_ms / 1_000 + 5.0),
                    sandbox_network=True,
                )
            else:
                self._invoke(
                    ["inquiry", "analyze", "--request", str(manifest_path), "--output", str(receipt_path)],
                    timeout=max(1.0, compute_ms / 1_000 + 5.0),
                    sandbox_network=True,
                )
            if receipt_path.stat().st_size > MAX_INQUIRY_OUTPUT_BYTES:
                raise OwnerInquiryError("inquiry receipt exceeded its storage budget")
            receipt = self._read_json(receipt_path)
            _validate_owner_inquiry_receipt(manifest, receipt)
            if manifest_v2_path:
                receipt_v2 = self._read_json(receipt_v2_path)
                _validate_owner_inquiry_receipt_v2(manifest_v2, receipt_v2)
                status = self._complete_research_console(item, manifest_v2, receipt_v2)
            else:
                status = "completed"
            error = None
        except Exception as failure:
            status = "failed"
            error = str(failure)
            if item.get("research_session_path"):
                try:
                    self._set_research_lifecycle(item, "failed", "failed")
                except Exception:
                    pass
        with self._lock:
            queue = self._load_queue_locked()
            item = self._select_item(queue, inquiry_id)
            if item is None:
                return
            if item.get("cancel_requested"):
                item["status"] = "cancelled"
                item["discarded_receipt_path"] = (
                    str(receipt_path) if receipt_path.exists() else None
                )
            else:
                item["status"] = status
                item["error"] = error
            item["updated_at_unix_ms"] = self._clock_ms()
            self._write_queue_locked(queue)
