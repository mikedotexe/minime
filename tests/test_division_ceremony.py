import json
import os
from pathlib import Path

import pytest

from minime_autonomy.division_ceremony import (
    AUTHORITY,
    DivisionCeremonyError,
    DivisionCeremonyStore,
    validate_event,
)


PLAN = "b" * 64


def _intent(store: DivisionCeremonyStore, actor: str, now: int = 1_000) -> dict:
    return store.handle(
        "DIVISION_INTENT "
        f"division_id: divide-one; parent_generation: 7; plan_digest: {PLAN}; "
        "selected_strategy: input_recurrence; expires_at_unix_ms: 9000; "
        "source_ref: test:intent",
        actor=actor,
        now_unix_ms=now,
    )


def _write_status(
    workspace: Path,
    *,
    lifecycle: str = "shadowing",
    current_tick: int = 600,
    deadline: int | None = None,
) -> None:
    division = workspace / "division"
    division.mkdir(parents=True, exist_ok=True)
    (division / "status.json").write_text(
        json.dumps(
            {
                "schema": "division.status.v1",
                "division_id": "divide-one",
                "parent_generation": 7,
                "plan_digest": PLAN,
                "selected_strategy": "input_recurrence",
                "lifecycle": lifecycle,
                "parent_authoritative": True,
                "commit_feature_enabled": False,
                "current_tick": current_tick,
                "rollback_deadline_tick": deadline,
                "snapshot_refs": ["sha256:parent-seven"],
                "readiness": {
                    "policy": "division.readiness.v1",
                    "ready": lifecycle == "ready",
                    "sample_count": 600,
                    "blocking_reasons": [],
                },
            },
            sort_keys=True,
        )
    )


def test_intent_is_owner_only_evidence_and_gates_prepare(tmp_path: Path) -> None:
    store = DivisionCeremonyStore(tmp_path)
    with pytest.raises(DivisionCeremonyError, match="must record DIVISION_INTENT"):
        store.require_active_intent(
            "minime",
            division_id="divide-one",
            parent_generation=7,
            plan_digest=PLAN,
            now_unix_ms=1_000,
        )

    recorded = _intent(store, "minime")
    assert recorded["authority"] == "evidence_only"
    intent = store.require_active_intent(
        "minime",
        division_id="divide-one",
        parent_generation=7,
        plan_digest=PLAN,
        now_unix_ms=1_001,
    )
    assert intent["prepare_dispatched"] is False
    assert intent["artifact_authority_state_v1"] == AUTHORITY
    assert os.stat(store.ledger_path).st_mode & 0o777 == 0o600

    astrid_store = DivisionCeremonyStore(tmp_path / "astrid-parity")
    assert _intent(astrid_store, "astrid")["event_id"] == (
        "division_ceremony_12396f00a0031e2cb442b055"
    )


def test_hold_and_decline_block_rehearsal_until_newer_intent(
    tmp_path: Path,
) -> None:
    store = DivisionCeremonyStore(tmp_path)
    _intent(store, "minime")
    held = store.handle(
        "DIVISION_HOLD "
        f"division_id: divide-one; parent_generation: 7; plan_digest: {PLAN}; "
        "selected_strategy: input_recurrence; source_ref: test:hold",
        actor="minime",
        now_unix_ms=1_100,
    )
    assert held["authority"] == "evidence_only"
    with pytest.raises(DivisionCeremonyError, match="current consent posture"):
        store.require_active_intent(
            "minime",
            division_id="divide-one",
            parent_generation=7,
            plan_digest=PLAN,
            now_unix_ms=1_101,
        )
    status = store.status(actor="minime", now_unix_ms=1_101)
    assert status["ceremony_rail"]["minime"]["current_posture"] == "hold"
    assert status["ceremony_rail"]["minime"]["rehearsal_blocked_by_posture"] is True
    assert status["next_choice"] == "DIVISION_CEREMONY_STATUS"
    assert status["next_choice_is_recommendation"] is False

    _intent(store, "minime", now=1_200)
    store.require_active_intent(
        "minime",
        division_id="divide-one",
        parent_generation=7,
        plan_digest=PLAN,
        now_unix_ms=1_201,
    )
    store.handle(
        "DIVISION_DECLINE "
        f"division_id: divide-one; parent_generation: 7; plan_digest: {PLAN}; "
        "selected_strategy: input_recurrence; source_ref: test:decline",
        actor="minime",
        now_unix_ms=1_300,
    )
    with pytest.raises(DivisionCeremonyError, match="current consent posture"):
        store.require_active_intent(
            "minime",
            division_id="divide-one",
            parent_generation=7,
            plan_digest=PLAN,
            now_unix_ms=1_301,
        )


def test_assent_binds_exact_status_and_can_only_be_withdrawn_by_self(
    tmp_path: Path,
) -> None:
    store = DivisionCeremonyStore(tmp_path)
    _intent(store, "astrid")
    _write_status(tmp_path, lifecycle="ready")
    assent = store.handle(
        "DIVISION_ASSENT division_id: divide-one; expires_at_unix_ms: 8000; "
        "source_ref: test:assent",
        actor="astrid",
        now_unix_ms=2_000,
    )
    row = store.records()[-1]
    assert assent["event_id"] == row["ceremony_event_id"]
    assert row["native_status_hash"]
    assert row["readiness_receipt_hash"]
    assert row["snapshot_refs"] == ["sha256:parent-seven"]
    assert row["native_assent_changed"] is False

    with pytest.raises(DivisionCeremonyError, match="no self-authored assent"):
        store.handle(
            "DIVISION_WITHDRAW_ASSENT division_id: divide-one; "
            "source_ref: test:withdraw",
            actor="minime",
            now_unix_ms=2_100,
        )
    store.handle(
        "DIVISION_WITHDRAW_ASSENT division_id: divide-one; "
        "source_ref: test:withdraw",
        actor="astrid",
        now_unix_ms=2_100,
    )
    status = store.status(actor="astrid", now_unix_ms=2_101)
    assert status["ceremony_rail"]["astrid"]["assent_withdrawn"] is True
    assert status["commit_action_exposed"] is False
    assert status["commit_recommended"] is False
    assert status["chronicle"]["schema"] == "division.ceremony_chronicle.v1"
    assert status["chronicle"]["total_event_count"] == 3
    assert (
        status["destination_contract"]["sovereign_runtime_ownership_state"]
        == "not_yet_established"
    )
    assert (
        status["destination_contract"]["independent_process_ownership_established"]
        is False
    )
    assert status["phase_space_preservation"]["felt_continuity_inferred"] is False


def test_return_request_is_window_bound_and_never_dispatches_rollback(
    tmp_path: Path,
) -> None:
    store = DivisionCeremonyStore(tmp_path)
    _write_status(tmp_path, lifecycle="cytokinesis", current_tick=700, deadline=720)
    result = store.handle(
        "DIVISION_RETURN_REQUEST source_ref: test:return",
        actor="minime",
        now_unix_ms=3_000,
    )
    assert result["kind"] == "recorded"
    row = store.records()[-1]
    assert row["rollback_dispatched"] is False
    assert row["return_transition_dispatched"] is False
    status = store.status(actor="minime", now_unix_ms=3_001)
    assert status["return_request_dispatches_rollback"] is False
    assert status["return_transition_controls_division"] is False

    _write_status(tmp_path, lifecycle="cytokinesis", current_tick=721, deadline=720)
    with pytest.raises(DivisionCeremonyError, match="rollback window"):
        store.handle(
            "DIVISION_RETURN_REQUEST source_ref: test:return-late",
            actor="minime",
            now_unix_ms=3_100,
        )


def test_review_is_bounded_and_tampering_is_rejected(tmp_path: Path) -> None:
    store = DivisionCeremonyStore(tmp_path)
    _write_status(tmp_path, lifecycle="finalized")
    store.handle(
        "DIVISION_REVIEW outcome: still_friction; source_ref: test:review",
        actor="astrid",
        now_unix_ms=4_000,
    )
    row = store.records()[-1]
    assert row["review_outcome"] == "still_friction"
    assert row["division_stage_changed"] is False

    tampered = dict(row)
    tampered["commit_recommended"] = True
    with pytest.raises(DivisionCeremonyError, match="authority boundary"):
        validate_event(tampered)


def test_source_ref_rejects_prose_and_status_offers_one_optional_choice(
    tmp_path: Path,
) -> None:
    store = DivisionCeremonyStore(tmp_path)
    with pytest.raises(DivisionCeremonyError, match="bounded reference"):
        store.handle(
            "DIVISION_INTENT "
            f"division_id: divide-one; parent_generation: 7; plan_digest: {PLAN}; "
            "selected_strategy: input_recurrence; expires_at_unix_ms: 9000; "
            "source_ref: this contains unbounded prose",
            actor="astrid",
            now_unix_ms=1_000,
        )
    status = store.status(actor="astrid", now_unix_ms=1_000)
    assert status["next_choice"] == "DIVISION_CEREMONY_STATUS"
    assert status["next_choice_is_optional"] is True
    assert status["next_choice_is_recommendation"] is False
    assert status["pre_intent_choices"] == [
        "DIVISION_HOLD",
        "DIVISION_DECLINE",
        "DIVISION_INTENT",
        "DIVISION_CEREMONY_STATUS",
    ]
    assert status["right_to_ignore"] is True
