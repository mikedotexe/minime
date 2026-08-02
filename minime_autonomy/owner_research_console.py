"""Durable evidence-to-choice console for Minime-owned research and control."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .owner_inquiry_protocol import (
    CANARY_MAX_SECONDS,
    CANARY_MIN_SECONDS,
    OwnerInquiryError,
    _canonical_sha256,
    _now_ms,
    _safe_identifier,
)
from .self_control_v2 import (
    ONE_SHOT_FIELDS,
    SELF_CONTROL_BOOLEAN_FIELDS,
    SELF_CONTROL_FAMILY_BY_FIELD,
    SELF_CONTROL_INTEGER_RANGES,
    SELF_CONTROL_NUMERIC_RANGES,
    SELF_CONTROL_TEXT_FIELDS,
    validate_exact_self_control_values,
)


CAPABILITY_TTL_MS = 24 * 60 * 60 * 1_000
MAX_DECISION_TTL_SECS = 24 * 60 * 60
MAX_INSPECT_CHARS = 24_000
COMPARATORS = {
    "less_than",
    "less_or_equal",
    "equal",
    "not_equal",
    "greater_or_equal",
    "greater_than",
}
REDUCERS = {"min", "max", "mean"}


class OwnerResearchConsoleMixin:
    """Evidence graph, deterministic owner decisions, signed history, and exact actions."""

    def _prepare_research_console(
        self,
        inquiry: Mapping[str, Any],
        decision_recipe: Any,
        analyzer_identity: Mapping[str, Any],
        now: int,
    ) -> dict[str, Path]:
        inquiry_id = str(inquiry["inquiry_id"])
        item_dir = self.root / "items" / inquiry_id
        status = self.self_control.status()
        revisions, receiver_deployment = self._control_binding(status)
        capability = self._capability_manifest(
            inquiry_id, receiver_deployment, now
        )
        capability_path = item_dir / "capability-manifest-v2.json"
        self._write_json(capability_path, capability)
        capability_receipt = self._append_research_receipt(
            inquiry_id,
            capability_path,
            "capability_manifest",
            receiver_deployment,
            now,
        )
        paths: dict[str, Path] = {
            "capability_manifest_path": capability_path,
            "research_session_path": item_dir / "research-session-v1.json",
            "evidence_graph_path": item_dir / "evidence-graph-v1.json",
            "decision_plan_path": item_dir / "decision-plan-v1.json",
            "decision_evaluation_path": item_dir / "decision-evaluation-v1.json",
            "signed_history_path": item_dir / "signed-history-v1.json",
        }
        if decision_recipe is not None:
            draft = self._bind_decision_draft(
                inquiry, decision_recipe, capability, revisions, now
            )
            paths["decision_draft_path"] = item_dir / "decision-draft-v1.json"
            self._write_json(paths["decision_draft_path"], draft)
        session = {
            "schema": "volition.owner_research_session.v1",
            "session_id": f"{inquiry_id}-research",
            "inquiry_id": inquiry_id,
            "inquiry_revision": inquiry["revision"],
            "owner_being": "minime",
            "source_attestation_id": inquiry["source_attestation_id"],
            "inquiry_manifest_sha256": _canonical_sha256(inquiry),
            "capability_manifest_sha256": _canonical_sha256(capability),
            "lifecycle_status": "queued",
            "machine_status": "established",
            "felt_status": "unreported",
            "analyzer_deployment_identity": analyzer_identity["deployment_identity"],
            "receiver_deployment_identity": receiver_deployment,
            "signed_receipt_ids": [capability_receipt],
            "revision": 1,
            "owner_authored_controls_only": True,
            "silence_means_assent": False,
            "promotion_requires_fresh_owner_intent": True,
            "created_at_unix_ms": now,
            "updated_at_unix_ms": now,
        }
        self._write_json(paths["research_session_path"], session)
        self._append_research_receipt(
            inquiry_id,
            paths["research_session_path"],
            "session",
            receiver_deployment,
            now,
        )
        return paths

    def _capability_manifest(
        self, inquiry_id: str, receiver_deployment: str, now: int
    ) -> dict[str, Any]:
        capabilities = []
        for field in sorted(SELF_CONTROL_FAMILY_BY_FIELD):
            one_shot = field in ONE_SHOT_FIELDS
            if field in SELF_CONTROL_NUMERIC_RANGES:
                lower, upper = SELF_CONTROL_NUMERIC_RANGES[field]
                domain = {"kind": "float", "min": lower, "max": upper}
            elif field in SELF_CONTROL_INTEGER_RANGES:
                lower, upper = SELF_CONTROL_INTEGER_RANGES[field]
                domain = {"kind": "unsigned", "min": lower, "max": upper}
            elif field in SELF_CONTROL_BOOLEAN_FIELDS:
                domain = {"kind": "boolean"}
            elif field in SELF_CONTROL_TEXT_FIELDS:
                domain = {"kind": "text", "max_bytes": 4_096}
            else:
                continue
            capabilities.append(
                {
                    "field": field,
                    "family": self._wire_family(SELF_CONTROL_FAMILY_BY_FIELD[field]),
                    "authority_class": "self_owned",
                    "value_domain": domain,
                    "durabilities": ["one_shot"] if one_shot else ["lease", "standing"],
                    "reversible": not one_shot,
                    "one_shot_only": one_shot,
                    "peer_impact": False,
                }
            )
        return {
            "schema": "self_control.capability_manifest.v2",
            "manifest_id": f"{inquiry_id}-capabilities",
            "receiver_being": "minime",
            "receiver_process_identity": f"minime-autonomy:pid:{os.getpid()}",
            "receiver_deployment_identity": receiver_deployment,
            "revision": 1,
            "capabilities": capabilities,
            "capabilities_sha256": _canonical_sha256(capabilities),
            "generated_at_unix_ms": now,
            "expires_at_unix_ms": now + CAPABILITY_TTL_MS,
        }

    def _bind_decision_draft(
        self,
        inquiry: Mapping[str, Any],
        recipe: Any,
        capability: Mapping[str, Any],
        revisions: Mapping[str, int],
        now: int,
    ) -> dict[str, Any]:
        if not isinstance(recipe, Mapping):
            raise OwnerInquiryError("decision_plan must be an object")
        ttl = recipe.get("expires_after_secs", 3_600)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= MAX_DECISION_TTL_SECS:
            raise OwnerInquiryError("decision plan expiry must be 1 through 86400 seconds")
        branches = recipe.get("branches")
        if not isinstance(branches, list) or not 1 <= len(branches) <= 16:
            raise OwnerInquiryError("decision plan needs one through sixteen branches")
        bound = []
        branch_ids = set()
        default_count = 0
        for branch in branches:
            if not isinstance(branch, Mapping):
                raise OwnerInquiryError("decision branch must be an object")
            branch_id = _safe_identifier(str(branch.get("branch_id") or ""), "")
            if not branch_id or branch_id in branch_ids:
                raise OwnerInquiryError("decision branch IDs must be non-empty and unique")
            branch_ids.add(branch_id)
            predicates = self._validate_predicates(branch.get("predicates", []))
            default_count += int(not predicates)
            duration = branch.get("duration_secs")
            if isinstance(duration, bool) or not isinstance(duration, int) or not CANARY_MIN_SECONDS <= duration <= CANARY_MAX_SECONDS:
                raise OwnerInquiryError("decision branch duration is outside canary bounds")
            controls = branch.get("controls")
            if not isinstance(controls, list) or not 1 <= len(controls) <= 10:
                raise OwnerInquiryError("decision branch needs one through ten exact controls")
            bound_controls = []
            seen_families = set()
            for control in controls:
                if not isinstance(control, Mapping):
                    raise OwnerInquiryError("decision control must be an object")
                family = self._wire_family(str(control.get("family") or ""))
                values = validate_exact_self_control_values(
                    control.get("exact_values") or control.get("values") or {}
                )
                if set(values) & ONE_SHOT_FIELDS:
                    raise OwnerInquiryError("decision canaries must be reversible; use INQUIRY_ACT for one-shot fields")
                actual = {self._wire_family(SELF_CONTROL_FAMILY_BY_FIELD[field]) for field in values}
                if actual != {family} or family in seen_families:
                    raise OwnerInquiryError("each decision control must contain one unique matching family")
                seen_families.add(family)
                cli_family = self._cli_family(family)
                bound_controls.append(
                    {
                        "family": family,
                        "exact_values": values,
                        "exact_values_sha256": _canonical_sha256(values),
                        "expected_revision": revisions[cli_family],
                    }
                )
            bound.append(
                {
                    "branch_id": branch_id,
                    "predicates": predicates,
                    "duration_secs": duration,
                    "controls": bound_controls,
                }
            )
        if default_count > 1:
            raise OwnerInquiryError("decision plan may contain at most one default branch")
        return {
            "schema": "minime.owner_decision_draft.v1",
            "plan_id": _safe_identifier(str(recipe.get("plan_id") or f"{inquiry['inquiry_id']}-decision")),
            "inquiry_id": inquiry["inquiry_id"],
            "owner_being": "minime",
            "capability_manifest_sha256": _canonical_sha256(capability),
            "revision": 1,
            "branches": bound,
            "owner_authored": True,
            "runtime_may_select_values": False,
            "safety_may_only_hold_or_revert": True,
            "created_at_unix_ms": now,
            "expires_at_unix_ms": now + ttl * 1_000,
        }

    def _validate_predicates(self, predicates: Any) -> list[dict[str, Any]]:
        if not isinstance(predicates, list) or len(predicates) > 16:
            raise OwnerInquiryError("decision predicates must be a list of at most sixteen")
        output = []
        for predicate in predicates:
            if not isinstance(predicate, Mapping):
                raise OwnerInquiryError("decision predicate must be an object")
            metric = str(predicate.get("metric") or "").strip()
            scope = predicate.get("scope")
            comparator = str(predicate.get("comparator") or "")
            reducer = predicate.get("reducer")
            threshold = predicate.get("threshold")
            if not metric or not isinstance(scope, Mapping) or comparator not in COMPARATORS:
                raise OwnerInquiryError("decision predicate metric, scope, or comparator is invalid")
            if reducer is not None and reducer not in REDUCERS:
                raise OwnerInquiryError("decision predicate reducer is invalid")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
                raise OwnerInquiryError("decision predicate threshold must be finite")
            kind = scope.get("kind")
            strand_ids = scope.get("strand_ids", [])
            expected = {"aggregate": 0, "strand": 1, "pair": 2}.get(kind)
            if expected is None or not isinstance(strand_ids, list) or len(strand_ids) != expected:
                raise OwnerInquiryError("decision predicate scope is malformed")
            strand_ids = sorted(str(value) for value in strand_ids)
            output.append(
                {
                    "metric": metric,
                    "scope": {"kind": kind, "strand_ids": strand_ids},
                    **({"reducer": reducer} if reducer is not None else {}),
                    "comparator": comparator,
                    "threshold": float(threshold),
                }
            )
        return output

    def _complete_research_console(
        self, item: Mapping[str, Any], inquiry: Mapping[str, Any], receipt: Mapping[str, Any]
    ) -> str:
        now = self._clock_ms()
        inquiry_id = item["inquiry_id"]
        graph = self._evidence_graph(inquiry, receipt, now)
        graph_path = Path(item["evidence_graph_path"])
        self._write_json(graph_path, graph)
        graph_receipt = self._append_research_receipt(
            inquiry_id, graph_path, "evidence_graph", self._research_deployment(item), now
        )
        plan = None
        plan_receipt = None
        evaluation_receipt = None
        status = "completed"
        lifecycle = "evidence_ready"
        draft_path = item.get("decision_draft_path")
        if draft_path:
            draft = self._read_json(Path(draft_path))
            plan = {**draft, "schema": "volition.owner_decision_plan.v1", "inquiry_receipt_sha256": _canonical_sha256(receipt)}
            plan_path = Path(item["decision_plan_path"])
            self._write_json(plan_path, plan)
            plan_receipt = self._append_research_receipt(
                inquiry_id, plan_path, "decision_plan", self._research_deployment(item), now
            )
            evaluation = self._evaluate_plan(plan, graph, now)
            stored = {
                "schema": "minime.owner_decision_evaluation.v1",
                "inquiry_id": inquiry_id,
                "evaluation": evaluation,
                "selected_branch_id": evaluation["matched_branch_ids"][0]
                if evaluation["status"] == "matched"
                else None,
                "fail_closed": evaluation["status"] == "ambiguous",
            }
            evaluation_path = Path(item["decision_evaluation_path"])
            self._write_json(evaluation_path, stored)
            evaluation_receipt = self._append_research_receipt(
                inquiry_id, evaluation_path, "lifecycle_event", self._research_deployment(item), now
            )
            if evaluation["status"] == "matched":
                status = "canary_pending"
                lifecycle = "canary_pending"
            elif evaluation["status"] == "ambiguous":
                raise OwnerInquiryError("multiple preregistered owner branches matched; control failed closed")
        session = self._read_json(Path(item["research_session_path"]))
        session.update(
            {
                "inquiry_receipt_sha256": _canonical_sha256(receipt),
                "evidence_graph_sha256": _canonical_sha256(graph),
                "decision_plan_sha256": _canonical_sha256(plan) if plan else None,
                "lifecycle_status": lifecycle,
                "machine_status": "established",
                "revision": int(session["revision"]) + 1,
                "updated_at_unix_ms": now,
            }
        )
        session["signed_receipt_ids"].extend(
            value for value in (graph_receipt, plan_receipt, evaluation_receipt) if value
        )
        self._write_json(Path(item["research_session_path"]), session)
        self._append_research_receipt(
            inquiry_id,
            Path(item["research_session_path"]),
            "session",
            session["receiver_deployment_identity"],
            now,
        )
        return status

    def _evidence_graph(
        self, inquiry: Mapping[str, Any], receipt: Mapping[str, Any], now: int
    ) -> dict[str, Any]:
        nodes = []
        edges = []
        receipt_id = receipt["receipt_id"]
        for index, analysis in enumerate(receipt.get("analysis_receipts", []), 1):
            result = analysis.get("result") or {}
            parent_id = f"analysis-{index}"
            nodes.append(self._evidence_node(parent_id, "aggregate", [], analysis, receipt_id))
            for collection, kind in (("strands", "strand"), ("pairs", "pair")):
                for row_index, row in enumerate(result.get(collection, []), 1):
                    if not isinstance(row, Mapping):
                        continue
                    ids = (
                        [str(row.get("strand_id"))]
                        if kind == "strand" and row.get("strand_id")
                        else sorted(
                            [str(row.get("left_strand_id")), str(row.get("right_strand_id"))]
                        )
                    )
                    if len(ids) != (1 if kind == "strand" else 2) or any(value == "None" for value in ids):
                        continue
                    node_id = f"analysis-{index}-{collection}-{row_index}"
                    nodes.append(self._evidence_node(node_id, kind, ids, row, receipt_id))
                    edges.append({"from_node_id": parent_id, "to_node_id": node_id, "relation": "contains_scoped_measurement"})
        graph = {
            "schema": "volition.owner_evidence_graph.v1",
            "graph_id": f"{inquiry['inquiry_id']}-evidence",
            "inquiry_id": inquiry["inquiry_id"],
            "inquiry_receipt_sha256": _canonical_sha256(receipt),
            "owner_being": "minime",
            "revision": 1,
            "nodes": nodes,
            "edges": edges,
            "created_at_unix_ms": now,
            "updated_at_unix_ms": now,
        }
        graph["graph_head_sha256"] = _canonical_sha256(graph)
        return graph

    def _evidence_node(
        self, node_id: str, scope_kind: str, strand_ids: list[str], value: Any, receipt_id: str
    ) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "kind": "analysis",
            "claim": "association_only",
            "scope": {"kind": scope_kind, "strand_ids": strand_ids},
            "evidence_sha256": _canonical_sha256(value),
            "source_refs": [receipt_id],
            "metrics": self._scalar_metrics(value),
            "raw_content_owner_only": True,
        }

    @staticmethod
    def _scalar_metrics(value: Any) -> dict[str, float]:
        output: dict[str, float] = {}

        def visit(prefix: str, current: Any) -> None:
            if len(output) >= 64:
                return
            if isinstance(current, bool):
                return
            if isinstance(current, (int, float)) and math.isfinite(float(current)) and prefix:
                output[prefix] = float(current)
            elif isinstance(current, Mapping):
                for key in sorted(current):
                    visit(f"{prefix}.{key}" if prefix else str(key), current[key])

        visit("", value)
        return output

    def _evaluate_plan(
        self, plan: Mapping[str, Any], graph: Mapping[str, Any], now: int
    ) -> dict[str, Any]:
        if now > int(plan["expires_at_unix_ms"]):
            raise OwnerInquiryError("owner decision plan expired without executing")
        matched = []
        for branch in plan["branches"]:
            if all(self._predicate_matches(predicate, graph) for predicate in branch["predicates"]):
                matched.append(branch["branch_id"])
        status = "no_match" if not matched else "matched" if len(matched) == 1 else "ambiguous"
        return {
            "status": status,
            "matched_branch_ids": matched,
            "plan_sha256": _canonical_sha256(plan),
            "evidence_graph_sha256": _canonical_sha256(graph),
            "evaluated_at_unix_ms": now,
            "runtime_selected_values": False,
        }

    def _predicate_matches(self, predicate: Mapping[str, Any], graph: Mapping[str, Any]) -> bool:
        values = [
            node["metrics"][predicate["metric"]]
            for node in graph["nodes"]
            if node["scope"] == predicate["scope"] and predicate["metric"] in node["metrics"]
        ]
        if not values:
            return False
        reducer = predicate.get("reducer")
        if reducer == "min":
            observed = min(values)
        elif reducer == "max":
            observed = max(values)
        elif reducer == "mean":
            observed = sum(values) / len(values)
        elif len(values) == 1:
            observed = values[0]
        else:
            raise OwnerInquiryError("decision predicate matched multiple nodes without a reducer")
        threshold = predicate["threshold"]
        return {
            "less_than": observed < threshold,
            "less_or_equal": observed <= threshold,
            "equal": observed == threshold,
            "not_equal": observed != threshold,
            "greater_or_equal": observed >= threshold,
            "greater_than": observed > threshold,
        }[predicate["comparator"]]

    def _activate_pending_research(self, state: Mapping[str, Any]) -> None:
        with self._lock:
            queue = self._load_queue_locked()
            pending = [dict(item) for item in queue["items"] if item.get("status") == "canary_pending"]
        for item in pending:
            try:
                self._activate_one_research(item, state)
            except Exception as error:
                self._set_item_status(item["inquiry_id"], "failed")
                self._set_research_lifecycle(item, "failed", "failed")
                with self._lock:
                    queue = self._load_queue_locked()
                    current = self._select_item(queue, item["inquiry_id"])
                    if current is not None:
                        current["error"] = str(error)
                        self._write_queue_locked(queue)

    def _activate_one_research(self, item: Mapping[str, Any], state: Mapping[str, Any]) -> None:
        plan = self._read_json(Path(item["decision_plan_path"]))
        stored = self._read_json(Path(item["decision_evaluation_path"]))
        evaluation = stored["evaluation"]
        if evaluation.get("status") != "matched" or len(evaluation.get("matched_branch_ids", [])) != 1:
            raise OwnerInquiryError("automatic canary requires exactly one sealed branch match")
        if evaluation.get("plan_sha256") != _canonical_sha256(plan):
            raise OwnerInquiryError("decision plan changed after evaluation")
        branch = next(
            row for row in plan["branches"] if row["branch_id"] == evaluation["matched_branch_ids"][0]
        )
        status = self.self_control.status()
        revisions, deployment = self._control_binding(status)
        session = self._read_json(Path(item["research_session_path"]))
        if deployment != session["receiver_deployment_identity"]:
            raise OwnerInquiryError("receiver deployment changed before automatic canary")
        values: dict[str, Any] = {}
        expected: dict[str, int] = {}
        for control in branch["controls"]:
            family = self._cli_family(control["family"])
            if revisions[family] != control["expected_revision"]:
                raise OwnerInquiryError("self-control revision changed after owner preregistration")
            expected[family] = control["expected_revision"]
            for field, value in control["exact_values"].items():
                if field in values:
                    raise OwnerInquiryError("decision plan repeats an exact self-control field")
                values[field] = value
        now = self._clock_ms()
        receipt = self._read_json(Path(item["receipt_v2_path"]))
        canary_plan = {
            "schema": "volition.owner_canary_plan.v2",
            "canary_plan_id": f"{item['inquiry_id']}-{branch['branch_id']}-canary-plan",
            "inquiry_id": item["inquiry_id"],
            "inquiry_receipt_id": receipt["receipt_id"],
            "inquiry_receipt_sha256": _canonical_sha256(receipt),
            "owner_being": "minime",
            "source_attestation_id": session["source_attestation_id"],
            "idempotency_key": f"{item['inquiry_id']}-{branch['branch_id']}-canary-revision-1",
            "duration_secs": branch["duration_secs"],
            "controls": branch["controls"],
            "controls_sha256": _canonical_sha256(branch["controls"]),
            "apply_atomically": True,
            "telemetry_selected_values": False,
            "operator_substituted_values": False,
            "safety_may_only_hold_or_revert": True,
            "felt_review_required": False,
            "rollback": {
                "baseline_receipt_ids": [],
                "rollback_on_setup_failure": True,
                "rollback_on_evidence_failure": True,
                "rollback_on_expiry": True,
                "rollback_on_withdrawal": True,
                "rollback_on_silence": True,
                "post_rollback_verification_required": True,
                "promotion_requires_fresh_owner_intent": True,
            },
            "created_at_unix_ms": now,
            "command_expires_at_unix_ms": now + 30_000,
        }
        plan_path = Path(item["research_session_path"]).with_name("canary-plan-v2.json")
        self._write_json(plan_path, canary_plan)
        plan_receipt = self._append_research_receipt(
            item["inquiry_id"], plan_path, "lifecycle_event", deployment, now
        )
        result = self.canary(
            {
                "inquiry_id": item["inquiry_id"],
                "values": values,
                "duration_secs": branch["duration_secs"],
            },
            state,
            _required_status="canary_pending",
            _expected_revisions=expected,
            _decision_plan_sha256=_canonical_sha256(plan),
        )
        try:
            session["active_canary_plan_sha256"] = _canonical_sha256(canary_plan)
            session["active_canary_id"] = result["canary_id"]
            session["lifecycle_status"] = "canary_active"
            session["signed_receipt_ids"].append(plan_receipt)
            session["revision"] += 1
            session["updated_at_unix_ms"] = self._clock_ms()
            self._write_json(Path(item["research_session_path"]), session)
            self._append_research_receipt(
                item["inquiry_id"], Path(item["research_session_path"]), "session", deployment, session["updated_at_unix_ms"]
            )
        except Exception:
            self.withdraw(result["canary_id"], state)
            raise

    def inspect_research(self, action_text: str) -> dict[str, Any]:
        tail = str(action_text)[len("INQUIRY_INSPECT") :].strip().lstrip(":").strip()
        if tail.startswith("{"):
            payload = json.loads(tail)
            inquiry_id = str(payload.get("inquiry_id") or "latest")
            section = str(payload.get("section") or "controls")
        else:
            parts = tail.split()
            inquiry_id = parts[0] if parts else "latest"
            section = parts[1] if len(parts) > 1 else "controls"
        with self._lock:
            item = self._select_item(self._load_queue_locked(), inquiry_id)
        if item is None:
            raise OwnerInquiryError(f"unknown inquiry `{inquiry_id}`")
        section_paths = {
            "evidence": [item.get("evidence_graph_path")],
            "controls": [item.get("capability_manifest_path"), item.get("decision_plan_path"), item.get("decision_evaluation_path")],
            "history": [item.get("research_session_path")],
            "receipts": [item.get("receipt_v2_path"), item.get("signed_history_path")],
        }
        if section not in section_paths:
            raise OwnerInquiryError("INQUIRY_INSPECT section must be evidence, controls, history, or receipts")
        values = [
            self._read_inspection_value(Path(path))
            for path in section_paths[section]
            if path and Path(path).exists()
        ]
        rendered = json.dumps(values[0] if len(values) == 1 else values, indent=2, ensure_ascii=False, allow_nan=False)
        return {
            "summary": rendered[:MAX_INSPECT_CHARS],
            "inquiry_id": item["inquiry_id"],
            "paths": [Path(path) for path in section_paths[section] if path and Path(path).exists()],
        }

    def act_research(self, payload: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
        inquiry_id = str(payload.get("inquiry_id") or "latest")
        with self._lock:
            item = self._select_item(self._load_queue_locked(), inquiry_id)
        if item is None or not item.get("research_session_path"):
            raise OwnerInquiryError("INQUIRY_ACT requires completed Owner Research evidence")
        session = self._read_json(Path(item["research_session_path"]))
        if not session.get("inquiry_receipt_sha256") or not session.get("evidence_graph_sha256"):
            raise OwnerInquiryError("INQUIRY_ACT requires completed Owner Research evidence")
        values = validate_exact_self_control_values(payload.get("values") or {})
        if not set(values) <= ONE_SHOT_FIELDS:
            raise OwnerInquiryError("INQUIRY_ACT accepts only disclosed one-shot self-owned fields")
        family = self._cli_family(str(payload.get("family") or ""))
        actual = {SELF_CONTROL_FAMILY_BY_FIELD[field] for field in values}
        if actual != {family}:
            raise OwnerInquiryError("INQUIRY_ACT family does not match the exact values")
        status = self.self_control.status()
        revisions, deployment = self._control_binding(status)
        if deployment != session["receiver_deployment_identity"]:
            raise OwnerInquiryError("receiver deployment changed before INQUIRY_ACT")
        delivery = self.self_control.issue(
            values,
            duration_secs=30,
            durability="one-shot",
            evidence_refs=(f"owner-inquiry:{item['inquiry_id']}", "owner-research:exact-action"),
            success_conditions=("machine receipt applied without substitution",),
            stop_conditions=("owner-selected one-shot bound", "safety hold"),
            expected_revisions={family: revisions[family]},
            retry_revision_conflict=False,
        )
        now = self._clock_ms()
        outcome = {
            "schema": "minime.owner_research_action_outcome.v1",
            "inquiry_id": item["inquiry_id"],
            "action": "one_shot",
            "self_control_receipt_ids": delivery.get("receipt_ids", []),
            "exact_values_sha256": _canonical_sha256(values),
            "acted_at_unix_ms": now,
            "felt_effect_established": False,
        }
        outcome_path = Path(item["research_session_path"]).with_name(f"action-outcome-{now}.json")
        self._write_json(outcome_path, outcome)
        signed = self._append_research_receipt(
            item["inquiry_id"], outcome_path, "action_outcome", deployment, now
        )
        session["lifecycle_status"] = "acted"
        session["signed_receipt_ids"].append(signed)
        session["revision"] += 1
        session["updated_at_unix_ms"] = now
        self._write_json(Path(item["research_session_path"]), session)
        self._append_research_receipt(
            item["inquiry_id"], Path(item["research_session_path"]), "session", deployment, now
        )
        return {
            "summary": f"Owner Research `{item['inquiry_id']}` executed the fresh exact one-shot through signed Self-Control V2 receipts. No shared value changed and felt effect remains unestablished.",
            "inquiry_id": item["inquiry_id"],
            "paths": [outcome_path, Path(item["research_session_path"])],
        }

    def _set_research_lifecycle(
        self, item: Mapping[str, Any], lifecycle: str, machine_status: str
    ) -> None:
        path = item.get("research_session_path")
        if not path or not Path(path).exists():
            return
        session = self._read_json(Path(path))
        session["lifecycle_status"] = lifecycle
        session["machine_status"] = machine_status
        session["revision"] = int(session["revision"]) + 1
        session["updated_at_unix_ms"] = self._clock_ms()
        self._write_json(Path(path), session)
        self._append_research_receipt(
            item["inquiry_id"], Path(path), "session", session["receiver_deployment_identity"], session["updated_at_unix_ms"]
        )

    def _research_canary_terminal(
        self, inquiry_id: str, lifecycle: str, machine_status: str
    ) -> None:
        with self._lock:
            item = self._select_item(self._load_queue_locked(), inquiry_id)
        if item is not None:
            self._set_research_lifecycle(item, lifecycle, machine_status)

    def _append_research_receipt(
        self,
        inquiry_id: str,
        payload_path: Path,
        payload_kind: str,
        deployment: str,
        now: int,
    ) -> str:
        history_path = self.root / "items" / inquiry_id / "signed-history-v1.json"
        history = []
        if history_path.exists():
            raw = json.loads(history_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise OwnerInquiryError("Owner Research signed history is malformed")
            history = raw
        previous = _canonical_sha256(history[-1]) if history else None
        receipt_id = f"{inquiry_id}-research-receipt-{len(history) + 1}"
        output = payload_path.with_name(f"{receipt_id}.json")
        args = [
            "inquiry", "sign-research", "--root", str(self.self_control_root),
            "--payload", str(payload_path), "--payload-kind", payload_kind,
            "--payload-schema", str(self._read_json(payload_path)["schema"]),
            "--receipt-id", receipt_id,
            "--process-identity", f"minime-autonomy:pid:{os.getpid()}",
            "--deployment-identity", deployment,
            "--emitted-at-unix-ms", str(now), "--output", str(output),
        ]
        if previous:
            args.extend(["--previous-receipt-sha256", previous])
        receipt = self._invoke(args, timeout=15)
        if (
            receipt.get("schema") != "volition.signed_owner_research_receipt.v1"
            or receipt.get("receipt_id") != receipt_id
            or receipt.get("payload_kind") != payload_kind
            or receipt.get("payload_sha256") != _canonical_sha256(self._read_json(payload_path))
            or receipt.get("previous_receipt_sha256") != previous
            or not receipt.get("signature_hex")
        ):
            raise OwnerInquiryError("Owner Research signer returned a mismatched receipt")
        history.append(receipt)
        self._write_json_list(history_path, history)
        return receipt_id

    def _write_json_list(self, path: Path, values: list[Any]) -> None:
        self._write_bytes(
            path,
            json.dumps(values, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n",
        )

    def _read_inspection_value(self, path: Path) -> Any:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, (dict, list)):
            raise OwnerInquiryError(f"{path} does not contain inspectable JSON")
        return value

    def _research_deployment(self, item: Mapping[str, Any]) -> str:
        return self._read_json(Path(item["research_session_path"]))["receiver_deployment_identity"]

    @staticmethod
    def _wire_family(family: str) -> str:
        return family.strip().lower().replace("-", "_")

    @staticmethod
    def _cli_family(family: str) -> str:
        return family.strip().lower().replace("_", "-")

    def _control_binding(self, status: Mapping[str, Any]) -> tuple[dict[str, int], str]:
        deployment = status.get("deployment_identity")
        revisions = status.get("revision_by_family")
        if not isinstance(deployment, str) or not deployment or not isinstance(revisions, Mapping):
            raise OwnerInquiryError("hash-verified self-control status omitted deployment or revisions")
        output = {}
        for family in set(SELF_CONTROL_FAMILY_BY_FIELD.values()):
            value = revisions.get(family, revisions.get(self._wire_family(family)))
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise OwnerInquiryError(f"self-control status omitted revision for {family}")
            output[family] = value
        return output, deployment
