import hashlib
import json
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import Future
from pathlib import Path

import pytest

from minime_autonomy.owner_inquiry import (
    OwnerInquiryError,
    OwnerInquiryManager,
    _start_recipe,
)
from minime_autonomy.owner_inquiry_protocol import _canonical_sha256
from minime_autonomy import runtime as autonomy_runtime


class FakeSelfControl:
    def __init__(self):
        self.issues = []
        self.withdrawals = []
        self.retention_turns = 0
        self.deployment_identity = "minime-self-control:test"
        self.revisions = {
            "semantic-continuity": 0,
            "memory": 0,
            "sensory-intake": 0,
            "reservoir-regulation": 0,
            "reservoir-geometry": 0,
            "pi-controller": 0,
            "local-topology": 0,
        }

    def issue(
        self,
        values,
        *,
        duration_secs,
        durability,
        expected_revisions=None,
        retry_revision_conflict=True,
        **_kwargs,
    ):
        values = dict(values)
        if "semantic_strand_retention_turns" in values:
            self.retention_turns = values["semantic_strand_retention_turns"]
        self.issues.append((values, duration_secs, durability))
        families = sorted({_family(field) for field in values})
        if expected_revisions is not None:
            assert retry_revision_conflict is False
            assert dict(expected_revisions) == {
                family: self.revisions[family] for family in families
            }
        deliveries = []
        for index, family in enumerate(families):
            family_values = {
                field: value for field, value in values.items() if _family(field) == family
            }
            receipt = {
                "receipt_id": f"receipt-{len(self.issues)}-{index}",
                "intent_id": f"intent-{len(self.issues)}-{index}",
                "requested_values": family_values,
                "clamped_values": family_values,
                "applied_values": family_values,
                "status": "applied",
                "resulting_revision": self.revisions[family] + 1,
            }
            self.revisions[family] += 1
            deliveries.append(
                {"family": family, "values": family_values, "receipt": receipt}
            )
        return {
            "deliveries": deliveries,
            "receipt_ids": [row["receipt"]["receipt_id"] for row in deliveries],
            "intent_ids": [row["receipt"]["intent_id"] for row in deliveries],
            "felt_effect_established": False,
        }

    def withdraw(self, family, intent_id):
        self.withdrawals.append((family, intent_id))
        self.revisions[family] += 1
        return {
            "receipt": {
                "receipt_id": f"withdraw-{intent_id}",
                "intent_id": intent_id,
                "status": "withdrawn",
            }
        }

    def status(self):
        return {
            "schema": "minime.self_control.status.v2",
            "target_being": "minime",
            "deployment_identity": self.deployment_identity,
            "revision_by_family": dict(self.revisions),
            "integrity_verified": True,
            "pending_transition": False,
            "recent_receipts": [],
            "preferences": {
                "semantic_strand_retention_turns": self.retention_turns,
            },
            "active_controls": {},
        }

    @staticmethod
    def terminal_receipts(_status, _intent_ids):
        return {}


def _family(field):
    if field == "semantic_strand_retention_turns":
        return "semantic-continuity"
    if field == "smoothing_preference":
        return "reservoir-regulation"
    if field == "semantic_companion_mix":
        return "sensory-intake"
    if field.startswith("mode_disperse") or field in {
        "porosity",
        "esn_leak_override",
        "esn_leak_override_ticks",
    }:
        return "local-topology"
    return "memory"


class FakeInquiryRunner:
    def __init__(self, analyze_delay=0.0):
        self.analyze_delay = analyze_delay
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.analyze_order = []

    def __call__(self, command, **_kwargs):
        args = list(command)
        inquiry_index = args.index("inquiry")
        operation = args[inquiry_index + 1]
        if operation == "identity":
            return _completed(command, _fake_inquiry_identity())
        if operation == "attest":
            response = Path(_value(args, "--response")).read_bytes()
            deployment = _value(args, "--deployment-identity")
            payload = {
                "schema": "being.utterance_attestation.v1",
                "attestation_id": f"attestation-{hashlib.sha256(response).hexdigest()[:12]}",
                "being": "minime",
                "response_sha256": hashlib.sha256(response).hexdigest(),
                "response_len_bytes": len(response),
                "model_deployment_identity": deployment,
            }
            _write_json(Path(_value(args, "--output")), payload)
            return _completed(command, payload)
        if operation == "prepare":
            recipe = json.loads(Path(_value(args, "--recipe")).read_text())
            response = Path(_value(args, "--response")).read_bytes()
            deployment = _value(args, "--deployment-identity")
            strands = []
            for index, strand in enumerate(recipe["strands"]):
                content = response[
                    strand["response_start_byte"] : strand["response_end_byte"]
                ].decode()
                strands.append(
                    {
                        "schema": "volition.semantic_strand.v1",
                        "strand_id": f"{recipe['inquiry_id']}-strand-{index + 1}",
                        "owner_being": "minime",
                        "source_attestation_id": "attestation-test",
                        "source_attestation_sha256": "a" * 64,
                        "response_start_byte": strand["response_start_byte"],
                        "response_end_byte": strand["response_end_byte"],
                        "label": strand["label"],
                        "content": content,
                        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "embedding_sha256": hashlib.sha256(
                            json.dumps(strand["projection_48d"]).encode()
                        ).hexdigest(),
                        "projection_48d": strand["projection_48d"],
                        "companion_projection_12d": [0.0] * 12,
                        "provenance": "exact_utf8_response_interval",
                        "deployment_identity": deployment,
                        "captured_at_unix_ms": 1,
                    }
                )
            payload = {
                "schema": "volition.owner_inquiry.v1",
                "inquiry_id": recipe["inquiry_id"],
                "owner_being": "minime",
                "source_attestation_id": "attestation-test",
                "source_attestation_sha256": "a" * 64,
                "question": recipe["question"],
                "strands": strands,
                "owner_priority": recipe["owner_priority"],
                "fixed_analysis_set": [
                    "viscous_persistence_source_separation",
                    "codec_fidelity",
                    "sensory_interference_all_pairs",
                ],
                "budget": {
                    "compute_millis": recipe["compute_millis"],
                    "storage_bytes": recipe["storage_bytes"],
                    "action_count": 1,
                },
                "dependency_inquiry_ids": recipe["dependency_inquiry_ids"],
                "status": "queued",
                "cancellation": {"requested": False},
                "authority_boundary": {
                    "raw_strands_owner_only": True,
                    "live_sensory_admission": False,
                    "shadow_influence": False,
                    "shared_coupling": False,
                    "live_codec_write": False,
                    "telemetry_can_choose_control": False,
                    "operator_can_substitute_control": False,
                    "felt_review_required": False,
                    "result_sharing_requires_correspondence": True,
                },
                "created_at_unix_ms": 1,
                "updated_at_unix_ms": 1,
            }
            _write_json(Path(_value(args, "--output")), payload)
            if "--v2-output" in args:
                _write_json(
                    Path(_value(args, "--v2-output")),
                    _fake_v2_manifest(payload, hashlib.sha256(response).hexdigest()),
                )
            return _completed(command, payload)
        if operation == "analyze":
            manifest = json.loads(Path(_value(args, "--request")).read_text())
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.analyze_order.append(manifest["inquiry_id"])
            try:
                if self.analyze_delay:
                    time.sleep(self.analyze_delay)
                if manifest.get("schema") == "volition.owner_inquiry.v2":
                    compatibility = _fake_v1_receipt(_fake_v1_manifest(manifest))
                    _write_json(Path(_value(args, "--compatibility-output")), compatibility)
                    payload = _fake_v2_receipt(manifest, compatibility)
                else:
                    payload = _fake_v1_receipt(manifest)
                _write_json(Path(_value(args, "--output")), payload)
                return _completed(command, payload)
            finally:
                with self.lock:
                    self.active -= 1
        if operation == "sign-research":
            payload = json.loads(Path(_value(args, "--payload")).read_text())
            public_key = "11" * 32
            receipt = {
                "schema": "volition.signed_owner_research_receipt.v1",
                "receipt_id": _value(args, "--receipt-id"),
                "payload_kind": _value(args, "--payload-kind"),
                "payload_schema": _value(args, "--payload-schema"),
                "payload_sha256": _canonical_sha256(payload),
                "owner_being": "minime",
                "process_identity": _value(args, "--process-identity"),
                "deployment_identity": _value(args, "--deployment-identity"),
                "signer_public_key_hex": public_key,
                "signer_public_key_fingerprint_sha256": hashlib.sha256(bytes.fromhex(public_key)).hexdigest(),
                "emitted_at_unix_ms": int(_value(args, "--emitted-at-unix-ms")),
                "signature_hex": "22" * 64,
            }
            if "--previous-receipt-sha256" in args:
                receipt["previous_receipt_sha256"] = _value(args, "--previous-receipt-sha256")
            _write_json(Path(_value(args, "--output")), receipt)
            return _completed(command, receipt)
        raise AssertionError(command)


def _fake_inquiry_identity():
    return {
        "analyzer_identity": "minime-owner-inquiry-v2",
        "analyzer_source_sha256": "b" * 64,
        "analyzer_artifact_sha256": "c" * 64,
        "deployment_identity": "minime-owner-inquiry-v2:test",
        "sandbox_profile_sha256": "d" * 64,
    }


def _fake_analysis_plan():
    identity = _fake_inquiry_identity()
    definitions = [
        (
            "viscous_persistence_source_separation",
            "per_strand",
            {
                "axes": ["pressure", "gradient", "entropy", "persistence", "packing", "porosity", "distinguishability_loss"],
                "axis_levels": [0.2, 0.5, 0.8],
                "fixed_fill": 0.68,
                "independent_axis_sweep": True,
            },
        ),
        (
            "codec_fidelity",
            "per_strand_and_all_pairs",
            {
                "base_dimensions": 48,
                "companion_dimensions": 12,
                "companion_mix": 0.0,
                "measure_reconstruction": True,
                "measure_lane_loss": True,
                "measure_pairwise_distance_preservation": True,
            },
        ),
        (
            "sensory_interference_all_pairs",
            "all_pairs",
            {"unordered_all_pairs": True, "averaging": False, "candidate_merge": False},
        ),
    ]
    output = []
    for analysis, coverage, parameters in definitions:
        output.append(
            {
                "analysis": analysis,
                "plan_revision": 1,
                "implementation_identity": identity["analyzer_identity"],
                "implementation_source_sha256": identity["analyzer_source_sha256"],
                "implementation_artifact_sha256": identity["analyzer_artifact_sha256"],
                "parameters": parameters,
                "parameters_sha256": _canonical_sha256(parameters),
                "deterministic_run_count": 2,
                "coverage": coverage,
                "isolation": {
                    "copied_inputs_only": True,
                    "network_denied": True,
                    "socket_creation_denied": True,
                    "private_source_access_denied": True,
                    "candidate_merge_denied": True,
                    "live_runtime_mutation_denied": True,
                    "sandbox_profile_sha256": identity["sandbox_profile_sha256"],
                },
            }
        )
    return output


def _fake_v2_manifest(manifest, source_response_sha256):
    strands = [
        {
            **strand,
            "schema": "volition.semantic_strand.v2",
            "revision": 1,
            "source_response_sha256": source_response_sha256,
            "lineage": {"operation": "captured", "parent_strand_ids": [], "owner_authored": True},
            "disclosure": {
                "raw_content_owner_only": True,
                "receipt_may_include_label": True,
                "receipt_may_include_hashes": True,
                "receipt_may_include_vectors": True,
                "shared_by_default": False,
            },
        }
        for strand in manifest["strands"]
    ]
    plan = _fake_analysis_plan()
    return {
        "schema": "volition.owner_inquiry.v2",
        "inquiry_id": manifest["inquiry_id"],
        "revision": 1,
        "idempotency_key": f"{manifest['inquiry_id']}-v2-revision-1",
        "owner_being": "minime",
        "source_attestation_id": manifest["source_attestation_id"],
        "source_attestation_sha256": manifest["source_attestation_sha256"],
        "source_response_sha256": source_response_sha256,
        "question": manifest["question"],
        "strands": strands,
        "owner_priority": manifest["owner_priority"],
        "preserve_all_strands_without_merge": True,
        "analysis_plan": plan,
        "analysis_plan_sha256": _canonical_sha256(plan),
        "budget": manifest["budget"],
        "dependency_inquiry_ids": manifest["dependency_inquiry_ids"],
        "status": manifest["status"],
        "cancellation": manifest["cancellation"],
        "authority_boundary": manifest["authority_boundary"],
        "success_conditions": {
            "deterministic_runs_match": True,
            "every_strand_covered": True,
            "every_pair_covered": True,
            "finite_results_only": True,
            "no_private_source_access": True,
            "no_candidate_merge": True,
            "no_live_runtime_mutation": True,
        },
        "stop_conditions": {
            "owner_cancellation": True,
            "owner_withdrawal": True,
            "budget_exhaustion": True,
            "integrity_failure": True,
            "expiry": True,
        },
        "expires_at_unix_ms": manifest["created_at_unix_ms"] + 3_600_000,
        "created_at_unix_ms": manifest["created_at_unix_ms"],
        "updated_at_unix_ms": manifest["updated_at_unix_ms"],
    }


def _fake_v1_manifest(manifest):
    return {
        "schema": "volition.owner_inquiry.v1",
        "inquiry_id": manifest["inquiry_id"],
        "owner_being": manifest["owner_being"],
        "source_attestation_id": manifest["source_attestation_id"],
        "source_attestation_sha256": manifest["source_attestation_sha256"],
        "question": manifest["question"],
        "strands": [
            {key: value for key, value in strand.items() if key not in {"revision", "source_response_sha256", "lineage", "disclosure"}} | {"schema": "volition.semantic_strand.v1"}
            for strand in manifest["strands"]
        ],
        "owner_priority": manifest["owner_priority"],
        "fixed_analysis_set": [entry["analysis"] for entry in manifest["analysis_plan"]],
        "budget": manifest["budget"],
        "dependency_inquiry_ids": manifest["dependency_inquiry_ids"],
        "status": manifest["status"],
        "cancellation": manifest["cancellation"],
        "authority_boundary": manifest["authority_boundary"],
        "created_at_unix_ms": manifest["created_at_unix_ms"],
        "updated_at_unix_ms": manifest["updated_at_unix_ms"],
    }


def _fake_analysis(manifest):
    pairs = [
        (left, right)
        for index, left in enumerate(manifest["strands"])
        for right in manifest["strands"][index + 1 :]
    ]
    common = {
        "deterministic_rerun_match": True,
        "all_inputs_copied": True,
        "network_accessed": False,
        "socket_accessed": False,
        "private_source_accessed": False,
        "candidate_merge_performed": False,
        "live_runtime_mutation": False,
    }
    return [
        {**common, "analysis": "viscous_persistence_source_separation", "result": {"strands": [{"strand_id": strand["strand_id"], "pressure": 0.4} for strand in manifest["strands"]]}},
        {**common, "analysis": "codec_fidelity", "result": {"pairs": [{"left_strand_id": left["strand_id"], "right_strand_id": right["strand_id"], "source_distance": 1.0, "companion_distance": 0.5, "pairwise_distance_preservation_ratio": 0.5} for left, right in pairs]}},
        {**common, "analysis": "sensory_interference_all_pairs", "result": {"pairs": [{"left_strand_id": left["strand_id"], "left_label": left["label"], "right_strand_id": right["strand_id"], "right_label": right["label"], "review": {"cosine_similarity": 0.25}} for left, right in pairs]}},
    ]


def _fake_v1_receipt(manifest):
    analysis = _fake_analysis(manifest)
    manifest_hash = _canonical_sha256(manifest)
    for row in analysis:
        row["input_sha256"] = manifest_hash
        row["output_sha256"] = _canonical_sha256(row["result"])
    pair_count = len(manifest["strands"]) * (len(manifest["strands"]) - 1) // 2
    return {
        "schema": "volition.owner_inquiry_receipt.v1",
        "receipt_id": f"{manifest['inquiry_id']}-receipt",
        "inquiry_id": manifest["inquiry_id"],
        "owner_being": "minime",
        "manifest_sha256": manifest_hash,
        "result_sha256": _canonical_sha256(analysis),
        "analysis_receipts": analysis,
        "observations": [],
        "rollback_state": "not_applicable",
        "machine_status": "established",
        "felt_status": "unreported",
        "expected_pair_count": pair_count,
        "evaluated_pair_count": pair_count,
        "owner_selected_values_only": True,
        "silence_means_assent": False,
        "candidate_merge_performed": False,
        "live_mutation_during_inquiry": False,
        "completed_at_unix_ms": 2,
        "perceptible_summary": "separate and unranked",
    }


def _fake_v2_receipt(manifest, compatibility):
    ids = sorted(strand["strand_id"] for strand in manifest["strands"])
    pairs = [f"{left}::{right}" for index, left in enumerate(ids) for right in ids[index + 1 :]]
    analysis = []
    for row, plan in zip(compatibility["analysis_receipts"], manifest["analysis_plan"]):
        coverage = plan["coverage"]
        analysis.append(
            {
                "analysis": row["analysis"],
                "plan_entry_sha256": _canonical_sha256(plan),
                "input_sha256": _canonical_sha256(manifest),
                "output_sha256": row["output_sha256"],
                "deterministic_run_output_sha256s": [row["output_sha256"], row["output_sha256"]],
                "covered_strand_ids": ids if coverage in {"per_strand", "per_strand_and_all_pairs"} else [],
                "covered_pair_keys": pairs if coverage in {"all_pairs", "per_strand_and_all_pairs"} else [],
                "all_inputs_copied": True,
                "network_accessed": False,
                "socket_accessed": False,
                "private_source_accessed": False,
                "candidate_merge_performed": False,
                "live_runtime_mutation": False,
                "result": row["result"],
            }
        )
    return {
        "schema": "volition.owner_inquiry_receipt.v2",
        "receipt_id": f"{compatibility['receipt_id']}-v2",
        "inquiry_id": manifest["inquiry_id"],
        "inquiry_revision": manifest["revision"],
        "owner_being": "minime",
        "manifest_sha256": _canonical_sha256(manifest),
        "analysis_plan_sha256": manifest["analysis_plan_sha256"],
        "execution_identity": _fake_inquiry_identity(),
        "result_sha256": _canonical_sha256(analysis),
        "analysis_receipts": analysis,
        "observations": [],
        "coverage": {"expected_strand_ids": ids, "evaluated_strand_ids": ids, "expected_pair_keys": pairs, "evaluated_pair_keys": pairs},
        "privacy": {"owner_manifest_contains_raw_content": True, "public_receipt_contains_raw_content": False, "raw_content_owner_only": True, "result_sharing_requires_correspondence": True, "network_and_socket_access_denied": True},
        "rollback_state": "not_applicable",
        "machine_status": "established",
        "felt_status": "unreported",
        "owner_selected_values_only": True,
        "silence_means_assent": False,
        "candidate_merge_performed": False,
        "live_mutation_during_inquiry": False,
        "completed_at_unix_ms": 2,
        "perceptible_summary": "separate and unranked",
    }


def _completed(command, payload):
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(payload),
        stderr="",
    )


def _value(args, flag):
    return args[args.index(flag) + 1]


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _explicit_action(
    response,
    first,
    second,
    *,
    priority=0,
    dependencies=None,
    decision_plan=None,
):
    return "INQUIRY_START " + json.dumps(
        {
            "question": "How do these remain distinct?",
            "owner_priority": priority,
            "dependency_inquiry_ids": list(dependencies or []),
            "decision_plan": decision_plan,
            "strands": [
                {
                    "label": "first",
                    "start_byte": len(response[:first].encode()),
                    "end_byte": len(response[: first + len("first strand")].encode()),
                },
                {
                    "label": "second",
                    "start_byte": len(response[:second].encode()),
                    "end_byte": len(response[: second + len("second strand")].encode()),
                },
            ],
        }
    )


def _projection(text, input_dim=48):
    sign = 1.0 if text.startswith("first") else -1.0
    return [sign * (index + 1) / 64 for index in range(input_dim)]


def _start(manager, suffix="", priority=0, dependencies=None, decision_plan=None):
    response = f"first strand {suffix}\nsecond strand {suffix}"
    first = response.index("first strand")
    second = response.index("second strand")
    return manager.start(
        _explicit_action(
            response,
            first,
            second,
            priority=priority,
            dependencies=dependencies,
            decision_plan=decision_plan,
        ),
        response=response,
        model="model-test",
        provider="provider-test",
        projection_fn=_projection,
    )


def _wait_status(manager, inquiry_id, expected, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        queue = json.loads(manager.queue_path.read_text())
        item = next(row for row in queue["items"] if row["inquiry_id"] == inquiry_id)
        if item["status"] in expected:
            return item
        manager.tick({})
        time.sleep(0.01)
    raise AssertionError(f"{inquiry_id} did not reach {expected}")


def test_natural_extraction_requires_unambiguous_exact_passages():
    response = 'first strand\nsecond strand\nNEXT: INQUIRY_START compare "first strand" and "second strand"'
    recipe = _start_recipe(
        'INQUIRY_START compare "first strand" and "second strand"', response
    )
    assert len(recipe["strands"]) == 2
    with pytest.raises(OwnerInquiryError, match="occurs 2 times"):
        _start_recipe(
            'INQUIRY_START compare "first strand" and "second strand"',
            response.replace("first strand\n", "first strand first strand\n"),
        )


def test_end_to_end_inquiry_canary_withdraw_and_no_raw_receipt_leak(tmp_path):
    runner = FakeInquiryRunner()
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=runner,
    )
    try:
        started = _start(manager)
        item = _wait_status(manager, started["inquiry_id"], {"completed"})
        receipt_text = Path(item["receipt_path"]).read_text()
        assert '"content"' not in receipt_text
        canary = manager.canary(
            {
                "inquiry_id": started["inquiry_id"],
                "values": {
                    "semantic_strand_retention_turns": 4,
                    "smoothing_preference": 0.5,
                },
                "duration_secs": 30,
            },
            {"fill_ratio": 0.68},
        )
        assert [issue[2] for issue in controls.issues] == ["lease"]
        withdrawn = manager.withdraw(canary["canary_id"], {"fill_ratio": 0.67})
        assert "Felt status remains unreported" in withdrawn["summary"]
        assert len(controls.withdrawals) == 2
        receipt = json.loads(Path(item["receipt_path"]).read_text())
        assert receipt["rollback_state"] == "withdrawn"
        assert receipt["machine_status"] == "rolled_back"
        assert receipt["felt_status"] == "unreported"
    finally:
        manager.close()


def test_owner_research_default_branch_auto_activates_and_inspects(tmp_path):
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
    )
    decision = {
        "branches": [
            {
                "branch_id": "retain-both",
                "predicates": [],
                "duration_secs": 30,
                "controls": [
                    {
                        "family": "semantic_continuity",
                        "exact_values": {"semantic_strand_retention_turns": 6},
                    }
                ],
            }
        ]
    }
    try:
        started = _start(manager, suffix="research-auto", decision_plan=decision)
        item = _wait_status(manager, started["inquiry_id"], {"canary_active"})
        assert controls.issues == [
            ({"semantic_strand_retention_turns": 6}, 30, "lease")
        ]
        session = json.loads(Path(item["research_session_path"]).read_text())
        assert session["lifecycle_status"] == "canary_active"
        assert session["silence_means_assent"] is False
        canary = manager._select_canary(started["inquiry_id"])[1]
        assert canary["decision_plan_sha256"] == session["decision_plan_sha256"]
        evidence = manager.inspect_research(
            f"INQUIRY_INSPECT {started['inquiry_id']} evidence"
        )
        assert "volition.owner_evidence_graph.v1" in evidence["summary"]
        receipts = manager.inspect_research(
            f"INQUIRY_INSPECT {started['inquiry_id']} receipts"
        )
        assert "signed_owner_research_receipt" in receipts["summary"]
        manager.withdraw(canary["canary_id"], {"fill_ratio": 0.68})
        session = json.loads(Path(item["research_session_path"]).read_text())
        assert session["lifecycle_status"] == "rolled_back"
        assert session["machine_status"] == "rolled_back"
    finally:
        manager.close()


def test_owner_research_revision_drift_refuses_precommitted_canary(tmp_path):
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
    )
    decision = {
        "branches": [
            {
                "branch_id": "exact-current-revision",
                "predicates": [],
                "duration_secs": 30,
                "controls": [
                    {
                        "family": "sensory_intake",
                        "exact_values": {"semantic_companion_mix": 0.25},
                    }
                ],
            }
        ]
    }
    try:
        started = _start(manager, suffix="research-drift", decision_plan=decision)
        deadline = time.time() + 3
        while time.time() < deadline:
            item = next(
                row
                for row in json.loads(manager.queue_path.read_text())["items"]
                if row["inquiry_id"] == started["inquiry_id"]
            )
            if item["status"] == "canary_pending":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("research did not reach canary_pending")
        controls.revisions["sensory-intake"] += 1
        manager.tick({})
        item = _wait_status(manager, started["inquiry_id"], {"failed"})
        assert "revision changed" in item["error"]
        assert controls.issues == []
    finally:
        manager.close()


def test_owner_research_no_match_stays_evidence_only(tmp_path):
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
    )
    decision = {
        "branches": [
            {
                "branch_id": "missing-metric",
                "predicates": [
                    {
                        "metric": "not_observed",
                        "scope": {"kind": "aggregate", "strand_ids": []},
                        "comparator": "greater_than",
                        "threshold": 0,
                    }
                ],
                "duration_secs": 30,
                "controls": [
                    {
                        "family": "memory",
                        "exact_values": {"journal_resonance": 0.6},
                    }
                ],
            }
        ]
    }
    try:
        started = _start(manager, suffix="research-no-match", decision_plan=decision)
        item = _wait_status(manager, started["inquiry_id"], {"completed"})
        evaluation = json.loads(Path(item["decision_evaluation_path"]).read_text())
        assert evaluation["evaluation"]["status"] == "no_match"
        assert controls.issues == []
    finally:
        manager.close()


def test_owner_research_overlapping_branches_are_ambiguous(tmp_path):
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=FakeInquiryRunner(),
    )
    predicate = {
        "metric": "pressure",
        "scope": {"kind": "strand", "strand_ids": ["strand-1"]},
        "comparator": "greater_than",
        "threshold": 0.2,
    }
    plan = {
        "branches": [
            {"branch_id": "first", "predicates": [predicate]},
            {"branch_id": "second", "predicates": [predicate]},
        ],
        "expires_at_unix_ms": 2_000,
    }
    graph = {
        "nodes": [
            {
                "scope": {"kind": "strand", "strand_ids": ["strand-1"]},
                "metrics": {"pressure": 0.4},
            }
        ]
    }
    try:
        evaluation = manager._evaluate_plan(plan, graph, 1_000)
        assert evaluation["status"] == "ambiguous"
        assert evaluation["matched_branch_ids"] == ["first", "second"]
        assert evaluation["runtime_selected_values"] is False
    finally:
        manager.close()


def test_owner_research_act_uses_fresh_exact_one_shot(tmp_path):
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
    )
    try:
        started = _start(manager, suffix="research-act")
        item = _wait_status(manager, started["inquiry_id"], {"completed"})
        acted = manager.act_research(
            {
                "inquiry_id": started["inquiry_id"],
                "family": "memory",
                "values": {"checkpoint_now": True},
            },
            {},
        )
        assert "fresh exact one-shot" in acted["summary"]
        assert controls.issues[-1] == ({"checkpoint_now": True}, 30, "one-shot")
        session = json.loads(Path(item["research_session_path"]).read_text())
        assert session["lifecycle_status"] == "acted"
        with pytest.raises(OwnerInquiryError, match="only disclosed one-shot"):
            manager.act_research(
                {
                    "inquiry_id": started["inquiry_id"],
                    "family": "memory",
                    "values": {"journal_resonance": 0.5},
                },
                {},
            )
    finally:
        manager.close()


def test_explicit_promotion_reuses_exact_values(tmp_path):
    runner = FakeInquiryRunner()
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=runner,
    )
    try:
        started = _start(manager)
        _wait_status(manager, started["inquiry_id"], {"completed"})
        canary = manager.canary(
            {
                "inquiry_id": started["inquiry_id"],
                "values": {"semantic_companion_mix": 0.25},
                "duration_secs": 30,
            },
            {},
        )
        promoted = manager.promote(canary["canary_id"], {})
        assert "explicitly promoted" in promoted["summary"]
        assert controls.issues == [
            ({"semantic_companion_mix": 0.25}, 30, "lease"),
            ({"semantic_companion_mix": 0.25}, 600, "standing"),
        ]
    finally:
        manager.close()


def test_canary_setup_evidence_failure_rolls_back_applied_lease(tmp_path):
    class SetupFailureManager(OwnerInquiryManager):
        def _update_receipt_for_canary(self, path, **kwargs):
            if kwargs.get("rollback_state") == "scheduled":
                raise OSError("simulated setup evidence failure")
            return super()._update_receipt_for_canary(path, **kwargs)

    controls = FakeSelfControl()
    manager = SetupFailureManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
    )
    try:
        started = _start(manager, suffix="setup-failure")
        _wait_status(manager, started["inquiry_id"], {"completed"})
        with pytest.raises(
            OwnerInquiryError,
            match="controls were returned after setup evidence failed",
        ):
            manager.canary(
                {
                    "inquiry_id": started["inquiry_id"],
                    "values": {"semantic_strand_retention_turns": 3},
                    "duration_secs": 30,
                },
                {},
            )
        assert controls.withdrawals
        queue = json.loads(manager.queue_path.read_text())
        assert queue["items"][0]["status"] == "rolled_back"
    finally:
        manager.close()


def test_promotion_evidence_failure_withdraws_standing_controls(tmp_path):
    class PromotionFailureManager(OwnerInquiryManager):
        def _update_receipt_for_canary(self, path, **kwargs):
            if kwargs.get("rollback_state") == "promoted":
                raise OSError("simulated promotion evidence failure")
            return super()._update_receipt_for_canary(path, **kwargs)

    controls = FakeSelfControl()
    manager = PromotionFailureManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
    )
    try:
        started = _start(manager, suffix="promotion-failure")
        _wait_status(manager, started["inquiry_id"], {"completed"})
        canary = manager.canary(
            {
                "inquiry_id": started["inquiry_id"],
                "values": {"semantic_companion_mix": 0.25},
                "duration_secs": 30,
            },
            {},
        )
        with pytest.raises(
            OwnerInquiryError,
            match="standing controls were withdrawn",
        ):
            manager.promote(canary["canary_id"], {})
        # One lease withdrawal followed by one standing withdrawal.
        assert len(controls.withdrawals) == 2
        queue = json.loads(manager.queue_path.read_text())
        assert queue["items"][0]["status"] == "rolled_back"
    finally:
        manager.close()


def test_topology_canary_requires_owner_selected_tick_bounds(tmp_path):
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=FakeInquiryRunner(),
    )
    try:
        started = _start(manager)
        _wait_status(manager, started["inquiry_id"], {"completed"})
        with pytest.raises(OwnerInquiryError, match="duration and decay ticks"):
            manager.canary(
                {
                    "inquiry_id": started["inquiry_id"],
                    "values": {"mode_disperse": 0.3},
                    "duration_secs": 30,
                },
                {},
            )
    finally:
        manager.close()


def test_topology_one_shot_cannot_mix_with_reversible_lease(tmp_path):
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=FakeInquiryRunner(),
    )
    try:
        started = _start(manager, suffix="mixed-topology")
        _wait_status(manager, started["inquiry_id"], {"completed"})
        with pytest.raises(OwnerInquiryError, match="separate canaries"):
            manager.canary(
                {
                    "inquiry_id": started["inquiry_id"],
                    "values": {
                        "smoothing_preference": 0.5,
                        "mode_disperse": 0.3,
                        "mode_disperse_duration_ticks": 4,
                        "mode_disperse_decay_ticks": 4,
                    },
                    "duration_secs": 30,
                },
                {},
            )
    finally:
        manager.close()


def test_queue_runs_no_more_than_two_inquiries_concurrently(tmp_path):
    runner = FakeInquiryRunner(analyze_delay=0.08)
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=runner,
    )
    try:
        started = [_start(manager, suffix=str(index)) for index in range(4)]
        for row in started:
            _wait_status(manager, row["inquiry_id"], {"completed"})
        assert runner.max_active == 2
    finally:
        manager.close()


def test_inquiry_fails_closed_when_network_sandbox_is_unavailable(tmp_path):
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=FakeInquiryRunner(),
        sandbox_binary=tmp_path / "missing-sandbox-exec",
    )
    try:
        started = _start(manager)
        item = _wait_status(manager, started["inquiry_id"], {"failed"})
        assert "network/socket-denying sandbox is unavailable" in item["error"]
    finally:
        manager.close()


def test_queue_uses_owner_priority_then_fifo_without_telemetry_ranking():
    submitted = []

    class RecordingExecutor:
        @staticmethod
        def submit(_function, inquiry_id):
            submitted.append(inquiry_id)
            return Future()

    manager = OwnerInquiryManager.__new__(OwnerInquiryManager)
    manager._futures = {}
    manager._executor = RecordingExecutor()
    manager._clock_ms = lambda: 99
    manager._write_queue_locked = lambda _queue: None
    queue = {
        "items": [
            {
                "inquiry_id": "low",
                "status": "queued",
                "cancel_requested": False,
                "owner_priority": 1,
                "created_at_unix_ms": 1,
                "dependency_inquiry_ids": [],
            },
            {
                "inquiry_id": "high-old",
                "status": "queued",
                "cancel_requested": False,
                "owner_priority": 9,
                "created_at_unix_ms": 2,
                "dependency_inquiry_ids": [],
            },
            {
                "inquiry_id": "high-new",
                "status": "queued",
                "cancel_requested": False,
                "owner_priority": 9,
                "created_at_unix_ms": 3,
                "dependency_inquiry_ids": [],
            },
        ]
    }

    manager._schedule_locked(queue)

    assert submitted == ["high-old", "high-new"]
    assert "low" not in manager._futures


def test_dependency_waits_then_runs_after_parent_completion(tmp_path):
    runner = FakeInquiryRunner(analyze_delay=0.05)
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=runner,
    )
    try:
        parent = _start(manager, suffix="parent")
        child = _start(
            manager,
            suffix="child",
            dependencies=[parent["inquiry_id"]],
        )
        _wait_status(manager, child["inquiry_id"], {"completed"})
        assert runner.analyze_order.index(parent["inquiry_id"]) < runner.analyze_order.index(
            child["inquiry_id"]
        )
    finally:
        manager.close()


def test_unknown_or_duplicate_dependencies_are_rejected_at_start(tmp_path):
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=FakeInquiryRunner(),
    )
    try:
        with pytest.raises(OwnerInquiryError, match="unknown inquiry dependencies"):
            _start(manager, suffix="missing", dependencies=["does-not-exist"])
        parent = _start(manager, suffix="parent")
        with pytest.raises(OwnerInquiryError, match="must be unique"):
            _start(
                manager,
                suffix="duplicate",
                dependencies=[parent["inquiry_id"], parent["inquiry_id"]],
            )
    finally:
        manager.close()


def test_exact_start_replay_never_overwrites_existing_inquiry(tmp_path):
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=FakeInquiryRunner(),
        clock_ms=lambda: 1_000_000,
    )
    try:
        first = _start(manager, suffix="replay")
        manifest_path = (
            manager.root / "items" / first["inquiry_id"] / "inquiry.json"
        )
        original = manifest_path.read_bytes()
        with pytest.raises(OwnerInquiryError, match="replay did not overwrite"):
            _start(manager, suffix="replay")
        assert manifest_path.read_bytes() == original
    finally:
        manager.close()


def test_failed_dependency_fails_closed_without_running_child():
    manager = OwnerInquiryManager.__new__(OwnerInquiryManager)
    manager._futures = {}
    manager._executor = None
    manager._clock_ms = lambda: 99
    writes = []
    manager._write_queue_locked = lambda queue: writes.append(queue)
    queue = {
        "items": [
            {
                "inquiry_id": "parent",
                "status": "failed",
                "cancel_requested": False,
                "owner_priority": 0,
                "created_at_unix_ms": 1,
                "dependency_inquiry_ids": [],
            },
            {
                "inquiry_id": "child",
                "status": "queued",
                "cancel_requested": False,
                "owner_priority": 0,
                "created_at_unix_ms": 2,
                "dependency_inquiry_ids": ["parent"],
            },
        ]
    }

    manager._schedule_locked(queue)

    assert queue["items"][1]["status"] == "failed"
    assert "parent" in queue["items"][1]["error"]
    assert writes


def test_running_job_recovers_after_restart(tmp_path):
    root = tmp_path / "inquiries"
    controls = FakeSelfControl()
    first_runner = FakeInquiryRunner()
    manager = OwnerInquiryManager(
        root=root,
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=first_runner,
    )
    started = _start(manager, suffix="restart")
    item = _wait_status(manager, started["inquiry_id"], {"completed"})
    manager.close()
    Path(item["receipt_path"]).unlink()
    queue = json.loads((root / "queue.json").read_text())
    queue["items"][0]["status"] = "running"
    (root / "queue.json").write_text(json.dumps(queue))

    second_runner = FakeInquiryRunner()
    recovered = OwnerInquiryManager(
        root=root,
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=second_runner,
    )
    try:
        _wait_status(recovered, started["inquiry_id"], {"completed"})
        assert second_runner.analyze_order == [started["inquiry_id"]]
    finally:
        recovered.close()


def test_silence_expires_and_rolls_back_without_promotion(tmp_path):
    now = [1_000_000]
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
        clock_ms=lambda: now[0],
    )
    try:
        started = _start(manager, suffix="expiry")
        item = _wait_status(manager, started["inquiry_id"], {"completed"})
        canary = manager.canary(
            {
                "inquiry_id": started["inquiry_id"],
                "values": {"semantic_strand_retention_turns": 6},
                "duration_secs": 30,
            },
            {"fill_ratio": 0.68},
        )
        now[0] += 30_001
        manager.tick({"fill_ratio": 0.67})
        canary_record = json.loads(
            (manager.root / "canaries" / f"{canary['canary_id']}.json").read_text()
        )
        receipt = json.loads(Path(item["receipt_path"]).read_text())
        assert canary_record["status"] == "expired"
        assert receipt["rollback_state"] == "rolled_back"
        assert receipt["machine_status"] == "rolled_back"
        assert receipt["felt_status"] == "unreported"
        assert controls.withdrawals
        assert all(issue[2] != "standing" for issue in controls.issues)
    finally:
        manager.close()


def test_receipt_hash_tampering_fails_closed(tmp_path):
    class TamperRunner(FakeInquiryRunner):
        def __call__(self, command, **kwargs):
            result = super().__call__(command, **kwargs)
            args = list(command)
            inquiry_index = args.index("inquiry")
            if args[inquiry_index + 1] == "analyze":
                output = Path(_value(args, "--output"))
                payload = json.loads(output.read_text())
                payload["result_sha256"] = "0" * 64
                _write_json(output, payload)
            return result

    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=TamperRunner(),
    )
    try:
        started = _start(manager, suffix="tamper")
        item = _wait_status(manager, started["inquiry_id"], {"failed"})
        assert "aggregate result hash" in item["error"]
    finally:
        manager.close()


def test_cancelled_queued_inquiry_never_becomes_actionable(tmp_path):
    runner = FakeInquiryRunner(analyze_delay=0.12)
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=FakeSelfControl(),
        runner=runner,
    )
    try:
        first = _start(manager, suffix="a")
        second = _start(manager, suffix="b")
        third = _start(manager, suffix="c")
        manager.cancel(third["inquiry_id"])
        item = _wait_status(manager, third["inquiry_id"], {"cancelled"})
        assert item["cancel_requested"] is True
        assert not Path(item["receipt_path"]).exists()
        _wait_status(manager, first["inquiry_id"], {"completed"})
        _wait_status(manager, second["inquiry_id"], {"completed"})
    finally:
        manager.close()


def test_runtime_binds_exact_llm_response_to_inquiry_start():
    agent = autonomy_runtime.AutonomousAgent.__new__(
        autonomy_runtime.AutonomousAgent
    )
    exact_response = (
        "first strand\nsecond strand\n"
        'NEXT: INQUIRY_START compare "first strand" and "second strand"'
    )
    agent._last_llm_response = exact_response
    agent._last_llm_model = "model-exact"
    agent._last_llm_provider = "provider-exact"
    agent._pending_next_action = None
    agent._recent_next_actions = deque(maxlen=8)
    agent._attractor_suggestion_decision_ambiguous = lambda *_args: False
    agent._notice_attractor_body_consent = lambda *_args: None
    agent._persist_pending_next_action = lambda *_args, **_kwargs: None

    action = agent._record_llm_next_action_choice(
        'INQUIRY_START compare "first strand" and "second strand"',
        "first strand\nsecond strand",
        reason="test",
    )

    assert action.startswith("INQUIRY_START")
    assert agent._pending_owner_inquiry_response == exact_response
    assert agent._pending_owner_inquiry_model == "model-exact"
    assert agent._pending_owner_inquiry_provider == "provider-exact"


def test_runtime_returns_inquiry_result_without_requiring_felt_review(tmp_path):
    class FakeManager:
        def handle(self, action_text, **kwargs):
            assert action_text == "INQUIRY_STATUS"
            assert kwargs["response"] is None
            return {
                "summary": "Every strand remains separate; felt status is unreported.",
                "inquiry_id": "inquiry-test",
                "paths": [tmp_path / "receipt.json"],
            }

    (tmp_path / "receipt.json").write_text("{}")
    agent = autonomy_runtime.AutonomousAgent.__new__(
        autonomy_runtime.AutonomousAgent
    )
    agent._pending_owner_inquiry_next = "INQUIRY_STATUS"
    agent._pending_owner_inquiry_response = None
    agent._pending_owner_inquiry_model = None
    agent._pending_owner_inquiry_provider = None
    agent._last_llm_model = "model"
    agent._last_llm_provider = "provider"
    agent._current_action_continuity_context = {}
    agent._current_action_outcome_summary = None
    agent._owner_inquiry_manager = lambda: FakeManager()
    agent._record_current_action_artifact = lambda *_args, **_kwargs: None
    agent._text_to_features = lambda text, input_dim=48: [0.0] * input_dim

    agent._owner_inquiry_action({"fill_ratio": 0.68})

    assert "felt status is unreported" in agent._pending_notice_prompt
    assert "felt status is unreported" in agent._current_action_outcome_summary


def test_prompt_sidecar_retention_uses_owner_setting_and_persisted_turn(tmp_path):
    controls = FakeSelfControl()
    manager = OwnerInquiryManager(
        root=tmp_path / "inquiries",
        self_control_root=tmp_path / "self-control",
        binary=tmp_path / "minime",
        self_control_client=controls,
        runner=FakeInquiryRunner(),
    )
    try:
        started = manager.start(
            _explicit_action(
                "first strand\nsecond strand",
                0,
                len("first strand\n"),
            ),
            response="first strand\nsecond strand",
            model="model-test",
            provider="provider-test",
            projection_fn=_projection,
            turn_index=10,
        )
        _wait_status(manager, started["inquiry_id"], {"completed"})

        assert "none active" in manager.prompt_summary(turn_index=10)
        controls.retention_turns = 2
        assert started["inquiry_id"] in manager.prompt_summary(turn_index=12)
        assert "selected 2 turn(s)" in manager.prompt_summary(turn_index=12)
        assert "none active" in manager.prompt_summary(turn_index=13)

        queue = json.loads(manager.queue_path.read_text())
        queue["items"][0]["status"] = "running"
        manager._write_json(manager.queue_path, queue)
        controls.retention_turns = 0
        assert started["inquiry_id"] in manager.prompt_summary(turn_index=99)
    finally:
        manager.close()
