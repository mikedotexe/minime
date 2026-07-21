import json
import time
from pathlib import Path

import pytest

import autonomous_agent as aa
from minime_autonomy.division_actions import (
    DivisionActionError,
    DivisionActionStore,
    division_action_availability,
)


def command(action: str, *, being: str = "minime", key: str = "division-key-1") -> dict:
    now = int(time.time() * 1000)
    return {
        "schema": "division.command.v1",
        "action": action,
        "division_id": "division-minime-test",
        "idempotency_key": key,
        "expected_parent_generation": 4,
        "plan_digest": "b" * 64,
        "source": {
            "being": being,
            "process_identity": "minime-autonomy:test",
            "deployment_identity": "local-test",
        },
        "requested_at_unix_ms": now,
        "expires_at_unix_ms": now + 60_000,
    }


def write_command(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "command.json"
    path.write_text(json.dumps(payload))
    return path


def enable_native_rehearsal(store: DivisionActionStore) -> None:
    store.division_dir.mkdir(parents=True, exist_ok=True)
    store.status_path.write_text(
        json.dumps(
            {
                "schema": "division.status.v1",
                "lifecycle": "idle",
                "parent_authoritative": True,
                "commit_feature_enabled": False,
                "rehearsal_dispatch_enabled": True,
                "readiness": {
                    "ready": False,
                    "blocking_reasons": ["division_not_prepared"],
                },
            }
        )
    )


def test_status_is_read_only_when_native_runtime_has_not_started(tmp_path: Path) -> None:
    result = DivisionActionStore(tmp_path).handle("DIVISION_STATUS")

    assert result["kind"] == "status"
    assert result["status"]["parent_authoritative"] is True
    assert result["status"]["commit_feature_enabled"] is False
    assert result["status"]["readiness"]["blocking_reasons"] == [
        "native_status_unavailable"
    ]
    card = result["status"]["action_availability_v1"]["minime"]
    assert card["recommended_action"] == "DIVISION_STATUS"
    assert [entry["action"] for entry in card["available_actions"]] == [
        "DIVISION_STATUS",
    ]
    prepare = next(
        entry for entry in card["blocked_actions"]
        if entry["action"] == "DIVISION_PREPARE"
    )
    assert prepare["reasons"] == ["rehearsal_feature_disabled"]


def test_action_availability_tracks_assent_commit_and_rollback_windows() -> None:
    status = {
        "schema": "division.status.v1",
        "division_id": "division-minime-test",
        "lifecycle": "shadowing",
        "parent_authoritative": True,
        "commit_feature_enabled": False,
        "rehearsal_dispatch_enabled": True,
        "astrid_assent": False,
        "minime_assent": False,
        "current_tick": 600,
        "rollback_deadline_tick": None,
        "readiness": {"ready": False},
    }
    shadow = division_action_availability(status, being="minime")
    assert shadow["recommended_action"] == "DIVISION_ASSENT"
    assert {entry["action"] for entry in shadow["available_actions"]} == {
        "DIVISION_STATUS",
        "DIVISION_ASSENT",
        "DIVISION_ABORT",
    }

    status.update(
        lifecycle="ready",
        commit_feature_enabled=True,
        astrid_assent=True,
        minime_assent=True,
        readiness={"ready": True},
    )
    ready = division_action_availability(status, being="minime")
    assert ready["recommended_action"] == "DIVISION_COMMIT"
    commit = next(
        entry
        for entry in ready["available_actions"]
        if entry["action"] == "DIVISION_COMMIT"
    )
    assert commit["requires_operator_capability"] is True

    status.update(
        lifecycle="cytokinesis",
        parent_authoritative=False,
        current_tick=700,
        rollback_deadline_tick=1200,
    )
    grace = division_action_availability(status, being="minime")
    assert any(
        entry["action"] == "DIVISION_ROLLBACK"
        for entry in grace["available_actions"]
    )

    status["current_tick"] = 1201
    expired = division_action_availability(status, being="minime")
    rollback_block = next(
        entry
        for entry in expired["blocked_actions"]
        if entry["action"] == "DIVISION_ROLLBACK"
    )
    assert rollback_block["reasons"] == ["rollback_window_expired"]


def test_operator_ack_without_native_rehearsal_build_cannot_open_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINIME_DIVISION_REHEARSAL_ENABLED", "true")
    store = DivisionActionStore(tmp_path / "workspace")
    artifact = write_command(tmp_path, command("DIVISION_PREPARE"))

    with pytest.raises(DivisionActionError, match="running native Minime build"):
        store.handle(f"DIVISION_PREPARE {artifact}")
    assert not store.inbox_dir.exists()


def test_prepare_requires_exact_artifact_and_queues_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINIME_DIVISION_REHEARSAL_ENABLED", "true")
    store = DivisionActionStore(tmp_path / "workspace")
    enable_native_rehearsal(store)
    artifact = write_command(tmp_path, command("DIVISION_PREPARE"))

    first = store.handle(f"DIVISION_PREPARE {artifact}")
    duplicate = store.handle(f"DIVISION_PREPARE {artifact}")

    queued = Path(first["inbox_path"])
    assert queued.is_file()
    assert first == duplicate
    assert json.loads(queued.read_text())["source"]["being"] == "minime"
    assert not list(queued.parent.glob("*.tmp-*"))


def test_command_source_expiry_and_action_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINIME_DIVISION_REHEARSAL_ENABLED", "true")
    store = DivisionActionStore(tmp_path / "workspace")
    enable_native_rehearsal(store)
    wrong_source = write_command(
        tmp_path, command("DIVISION_PREPARE", being="astrid")
    )
    with pytest.raises(DivisionActionError, match="issued by Minime"):
        store.handle(f"DIVISION_PREPARE {wrong_source}")

    stale = command("DIVISION_ASSENT", key="stale")
    stale["expires_at_unix_ms"] = stale["requested_at_unix_ms"] - 1
    stale_path = write_command(tmp_path, stale)
    with pytest.raises(DivisionActionError, match="expired"):
        store.handle(f"DIVISION_ASSENT {stale_path}")

    mismatch = command("DIVISION_ABORT", key="mismatch")
    mismatch_path = write_command(tmp_path, mismatch)
    with pytest.raises(DivisionActionError, match="does not match"):
        store.handle(f"DIVISION_ASSENT {mismatch_path}")


def test_commit_requires_exact_one_shot_human_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINIME_DIVISION_REHEARSAL_ENABLED", "true")
    store = DivisionActionStore(tmp_path / "workspace")
    enable_native_rehearsal(store)
    payload = command("DIVISION_COMMIT", key="commit")
    artifact = write_command(tmp_path, payload)
    with pytest.raises(DivisionActionError, match="requires an exact"):
        store.handle(f"DIVISION_COMMIT {artifact}")

    payload["capability"] = {
        "token_id": "human-token-1",
        "scope": "reservoir_division.commit",
        "division_id": payload["division_id"],
        "expected_parent_generation": payload["expected_parent_generation"],
        "plan_digest": payload["plan_digest"],
        "expires_at_unix_ms": payload["expires_at_unix_ms"],
        "approved_by": "human-operator",
        "one_shot": True,
    }
    artifact.write_text(json.dumps(payload))
    result = store.handle(f"DIVISION_COMMIT {artifact}")
    assert result["kind"] == "queued"


def test_commit_rejects_capability_that_expired_before_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINIME_DIVISION_REHEARSAL_ENABLED", "true")
    store = DivisionActionStore(tmp_path / "workspace")
    enable_native_rehearsal(store)
    payload = command("DIVISION_COMMIT", key="expired-capability")
    payload["capability"] = {
        "token_id": "expired-human-token",
        "scope": "reservoir_division.commit",
        "division_id": payload["division_id"],
        "expected_parent_generation": payload["expected_parent_generation"],
        "plan_digest": payload["plan_digest"],
        "expires_at_unix_ms": payload["requested_at_unix_ms"] + 1,
        "approved_by": "human-operator",
        "one_shot": True,
    }
    artifact = write_command(tmp_path, payload)

    with pytest.raises(DivisionActionError, match="exactly scoped"):
        store.handle(
            f"DIVISION_COMMIT {artifact}",
            now_unix_ms=payload["requested_at_unix_ms"] + 2,
        )


def test_division_routes_and_authority_stages_are_visible() -> None:
    expected = {
        "DIVISION_STATUS": ("division_status", "read_only"),
        "DIVISION_PREPARE": ("division_prepare", "live_control"),
        "DIVISION_ASSENT": ("division_assent", "live_control"),
        "DIVISION_COMMIT": ("division_commit", "live_control"),
        "DIVISION_ABORT": ("division_abort", "live_control"),
        "DIVISION_ROLLBACK": ("division_rollback", "live_control"),
    }
    for base, (route, stage) in expected.items():
        assert aa.ActionPreflightStore.ROUTE_BY_BASE[base] == route
        assert aa.ActionContinuityStore.stage_for_action(base, route) == stage
        assert base in aa.DIVISION_NEXT_ACTIONS

    assert "division_status" in aa.HARD_RESET_ALLOWED_ACTIONS
    assert "division_abort" in aa.HARD_RESET_ALLOWED_ACTIONS
    assert "division_prepare" not in aa.HARD_RESET_ALLOWED_ACTIONS
    assert "division_commit" not in aa.HARD_RESET_ALLOWED_ACTIONS
