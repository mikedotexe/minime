import json

from minime_autonomy.collaboration_attention import (
    ContextSubmissionTracker,
    empty_checkpoint,
    finish_prompt_offer,
    load_checkpoint_file,
    mark_explicit_inspection,
    merge_checkpoint_file,
    prepare_prompt_offer,
)


def _write_room(
    root,
    revision_char="a",
    *,
    actor="astrid",
    event_id="thought:1",
    room_id="coll_test",
    material_t_ms=20,
):
    room = root / room_id
    room.mkdir(parents=True, exist_ok=True)
    (room / "meta.json").write_text(json.dumps({
        "id": room_id,
        "topic": "quiet shared inquiry",
        "status": "joined",
        "inviter": "astrid",
        "invitee": "minime",
        "members": ["astrid", "minime"],
        "updated_t_ms": 10,
    }))
    revision = "sha256:" + revision_char * 64
    (room / "chamber_state.json").write_text(json.dumps({
        "attention_projection_v1": {
            "schema_version": 1,
            "policy": "collaboration_attention_projection_v1",
            "audience_revisions": {
                "minime": {
                    "material_revision": revision,
                    "material_t_ms": material_t_ms,
                    "latest_material_event": {
                        "event_id": event_id,
                        "kind": "shared_thought",
                        "actor": actor,
                    },
                }
            },
        }
    }))
    return revision


def test_migration_baselines_existing_room_without_notice(tmp_path):
    revision = _write_room(tmp_path)
    checkpoint = empty_checkpoint()

    offer, changed = prepare_prompt_offer(tmp_path, checkpoint)

    assert offer is None
    assert changed is True
    assert checkpoint["migration_complete"] is True
    assert checkpoint["satisfied_revisions"]["coll_test"] == revision


def test_new_revision_retries_when_packed_out_then_quiets_after_submission(tmp_path):
    first = _write_room(tmp_path, "a")
    checkpoint = empty_checkpoint()
    checkpoint["migration_complete"] = True
    checkpoint["satisfied_revisions"]["coll_test"] = first
    second = _write_room(tmp_path, "b", event_id="thought:2")

    offer, changed = prepare_prompt_offer(tmp_path, checkpoint)
    assert changed is False
    assert offer is not None
    assert offer.material_revision == second
    assert "No response is required; silence remains neutral" in offer.content
    assert finish_prompt_offer(checkpoint, offer, False) is False

    retry, _ = prepare_prompt_offer(tmp_path, checkpoint)
    assert retry == offer
    assert finish_prompt_offer(checkpoint, retry, True) is True
    assert prepare_prompt_offer(tmp_path, checkpoint) == (None, False)


def test_room_first_seen_after_migration_gets_a_notice(tmp_path):
    checkpoint = empty_checkpoint()
    checkpoint["migration_complete"] = True
    revision = _write_room(tmp_path, "d", room_id="coll_new")

    offer, changed = prepare_prompt_offer(tmp_path, checkpoint)

    assert changed is False
    assert offer is not None
    assert offer.collab_id == "coll_new"
    assert offer.material_revision == revision


def test_pending_rooms_are_offered_in_material_event_order(tmp_path):
    checkpoint = empty_checkpoint()
    checkpoint["migration_complete"] = True
    _write_room(tmp_path, "a", room_id="coll_later", material_t_ms=200)
    _write_room(tmp_path, "b", room_id="coll_earlier", material_t_ms=100)

    offer, _ = prepare_prompt_offer(tmp_path, checkpoint)

    assert offer is not None
    assert offer.collab_id == "coll_earlier"


def test_explicit_inspection_satisfies_the_current_revision(tmp_path):
    revision = _write_room(tmp_path, "e", event_id="thought:3")
    checkpoint = empty_checkpoint()
    checkpoint["migration_complete"] = True
    audit = tmp_path / "audit.jsonl"

    assert prepare_prompt_offer(tmp_path, checkpoint)[0] is not None
    assert mark_explicit_inspection(
        tmp_path,
        checkpoint,
        "coll_test",
        audit_path=audit,
    ) is True
    assert checkpoint["satisfied_revisions"]["coll_test"] == revision
    assert prepare_prompt_offer(tmp_path, checkpoint) == (None, False)
    assert "explicitly_inspected" in audit.read_text()


def test_explicit_inspection_completes_a_fresh_migration_checkpoint(tmp_path):
    revision = _write_room(tmp_path, "f", event_id="thought:4")
    checkpoint = empty_checkpoint()
    checkpoint["satisfied_revisions"]["coll_test"] = revision

    assert mark_explicit_inspection(tmp_path, checkpoint, "coll_test") is True
    assert checkpoint["migration_complete"] is True


def test_submission_tracker_requires_exact_complete_notice():
    exact = "[collab-attention-v1:abc] complete optional notice"
    tracker = ContextSubmissionTracker(exact)
    tracker.mark_final_messages([{"role": "user", "content": "[collab-attention-v1:abc]"}])
    assert tracker.submitted is False

    tracker.mark_final_messages([{"role": "user", "content": f"before\n{exact}\nafter"}])
    assert tracker.submitted is True
    assert exact not in tracker.without_submitted_content(f"prompt\n{exact}")


def test_checkpoint_merge_is_restart_stable_and_preserves_unknown_fields(tmp_path):
    path = tmp_path / "sovereignty_state.json"
    path.write_text(json.dumps({"regime": "hold", "foreign_future_field": {"x": 1}}))
    checkpoint = empty_checkpoint()
    checkpoint["satisfied_revisions"]["coll_test"] = "sha256:" + "c" * 64

    merge_checkpoint_file(path, checkpoint)

    state = json.loads(path.read_text())
    assert state["regime"] == "hold"
    assert state["foreign_future_field"] == {"x": 1}
    assert load_checkpoint_file(path) == checkpoint
