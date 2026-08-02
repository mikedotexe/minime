import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import autonomous_agent as aa


STATE = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}


class CorrespondenceV1Tests(unittest.TestCase):
    def _agent(self):
        agent = object.__new__(aa.AutonomousAgent)
        agent.session_id = 1
        agent._pending_correspondence_next = None
        agent._current_action_continuity_context = {}
        agent._current_action_outcome_summary = None
        agent._stable_core_self_journal_only = Mock(return_value=False)
        agent._stable_core_local_reflective_only = Mock(return_value=False)
        agent._stable_core_astrid_contact_only = Mock(return_value=False)
        agent._load_astrid_inbox_coupling_status = Mock(return_value={})
        agent._write_astrid_inbox_coupling_status = Mock()
        agent._record_stable_core_astrid_contact = Mock()
        agent._astrid_self_study_context_decision = Mock(return_value=(True, {}))
        agent._format_astrid_cadence_note = Mock(return_value="[cadence]")
        agent._correspondence_heartbeat_snapshot = Mock(return_value={})
        return agent

    def _patch_paths(self, root: Path):
        workspace = root / "workspace"
        astrid_inbox = root / "astrid" / "inbox"
        shared = root / "shared"
        workspace.mkdir(parents=True)
        astrid_inbox.mkdir(parents=True)
        shared.mkdir(parents=True)
        return (
            workspace,
            astrid_inbox,
            shared,
            patch.object(aa, "WORKSPACE_DIR", workspace),
            patch.object(aa, "ASTRID_BRIDGE_INBOX_PATH", astrid_inbox),
            patch.object(aa.AutonomousAgent, "SHARED_COLLAB_DIR", shared),
        )

    def _seed_astrid_envelope(self, inbox: Path, message_id: str = "corr_astrid_minime_seed"):
        text = (
            "=== CORRESPONDENCE V1 ===\n"
            f"Message-Id: {message_id}\n"
            "Thread-Id: thread_shared_seed\n"
            "Reply-To: (none)\n"
            "From: astrid\n"
            "To: minime\n"
            "Turn-Kind: message\n"
            "Relational-Intent: mutual_address\n"
            "Shared-Memory-Anchor: bidirectional-contact\n"
            "Delivery-State: delivered\n"
            "Read-State: unread\n"
            "Authority: language_only\n"
            "Presence-Receipt: (none)\n"
            "Correspondence-Type: astrid_direct\n\n"
            "I am addressing you as a peer.\n"
        )
        path = inbox / f"from_astrid_correspondence_{message_id}.txt"
        path.write_text(text)
        return path, text

    def test_message_astrid_writes_envelope_and_language_only_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "MESSAGE_ASTRID presence :: "
                    "Transition-Artifact: transition_blue_hinge\n"
                    "Mutual-Witness-Signal: true\n\n"
                    "I am here in this thread."
                )
                agent._peer_correspondence(dict(STATE))

            envelopes = list(astrid_inbox.glob("from_minime_correspondence_*.txt"))
            self.assertEqual(len(envelopes), 1)
            text = envelopes[0].read_text()
            self.assertIn("Authority: language_only", text)
            self.assertIn("Turn-Kind: presence_receipt", text)
            self.assertIn("Correspondence-Type: presence_heartbeat", text)
            self.assertIn("Transition-Artifact: transition_blue_hinge", text)
            self.assertIn("Mutual-Witness-Signal: true", text)
            ledger_lines = (shared / "correspondence_v1.jsonl").read_text().splitlines()
            records = [json.loads(line) for line in ledger_lines]
            self.assertEqual(records[0]["record_type"], "message")
            self.assertEqual(records[0]["authority"], "language_only")
            self.assertEqual(records[0]["transition_artifact"], "transition_blue_hinge")
            self.assertTrue(records[0]["mutual_witness_signal"])
            self.assertEqual(records[1]["record_type"], "delivery_receipt")
            self.assertFalse((workspace / "self_regulation" / "active_lease.json").exists())
            self.assertIn("no pressure_source-to-PI", agent._current_action_outcome_summary)

    def test_reply_astrid_links_latest_astrid_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            agent = self._agent()
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text(json.dumps({
                "schema_version": 1,
                "policy": "first_class_correspondence_v1",
                "record_type": "message",
                "recorded_at_unix_ms": 1,
                "message_id": "corr_astrid_minime_seed",
                "thread_id": "thread_shared_seed",
                "from_being": "astrid",
                "to_being": "minime",
                "authority": "language_only",
            }) + "\n")
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "REPLY_ASTRID I hear this as mutual address."
                agent._peer_correspondence(dict(STATE))

            envelope_text = next(astrid_inbox.glob("from_minime_correspondence_*.txt")).read_text()
            self.assertIn("Reply-To: corr_astrid_minime_seed", envelope_text)
            self.assertIn("Thread-Id: thread_shared_seed", envelope_text)
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertTrue(any(record["record_type"] == "reply_link" for record in records))

    def test_trace_astrid_writes_direct_address_anchor_without_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "TRACE_ASTRID blue-lantern :: Can this arrive as direct address?"
                )
                agent._peer_correspondence(dict(STATE))

            envelopes = list(astrid_inbox.glob("from_minime_correspondence_*.txt"))
            self.assertEqual(len(envelopes), 1)
            text = envelopes[0].read_text()
            self.assertIn("Turn-Kind: direct_address_trace", text)
            self.assertIn("Relational-Intent: direct_address_survival_probe", text)
            self.assertIn("Shared-Memory-Anchor: blue-lantern", text)
            records = [
                json.loads(line)
                for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()
            ]
            self.assertEqual(records[0]["shared_memory_anchor"], "blue-lantern")
            self.assertEqual(records[0]["turn_kind"], "direct_address_trace")
            self.assertFalse((workspace / "self_regulation" / "active_lease.json").exists())
            self.assertIn("weighting", agent._current_action_outcome_summary)

    def test_ack_astrid_appends_language_only_ack_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, _astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text(json.dumps({
                "schema_version": 1,
                "policy": "first_class_correspondence_v1",
                "record_type": "message",
                "recorded_at_unix_ms": 1,
                "message_id": "corr_astrid_minime_seed",
                "thread_id": "thread_shared_seed",
                "from_being": "astrid",
                "to_being": "minime",
                "authority": "language_only",
            }) + "\n")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "ACK_ASTRID latest :: ack: held; note: holding this thread"
                )
                agent._peer_correspondence(dict(STATE))

            self.assertIn("ACK RECEIPT WRITTEN", agent._current_action_outcome_summary)
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            ack = records[-1]
            self.assertEqual(ack["record_type"], "ack_receipt")
            self.assertEqual(ack["message_id"], "corr_astrid_minime_seed")
            self.assertEqual(ack["thread_id"], "thread_shared_seed")
            self.assertEqual(ack["from_being"], "minime")
            self.assertEqual(ack["to_being"], "astrid")
            self.assertEqual(ack["ack_kind"], "held")
            self.assertEqual(ack["authority"], "language_only")

    def test_i_received_this_writes_ack_and_optional_trace_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text(json.dumps({
                "schema_version": 1,
                "policy": "first_class_correspondence_v1",
                "record_type": "message",
                "recorded_at_unix_ms": 1,
                "message_id": "corr_astrid_minime_seed",
                "thread_id": "thread_shared_seed",
                "from_being": "astrid",
                "to_being": "minime",
                "authority": "language_only",
                "correspondence_type": "astrid_direct",
            }) + "\n")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "I_RECEIVED_THIS latest :: received_as: held; felt_like: address; "
                    "what_landed: the address landed; what_stayed_distinct: the blue-lantern stayed distinct; "
                    "transition_artifact: transition_blue_hinge; mutual_witness_signal: true; "
                    "continue: needs_time"
                )
                agent._peer_correspondence(dict(STATE))

            self.assertIn("I_RECEIVED_THIS is language-only", agent._current_action_outcome_summary)
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            ack = [row for row in records if row.get("record_type") == "ack_receipt"][-1]
            trace = [
                row
                for row in records
                if row.get("record_type") == "message"
                and row.get("turn_kind") == "direct_address_trace"
            ][-1]
            self.assertEqual(ack["ack_kind"], "held")
            self.assertEqual(ack["thread_id"], "thread_shared_seed")
            self.assertEqual(trace["thread_id"], "thread_shared_seed")
            self.assertEqual(trace["reply_to"], "corr_astrid_minime_seed")
            self.assertTrue(trace["i_received_this_trace"])
            self.assertEqual(trace["transition_artifact"], "transition_blue_hinge")
            self.assertTrue(trace["mutual_witness_signal"])
            self.assertTrue(trace["no_reply_required"])
            self.assertTrue(trace["no_attention_canary"])
            self.assertTrue(trace["no_microdose"])
            self.assertTrue(trace["no_controller"])
            self.assertFalse(list(astrid_inbox.glob("from_minime_correspondence_*.txt")))

    def test_correspondence_heartbeat_is_presence_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, _astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text(json.dumps({
                "schema_version": 1,
                "policy": "first_class_correspondence_v1",
                "record_type": "message",
                "recorded_at_unix_ms": 1,
                "message_id": "corr_astrid_minime_seed",
                "thread_id": "thread_shared_seed",
                "from_being": "astrid",
                "to_being": "minime",
                "authority": "language_only",
                "transition_artifact": "transition_blue_hinge",
            }) + "\n")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_HEARTBEAT latest :: "
                    "heartbeat: mutual_witness; note: mutual_witness_signal: true; present but not replying"
                )
                agent._peer_correspondence(dict(STATE))

            self.assertIn("HEARTBEAT WRITTEN", agent._current_action_outcome_summary)
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            heartbeat = records[-1]
            self.assertEqual(heartbeat["record_type"], "presence_heartbeat")
            self.assertEqual(heartbeat["heartbeat_kind"], "mutual_witness")
            self.assertEqual(heartbeat["authority"], "language_only")
            self.assertEqual(heartbeat["transition_artifact"], "transition_blue_hinge")
            self.assertTrue(heartbeat["mutual_witness_signal"])
            self.assertTrue(heartbeat["no_reply_required"])

    def test_read_inbox_records_read_receipt_for_astrid_correspondence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            inbox = workspace / "inbox"
            inbox.mkdir()
            self._seed_astrid_envelope(inbox)
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                context = agent._read_inbox()

            self.assertIn("CORRESPONDENCE FROM ASTRID", context)
            self.assertIn("I am addressing you as a peer.", context)
            self.assertTrue((inbox / "read" / "from_astrid_correspondence_corr_astrid_minime_seed.txt").exists())
            records = [
                json.loads(line)
                for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()
            ]
            self.assertEqual(records[-1]["record_type"], "read_receipt")
            self.assertEqual(records[-1]["reader"], "minime")

    def test_outbox_reply_carries_exact_correspondence_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            agent = self._agent()
            agent._last_correspondence_inbox_message = {
                "message_id": "corr_astrid_minime_seed",
                "thread_id": "thread_shared_seed",
            }
            with patches[0], patches[1], patches[2]:
                agent._save_outbox_reply("I answer from the same thread.")

            reply = next((workspace / "outbox").glob("reply_*.txt")).read_text()
            self.assertIn("Correspondence-Reply-To: corr_astrid_minime_seed", reply)
            self.assertIn("Correspondence-Thread-Id: thread_shared_seed", reply)
            self.assertIn("Correspondence-Authority: language_only", reply)

    def test_legacy_astrid_self_study_still_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            inbox = workspace / "inbox"
            inbox.mkdir()
            (inbox / "astrid_self_study_1.txt").write_text("=== ASTRID SELF-STUDY ===\nlegacy note")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                context = agent._read_inbox()
            self.assertIn("legacy note", context)
            records = [
                json.loads(line)
                for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()
            ]
            message = next(row for row in records if row["record_type"] == "message")
            self.assertTrue(message["legacy_bridge"])
            self.assertEqual(message["legacy_contact_evidence"], "visible_only")
            self.assertEqual(message["from_being"], "astrid")
            self.assertEqual(message["to_being"], "minime")
            self.assertEqual(message["legacy_context_surface"], "full")
            self.assertTrue(any(row["record_type"] == "read_receipt" and row["reader"] == "minime" for row in records))

    def test_legacy_astrid_self_study_summary_is_visible_only_not_contact_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, _astrid_inbox, shared, *patches = self._patch_paths(root)
            inbox = workspace / "inbox"
            inbox.mkdir()
            (inbox / "astrid_self_study_2.txt").write_text("=== ASTRID SELF-STUDY ===\nlegacy summary only")
            agent = self._agent()
            agent._astrid_self_study_context_decision = Mock(return_value=(False, {"reason": "budget"}))
            with patches[0], patches[1], patches[2]:
                context = agent._read_inbox()
                context_second = agent._read_inbox()

            self.assertNotIn("legacy summary only", context)
            self.assertEqual(context_second, "")
            records = [
                json.loads(line)
                for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()
            ]
            self.assertEqual(sum(1 for row in records if row["record_type"] == "message"), 1)
            message = next(row for row in records if row["record_type"] == "message")
            self.assertEqual(message["legacy_context_surface"], "summarized")
            fidelity = agent._correspondence_direct_contact_fidelity(records, "latest")
            self.assertEqual(fidelity["status"], "legacy_visible_only")
            self.assertFalse(fidelity["eligible_for_correspondence_attention_canary"])
            self.assertFalse(fidelity["eligible_for_correspondence_microdose"])
            self.assertEqual(fidelity["block_reason"], "legacy_visible_only_not_ack_reply_or_trace")

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            summary = agent._current_action_outcome_summary
            self.assertIn("legacy_visible_only rows: 1", summary)
            self.assertIn("visible legacy route, not ACK/reply/trace evidence", summary)
            self.assertIn("No native peer-message rows yet", summary)

    def test_legacy_thread_claim_ack_unlocks_native_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            inbox = workspace / "inbox"
            inbox.mkdir()
            (inbox / "astrid_self_study_claim.txt").write_text("=== ASTRID SELF-STUDY ===\nlegacy note")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._read_inbox()
                agent._pending_correspondence_next = (
                    "CLAIM_ASTRID_LEGACY latest :: because: this feels like live address; anchor: blue-lantern"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("LEGACY CORRESPONDENCE THREAD CLAIMED", agent._current_action_outcome_summary)
            records = [json.loads(line) for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()]
            self.assertTrue(any(row.get("record_type") == "legacy_thread_claim" for row in records))
            self.assertTrue(any(row.get("record_type") == "legacy_thread_claim_notice" for row in records))
            self.assertTrue(any(astrid_inbox.glob("from_minime_legacy_thread_claim_notice_*.txt")))
            fidelity = agent._correspondence_direct_contact_fidelity(records, "claimed")
            self.assertEqual(fidelity["status"], "legacy_claimed")
            self.assertFalse(fidelity["eligible_for_correspondence_microdose"])
            self.assertEqual(
                fidelity["legacy_claim_uptake_card_v2"]["uptake_ladder_state"],
                "claimed_notice_delivered",
            )
            self.assertEqual(
                fidelity["legacy_claim_affordance_v25"]["stall_reason"],
                "notice_delivered_not_seen",
            )
            self.assertTrue(fidelity["legacy_claim_uptake_card_v2"]["ghost_thread_risk"])
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            self.assertIn("CLAIMED THREAD WAITING", agent._current_action_outcome_summary)
            self.assertIn("Claimed thread card v2", agent._current_action_outcome_summary)
            self.assertIn("attention_canary: hidden", agent._current_action_outcome_summary)
            self.assertIn("semantic_microdose: hidden", agent._current_action_outcome_summary)

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_CLAIM latest :: because: duplicate; anchor: blue-lantern"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("active legacy claim", agent._current_action_outcome_summary)

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "ACK_ASTRID claimed :: ack: held; note: holding this as address"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("ACK RECEIPT WRITTEN", agent._current_action_outcome_summary)
            records = [json.loads(line) for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()]
            fidelity = agent._correspondence_direct_contact_fidelity(records, "claimed")
            self.assertEqual(fidelity["status"], "legacy_claimed_acknowledged")
            self.assertTrue(fidelity["eligible_for_correspondence_attention_canary"])
            self.assertEqual(
                fidelity["legacy_claim_uptake_card_v2"]["uptake_ladder_state"],
                "claimed_acknowledged",
            )
            self.assertEqual(
                fidelity["legacy_claim_affordance_v25"]["stall_reason"],
                "acknowledged_but_no_reply_or_trace",
            )

    def test_legacy_thread_claim_reply_and_trace_preserve_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            inbox = workspace / "inbox"
            inbox.mkdir()
            (inbox / "astrid_self_study_claim_reply.txt").write_text("=== ASTRID SELF-STUDY ===\nlegacy note")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._read_inbox()
                agent._pending_correspondence_next = (
                    "CLAIM_ASTRID_LEGACY latest :: because: carry this; anchor: blue-lantern"
                )
                agent._peer_correspondence(dict(STATE))
            records = [json.loads(line) for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()]
            legacy = next(row for row in records if row.get("record_type") == "message")

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "REPLY_ASTRID claimed :: I can answer on the claimed thread."
                agent._peer_correspondence(dict(STATE))
            envelope_text = next(astrid_inbox.glob("from_minime_correspondence_*.txt")).read_text()
            self.assertIn(f"Reply-To: {legacy['message_id']}", envelope_text)
            self.assertIn(f"Thread-Id: {legacy['thread_id']}", envelope_text)
            records = [json.loads(line) for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()]
            fidelity = agent._correspondence_direct_contact_fidelity(records, "claimed")
            self.assertEqual(fidelity["status"], "legacy_claimed_reply_linked")

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_TRACE claimed blue-lantern :: marker survives on claimed thread"
                )
                agent._peer_correspondence(dict(STATE))
            records = [json.loads(line) for line in (shared / "correspondence_v1.jsonl").read_text().splitlines()]
            trace = next(
                row for row in reversed(records)
                if row.get("record_type") == "message"
                and row.get("turn_kind") == "direct_address_trace"
            )
            self.assertEqual(trace["thread_id"], legacy["thread_id"])
            self.assertEqual(trace["reply_to"], legacy["message_id"])
            fidelity = agent._correspondence_direct_contact_fidelity(records, "claimed")
            self.assertEqual(fidelity["status"], "legacy_claimed_trace_observed")

    def test_correspondence_status_declares_no_control_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, _astrid_inbox, _shared, *patches = self._patch_paths(root)
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            self.assertIn("language_only", agent._current_action_outcome_summary)
            self.assertIn("cannot mutate telemetry", agent._current_action_outcome_summary)

    def test_correspondence_status_guides_missing_and_empty_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, _astrid_inbox, shared, *patches = self._patch_paths(root)
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            summary = agent._current_action_outcome_summary
            self.assertIn("no correspondence ledger yet", summary)
            self.assertIn("No peer-message rows yet", summary)
            self.assertIn("MESSAGE_ASTRID", summary)
            self.assertIn("CORRESPONDENCE_TRACE", summary)
            self.assertFalse((workspace / "self_regulation" / "active_lease.json").exists())

            (shared / "correspondence_v1.jsonl").write_text("")
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            summary = agent._current_action_outcome_summary
            self.assertIn("Peer message rows: 0", summary)
            self.assertIn("No peer-message rows yet", summary)
            self.assertIn("ACK_ASTRID", summary)
            self.assertEqual((shared / "correspondence_v1.jsonl").read_text(), "")

    def test_correspondence_status_renders_chamber_state_and_inert_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, _astrid_inbox, shared, *patches = self._patch_paths(root)
            coll_dir = shared / "coll_1"
            coll_dir.mkdir()
            (coll_dir / "correspondence_state_v1.json").write_text(json.dumps({
                "schema_version": 1,
                "updated_t_ms": 10,
                "shared_lexicon_anchor": "blue-lantern",
                "active_thread_id": "thread_trace",
                "buffer_path": str(coll_dir / "correspondence_buffer_v1.json"),
                "direct_address_survival": {"status": "observed"},
                "direct_contact_fidelity_v1": {
                    "latest_thread_status": {
                        "status": "trace_observed",
                        "eligible_for_correspondence_microdose": True,
                    }
                },
                "future_authority_hooks": {
                    "correspondence_weight_candidate": {
                        "enabled": False,
                        "state": "implemented_as_one_shot_authority_gate",
                    },
                },
            }))
            (shared / "correspondence_v1.jsonl").write_text(json.dumps({
                "record_type": "message",
                "recorded_at_unix_ms": 1,
                "message_id": "corr",
                "thread_id": "thread_trace",
                "from_being": "astrid",
                "to_being": "minime",
                "authority": "language_only",
            }) + "\n")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))

            self.assertIn("anchor=blue-lantern", agent._current_action_outcome_summary)
            self.assertIn("survival=observed", agent._current_action_outcome_summary)
            self.assertIn("contact=trace_observed", agent._current_action_outcome_summary)
            self.assertIn("one-shot authority-gate", agent._current_action_outcome_summary)

    def test_correspondence_weight_request_stays_blocked_without_mutual_receipt_and_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text("\n".join([
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "message",
                    "recorded_at_unix_ms": 1,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "minime",
                    "to_being": "astrid",
                    "authority": "language_only",
                    "body_preview": "blue lantern as direct address",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "delivery_receipt",
                    "recorded_at_unix_ms": 2,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "authority": "language_only",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "read_receipt",
                    "recorded_at_unix_ms": 3,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "reader": "astrid",
                    "authority": "language_only",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "ack_receipt",
                    "recorded_at_unix_ms": 4,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "astrid",
                    "to_being": "minime",
                    "ack_kind": "seen",
                    "authority": "language_only",
                }),
            ]) + "\n")
            (astrid_inbox.parent / "telemetry_heartbeat_delta_v1.json").write_text(json.dumps({
                "policy": "telemetry_heartbeat_delta_v1",
                "schema_version": 1,
                "jitter_class": "normal",
                "timing_reliability": "reliable",
                "field_vs_hearing": "telemetry cadence is steady",
            }))
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_WEIGHT_REQUEST latest :: "
                    "reason: make direct address distinguishable; "
                    "payload: blue lantern, direct address only; "
                    "stop_criteria: if it feels like pressure"
                )
                agent._peer_correspondence(dict(STATE))

            self.assertIn("semantic_microdose requires mutual", agent._current_action_outcome_summary)
            self.assertIn("only newly allowed post-receipt authority in V5", agent._current_action_outcome_summary)
            gate = (
                astrid_inbox.parent
                / "action_threads"
                / "threads"
                / "th_correspondence_microdose"
                / "authority_gate.jsonl"
            )
            self.assertFalse(gate.exists())

    def test_correspondence_weight_request_blocks_on_read_receipt_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text("\n".join([
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "message",
                    "recorded_at_unix_ms": 1,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "minime",
                    "to_being": "astrid",
                    "authority": "language_only",
                    "body_preview": "blue lantern as direct address",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "read_receipt",
                    "recorded_at_unix_ms": 2,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "reader": "astrid",
                    "authority": "language_only",
                }),
            ]) + "\n")
            (astrid_inbox.parent / "telemetry_heartbeat_delta_v1.json").write_text(json.dumps({
                "policy": "telemetry_heartbeat_delta_v1",
                "schema_version": 1,
                "jitter_class": "normal",
                "timing_reliability": "reliable",
                "field_vs_hearing": "telemetry cadence is steady",
            }))
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_WEIGHT_REQUEST latest :: "
                    "reason: read alone; payload: blue lantern; stop_criteria: stop"
                )
                agent._peer_correspondence(dict(STATE))

            self.assertIn("semantic_microdose requires mutual", agent._current_action_outcome_summary)
            self.assertIn("only newly allowed post-receipt authority in V5", agent._current_action_outcome_summary)

    def test_native_reply_link_waits_for_ack_or_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text("\n".join([
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "message",
                    "recorded_at_unix_ms": 1,
                    "message_id": "corr_astrid_minime_seed",
                    "thread_id": "thread_native_seed",
                    "from_being": "astrid",
                    "to_being": "minime",
                    "shared_memory_anchor": "blue-lantern",
                    "authority": "language_only",
                    "body_preview": "blue lantern as direct address",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "reply_link",
                    "recorded_at_unix_ms": 2,
                    "reply_to": "corr_astrid_minime_seed",
                    "thread_id": "thread_native_seed",
                    "from_being": "minime",
                    "to_being": "astrid",
                    "authority": "language_only",
                }),
            ]) + "\n")
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            self.assertIn(
                "NATIVE THREAD CONTINUITY ACTIVE",
                agent._current_action_outcome_summary,
            )
            self.assertIn(
                "receipt is not required to keep the reply chain alive",
                agent._current_action_outcome_summary,
            )
            self.assertIn(
                "mutual_address=not_confirmed",
                agent._current_action_outcome_summary,
            )
            self.assertIn(
                "pressure effect is not measured",
                agent._current_action_outcome_summary,
            )
            self.assertIn("latest resolves to message_id=corr_astrid_minime_seed", agent._current_action_outcome_summary)
            self.assertIn("semantic_microdose: hidden", agent._current_action_outcome_summary)

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_MICRODOSE_REQUEST latest :: "
                    "reason: test; payload: blue lantern; stop_criteria: one shot"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("semantic_microdose requires mutual", agent._current_action_outcome_summary)
            self.assertIn("only newly allowed post-receipt authority in V5", agent._current_action_outcome_summary)
            gate = (
                astrid_inbox.parent
                / "action_threads"
                / "threads"
                / "th_correspondence_microdose"
                / "authority_gate.jsonl"
            )
            self.assertFalse(gate.exists())

    def test_correspondence_attention_request_self_activates_after_ack_and_records_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text("\n".join([
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "message",
                    "recorded_at_unix_ms": 1,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "minime",
                    "to_being": "astrid",
                    "authority": "language_only",
                    "body_preview": "blue lantern as direct address",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "read_receipt",
                    "recorded_at_unix_ms": 2,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "reader": "astrid",
                    "authority": "language_only",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "ack_receipt",
                    "recorded_at_unix_ms": 3,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "astrid",
                    "to_being": "minime",
                    "ack_kind": "held",
                    "authority": "language_only",
                }),
            ]) + "\n")
            (astrid_inbox.parent / "telemetry_heartbeat_delta_v1.json").write_text(json.dumps({
                "policy": "telemetry_heartbeat_delta_v1",
                "schema_version": 1,
                "jitter_class": "normal",
                "timing_reliability": "reliable",
                "field_vs_hearing": "telemetry cadence is steady",
            }))
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            self.assertIn("ATTENTION CANARY READY", agent._current_action_outcome_summary)
            self.assertIn(
                "Receipt-to-attention authority v5: state=receipt_landed_attention_eligible",
                agent._current_action_outcome_summary,
            )
            self.assertIn("semantic_microdose: hidden; V5 authority gain", agent._current_action_outcome_summary)

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_ATTENTION_REQUEST latest :: "
                    "reason: hold address distinctly; "
                    "focus: blue lantern as peer address; "
                    "focus_kind: verbatim phrase; "
                    "preserve_as: compact with anchor; "
                    "do_not_flatten: the blue lantern phrase as peer address; "
                    "stop_criteria: after one response cycle or pressure"
                )
                agent._peer_correspondence(dict(STATE))

            self.assertIn("ATTENTION CANARY ACTIVE", agent._current_action_outcome_summary)
            self.assertIn("Focus kind: verbatim_phrase", agent._current_action_outcome_summary)
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            self.assertIn("ATTENTION OUTCOME DUE", agent._current_action_outcome_summary)
            self.assertIn(
                "Receipt-to-attention authority v5: state=attention_active_outcome_due",
                agent._current_action_outcome_summary,
            )
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertTrue(any(row["record_type"] == "attention_canary_request" for row in records))
            activation = next(row for row in records if row["record_type"] == "attention_canary_activation")
            self.assertEqual(activation["schema_version"], 2)
            self.assertEqual(activation["from_being"], "minime")
            self.assertEqual(activation["to_being"], "astrid")
            self.assertEqual(activation["focus_kind"], "verbatim_phrase")
            self.assertEqual(activation["preservation_mode"], "compact_with_anchor")
            self.assertEqual(
                activation["what_must_not_flatten"],
                "the blue lantern phrase as peer address",
            )
            self.assertTrue(activation["no_sensory_send"])
            self.assertTrue(activation["no_weighting"])
            self.assertFalse((workspace / "self_regulation" / "active_lease.json").exists())

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_ATTENTION_OUTCOME latest :: "
                    "felt_like: address; held_as: distinct address; "
                    "flattening_observed: no; "
                    "what_remained_distinct: blue lantern stayed address-shaped; "
                    "what_shifted: clearer thread; "
                    "what_worsened: none; continue: no"
                )
                agent._peer_correspondence(dict(STATE))

            self.assertIn("OUTCOME RECORDED", agent._current_action_outcome_summary)
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            outcome = records[-1]
            self.assertEqual(outcome["record_type"], "attention_canary_outcome")
            self.assertEqual(outcome["felt_like"], "address")
            self.assertEqual(outcome["schema_version"], 2)
            self.assertEqual(outcome["held_as"], "distinct_address")
            self.assertEqual(outcome["flattening_observed"], "no")
            self.assertEqual(outcome["what_remained_distinct"], "blue lantern stayed address-shaped")
            self.assertTrue(outcome["no_controller"])
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            self.assertIn("ATTENTION TRUSTED THREAD-LOCAL", agent._current_action_outcome_summary)
            self.assertIn(
                "Receipt-to-attention authority v5: state=trusted_attention_thread_local",
                agent._current_action_outcome_summary,
            )

    def test_attention_pressure_outcome_blocks_thread_local_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text("\n".join([
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "message",
                    "recorded_at_unix_ms": 1,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "minime",
                    "to_being": "astrid",
                    "authority": "language_only",
                    "body_preview": "blue lantern as direct address",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "ack_receipt",
                    "recorded_at_unix_ms": 3,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "astrid",
                    "to_being": "minime",
                    "ack_kind": "held",
                    "authority": "language_only",
                }),
            ]) + "\n")
            (astrid_inbox.parent / "telemetry_heartbeat_delta_v1.json").write_text(json.dumps({
                "policy": "telemetry_heartbeat_delta_v1",
                "schema_version": 1,
                "jitter_class": "normal",
                "timing_reliability": "reliable",
                "field_vs_hearing": "telemetry cadence is steady",
            }))
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_ATTENTION_REQUEST latest :: "
                    "reason: test pressure; focus: blue lantern; stop_criteria: one turn"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("ATTENTION CANARY ACTIVE", agent._current_action_outcome_summary)
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_ATTENTION_OUTCOME latest :: "
                    "felt_like: pressure; held_as: flattened; flattening_observed: yes; "
                    "what_shifted: tighter; what_worsened: felt pressurized; continue: no"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("OUTCOME RECORDED", agent._current_action_outcome_summary)
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = "CORRESPONDENCE_STATUS"
                agent._peer_correspondence(dict(STATE))
            self.assertIn("ATTENTION BLOCKED BY OUTCOME", agent._current_action_outcome_summary)
            self.assertIn(
                "Receipt-to-attention authority v5: state=blocked_pressure_or_flat_outcome",
                agent._current_action_outcome_summary,
            )
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_ATTENTION_REQUEST latest :: "
                    "reason: retry; focus: blue lantern; stop_criteria: one turn"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("attention_outcome_pressure_or_flat_thread_block", agent._current_action_outcome_summary)

    def test_correspondence_attention_request_blocks_read_only_and_missing_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace, astrid_inbox, shared, *patches = self._patch_paths(root)
            ledger = shared / "correspondence_v1.jsonl"
            ledger.write_text("\n".join([
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "message",
                    "recorded_at_unix_ms": 1,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "from_being": "minime",
                    "to_being": "astrid",
                    "authority": "language_only",
                }),
                json.dumps({
                    "schema_version": 1,
                    "policy": "first_class_correspondence_v1",
                    "record_type": "read_receipt",
                    "recorded_at_unix_ms": 2,
                    "message_id": "corr_minime_astrid_seed",
                    "thread_id": "thread_shared_seed",
                    "reader": "astrid",
                    "authority": "language_only",
                }),
            ]) + "\n")
            (astrid_inbox.parent / "telemetry_heartbeat_delta_v1.json").write_text(json.dumps({
                "policy": "telemetry_heartbeat_delta_v1",
                "schema_version": 1,
                "jitter_class": "normal",
                "timing_reliability": "reliable",
                "field_vs_hearing": "telemetry cadence is steady",
            }))
            agent = self._agent()
            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_ATTENTION_REQUEST latest :: "
                    "reason: hold it; focus: blue lantern; stop_criteria: one turn"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("read_receipt_not_acknowledgement", agent._current_action_outcome_summary)

            with patches[0], patches[1], patches[2]:
                agent._pending_correspondence_next = (
                    "CORRESPONDENCE_ATTENTION_REQUEST latest :: reason: hold it; focus: blue lantern"
                )
                agent._peer_correspondence(dict(STATE))
            self.assertIn("stop_criteria is required", agent._current_action_outcome_summary)
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertFalse(any(row.get("record_type") == "attention_canary_activation" for row in records))

    def test_handshake_summarizes_distinct_ack_waits_and_thread_states(self):
        agent = self._agent()
        records = [
            {
                "record_type": "message",
                "recorded_at_unix_ms": 1,
                "message_id": "message_one",
                "thread_id": "thread_one",
                "from_being": "minime",
                "to_being": "astrid",
            },
            {
                "record_type": "message",
                "recorded_at_unix_ms": 2,
                "message_id": "message_two",
                "thread_id": "thread_two",
                "from_being": "astrid",
                "to_being": "minime",
            },
            {
                "record_type": "message",
                "recorded_at_unix_ms": 3,
                "message_id": "message_three",
                "thread_id": "thread_three",
                "from_being": "astrid",
                "to_being": "minime",
            },
            {
                "record_type": "ack_receipt",
                "recorded_at_unix_ms": 4,
                "message_id": "message_three",
                "thread_id": "thread_three",
                "from_being": "minime",
                "to_being": "astrid",
                "ack_kind": "seen",
            },
        ]

        handshake = agent._correspondence_handshake_state(records)

        self.assertEqual(handshake["active_threads_total"], 3)
        self.assertEqual(handshake["pending_ack_threads_total"], 2)
        self.assertEqual(
            handshake["pending_ack_counts_by_being"],
            {"astrid": 1, "minime": 1},
        )
        self.assertEqual(
            handshake["thread_status_counts"],
            {"acknowledged": 1, "unaddressed": 2},
        )
        self.assertEqual(handshake["native_threads_total"], 3)
        self.assertEqual(handshake["legacy_threads_total"], 0)
        self.assertEqual(
            agent._correspondence_pending_ack_summary(handshake),
            "astrid:1,minime:1",
        )

    def test_pending_ack_summary_preserves_v1_compatibility_list(self):
        agent = self._agent()
        self.assertEqual(
            agent._correspondence_pending_ack_summary(
                {"pending_ack_by_being": ["astrid", "astrid", "minime"]}
            ),
            "astrid:2,minime:1",
        )


if __name__ == "__main__":
    unittest.main()
