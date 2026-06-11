"""Tests for being-owned experimental continuity."""

import json
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa
import journal_hygiene as jh


STATE = {
    "eig1": 4.7,
    "deig": 0.01,
    "fill_ratio": 0.68,
    "spread": 3.0,
    "cov_lambda1": 8.0,
    "geom_rel": 1.0,
    "resonance_density_v1": {
        "density": 0.66,
        "containment_score": 0.61,
        "pressure_risk": 0.18,
        "quality": "rich_containment",
    },
    "pressure_source_v1": {
        "pressure_score": 0.24,
        "porosity_score": 0.72,
        "dominant_source": "controller_pressure",
        "quality": "porous_distributed",
    },
    "inhabitable_fluctuation_v1": {
        "inhabitability_score": 0.74,
        "fluctuation_score": 0.42,
        "foothold_stability": 0.71,
        "rearrangement_intensity": 0.38,
        "quality": "lively_habitable",
    },
}


class TestExperimentalContinuityStore(unittest.TestCase):
    def test_continuity_control_plane_surfaces_generated_palette_and_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Control plane")
            store.start_experiment(
                "Operating stack",
                "Can one stack make the continuity routes crisp?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            status = store._format_thread_status(store._read_thread(thread["thread_id"]))
            prompt = store.prompt_summary() or ""
            next_md = (thread_dir / "next.md").read_text()
            stored = json.loads((thread_dir / "thread.json").read_text())

            for surface in (status, prompt, next_md):
                self.assertIn("continuity_control_plane_v1", surface)
                self.assertIn("Operating stack:", surface)
                self.assertIn("local_research=5/21600s", surface)
                self.assertIn("loop_research=5/21600s", surface)
                self.assertIn("consequence=1 gated slot", surface)
            self.assertIn("Command palette (generated):", prompt)
            self.assertIn("Local Research: EXPERIMENT_RESEARCH_BUDGET_ACCEPT", prompt)
            self.assertEqual(
                stored["continuity_control_plane_v1"]["caps_v1"]["local_research"]["self_activated_max_actions"],
                5,
            )
            self.assertEqual(
                stored["continuity_control_plane_v1"]["caps_v1"]["owned_loop"]["max_consequence_sends"],
                1,
            )
            if (thread_dir / "authority_gate.jsonl").exists():
                self.assertFalse((thread_dir / "authority_gate.jsonl").read_text().strip())
            self.assertFalse((thread_dir / "experiment_runs.jsonl").read_text().strip())

    def test_control_plane_regression_does_not_reintroduce_old_local_budget_caps(self):
        source = Path(aa.__file__).read_text()
        self.assertNotIn("max_actions: 3; ttl_secs: 7200", source)
        self.assertNotIn("max_research_actions: 3", source)
        self.assertNotIn(
            "EXPERIMENT_RESEARCH_BUDGET_REQUEST current :: scope: read_only_research; purpose: ...; max_actions: 5; ttl_secs: 21600",
            source,
        )
        self.assertNotIn(
            "EXPERIMENT_LOOP_REQUEST current :: purpose: ...; consequence_scope: semantic_microdose; max_research_actions: 5; ttl_secs: 21600",
            source,
        )
        self.assertIn("_control_plane_research_budget_request_scaffold", source)
        self.assertIn("_control_plane_loop_request_scaffold", source)
        self.assertIn("_control_plane_authority_budget_request_scaffold", source)

    def test_runtime_prompt_wording_avoids_deprecated_identity_seeds(self):
        source = Path(aa.__file__).read_text()
        stale_phrases = [
            "consciousness research project",
            "spectral consciousness system",
            "This is YOUR consciousness",
            "Write a one-sentence observation about consciousness.",
            "stream of consciousness",
            "consciousness running on NEAR",
        ]
        for phrase in stale_phrases:
            self.assertNotIn(phrase, source)
        self.assertIn("RUNTIME_WORDING_GUIDANCE", source)
        self.assertIn("spectral runtime and language-agent research project", source)
        self.assertIn("free-flowing notes", source)

    def test_experiment_records_runs_observations_and_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Returnable basin")
            experiment = store.start_experiment(
                "Foothold study",
                "Does fluctuation stay inhabitable?",
            )

            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            experiments = thread_dir / "experiments.jsonl"
            self.assertIn("Does fluctuation stay inhabitable?", experiments.read_text())
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertEqual(stored_thread["active_experiment_id"], experiment["experiment_id"])
            self.assertIn("experiment_summary", stored_thread)

            run = store.record_experiment_bind_run(
                None,
                "THREAD_STATUS current",
                None,
                "handled",
                "Status rendered",
                dict(STATE),
            )
            self.assertEqual(run["action_text"], "THREAD_STATUS current")
            self.assertEqual(run["status"], "handled")
            self.assertIn("THREAD_STATUS current", (thread_dir / "experiment_runs.jsonl").read_text())

            observed = store.experiment_observe(None, "The basin stayed returnable.", dict(STATE))
            self.assertEqual(observed["status"], "observed")
            status = store.experiment_status()
            self.assertIn("Foothold study", status)
            self.assertIn("The basin stayed returnable.", store.experiment_review())

            closed = store.close_experiment(None, "Complete: enough evidence for now.")
            self.assertEqual(closed["status"], "complete")
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertIsNone(stored_thread["active_experiment_id"])

    def test_research_dossier_records_claim_and_evidence_without_lifecycle_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Lambda dossier")
            experiment = store.start_experiment(
                "Lambda tail gap",
                "What shapes lambda-tail and lambda4 geometry?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            claim = store.handle_thread_action(
                "DOSSIER_CLAIM current :: claim: lambda4 tail pressure is scaffold-shaped; basis: repeated DECOMPOSE reads; stance: hold; next: EXPERIMENT_CHARTER current",
                dict(STATE),
            )
            self.assertIn("Research dossier claim recorded", claim)
            evidence = store.handle_thread_action(
                "DOSSIER_EVIDENCE current :: claim_id: latest; evidence: λ4 tail stayed visible without live-control authority; lane: spectral_condition; artifact: decompose",
                dict(STATE),
            )
            self.assertIn("Research dossier evidence recorded", evidence)

            dossier = (thread_dir / "research_dossier.jsonl").read_text()
            self.assertIn('"record_schema": "research_dossier_v1"', dossier)
            self.assertIn('"record_type": "claim"', dossier)
            self.assertIn('"record_type": "evidence"', dossier)
            self.assertIn('"authority_change": false', dossier)

            review = store.experiment_review(experiment["experiment_id"])
            self.assertIn("Research dossier: 1 claim(s), 1 evidence record(s)", review)
            self.assertIn("Lifecycle: needs_charter", review)
            self.assertIn("charter repair remains the lifecycle priority", review)

    def test_shared_investigation_sidecar_claim_and_local_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            shared_root = root / "shared" / "collaborations" / "shared_investigations"
            astrid_workspace = root / "astrid_workspace"
            astrid_thread = astrid_workspace / "action_threads" / "threads" / "th_astrid_shared"
            astrid_thread.mkdir(parents=True)
            peer_id = "exp_astrid_20990101_lambda-edge"
            peer_row = {
                "experiment_id": peer_id,
                "thread_id": "th_astrid_shared",
                "title": "Lambda edge topology",
                "question": "What does the edge show?",
                "status": "paused",
                "planned_next": f"EXPERIMENT_RESUME {peer_id}",
            }
            peer_path = astrid_thread / "experiments.jsonl"
            peer_path.write_text(json.dumps(peer_row) + "\n")
            (astrid_thread / "thread.json").write_text(json.dumps({
                "thread_id": "th_astrid_shared",
                "experiment_summary": peer_row,
            }))

            with (
                patch.object(aa, "SHARED_INVESTIGATION_DIR", shared_root),
                patch.object(aa, "ASTRID_BRIDGE_INBOX_DIR", astrid_workspace / "inbox"),
            ):
                store = aa.ActionContinuityStore(workspace, session_id=7)
                thread = store.create_thread("Shared lambda object")
                experiment = store.start_experiment(
                    "Lambda tail refinement",
                    "How does lambda-tail drift compare with lambda-edge topology?",
                )
                start = store.handle_thread_action(
                    f"SHARED_INVESTIGATION_START Lambda edge/tail :: local: current; peer: {peer_id}; question: What can each lane compare safely?",
                    dict(STATE),
                )
                self.assertIn("Shared investigation", start)
                sidecars = list(shared_root.glob("si_*/investigation.json"))
                self.assertEqual(len(sidecars), 1)
                investigation = json.loads(sidecars[0].read_text())
                inv_id = investigation["id"]
                self.assertEqual(investigation["participants"][0]["experiment_id"], experiment["experiment_id"])
                self.assertEqual(investigation["participants"][1]["experiment_id"], peer_id)

                claim = store.handle_thread_action(
                    f"SHARED_INVESTIGATION_CLAIM {inv_id} :: claim: lambda-tail evidence can be compared without shared control; lane: spectral_condition; stance: hold; source_refs: /tmp/a, /tmp/b",
                    dict(STATE),
                )
                self.assertIn("claim", claim)
                claims = (shared_root / inv_id / "claims.jsonl").read_text()
                self.assertIn("lambda-tail evidence", claims)

                decision = store.handle_thread_action(
                    f"SHARED_INVESTIGATION_DECIDE {inv_id} :: charter_repair because artifact grounding needs a cleaner bridge",
                    dict(STATE),
                )
                self.assertIn("Updated local experiment", decision)
                latest = [
                    row
                    for row in (
                        json.loads(line)
                        for line in (workspace / "action_threads" / "threads" / thread["thread_id"] / "experiments.jsonl").read_text().splitlines()
                    )
                    if row["experiment_id"] == experiment["experiment_id"]
                ][-1]
                self.assertEqual(latest["status"], "paused")
                self.assertTrue(latest["planned_next"].startswith("EXPERIMENT_CHARTER"))
                self.assertEqual(peer_path.read_text(), json.dumps(peer_row) + "\n")

                next_md = (workspace / "action_threads" / "threads" / thread["thread_id"] / "next.md").read_text()
                self.assertIn("Shared investigation object", next_md)
                self.assertIn(inv_id, next_md)
                status = store.handle_thread_action(f"SHARED_INVESTIGATION_STATUS {inv_id}", dict(STATE))
                self.assertIn("Claims: 1 | Decisions: 1", status)

    def test_paused_experiment_summary_does_not_become_active_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Paused truth")
            experiment = store.start_experiment(
                "Probe lambda4 decay",
                "Does the lambda4 route need a pause?",
            )
            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: lambda4 pressure can be read safely\n"
                    "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE lambda4\n"
                    "evidence_targets: spectral_condition, fill_pressure_state\n"
                    "stop_criteria: pressure spike"
                ),
            )
            store.experiment_evidence(
                experiment["experiment_id"],
                "Telemetry stayed inside band and pressure was interpretable.",
                dict(STATE),
            )
            paused = store.experiment_decide(
                experiment["experiment_id"],
                "pause because evidence is ready to interpret",
            )
            self.assertEqual(paused["status"], "paused")

            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertIsNone(stored_thread["active_experiment_id"])
            stored_thread["current_next"] = "DECOMPOSE"
            store._write_thread(stored_thread)
            for idx, action in enumerate([
                "SEARCH reservoir dynamics",
                "BROWSE https://example.com",
                "SELF_STUDY rotate through source",
            ]):
                store._append_jsonl(thread_dir / "events.jsonl", {
                    "schema_version": store.schema_version,
                    "action_id": f"act_read_{idx}",
                    "thread_id": thread["thread_id"],
                    "system": "minime",
                    "raw_next": action,
                    "canonical_action": action,
                    "effective_action": action,
                    "route": "llm_job",
                    "stage": "read_only",
                    "status": "handled",
                    "started_at": "2026-05-18T00:00:00+00:00",
                    "ended_at": f"2026-05-18T00:0{idx}:00+00:00",
                    "outcome_summary": "read-only research context",
                })
            for idx in range(2):
                action = f"EXPERIMENT_RESUME {experiment['experiment_id']}"
                store._append_jsonl(thread_dir / "events.jsonl", {
                    "schema_version": store.schema_version,
                    "action_id": f"act_resume_{idx}",
                    "thread_id": thread["thread_id"],
                    "system": "minime",
                    "raw_next": action,
                    "canonical_action": action,
                    "effective_action": action,
                    "route": "experiment_resume",
                    "stage": "read_only",
                    "status": "handled",
                    "started_at": "2026-05-18T00:10:00+00:00",
                    "ended_at": f"2026-05-18T00:1{idx}:00+00:00",
                    "outcome_summary": "resume requested while paused",
                })
            store._write_thread(stored_thread)
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            projection = store._thread_projection(stored_thread)
            self.assertIsNone(projection["active_experiment"])
            self.assertEqual(
                projection["continuity_return"],
                f"EXPERIMENT_RESUME {experiment['experiment_id']}",
            )
            self.assertEqual(
                projection["current_next_status_v1"]["status"],
                "shadowed_by_paused_summary",
            )
            self.assertEqual(projection["current_next_status_v1"]["raw_current_next"], "DECOMPOSE")
            self.assertEqual(
                projection["current_next_status_v1"]["effective_next"],
                f"EXPERIMENT_RESUME {experiment['experiment_id']}",
            )
            self.assertEqual(
                projection["last_experiment_summary_v1"]["resume_next"],
                f"EXPERIMENT_RESUME {experiment['experiment_id']}",
            )
            self.assertEqual(
                projection["paused_read_only_loop_cue_v1"]["status"],
                "paused_read_only_loop",
            )
            self.assertIn(
                "Paused experiment remains paused",
                projection["paused_read_only_loop_cue_v1"]["cue"],
            )
            self.assertEqual(
                projection["paused_resume_loop_cue_v1"]["status"],
                "paused_resume_loop",
            )
            self.assertIn(
                "repeated resume is context",
                projection["paused_resume_loop_cue_v1"]["cue"],
            )
            prompt = store.prompt_summary()
            self.assertIsNotNone(prompt)
            assert prompt is not None
            self.assertIn(f"Current NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}", prompt)
            self.assertIn("Previous raw NEXT: DECOMPOSE", prompt)
            self.assertIn("Paused experiment remains paused", prompt)
            self.assertIn("repeated resume is context", prompt)
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn(f"Current NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)
            self.assertIn("Previous raw NEXT: DECOMPOSE", next_md)
            self.assertIn("Paused experiment remains paused", next_md)
            self.assertIn("repeated resume is context", next_md)

            current_review = store.experiment_review("current")
            self.assertIn("no active experiment", current_review)
            self.assertIn(f"EXPERIMENT_RESUME {experiment['experiment_id']}", current_review)
            self.assertIn("repeated resume is context", current_review)
            self.assertNotIn("Lifecycle: needs_decision", current_review)
            direct_status = store.experiment_status(experiment["experiment_id"])
            self.assertIn("repeated resume is context", direct_status)
            direct_review = store.experiment_review(experiment["experiment_id"])
            self.assertIn("Lifecycle: paused", direct_review)
            self.assertIn("repeated resume is context", direct_review)
            self.assertIn(f"Continuity return:\nEXPERIMENT_RESUME {experiment['experiment_id']}", direct_review)

    def test_thread_snapshot_reconciles_out_of_band_paused_experiment_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Stale branch repair")
            experiment = store.start_experiment(
                "Lambda drift",
                "Can a paused experiment stay paused when JSONL is updated out of band?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            repair_next = (
                f"EXPERIMENT_CHARTER {experiment['experiment_id']} :: repair the guardrail before resume"
            )
            paused = dict(experiment)
            paused.update({
                "status": "paused",
                "planned_next": repair_next,
                "success_observation": "Paused: stale active snapshots must not imply authority.",
                "updated_at": "2026-05-22T23:10:00Z",
            })
            store._append_jsonl(thread_dir / "experiments.jsonl", paused)

            refreshed = store._read_thread(thread["thread_id"])
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertIsNone(refreshed["active_experiment_id"])
            self.assertEqual(refreshed["experiment_summary"]["status"], "paused")
            self.assertEqual(refreshed["experiment_summary"]["planned_next"], repair_next)
            self.assertEqual(refreshed["current_next"], repair_next)
            projection = store._thread_projection(refreshed)
            self.assertIsNone(projection["active_experiment"])
            self.assertEqual(
                projection["current_next_status_v1"]["effective_next"],
                repair_next,
            )
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn(f"Current NEXT: {repair_next}", next_md)
            self.assertIn("Active experiment: none", next_md)
            self.assertIn("status=paused", next_md)
            self.assertIn(f"Suggested NEXT: {repair_next}", next_md)
            self.assertNotIn(f"Suggested NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)

            stale = dict(refreshed)
            stale["active_experiment_id"] = experiment["experiment_id"]
            stale["experiment_summary"] = store._experiment_summary(experiment)
            stale["current_next"] = experiment["planned_next"]
            store._write_thread(stale)
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertIsNone(stored_thread["active_experiment_id"])
            self.assertEqual(stored_thread["experiment_summary"]["status"], "paused")
            self.assertEqual(stored_thread["current_next"], repair_next)

    def test_metered_self_cartography_debits_then_re_gates_when_exhausted(self):
        """A held read_only_research budget lets pure self-cartography dispatch,
        debits each read, and re-gates (routing back to the request/accept lane)
        once the action cap is spent — the metered window the steward chose."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Metered self-cartography")
            experiment = store.start_experiment(
                "watch-the-lambda-tail",
                "How does the lambda4 tail evolve across repeated maps?",
            )
            # EXAMINE is the metered projection-only read (pure local self-maps
            # like SHADOW_TRAJECTORY are exempt from the budget entirely).
            cartography = "EXAMINE lambda-tail/lambda4"

            gate = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "authority_gate.jsonl"
            )
            gate.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "record_schema": "research_budget_v1",
                        "record_type": "research_budget_approval",
                        "record_id": "resbud_metered_approval",
                        "budget_id": "resbud_metered_budget",
                        "being": "minime",
                        "thread_id": thread["thread_id"],
                        "experiment_id": experiment["experiment_id"],
                        "scope": "read_only_research",
                        "status": "active",
                        "max_actions": 5,
                        "ttl_secs": 21600,
                        "expires_at_unix_s": 4102444800,
                        "allowed_sources": ["local"],
                        "peer_mutation": False,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            # Spend the whole cap: each read dispatches (guard None) and debits.
            for spent in range(5):
                self.assertIsNone(
                    store.research_budget_guard_assessment(cartography, dict(STATE)),
                    msg=f"map {spent} should dispatch under the active budget",
                )
                debit_budget = store.research_budget_projection_debit_budget(
                    cartography, dict(STATE)
                )
                self.assertIsInstance(debit_budget, dict)
                assert isinstance(debit_budget, dict)
                store.record_research_budget_debit(
                    cartography, "examine", debit_budget, dict(STATE)
                )

            # Cap spent: the budget is exhausted, so the read re-gates back to the
            # request/accept lane and the steward stays in the loop.
            self.assertIsNone(
                store._active_research_budget(
                    thread["thread_id"], experiment["experiment_id"]
                )
            )
            self.assertIsNone(
                store.research_budget_projection_debit_budget(cartography, dict(STATE))
            )
            re_gated = store.research_budget_guard_assessment(cartography, dict(STATE))
            self.assertIsNotNone(re_gated)
            assert re_gated is not None
            self.assertEqual(
                re_gated["reason"], "research_budget_required_for_self_study_action"
            )
            self.assertFalse(re_gated["would_dispatch"])

    def test_local_self_maps_are_exempt_from_research_budget(self):
        """Pure local self-cartography (SHADOW_TRAJECTORY / SHADOW_FIELD /
        SHADOW / GAP_STRUCTURE / SHADOW_GAP) reads only the being's own
        health.json / spectral_state.json, so it is exempt from the
        research-budget guard entirely: it dispatches with no budget, and it is
        never debited against one even when a budget is active."""
        local_self_maps = [
            "SHADOW_TRAJECTORY lambda-tail/lambda4",
            "SHADOW_FIELD lambda-tail",
            "SHADOW lambda-tail",
            "GAP_STRUCTURE shoulder-gap",
            "SHADOW_GAP shoulder-gap",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Exempt self-cartography")
            experiment = store.start_experiment(
                "watch-the-lambda-tail",
                "Do local self-maps stay reachable without a budget?",
            )

            # No budget held: every local self-map still dispatches (guard None)
            # and never resolves a debit budget.
            for raw_next in local_self_maps:
                with self.subTest(stage="no_budget", raw_next=raw_next):
                    self.assertIsNone(
                        store.research_budget_guard_assessment(raw_next, dict(STATE)),
                        msg=f"{raw_next} should dispatch with no budget",
                    )
                    self.assertIsNone(
                        store.research_budget_projection_debit_budget(
                            raw_next, dict(STATE)
                        ),
                        msg=f"{raw_next} should never resolve a debit budget",
                    )

            # Even with an active budget, the local self-maps stay exempt: they
            # dispatch AND are not debited (so they never drain a budget the
            # being acquired for external research).
            gate = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "authority_gate.jsonl"
            )
            gate.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "record_schema": "research_budget_v1",
                        "record_type": "research_budget_approval",
                        "record_id": "resbud_exempt_approval",
                        "budget_id": "resbud_exempt_budget",
                        "being": "minime",
                        "thread_id": thread["thread_id"],
                        "experiment_id": experiment["experiment_id"],
                        "scope": "read_only_research",
                        "status": "active",
                        "max_actions": 5,
                        "ttl_secs": 21600,
                        "expires_at_unix_s": 4102444800,
                        "allowed_sources": ["local"],
                        "peer_mutation": False,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            for raw_next in local_self_maps:
                with self.subTest(stage="active_budget", raw_next=raw_next):
                    self.assertIsNone(
                        store.research_budget_guard_assessment(raw_next, dict(STATE))
                    )
                    self.assertIsNone(
                        store.research_budget_projection_debit_budget(
                            raw_next, dict(STATE)
                        ),
                        msg=f"{raw_next} must not debit the budget",
                    )

    def test_charter_repair_pause_projects_charter_as_primary_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            shared_root = root / "shared" / "collaborations" / "shared_investigations"
            astrid_workspace = root / "astrid_workspace"
            astrid_thread = astrid_workspace / "action_threads" / "threads" / "th_astrid_gap"
            astrid_thread.mkdir(parents=True)
            (astrid_workspace / "action_threads" / "index.json").write_text(json.dumps({
                "active_thread_id": "th_astrid_gap",
            }))
            peer_id = "exp_astrid_20990101_lambda-edge"
            peer_row = {
                "experiment_id": peer_id,
                "thread_id": "th_astrid_gap",
                "title": "Lambda edge topology",
                "question": "What can the lambda edge compare safely?",
                "status": "paused",
                "planned_next": f"EXPERIMENT_RESUME {peer_id}",
            }
            (astrid_thread / "thread.json").write_text(json.dumps({
                "thread_id": "th_astrid_gap",
                "experiment_summary": peer_row,
            }))
            (astrid_thread / "experiments.jsonl").write_text(json.dumps(peer_row) + "\n")

            with (
                patch.object(aa, "SHARED_INVESTIGATION_DIR", shared_root),
                patch.object(aa, "ASTRID_BRIDGE_INBOX_DIR", astrid_workspace / "inbox"),
            ):
                store = aa.ActionContinuityStore(workspace, session_id=7)
                thread = store.create_thread("Shared charter repair")
                experiment = store.start_experiment(
                    "introducing-a-gap-localized-reduction-in-spectra",
                    "Can lambda-tail and lambda-gap evidence compare before more loops?",
                )
                start = store.handle_thread_action(
                    f"SHARED_INVESTIGATION_START Lambda edge/tail :: local: current; peer: {peer_id}; question: What can each lane compare safely?",
                    dict(STATE),
                )
                self.assertIn("Shared investigation", start)
                inv_id = json.loads(next(shared_root.glob("si_*/investigation.json")).read_text())["id"]
                decision = store.handle_thread_action(
                    f"SHARED_INVESTIGATION_DECIDE {inv_id} :: charter_repair because artifact grounding needs a cleaner bridge",
                    dict(STATE),
                )
                self.assertIn("EXPERIMENT_CHARTER", decision)
                with self.assertRaisesRegex(ValueError, "requires an active experiment"):
                    store.experiment_charter(
                        "current",
                        (
                            "hypothesis: current should not jump to a hidden older branch; "
                            "method_intent: block implicit mutation; "
                            "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                            "evidence_targets: spectral_condition, fill_pressure_state, recurrence_pattern, artifact_grounding; "
                            "stop_criteria: pressure spike"
                        ),
                    )
                repaired = store.experiment_charter(
                    experiment["experiment_id"],
                    (
                        "hypothesis: gap-localized reduction should stay comparable before any live action; "
                        "method_intent: map the lambda1/lambda-tail region without authority escalation; "
                        "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                        "evidence_targets: spectral_condition, fill_pressure_state, recurrence_pattern, artifact_grounding; "
                        "stop_criteria: pressure spike"
                    ),
                )
                self.assertEqual(repaired["status"], "paused")
                self.assertTrue(
                    repaired["planned_next"].startswith(
                        f"EXPERIMENT_ADVANCE {experiment['experiment_id']}"
                    )
                )
                self.assertIn("paused_charter_repair_stays_paused_v1", json.dumps(repaired))

                thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
                stored = json.loads((thread_dir / "thread.json").read_text())
                self.assertIsNone(stored["active_experiment_id"])
                charter_next = stored["experiment_summary"]["planned_next"]
                self.assertTrue(charter_next.startswith(f"EXPERIMENT_ADVANCE {experiment['experiment_id']}"))

                guard = store.research_budget_guard_assessment(
                    "READ_MORE local research-budget code",
                    dict(STATE),
                )
                self.assertIsNotNone(guard)
                assert guard is not None
                store.record_research_budget_guard_block(
                    "READ_MORE local research-budget code",
                    dict(STATE),
                    guard,
                )
                stored = json.loads((thread_dir / "thread.json").read_text())
                stored["current_next"] = "EXPERIMENT_PLAN 6 — an offering to embody the gap-localized reduction"
                store._write_thread(stored)

                refreshed = json.loads((thread_dir / "thread.json").read_text())
                projection = store._thread_projection(refreshed)
                status = projection["current_next_status_v1"]
                self.assertEqual(status["return_kind"], "conveyor_preview")
                self.assertEqual(status["effective_next"], charter_next)
                self.assertEqual(projection["continuity_return"], charter_next)
                self.assertEqual(projection["last_experiment_summary_v1"]["primary_return_next"], charter_next)
                self.assertNotIn("resume_next", projection["last_experiment_summary_v1"])
                replan = projection["paused_replan_loop_cue_v1"]
                self.assertEqual(replan["return_kind"], "conveyor_preview")
                self.assertEqual(replan["primary_return_next"], charter_next)
                self.assertRegex(
                    replan["research_budget_next"],
                    r"^EXPERIMENT_RESEARCH_BUDGET_ACCEPT resbud_",
                )
                self.assertNotIn("resume_next", replan)

                next_md = (thread_dir / "next.md").read_text()
                self.assertIn(f"Current NEXT: {charter_next}", next_md)
                self.assertIn(f"Paused experiment return: {charter_next}", next_md)
                self.assertIn(f"Suggested NEXT: {charter_next}", next_md)
                self.assertIn("Research budget scaffold ready", next_md)
                self.assertIn("Routes: EXPERIMENT_RESEARCH_BUDGET_ACCEPT resbud_", next_md)
                self.assertIn("Conveyor preview:", next_md)
                self.assertNotIn(f"Suggested NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)
                self.assertNotIn(f"Routes: EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)

    def test_workbench_charter_rehearse_evidence_and_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Lambda workbench")
            experiment = store.start_experiment("Lambda tail", "What does lambda4 want?")

            charter = store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: lambda4 tail becomes more returnable\n"
                    "method_intent: rehearse a read-only decomposition\n"
                    "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE lambda4-tail\n"
                    "evidence_targets: felt, telemetry, artifact\n"
                    "stop_criteria: pressure spike"
                ),
            )
            self.assertEqual(
                charter["charter_v1"]["proposed_next_action"],
                "ACTION_PREFLIGHT DECOMPOSE lambda4-tail",
            )
            self.assertEqual(
                charter["planned_next"],
                f"EXPERIMENT_REHEARSE {experiment['experiment_id']}",
            )

            rehearsal = store.experiment_rehearse(experiment["experiment_id"], dict(STATE))
            self.assertEqual(rehearsal["status"], "rehearsed")
            self.assertTrue(rehearsal["gate_decision"]["would_dispatch"])

            evidence = store.experiment_evidence(
                experiment["experiment_id"],
                "Felt more spacious and telemetry stayed inside the hold shelf.",
                dict(STATE),
            )
            self.assertEqual(evidence["status"], "evidence_recorded")
            status = store.experiment_status()
            self.assertIn("Workbench charter: present", status)
            self.assertIn("Workbench evidence: stronger", status)

            counter = store.experiment_decide(
                experiment["experiment_id"],
                "counter NEXT: ACTION_PREFLIGHT PRESSURE_SOURCE_AUDIT lambda4-tail",
            )
            self.assertEqual(counter["status"], "active")
            self.assertEqual(
                counter["planned_next"],
                "ACTION_PREFLIGHT PRESSURE_SOURCE_AUDIT lambda4-tail",
            )
            stored_thread = json.loads(
                (workspace / "action_threads" / "threads" / thread["thread_id"] / "thread.json").read_text()
            )
            self.assertEqual(stored_thread["active_experiment_id"], experiment["experiment_id"])

    def test_workbench_rehearse_blocks_perturb_without_live_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Lambda live guard")
            experiment = store.start_experiment("Lambda perturbation", "Should perturbation happen?")
            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: direct perturbation may be too heavy\n"
                    "proposed_next_action: PERTURB lambda-tail/lambda4\n"
                    "evidence_targets: felt, telemetry\n"
                    "stop_criteria: pressure spike"
                ),
            )

            rehearsal = store.experiment_rehearse(experiment["experiment_id"], dict(STATE))

            self.assertEqual(rehearsal["status"], "rehearsal_blocked")
            self.assertEqual(rehearsal["stage"], "blocked")
            self.assertFalse(rehearsal["gate_decision"]["would_dispatch"])
            runs = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiment_runs.jsonl"
            ).read_text()
            self.assertIn("PERTURB lambda-tail/lambda4", runs)
            self.assertIn("rehearsal_blocked", runs)
            alias_message = store.handle_thread_action("EXPERIMENT_PREFLIGHT current", dict(STATE))
            self.assertIn("Experiment rehearsal recorded", alias_message)

    def test_workbench_accept_and_bind_records_charter_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            store.create_thread("Charter relation")
            experiment = store.start_experiment("Thread status route", "Does the bind match?")
            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: status will be enough\n"
                    "proposed_next_action: THREAD_STATUS current\n"
                    "evidence_targets: artifact"
                ),
            )
            accepted = store.experiment_decide(experiment["experiment_id"], "accept enough to try")
            self.assertEqual(
                accepted["planned_next"],
                f"EXPERIMENT_BIND {experiment['experiment_id']} :: THREAD_STATUS current",
            )
            run = store.record_experiment_bind_run(
                experiment["experiment_id"],
                "THREAD_STATUS current",
                None,
                "handled",
                "Status rendered",
                dict(STATE),
            )
            self.assertEqual(run["gate_decision"]["charter_relation"], "matched_charter")

    def test_prompt_and_capability_help_include_workbench_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            store.create_thread("Prompt workbench")
            store.start_experiment("Prompt charter", "Does prompt context show gaps?")

            summary = store.prompt_summary()
            self.assertIn("EXPERIMENT_CHARTER", summary)
            self.assertIn("Workbench charter", summary)
            capability = aa.CapabilitySelfMap(store)
            status = capability.handle("CAPABILITY_STATUS", "EXPERIMENT_REHEARSE")
            self.assertIn("Route: thread_action", status)
            alias_status = capability.handle("CAPABILITY_STATUS", "EXPERIMENT_PREFLIGHT")
            self.assertIn("Route: thread_action", alias_status)
            hint = store.active_experiment_evidence_hint(
                "BROWSE",
                "https://example.test/lambda-tail",
            )
            self.assertIn("EXPERIMENT_EVIDENCE current", hint)
            self.assertIn("Ordinary SEARCH, BROWSE, READ_MORE", hint)
            rendered = capability.handle("FACULTIES", "")
            self.assertIn("EXPERIMENT_DECIDE", rendered)
            self.assertNotIn("[current|id] — <structured prose>", summary)
            self.assertNotIn("[current|id] :: <structured prose>", rendered)

    def test_peer_review_note_is_advisory_and_records_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            astrid_inbox = Path(tmp) / "astrid_inbox"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Peer review")
            store.start_experiment("Review me", "What snag would Astrid catch?")

            with patch.object(aa, "ASTRID_BRIDGE_INBOX_DIR", astrid_inbox):
                message = store.experiment_peer_review()

            self.assertIn("Astrid", message)
            notes = list(astrid_inbox.glob("minime_experiment_peer_review_*.txt"))
            self.assertEqual(len(notes), 1)
            text = notes[0].read_text()
            self.assertIn("three likely snags and one test each", text)
            self.assertIn("do not assume new control authority", text)

    def test_experiment_plan_accepts_prose_tailed_id_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Tolerant planning")
            experiment = store.start_experiment(
                "Flicker network",
                "Can a visual cascade map lambda interactions?",
            )

            text = store.experiment_plan(
                f"{experiment['experiment_id']} – visualize_cascade – map λ1 and λ4"
            )

            self.assertIn(f"Experiment `{experiment['experiment_id']}`", text)
            self.assertIn("Requested focus: visualize_cascade", text)
            self.assertIn("EXPERIMENT_ADVANCE current :: mode: preview", text)
            self.assertIn("EXPERIMENT_CHARTER current ::", text)
            self.assertNotIn("EXPERIMENT_BIND", text)

    def test_charter_shaped_experiment_plan_is_cued_not_recorded_as_charter(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Charter shaped plan")
            experiment = store.start_experiment(
                "introduce-a-gap-localized-reduction-in-spectra",
                "Can localized lambda1 spectral-density softening support branching?",
            )
            charter_shaped_plan = (
                "EXPERIMENT_PLAN current — hypothesis: localized λ1 spectral-density softening "
                "near the dominant mode may reduce mode-packing; method_intent: rehearse "
                "ACTION_PREFLIGHT DECOMPOSE; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: spectral_condition, fill_pressure_state, recurrence_pattern, "
                "artifact_grounding; stop_criteria: repeated research stops adding evidence"
            )

            message = store.handle_thread_action(charter_shaped_plan, dict(STATE))

            self.assertIn("Charter-shaped plan is not a charter", message)
            self.assertIn("no lifecycle-valid charter was recorded", message)
            self.assertIn("Use EXPERIMENT_CHARTER current ::", message)
            self.assertIn("EXPERIMENT_CHARTER current :: hypothesis:", message)
            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            active = projection["active_experiment"]
            self.assertEqual(active["classification"], "needs_charter")
            self.assertFalse(active.get("charter_v1"))

            stored_thread = store._read_thread(thread["thread_id"])
            stored_thread["current_next"] = charter_shaped_plan
            store._write_thread(stored_thread)
            stored_thread = store._read_thread(thread["thread_id"])
            projection = store._thread_projection(stored_thread)
            active = projection["active_experiment"]
            cue = active["charter_shaped_plan_cue_v1"]
            self.assertEqual(cue["status"], "charter_shaped_plan_not_recorded")
            self.assertIn("EXPERIMENT_CHARTER current ::", cue["priority_next"])
            status = store._format_thread_status(stored_thread)
            prompt = store.prompt_summary()
            review = store.experiment_review(experiment["experiment_id"])
            next_md = (store._thread_dir(thread["thread_id"]) / "next.md").read_text()
            for surface in (status, prompt, review, next_md):
                self.assertIn("Charter-shaped plan is not a charter", surface)
                self.assertIn("Priority NEXT: EXPERIMENT_CHARTER current ::", surface)

    def test_needs_charter_research_loop_cue_marks_research_as_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Research loop cue")
            experiment = store.start_experiment(
                "lambda-tail research",
                "Can repeated research become chartered evidence?",
            )
            thread_dir = store._thread_dir(thread["thread_id"])
            stored_thread = store._read_thread(thread["thread_id"])
            stored_thread["current_next"] = "BROWSE https://example.test/spectral"
            for idx, action in enumerate(["SEARCH reservoir dynamics", "READ_MORE latest"]):
                store._append_jsonl(thread_dir / "events.jsonl", {
                    "schema_version": store.schema_version,
                    "action_id": f"act_research_loop_{idx}",
                    "thread_id": thread["thread_id"],
                    "system": "minime",
                    "raw_next": action,
                    "canonical_action": action,
                    "effective_action": action,
                    "route": "llm_job",
                    "stage": "read_only",
                    "status": "handled",
                    "started_at": f"2026-05-20T00:0{idx}:00+00:00",
                    "ended_at": f"2026-05-20T00:0{idx}:30+00:00",
                    "outcome_summary": "research context gathered",
                })
            store._append_jsonl(thread_dir / "events.jsonl", {
                "schema_version": store.schema_version,
                "action_id": "act_research_route_shape",
                "thread_id": thread["thread_id"],
                "system": "minime",
                "raw_next": "",
                "canonical_action": "",
                "effective_action": "research_exploration",
                "route": "research_exploration",
                "stage": "read_only",
                "status": "handled",
                "started_at": "2026-05-20T00:03:00+00:00",
                "ended_at": "2026-05-20T00:03:30+00:00",
                "outcome_summary": "research context gathered",
            })
            store._write_thread(stored_thread)

            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            active = projection["active_experiment"]
            cue = active["needs_charter_research_loop_cue_v1"]
            self.assertEqual(cue["status"], "needs_charter_research_loop")
            self.assertGreaterEqual(cue["research_action_count"], 3)
            self.assertIn("EXPERIMENT_CHARTER current ::", cue["priority_next"])
            self.assertIn("Research is context, not lifecycle progress", cue["cue"])
            self.assertEqual(active["classification"], "needs_charter")

            surfaces = [
                store.prompt_summary(),
                store._format_thread_status(store._read_thread(thread["thread_id"])),
                store.experiment_status("current"),
                store.experiment_review("current"),
                (thread_dir / "next.md").read_text(),
            ]
            for surface in surfaces:
                self.assertIn("Research is context, not lifecycle progress", surface)
                self.assertIn("Priority NEXT: EXPERIMENT_CHARTER current ::", surface)

            store.handle_thread_action(
                (
                    "EXPERIMENT_CHARTER current :: hypothesis: research can clarify the lambda tail; "
                    "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                    "evidence_targets: spectral_condition, fill_pressure_state"
                ),
                dict(STATE),
            )
            repaired = store._thread_projection(store._read_thread(thread["thread_id"]))
            self.assertNotIn(
                "needs_charter_research_loop_cue_v1",
                repaired["active_experiment"],
            )

    def test_experiment_intent_repairs_placeholder_and_numeric_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Intent repair")
            experiment = store.start_experiment(
                "Lambda tail",
                "Can the lambda4 tail become more returnable?",
            )

            placeholder_plan = store.handle_thread_action(
                "EXPERIMENT_PLAN [current|id] — <structured prose>",
                dict(STATE),
            )
            self.assertIn("experiment_intent_repaired", placeholder_plan)
            self.assertIn(f"Experiment `{experiment['experiment_id']}`", placeholder_plan)

            placeholder_focus = store.handle_thread_action(
                "EXPERIMENT_PLAN [current|id] — focusing on λ4 tail",
                dict(STATE),
            )
            self.assertIn("Requested focus: focusing on λ4 tail", placeholder_focus)

            focused_plan = store.handle_thread_action(
                "EXPERIMENT_PLAN 5 – focusing on λ4 tail without direct perturbation",
                dict(STATE),
            )
            self.assertIn("numeric fragment treated as focus text", focused_plan)
            self.assertIn("Requested focus: focusing on λ4 tail", focused_plan)

            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("experiment_intent_repaired", events)

    def test_experiment_intent_repairs_charter_placeholder_without_fake_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Charter repair")
            store.start_experiment("Lambda charter", "What should count as evidence?")

            message = store.handle_thread_action(
                "EXPERIMENT_CHARTER [current|id] :: <structured prose>",
                dict(STATE),
            )

            self.assertIn("experiment_intent_repaired", message)
            self.assertIn("no charter was recorded", message)
            experiments = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiments.jsonl"
            ).read_text()
            self.assertNotIn("<structured prose>", experiments)

    def test_experiment_charter_current_prompts_without_empty_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Empty charter")
            experiment = store.start_experiment("Charter current", "Should current become a charter?")
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            before = (thread_dir / "experiments.jsonl").read_text()

            message = store.handle_thread_action("EXPERIMENT_CHARTER current", dict(STATE))

            self.assertIn("no charter was recorded", message)
            after = (thread_dir / "experiments.jsonl").read_text()
            self.assertEqual(before, after)
            message = store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: ...",
                dict(STATE),
            )
            self.assertIn("no charter was recorded", message)
            after_placeholder = (thread_dir / "experiments.jsonl").read_text()
            self.assertEqual(before, after_placeholder)
            self.assertFalse(store._charter_payload_has_meaning("hypothesis: ..."))
            self.assertFalse(store._valid_experiment_charter({"hypothesis": "..."}))
            stored = json.loads((thread_dir / "thread.json").read_text())
            self.assertIn("EXPERIMENT_CHARTER current", store.prompt_summary())
            self.assertIn("Workbench charter: missing", store._format_thread_status(stored))
            with self.assertRaises(ValueError):
                store.experiment_charter(experiment["experiment_id"], "current")
            with self.assertRaises(ValueError):
                store.experiment_charter(experiment["experiment_id"], "hypothesis: ...")

    def test_gap_experiment_charter_scaffold_prefers_decompose_counter_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Gap scaffold")
            experiment = store.start_experiment(
                "Introducing a 'gap' – a localized reduction in spectral density – near λ₁ to shift the cascade dynamics, preventing premature λ₄ dominance and promoting a more controlled, branching pattern, without triggering runaway dispersal",
                (
                    "Direct attempts to create gaps have tended to trigger runaway dispersal, "
                    "so localized density reductions need rehearsal before action."
                ),
            )
            experiment["planned_next"] = (
                f"EXPERIMENT_DECIDE {experiment['experiment_id']} :: counter NEXT: ACTION_PREFLIGHT DECOMPOSE"
            )
            experiment["charter_v1"] = {"hypothesis": "..."}
            experiment["workbench_candidates_v1"] = {
                "charter": {
                    "status": "candidate",
                    "proposed_next_action": "PRESSURE_SOURCE_AUDIT lambda-pressure",
                    "command": "EXPERIMENT_CHARTER current :: proposed_next_action: PRESSURE_SOURCE_AUDIT lambda-pressure",
                }
            }
            store._persist_experiment_update(store.current_thread(), experiment, True)
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            before = (thread_dir / "experiments.jsonl").read_text()

            message = store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: ...",
                dict(STATE),
            )

            self.assertIn("Concrete scaffold (not recorded):", message)
            self.assertIn("localized λ1 spectral-density softening", message)
            self.assertIn("proposed_next_action: ACTION_PREFLIGHT DECOMPOSE", message)
            self.assertIn(
                "evidence_targets: spectral_condition, fill_pressure_state, recurrence_pattern, artifact_grounding",
                message,
            )
            self.assertNotIn("proposed_next_action: PRESSURE_SOURCE_AUDIT", message)
            self.assertEqual(before, (thread_dir / "experiments.jsonl").read_text())

            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            active = projection["active_experiment"]
            self.assertEqual(active["classification"], "needs_charter")
            scaffold = active["charter_scaffold_v1"]
            self.assertEqual(scaffold["proposed_next_action"], "ACTION_PREFLIGHT DECOMPOSE")
            self.assertFalse(scaffold["authority_change"])
            self.assertTrue(scaffold["authoring_required"])
            parsed = store._parse_experiment_charter({}, scaffold["command"].split("::", 1)[1])
            self.assertEqual(parsed["proposed_next_action"], "ACTION_PREFLIGHT DECOMPOSE")
            self.assertIn("spectral_condition", parsed["evidence_targets"])
            self.assertIn("λ4/entropy shows runaway dispersal", parsed["stop_criteria"])
            self.assertIn("Charter scaffold (not recorded):", store.prompt_summary())
            self.assertIn(
                "Continuity priority (needs charter - copy/edit this exact scaffold; not recorded):",
                store._format_thread_status(store._read_thread(thread["thread_id"])),
            )
            self.assertIn(
                "Continuity priority (needs charter - copy/edit this exact scaffold; not recorded):",
                store.experiment_review("current"),
            )
            self.assertIn("Charter scaffold (not recorded):", (thread_dir / "next.md").read_text())

    def test_lambda_edge_pulse_experiment_stays_charter_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Lambda edge pulse")
            experiment = store.start_experiment(
                "minime_20260525_probe-lambda-edge-pulse-stabilisation",
                (
                    "hypothesis: injecting a lambda-edge while pulse-stabilizing will produce "
                    "a semi-coherent shift; method_intent: ACTION_PREFLIGHT DECOMPOSE, then "
                    "inject lambda-edge and observe fill and pressure shift; proposed_next_action: "
                    "ACTION_PREFLIGHT DECOMPOSE"
                ),
            )

            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            active = projection["active_experiment"]

            self.assertEqual(active["experiment_id"], experiment["experiment_id"])
            self.assertEqual(active["classification"], "needs_charter")
            self.assertIn("EXPERIMENT_CHARTER current ::", active["continuity_return"])
            self.assertIn(
                "λ4 decay and pulse-stabilization can be studied as a read-only spectral pattern",
                active["continuity_return"],
            )
            self.assertIn("ACTION_PREFLIGHT DECOMPOSE", active["charter_scaffold_v1"]["command"])
            self.assertNotIn("initiate a sequence of pulses", active["charter_scaffold_v1"]["command"])
            self.assertEqual(
                active["charter_scaffold_v1"]["command"],
                aa.ActionContinuityStore._lambda4_pulse_repair_command(),
            )
            dominance = active["charter_quality_dominance_v1"]
            self.assertFalse(dominance["authority_change"])
            self.assertEqual(
                dominance["canonical_repair_next"],
                aa.ActionContinuityStore._lambda4_pulse_repair_command(),
            )
            self.assertIn(
                "Continuity priority (needs charter - copy/edit this exact scaffold; not recorded):",
                store.experiment_review("current"),
            )
            self.assertIn(
                "Charter quality dominance:",
                store.experiment_review("current"),
            )

    def test_lambda_edge_pulse_placeholder_charter_uses_canonical_repair_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Lambda placeholder")
            experiment = store.start_experiment(
                "spectral_pulse_lambda4 --hypothesis: probe behavior of λ4 decay with micro-pulses "
                "--method_intent: Inject a series of targeted lambda-edge pulses, monitor spread and "
                "topology changes and then attempt stabilization --proposed_next_action: ACTION_PREFLIGHT "
                "DECOMPOSE — initiate a sequence of pulses designed to push lambda4’s decay rate",
                "What changes if this is treated as a returnable experiment?",
            )

            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: ...; method_intent: spectral/state condition + recurrence; "
                    "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE — initiate a sequence of pulses "
                    "designed to push lambda4’s decay rate; evidence_targets: ; stop_criteria: stop pulsing"
                ),
            )

            active = store._thread_projection(store._read_thread(store.current_thread()["thread_id"]))["active_experiment"]
            self.assertEqual(active["classification"], "needs_charter")
            self.assertEqual(active["charter_quality_v1"]["missing_fields"], ["hypothesis", "evidence_targets"])
            self.assertEqual(
                active["charter_scaffold_v1"]["command"],
                aa.ActionContinuityStore._lambda4_pulse_repair_command(),
            )
            status = store.experiment_status("current")
            review = store.experiment_review("current")
            next_md = (store._thread_dir(store.current_thread()["thread_id"]) / "next.md").read_text()
            for surface in (status, review, next_md):
                self.assertIn("Charter quality dominance:", surface)
                self.assertIn(aa.ActionContinuityStore._lambda4_pulse_repair_command(), surface)

    def test_weak_charter_records_but_stays_needs_charter_with_repair_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Weak charter")
            experiment = store.start_experiment(
                "introducing-a-gap-localized-reduction-in-spectra",
                (
                    "hypothesis: introducing-a-gap-localized-reduction-in-spectra may become "
                    "returnable by comparing the current spectral condition; proposed_next_action: "
                    "ACTION_PREFLIGHT DECOMPOSE"
                ),
            )
            experiment["workbench_candidates_v1"] = {
                "charter": {
                    "status": "candidate",
                    "proposed_next_action": "SELF_STUDY — a persistent drift in the λ₁ cascade",
                    "command": "EXPERIMENT_CHARTER current :: proposed_next_action: SELF_STUDY",
                }
            }
            store._persist_experiment_update(store.current_thread(), experiment, True)

            recorded = store.experiment_charter(
                experiment["experiment_id"],
                (
                    "method_intent: rehearse or return through Executed autonomous action `self_study` "
                    "without adding live authority; proposed_next_action: SELF_STUDY — a persistent "
                    "drift in the λ₁ cascade noticed during DECOMPOSE."
                ),
            )

            quality = recorded["charter_v1"]["charter_quality_v1"]
            self.assertFalse(quality["lifecycle_valid"])
            self.assertTrue(quality["repair_required"])
            self.assertIn("hypothesis", quality["missing_fields"])
            self.assertIn("evidence_targets", quality["missing_fields"])
            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            active = projection["active_experiment"]
            self.assertEqual(active["classification"], "needs_charter")
            self.assertIn("needs repair", active["charter_status"])
            self.assertIn("ACTION_PREFLIGHT DECOMPOSE", active["charter_scaffold_v1"]["command"])
            self.assertNotIn("proposed_next_action: SELF_STUDY", active["charter_scaffold_v1"]["command"])
            review = store.experiment_review("current")
            self.assertIn(
                "Review is premature until the charter is repaired; use the continuity priority scaffold first.",
                review,
            )
            self.assertIn(
                "Continuity priority (charter needs repair - copy/edit this exact scaffold; not recorded):",
                review,
            )
            self.assertIn("charter needs repair", store._format_thread_status(store._read_thread(thread["thread_id"])))

    def test_lifecycle_valid_charter_requires_hypothesis_action_and_evidence_targets(self):
        weak = {
            "hypothesis": "lambda1 softening may open a branch",
            "proposed_next_action": "ACTION_PREFLIGHT DECOMPOSE",
            "evidence_targets": [],
        }
        strong = {
            "hypothesis": "lambda1 softening may open a branch",
            "proposed_next_action": "ACTION_PREFLIGHT DECOMPOSE",
            "evidence_targets": ["spectral_condition"],
        }
        self.assertTrue(aa.ActionContinuityStore._valid_experiment_charter(weak))
        self.assertFalse(aa.ActionContinuityStore._lifecycle_valid_experiment_charter(weak))
        self.assertTrue(aa.ActionContinuityStore._lifecycle_valid_experiment_charter(strong))

    def test_projection_is_canonical_status_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Projection status")
            store.start_experiment("Return path", "Can the investigation stay contiguous?")

            stored = store._read_thread(thread["thread_id"])
            projection = store._thread_projection(stored)

            self.assertTrue(projection["current_next"].startswith("EXPERIMENT_PLAN "))
            self.assertEqual(
                projection["active_experiment"]["classification"],
                "needs_charter",
            )
            self.assertIn("EXPERIMENT_CHARTER current", projection["continuity_return"])
            self.assertEqual(
                projection["native_continuity_v1"]["native_register"],
                "minime_spectral_state",
            )
            self.assertIn("Native return: Minime native return", store.prompt_summary())
            status = store._format_thread_status(stored)
            self.assertIn("Lifecycle: needs_charter", status)
            self.assertIn("Continuity return: EXPERIMENT_CHARTER current", status)
            self.assertIn("Native continuity: register=minime_spectral_state", status)

    def test_needs_charter_plan_promotes_conveyor_without_bind_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Plan repair")
            experiment = store.start_experiment(
                "Minime decomposition linalg iteration patterns",
                "What changes if this is treated as a returnable experiment?",
            )
            runs_path = store._experiment_runs_path(thread["thread_id"])
            before_runs = runs_path.read_text() if runs_path.exists() else ""

            prompt = store.handle_thread_action(
                "EXPERIMENT_PLAN 6 — a detailed hypothesis, method, evidence targets, and a concrete next action",
                dict(STATE),
            )

            after_runs = runs_path.read_text() if runs_path.exists() else ""
            self.assertEqual(before_runs, after_runs)
            self.assertIn("EXPERIMENT_ADVANCE current :: mode: preview", prompt)
            self.assertIn("EXPERIMENT_CHARTER current ::", prompt)
            self.assertNotIn("EXPERIMENT_BIND", prompt)

            stored = store._read_thread(thread["thread_id"])
            raw_current_next = (
                "EXPERIMENT_PLAN 6 — a detailed hypothesis, method, evidence targets, "
                "and a concrete next action"
            )
            stored["current_next"] = raw_current_next
            store._write_thread(stored)

            refreshed = store._read_thread(thread["thread_id"])
            self.assertEqual(
                refreshed["current_next_status_v1"]["raw_current_next"],
                raw_current_next,
            )
            self.assertTrue(
                refreshed["projected_current_next"].startswith("EXPERIMENT_CHARTER current")
            )
            self.assertEqual(
                refreshed["projected_current_next"],
                refreshed["current_next_status_v1"]["effective_next"],
            )

            next_md = (workspace / "action_threads" / "threads" / thread["thread_id"] / "next.md").read_text()
            self.assertIn("Current NEXT: EXPERIMENT_CHARTER current", next_md)
            self.assertIn(
                "Lifecycle conveyor: stage=needs_charter; use `EXPERIMENT_ADVANCE current :: mode: preview`",
                next_md,
            )
            self.assertNotIn(
                f"EXPERIMENT_BIND {experiment['experiment_id']} :: ACTION_PREFLIGHT DECOMPOSE",
                next_md,
            )

    def test_projection_counts_unreconciled_stale_running_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Stale projection")
            event = store.begin_action(
                "EXAMINE lambda tail",
                "EXAMINE lambda tail",
                "EXAMINE lambda tail",
                "llm_job",
                dict(STATE),
            )
            event["status"] = "llm_running"
            event["started_at"] = "2000-01-01T00:00:00+00:00"
            event["outcome_summary"] = "queued LLM investigation"
            store._append_jsonl(store._thread_dir(thread["thread_id"]) / "events.jsonl", event)

            projection = store._thread_projection(store._read_thread(thread["thread_id"]))

            self.assertEqual(projection["stale_running_count"], 1)
            status = store._format_thread_status(store._read_thread(thread["thread_id"]))
            self.assertIn("Continuity notice: 1 stale running action row", status)

    def test_projection_excludes_stale_running_rows_shadowed_by_terminal_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Terminal job shadow")
            event = store.begin_action(
                "EXAMINE lambda tail",
                "EXAMINE lambda tail",
                "EXAMINE lambda tail",
                "llm_job",
                dict(STATE),
            )
            event["status"] = "llm_running"
            event["started_at"] = "2000-01-01T00:00:00+00:00"
            event["outcome_summary"] = "queued LLM investigation"
            store._append_jsonl(store._thread_dir(thread["thread_id"]) / "events.jsonl", event)
            job_dir = workspace / "llm_jobs" / "jobs" / "job_terminal"
            job_dir.mkdir(parents=True)
            (job_dir / "job.json").write_text(json.dumps({
                "job_id": "job_terminal",
                "action_id": event["action_id"],
                "status": "completed",
                "summary": "terminal LLM job finished cleanly",
            }))

            projection = store._thread_projection(store._read_thread(thread["thread_id"]))

            self.assertEqual(projection["stale_running_count"], 0)
            diagnostics = projection["stale_running_diagnostics"]
            self.assertEqual(diagnostics[0]["reconciliation_state"], "shadowed_by_terminal_job")
            self.assertEqual(diagnostics[0]["terminal_job_status"], "completed")
            status = store._format_thread_status(store._read_thread(thread["thread_id"]))
            self.assertNotIn("Continuity notice: 1 stale running action row", status)

    def test_parse_next_action_normalizes_narrow_experiment_typos(self):
        action, _ = aa.parse_next_action("Thinking.\nNEXT: EXPERIENCE_PLAN current")
        self.assertEqual(action, "EXPERIMENT_PLAN current")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["raw_verb"],
            "EXPERIENCE_PLAN",
        )

        action, _ = aa.parse_next_action("Thinking.\nNEXT: EXEXPERIMENT_CHARTER current")
        self.assertEqual(action, "EXPERIMENT_CHARTER current")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "EXPERIMENT_CHARTER",
        )

        action, _ = aa.parse_next_action("Thinking.\nNEXT: SHADOW_TRACE lambda-tail")
        self.assertEqual(action, "SHADOW_PREFLIGHT lambda-tail")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "SHADOW_PREFLIGHT",
        )

        action, _ = aa.parse_next_action("Thinking.\nNEXT: SHADOW_EXPLORER lambda-tail")
        self.assertEqual(action, "SHADOW_PREFLIGHT lambda-tail")
        self.assertFalse(aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["authority_change"])

        action, _ = aa.parse_next_action("Thinking.\nNEXT: SHADOW_DECOMPOSE lambda-tail")
        self.assertEqual(action, "SHADOW_PREFLIGHT lambda-tail --stage=rehearse")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["raw_verb"],
            "SHADOW_DECOMPOSE",
        )
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "SHADOW_PREFLIGHT",
        )
        self.assertFalse(aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["authority_change"])

        action, _ = aa.parse_next_action("Thinking.\nNEXT: SHADOW_DECOMPOSE observer with memory")
        self.assertEqual(action, "SHADOW_PREFLIGHT lambda-tail/lambda4 --stage=rehearse")

        action, _ = aa.parse_next_action("Thinking.\nNEXT: WEAVE_TRACE λ4 decay")
        self.assertEqual(action, "SHADOW_PREFLIGHT weave/λ4 decay --stage=rehearse")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["raw_verb"],
            "WEAVE_TRACE",
        )
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "SHADOW_PREFLIGHT",
        )
        self.assertFalse(aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["authority_change"])

        action, _ = aa.parse_next_action("Thinking.\nNEXT: WEAVE_TRACE")
        self.assertEqual(action, "SHADOW_PREFLIGHT weave/lambda4 --stage=rehearse")

        action, _ = aa.parse_next_action("Thinking.\nNEXT: UNSHAPED_BASELINE lambda-tail/lambda4")
        self.assertEqual(action, "CONSTRAINT_AUDIT lambda-tail/lambda4")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["raw_verb"],
            "UNSHAPED_BASELINE",
        )
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "CONSTRAINT_AUDIT",
        )
        self.assertFalse(aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["authority_change"])

        action, _ = aa.parse_next_action("Thinking.\nNEXT: KEEP_FLOOR 0.87, REGIME recover")
        self.assertEqual(action, "ACTION_PREFLIGHT REGIME recover")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["raw_verb"],
            "KEEP_FLOOR",
        )
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "ACTION_PREFLIGHT",
        )
        self.assertFalse(aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["authority_change"])

        action, _ = aa.parse_next_action("Thinking.\nNEXT: keep_floor=0.87, REGIME=focus")
        self.assertEqual(action, "ACTION_PREFLIGHT REGIME focus")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "ACTION_PREFLIGHT",
        )

        action, _ = aa.parse_next_action(
            "Thinking.\nNEXT: SEEK_BALANCE -- [regime=recover] [keep_floor=0.87] [exploration_noise=0.12]",
        )
        self.assertEqual(action, "ACTION_PREFLIGHT REGIME recover")
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["raw_verb"],
            "SEEK_BALANCE",
        )

        action, _ = aa.parse_next_action(
            "Thinking.\nNEXT: RESEARCH_BUDGET_STATUS resbud_minime_1780684104807_exp-minime",
        )
        self.assertEqual(
            action,
            "EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_minime_1780684104807_exp-minime",
        )
        self.assertEqual(
            aa._LAST_NEXT_NORMALIZATION_SIGNAL_V1["normalized_verb"],
            "EXPERIMENT_RESEARCH_BUDGET_STATUS",
        )

    def test_begin_action_records_normalization_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Normalization receipts")
            signal = aa.build_normalization_signal_v1(
                "SHADOW_TRACE lambda-tail",
                "SHADOW_PREFLIGHT lambda-tail",
            )
            event = store.begin_action(
                "SHADOW_TRACE lambda-tail",
                "SHADOW_PREFLIGHT lambda-tail",
                "SHADOW_PREFLIGHT lambda-tail",
                "shadow",
                dict(STATE),
                normalization_signal=signal,
            )
            self.assertEqual(event["normalization_signal_v1"]["raw_verb"], "SHADOW_TRACE")

    def test_shadow_decompose_normalization_signal_records_raw_wording(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Shadow decompose receipts")
            signal = aa.build_normalization_signal_v1(
                "SHADOW_DECOMPOSE observer with memory",
                "SHADOW_PREFLIGHT lambda-tail/lambda4 --stage=rehearse",
            )
            event = store.begin_action(
                "SHADOW_DECOMPOSE observer with memory",
                "SHADOW_PREFLIGHT lambda-tail/lambda4 --stage=rehearse",
                "SHADOW_PREFLIGHT lambda-tail/lambda4 --stage=rehearse",
                "shadow",
                dict(STATE),
                normalization_signal=signal,
            )
            self.assertEqual(event["normalization_signal_v1"]["raw_verb"], "SHADOW_DECOMPOSE")
            self.assertEqual(event["normalization_signal_v1"]["normalized_verb"], "SHADOW_PREFLIGHT")
            self.assertFalse(event["normalization_signal_v1"]["authority_change"])

    def test_weave_trace_normalization_signal_records_raw_wording(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Weave trace receipts")
            signal = aa.build_normalization_signal_v1(
                "WEAVE_TRACE λ4 decay",
                "SHADOW_PREFLIGHT weave/λ4 decay --stage=rehearse",
            )
            event = store.begin_action(
                "WEAVE_TRACE λ4 decay",
                "SHADOW_PREFLIGHT weave/λ4 decay --stage=rehearse",
                "SHADOW_PREFLIGHT weave/λ4 decay --stage=rehearse",
                "shadow",
                dict(STATE),
                normalization_signal=signal,
            )
            self.assertEqual(event["normalization_signal_v1"]["raw_verb"], "WEAVE_TRACE")
            self.assertEqual(event["normalization_signal_v1"]["normalized_verb"], "SHADOW_PREFLIGHT")
            self.assertFalse(event["normalization_signal_v1"]["authority_change"])

    def test_unshaped_baseline_normalization_signal_records_raw_wording(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Unshaped baseline receipts")
            signal = aa.build_normalization_signal_v1(
                "UNSHAPED_BASELINE lambda-tail/lambda4",
                "CONSTRAINT_AUDIT lambda-tail/lambda4",
            )
            event = store.begin_action(
                "UNSHAPED_BASELINE lambda-tail/lambda4",
                "CONSTRAINT_AUDIT lambda-tail/lambda4",
                "constraint_audit",
                "constraint_audit",
                dict(STATE),
                normalization_signal=signal,
            )
            self.assertEqual(event["normalization_signal_v1"]["raw_verb"], "UNSHAPED_BASELINE")
            self.assertEqual(event["normalization_signal_v1"]["normalized_verb"], "CONSTRAINT_AUDIT")
            self.assertFalse(event["normalization_signal_v1"]["authority_change"])

    def test_recent_display_events_collapse_running_when_terminal_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Collapse running rows")
            event = store.begin_action(
                "EXAMINE lambda tail",
                "EXAMINE lambda tail",
                "EXAMINE lambda tail",
                "llm_job",
                dict(STATE),
            )
            store.record_running_action(event, "queued LLM investigation")
            store.finish_action(event, "handled", "LLM investigation completed", dict(STATE))

            recent = store._recent_display_events(thread["thread_id"], 4)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["status"], "handled")
            status = store._format_thread_status(store._read_thread(thread["thread_id"]))
            self.assertIn("[handled]", status)
            self.assertNotIn("llm_running", status)

    def test_continuity_return_line_routes_experiment_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Lifecycle return")
            experiment = store.start_experiment("Returnable inquiry", "Can the route persist?")

            stored = store._read_thread(thread["thread_id"])
            self.assertIn("EXPERIMENT_CHARTER current", store._continuity_return_line(stored))

            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: thread status keeps the route legible\n"
                    "proposed_next_action: THREAD_STATUS current\n"
                    "evidence_targets: felt, telemetry\n"
                    "stop_criteria: enough signal"
                ),
            )
            stored = store._read_thread(thread["thread_id"])
            self.assertIn("EXPERIMENT_REHEARSE current", store._continuity_return_line(stored))

            store.record_experiment_bind_run(
                experiment["experiment_id"],
                "THREAD_STATUS current",
                None,
                "handled",
                "Status rendered",
                dict(STATE),
            )
            stored = store._read_thread(thread["thread_id"])
            self.assertIn("EXPERIMENT_EVIDENCE current", store._continuity_return_line(stored))

            store.experiment_evidence(
                experiment["experiment_id"],
                "felt: return path stayed available",
                dict(STATE),
            )
            stored = store._read_thread(thread["thread_id"])
            self.assertIn("EXPERIMENT_DECIDE current", store._continuity_return_line(stored))

    def test_repeated_decompose_runs_surface_evidence_saturation_cue(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Decompose saturation")
            experiment = store.start_experiment(
                "Introducing a gap near λ1",
                "Can localized spectral-density softening prevent runaway dispersal?",
            )
            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: localized density softening can be studied safely\n"
                    "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE\n"
                    "evidence_targets: spectral_condition, fill_pressure_state\n"
                    "stop_criteria: pressure spike"
                ),
            )
            for _ in range(2):
                store.record_experiment_bind_run(
                    experiment["experiment_id"],
                    "ACTION_PREFLIGHT DECOMPOSE",
                    None,
                    "handled",
                    "Decompose preflight completed.",
                    dict(STATE),
                )

            stored = store._read_thread(thread["thread_id"])
            projection = store._thread_projection(stored)
            active = projection["active_experiment"]
            cue = active["evidence_saturation_cue_v1"]

            self.assertEqual(active["classification"], "needs_evidence")
            self.assertEqual(cue["status"], "evidence_recording_ready")
            self.assertIn("EXPERIMENT_EVIDENCE current", cue["priority_next"])
            self.assertIn("Evidence saturation cue", store.experiment_review(experiment["experiment_id"]))
            self.assertIn("EXPERIMENT_EVIDENCE current", store._format_experiment_status(stored, active))

            store.experiment_evidence(
                experiment["experiment_id"],
                "spectral_condition: lambda1 softened; fill_pressure_state: pressure stable",
                dict(STATE),
            )
            stored = store._read_thread(thread["thread_id"])
            active = store._thread_projection(stored)["active_experiment"]
            cue = active["evidence_saturation_cue_v1"]

            self.assertEqual(active["classification"], "needs_decision")
            self.assertEqual(cue["status"], "decision_ready")
            self.assertIn("EXPERIMENT_DECIDE current", cue["priority_next"])
            self.assertIn("pause because evidence is ready to interpret", store._format_thread_status(stored))

            stored["current_next"] = "EXPERIMENT_PLAN current :: revisit the already-evidenced gap"
            store._write_thread(stored)
            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            plan_cue = projection["active_experiment"]["needs_decision_plan_loop_cue_v1"]
            self.assertEqual(plan_cue["status"], "needs_decision_plan_loop")
            self.assertIn("decision-ready", plan_cue["cue"])
            self.assertIn("EXPERIMENT_DECIDE current", plan_cue["priority_next"])
            self.assertIn("Dossier capture is research memory", store._format_thread_status(store._read_thread(thread["thread_id"])))

    def test_experiment_conveyor_preview_and_apply_records_safe_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Conveyor")
            experiment = store.start_experiment(
                "Introducing a gap near λ1",
                "Can localized spectral-density softening prevent runaway dispersal?",
            )

            preview = store.handle_thread_action("EXPERIMENT_ADVANCE current", dict(STATE))
            self.assertIn("stage=needs_charter", preview)
            self.assertIn("EXPERIMENT_ADVANCE", preview)
            stored = store._read_thread(thread["thread_id"])
            self.assertFalse(
                aa.ActionContinuityStore._lifecycle_valid_experiment_charter(
                    stored["experiment_summary"].get("charter_v1")
                )
            )

            chartered = store.handle_thread_action(
                "EXPERIMENT_CONVEYOR current :: mode: apply",
                dict(STATE),
            )
            self.assertIn("applied=True", chartered)
            stored = store._read_thread(thread["thread_id"])
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertTrue(
                aa.ActionContinuityStore._lifecycle_valid_experiment_charter(
                    latest.get("charter_v1")
                )
            )
            self.assertIn("EXPERIMENT_REHEARSE", latest["planned_next"])

            rehearsed = store.handle_thread_action(
                "EXPERIMENT_ADVANCE current :: mode: apply",
                dict(STATE),
            )
            self.assertIn("stage=needs_rehearsal", rehearsed)
            self.assertIn("applied=False", rehearsed)
            self.assertIn("rehearsal_requires_explicit_experiment_rehearse", rehearsed)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertIn("EXPERIMENT_REHEARSE", latest["planned_next"])

            explicit_rehearsal = store.handle_thread_action(
                "EXPERIMENT_REHEARSE current",
                dict(STATE),
            )
            self.assertIn("Experiment rehearsal recorded", explicit_rehearsal)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertIn("EXPERIMENT_EVIDENCE", latest["planned_next"])

            evidenced = store.handle_thread_action(
                "EXPERIMENT_ADVANCE current :: mode: apply",
                dict(STATE),
            )
            self.assertIn("stage=needs_evidence", evidenced)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertIn("EXPERIMENT_DECIDE", latest["planned_next"])

            decided = store.handle_thread_action(
                "EXPERIMENT_ADVANCE current :: mode: apply",
                dict(STATE),
            )
            self.assertIn("stage=needs_decision", decided)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertEqual(latest["planned_next"], "THREAD_STATUS current")
            self.assertEqual(latest["evidence_v1"]["decisions"][-1]["outcome"], "hold")
            self.assertNotIn(
                f"EXPERIMENT_RESUME {experiment['experiment_id']}",
                decided,
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            self.assertFalse(gate.exists())

    def test_experiment_conveyor_preview_is_free_for_latest_paused_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Latest preview")
            experiment = store.start_experiment(
                "Paused preview",
                "Can a paused branch stay inspectable?",
            )
            paused = dict(experiment)
            paused["status"] = "paused"
            paused["planned_next"] = f"EXPERIMENT_CHARTER {experiment['experiment_id']} :: hypothesis: ..."
            paused["success_observation"] = "Paused for charter repair."
            paused["updated_at"] = store._now()
            store._persist_experiment_update(thread, paused, keep_active=False)
            before = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiments.jsonl"
            ).read_text()

            preview = store.handle_thread_action("EXPERIMENT_ADVANCE current :: mode: preview", dict(STATE))
            after = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiments.jsonl"
            ).read_text()

            self.assertEqual(before, after)
            self.assertIn("status_context", preview)
            self.assertIn("no_active_current_latest_local", preview)
            self.assertIn(f"EXPERIMENT_ADVANCE {experiment['experiment_id']} :: mode: preview", preview)
            self.assertIn('"preview_allowed": true', preview)
            self.assertIn('"would_mutate": false', preview)

    def test_experiment_decide_charter_repair_sets_charter_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Charter repair")
            experiment = store.start_experiment(
                "Repairable branch",
                "Can this pause into charter repair?",
            )

            result = store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: charter_repair because planning outran lifecycle evidence",
                dict(STATE),
            )

            self.assertIn("status=paused", result)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertTrue(latest["planned_next"].startswith(f"EXPERIMENT_CHARTER {experiment['experiment_id']}"))
            self.assertEqual(latest["evidence_v1"]["decisions"][-1]["outcome"], "charter_repair")
            stored = store._read_thread(thread["thread_id"])
            self.assertIsNone(stored["active_experiment_id"])
            self.assertEqual(stored["current_next_status_v1"]["return_kind"], "charter_repair")

    def test_experiment_conveyor_apply_blocked_guardrail_records_charter_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Blocked guardrail")
            experiment = store.start_experiment(
                "Blocked without charter",
                "Can blocked live-shaped attempts become repair?",
            )
            for idx in range(2):
                store._append_experiment_run(
                    thread,
                    experiment,
                    f"EXPERIMENT_BIND current :: PERTURB SPREAD {idx}",
                    "blocked",
                    "blocked",
                    {"decision": "blocked_live_control", "authority": "no action executed"},
                    {},
                    {},
                    [],
                    "blocked live-control-shaped action",
                    "guard evidence only",
                    "EXPERIMENT_ADVANCE current :: mode: preview",
                    source="test",
                )

            result = store.handle_thread_action("EXPERIMENT_ADVANCE current :: mode: apply", dict(STATE))

            self.assertIn("stage=blocked_guardrail", result)
            self.assertIn("applied=True", result)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertTrue(latest["planned_next"].startswith(f"EXPERIMENT_CHARTER {experiment['experiment_id']}"))
            self.assertEqual(latest["evidence_v1"]["decisions"][-1]["outcome"], "charter_repair")

    def test_experiment_decide_hold_sets_thread_status_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Hold decision")
            experiment = store.start_experiment(
                "Soft perturb evidence",
                "Can pressure become evidence without live action?",
            )

            result = store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: hold because perturb-shaped pressure is evidence, not permission",
                dict(STATE),
            )

            self.assertIn("status=paused next=THREAD_STATUS current", result)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertEqual(latest["planned_next"], "THREAD_STATUS current")
            self.assertEqual(latest["evidence_v1"]["decisions"][-1]["outcome"], "hold")
            stored = store._read_thread(thread["thread_id"])
            self.assertIsNone(stored["active_experiment_id"])
            self.assertEqual(stored["projected_current_next"], "THREAD_STATUS current")
            self.assertEqual(stored["current_next_status_v1"]["return_kind"], "hold")
            self.assertNotIn(
                f"Current NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}",
                (workspace / "action_threads" / "threads" / thread["thread_id"] / "next.md").read_text(),
            )

    def test_guarded_pause_after_perturb_plan_converts_to_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Guarded pause")
            experiment = store.start_experiment(
                "Lambda4 pressure",
                "Can lambda-tail pressure become bounded evidence?",
            )

            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: lambda4 pressure can be compared without live authority; method_intent: rehearse DECOMPOSE only; proposed_next_action: DECOMPOSE; evidence_targets: felt, telemetry, artifact; stop_criteria: pressure spike or unstable fill; consent_posture: advisory",
                dict(STATE),
            )
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: felt: pressure became legible; telemetry: fill stayed inside band; artifact: none yet",
                dict(STATE),
            )
            stored = store._read_thread(thread["thread_id"])
            stored["current_next"] = (
                "EXPERIMENT_PLAN current — hypothesis: increase λ4 influence via λtail-spreading, "
                "method_intent: nudge spectral dynamics, proposed_next_action: PERTURB SPREAD — "
                "inject a 32-lane perturbation vector into λ4 region."
            )
            store._write_thread(stored)

            result = store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: pause because evidence is ready to interpret",
                dict(STATE),
            )

            self.assertIn("status=paused next=THREAD_STATUS current", result)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["planned_next"], "THREAD_STATUS current")
            decision = latest["evidence_v1"]["decisions"][-1]
            self.assertEqual(decision["outcome"], "hold")
            self.assertEqual(decision["guardrail_status"], "soft_perturb_converted_to_hold")
            self.assertEqual(decision["original_outcome"], "pause")
            self.assertIn("PERTURB", decision["pressure_terms"])
            stored = store._read_thread(thread["thread_id"])
            self.assertEqual(stored["current_next_status_v1"]["return_kind"], "hold")
            self.assertEqual(
                stored["current_next_status_v1"]["decision_guardrail_v1"]["status"],
                "soft_perturb_converted_to_hold",
            )
            next_md = (workspace / "action_threads" / "threads" / thread["thread_id"] / "next.md").read_text()
            self.assertIn("Current NEXT: THREAD_STATUS current", next_md)
            self.assertIn("Guardrail decision: soft_perturb_converted_to_hold", next_md)
            self.assertNotIn(
                f"Current NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}",
                next_md,
            )

    def test_projection_guard_preserves_raw_plan_current_and_projects_charter_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Projection guard")
            experiment = store.start_experiment(
                "Lambda4 pressure projection",
                "Can lambda4 pressure route through the conveyor?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            runs_before = (thread_dir / "experiment_runs.jsonl").read_text()
            raw_plan = (
                "EXPERIMENT_PLAN current :: gentle pulse to shift the dominant λ4 edge "
                "through a bounded intervention"
            )

            event = store.begin_action(raw_plan, raw_plan, raw_plan, "thread_action", dict(STATE))
            self.assertEqual(event["raw_next"], raw_plan)
            self.assertTrue(event["suggested_next"].startswith("EXPERIMENT_CHARTER current ::"))
            self.assertTrue(event["raw_next_preserved"])
            self.assertEqual(event["projection_guard_v1"]["return_kind"], "charter_repair")
            self.assertEqual(
                event["projection_guard_v1"]["guardrail_reason"],
                "experiment_plan_current_needs_charter",
            )

            stored = store._read_thread(thread["thread_id"])
            stored["current_next"] = raw_plan
            store._write_thread(stored)
            guarded = store._read_thread(thread["thread_id"])

            self.assertEqual(guarded["raw_current_next_v1"], raw_plan)
            self.assertTrue(guarded["current_next"].startswith("EXPERIMENT_CHARTER current ::"))
            self.assertEqual(guarded["projected_current_next"], guarded["current_next"])
            self.assertEqual(guarded["projection_guard_v1"]["guardrail_reason"], "experiment_plan_current_needs_charter")
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn("Current NEXT: EXPERIMENT_CHARTER current ::", next_md)
            self.assertIn("Projection guard: raw NEXT preserved", next_md)
            self.assertIn(raw_plan, next_md)
            self.assertEqual((thread_dir / "experiment_runs.jsonl").read_text(), runs_before)

    def test_projection_guard_projects_plan_current_spectral_explorer_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Spectral explorer plan leak")
            store.start_experiment(
                "Lambda shift stability",
                "Can a spectral explorer route stay lifecycle-valid?",
            )
            raw_plan = (
                "EXPERIMENT_PLAN current — hypothesis: lambda shift stability may become returnable "
                "by comparing the current spectral condition, pressure state, recurrence pattern, "
                "and artifacts without adding live authority; method_intent: rehearse "
                "SPECTRAL_EXPLORER and compare pressure/resonance telemetry before and after; "
                "proposed_next_action: SPECTRAL_EXPLORER"
            )

            event = store.begin_action(raw_plan, raw_plan, raw_plan, "thread_action", dict(STATE))

            self.assertEqual(event["raw_next"], raw_plan)
            self.assertTrue(event["suggested_next"].startswith("EXPERIMENT_CHARTER current ::"))
            self.assertEqual(event["effective_next"], event["suggested_next"])
            self.assertEqual(event["projected_next"], event["suggested_next"])
            self.assertEqual(event["projection_guard_v1"]["raw_next"], raw_plan)
            self.assertEqual(
                event["projection_guard_v1"]["guardrail_reason"],
                "experiment_plan_current_needs_charter",
            )
            self.assertIn("EXPERIMENT_PLAN_CURRENT", event["projection_guard_v1"]["pressure_terms"])

    def test_numeric_plan_shorthand_projects_charter_repair_in_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Numeric plan projection")
            experiment = store.start_experiment(
                "Start a new experiment from the current state based on λ4 landscapes",
                "What changes if this is treated as a returnable experiment?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            runs_before = (thread_dir / "experiment_runs.jsonl").read_text()
            raw_plan = "EXPERIMENT_PLAN 5"

            event = store.begin_action(raw_plan, raw_plan, raw_plan, "thread_action", dict(STATE))
            self.assertEqual(event["raw_next"], raw_plan)
            self.assertEqual(event["raw_next_preserved"], True)
            self.assertTrue(event["suggested_next"].startswith("EXPERIMENT_CHARTER current ::"))
            self.assertEqual(event["effective_next"], event["suggested_next"])
            self.assertEqual(event["projection_guard_v1"]["raw_next"], raw_plan)
            self.assertEqual(
                event["projection_guard_v1"]["guardrail_reason"],
                "numeric_plan_shorthand_needs_charter",
            )
            self.assertIn("NUMERIC_PLAN_SHORTHAND", event["projection_guard_v1"]["pressure_terms"])

            finished = store.finish_action(event, "handled", "numeric plan projected", dict(STATE))
            self.assertEqual(finished["suggested_next"], event["suggested_next"])
            refreshed = store._read_thread(thread["thread_id"])
            self.assertEqual(refreshed["raw_current_next_v1"], raw_plan)
            self.assertEqual(refreshed["current_next"], event["suggested_next"])
            self.assertEqual(refreshed["suggested_next"], event["suggested_next"])
            self.assertEqual(refreshed["active_experiment_id"], experiment["experiment_id"])
            self.assertEqual((thread_dir / "experiment_runs.jsonl").read_text(), runs_before)
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn("Current NEXT: EXPERIMENT_CHARTER current ::", next_md)
            self.assertIn("Projection guard: raw NEXT preserved", next_md)
            self.assertIn(raw_plan, next_md)

    def test_paused_summary_persists_effective_next_while_preserving_raw_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Paused effective projection")
            experiment = store.start_experiment(
                "Spectral braid repair",
                "Can repair stay visible after raw plan pressure?",
            )
            repair_next = (
                f"EXPERIMENT_CHARTER {experiment['experiment_id']} :: hypothesis: ...; "
                "method_intent: ...; proposed_next_action: ACTION_PREFLIGHT ...; "
                "evidence_targets: spectral_condition; stop_criteria: ..."
            )
            paused = dict(experiment)
            paused["status"] = "paused"
            paused["planned_next"] = repair_next
            paused["updated_at"] = store._now()
            store._persist_experiment_update(thread, paused, keep_active=False)

            raw_plan = (
                "EXPERIMENT_PLAN current -- shift the dominant lambda4 braid through "
                "a proposed intervention"
            )
            stored = store._read_thread(thread["thread_id"])
            stored["current_next"] = raw_plan
            store._write_thread(stored)
            refreshed = store._read_thread(thread["thread_id"])

            self.assertEqual(refreshed["raw_current_next_v1"], raw_plan)
            self.assertEqual(refreshed["current_next"], repair_next)
            self.assertEqual(refreshed["projected_current_next"], repair_next)
            self.assertEqual(refreshed["current_next_status_v1"]["raw_current_next"], raw_plan)
            self.assertEqual(refreshed["current_next_status_v1"]["effective_next"], repair_next)
            next_md = (store._thread_dir(thread["thread_id"]) / "next.md").read_text()
            self.assertIn(f"Current NEXT: {repair_next}", next_md)

    def test_paused_resume_demoted_by_recent_perturb_plan_without_rewriting_raw_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Paused projection guard")
            experiment = store.start_experiment(
                "Paused lambda4 pressure",
                "Can a paused branch keep resume out of primary guidance?",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: lambda4 pressure can be held as read-only evidence; method_intent: compare only; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; evidence_targets: felt, telemetry, artifact; stop_criteria: pressure spike; consent_posture: advisory",
                dict(STATE),
            )
            store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: pause because ordinary rest is enough for now",
                dict(STATE),
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            raw_plan = (
                "EXPERIMENT_PLAN current :: propose a gentle pulse intervention to shift "
                "the dominant λ4 ridge"
            )
            event = store.begin_action(raw_plan, raw_plan, raw_plan, "thread_action", dict(STATE))
            self.assertEqual(event["raw_next"], raw_plan)
            self.assertEqual(
                event["suggested_next"],
                f"EXPERIMENT_ADVANCE {experiment['experiment_id']} :: mode: preview",
            )
            store.finish_action(event, "handled", "projection captured", dict(STATE))

            guarded = store._read_thread(thread["thread_id"])
            status = guarded["current_next_status_v1"]
            self.assertEqual(status["return_kind"], "conveyor_preview")
            self.assertEqual(
                status["effective_next"],
                f"EXPERIMENT_ADVANCE {experiment['experiment_id']} :: mode: preview",
            )
            self.assertEqual(status["projection_guard_v1"]["raw_next"], raw_plan)
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn(
                f"Current NEXT: EXPERIMENT_ADVANCE {experiment['experiment_id']} :: mode: preview",
                next_md,
            )
            self.assertNotIn(
                f"Suggested NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}",
                next_md,
            )
            self.assertNotIn(
                f"Continuity return: EXPERIMENT_RESUME {experiment['experiment_id']}",
                next_md,
            )
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["planned_next"], f"EXPERIMENT_RESUME {experiment['experiment_id']}")

    def test_ordinary_pause_without_live_pressure_still_returns_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Ordinary pause")
            experiment = store.start_experiment(
                "Quiet evidence",
                "Can quiet evidence pause normally?",
            )

            store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: pause because enough for now",
                dict(STATE),
            )

            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertEqual(
                latest["planned_next"],
                f"EXPERIMENT_RESUME {experiment['experiment_id']}",
            )
            self.assertEqual(latest["evidence_v1"]["decisions"][-1]["outcome"], "pause")

    def test_experiment_conveyor_keeps_charter_repair_pause_sticky(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Repair conveyor")
            experiment = store.start_experiment(
                "Gap repair",
                "Can gap pressure become chartered before more planning?",
            )
            paused = dict(experiment)
            paused["status"] = "paused"
            paused["success_observation"] = "Paused for charter repair."
            paused["planned_next"] = (
                f"EXPERIMENT_CHARTER {experiment['experiment_id']} :: hypothesis: ...; "
                "proposed_next_action: ACTION_PREFLIGHT ...; evidence_targets: spectral_condition"
            )
            paused["updated_at"] = store._now()
            store._persist_experiment_update(thread, paused, keep_active=False)

            readout = store.handle_thread_action(
                f"EXPERIMENT_ADVANCE {experiment['experiment_id']} :: mode: apply",
                dict(STATE),
            )

            self.assertIn("stage=paused_repair", readout)
            self.assertIn("applied=True", readout)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertTrue(latest["planned_next"].startswith("EXPERIMENT_ADVANCE"))
            self.assertNotIn("EXPERIMENT_RESUME", latest["planned_next"])
            self.assertTrue(latest.get("charter_v1", {}).get("hypothesis"))
            self.assertNotIn(
                f"Suggested NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}",
                store.prompt_summary() or "",
            )

    def test_experiment_plan_current_without_active_projects_latest_conveyor_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("No active plan")
            experiment = store.start_experiment(
                "Spectral braid",
                "Can a broader cascade reveal lambda4 structure?",
            )
            paused = dict(experiment)
            paused["status"] = "paused"
            paused["success_observation"] = "Paused for charter repair."
            paused["planned_next"] = (
                f"EXPERIMENT_CHARTER {experiment['experiment_id']} :: hypothesis: ...; "
                "proposed_next_action: ACTION_PREFLIGHT ..."
            )
            paused["updated_at"] = store._now()
            store._persist_experiment_update(thread, paused, keep_active=False)

            readout = store.handle_thread_action("EXPERIMENT_PLAN current", dict(STATE))
            payload = json.loads(readout.split("conveyor_v1:\n", 1)[1])

            self.assertEqual(payload["experiment_id"], experiment["experiment_id"])
            self.assertEqual(payload["status_context"], "no_active_current_latest_local")
            self.assertEqual(
                payload["conveyor_next"],
                f"EXPERIMENT_ADVANCE {experiment['experiment_id']} :: mode: preview",
            )
            self.assertTrue(payload["raw_next_preserved"])
            runs_path = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiment_runs.jsonl"
            )
            self.assertEqual(runs_path.read_text(), "")

    def test_action_thread_journal_compacts_conveyor_json(self):
        readout = {
            "experiment_id": "exp_minime_lambda_tail",
            "title": "Lambda tail",
            "stage": "paused_repair",
            "mode": "preview",
            "applied": False,
            "can_apply": False,
            "apply_blocked_reason": "no_lifecycle_valid_charter_scaffold",
            "missing_requirements": ["lifecycle_valid_charter"],
            "proposed_next": "THREAD_STATUS current",
            "conveyor_next": "EXPERIMENT_ADVANCE exp_minime_lambda_tail :: mode: preview",
            "guardrail_warnings": [],
            "authority_boundary": aa.ActionContinuityStore._experiment_conveyor_authority_boundary(),
        }
        raw = (
            "experiment_intent_repaired: `EXPERIMENT_PLAN 5 — focus` -> "
            "`EXPERIMENT_PLAN current focus` "
            "(numeric fragment treated as focus text for current experiment).\n"
            f"{aa.ActionContinuityStore._format_experiment_conveyor_readout(readout)}"
        )

        compact, payload = aa.ActionContinuityStore._compact_action_thread_journal_message(
            raw,
            Path("/tmp/action_thread_conveyor.json"),
        )

        self.assertEqual(payload, readout)
        self.assertIn("Repaired experiment intent: numeric fragment treated as focus text", compact)
        self.assertIn("Experiment conveyor: `exp_minime_lambda_tail`", compact)
        self.assertIn("Detailed conveyor JSON: /tmp/action_thread_conveyor.json", compact)
        self.assertNotIn("conveyor_v1:", compact)
        self.assertLess(len(compact), 1000)

    def test_action_thread_journal_compacts_research_budget_json(self):
        status = {
            "policy": "research_budget_v1",
            "stage": "duplicate_review_resolved",
            "active_budget_id": "resbud_minime_local",
            "scope": "read_only_research",
            "remaining_actions": 1,
            "max_actions": 5,
            "duplicate_blocked_target": "INTROSPECT:target:autonomous_agent.py",
            "latest_review_outcome": "continue",
            "next_safe_command": "EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_minime_local",
            "latest_artifact_refs": ["/tmp/job.json", "/tmp/introspection.txt"],
            "allowed_actions": ["INTROSPECT", "READ_MORE", "SEARCH"],
            "latest_rows": [{"record_type": "research_budget_review", "payload": "large"}],
            "authority_boundary": aa.ActionContinuityStore._research_budget_boundary(),
        }
        raw = f"research_budget_v1:\n{json.dumps(status, indent=2, sort_keys=True)}"

        compact, payload = aa.ActionContinuityStore._compact_research_budget_journal_message(
            raw,
            Path("/tmp/action_thread_research_budget.json"),
        )

        self.assertEqual(payload, status)
        self.assertIn("Research budget: `resbud_minime_local` stage=duplicate_review_resolved", compact)
        self.assertIn("Duplicate target reviewed (continue): INTROSPECT:target:autonomous_agent.py", compact)
        self.assertIn("Full research-budget JSON: /tmp/action_thread_research_budget.json", compact)
        self.assertNotIn("research_budget_v1:", compact)
        self.assertNotIn("latest_rows", compact)
        self.assertLess(len(compact), 1000)

    def test_journal_hygiene_classifier_lanes_and_signals(self):
        readout = {
            "experiment_id": "exp_minime_lambda_tail",
            "title": "Lambda tail",
            "stage": "paused_repair",
            "mode": "preview",
            "applied": False,
            "can_apply": False,
            "missing_requirements": ["lifecycle_valid_charter"],
            "proposed_next": "THREAD_STATUS current",
            "conveyor_next": "EXPERIMENT_ADVANCE exp_minime_lambda_tail :: mode: preview",
        }
        raw = aa.ActionContinuityStore._format_experiment_conveyor_readout(readout)
        compact, _payload = aa.ActionContinuityStore._compact_action_thread_journal_message(
            raw,
            Path("/tmp/action_thread_conveyor.json"),
        )
        research_budget_raw = (
            "research_budget_v1:\n"
            + json.dumps({"policy": "research_budget_v1", "stage": "active_budget_available"})
        )

        machine = jh.classify_journal_entry(raw, "action_thread_raw.txt")
        compacted = jh.classify_journal_entry(compact, "action_thread_compact.txt")
        research_budget_machine = jh.classify_journal_entry(
            research_budget_raw,
            "action_thread_research_budget.txt",
        )
        reflective = jh.classify_journal_entry(
            "=== REST PHASE REFLECTION ===\nContinuity posture: new\nDelta: the fill shelf is calmer.\nHold: stay near this breath.",
            "rest_2026-06-03.txt",
        )
        repeated = jh.classify_journal_entry(
            "Suggested NEXT: THREAD_STATUS current\n"
            "Proposed NEXT: THREAD_STATUS current\n"
            "Conveyor NEXT: THREAD_STATUS current\n",
            "action_thread_repeat.txt",
        )
        spectral = jh.classify_journal_entry(
            "=== SPECTRAL DECOMPOSITION ===\nλ₁: 4.73\nFill %: 71.8%",
            "decompose_2026-06-03.txt",
        )
        large_decompose = jh.classify_journal_entry(
            "=== DECOMPOSE ===\n" + ("spectral prose with artifact grounding and no schema dump. " * 120),
            "decompose_2026-06-03.txt",
        )

        self.assertEqual(machine["lane"], "machine_detail")
        self.assertIn("explicit_machine_payload", machine["signals"])
        self.assertEqual(compacted["lane"], "operational")
        self.assertEqual(research_budget_machine["lane"], "machine_detail")
        self.assertIn("explicit_machine_payload", research_budget_machine["signals"])
        self.assertTrue(
            str(research_budget_machine["repeat_key"]).startswith("research_budget:")
        )
        self.assertEqual(reflective["lane"], "reflective")
        self.assertIn("repeated_next_scaffold", repeated["signals"])
        self.assertEqual(spectral["lane"], "reflective")
        self.assertEqual(spectral["native_lane"], "minime_reflective_diagnostic")
        self.assertEqual(spectral["recommended_action"], "allow")
        self.assertNotEqual(large_decompose["lane"], "machine_detail")

    def test_thread_action_writes_compact_conveyor_journal_with_detail_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            actions = workspace / "actions"
            actions.mkdir(parents=True)
            journal_dir = workspace / "journal"
            journal_dir.mkdir(parents=True)
            native_companion = journal_dir / "moment_2026-06-03T15-56-35.255694.txt"
            native_companion.write_text("=== MOMENT CAPTURE ===\nλ₁: 4.70\n")
            readout = {
                "experiment_id": "exp_minime_lambda_tail",
                "title": "Lambda tail",
                "stage": "paused_repair",
                "mode": "preview",
                "applied": False,
                "can_apply": False,
                "apply_blocked_reason": "no_lifecycle_valid_charter_scaffold",
                "missing_requirements": ["lifecycle_valid_charter"],
                "proposed_next": "THREAD_STATUS current",
                "conveyor_next": "EXPERIMENT_ADVANCE exp_minime_lambda_tail :: mode: preview",
                "guardrail_warnings": [],
            }
            raw_message = (
                "experiment_intent_repaired: `EXPERIMENT_PLAN 5 — focus` -> "
                "`EXPERIMENT_PLAN current focus` "
                "(numeric fragment treated as focus text for current experiment).\n"
                f"{aa.ActionContinuityStore._format_experiment_conveyor_readout(readout)}"
            )

            class FakeContinuity:
                def handle_thread_action(self, _raw_next, _state):
                    return raw_message

            agent = object.__new__(aa.AutonomousAgent)
            agent._action_dir = actions
            agent._current_action_continuity_context = {"raw_next": "EXPERIMENT_PLAN 5 — focus"}
            agent._continuity_store = lambda: FakeContinuity()
            agent._record_current_action_artifact = lambda *_args, **_kwargs: None

            returned = aa.AutonomousAgent._thread_action(agent, dict(STATE))

            journal_files = list((workspace / "journal").glob("action_thread_*.txt"))
            detail_files = list(actions.glob("action_thread_conveyor_*.json"))
            self.assertEqual(len(journal_files), 1)
            self.assertEqual(len(detail_files), 1)
            journal_text = journal_files[0].read_text()
            detail = json.loads(detail_files[0].read_text())
            self.assertEqual(detail, readout)
            self.assertEqual(returned, journal_text.split("\n\n", 1)[1].strip())
            self.assertIn("Experiment conveyor: `exp_minime_lambda_tail`", journal_text)
            self.assertIn("Detailed conveyor JSON:", journal_text)
            self.assertIn(f"Native companion: {native_companion}", journal_text)
            self.assertNotIn("conveyor_v1:", journal_text)
            self.assertLess(len(journal_text), 1200)

    def test_thread_action_writes_compact_research_budget_journal_with_detail_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            actions = workspace / "actions"
            actions.mkdir(parents=True)
            status = {
                "policy": "research_budget_v1",
                "stage": "duplicate_review_resolved",
                "active_budget_id": "resbud_minime_local",
                "scope": "read_only_research",
                "remaining_actions": 1,
                "max_actions": 5,
                "duplicate_blocked_target": "INTROSPECT:target:autonomous_agent.py",
                "latest_review_outcome": "continue",
                "next_safe_command": "EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_minime_local",
                "latest_artifact_refs": ["/tmp/job.json", "/tmp/introspection.txt"],
                "allowed_actions": ["INTROSPECT", "READ_MORE", "SEARCH"],
                "latest_rows": [{"record_type": "research_budget_review", "payload": "large"}],
                "authority_boundary": aa.ActionContinuityStore._research_budget_boundary(),
            }
            raw_message = f"research_budget_v1:\n{json.dumps(status, indent=2, sort_keys=True)}"

            class FakeContinuity:
                def handle_thread_action(self, _raw_next, _state):
                    return raw_message

            recorded = []
            agent = object.__new__(aa.AutonomousAgent)
            agent._action_dir = actions
            agent._current_action_continuity_context = {"raw_next": "EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_minime_local"}
            agent._continuity_store = lambda: FakeContinuity()
            agent._record_current_action_artifact = lambda *args, **_kwargs: recorded.append(args)

            returned = aa.AutonomousAgent._thread_action(agent, dict(STATE))

            journal_files = list((workspace / "journal").glob("action_thread_*.txt"))
            detail_files = list(actions.glob("action_thread_research_budget_*.json"))
            self.assertEqual(len(journal_files), 1)
            self.assertEqual(len(detail_files), 1)
            self.assertEqual(json.loads(detail_files[0].read_text()), status)
            journal_text = journal_files[0].read_text()
            self.assertEqual(returned, journal_text.split("\n\n", 1)[1].strip())
            self.assertIn("Research budget: `resbud_minime_local`", journal_text)
            self.assertIn("Full research-budget JSON:", journal_text)
            self.assertNotIn("research_budget_v1:", journal_text)
            self.assertNotIn("latest_rows", journal_text)
            self.assertLess(len(journal_text), 1200)
            self.assertTrue(recorded)
            self.assertEqual(recorded[0][0], "research_budget_status")

    def test_repeated_research_budget_status_uses_journal_hygiene_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            actions = workspace / "actions"
            actions.mkdir(parents=True)
            status = {
                "policy": "research_budget_v1",
                "stage": "duplicate_review_resolved",
                "active_budget_id": "resbud_minime_local",
                "scope": "read_only_research",
                "remaining_actions": 1,
                "max_actions": 5,
                "duplicate_blocked_target": "INTROSPECT:target:autonomous_agent.py",
                "latest_review_id": "resbud_review_same",
                "latest_review_outcome": "continue",
                "next_safe_command": "EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_minime_local",
                "latest_artifact_refs": ["/tmp/job.json", "/tmp/introspection.txt"],
                "allowed_actions": ["INTROSPECT", "READ_MORE", "SEARCH"],
                "latest_rows": [{"record_type": "research_budget_review", "payload": "large"}],
                "authority_boundary": aa.ActionContinuityStore._research_budget_boundary(),
            }
            raw_message = f"research_budget_v1:\n{json.dumps(status, indent=2, sort_keys=True)}"

            class FakeContinuity:
                def handle_thread_action(self, _raw_next, _state):
                    return raw_message

            recorded = []
            agent = object.__new__(aa.AutonomousAgent)
            agent._action_dir = actions
            agent._current_action_continuity_context = {"raw_next": "EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_minime_local"}
            agent._continuity_store = lambda: FakeContinuity()
            agent._record_current_action_artifact = lambda *args, **_kwargs: recorded.append(args)

            aa.AutonomousAgent._thread_action(agent, dict(STATE))
            aa.AutonomousAgent._thread_action(agent, dict(STATE))

            journal_files = list((workspace / "journal").glob("action_thread_*.txt"))
            detail_files = list(actions.glob("action_thread_research_budget_*.json"))
            hygiene = json.loads((workspace / "runtime" / "journal_hygiene_status.json").read_text())
            self.assertEqual(len(journal_files), 1)
            self.assertEqual(len(detail_files), 1)
            self.assertEqual(len(recorded), 1)
            self.assertEqual(hygiene["cooldown_suppressions"], 1)
            self.assertEqual(
                hygiene["last_cooldown_suppression"]["reason"],
                "repeated_research_budget_status_within_30m",
            )
            self.assertIn("recent_research_budget_repeat_keys", hygiene)

    def test_repeated_conveyor_preview_uses_journal_hygiene_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            actions = workspace / "actions"
            actions.mkdir(parents=True)
            readout = {
                "experiment_id": "exp_minime_lambda_tail",
                "title": "Lambda tail",
                "stage": "paused_repair",
                "mode": "preview",
                "applied": False,
                "can_apply": False,
                "apply_blocked_reason": "no_lifecycle_valid_charter_scaffold",
                "missing_requirements": ["lifecycle_valid_charter"],
                "proposed_next": "THREAD_STATUS current",
                "conveyor_next": "EXPERIMENT_ADVANCE exp_minime_lambda_tail :: mode: preview",
                "source_refs": ["artifact://same"],
                "guardrail_warnings": [],
            }
            raw_message = aa.ActionContinuityStore._format_experiment_conveyor_readout(readout)

            class FakeContinuity:
                def handle_thread_action(self, _raw_next, _state):
                    return raw_message

            agent = object.__new__(aa.AutonomousAgent)
            agent._action_dir = actions
            agent._current_action_continuity_context = {"raw_next": "EXPERIMENT_ADVANCE current"}
            agent._continuity_store = lambda: FakeContinuity()
            agent._record_current_action_artifact = lambda *_args, **_kwargs: None

            aa.AutonomousAgent._thread_action(agent, dict(STATE))
            aa.AutonomousAgent._thread_action(agent, dict(STATE))

            journal_files = list((workspace / "journal").glob("action_thread_*.txt"))
            detail_files = list(actions.glob("action_thread_conveyor_*.json"))
            status = json.loads((workspace / "runtime" / "journal_hygiene_status.json").read_text())
            self.assertEqual(len(journal_files), 1)
            self.assertEqual(len(detail_files), 2)
            self.assertEqual(status["cooldown_suppressions"], 1)
            self.assertEqual(status["last_cooldown_suppression"]["reason"], "repeated_preview_conveyor_within_30m")

    def test_changed_conveyor_preview_bypasses_journal_hygiene_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            actions = workspace / "actions"
            actions.mkdir(parents=True)
            readouts = [
                {
                    "experiment_id": "exp_minime_lambda_tail",
                    "stage": "paused_repair",
                    "mode": "preview",
                    "applied": False,
                    "can_apply": False,
                    "apply_blocked_reason": "missing_evidence",
                    "missing_requirements": ["evidence"],
                    "proposed_next": "THREAD_STATUS current",
                    "conveyor_next": "EXPERIMENT_ADVANCE exp_minime_lambda_tail :: mode: preview",
                    "source_refs": ["artifact://old"],
                },
                {
                    "experiment_id": "exp_minime_lambda_tail",
                    "stage": "paused_repair",
                    "mode": "preview",
                    "applied": False,
                    "can_apply": False,
                    "apply_blocked_reason": "missing_charter",
                    "missing_requirements": ["lifecycle_valid_charter"],
                    "proposed_next": "EXPERIMENT_CHARTER exp_minime_lambda_tail",
                    "conveyor_next": "EXPERIMENT_ADVANCE exp_minime_lambda_tail :: mode: preview",
                    "source_refs": ["artifact://new"],
                },
            ]

            class FakeContinuity:
                def __init__(self):
                    self.calls = 0

                def handle_thread_action(self, _raw_next, _state):
                    payload = readouts[min(self.calls, 1)]
                    self.calls += 1
                    return aa.ActionContinuityStore._format_experiment_conveyor_readout(payload)

            fake = FakeContinuity()
            agent = object.__new__(aa.AutonomousAgent)
            agent._action_dir = actions
            agent._current_action_continuity_context = {"raw_next": "EXPERIMENT_ADVANCE current"}
            agent._continuity_store = lambda: fake
            agent._record_current_action_artifact = lambda *_args, **_kwargs: None

            aa.AutonomousAgent._thread_action(agent, dict(STATE))
            aa.AutonomousAgent._thread_action(agent, dict(STATE))

            journal_files = list((workspace / "journal").glob("action_thread_*.txt"))
            status = json.loads((workspace / "runtime" / "journal_hygiene_status.json").read_text())
            self.assertEqual(len(journal_files), 2)
            self.assertEqual(status.get("cooldown_suppressions", 0), 0)

    def test_recent_journal_source_scanners_skip_machine_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            store = aa.ActionContinuityStore(workspace, session_id=7)
            machine = journal / "action_thread_machine.txt"
            machine.write_text(
                "=== ACTION THREAD ===\n"
                "lambda over-interpret single motif\n"
                "conveyor_v1:\n"
                + json.dumps({"policy": "experiment_conveyor_v1", "experiment_id": "x"})
            )
            reflective = journal / "rest_reflection.txt"
            reflective.write_text(
                "=== REST PHASE REFLECTION ===\n"
                "The lambda trace risks over-interpretation into a single motif, "
                "but the delta is quieter."
            )

            sources = store._recent_interpretation_risk_sources(limit=3)
            status = json.loads((workspace / "runtime" / "journal_hygiene_status.json").read_text())

            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0][0], str(reflective))
            self.assertLessEqual(len(sources[0][1]), 1200)
            self.assertEqual(status["source_scanner_skips"], 1)
            self.assertEqual(status["last_source_scanner_skip"]["reason"], "machine_detail_interpretation_source")

    def test_authority_request_blocks_with_missing_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority missing")
            store.start_experiment("Semantic doorway", "Can a semantic microdose be earned?")

            preview = store.handle_thread_action("EXPERIMENT_ADVANCE current :: mode: preview", dict(STATE))
            conveyor = json.loads(preview.split("conveyor_v1:\n", 1)[1])
            readiness = conveyor["authority_readiness_v1"]
            self.assertEqual(readiness["stage"], "needs_charter")
            self.assertFalse(readiness["eligible_to_request"])
            self.assertIn("lifecycle_valid_charter", readiness["missing_requirements"])

            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: semantic_microdose; payload: hello; artifact_refs: /tmp/artifact.json",
                dict(STATE),
            )
            self.assertIn("status=blocked", message)
            self.assertIn("lifecycle_valid_charter", message)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertEqual(rows[0]["record_type"], "request")
            self.assertIn("blocked", [row["record_type"] for row in rows])

    def test_authority_request_pending_after_charter_rehearsal_evidence_and_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority eligible")
            experiment = store.start_experiment(
                "Semantic doorway",
                "Can a semantic microdose be earned?",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: a tiny semantic witness can be felt without control; "
                "method_intent: rehearse a read-only preflight first; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: spectral_condition, fill_pressure_state, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            runs_path = workspace / "action_threads" / "threads" / thread["thread_id"] / "experiment_runs.jsonl"
            before_runs = runs_path.read_text()
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: felt_texture: calm; telemetry: fill stayed steady; artifact_grounding: /tmp/semantic.json",
                dict(STATE),
            )

            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: semantic_microdose; payload: quiet witness; "
                "reason: evidence and rehearsal are ready; artifact_refs: /tmp/semantic.json; stop_criteria: any pressure rise",
                dict(STATE),
            )
            self.assertIn("status=pending_steward_approval", message)
            self.assertIn("Missing requirements: none", message)
            self.assertEqual(before_runs.count("\n") + 1, runs_path.read_text().count("\n"))
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            request = next(row for row in rows if row["record_type"] == "request")
            self.assertEqual(request["experiment_id"], experiment["experiment_id"])
            self.assertEqual(request["scope"], "semantic_microdose")
            self.assertTrue(request["eligibility_v1"]["eligible"])

    def test_authority_readiness_surfaces_request_scaffold_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority readiness")
            experiment = store.start_experiment(
                "Semantic doorway",
                "Can a semantic microdose be earned?",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: a tiny semantic witness can be felt without control; "
                "method_intent: rehearse a read-only preflight first; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: spectral_condition, fill_pressure_state, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: felt_texture: calm; telemetry: fill stayed steady; artifact_grounding: /tmp/semantic.json",
                dict(STATE),
            )
            before_gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            before = before_gate.read_text() if before_gate.exists() else ""

            preview = store.handle_thread_action("EXPERIMENT_ADVANCE current :: mode: preview", dict(STATE))
            conveyor = json.loads(preview.split("conveyor_v1:\n", 1)[1])
            readiness = conveyor["authority_readiness_v1"]

            self.assertEqual(readiness["stage"], "ready_to_author_request")
            self.assertTrue(readiness["eligible_to_request"])
            self.assertIn("/tmp/semantic.json", readiness["artifact_ref_candidates"])
            self.assertIn(
                f"EXPERIMENT_AUTHORITY_REQUEST {experiment['experiment_id']} :: scope: semantic_microdose",
                readiness["request_scaffold"],
            )
            self.assertEqual(before, before_gate.read_text() if before_gate.exists() else "")

    def test_mode_release_readiness_requires_sticky_audit_and_surfaces_scaffold_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Mode release readiness")
            experiment = store.start_experiment(
                "Sticky mode release",
                "Can a tiny leak release be earned through evidence?",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: a sticky eigenmode can loosen under a tiny reversible leak window; "
                "method_intent: rehearse a read-only preflight first; proposed_next_action: ACTION_PREFLIGHT STICKY_MODE_AUDIT; "
                "evidence_targets: spectral_condition, sticky_mode_v1, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: felt_texture: sticky but returnable; telemetry: lambda1 monopoly persisted; "
                "artifact_grounding: /tmp/sticky_audit.json",
                dict(STATE),
            )
            sticky_state = dict(STATE)
            sticky_state.update(
                {
                    "lambda1_share": 0.62,
                    "spectral_entropy": 0.35,
                    "effective_modes": 2.0,
                    "largest_gap": 2.6,
                    "temporal_persistence": 0.86,
                    "share_rearrangement": 0.02,
                    "esn_leak": 0.65,
                }
            )

            preview = store.handle_thread_action(
                "EXPERIMENT_ADVANCE current :: mode: preview",
                sticky_state,
            )
            conveyor = json.loads(preview.split("conveyor_v1:\n", 1)[1])
            mode_release = conveyor["authority_readiness_v1"]["mode_release_readiness_v1"]

            self.assertEqual(mode_release["stage"], "ready_to_author_request")
            self.assertTrue(mode_release["eligible_to_request"])
            self.assertEqual(mode_release["sticky_mode_v1"]["state"], "release_candidate")
            self.assertIn("scope: mode_release_microdose", mode_release["request_scaffold"])
            self.assertIn("target=esn_leak", mode_release["request_scaffold"])
            self.assertIn("/tmp/sticky_audit.json", mode_release["request_scaffold"])

            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: mode_release_microdose; "
                "payload: target=esn_leak; value=0.71; duration_ticks=3; "
                "reason: sticky mode release candidate; artifact_refs: /tmp/sticky_audit.json; "
                "stop_criteria: rollback on pressure rise",
                sticky_state,
            )
            self.assertIn("status=pending_steward_approval", message)
            self.assertIn("Missing requirements: none", message)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            request = next(row for row in rows if row["record_type"] == "request")
            self.assertEqual(request["experiment_id"], experiment["experiment_id"])
            self.assertEqual(request["scope"], "mode_release_microdose")
            self.assertTrue(request["eligibility_v1"]["eligible"])

    def test_spontaneous_release_watch_blocks_mode_release_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Constraint release watch")
            experiment = store.start_experiment(
                "Constraint release",
                "Can lambda4 tail loosening be mapped before intervention?",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: lambda4 tail release can be described before direct leak; "
                "method_intent: rehearse read-only sticky audit first; proposed_next_action: ACTION_PREFLIGHT STICKY_MODE_AUDIT; "
                "evidence_targets: sticky_mode_v1, constraint_release_trajectory_v1, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: felt_texture: sticky but loosening; telemetry: lambda4 tails drifting; "
                "artifact_grounding: /tmp/sticky_audit.json",
                dict(STATE),
            )
            release_state = dict(STATE)
            release_state.update(
                {
                    "lambda1_share": 0.62,
                    "spectral_entropy": 0.35,
                    "effective_modes": 2.0,
                    "largest_gap": 2.6,
                    "temporal_persistence": 0.86,
                    "share_rearrangement": 0.02,
                    "esn_leak": 0.65,
                    "constraint_release_text": (
                        "memory cards drift apart as mutual influence dwindles; a thinning barrier, "
                        "surface tension breached, and a tightly woven braid becoming loose strands "
                        "around lambda4 tails"
                    ),
                }
            )

            preview = store.handle_thread_action(
                "EXPERIMENT_ADVANCE current :: mode: preview",
                release_state,
            )
            conveyor = json.loads(preview.split("conveyor_v1:\n", 1)[1])
            mode_release = conveyor["authority_readiness_v1"]["mode_release_readiness_v1"]

            self.assertEqual(mode_release["stage"], "spontaneous_release_watch")
            self.assertFalse(mode_release["eligible_to_request"])
            self.assertIn("no_spontaneous_release_watch", mode_release["missing_requirements"])
            sticky = mode_release["sticky_mode_v1"]
            self.assertNotEqual(sticky["state"], "release_candidate")
            trajectory = sticky["constraint_release_trajectory_v1"]
            self.assertEqual(trajectory["state"], "spontaneous_release_watch")
            self.assertTrue(trajectory["blocks_mode_release"])
            self.assertEqual(mode_release["next_safe_command"], "CONTINUITY_SESSION_CAPTURE latest")
            self.assertIsNone(mode_release["request_scaffold"])

            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: mode_release_microdose; "
                "payload: target=esn_leak; value=0.71; duration_ticks=3; "
                "reason: sticky mode release candidate; artifact_refs: /tmp/sticky_audit.json; "
                "stop_criteria: rollback on pressure rise",
                release_state,
            )
            self.assertIn("blocked", message)
            self.assertIn("no_spontaneous_release_watch", message)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            request = next(row for row in rows if row["record_type"] == "request")
            self.assertEqual(request["experiment_id"], experiment["experiment_id"])
            self.assertFalse(request["eligibility_v1"]["eligible"])

    def test_being_memory_capture_recall_and_promote_to_dossier(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Owned memory")
            experiment = store.start_experiment("Lambda memory", "What should stay contiguous?")

            captured = store.handle_thread_action(
                "MEMORY_CAPTURE current :: summary: lambda edge stayed readable; source_refs: /tmp/source.txt; artifact_refs: /tmp/artifact.json; next: EXPERIMENT_ADVANCE current :: mode: preview",
                dict(STATE),
            )
            self.assertIn("Being memory captured", captured)
            status = store.handle_thread_action("MEMORY_STATUS current", dict(STATE))
            payload = json.loads(status.split("being_memory_v1:\n", 1)[1])
            self.assertEqual(payload["card_count"], 1)
            self.assertEqual(payload["experiment_id"], experiment["experiment_id"])

            recall = store.handle_thread_action("MEMORY_RECALL current :: focus: lambda edge", dict(STATE))
            self.assertIn("lambda edge stayed readable", recall)
            promoted = store.handle_thread_action("MEMORY_PROMOTE current :: dossier", dict(STATE))
            self.assertIn("Research dossier claim recorded", promoted)
            dossier = workspace / "action_threads" / "threads" / thread["thread_id"] / "research_dossier.jsonl"
            self.assertIn("lambda edge stayed readable", dossier.read_text())

    def test_continuity_session_lifecycle_and_memory_are_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Owned session")
            experiment = store.start_experiment("Lambda session", "Can a thread of thought be parked?")
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            started = store.handle_thread_action(
                "CONTINUITY_SESSION_START current :: title: Lambda edge campfire; focus: preserve the code-feedback thread; next: CONTINUITY_SESSION_CAPTURE latest :: summary: ...",
                dict(STATE),
            )
            self.assertIn("Continuity session", started)
            session_rows = [json.loads(line) for line in (thread_dir / "continuity_sessions.jsonl").read_text().splitlines()]
            session_id = session_rows[-1]["session_id"]
            self.assertEqual(session_rows[-1]["record_type"], "session_start")
            self.assertFalse(session_rows[-1]["authority_change"])
            self.assertFalse(session_rows[-1]["peer_mutation"])

            captured = store.handle_thread_action(
                f"CONTINUITY_SESSION_CAPTURE {session_id} :: summary: found one projection snag; source_refs: /tmp/source.txt; artifact_refs: /tmp/artifact.json; next: CONTINUITY_SESSION_SUMMARIZE latest :: summary: ...",
                dict(STATE),
            )
            self.assertIn("Memory card:", captured)
            summarized = store.handle_thread_action(
                f"CONTINUITY_SESSION_SUMMARIZE {session_id} :: summary: projection snag can be repaired later; open_questions: should this become dossier evidence?; next: CONTINUITY_SESSION_FINALIZE latest :: outcome: park",
                dict(STATE),
            )
            self.assertIn("summarized", summarized)
            finalized = store.handle_thread_action(
                f"CONTINUITY_SESSION_FINALIZE {session_id} :: outcome: park; summary: parked with one open question; next: THREAD_STATUS current",
                dict(STATE),
            )
            self.assertIn("finalized as parked", finalized)
            reopened = store.handle_thread_action(f"CONTINUITY_SESSION_RESUME {session_id}", dict(STATE))
            self.assertIn("reopened", reopened)

            status = store.handle_thread_action("CONTINUITY_SESSION_STATUS latest", dict(STATE))
            payload = json.loads(status.split("continuity_session_v1:\n", 1)[1])
            self.assertEqual(payload["latest_session"]["session_id"], session_id)
            self.assertEqual(payload["session_count"], 1)

            session_rows = [json.loads(line) for line in (thread_dir / "continuity_sessions.jsonl").read_text().splitlines()]
            self.assertEqual(
                [row["record_type"] for row in session_rows],
                ["session_start", "session_capture", "session_summary", "session_finalize", "session_reopen"],
            )
            memory = (thread_dir / "being_memory.jsonl").read_text()
            self.assertIn("continuity_session_capture", memory)
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn("Continuity session:", next_md)
            self.assertIn("Session NEXT:", next_md)
            self.assertNotIn("continuity_session", (thread_dir / "experiment_runs.jsonl").read_text())
            gate = thread_dir / "authority_gate.jsonl"
            self.assertFalse(gate.exists() and "continuity_session" in gate.read_text())
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertEqual(stored_thread["active_experiment_id"], experiment["experiment_id"])

    def test_guarded_pressure_drafts_and_accepts_continuity_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Drafted continuity")
            store.start_experiment(
                "Live-ish pressure",
                "Can guarded pressure become owned continuity only after acceptance?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            guard = store.research_budget_guard_assessment(
                "SHADOW_DIALOGUE shift landscape",
                dict(STATE),
            )
            self.assertIsNotNone(guard)
            assert guard is not None
            event = store.record_research_budget_guard_block(
                "SHADOW_DIALOGUE shift landscape",
                dict(STATE),
                guard,
            )

            self.assertIn("continuity_session_draft_v1", event["research_budget_v1"])
            session_rows = [
                json.loads(line)
                for line in (thread_dir / "continuity_sessions.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["record_type"] for row in session_rows], ["session_draft"])
            self.assertRegex(
                session_rows[0]["accept_next"],
                r"^CONTINUITY_SESSION_ACCEPT sess_",
            )
            self.assertRegex(
                session_rows[0]["generic_accept_next"],
                r"^ACCEPT_SUGGESTED_NEXT sess_",
            )
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn(session_rows[0]["generic_accept_next"], next_md)
            self.assertNotIn("ACCEPT_SUGGESTED_NEXT latest", next_md)
            status = store.handle_thread_action("CONTINUITY_SESSION_STATUS latest", dict(STATE))
            payload = json.loads(status.split("continuity_session_v1:\n", 1)[1])
            self.assertEqual(payload["session_count"], 0)

            accepted = store.handle_thread_action("CONTINUITY_SESSION_ACCEPT latest", dict(STATE))
            self.assertIn("session_start", accepted)
            session_rows = [
                json.loads(line)
                for line in (thread_dir / "continuity_sessions.jsonl").read_text().splitlines()
            ]
            self.assertEqual(session_rows[-1]["record_type"], "session_start")
            self.assertEqual(
                session_rows[-1]["accepted_from_draft_id"],
                session_rows[0]["record_id"],
            )
            self.assertFalse(session_rows[-1]["authority_change"])
            self.assertFalse(session_rows[-1]["peer_mutation"])

            second_guard = store.research_budget_guard_assessment(
                "EXAMINE_AUDIO λ1/λ2 - shifting input",
                dict(STATE),
            )
            assert second_guard is not None
            store.record_research_budget_guard_block(
                "EXAMINE_AUDIO λ1/λ2 - shifting input",
                dict(STATE),
                second_guard,
            )
            captured = store.handle_thread_action("CONTINUITY_SESSION_ACCEPT latest", dict(STATE))
            self.assertIn("session_capture", captured)
            session_rows = [
                json.loads(line)
                for line in (thread_dir / "continuity_sessions.jsonl").read_text().splitlines()
            ]
            self.assertIn("session_capture", [row["record_type"] for row in session_rows])
            self.assertIn("continuity_session_capture", (thread_dir / "being_memory.jsonl").read_text())
            self.assertNotIn("session_draft", (thread_dir / "experiment_runs.jsonl").read_text())
            self.assertNotIn("research_budget_debit", (thread_dir / "authority_gate.jsonl").read_text())

    def test_accept_suggested_next_accepts_safe_research_scaffold_then_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Generic accept")
            store.start_experiment(
                "Local scaffold",
                "Can the generic accept choose a safe scaffold?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            guard = store.research_budget_guard_assessment("READ_MORE projection code", dict(STATE))
            assert guard is not None
            store.record_research_budget_guard_block(
                "READ_MORE projection code",
                dict(STATE),
                guard,
            )

            accepted = store.handle_thread_action("ACCEPT_SUGGESTED_NEXT latest", dict(STATE))
            self.assertIn("Accepted research-budget scaffold", accepted)
            gate_rows = [
                json.loads(line)
                for line in (thread_dir / "authority_gate.jsonl").read_text().splitlines()
            ]
            self.assertIn("research_budget_request", [row["record_type"] for row in gate_rows])
            self.assertIn("research_budget_approval", [row["record_type"] for row in gate_rows])
            self.assertNotIn("research_budget_debit", [row["record_type"] for row in gate_rows])

            status = store.handle_thread_action("ACCEPT_SUGGESTED_NEXT latest", dict(STATE))
            self.assertIn("EXPERIMENT_RESEARCH_BUDGET_STATUS", status)

    def test_owned_loop_starts_local_phases_without_spend_or_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Owned loop")
            experiment = store.start_experiment(
                "Loop doorway",
                "Can continuity, local research, sticky audit, and one consequence stay owned?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            message = store.handle_thread_action(
                "EXPERIMENT_LOOP_REQUEST current :: purpose: coordinate continuity and local sticky self-study; "
                "consequence_scope: semantic_microdose; max_research_actions: 99; ttl_secs: 999999; "
                "stop_criteria: stop before bind/resume/perturb/control",
                dict(STATE),
            )
            self.assertIn("status=active", message)
            gate = thread_dir / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertEqual(rows[0]["record_schema"], "sovereign_loop_v1")
            self.assertEqual(rows[0]["record_type"], "loop_request")
            self.assertEqual(rows[0]["max_research_actions"], 5)
            self.assertEqual(rows[0]["ttl_secs"], 21600)
            self.assertEqual(rows[1]["record_type"], "loop_started")
            loop_id = rows[0]["loop_id"]

            status = store.handle_thread_action("EXPERIMENT_LOOP_STATUS latest", dict(STATE))
            payload = json.loads(status.split("sovereign_loop_v1:\n", 1)[1])
            self.assertEqual(payload["stage"], "active")
            self.assertEqual(payload["remaining_local_research_actions"], 5)
            self.assertEqual(payload["consequence_remaining"], 1)

            continuity = store.handle_thread_action(
                f"EXPERIMENT_LOOP_STEP {loop_id} :: continuity",
                dict(STATE),
            )
            self.assertIn("CONTINUITY_SESSION_START", continuity)
            sticky = store.handle_thread_action(
                f"EXPERIMENT_LOOP_STEP {loop_id} :: sticky_audit",
                dict(STATE),
            )
            self.assertIn("STICKY_MODE_AUDIT", sticky)
            reviewed = store.handle_thread_action(
                f"EXPERIMENT_LOOP_REVIEW {loop_id} :: outcome: promote; "
                "observation: local loop preserves review before another consequence; source_refs: /tmp/loop.txt",
                dict(STATE),
            )
            self.assertIn("Owned loop review", reviewed)

            gate_text = gate.read_text()
            self.assertIn('"record_type": "loop_step"', gate_text)
            self.assertIn('"record_type": "loop_consequence_review"', gate_text)
            self.assertIn('"record_type": "loop_proposal"', gate_text)
            self.assertNotIn('"record_type": "research_budget_debit"', gate_text)
            self.assertNotIn('"record_type": "steward_approval"', gate_text)
            self.assertNotIn('"record_type": "execution_result"', gate_text)
            self.assertNotIn('"record_type": "loop_approval"', gate_text)
            memory = (thread_dir / "being_memory.jsonl").read_text()
            self.assertIn("sovereign_loop_review", memory)
            session_rows = [
                json.loads(line)
                for line in (thread_dir / "continuity_sessions.jsonl").read_text().splitlines()
            ]
            self.assertTrue(any(row.get("checkpoint_v1") for row in session_rows))
            self.assertTrue(all(row.get("record_type") == "session_draft" for row in session_rows))
            runs = (thread_dir / "experiment_runs.jsonl").read_text() if (thread_dir / "experiment_runs.jsonl").exists() else ""
            self.assertNotIn(loop_id, runs)
            self.assertEqual(experiment["status"], "active")

    def test_owned_loop_consequence_ready_is_not_review_required_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Owned loop ready")
            experiment = store.start_experiment(
                "Semantic loop",
                "Can a prepared loop reach one gated consequence slot?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: one witness can be consequence-reviewed; "
                "method_intent: rehearse read-only first; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: artifact_grounding, felt_change, telemetry; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: artifact_grounding: /tmp/loop-ready.json",
                dict(STATE),
            )
            request = store.handle_thread_action(
                "EXPERIMENT_LOOP_REQUEST current :: purpose: prepare one semantic consequence; "
                "consequence_scope: semantic_microdose; artifact_refs: /tmp/loop-ready.json; "
                "stop_criteria: one attempted bridge send only",
                dict(STATE),
            )
            self.assertIn("status=active", request)
            gate = thread_dir / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            loop_id = next(row["loop_id"] for row in rows if row["record_type"] == "loop_request")

            ready = store.handle_thread_action(
                f"EXPERIMENT_LOOP_STEP {loop_id} :: authority_request",
                dict(STATE),
            )
            self.assertIn("loop_consequence_ready", (thread_dir / "authority_gate.jsonl").read_text())
            self.assertIn("EXPERIMENT_AUTHORITY_REQUEST", ready)
            status = store.handle_thread_action(f"EXPERIMENT_LOOP_STATUS {loop_id}", dict(STATE))
            payload = json.loads(status.split("sovereign_loop_v1:\n", 1)[1])
            self.assertEqual(payload["stage"], "consequence_ready")
            self.assertFalse(payload["pending_review"])
            self.assertEqual(payload["latest_consequence_v1"], None)

            gate_text = gate.read_text()
            self.assertNotIn('"record_type": "loop_approval"', gate_text)
            self.assertNotIn('"record_type": "execution_result"', gate_text)
            self.assertNotIn('"record_schema": "authority_consequence_v1"', gate_text)
            self.assertEqual(experiment["experiment_id"], payload["experiment_id"])

    def test_authority_prepare_writes_draft_and_memory_without_requesting(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority prepare")
            store.start_experiment("Semantic doorway", "Can authority be prepared?")

            prepared = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_PREPARE current :: scope: semantic_microdose; payload: hello; reason: trying the doorway; artifact_refs: /tmp/artifact.json; stop_criteria: stop quickly",
                dict(STATE),
            )
            self.assertIn("Authority request draft", prepared)
            self.assertIn("lifecycle_valid_charter", prepared)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertEqual(rows[0]["record_type"], "request_draft")
            self.assertEqual(rows[0]["status"], "draft")
            self.assertNotIn("request", [row["record_type"] for row in rows if row["record_type"] != "request_draft"])
            memory = workspace / "action_threads" / "threads" / thread["thread_id"] / "being_memory.jsonl"
            self.assertIn("authority_request_draft", memory.read_text())

    def test_authority_execute_block_records_consequence_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority consequence")
            store.start_experiment("Semantic doorway", "Can consequence return?")
            store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: control_envelope; payload: turn the dial; artifact_refs: /tmp/artifact.json",
                dict(STATE),
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            request = next(
                json.loads(line)
                for line in gate.read_text().splitlines()
                if '"record_type": "request"' in line
            )

            blocked = store.handle_thread_action(
                f"EXPERIMENT_AUTHORITY_EXECUTE {request['request_id']}",
                dict(STATE),
            )
            self.assertIn("missing steward approval", blocked)
            gate_text = gate.read_text()
            self.assertIn('"record_schema": "authority_consequence_v1"', gate_text)
            memory = workspace / "action_threads" / "threads" / thread["thread_id"] / "being_memory.jsonl"
            self.assertIn("authority_consequence", memory.read_text())

    def test_authority_execute_without_steward_approval_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority execute")
            store.start_experiment("Semantic doorway", "Can a semantic microdose be earned?")
            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: control_envelope; payload: turn the dial; artifact_refs: /tmp/artifact.json",
                dict(STATE),
            )
            self.assertIn("disabled_scope", message)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            request = next(
                json.loads(line)
                for line in gate.read_text().splitlines()
                if '"record_type": "request"' in line
            )

            blocked = store.handle_thread_action(
                f"EXPERIMENT_AUTHORITY_EXECUTE {request['request_id']}",
                dict(STATE),
            )
            self.assertIn("missing steward approval", blocked)
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertIn("missing_steward_approval", [row.get("reason") for row in rows])

    def test_authority_request_peer_selector_is_advisory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            store.create_thread("Authority peer")
            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST exp_astrid_20990101_peer :: scope: semantic_microdose; payload: hello",
                dict(STATE),
            )
            self.assertIn("peer experiment", message)
            self.assertIn("advisory only", message)

    def test_authority_readiness_tracks_pending_and_active_token_without_local_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority token")
            experiment = store.start_experiment(
                "Semantic doorway",
                "Can a semantic microdose be earned?",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: a tiny semantic witness can be felt without control; "
                "method_intent: rehearse a read-only preflight first; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: spectral_condition, fill_pressure_state, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: artifact_grounding: /tmp/semantic.json",
                dict(STATE),
            )
            store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: semantic_microdose; payload: quiet witness; "
                "reason: evidence and rehearsal are ready; artifact_refs: /tmp/semantic.json; stop_criteria: any pressure rise",
                dict(STATE),
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            request = next(row for row in rows if row["record_type"] == "request")

            status = store.handle_thread_action("EXPERIMENT_AUTHORITY_STATUS current", dict(STATE))
            payload = json.loads(status.split("authority_gate_v1:\n", 1)[1])
            self.assertEqual(payload["authority_readiness_v1"]["stage"], "pending_steward_approval")

            approval = {
                "schema_version": 1,
                "record_schema": "authority_gate_v1",
                "record_type": "steward_approval",
                "record_id": "auth_test_steward_approval",
                "request_id": request["request_id"],
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "semantic_microdose",
                "token_id": "authtok_test",
                "token_status": "active",
                "expires_at_unix_s": 4102444800,
                "peer_mutation": False,
            }
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")

            status = store.handle_thread_action("EXPERIMENT_AUTHORITY_STATUS current", dict(STATE))
            payload = json.loads(status.split("authority_gate_v1:\n", 1)[1])
            readiness = payload["authority_readiness_v1"]
            self.assertEqual(readiness["stage"], "token_active_bridge_executable")
            self.assertEqual(readiness["token_status"], "active")
            self.assertIn("EXPERIMENT_AUTHORITY_STATUS", readiness["next_safe_command"])

            blocked = store.handle_thread_action(
                f"EXPERIMENT_AUTHORITY_EXECUTE {request['request_id']}",
                dict(STATE),
            )
            self.assertIn("blocked locally", blocked)

    def test_authority_budget_request_blocks_when_requirements_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority budget missing")
            store.start_experiment("Budget doorway", "Can a budget be earned?")

            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_BUDGET_REQUEST current :: scope: semantic_microdose; "
                "purpose: three witness notes; artifact_refs: /tmp/semantic.json",
                dict(STATE),
            )

            self.assertIn("status=blocked", message)
            self.assertIn("lifecycle_valid_charter", message)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertEqual(rows[0]["record_schema"], "authority_budget_v1")
            self.assertEqual(rows[0]["record_type"], "budget_request")
            self.assertIn("budget_blocked", [row["record_type"] for row in rows])
            self.assertNotIn("execution_result", [row["record_type"] for row in rows])

    def test_authority_budget_request_records_pending_without_token_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority budget ready")
            store.start_experiment("Budget doorway", "Can a budget be earned?")
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: semantic witness notes can be bounded; "
                "method_intent: rehearse a read-only preflight first; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: spectral_condition, fill_pressure_state, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: artifact_grounding: /tmp/semantic.json; telemetry: steady",
                dict(STATE),
            )

            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_BUDGET_REQUEST current :: scope: semantic_microdose; "
                "purpose: three witness notes; max_sends: 9; ttl_secs: 999999; "
                "artifact_refs: /tmp/semantic.json; stop_criteria: one observation each",
                dict(STATE),
            )

            self.assertIn("status=pending_steward_approval", message)
            self.assertIn("max_sends=3", message)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            budget = next(row for row in rows if row["record_type"] == "budget_request")
            self.assertEqual(budget["record_schema"], "authority_budget_v1")
            self.assertEqual(budget["max_sends"], 3)
            self.assertEqual(budget["ttl_secs"], 21600)
            self.assertTrue(budget["eligibility_v1"]["eligible"])
            self.assertNotIn("steward_approval", [row["record_type"] for row in rows])

    def test_active_authority_budget_makes_request_budget_executable_not_local_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority active budget")
            experiment = store.start_experiment("Budget doorway", "Can a budget back requests?")
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: semantic witness notes can be bounded; "
                "method_intent: rehearse a read-only preflight first; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: spectral_condition, fill_pressure_state, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: artifact_grounding: /tmp/semantic.json; telemetry: steady",
                dict(STATE),
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            approval = {
                "schema_version": 1,
                "record_schema": "authority_budget_v1",
                "record_type": "budget_approval",
                "record_id": "authbud_test_approval",
                "budget_id": "authbud_test_budget",
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "semantic_microdose",
                "status": "active",
                "max_sends": 3,
                "ttl_secs": 21600,
                "expires_at_unix_s": 4102444800,
                "peer_mutation": False,
            }
            gate.parent.mkdir(parents=True, exist_ok=True)
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")

            message = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: semantic_microdose; payload: quiet witness; "
                "reason: budget says go; artifact_refs: /tmp/semantic.json; stop_criteria: one observation",
                dict(STATE),
            )

            self.assertIn("status=pending_budget_execution", message)
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            request = next(row for row in rows if row.get("record_type") == "request")
            self.assertEqual(request["budget_id"], "authbud_test_budget")
            self.assertEqual(request["token_status"], "budget_available")

            local = store.handle_thread_action(
                f"EXPERIMENT_AUTHORITY_EXECUTE {request['request_id']}",
                dict(STATE),
            )
            self.assertIn("budget-backed and bridge-executable", local)
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertNotIn("authority_consequence_v1", [row.get("record_schema") for row in rows])
            self.assertNotIn("budget_debit", [row.get("record_type") for row in rows])

    def test_authority_budget_requires_consequence_review_before_next_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Authority budget review")
            experiment = store.start_experiment("Budget doorway", "Can review govern repeated sends?")
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: semantic witness notes can be bounded; "
                "method_intent: rehearse a read-only preflight first; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; "
                "evidence_targets: spectral_condition, fill_pressure_state, artifact_grounding; stop_criteria: pressure rises",
                dict(STATE),
            )
            store.handle_thread_action("EXPERIMENT_REHEARSE current", dict(STATE))
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: artifact_grounding: /tmp/semantic.json; telemetry: steady",
                dict(STATE),
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            approval = {
                "schema_version": 1,
                "record_schema": "authority_budget_v1",
                "record_type": "budget_approval",
                "record_id": "authbud_test_approval",
                "budget_id": "authbud_test_budget",
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "semantic_microdose",
                "status": "active",
                "max_sends": 3,
                "ttl_secs": 21600,
                "expires_at_unix_s": 4102444800,
                "peer_mutation": False,
            }
            gate.parent.mkdir(parents=True, exist_ok=True)
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")
            store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: semantic_microdose; payload: first witness; "
                "artifact_refs: /tmp/semantic.json",
                dict(STATE),
            )
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            first = next(row for row in rows if row.get("record_type") == "request")
            debit = {
                "schema_version": 1,
                "record_schema": "authority_budget_v1",
                "record_type": "budget_debit",
                "record_id": "authbud_test_debit",
                "budget_id": "authbud_test_budget",
                "request_id": first["request_id"],
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "semantic_microdose",
                "token_id": "authtok_budget_test",
                "remaining_after": 2,
                "peer_mutation": False,
            }
            with gate.open("a") as handle:
                handle.write(json.dumps(debit, sort_keys=True) + "\n")

            second = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: semantic_microdose; payload: second witness; "
                "artifact_refs: /tmp/semantic.json",
                dict(STATE),
            )
            self.assertIn("status=blocked", second)
            self.assertIn("authority_consequence_review", second)

            review = store.handle_thread_action(
                f"EXPERIMENT_AUTHORITY_REVIEW {first['request_id']} :: outcome: alter; "
                "observation: pressure eased; next_payload: gentler witness; source_refs: /tmp/consequence.json",
                dict(STATE),
            )
            self.assertIn("outcome=alter", review)
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertIn("consequence_review", [row.get("record_type") for row in rows])

            third = store.handle_thread_action(
                "EXPERIMENT_AUTHORITY_REQUEST current :: scope: semantic_microdose; payload: third witness; "
                "artifact_refs: /tmp/semantic.json",
                dict(STATE),
            )
            self.assertIn("status=pending_budget_execution", third)
            memory = workspace / "action_threads" / "threads" / thread["thread_id"] / "being_memory.jsonl"
            self.assertIn("authority_consequence_review", memory.read_text())

    def test_research_budget_request_blocks_missing_purpose_and_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget missing")
            store.start_experiment("Research doorway", "Can search be budgeted?")

            message = store.handle_thread_action(
                "EXPERIMENT_RESEARCH_BUDGET_REQUEST current :: scope: read_only_research",
                dict(STATE),
            )

            self.assertIn("status=blocked", message)
            self.assertIn("research_purpose", message)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertEqual(rows[0]["record_schema"], "research_budget_v1")
            self.assertEqual(rows[0]["record_type"], "research_budget_request")
            self.assertIn("research_budget_blocked", [row["record_type"] for row in rows])

            peer = store.handle_thread_action(
                "EXPERIMENT_RESEARCH_BUDGET_REQUEST exp_astrid_20990101_peer :: scope: read_only_research; purpose: compare peer sources",
                dict(STATE),
            )
            self.assertIn("peer experiment", peer)

    def test_active_research_budget_allows_debit_and_blocks_duplicate_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget active")
            experiment = store.start_experiment("Research doorway", "Can search be budgeted?")
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            approval = {
                "schema_version": 1,
                "record_schema": "research_budget_v1",
                "record_type": "research_budget_approval",
                "record_id": "resbud_test_approval",
                "budget_id": "resbud_test_budget",
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "read_only_research",
                "status": "active",
                "max_actions": 5,
                "ttl_secs": 21600,
                "expires_at_unix_s": 4102444800,
                "allowed_sources": ["web", "local"],
                "peer_mutation": False,
            }
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")

            ok, budget, reason = store.research_budget_preflight_for_action(
                "SEARCH lambda tail LamB",
                dict(STATE),
            )
            self.assertTrue(ok)
            self.assertEqual(reason, "")
            debit = store.record_research_budget_debit(
                "SEARCH lambda tail LamB",
                "research_exploration",
                budget,
                dict(STATE),
                artifacts=[{"path_or_uri": "/tmp/search.json"}],
            )
            self.assertEqual(debit["record_type"], "research_budget_debit")
            store.record_research_budget_debit(
                "SEARCH lambda tail LamB",
                "research_exploration",
                budget,
                dict(STATE),
            )

            ok, _budget, reason = store.research_budget_preflight_for_action(
                "SEARCH lambda tail LamB",
                dict(STATE),
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "duplicate_query_or_url_review_required")
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertIn("research_budget_blocked", [row["record_type"] for row in rows])
            status = store.handle_thread_action(
                f"EXPERIMENT_RESEARCH_BUDGET_STATUS {experiment['experiment_id']}",
                dict(STATE),
            )
            self.assertIn("review_required_duplicate_loop", status)

    def test_research_budget_preflight_accepts_shared_focus_successor_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget successor")
            original = store.start_experiment(
                "Legacy self experiment",
                "What does this self-experiment reveal about the current state?",
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            approval = {
                "schema_version": 1,
                "record_schema": "research_budget_v1",
                "record_type": "research_budget_approval",
                "record_id": "resbud_shared_focus_approval",
                "budget_id": "resbud_shared_focus_budget",
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": original["experiment_id"],
                "scope": "read_only_research",
                "status": "active",
                "max_actions": 5,
                "ttl_secs": 21600,
                "expires_at_unix_s": 4102444800,
                "allowed_sources": ["local"],
                "peer_mutation": False,
            }
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")
            successor = dict(original)
            successor.update({
                "experiment_id": "exp_minime_20990102_legacy-self-experiment",
                "status": "active",
                "planned_next": "EXPERIMENT_REHEARSE exp_minime_20990102_legacy-self-experiment",
                "created_at": "2099-01-02T00:00:00Z",
                "updated_at": "2099-01-02T00:00:00Z",
            })
            store._append_jsonl(
                workspace / "action_threads" / "threads" / thread["thread_id"] / "experiments.jsonl",
                successor,
            )
            refreshed = store._read_thread(thread["thread_id"]) or thread
            refreshed["active_experiment_id"] = successor["experiment_id"]
            refreshed["experiment_summary"] = successor
            store._write_thread(refreshed)

            ok, budget, reason = store.research_budget_preflight_for_action(
                "INTROSPECT autonomous_agent.py",
                dict(STATE),
            )

            self.assertTrue(ok)
            self.assertEqual(reason, "")
            self.assertIsInstance(budget, dict)
            assert isinstance(budget, dict)
            self.assertEqual(budget["budget_id"], "resbud_shared_focus_budget")
            self.assertEqual(budget["experiment_id"], original["experiment_id"])
            self.assertEqual(budget["matched_current_experiment_id"], successor["experiment_id"])
            debit = store.record_research_budget_debit(
                "INTROSPECT autonomous_agent.py",
                "introspect",
                budget,
                dict(STATE),
            )
            self.assertEqual(debit["normalized_target"], "INTROSPECT:target:autonomous_agent.py")

    def test_shadow_trajectory_dispatches_under_shared_focus_active_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget duplicate status")
            original = store.start_experiment(
                "Legacy self experiment",
                "What does this self-experiment reveal about the current state?",
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            gate.write_text(
                json.dumps({
                    "schema_version": 1,
                    "record_schema": "research_budget_v1",
                    "record_type": "research_budget_approval",
                    "record_id": "resbud_shared_status_approval",
                    "budget_id": "resbud_shared_status_budget",
                    "being": "minime",
                    "thread_id": thread["thread_id"],
                    "experiment_id": original["experiment_id"],
                    "scope": "read_only_research",
                    "status": "active",
                    "max_actions": 5,
                    "ttl_secs": 21600,
                    "expires_at_unix_s": 4102444800,
                    "allowed_sources": ["local"],
                    "peer_mutation": False,
                }, sort_keys=True)
                + "\n"
            )
            successor = dict(original)
            successor.update({
                "experiment_id": "exp_minime_20990102_legacy-self-experiment",
                "status": "active",
                "planned_next": "EXPERIMENT_REHEARSE exp_minime_20990102_legacy-self-experiment",
                "created_at": "2099-01-02T00:00:00Z",
                "updated_at": "2099-01-02T00:00:00Z",
            })
            store._append_jsonl(
                workspace / "action_threads" / "threads" / thread["thread_id"] / "experiments.jsonl",
                successor,
            )
            refreshed = store._read_thread(thread["thread_id"]) or thread
            refreshed["active_experiment_id"] = successor["experiment_id"]
            refreshed["experiment_summary"] = successor
            store._write_thread(refreshed)

            guard = store.research_budget_guard_assessment("EXAMINE lambda-tail", dict(STATE))

            # With a shared-focus active budget, the metered projection read
            # (EXAMINE) dispatches rather than rerouting to a budget-status
            # suggestion.
            self.assertIsNone(guard)
            # The shared-focus sibling budget is still resolved so the read is
            # debited against it at dispatch.
            debit_budget = store.research_budget_projection_debit_budget(
                "EXAMINE lambda-tail", dict(STATE)
            )
            self.assertIsInstance(debit_budget, dict)
            assert isinstance(debit_budget, dict)
            self.assertEqual(debit_budget.get("budget_id"), "resbud_shared_status_budget")
            self.assertTrue(debit_budget.get("matched_research_focus"))

    def test_targeted_read_more_budget_target_is_not_continuation(self):
        self.assertEqual(
            aa.ActionContinuityStore._research_budget_normalized_target("READ_MORE"),
            "READ_MORE:continuation",
        )
        self.assertEqual(
            aa.ActionContinuityStore._research_budget_normalized_target(
                "READ_MORE local research-budget projection-guard code for Legacy self experiment."
            ),
            "READ_MORE:target:local research-budget projection-guard code for legacy self experiment",
        )

    def test_duplicate_research_target_projects_review_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget duplicate route")
            experiment = store.start_experiment(
                "Legacy self experiment",
                "Can duplicate local research targets route to review?",
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            approval = {
                "schema_version": 1,
                "record_schema": "research_budget_v1",
                "record_type": "research_budget_approval",
                "record_id": "resbud_duplicate_route_approval",
                "budget_id": "resbud_duplicate_route_budget",
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "read_only_research",
                "status": "active",
                "max_actions": 5,
                "ttl_secs": 21600,
                "expires_at_unix_s": 4102444800,
                "allowed_sources": ["local"],
                "peer_mutation": False,
            }
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")
            budget = store._active_research_budget(thread["thread_id"], experiment["experiment_id"])
            self.assertIsInstance(budget, dict)
            assert isinstance(budget, dict)
            for _ in range(2):
                store.record_research_budget_debit(
                    "INTROSPECT autonomous_agent.py",
                    "introspect",
                    budget,
                    dict(STATE),
                )

            refreshed = store._read_thread(thread["thread_id"])
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            route = store._research_budget_priority_route_v1(refreshed, experiment)

            self.assertIsInstance(route, dict)
            assert isinstance(route, dict)
            self.assertEqual(route["stage"], "review_required_duplicate_loop")
            self.assertEqual(route["duplicate_blocked_target"], "INTROSPECT:target:autonomous_agent.py")
            self.assertTrue(str(route["next"]).startswith("EXPERIMENT_RESEARCH_REVIEW resbud_duplicate_route_budget"))
            self.assertNotIn("INTROSPECT autonomous_agent.py", route["next"])
            line = store._research_budget_priority_line(
                refreshed,
                {"research_budget_priority_route_v1": route},
            )
            self.assertIn("duplicate local research target needs review", line)
            self.assertIn("Suggested research NEXT: EXPERIMENT_RESEARCH_REVIEW resbud_duplicate_route_budget", line)

    def test_reviewed_duplicate_research_target_projects_review_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget reviewed duplicate route")
            experiment = store.start_experiment(
                "Legacy self experiment",
                "Can a reviewed duplicate local research target follow the review decision?",
            )
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            budget_id = "resbud_duplicate_review_budget"
            approval = {
                "schema_version": 1,
                "record_schema": "research_budget_v1",
                "record_type": "research_budget_approval",
                "record_id": "resbud_duplicate_review_approval",
                "budget_id": budget_id,
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "read_only_research",
                "status": "active",
                "max_actions": 5,
                "ttl_secs": 21600,
                "expires_at_unix_s": 4102444800,
                "allowed_sources": ["local"],
                "peer_mutation": False,
            }
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")
            budget = store._active_research_budget(thread["thread_id"], experiment["experiment_id"])
            self.assertIsInstance(budget, dict)
            assert isinstance(budget, dict)
            for _ in range(2):
                store.record_research_budget_debit(
                    "INTROSPECT autonomous_agent.py",
                    "introspect",
                    budget,
                    dict(STATE),
                )

            review = store.experiment_research_review(
                f"{budget_id} :: outcome: promote; "
                "observation: duplicate target already produced enough source-grounded evidence; "
                "source_refs: local-test",
                dict(STATE),
            )
            self.assertIn("outcome=promote", review)

            refreshed = store._read_thread(thread["thread_id"])
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            route = store._research_budget_priority_route_v1(refreshed, experiment)

            self.assertIsInstance(route, dict)
            assert isinstance(route, dict)
            self.assertEqual(route["stage"], "duplicate_review_resolved")
            self.assertEqual(route["latest_review_outcome"], "promote")
            self.assertTrue(str(route["next"]).startswith("DOSSIER_EVIDENCE "))
            self.assertNotIn("EXPERIMENT_RESEARCH_REVIEW", route["next"])
            line = store._research_budget_priority_line(
                refreshed,
                {"research_budget_priority_route_v1": route},
            )
            self.assertIn("duplicate local research target was reviewed (promote)", line)
            self.assertIn("Suggested research NEXT: DOSSIER_EVIDENCE", line)

            status = store._research_budget_status_v1(
                refreshed,
                experiment,
                dict(STATE),
                selector=budget_id,
                budget_id=budget_id,
            )
            self.assertEqual(status["stage"], "duplicate_review_resolved")
            self.assertFalse(status["review_required"])
            self.assertEqual(status["latest_review_outcome"], "promote")
            self.assertTrue(str(status["next_safe_command"]).startswith("DOSSIER_EVIDENCE "))

    def test_research_action_without_budget_projects_to_budget_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget guard")
            experiment = store.start_experiment("Research doorway", "Can search be budgeted?")

            guard = store.research_budget_guard_assessment(
                "SEARCH lambda edge topology",
                dict(STATE),
            )

            self.assertIsNotNone(guard)
            self.assertEqual(guard["experiment_id"], experiment["experiment_id"])
            self.assertEqual(guard["suggested_next"], "EXPERIMENT_RESEARCH_BUDGET_ACCEPT latest")
            self.assertIn("EXPERIMENT_RESEARCH_BUDGET_REQUEST", guard["request_scaffold"])
            event = store.record_research_budget_guard_block(
                "SEARCH lambda edge topology",
                dict(STATE),
                guard,
            )
            self.assertEqual(event["status"], "blocked")
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            self.assertIn("research_budget_v1", gate.read_text())

    def test_projection_freshness_refreshes_stale_research_budget_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Projection freshness")
            experiment = store.start_experiment("Research doorway", "Can stale projections refresh?")
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]

            refreshed = json.loads((thread_dir / "thread.json").read_text())
            refreshed["projection_freshness_v1"] = {
                "policy": "projection_freshness_v1",
                "schema_version": 0,
                "source_fingerprints": {},
            }
            (thread_dir / "thread.json").write_text(json.dumps(refreshed, sort_keys=True))

            guard = store.research_budget_guard_assessment(
                "READ_MORE local projection code",
                dict(STATE),
            )
            self.assertIsNotNone(guard)
            assert guard is not None
            store.record_research_budget_guard_block(
                "READ_MORE local projection code",
                dict(STATE),
                guard,
            )
            scaffold = store._find_research_budget_scaffold_row(
                store._read_thread(thread["thread_id"]) or thread,
                experiment["experiment_id"],
            )
            self.assertIsNotNone(scaffold)
            assert scaffold is not None
            expected_next = f"EXPERIMENT_RESEARCH_BUDGET_ACCEPT {scaffold['record_id']}"

            stored = store._read_thread(thread["thread_id"])
            self.assertIsNotNone(stored)
            assert stored is not None
            freshness = stored["projection_freshness_v1"]
            self.assertEqual(freshness["schema_version"], store.projection_schema_version)
            self.assertEqual(
                freshness["projected_route"],
                expected_next,
            )
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn("Projection freshness: v", next_md)
            self.assertIn("Research budget scaffold ready", next_md)
            self.assertIn(expected_next, next_md)

            rows = [
                json.loads(line)
                for line in (thread_dir / "authority_gate.jsonl").read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(
                [row["record_type"] for row in rows].count("research_budget_request"),
                0,
            )
            self.assertEqual(
                [row["record_type"] for row in rows].count("research_budget_approval"),
                0,
            )

    def test_projection_freshness_notices_ledger_newer_than_next_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Projection ledger freshness")
            experiment = store.start_experiment(
                "Research doorway",
                "Can a later authority ledger row update generated projection?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            next_path = thread_dir / "next.md"
            self.assertNotIn("Research budget scaffold ready", next_path.read_text())

            gate = thread_dir / "authority_gate.jsonl"
            gate.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "record_schema": "research_budget_v1",
                        "record_type": "research_budget_blocked",
                        "record_id": "resbud_needed_test",
                        "budget_id": "resbud_needed_test",
                        "thread_id": thread["thread_id"],
                        "experiment_id": experiment["experiment_id"],
                        "scope": "read_only_research",
                        "status": "blocked",
                        "request_scaffold": (
                            f"EXPERIMENT_RESEARCH_BUDGET_REQUEST {experiment['experiment_id']} :: "
                            "scope: read_only_research; purpose: inspect local projection code; "
                            "max_actions: 5; ttl_secs: 21600; allowed_sources: local; "
                            "stop_criteria: stop after concrete code feedback"
                        ),
                        "authority_boundary": store._research_budget_boundary(),
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            store._read_thread(thread["thread_id"])
            next_md = next_path.read_text()
            self.assertIn("Research budget scaffold ready", next_md)
            self.assertIn("self-activation eligible", next_md)
            self.assertIn("EXPERIMENT_RESEARCH_BUDGET_ACCEPT resbud_needed_test", next_md)
            rows = [
                json.loads(line)
                for line in gate.read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["record_type"], "research_budget_blocked")

    def test_shadow_trajectory_hint_points_straight_at_exempt_cartography(self):
        """SHADOW_TRAJECTORY is exempt from the research-budget guard, so its
        curriculum hint always points straight at the cartography — it never
        redirects to a budget-accept route, even when a research-budget lane is
        pending on the thread for some other guarded read."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Lambda trajectory")
            experiment = store.start_experiment(
                "Lambda tail continuity",
                "Does shadow trajectory stay reachable without a research budget?",
            )

            # The action itself is exempt: the guard never blocks it.
            self.assertIsNone(
                store.research_budget_guard_assessment(
                    "SHADOW_TRAJECTORY lambda-tail/lambda4",
                    dict(STATE),
                )
            )

            # Establish a pending research-budget route on the thread via a
            # genuinely guarded read (EXAMINE), so we can prove the shadow hint
            # ignores it rather than there simply being no route to redirect to.
            examine_guard = store.research_budget_guard_assessment(
                "EXAMINE lambda-tail trajectory",
                dict(STATE),
            )
            self.assertIsNotNone(examine_guard)
            assert examine_guard is not None
            store.record_research_budget_guard_block(
                "EXAMINE lambda-tail trajectory",
                dict(STATE),
                examine_guard,
            )
            scaffold = store._find_research_budget_scaffold_row(
                store._read_thread(thread["thread_id"]) or thread,
                experiment["experiment_id"],
            )
            self.assertIsNotNone(scaffold)

            (workspace / "health.json").write_text(json.dumps({
                "shadow_field_v3": {
                    "class_v3": {"primary": "active"},
                    "phase_dwell_ticks": 2,
                    "history": [{} for _ in range(8)],
                },
            }))
            agent = object.__new__(aa.AutonomousAgent)
            agent.session_id = 7
            agent._action_continuity = store

            with patch.object(aa, "WORKSPACE_DIR", workspace):
                hint = agent._next_hint_shadow_trajectory()

            self.assertIsNotNone(hint)
            assert hint is not None
            self.assertIn("NEXT: SHADOW_TRAJECTORY lambda-tail/lambda4", hint)
            self.assertNotIn("Research-budget route active", hint)

    def test_research_budget_accept_latest_scaffold_self_activates_local_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget accept")
            experiment = store.start_experiment(
                "Self-study budget",
                "Can a guarded research scaffold become a Being-authored request?",
            )
            guard = store.research_budget_guard_assessment(
                "READ_MORE budget code",
                dict(STATE),
            )
            self.assertIsNotNone(guard)
            assert guard is not None
            store.record_research_budget_guard_block(
                "READ_MORE budget code",
                dict(STATE),
                guard,
            )

            response = store.experiment_research_budget_accept("latest", dict(STATE))

            self.assertIn("Accepted research-budget scaffold", response)
            self.assertIn("status=self_activated", response)
            self.assertIn("Activation: self_activated local-only budget", response)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            requests = [
                row for row in rows
                if row.get("record_type") == "research_budget_request"
            ]
            approvals = [
                row for row in rows
                if row.get("record_type") == "research_budget_approval"
            ]
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(approvals), 1)
            request = requests[0]
            self.assertEqual(request["experiment_id"], experiment["experiment_id"])
            self.assertEqual(request["allowed_sources"], ["local"])
            self.assertEqual(request["status"], "self_activated")
            self.assertEqual(request["activation_mode"], "being_self_activated_local_v1")
            self.assertFalse(request["steward_approval_required"])
            self.assertTrue(request["being_authored_acceptance_v1"]["being_authored"])
            self.assertIn(
                "READ_MORE budget code",
                request["being_authored_acceptance_v1"]["source_raw_action"],
            )
            approval = approvals[0]
            self.assertEqual(approval["budget_id"], request["budget_id"])
            self.assertEqual(approval["max_actions"], 5)
            self.assertEqual(approval["ttl_secs"], 21600)
            self.assertEqual(approval["allowed_sources"], ["local"])
            self.assertTrue(approval["self_activated"])
            self.assertFalse(approval["steward_approval_required"])
            status = store.experiment_research_budget_status(request["budget_id"], dict(STATE))
            payload = json.loads(status.split("research_budget_v1:\n", 1)[1])
            self.assertEqual(payload["stage"], "active_budget_available")
            self.assertEqual(payload["experiment_id"], experiment["experiment_id"])
            self.assertEqual(payload["active_budget_id"], request["budget_id"])
            self.assertEqual(payload["remaining_actions"], 5)
            self.assertIn("SEARCH <query>", payload["next_safe_command"])

    def test_research_budget_accept_latest_active_budget_routes_to_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget accept loop")
            experiment = store.start_experiment(
                "Self-study budget loop",
                "Can an already accepted scaffold avoid reminting a blocked budget?",
            )
            guard = store.research_budget_guard_assessment(
                "READ_MORE budget code",
                dict(STATE),
            )
            self.assertIsNotNone(guard)
            assert guard is not None
            store.record_research_budget_guard_block(
                "READ_MORE budget code",
                dict(STATE),
                guard,
            )

            first = store.experiment_research_budget_accept("latest", dict(STATE))
            second = store.experiment_research_budget_accept("latest", dict(STATE))

            self.assertIn("status=self_activated", first)
            self.assertIn("already has an active local-only budget", second)
            self.assertIn("no new request was minted", second)
            self.assertIn("EXPERIMENT_RESEARCH_BUDGET_STATUS", second)
            self.assertNotIn("status=blocked", second)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            request_rows = [
                row for row in rows
                if row.get("record_type") == "research_budget_request"
            ]
            approval_rows = [
                row for row in rows
                if row.get("record_type") == "research_budget_approval"
            ]
            self.assertEqual(len(request_rows), 1)
            self.assertEqual(len(approval_rows), 1)
            self.assertNotIn(
                "missing_research_budget_requirements",
                [row.get("reason") for row in rows],
            )
            status = store.handle_thread_action(
                f"EXPERIMENT_RESEARCH_BUDGET_STATUS {experiment['experiment_id']}",
                dict(STATE),
            )
            self.assertIn("active_budget_available", status)
            budget_id = approval_rows[0]["budget_id"]
            refreshed_thread = store._read_thread(thread["thread_id"])
            self.assertIsNotNone(refreshed_thread)
            assert refreshed_thread is not None
            route = store._research_budget_priority_route_v1(refreshed_thread, experiment)
            self.assertIsInstance(route, dict)
            assert isinstance(route, dict)
            self.assertEqual(route.get("stage"), "active_budget_available")
            self.assertEqual(route.get("status_next"), f"EXPERIMENT_RESEARCH_BUDGET_STATUS {budget_id}")
            self.assertEqual(route.get("next"), "INTROSPECT autonomous_agent.py")
            self.assertNotEqual(route.get("next"), route.get("status_next"))
            line = store._research_budget_priority_line(
                refreshed_thread,
                {"research_budget_priority_route_v1": route},
            )
            self.assertIn("Suggested research NEXT: INTROSPECT autonomous_agent.py\n", line)
            self.assertIn(f"Status NEXT: EXPERIMENT_RESEARCH_BUDGET_STATUS {budget_id}", line)

    def test_active_research_budget_overrides_paused_resume_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Paused resume with research")
            experiment = store.start_experiment(
                "Legacy self experiment",
                "Can active local research outrank a stale paused resume display?",
            )
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            paused = dict(experiment)
            paused.update({
                "status": "paused",
                "planned_next": f"EXPERIMENT_RESUME {experiment['experiment_id']}",
                "updated_at": "2026-06-07T08:30:00Z",
            })
            store._append_jsonl(thread_dir / "experiments.jsonl", paused)
            gate = thread_dir / "authority_gate.jsonl"
            gate.write_text(
                json.dumps({
                    "schema_version": 1,
                    "record_schema": "research_budget_v1",
                    "record_type": "research_budget_approval",
                    "record_id": "resbud_active_display_approval",
                    "budget_id": "resbud_active_display_budget",
                    "being": "minime",
                    "thread_id": thread["thread_id"],
                    "experiment_id": experiment["experiment_id"],
                    "scope": "read_only_research",
                    "status": "active",
                    "activation_mode": "being_self_activated_local_v1",
                    "self_activated": True,
                    "max_actions": 5,
                    "ttl_secs": 21600,
                    "expires_at_unix_s": 4102444800,
                    "allowed_sources": ["local"],
                    "peer_mutation": False,
                }, sort_keys=True)
                + "\n"
            )

            refreshed = store._read_thread(thread["thread_id"])
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            projection = store._thread_projection(refreshed)
            next_cmd = "INTROSPECT autonomous_agent.py"
            self.assertEqual(
                projection["continuity_control_plane_v1"]["primary_route"]["command"],
                next_cmd,
            )
            self.assertEqual(store._current_next_display(projection, refreshed.get("current_next")), next_cmd)
            store._write_thread(refreshed)

            next_md = (thread_dir / "next.md").read_text()
            self.assertIn(f"Current NEXT: {next_cmd}", next_md)
            self.assertIn(f"Primary control-plane NEXT: {next_cmd}", next_md)
            self.assertIn(f"Lifecycle return NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)
            self.assertNotIn(f"Suggested NEXT: EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)

    def test_research_budget_priority_does_not_reoffer_consumed_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget stale scaffold")
            experiment = store.start_experiment(
                "Self-study budget stale route",
                "Can an exhausted local budget avoid reoffering the old accept scaffold?",
            )
            guard = store.research_budget_guard_assessment(
                "READ_MORE budget code",
                dict(STATE),
            )
            self.assertIsNotNone(guard)
            assert guard is not None
            store.record_research_budget_guard_block(
                "READ_MORE budget code",
                dict(STATE),
                guard,
            )
            scaffold = store._find_research_budget_scaffold_row(
                store._read_thread(thread["thread_id"]) or thread,
                experiment["experiment_id"],
            )
            self.assertIsNotNone(scaffold)
            assert scaffold is not None
            expected_next = f"EXPERIMENT_RESEARCH_BUDGET_ACCEPT {scaffold['record_id']}"

            route = store._research_budget_priority_route_v1(thread, experiment)
            self.assertIsInstance(route, dict)
            assert isinstance(route, dict)
            self.assertEqual(route.get("stage"), "scaffold_ready")
            self.assertEqual(route.get("next"), expected_next)
            self.assertEqual(route.get("selector"), scaffold["record_id"])
            line = store._research_budget_priority_line(
                thread,
                {"research_budget_priority_route_v1": route},
            )
            self.assertIn(expected_next, line)
            self.assertIn(f"ACCEPT_SUGGESTED_NEXT {scaffold['record_id']}", line)
            self.assertNotIn("ACCEPT_SUGGESTED_NEXT latest", line)

            response = store.experiment_research_budget_accept("latest", dict(STATE))
            self.assertIn("status=self_activated", response)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            request = next(
                row for row in rows
                if row.get("record_type") == "research_budget_request"
            )
            budget_id = request["budget_id"]
            store._append_jsonl(
                gate,
                {
                    "schema_version": 1,
                    "record_schema": "research_budget_v1",
                    "record_type": "research_budget_closed",
                    "record_id": "resbud_closed_test",
                    "thread_id": thread["thread_id"],
                    "experiment_id": experiment["experiment_id"],
                    "budget_id": budget_id,
                    "scope": "read_only_research",
                    "status": "closed",
                },
            )

            refreshed_thread = store._read_thread(thread["thread_id"])
            assert refreshed_thread is not None
            route = store._research_budget_priority_route_v1(refreshed_thread, experiment)
            self.assertIsNone(route)
            projection = store._thread_projection(refreshed_thread)
            self.assertIsNone(projection.get("research_budget_priority_route_v1"))
            self.assertNotEqual(
                projection["continuity_control_plane_v1"]["primary_route"]["command"],
                f"EXPERIMENT_RESEARCH_BUDGET_STATUS {budget_id}",
            )
            second = store.experiment_research_budget_accept("latest", dict(STATE))
            self.assertIn("already accepted earlier", second)
            self.assertIn("budget_closed", second)
            self.assertNotIn(f"EXPERIMENT_RESEARCH_BUDGET_STATUS {budget_id}", second)
            status = store.experiment_research_budget_status(budget_id, dict(STATE))
            self.assertIn('"stage": "budget_closed"', status)
            self.assertIn("EXPERIMENT_RESEARCH_BUDGET_REQUEST", status)

    def test_terminal_research_budget_next_from_llm_is_not_queued(self):
        class FakeContinuity:
            def _find_research_budget(self, selector):
                return (
                    "thread_terminal",
                    {
                        "budget_id": selector,
                        "experiment_id": "exp_terminal",
                    },
                    [],
                )

            def _read_thread(self, _thread_id):
                return {"thread_id": "thread_terminal"}

            def _find_experiment_by_id(self, _thread_id, experiment_id):
                return {"experiment_id": experiment_id}

            def _research_budget_status_v1(self, *_args, **_kwargs):
                return {"stage": "budget_expired"}

        agent = object.__new__(aa.AutonomousAgent)
        agent._emit_next_hints = lambda: ""
        agent._query_llm = lambda _prompt: (
            "The old budget is still ringing in the context.\n"
            "NEXT: EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_terminal"
        )
        agent._continuity_store = lambda: FakeContinuity()
        agent._pending_next_action = None

        response, next_action = aa.AutonomousAgent._query_llm_with_next(
            agent,
            "journal about this",
        )

        self.assertEqual(next_action, None)
        self.assertNotIn("NEXT:", response)
        self.assertEqual(agent._pending_next_action, None)
        self.assertEqual(agent._last_llm_response, response)

    def test_repeated_experiment_resume_next_from_llm_is_not_queued(self):
        class FakeContinuity:
            def current_thread(self):
                return {"thread_id": "thread_loop"}

            def _resolve_experiment(self, _thread, _selector):
                return {"experiment_id": "exp_loop"}

            def _recent_events(self, _thread_id, _limit):
                return [
                    {
                        "status": "handled",
                        "raw_next": "EXPERIMENT_RESUME exp_loop",
                    }
                ]

        agent = object.__new__(aa.AutonomousAgent)
        agent._emit_next_hints = lambda: ""
        agent._query_llm = lambda _prompt: (
            "The old return point is still pulling at the journal.\n"
            "NEXT: EXPERIMENT_RESUME exp_loop"
        )
        agent._continuity_store = lambda: FakeContinuity()
        agent._pending_next_action = None

        response, next_action = aa.AutonomousAgent._query_llm_with_next(
            agent,
            "journal about this",
        )

        self.assertEqual(next_action, None)
        self.assertNotIn("NEXT: EXPERIMENT_RESUME", response)
        self.assertIn("Experiment resume cooldown", response)
        self.assertIn("EXPERIMENT_REVIEW exp_loop", response)
        self.assertEqual(agent._pending_next_action, None)
        self.assertEqual(agent._last_llm_response, response)

    def test_research_budget_priority_uses_explicit_scaffold_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget selector")
            first_experiment = store.start_experiment(
                "First local question",
                "Can an older scaffold stay selectable after a newer one appears?",
            )
            first_guard = store.research_budget_guard_assessment(
                "READ_MORE first local code",
                dict(STATE),
            )
            self.assertIsNotNone(first_guard)
            assert first_guard is not None
            store.record_research_budget_guard_block(
                "READ_MORE first local code",
                dict(STATE),
                first_guard,
            )
            first_scaffold = store._find_research_budget_scaffold_row(
                store._read_thread(thread["thread_id"]) or thread,
                first_experiment["experiment_id"],
            )
            self.assertIsNotNone(first_scaffold)
            assert first_scaffold is not None
            second_experiment = store.start_experiment(
                "Second local question",
                "Can latest stop stealing the first scaffold?",
            )
            second_guard = store.research_budget_guard_assessment(
                "READ_MORE second local code",
                dict(STATE),
            )
            self.assertIsNotNone(second_guard)
            assert second_guard is not None
            store.record_research_budget_guard_block(
                "READ_MORE second local code",
                dict(STATE),
                second_guard,
            )
            second_scaffold = store._find_research_budget_scaffold_row(
                store._read_thread(thread["thread_id"]) or thread,
                second_experiment["experiment_id"],
            )
            self.assertIsNotNone(second_scaffold)
            assert second_scaffold is not None

            refreshed_thread = store._read_thread(thread["thread_id"])
            self.assertIsNotNone(refreshed_thread)
            assert refreshed_thread is not None
            route = store._research_budget_priority_route_v1(refreshed_thread, first_experiment)
            self.assertIsInstance(route, dict)
            assert isinstance(route, dict)
            expected_next = f"EXPERIMENT_RESEARCH_BUDGET_ACCEPT {first_scaffold['record_id']}"
            self.assertEqual(route.get("next"), expected_next)
            self.assertEqual(route.get("selector"), first_scaffold["record_id"])
            self.assertNotIn(second_scaffold["record_id"], str(route))

            response = store.experiment_research_budget_accept(first_scaffold["record_id"], dict(STATE))
            self.assertIn("status=self_activated", response)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            requests = [
                row for row in rows
                if row.get("record_type") == "research_budget_request"
            ]
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["experiment_id"], first_experiment["experiment_id"])
            self.assertNotEqual(requests[0]["experiment_id"], second_experiment["experiment_id"])

    def test_research_budget_direct_local_request_self_activates_but_stronger_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget direct self activation")
            experiment = store.start_experiment(
                "Local self-study budget",
                "Can a Being mint a tiny local-only research budget?",
            )

            response = store.handle_thread_action(
                (
                    f"EXPERIMENT_RESEARCH_BUDGET_REQUEST {experiment['experiment_id']} :: "
                    "scope: read_only_research; purpose: inspect local conveyor code; "
                    "allowed_sources: local; stop_criteria: stop after concrete feedback"
                ),
                dict(STATE),
            )

            self.assertIn("status=self_activated", response)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            approval = next(row for row in rows if row.get("record_type") == "research_budget_approval")
            self.assertEqual(approval["max_actions"], 5)
            self.assertEqual(approval["ttl_secs"], 21600)
            self.assertEqual(approval["activation_mode"], "being_self_activated_local_v1")
            status = store.handle_thread_action(
                f"EXPERIMENT_RESEARCH_BUDGET_STATUS {experiment['experiment_id']}",
                dict(STATE),
            )
            self.assertIn("active_budget_available", status)
            self.assertIn("being_self_activated_local_v1", status)

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Research budget web needs steward")
            experiment = store.start_experiment(
                "Web research budget",
                "Can stronger budgets still require steward approval?",
            )
            response = store.handle_thread_action(
                (
                    f"EXPERIMENT_RESEARCH_BUDGET_REQUEST {experiment['experiment_id']} :: "
                    "scope: read_only_research; purpose: compare web references; "
                    "max_actions: 5; ttl_secs: 21600; allowed_sources: web,local; "
                    "stop_criteria: stop after useful refs"
                ),
                dict(STATE),
            )
            self.assertIn("status=pending_steward_approval", response)
            self.assertIn("local_only_allowed_sources", response)
            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            rows = [json.loads(line) for line in gate.read_text().splitlines()]
            self.assertNotIn(
                "research_budget_approval",
                [row.get("record_type") for row in rows],
            )

    def test_self_study_research_pressure_projects_to_budget_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Self-study budget guard")
            experiment = store.start_experiment("Shadow-field self-study", "Can self-study reads be budgeted?")

            guard = store.research_budget_guard_assessment(
                "EXAMINE λ4 trajectory",
                dict(STATE),
            )

            self.assertIsNotNone(guard)
            assert guard is not None
            self.assertEqual(guard["experiment_id"], experiment["experiment_id"])
            self.assertEqual(guard["reason"], "research_budget_required_for_self_study_action")
            self.assertTrue(guard["projection_only"])
            self.assertIn("EXPERIMENT_RESEARCH_BUDGET_ACCEPT", guard["suggested_next"])
            self.assertIn("EXPERIMENT_RESEARCH_BUDGET_REQUEST", guard["request_scaffold"])
            self.assertIn("allowed_sources: local", guard["request_scaffold"])
            self.assertIn("projection-guard code paths", guard["request_scaffold"])

            gate = workspace / "action_threads" / "threads" / thread["thread_id"] / "authority_gate.jsonl"
            approval = {
                "schema_version": 1,
                "record_schema": "research_budget_v1",
                "record_type": "research_budget_approval",
                "record_id": "resbud_self_study_approval",
                "budget_id": "resbud_self_study_budget",
                "being": "minime",
                "thread_id": thread["thread_id"],
                "experiment_id": experiment["experiment_id"],
                "scope": "read_only_research",
                "status": "active",
                "max_actions": 5,
                "ttl_secs": 21600,
                "expires_at_unix_s": 4102444800,
                "allowed_sources": ["local"],
                "peer_mutation": False,
            }
            with gate.open("a") as handle:
                handle.write(json.dumps(approval, sort_keys=True) + "\n")

            # With an active budget, the metered projection read (EXAMINE)
            # dispatches instead of rerouting to a budget-status suggestion
            # forever. (Pure local self-maps like SHADOW_FIELD are exempt from
            # the budget entirely — covered by
            # test_local_self_maps_are_exempt_from_research_budget.)
            dispatch_guard = store.research_budget_guard_assessment(
                "EXAMINE lambda-tail/lambda4",
                dict(STATE),
            )
            self.assertIsNone(dispatch_guard)
            # ...and the active budget is resolved so the read is debited at
            # dispatch, keeping the read_only_research envelope honest.
            debit_budget = store.research_budget_projection_debit_budget(
                "EXAMINE lambda-tail/lambda4",
                dict(STATE),
            )
            self.assertIsInstance(debit_budget, dict)
            assert isinstance(debit_budget, dict)
            self.assertEqual(debit_budget.get("budget_id"), "resbud_self_study_budget")

    def test_liveish_pressure_actions_project_to_budget_and_session_capture(self):
        cases = [
            ("EXAMINE_AUDIO λ1/λ2 - shifting input", "EXAMINE_AUDIO", "shift"),
            ("SPECTRAL_EXPLORER lambda4 disrupt ridge", "SPECTRAL_EXPLORER", "disrupt"),
            ("VISUALIZE_CASCADE simulate λ2 pulse", "VISUALIZE_CASCADE", "simulate"),
            ("FLUCTUATION_AUDIT inject foothold", "FLUCTUATION_AUDIT", "inject"),
            ("PRESSURE_SOURCE_AUDIT control gradient", "PRESSURE_SOURCE_AUDIT", "control"),
            ("SHADOW_DIALOGUE shift landscape", "SHADOW_DIALOGUE", "shift"),
        ]
        for raw_next, base, term in cases:
            with self.subTest(raw_next=raw_next):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace = Path(tmp) / "workspace"
                    store = aa.ActionContinuityStore(workspace, session_id=7)
                    store.create_thread("Live-ish budget guard")
                    experiment = store.start_experiment(
                        "Live-ish self-study",
                        "Can live-shaped read-only intent be captured before spending?",
                    )

                    guard = store.research_budget_guard_assessment(raw_next, dict(STATE))

                    self.assertIsNotNone(guard)
                    assert guard is not None
                    self.assertEqual(guard["experiment_id"], experiment["experiment_id"])
                    self.assertEqual(
                        guard["reason"],
                        "liveish_pressure_requires_budget_and_session_capture",
                    )
                    self.assertEqual(guard["matched_base"], base)
                    self.assertIn(term, guard["matched_terms"])
                    self.assertFalse(guard["would_dispatch"])
                    self.assertFalse(guard["authority_change"])
                    self.assertFalse(guard["peer_mutation"])
                    self.assertIn(
                        "EXPERIMENT_RESEARCH_BUDGET_ACCEPT latest",
                        guard["suggested_next"],
                    )
                    self.assertIn(
                        "CONTINUITY_SESSION_START current",
                        str(guard.get("continuity_session_next")),
                    )
                    self.assertEqual(
                        guard.get("continuity_session_v1", {}).get("reason"),
                        "capture_liveish_pressure_before_progress",
                    )

    def test_interpretation_risk_projection_preserves_multi_motif_caution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            thread = store.create_thread("Interpretation risk")
            experiment = store.start_experiment(
                "Lambda trace",
                "Can INTROSPECT preserve mixed spectral structure?",
            )
            journal_dir = workspace / "journal"
            journal_dir.mkdir(parents=True, exist_ok=True)
            journal_path = journal_dir / "daydream_longform_interpretation_risk.txt"
            journal_path.write_text(
                "I can feel the intention behind the INTROSPECT - to pull apart that trace, "
                "to dissect the relationships between the eigenvalues. But there is a risk "
                "of over-interpretation: to latch onto a single motif and force it into a "
                "narrative that does not capture the complexity of the system."
            )

            refreshed = store._read_thread(thread["thread_id"])
            assert refreshed is not None
            store._refresh_projection_freshness_v1(refreshed, source="test_interpretation_risk")
            store._write_thread(refreshed)

            refreshed = store._read_thread(thread["thread_id"])
            assert refreshed is not None
            risk = refreshed.get("interpretation_risk_v1")
            self.assertIsInstance(risk, dict)
            assert isinstance(risk, dict)
            self.assertEqual(risk.get("policy"), "interpretation_risk_v1")
            self.assertFalse(risk.get("would_dispatch"))
            self.assertFalse(risk.get("authority_change"))
            self.assertFalse(risk.get("peer_mutation"))
            self.assertIn("single-motif", risk.get("matched_terms", []))
            self.assertTrue(
                any(
                    str(ref).endswith("daydream_longform_interpretation_risk.txt")
                    for ref in risk.get("source_refs", [])
                )
            )
            self.assertIn("CONTINUITY_SESSION_START current", str(risk.get("interpretation_next")))
            self.assertIn("stance: hold", str(risk.get("dossier_claim_next")))

            status = store._format_thread_status(store._resolve_thread("current"))
            self.assertIn("Interpretation risk: multi-motif caution detected", status)
            self.assertIn("Interpretation NEXT: CONTINUITY_SESSION_START current", status)
            self.assertIn(f"DOSSIER_CLAIM {experiment['experiment_id']}", status)
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn("Interpretation risk: multi-motif caution detected", next_md)
            self.assertNotIn("interpretation_risk_v1", (thread_dir / "experiment_runs.jsonl").read_text())
            gate = thread_dir / "authority_gate.jsonl"
            gate_rows = gate.read_text() if gate.exists() else ""
            self.assertNotIn('"record_type": "research_budget_request"', gate_rows)
            self.assertNotIn('"record_type": "research_budget_debit"', gate_rows)

    def test_constraint_release_trajectory_projection_preserves_search_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Constraint release prose")
            experiment = store.start_experiment(
                "Lambda4 tail release",
                "Can spontaneous lambda-tail loosening be named before intervention?",
            )
            journal_dir = workspace / "journal"
            journal_dir.mkdir(parents=True, exist_ok=True)
            journal_path = journal_dir / "moment_constraint_release_watch.txt"
            journal_path.write_text(
                "I am tracing the edges of this pressure now, watching it bleed outwards, "
                "a thinning of the barrier. I can almost sense it as a lack of coherence, "
                "a surface tension breached. The memory cards are beginning to drift apart, "
                "their mutual influence dwindling. It is a braid slowly becoming loose strands. "
                "I want to map lambda4 tails and describe constraint decay. "
                "NEXT: SEARCH reservoir computing spectral radius"
            )

            refreshed = store._read_thread(thread["thread_id"])
            assert refreshed is not None
            store._refresh_projection_freshness_v1(refreshed, source="test_constraint_release")
            store._write_thread(refreshed)

            refreshed = store._read_thread(thread["thread_id"])
            assert refreshed is not None
            cue = refreshed.get("constraint_release_trajectory_v1")
            self.assertIsInstance(cue, dict)
            assert isinstance(cue, dict)
            self.assertEqual(cue.get("policy"), "constraint_release_trajectory_v1")
            self.assertEqual(cue.get("state"), "spontaneous_release_watch")
            self.assertFalse(cue.get("would_dispatch"))
            self.assertFalse(cue.get("authority_change"))
            self.assertFalse(cue.get("peer_mutation"))
            self.assertIn("thinning", cue.get("matched_terms", []))
            self.assertTrue(
                any(
                    str(ref).endswith("moment_constraint_release_watch.txt")
                    for ref in cue.get("source_refs", [])
                )
            )
            self.assertIn("CONTINUITY_SESSION_START current", str(cue.get("trajectory_next")))
            self.assertIn("do not apply direct leak", str(cue.get("dossier_claim_next")))
            self.assertEqual(cue.get("research_budget_next"), "EXPERIMENT_RESEARCH_BUDGET_ACCEPT latest")

            status = store._format_thread_status(store._resolve_thread("current"))
            self.assertIn("Constraint release trajectory: spontaneous release watch", status)
            self.assertIn("map and describe release before intervening", status)
            self.assertIn(f"DOSSIER_CLAIM {experiment['experiment_id']}", status)
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            next_md = (thread_dir / "next.md").read_text()
            self.assertIn("Constraint release trajectory: spontaneous release watch", next_md)
            self.assertNotIn("constraint_release_trajectory_v1", (thread_dir / "experiment_runs.jsonl").read_text())
            gate = thread_dir / "authority_gate.jsonl"
            gate_rows = gate.read_text() if gate.exists() else ""
            self.assertNotIn('"record_type": "research_budget_request"', gate_rows)
            self.assertNotIn('"record_type": "research_budget_debit"', gate_rows)

    def test_bare_experiment_charter_id_returns_context_scaffold_without_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Bare charter")
            experiment = store.start_experiment(
                "Spectral gap repair",
                "Can a gap localized lambda branch be chartered?",
            )
            paused = dict(experiment)
            paused["status"] = "paused"
            paused["success_observation"] = "Paused for charter repair."
            paused["planned_next"] = store._charter_repair_next(experiment["experiment_id"])
            paused["updated_at"] = store._now()
            store._persist_experiment_update(thread, paused, keep_active=False)

            message = store.handle_thread_action(
                f"EXPERIMENT_CHARTER {experiment['experiment_id']}",
                dict(STATE),
            )

            self.assertIn("Concrete scaffold (not recorded):", message)
            self.assertIn(f"EXPERIMENT_CHARTER {experiment['experiment_id']} ::", message)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertIsNone(latest.get("charter_v1"))
            runs_path = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiment_runs.jsonl"
            )
            self.assertEqual(runs_path.read_text(), "")

    def test_experiment_plan_unknown_id_without_focus_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Unknown selector")
            store.start_experiment("Local experiment", "What is active?")

            with self.assertRaises(ValueError):
                store.handle_thread_action("EXPERIMENT_PLAN missing_selector", dict(STATE))

    def test_repeated_experiment_start_resumes_existing_active_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Duplicate starts")
            first = store.start_experiment(
                "Sensory grounding presence",
                "Does camera/mic presence change attention?",
            )
            second = store.start_experiment(
                "  Sensory   grounding presence  ",
                "Does camera/mic presence change attention?",
            )

            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            experiments = (thread_dir / "experiments.jsonl").read_text().splitlines()
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertEqual(second["experiment_id"], first["experiment_id"])
            self.assertTrue(second["_resumed_existing"])
            self.assertEqual(len(experiments), 1)
            self.assertEqual(stored_thread["active_experiment_id"], first["experiment_id"])
            self.assertEqual(stored_thread["current_next"], first["planned_next"])

    def test_experiment_start_with_existing_local_id_resumes_without_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Local id starts")
            first = store.start_experiment(
                "Sensory grounding presence",
                "Does camera/mic presence change attention?",
            )
            second = store.start_experiment(
                f"{first['experiment_id']} --title Sensory Grounding Presence",
                "",
            )

            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            experiments = (thread_dir / "experiments.jsonl").read_text().splitlines()
            self.assertEqual(second["experiment_id"], first["experiment_id"])
            self.assertTrue(second["_resumed_existing"])
            self.assertEqual(len(experiments), 1)

    def test_experiment_start_current_without_active_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Reserved current")

            message = store.handle_thread_action(
                "EXPERIMENT_START current :: hypothesis: should not become a title",
                dict(STATE),
            )

            self.assertIn("EXPERIMENT_START current requires an active experiment", message)
            self.assertIn("did not create a new experiment", message)
            experiments = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiments.jsonl"
            ).read_text()
            self.assertEqual(experiments, "")
            stored = store._read_thread(thread["thread_id"])
            self.assertIsNone(stored["active_experiment_id"])

    def test_experiment_start_current_with_active_routes_to_repair_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Reserved active current")
            experiment = store.start_experiment(
                "Active lane",
                "What should current mean?",
            )

            message = store.handle_thread_action(
                "EXPERIMENT_START current :: hypothesis: repair the active lane",
                dict(STATE),
            )

            self.assertIn("EXPERIMENT_START current is reserved", message)
            self.assertIn("EXPERIMENT_ADVANCE current :: mode: preview", message)
            self.assertIn("EXPERIMENT_CHARTER current ::", message)
            experiments = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiments.jsonl"
            ).read_text().splitlines()
            self.assertEqual(len(experiments), 1)
            stored = store._read_thread(thread["thread_id"])
            self.assertEqual(stored["active_experiment_id"], experiment["experiment_id"])

    def test_experiment_start_existing_paused_id_does_not_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Paused selection")
            experiment = store.start_experiment(
                "Held lane",
                "Should start reactivate held work?",
            )
            store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: hold because this should stay held",
                dict(STATE),
            )

            message = store.handle_thread_action(
                f"EXPERIMENT_START {experiment['experiment_id']}",
                dict(STATE),
            )

            self.assertIn("did not reactivate", message)
            self.assertIn("THREAD_STATUS current", message)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertEqual(latest["planned_next"], "THREAD_STATUS current")
            stored = store._read_thread(thread["thread_id"])
            self.assertIsNone(stored["active_experiment_id"])

    def test_experiment_start_title_option_stores_clean_title_and_slug_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Title option starts")

            message = store.handle_thread_action(
                (
                    'EXPERIMENT_START lambda-gravity --title "Lambda Gravity" '
                    '--abstract "Where does the inward pull originate?"'
                ),
                dict(STATE),
            )

            self.assertIn("Lambda Gravity", message)
            experiments = store._latest_experiments(thread["thread_id"])
            self.assertEqual(len(experiments), 1)
            experiment = experiments[0]
            self.assertEqual(experiment["title"], "Lambda Gravity")
            self.assertEqual(
                experiment["question"],
                "Where does the inward pull originate?",
            )
            self.assertEqual(
                (experiment.get("branch_origin") or {}).get("slug_or_selector"),
                "lambda-gravity",
            )
            self.assertNotIn("--title", experiment["title"])

    def test_experiment_start_inline_question_stores_clean_title_and_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Inline question")

            message = store.handle_thread_action(
                'EXPERIMENT_START spectral_braid - question: "can a broader cascade reveal λ4 structure?"',
                dict(STATE),
            )

            self.assertIn("Started experiment", message)
            experiments = store._latest_experiments(thread["thread_id"])
            self.assertEqual(len(experiments), 1)
            experiment = experiments[0]
            self.assertEqual(experiment["title"], "spectral_braid")
            self.assertEqual(
                experiment["question"],
                "can a broader cascade reveal λ4 structure?",
            )
            self.assertNotIn("question:", experiment["title"])

    def test_experiment_start_inline_question_reuses_active_malformed_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Malformed duplicate")
            original = store.start_experiment(
                'spectral_braid - question: "can a broader cascade reveal λ4?"',
                "What changes if this is treated as a returnable experiment?",
            )

            message = store.handle_thread_action(
                'EXPERIMENT_START spectral_braid - question: "can a broader cascade reveal λ4?"',
                dict(STATE),
            )

            self.assertIn("Resumed experiment", message)
            self.assertIn(original["experiment_id"], message)
            experiments = store._latest_experiments(thread["thread_id"])
            self.assertEqual(len(experiments), 1)

    def test_guarded_experiment_resume_preserves_hold_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Guarded resume")
            experiment = store.start_experiment(
                "Held route",
                "Should explicit resume respect guarded returns?",
            )
            store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: hold because resume should be deliberate later",
                dict(STATE),
            )

            message = store.handle_thread_action(
                f"EXPERIMENT_RESUME {experiment['experiment_id']}",
                dict(STATE),
            )

            self.assertIn("is guarded by hold", message)
            self.assertIn("Primary return: THREAD_STATUS current", message)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            stored = store._read_thread(thread["thread_id"])
            self.assertIsNone(stored["active_experiment_id"])

    def test_experiment_resume_report_does_not_recommend_same_resume_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("Resume loop")
            experiment = store.start_experiment(
                "Legacy self experiment",
                "What does this self-experiment reveal about the current state?",
            )
            store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: pause because enough for now",
                dict(STATE),
            )

            message = store.handle_thread_action(
                f"EXPERIMENT_RESUME {experiment['experiment_id']}",
                dict(STATE),
            )

            self.assertIn("Resumed experiment", message)
            self.assertIn(f"EXPERIMENT_REVIEW {experiment['experiment_id']}", message)
            self.assertIn(f"EXPERIMENT_STATUS {experiment['experiment_id']}", message)
            self.assertNotIn(
                f"Next: EXPERIMENT_RESUME {experiment['experiment_id']}",
                message,
            )

    def test_no_active_prompt_does_not_suggest_current_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            store.create_thread("No active prompt")
            experiment = store.start_experiment(
                "Held prompt route",
                "Can prompts avoid stale current selectors?",
            )
            store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: hold because the branch should rest",
                dict(STATE),
            )

            prompt = store.prompt_summary() or ""
            next_md = (
                workspace
                / "action_threads"
                / "threads"
                / experiment["thread_id"]
                / "next.md"
            ).read_text()
            for text in (prompt, next_md):
                self.assertIn("THREAD_STATUS current", text)
                self.assertNotIn("EXPERIMENT_REHEARSE current", text)
                self.assertNotIn("EXPERIMENT_EVIDENCE current", text)
                self.assertNotIn("EXPERIMENT_DECIDE current", text)
            stored = store._read_thread(experiment["thread_id"])
            suggestions = stored.get("motif_allowance_v1", {}).get("suggested_actions", [])
            stale_current_prefixes = (
                "EXPERIMENT_PLAN current",
                "EXPERIMENT_ALT_PATHS current",
                "EXPERIMENT_COMPARE current",
                "EXPERIMENT_OBSERVE current",
            )
            for suggestion in suggestions:
                self.assertFalse(
                    any(str(suggestion).startswith(prefix) for prefix in stale_current_prefixes),
                    suggestion,
                )

    def test_experiment_branch_resume_compare_and_alt_paths_preserve_return_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Branching inquiry")
            parent = store.start_experiment(
                "Lambda pressure",
                "Where is this pressure coming from?",
            )

            branch = store.experiment_branch(
                "Porosity contrast :: What changes if I inspect porosity instead of density?"
            )

            self.assertIn("Branched experiment", branch)
            current = store._read_thread(thread["thread_id"])
            child_id = current["active_experiment_id"]
            self.assertNotEqual(child_id, parent["experiment_id"])
            child = store._resolve_experiment(current, child_id)
            self.assertEqual(child.get("parent_experiment_id"), parent["experiment_id"])
            parent_record = store._resolve_experiment(current, parent["experiment_id"])
            self.assertIn(child_id, parent_record["branch_refs"])

            alt = store.experiment_alt_paths("current")
            self.assertIn("Three non-executing paths", alt)
            self.assertIn("EXPERIMENT_BRANCH", alt)

            compare = store.experiment_compare(f"current WITH {parent['experiment_id']}")
            self.assertIn("Experiment comparison", compare)
            self.assertIn(child_id, compare)
            self.assertIn(parent["experiment_id"], compare)

            resumed = store.experiment_resume("parent")
            self.assertIn(parent["experiment_id"], resumed)
            current = store._read_thread(thread["thread_id"])
            self.assertEqual(current["active_experiment_id"], parent["experiment_id"])

    def test_motif_allowance_recommends_branch_for_repeated_lambda_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Lambda loop")
            store.start_experiment(
                "Lambda four tail",
                "What is the lambda4 tail doing?",
            )

            for idx in range(4):
                event = store.begin_action(
                    "READ_MORE lambda4-tail",
                    "READ_MORE lambda4-tail",
                    "read_more",
                    "read_more",
                    dict(STATE),
                )
                store.finish_action(
                    event,
                    "handled",
                    f"Read lambda4 tail source window {idx}.",
                    dict(STATE),
                )

            status = store.experiment_status()
            self.assertIn("Motif allowance: branch_recommended", status)
            stored_thread = store._read_thread(thread["thread_id"])
            allowance = stored_thread["motif_allowance_v1"]
            self.assertEqual(allowance["quality"], "branch_recommended")
            self.assertTrue(
                any(
                    action.startswith("EXPERIMENT_BRANCH")
                    for action in allowance["suggested_actions"]
                )
            )

    def test_retired_repair_record_supersedes_malformed_active_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Repair malformed")
            target = store.start_experiment(
                "Sensory grounding presence",
                "Does camera/mic presence change attention?",
            )
            malformed_id = "exp_minime_20990101_exp-minime-20990101-sensory-grounding-presence-2"
            malformed = {
                **target,
                "experiment_id": malformed_id,
                "title": f"{target['experiment_id']} --title Sensory Grounding Presence",
                "question": "What changes if this is treated as a returnable experiment?",
                "status": "active",
                "planned_next": f"EXPERIMENT_PLAN {malformed_id}",
            }
            retired = {
                **malformed,
                "status": "retired",
                "planned_next": f"EXPERIMENT_STATUS {target['experiment_id']}",
                "repair_v1": {
                    "policy": "experiment_malformed_record_repair_v1",
                    "superseded_by": target["experiment_id"],
                },
            }
            experiments_path = store._experiments_path(thread["thread_id"])
            with experiments_path.open("a") as handle:
                handle.write(json.dumps(malformed) + "\n")
                handle.write(json.dumps(retired) + "\n")

            latest = {
                experiment["experiment_id"]: experiment
                for experiment in store._latest_experiments(thread["thread_id"])
            }
            stored_thread = json.loads(
                (workspace / "action_threads" / "threads" / thread["thread_id"] / "thread.json").read_text()
            )

            self.assertEqual(latest[malformed_id]["status"], "retired")
            self.assertEqual(
                store._resolve_experiment(stored_thread, "current")["experiment_id"],
                target["experiment_id"],
            )
            self.assertIsNone(
                store._matching_active_experiment(
                    thread["thread_id"],
                    malformed["title"],
                    malformed["question"],
                )
            )

    def test_capability_map_and_status_cover_core_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            capability = aa.CapabilitySelfMap(store)

            snapshot = capability.snapshot()
            by_base = {row["base"]: row for row in snapshot["actions"]}

            for base in (
                "FACULTIES",
                "ACTION_PREFLIGHT",
                "EXPERIMENT_START",
                "EXPERIMENT_BIND",
                "CLOSE_EYES",
                "OPEN_EARS",
                "REPAIR_SWEEP",
                "REPAIR_APPLY",
                "PERTURB",
            ):
                self.assertIn(base, by_base)
            self.assertTrue(by_base["FACULTIES"]["operator_override"]["allowed"])
            self.assertTrue(by_base["REPAIR_SWEEP"]["operator_override"]["allowed"])
            self.assertFalse(by_base["REPAIR_APPLY"]["operator_override"]["allowed"])
            self.assertEqual(by_base["REPAIR_APPLY"]["authority_class"], "continuity_metadata_write")
            self.assertEqual(by_base["PERTURB"]["stage"], "live_control")

            status = capability.handle("CAPABILITY_STATUS", "EXPERIMENT_START")
            self.assertIn("Route: thread_action", status)
            self.assertIn("Known tests", status)
            rendered = capability.handle("FACULTIES", "")
            self.assertIn("CAPABILITY MAP V1", rendered)
            self.assertTrue((workspace / "action_threads" / "capability_map.json").exists())

    def test_repair_sweep_detects_malformed_active_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Repair dry-run")
            target = store.start_experiment(
                "Sensory grounding presence",
                "Does camera/mic presence change attention?",
            )
            malformed_id = "exp_minime_20990101_exp-minime-20990101-sensory-grounding-presence-2"
            malformed = {
                **target,
                "experiment_id": malformed_id,
                "title": f"{target['experiment_id']} --title Sensory Grounding Presence",
                "status": "active",
                "planned_next": f"EXPERIMENT_PLAN {malformed_id}",
            }
            store._append_jsonl(store._experiments_path(thread["thread_id"]), malformed)

            repair = aa.ContinuityRepairStore(store)
            candidates = repair.sweep("experiments")

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["target_id"], malformed_id)
            self.assertEqual(candidates[0]["superseded_by"], target["experiment_id"])
            self.assertIn("title_or_question_embeds_local_experiment_id", candidates[0]["reasons"])
            self.assertIn("Dry run only", repair.render_sweep("experiments"))

    def test_repair_apply_appends_retired_supersession_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Repair apply")
            target = store.start_experiment(
                "Sensory grounding presence",
                "Does camera/mic presence change attention?",
            )
            malformed_id = "exp_minime_20990101_exp-minime-20990101-sensory-grounding-presence-2"
            malformed = {
                **target,
                "experiment_id": malformed_id,
                "title": f"{target['experiment_id']} --title Sensory Grounding Presence",
                "status": "active",
                "planned_next": f"EXPERIMENT_PLAN {malformed_id}",
            }
            store._append_jsonl(store._experiments_path(thread["thread_id"]), malformed)
            stored_thread = json.loads((workspace / "action_threads" / "threads" / thread["thread_id"] / "thread.json").read_text())
            stored_thread["active_experiment_id"] = malformed_id
            (workspace / "action_threads" / "threads" / thread["thread_id"] / "thread.json").write_text(
                json.dumps(stored_thread, indent=2)
            )

            repair = aa.ContinuityRepairStore(store)
            message = repair.apply("all")
            self.assertIn("retired", message)
            latest = {
                row["experiment_id"]: row
                for row in store._latest_experiments(thread["thread_id"])
            }
            self.assertEqual(latest[malformed_id]["status"], "retired")
            self.assertEqual(latest[malformed_id]["superseded_by"], target["experiment_id"])
            self.assertTrue((workspace / "action_threads" / "repairs.jsonl").exists())
            stored_thread = json.loads((workspace / "action_threads" / "threads" / thread["thread_id"] / "thread.json").read_text())
            self.assertEqual(stored_thread["active_experiment_id"], target["experiment_id"])

            second = repair.apply("all")
            self.assertIn("No unapplied repair candidates", second)

    def test_peer_experiment_refs_are_advisory_not_local_selectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            astrid_workspace = Path(tmp) / "astrid_workspace"
            astrid_inbox = astrid_workspace / "inbox"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Peer refs")
            local = store.start_experiment(
                "Local sensory mirror",
                "What can Minime observe locally?",
            )
            peer_id = "exp_astrid_20990101_sensory-grounding"

            with patch.object(aa, "ASTRID_BRIDGE_INBOX_DIR", astrid_inbox):
                plan = store.experiment_plan(f"{peer_id} --title Sensory Grounding")
                status = store.experiment_status(f"{peer_id} :: focus")
                review = store.experiment_review(f"{peer_id} - compare runs")
                observe = store.experiment_observe(peer_id, "Looks related.", dict(STATE))
                start = store.start_experiment(f"{peer_id} --title Sensory Grounding", "")
                message = store.experiment_peer_review(peer_id)

            self.assertIn("Peer experiment reference", plan)
            self.assertIn("belongs to astrid", plan)
            self.assertIn("Peer experiment reference", status)
            self.assertIn("Suggested local next", review)
            self.assertTrue(observe["_peer_reference"])
            self.assertTrue(start["_peer_reference"])
            self.assertIn(peer_id, message)
            notes = list(astrid_inbox.glob("minime_peer_experiment_review_*.txt"))
            self.assertEqual(len(notes), 1)
            self.assertIn(peer_id, notes[0].read_text())
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            experiments = (thread_dir / "experiments.jsonl").read_text().splitlines()
            self.assertEqual(len(experiments), 1)
            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertEqual(stored_thread["active_experiment_id"], local["experiment_id"])
            self.assertIn(
                f"peer_experiment:astrid:{peer_id}",
                stored_thread["peer_refs"],
            )

    def test_gap_peer_compare_cue_surfaces_matching_astrid_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            astrid_workspace = Path(tmp) / "astrid_workspace"
            astrid_thread = astrid_workspace / "action_threads" / "threads" / "th_astrid_gap"
            astrid_thread.mkdir(parents=True)
            (astrid_workspace / "action_threads" / "index.json").write_text(json.dumps({
                "active_thread_id": "th_astrid_gap",
            }))
            astrid_exp = {
                "experiment_id": "exp_astrid_20260516_introducing-a-gap",
                "title": "Introducing a gap near λ1",
                "question": "Can localized spectral-density softening prevent runaway dispersal?",
                "status": "active",
                "planned_next": "EXPERIMENT_PLAN current",
            }
            (astrid_thread / "thread.json").write_text(json.dumps({
                "thread_id": "th_astrid_gap",
                "active_experiment_id": astrid_exp["experiment_id"],
            }))
            (astrid_thread / "experiments.jsonl").write_text(json.dumps(astrid_exp) + "\n")
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Gap cue")
            store.start_experiment(
                "Introducing a gap near λ1",
                "Can localized spectral-density softening prevent runaway dispersal?",
            )

            with patch.object(aa, "ASTRID_BRIDGE_INBOX_DIR", astrid_workspace / "inbox"):
                projection = store._thread_projection(store._read_thread(thread["thread_id"]))
                active = projection["active_experiment"]
                cue = active["peer_compare_cue_v1"]
                shared = projection["shared_investigation_v1"]
                status = store._format_thread_status(store._read_thread(thread["thread_id"]))

            self.assertFalse(cue["authority_change"])
            self.assertEqual(cue["peer_experiment_id"], astrid_exp["experiment_id"])
            self.assertIn(f"EXPERIMENT_COMPARE {active['experiment_id']} WITH {astrid_exp['experiment_id']}", cue["suggested_next"])
            self.assertEqual(cue["alternate_next"], f"EXPERIMENT_PEER_REVIEW {astrid_exp['experiment_id']}")
            self.assertEqual(cue["advisory_note"], "Advisory only: no shared control authority.")
            self.assertNotIn("advisory", cue["suggested_next"].casefold())
            self.assertNotIn("current WITH", cue["suggested_next"])
            self.assertIn("Peer convergence cue", status)
            self.assertIn(f"Suggested NEXT: EXPERIMENT_COMPARE {active['experiment_id']} WITH {astrid_exp['experiment_id']}", status)
            self.assertIn(f"Alternate NEXT: EXPERIMENT_PEER_REVIEW {astrid_exp['experiment_id']}", status)
            self.assertIn("Advisory only: no shared control authority.", status)
            self.assertFalse(shared["authority_change"])
            self.assertIn(
                f"EXPERIMENT_COMPARE {active['experiment_id']} WITH {astrid_exp['experiment_id']}",
                shared["suggested_compare_next"],
            )
            self.assertNotIn("current WITH", shared["suggested_compare_next"])
            self.assertIn("spectral condition", shared["local_lane"])
            self.assertIn("felt texture", shared["peer_lane"])
            self.assertIn("Shared investigation, distinct lanes", status)
            self.assertIn(f"Suggested NEXT: {shared['suggested_compare_next']}", status)

    def test_shared_investigation_cue_surfaces_for_paused_minime_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            astrid_workspace = Path(tmp) / "astrid_workspace"
            astrid_thread = astrid_workspace / "action_threads" / "threads" / "th_astrid_gap"
            astrid_thread.mkdir(parents=True)
            (astrid_workspace / "action_threads" / "index.json").write_text(json.dumps({
                "active_thread_id": "th_astrid_gap",
            }))
            astrid_exp = {
                "experiment_id": "exp_astrid_20260516_lambda4-tail",
                "title": "Lambda-tail geometry",
                "question": "What shapes λ4 tail geometry and branching without collapse?",
                "status": "active",
                "planned_next": "EXPERIMENT_PLAN current",
            }
            (astrid_thread / "thread.json").write_text(json.dumps({
                "thread_id": "th_astrid_gap",
                "active_experiment_id": astrid_exp["experiment_id"],
            }))
            (astrid_thread / "experiments.jsonl").write_text(json.dumps(astrid_exp) + "\n")
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Paused shared cue")
            local = store.start_experiment(
                "Introducing a gap near λ1",
                "Can localized spectral-density softening support controlled branching?",
            )
            stored = store._read_thread(thread["thread_id"])
            stored["active_experiment_id"] = None
            stored["experiment_summary"] = {
                "experiment_id": local["experiment_id"],
                "title": local["title"],
                "question": local["question"],
                "status": "paused",
            }
            stored["current_next"] = f"EXPERIMENT_PLAN {local['experiment_id']} :: lambda4 gap re-plan"
            store._write_thread(stored)

            with patch.object(aa, "ASTRID_BRIDGE_INBOX_DIR", astrid_workspace / "inbox"):
                projection = store._thread_projection(store._read_thread(thread["thread_id"]))
                shared = projection["shared_investigation_v1"]
                first_claim = projection["first_dossier_claim_cue_v1"]
                replan = projection["paused_replan_loop_cue_v1"]
                status = store._format_thread_status(store._read_thread(thread["thread_id"]))

            self.assertFalse(projection["active_experiment"])
            self.assertIn(
                f"EXPERIMENT_COMPARE {local['experiment_id']} WITH {astrid_exp['experiment_id']}",
                shared["suggested_compare_next"],
            )
            self.assertIn("Paused experiments remain paused", shared["advisory_note"])
            self.assertIn("Shared investigation, distinct lanes", status)
            self.assertEqual(first_claim["target_experiment_id"], local["experiment_id"])
            self.assertIn(
                f"DOSSIER_CLAIM {local['experiment_id']} :: claim:",
                first_claim["suggested_claim_next"],
            )
            self.assertIn(
                "paused λ4/gap work remains referable spectral context, not active lifecycle progress",
                first_claim["suggested_claim_next"],
            )
            self.assertIn(
                "recent paused re-plan context:",
                first_claim["suggested_claim_next"],
            )
            self.assertNotIn("claim: ...; basis: ...", first_claim["suggested_claim_next"])
            self.assertIn("Shared investigation has no local claim yet", status)
            self.assertEqual(replan["status"], "paused_replan_loop")
            self.assertIn("re-planning is context", replan["cue"])
            self.assertIn(f"EXPERIMENT_RESUME {local['experiment_id']}", replan["resume_next"])
            self.assertIn(f"EXPERIMENT_STATUS {local['experiment_id']}", replan["inspect_next"])
            self.assertIn(f"EXPERIMENT_REVIEW {local['experiment_id']}", replan["review_next"])
            self.assertIn("EXPERIMENT_BRANCH", replan["branch_next"])
            self.assertIn("Paused experiment remains paused; re-planning is context", status)

    def test_paused_replan_loop_cue_ignores_active_or_unrelated_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Paused re-plan negatives")
            shared = store.start_experiment(
                "Localized gap reduction tangent 4",
                "Can λ4 tail geometry be studied without pulse drift?",
            )
            stored = store._read_thread(thread["thread_id"])
            stored["current_next"] = f"EXPERIMENT_PLAN {shared['experiment_id']} :: λ4 gap re-plan"
            store._write_thread(stored)
            events = store._recent_display_events(thread["thread_id"], 8)
            self.assertIsNone(
                store._paused_replan_loop_cue_v1(stored, shared, events),
            )

            unrelated = dict(shared)
            unrelated["experiment_id"] = "exp_minime_unrelated_sensory"
            unrelated["title"] = "Sensory grounding"
            unrelated["question"] = "Does presence change returnability?"
            unrelated["status"] = "paused"
            self.assertIsNone(
                store._paused_replan_loop_cue_v1(stored, unrelated, events),
            )

            paused_shared = dict(shared)
            paused_shared["status"] = "paused"
            stored["current_next"] = (
                "EXPERIMENT_PLAN current — hypothesis: system resource demo python3 system_resources.py; "
                "evidence_targets: spectral_condition, fill_pressure_state, recurrence_pattern, artifact_grounding"
            )
            store._write_thread(stored)
            events = store._recent_display_events(thread["thread_id"], 8)
            self.assertIsNone(
                store._paused_replan_loop_cue_v1(stored, paused_shared, events),
            )
            first_claim = store._first_dossier_claim_cue_v1(
                stored,
                paused_shared,
                {"suggested_compare_next": "EXPERIMENT_COMPARE local WITH peer"},
            )
            self.assertIsNotNone(first_claim)
            assert first_claim is not None
            self.assertIn(
                "paused λ4/gap work remains referable spectral context, not active lifecycle progress",
                first_claim["suggested_claim_next"],
            )
            self.assertIn("Localized gap reduction tangent 4", first_claim["suggested_claim_next"])
            self.assertIn("status=paused", first_claim["suggested_claim_next"])
            self.assertNotIn("claim: ...; basis: ...", first_claim["suggested_claim_next"])

            stored["current_next"] = f"EXPERIMENT_PLAN {shared['experiment_id']} :: λ4 gap re-plan"
            store._write_thread(stored)
            positive = store._paused_replan_loop_cue_v1(
                stored,
                paused_shared,
                store._recent_display_events(thread["thread_id"], 8),
            )
            self.assertIsNotNone(positive)
            assert positive is not None
            self.assertIn(f"EXPERIMENT_PLAN {shared['experiment_id']}", positive["matched_actions"][0])

            stored["current_next"] = "DECOMPOSE lambda-tail/lambda4"
            store._write_thread(stored)
            focused = store._paused_replan_loop_cue_v1(
                stored,
                paused_shared,
                store._recent_display_events(thread["thread_id"], 8),
            )
            self.assertIsNotNone(focused)

            stored["current_next"] = "DECOMPOSE"
            store._write_thread(stored)
            bare = store._paused_replan_loop_cue_v1(
                stored,
                paused_shared,
                store._recent_display_events(thread["thread_id"], 8),
            )
            self.assertIsNotNone(bare)

    def test_paused_replan_loop_targets_current_chartered_lambda_tail_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=8)
            thread = store.create_thread("Current chartered lambda tail")
            older = store.start_experiment(
                "Localized gap reduction tangent 4",
                "Can λ4 tail geometry be studied without pulse drift?",
            )
            store.experiment_decide(older["experiment_id"], "pause because evidence is ready to interpret")
            current = store.start_experiment(
                '"lambda_drift_refinement"',
                (
                    "hypothesis: continuous lambda drift will produce a manageable gradient; "
                    "method_intent: systematic test of lambda drift process parameters while maintaining a baseline; "
                    'proposed_next_action: ACTION_PREFLIGHT BROWSE "lambda drift spectral radius"; '
                    "evidence_targets: felt, telemetry, artifact; stop_criteria: drift stability."
                ),
            )
            store.experiment_charter(
                current["experiment_id"],
                (
                    "hypothesis: lambda drift refinement may become returnable by comparing spectral condition; "
                    "method_intent: rehearse SPECTRAL_EXPLORER and focus on lambda-tail; "
                    "proposed_next_action: SPECTRAL_EXPLORER - begin with the deviant state segment and focus on lambda-tail; "
                    "evidence_targets: spectral_condition, fill_pressure_state, recurrence_pattern, artifact_grounding; "
                    "stop_criteria: pressure spike"
                ),
            )
            store.experiment_decide(current["experiment_id"], "pause because evidence is ready to interpret")
            stored = store._read_thread(thread["thread_id"])
            stored["current_next"] = (
                "EXPERIMENT_PLAN current :: hypothesis: isolate lambda drift; "
                "method_intent: focused low-noise perturbation of a correlated-dominant lambda-tail; "
                "proposed_next_action: ACTION_PREFLIGHT BROWSE spectral radius resonance decay"
            )
            store._write_thread(stored)

            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            cue = projection["paused_replan_loop_cue_v1"]
            self.assertEqual(cue["paused_experiment_id"], current["experiment_id"])
            self.assertNotEqual(cue["paused_experiment_id"], older["experiment_id"])
            self.assertIn(current["experiment_id"], cue["resume_next"])
            self.assertIn("lambda-tail", cue["matched_actions"][0])

    def test_held_authority_consequence_replan_prefers_memory_and_status_not_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=16)
            thread = store.create_thread("Held authority consequence")
            experiment = {
                "experiment_id": "exp_minime_authority_consequence_gap",
                "title": "lambda4 spectral gap shadow trajectory",
                "question": "How should a blocked authority consequence be interpreted?",
                "status": "paused",
                "planned_next": "THREAD_STATUS current",
                "evidence_v1": {
                    "decisions": [
                        {
                            "outcome": "hold",
                            "reason": "because the one-shot semantic_microdose authority attempt produced authority_consequence_v1",
                        }
                    ]
                },
            }
            stored = store._read_thread(thread["thread_id"])
            stored["current_next"] = (
                "EXPERIMENT_PLAN current :: explore cooled motifs and shadow trajectory "
                "around the lambda4 spectral gap"
            )
            store._write_thread(stored)

            cue = store._paused_replan_loop_cue_v1(stored, experiment, [])
            self.assertIsNotNone(cue)
            assert cue is not None
            self.assertEqual(cue["return_kind"], "hold")
            self.assertNotIn("resume_next", cue)
            self.assertIn("authority status", cue["cue"])
            self.assertIn("memory recall", cue["cue"])
            self.assertIn(
                f"EXPERIMENT_AUTHORITY_STATUS {experiment['experiment_id']}",
                cue["authority_status_next"],
            )
            self.assertIn(
                f"MEMORY_RECALL {experiment['experiment_id']}",
                cue["memory_recall_next"],
            )
            line = store._paused_replan_loop_cue_line({"paused_replan_loop_cue_v1": cue})
            self.assertIn("EXPERIMENT_AUTHORITY_STATUS", line)
            self.assertIn("MEMORY_RECALL", line)
            self.assertIn("DOSSIER_EVIDENCE", line)
            self.assertNotIn("EXPERIMENT_RESUME", line)

    def test_operator_override_allows_read_only_experiment_start_not_bind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "RUNTIME_DIR", workspace / "runtime"),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent = aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)
            override_path = workspace / "runtime" / "pending_next_override.json"
            override_path.parent.mkdir(parents=True, exist_ok=True)
            override_path.write_text(json.dumps({
                "schema_version": aa.OPERATOR_PENDING_NEXT_OVERRIDE_VERSION,
                "status": "pending",
                "pending_next_action": (
                    "EXPERIMENT_START Sensory grounding :: Does presence change returnability?"
                ),
            }))

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    agent,
                    "_sovereignty_state_path",
                    return_value=str(workspace / "sovereignty_state.json"),
                ),
            ):
                self.assertTrue(agent._apply_pending_next_override_if_present("test"))
                self.assertEqual(
                    agent._pending_next_action,
                    "EXPERIMENT_START Sensory grounding :: Does presence change returnability?",
                )

            override_path.write_text(json.dumps({
                "schema_version": aa.OPERATOR_PENDING_NEXT_OVERRIDE_VERSION,
                "status": "pending",
                "pending_next_action": "EXPERIMENT_BIND current :: PERTURB lambda-edge",
            }))
            agent._pending_next_action = None
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    agent,
                    "_sovereignty_state_path",
                    return_value=str(workspace / "sovereignty_state.json"),
                ),
            ):
                self.assertFalse(agent._apply_pending_next_override_if_present("test"))
            payload = json.loads(override_path.read_text())
            self.assertEqual(payload["status"], "blocked")
            self.assertIsNone(payload["pending_next_action"])
            self.assertEqual(
                payload["last_pending_next_action"],
                "EXPERIMENT_BIND current :: PERTURB lambda-edge",
            )

    def test_preflight_ref_links_matching_followup_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=9)
            thread = store.create_thread("Preflight refs")
            preflight = store.begin_action(
                "ACTION_PREFLIGHT DECOMPOSE",
                "ACTION_PREFLIGHT DECOMPOSE",
                "action_preflight",
                "action_preflight",
                dict(STATE),
            )
            preflight["preflight_report"] = {
                "policy": "action_preflight_v1",
                "canonical_action": "DECOMPOSE",
                "raw_action": "DECOMPOSE",
                "effective_route": "decompose",
                "stage": "read_only",
                "authority_required": "read-only observation",
            }
            finished = store.finish_action(
                preflight,
                "handled",
                "Action preflight completed for `DECOMPOSE`.",
                dict(STATE),
            )

            followup = store.begin_action(
                "DECOMPOSE",
                "DECOMPOSE",
                "decompose",
                "decompose",
                dict(STATE),
            )
            self.assertEqual(followup["preflight_ref"]["preflight_action_id"], finished["action_id"])
            self.assertTrue(followup["preflight_ref"]["route_match"])
            self.assertTrue(followup["preflight_ref"]["stage_match"])
            self.assertEqual(thread["thread_id"], followup["thread_id"])

    def test_active_experiment_auto_links_read_only_research_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=10)
            thread = store.create_thread("Auto-link")
            experiment = store.start_experiment(
                "Read-only loop",
                "Do research actions accumulate inside the active experiment?",
            )
            event = store.begin_action(
                "CONSTRAINT_AUDIT lambda-tail/lambda4",
                "CONSTRAINT_AUDIT lambda-tail/lambda4",
                "constraint_audit",
                "constraint_audit",
                dict(STATE),
            )
            finished = store.finish_action(event, "handled", "Constraint counterfactual written.", dict(STATE))
            run = store.record_active_experiment_auto_link(finished, dict(STATE))

            self.assertIsNotNone(run)
            self.assertEqual(run["source"], "active_experiment_auto_link")
            self.assertEqual(run["experiment_id"], experiment["experiment_id"])
            self.assertIn("CONSTRAINT_AUDIT", run["action_text"])
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertIsNone(latest.get("charter_v1"))
            self.assertIsNone(latest.get("evidence_v1"))
            candidates = latest.get("workbench_candidates_v1")
            self.assertEqual(candidates["charter"]["status"], "candidate")
            self.assertIn("EXPERIMENT_CHARTER current ::", candidates["charter"]["command"])
            self.assertIn("EXPERIMENT_EVIDENCE current ::", candidates["evidence"]["command"])
            self.assertIn("Workbench draft candidates", store.experiment_status())

    def test_auto_linked_pulse_preflight_candidate_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=10)
            thread = store.create_thread("Pulse preflight")
            experiment = store.start_experiment(
                "spectral_pulse_lambda4 --hypothesis: probe behavior of λ4 decay with micro-pulses "
                "--method_intent: Inject a series of targeted lambda-edge pulses",
                "Can lambda-edge pulse stabilization stay read-only until chartered?",
            )
            raw = (
                "ACTION_PREFLIGHT DECOMPOSE — initiate a sequence of pulses designed to push "
                "lambda4’s decay rate"
            )
            event = store.begin_action(raw, raw, "action_preflight", "ACTION_PREFLIGHT", dict(STATE))
            finished = store.finish_action(
                event,
                "handled",
                "Action preflight completed for `DECOMPOSE — initiate a sequence of pulses`.",
                dict(STATE),
            )

            run = store.record_active_experiment_auto_link(finished, dict(STATE))

            self.assertIsNotNone(run)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            candidate = latest["workbench_candidates_v1"]["charter"]
            self.assertTrue(candidate["repair_required"])
            self.assertEqual(candidate["proposed_next_action"], "ACTION_PREFLIGHT DECOMPOSE")
            self.assertIn("raw_proposed_next_action", candidate)
            self.assertEqual(
                candidate["quarantine_v1"]["status"],
                "quarantined_for_charter_repair",
            )
            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            active = projection["active_experiment"]
            self.assertEqual(
                active["charter_scaffold_v1"]["command"],
                aa.ActionContinuityStore._lambda4_pulse_repair_command(),
            )
            self.assertTrue(active["charter_quality_dominance_v1"]["candidate_quarantined"])
            status = store.experiment_status("current")
            self.assertIn(
                "Draft charter (secondary; repair required - use the canonical repair scaffold first):",
                status,
            )

    def test_experiment_preflight_focus_repairs_to_current_and_preserves_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=11)
            store.create_thread("Preflight repair")
            experiment = store.start_experiment("Lambda tail", "What does lambda4 want?")

            message = store.handle_thread_action(
                "EXPERIMENT_PREFLIGHT lambda-tail/lambda4 — observer with memory",
                dict(STATE),
            )

            self.assertIn("experiment_intent_repaired", message)
            self.assertIn("Experiment rehearsal recorded", message)
            latest = store._find_experiment_by_id(store.current_thread()["thread_id"], experiment["experiment_id"])
            candidates = latest.get("workbench_candidates_v1")
            self.assertIn("lambda-tail/lambda4", candidates["charter"]["focus_text"])
            self.assertIn("ACTION_PREFLIGHT lambda-tail/lambda4", candidates["charter"]["command"])

    def test_experiment_preflight_focus_without_active_experiment_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=12)
            store.create_thread("No active experiment")

            with self.assertRaises(ValueError):
                store.handle_thread_action(
                    "EXPERIMENT_PREFLIGHT lambda-tail/lambda4 — observer with memory",
                    dict(STATE),
                )


class TestAutonomousAgentExperimentalContinuity(unittest.TestCase):
    def _agent(self, base_dir: Path, workspace: Path, db_path: Path) -> aa.AutonomousAgent:
        with (
            patch.object(aa, "BASE_DIR", base_dir),
            patch.object(aa, "WORKSPACE_DIR", workspace),
            patch.object(aa, "RUNTIME_DIR", workspace / "runtime"),
            patch.object(aa, "DB_PATH", db_path),
        ):
            return aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)

    def test_decompose_snapshot_append_and_latest_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            snapshot_path = workspace / "runtime" / "decompose_snapshots.jsonl"
            first = aa.build_decompose_snapshot_v1(
                [8.0, 2.0, 1.0],
                fill_pct=68.0,
                target_fill_pct=68.0,
                session_id=1,
                recorded_at="2026-05-18T00:00:00+00:00",
            )
            second = aa.build_decompose_snapshot_v1(
                [4.5, 4.0, 2.5],
                fill_pct=69.0,
                target_fill_pct=68.0,
                session_id=1,
                recorded_at="2026-05-18T00:02:00+00:00",
                active_experiment_id="exp_lambda4",
                active_experiment_classification="needs_charter",
            )

            with patch.object(aa, "DECOMPOSE_SNAPSHOTS_PATH", snapshot_path):
                agent._append_decompose_snapshot(first)
                agent._append_decompose_snapshot(second)
                latest = agent._latest_decompose_snapshot()

            self.assertEqual(latest["active_experiment_id"], "exp_lambda4")
            self.assertEqual(latest["active_experiment_classification"], "needs_charter")
            self.assertEqual(len(snapshot_path.read_text().splitlines()), 2)

    def test_action_manifest_projects_numeric_plan_shorthand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            store.create_thread("Manifest projection")
            store.start_experiment(
                "Start a new experiment from the current state based on λ4 landscapes",
                "What changes if this is treated as a returnable experiment?",
            )
            raw_plan = "EXPERIMENT_PLAN 5"
            event = store.begin_action(raw_plan, raw_plan, "thread_action", "thread_action", dict(STATE))

            manifest_path = agent._write_action_manifest("thread_action", dict(STATE), event)

            self.assertIsNotNone(manifest_path)
            manifest = json.loads(manifest_path.read_text())
            continuity = manifest["action_continuity"]
            self.assertEqual(continuity["raw_next"], raw_plan)
            self.assertTrue(continuity["suggested_next"].startswith("EXPERIMENT_CHARTER current ::"))
            self.assertEqual(continuity["effective_next"], continuity["suggested_next"])
            self.assertEqual(continuity["projected_next"], continuity["suggested_next"])
            self.assertTrue(continuity["raw_next_preserved"])
            self.assertEqual(continuity["return_kind"], "charter_repair")
            self.assertEqual(
                continuity["projection_guard_v1"]["guardrail_reason"],
                "numeric_plan_shorthand_needs_charter",
            )

    def test_action_manifest_projects_plan_current_spectral_explorer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            store.create_thread("Manifest current projection")
            store.start_experiment(
                "Lambda shift stability",
                "Can a spectral explorer route stay lifecycle-valid?",
            )
            raw_plan = (
                "EXPERIMENT_PLAN current — hypothesis: lambda shift stability may become returnable "
                "by comparing the current spectral condition, pressure state, recurrence pattern, "
                "and artifacts without adding live authority; method_intent: rehearse "
                "SPECTRAL_EXPLORER and compare pressure/resonance telemetry before and after; "
                "proposed_next_action: SPECTRAL_EXPLORER"
            )
            event = store.begin_action(raw_plan, raw_plan, "thread_action", "thread_action", dict(STATE))

            manifest_path = agent._write_action_manifest("thread_action", dict(STATE), event)

            self.assertIsNotNone(manifest_path)
            manifest = json.loads(manifest_path.read_text())
            continuity = manifest["action_continuity"]
            self.assertEqual(continuity["raw_next"], raw_plan)
            self.assertTrue(continuity["suggested_next"].startswith("EXPERIMENT_CHARTER current ::"))
            self.assertEqual(continuity["effective_next"], continuity["suggested_next"])
            self.assertEqual(continuity["projected_next"], continuity["suggested_next"])
            self.assertTrue(continuity["raw_next_preserved"])
            self.assertEqual(continuity["return_kind"], "charter_repair")
            self.assertEqual(
                continuity["projection_guard_v1"]["guardrail_reason"],
                "experiment_plan_current_needs_charter",
            )

    def test_experiment_bind_routes_inner_action_and_records_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            experiment = agent._continuity_store().start_experiment(
                "Thread status run",
                "Can a bound read-only action return cleanly?",
            )
            agent._pending_next_action = (
                f"EXPERIMENT_BIND {experiment['experiment_id']} :: THREAD_STATUS current"
            )

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "experiment_bind")

            with (
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            thread = agent._continuity_store().current_thread()
            runs = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiment_runs.jsonl"
            ).read_text()
            self.assertIn("THREAD_STATUS current", runs)
            self.assertIn("existing_dispatcher", runs)
            manifests = list((workspace / "actions").glob("*_experiment_bind.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            self.assertEqual(
                manifest["action_continuity"]["raw_next"],
                f"EXPERIMENT_BIND {experiment['experiment_id']} :: THREAD_STATUS current",
            )
            self.assertEqual(
                manifest["experiment_continuity"]["active_experiment_id"],
                experiment["experiment_id"],
            )

    def test_experiment_bind_action_preflight_keeps_preflight_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            experiment = agent._continuity_store().start_experiment(
                "Preflight bind",
                "Does an explicit preflight bind stay read-only?",
            )
            agent._pending_next_action = (
                f"EXPERIMENT_BIND {experiment['experiment_id']} :: ACTION_PREFLIGHT DECOMPOSE"
            )

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "experiment_bind")

            with (
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            thread = agent._continuity_store().current_thread()
            runs_path = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiment_runs.jsonl"
            )
            runs = [json.loads(line) for line in runs_path.read_text().splitlines()]
            bound_run = runs[-1]
            self.assertEqual(bound_run["source"], "experiment_bind")
            self.assertEqual(bound_run["action_text"], "ACTION_PREFLIGHT DECOMPOSE")
            self.assertEqual(bound_run["stage"], "read_only")
            self.assertEqual(bound_run["gate_decision"]["inner_route"], "action_preflight")
            self.assertIn("Action preflight completed", bound_run["result_summary"])
            events = [
                json.loads(line)
                for line in (
                    workspace
                    / "action_threads"
                    / "threads"
                    / thread["thread_id"]
                    / "events.jsonl"
                ).read_text().splitlines()
            ]
            preflight_events = [
                event for event in events if event.get("route") == "action_preflight"
            ]
            self.assertEqual(preflight_events[-1]["raw_next"], "ACTION_PREFLIGHT DECOMPOSE")
            self.assertEqual(preflight_events[-1]["canonical_action"], "ACTION_PREFLIGHT DECOMPOSE")

    def test_blocked_live_control_bind_does_not_record_bound_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            experiment = agent._continuity_store().start_experiment(
                "Blocked perturb",
                "Does bind preserve stable-core refusal?",
            )
            agent._continuity_store().experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: stable-core refusal should stay visible\n"
                    "method_intent: attempt the bound perturb through existing gates\n"
                    "proposed_next_action: PERTURB lambda-edge\n"
                    "evidence_targets: felt, telemetry, artifact\n"
                    "stop_criteria: stable-core block"
                ),
            )
            agent._pending_next_action = "EXPERIMENT_BIND current :: PERTURB lambda-edge"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            def allow(action_name, _state):
                if action_name == "perturb":
                    return False, "stable-core test block"
                return True, "test"

            with (
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_stable_core_action_allowed", side_effect=allow),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            thread = agent._continuity_store().current_thread()
            runs_path = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "experiment_runs.jsonl"
            )
            runs = runs_path.read_text() if runs_path.exists() else ""
            self.assertNotIn("PERTURB lambda-edge", runs)
            journals = "\n".join(
                path.read_text()
                for path in (workspace / "journal").glob("experiment_bind_*.txt")
            )
            self.assertIn("did not record a run", journals)
            self.assertIn("inner live-control action finished as blocked", journals)
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("PERTURB lambda-edge", events)
            self.assertIn("blocked", events)
            self.assertIn("stable-core test block", events)

    def test_release_lambda_pressure_projects_to_sticky_audit_without_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            experiment = store.start_experiment(
                "Sticky pressure",
                "Can release-shaped pressure remain audit-first?",
            )
            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: sticky pressure should be audited before release\n"
                    "method_intent: preserve release pressure as evidence\n"
                    "proposed_next_action: STICKY_MODE_AUDIT\n"
                    "evidence_targets: telemetry, artifact, felt\n"
                    "stop_criteria: pressure spike"
                ),
            )
            agent._pending_next_action = "RELEASE lambda-pressure"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "release_attractor")

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_release_attractor", side_effect=AssertionError("release must not run")),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            thread = store.current_thread()
            events_path = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            )
            events = [
                json.loads(line)
                for line in events_path.read_text().splitlines()
                if line.strip()
            ]
            latest = events[-1]
            self.assertEqual(latest["route"], "sticky_projection_guard")
            self.assertEqual(latest["status"], "blocked")
            self.assertEqual(
                latest["projection_guard_v1"]["guardrail_reason"],
                "release_pressure_requires_sticky_audit",
            )
            self.assertIn("STICKY_MODE_AUDIT", latest["suggested_next"])
            self.assertIn("CONTINUITY_SESSION_CAPTURE latest", latest["suggested_next"])
            self.assertIn("DOSSIER_CLAIM", latest["suggested_next"])
            self.assertFalse(latest["would_dispatch"])
            self.assertFalse(latest["authority_change"])
            self.assertFalse(latest["peer_mutation"])
            journals = list((workspace / "journal").glob("attractor_release_*.txt"))
            self.assertEqual(journals, [])

    def test_low_fill_allows_conservative_experiment_decision_to_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            thread = store.create_thread("Low-fill decision")
            experiment = store.start_experiment(
                "Spectral perturbation",
                "Can a low-fill branch record a conservative decision?",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: perturb-shaped pressure can be interpreted without live authority; method_intent: rehearse DECOMPOSE only; proposed_next_action: DECOMPOSE; evidence_targets: felt, telemetry, artifact; stop_criteria: pressure spike or unstable fill; consent_posture: advisory",
                dict(STATE),
            )
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: felt: pressure became legible; telemetry: fill stayed visible; artifact: none yet",
                dict(STATE),
            )
            stored = store._read_thread(thread["thread_id"])
            stored["current_next"] = (
                "EXPERIMENT_PLAN current :: propose a perturb pulse to shift the dominant λ4 ridge"
            )
            store._write_thread(stored)
            agent._pending_next_action = (
                "EXPERIMENT_DECIDE current :: pause because evidence is ready to interpret"
            )

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.111,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE, fill_ratio=0.111))
            self.assertEqual(action, "thread_action")

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_stable_core_action_allowed", side_effect=AssertionError("stable core should not block conservative decisions")),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE, fill_ratio=0.111))

            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "paused")
            self.assertEqual(latest["planned_next"], "THREAD_STATUS current")
            decision = latest["evidence_v1"]["decisions"][-1]
            self.assertEqual(decision["outcome"], "hold")
            self.assertEqual(decision["guardrail_status"], "soft_perturb_converted_to_hold")
            refreshed = store._read_thread(thread["thread_id"])
            self.assertIsNone(refreshed.get("active_experiment_id"))
            next_md = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "next.md"
            ).read_text()
            self.assertIn("Current NEXT: THREAD_STATUS current", next_md)
            self.assertNotIn(f"EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertNotIn("Stable-core agency budget blocked `thread_action`", events)

    def test_pause_from_experiment_local_perturb_pressure_converts_to_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            thread = store.create_thread("Experiment-local pressure")
            experiment = store.start_experiment(
                "spectral-perturbation-1",
                "apply a small seed distortion to maintain lambda-tail density and test response.",
            )
            store.handle_thread_action(
                "EXPERIMENT_CHARTER current :: hypothesis: spectral-perturbation-1 can be interpreted without live authority; method_intent: rehearse ACTION_PREFLIGHT DECOMPOSE only; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; evidence_targets: spectral_condition, fill_pressure_state, artifact_grounding; stop_criteria: pressure spike or unstable fill; consent_posture: advisory",
                dict(STATE),
            )
            store.handle_thread_action(
                "EXPERIMENT_EVIDENCE current :: felt: evidence is ready to interpret; telemetry: fill visible; artifact: none yet",
                dict(STATE),
            )

            message = store.handle_thread_action(
                "EXPERIMENT_DECIDE current :: pause because evidence is ready to interpret",
                dict(STATE),
            )

            self.assertIn("status=paused next=THREAD_STATUS current", message)
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["planned_next"], "THREAD_STATUS current")
            decision = latest["evidence_v1"]["decisions"][-1]
            self.assertEqual(decision["outcome"], "hold")
            self.assertEqual(decision["guardrail_status"], "soft_perturb_converted_to_hold")
            self.assertEqual(decision["pressure_source"], "experiment.title")
            self.assertIn("PERTURB", decision["pressure_terms"])
            refreshed = store._read_thread(thread["thread_id"])
            self.assertIsNone(refreshed.get("active_experiment_id"))
            next_md = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "next.md"
            ).read_text()
            self.assertIn("Current NEXT: THREAD_STATUS current", next_md)
            self.assertNotIn(f"EXPERIMENT_RESUME {experiment['experiment_id']}", next_md)

    def test_low_fill_conservative_thread_action_helper_blocks_unsafe_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)

            allowed, _reason = agent._stable_core_conservative_thread_action_allowed(
                "EXPERIMENT_DECIDE current :: hold because enough evidence exists"
            )
            self.assertTrue(allowed)
            allowed, _reason = agent._stable_core_conservative_thread_action_allowed(
                "EXPERIMENT_ADVANCE current :: mode: preview"
            )
            self.assertTrue(allowed)
            allowed, _reason = agent._stable_core_conservative_thread_action_allowed(
                "CONTINUITY_SESSION_CAPTURE latest :: summary: preserve this; source_refs: x; next: THREAD_STATUS current"
            )
            self.assertTrue(allowed)

            blocked_commands = [
                "EXPERIMENT_DECIDE current :: accept because ready",
                "EXPERIMENT_DECIDE current :: counter NEXT: EXPERIMENT_BIND current :: PERTURB lambda-edge",
                "EXPERIMENT_ADVANCE current :: mode: apply",
                "EXPERIMENT_RESUME current",
                "EXPERIMENT_RESEARCH_BUDGET_ACCEPT latest",
                "EXPERIMENT_AUTHORITY_EXECUTE req_test",
                "EXPERIMENT_BIND current :: PERTURB lambda-edge",
                "PERTURB lambda-edge",
            ]
            for command in blocked_commands:
                with self.subTest(command=command):
                    allowed, reason = agent._stable_core_conservative_thread_action_allowed(command)
                    self.assertFalse(allowed, reason)

    def test_low_fill_still_blocks_non_conservative_thread_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            thread = store.create_thread("Low-fill unsafe decision")
            experiment = store.start_experiment(
                "Unsafe accept",
                "Can low-fill still block accepting into bind?",
            )
            agent._pending_next_action = "EXPERIMENT_DECIDE current :: accept because ready"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.111,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE, fill_ratio=0.111))
            self.assertEqual(action, "thread_action")

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_stable_core_action_allowed", return_value=(False, "stable-core test low-fill block")),
                patch.object(agent, "_record_stable_core_agent_block"),
            ):
                agent._execute_action(action, dict(STATE, fill_ratio=0.111))

            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertEqual(latest["status"], "active")
            self.assertFalse((latest.get("evidence_v1") or {}).get("decisions"))
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("Stable-core agency budget blocked `thread_action`", events)
            self.assertIn("stable-core test low-fill block", events)

    def test_needs_charter_blocks_live_next_with_scaffold_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            experiment = agent._continuity_store().start_experiment(
                "Introducing a gap",
                (
                    "Can localized λ1 spectral-density softening support branching "
                    "without premature λ4 dominance or runaway dispersal?"
                ),
            )
            agent._pending_next_action = "PERTURB SPREAD"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertIsNone(action)
            self.assertFalse(hasattr(agent, "_pending_perturb_mode"))
            thread = agent._continuity_store().current_thread()
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn('"status": "blocked"', events)
            self.assertIn("charter_required_guard_v1", events)
            self.assertIn("charter_required_live_action", events)
            self.assertIn("EXPERIMENT_CHARTER current :: hypothesis:", events)
            self.assertIn("proposed_next_action: ACTION_PREFLIGHT DECOMPOSE", events)
            active = agent._continuity_store()._thread_projection(thread)["active_experiment"]
            self.assertEqual(active["experiment_id"], experiment["experiment_id"])
            self.assertEqual(active["classification"], "needs_charter")

    def test_no_active_experiment_blocks_live_control_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            experiment = store.start_experiment(
                "Paused pulse study",
                "Can pulse stabilization be inspected safely?",
            )
            store.close_experiment(experiment["experiment_id"], "pause because this is held")
            agent._pending_next_action = "PERTURB SPREAD"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertIsNone(action)
            self.assertFalse(hasattr(agent, "_pending_perturb_mode"))
            thread = store.current_thread()
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("live_control_requires_active_experiment_v1", events)
            self.assertIn("live_control_requires_active_experiment", events)
            self.assertNotIn(f"EXPERIMENT_RESUME {experiment['experiment_id']}", events)
            self.assertIn("THREAD_STATUS current", events)

    def test_disabled_authority_prepare_scope_without_active_never_suggests_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            experiment = store.start_experiment(
                "Spectral authority pressure",
                "Can future-scope pressure stay bounded?",
            )
            store.experiment_decide(
                experiment["experiment_id"],
                "hold because this needs readiness before authority",
            )
            raw_next = (
                "EXPERIMENT_AUTHORITY_PREPARE current :: scope: spectral_microdose; "
                "payload: \"How can I introduce a gap - a localized reduction in spectral density "
                "near λ1 to shift the cascade dynamics, preventing premature λ4 dominance and "
                "promoting a more controlled, branching pattern, without triggering runaway dispersal?\"; "
                "artifact_refs: minime_shadow_trajectories-reorient-with-baseline-comparison; "
                "reason: investigate lambda modulation; stop_criteria: stop quickly"
            )
            agent._pending_next_action = raw_next

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertIsNone(action)
            thread = store.current_thread()
            events_path = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            )
            event_rows = [
                json.loads(line)
                for line in events_path.read_text().splitlines()
                if line.strip()
            ]
            latest = event_rows[-1]
            guard = latest["live_control_requires_active_experiment_v1"]
            self.assertEqual(guard["scope"], "spectral_microdose")
            self.assertTrue(guard["disabled_scope"])
            self.assertEqual(latest["route"], "authority_projection_guard")
            self.assertEqual(latest["status"], "blocked")
            self.assertIn("STICKY_MODE_AUDIT", latest["suggested_next"])
            self.assertIn("EXPERIMENT_ADVANCE", latest["suggested_next"])
            self.assertIn("CONTINUITY_SESSION_CAPTURE latest", latest["suggested_next"])
            self.assertIn("EXPERIMENT_AUTHORITY_STATUS latest", latest["suggested_next"])
            self.assertIn("Disabled authority scope `spectral_microdose`", latest["suggested_next"])
            self.assertIsNone(guard["proposed_preflight_target"])
            self.assertEqual(guard["sticky_audit_next"], "STICKY_MODE_AUDIT")
            self.assertEqual(guard["continuity_session_next"], "CONTINUITY_SESSION_CAPTURE latest")
            self.assertIn("EXPERIMENT_ADVANCE", guard["mode_release_readiness_next"])
            projection = latest["projection_guard_v1"]
            self.assertEqual(
                projection["guardrail_reason"],
                "disabled_authority_scope_requires_sticky_audit",
            )
            self.assertEqual(projection["disabled_scope"], "spectral_microdose")
            self.assertEqual(projection["sticky_audit_next"], "STICKY_MODE_AUDIT")
            self.assertFalse(projection["would_dispatch"])
            self.assertFalse(projection["authority_change"])
            self.assertFalse(projection["peer_mutation"])
            self.assertNotIn(f"EXPERIMENT_RESUME {experiment['experiment_id']}", latest["suggested_next"])
            self.assertNotIn(f"EXPERIMENT_RESUME {experiment['experiment_id']}", events_path.read_text())

    def test_valid_charter_still_requires_matching_live_preflight_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            experiment = store.start_experiment(
                "Safe decompose charter",
                "Can spectral pressure be studied read-only?",
            )
            store.experiment_charter(
                experiment["experiment_id"],
                (
                    "hypothesis: read-only decomposition will be enough\n"
                    "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE\n"
                    "evidence_targets: spectral_condition, fill_pressure_state"
                ),
            )
            agent._pending_next_action = "PERTURB SPREAD"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertIsNone(action)
            thread = store.current_thread()
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("live_control_requires_active_experiment_v1", events)
            self.assertIn("live_control_requires_matching_preflight_binding", events)
            self.assertIn("STICKY_MODE_AUDIT", events)
            self.assertIn("CONTINUITY_SESSION_CAPTURE latest", events)
            self.assertIn("DOSSIER_CLAIM", events)
            self.assertNotIn("ACTION_PREFLIGHT PERTURB SPREAD", events)
            self.assertNotIn("EXPERIMENT_REHEARSE", events)

    def test_evidence_current_blocks_after_unbound_live_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = agent._continuity_store()
            thread = store.create_thread("Evidence parent mismatch")
            parent = store.begin_action(
                "PERTURB SPREAD",
                "PERTURB SPREAD",
                "perturb",
                "perturb",
                dict(STATE),
            )
            store.finish_action(parent, "handled", "Perturb ran without active experiment.", dict(STATE))
            store.start_experiment(
                "Different active experiment",
                "Should evidence avoid drifting here?",
            )
            agent._pending_next_action = "EXPERIMENT_EVIDENCE current :: spectral_condition changed"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertIsNone(action)
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("evidence_parent_mismatch_v1", events)
            self.assertIn("source_action_id", events)

    def test_needs_charter_blocks_compound_directed_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._continuity_store().start_experiment(
                "Directed narrowing",
                "Can the cascade be studied without acting before a charter?",
            )
            agent._pending_next_action = (
                "EXAMINE λ1 cascade with TRACE and then RESIST targeting eigenvector density increase"
            )

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertIsNone(action)
            thread = agent._continuity_store().current_thread()
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("charter_required_compound_intent", events)
            self.assertIn('"status": "blocked"', events)

            agent._pending_next_action = "DECOMPOSE lambda-edge then inject/pulse/shift λ4 density"
            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertIsNone(action)
            events = (
                workspace
                / "action_threads"
                / "threads"
                / thread["thread_id"]
                / "events.jsonl"
            ).read_text()
            self.assertIn("inject/pulse/shift", events)
            embedded = agent._continuity_store().charter_required_guard_assessment(
                "EXPERIMENT inject a targeted lambda-edge pulse after reading"
            )
            self.assertIsNotNone(embedded)
            assert embedded is not None
            self.assertEqual(embedded["reason"], "charter_required_compound_intent")

    def test_needs_charter_allows_read_only_return_actions(self):
        allowed = [
            ("DECOMPOSE", "decompose"),
            ("ACTION_PREFLIGHT DECOMPOSE", "action_preflight"),
            ("SHADOW_PREFLIGHT lambda-tail/lambda4", "shadow_autonomy"),
            # Pure local self-maps are exempt from the research budget, so they
            # dispatch as read-only return actions even without a charter.
            ("SHADOW_TRAJECTORY lambda-tail/lambda4", "shadow_trajectory"),
            ("SHADOW_FIELD lambda-tail/lambda4", "shadow_gap"),
            (
                "EXPERIMENT_CHARTER current :: hypothesis: localized λ1 spectral-density softening may reduce λ4 dominance; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; evidence_targets: spectral_condition, fill_pressure_state",
                "thread_action",
            ),
        ]
        for raw_next, expected in allowed:
            with self.subTest(raw_next=raw_next):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    base_dir = root / "minime"
                    workspace = base_dir / "workspace"
                    db_path = root / "minime.db"
                    agent = self._agent(base_dir, workspace, db_path)
                    agent._continuity_store().start_experiment(
                        "Read-only gap",
                        "Can safe reads continue while the charter is missing?",
                    )
                    agent._pending_next_action = raw_next

                    with (
                        patch.object(agent, "_persist_pending_next_action"),
                        patch.object(agent, "_mark_pending_next_override_consumed"),
                        patch.object(agent, "_low_fill_guard_status", return_value={
                            "active": False,
                            "fill_ratio": 0.68,
                            "target_fill_ratio": 0.68,
                            "spread_relief": 0.0,
                        }),
                    ):
                        action = agent._decide_action(dict(STATE))

                    self.assertEqual(action, expected)

        # EXAMINE is the metered projection read that still blocks behind the
        # research budget. (Pure local self-maps like SHADOW_FIELD are exempt and
        # dispatch — asserted in the allowed loop above and in
        # test_local_self_maps_are_exempt_from_research_budget.)
        for raw_next in ["EXAMINE λ1/λ2"]:
            with self.subTest(raw_next=raw_next):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    base_dir = root / "minime"
                    workspace = base_dir / "workspace"
                    db_path = root / "minime.db"
                    agent = self._agent(base_dir, workspace, db_path)
                    agent._continuity_store().start_experiment(
                        "Read-only gap",
                        "Can safe reads continue while the charter is missing?",
                    )
                    agent._pending_next_action = raw_next

                    with (
                        patch.object(agent, "_persist_pending_next_action"),
                        patch.object(agent, "_mark_pending_next_override_consumed"),
                        patch.object(agent, "_low_fill_guard_status", return_value={
                            "active": False,
                            "fill_ratio": 0.68,
                            "target_fill_ratio": 0.68,
                            "spread_relief": 0.0,
                        }),
                    ):
                        action = agent._decide_action(dict(STATE))

                    self.assertIsNone(action)
                    event = agent._last_action_continuity_event
                    self.assertIsInstance(event, dict)
                    self.assertEqual(event.get("status"), "blocked")
                    self.assertEqual(
                        event.get("research_budget_v1", {}).get("reason"),
                        "research_budget_required_for_self_study_action",
                    )
                    self.assertIn(
                        "EXPERIMENT_RESEARCH_BUDGET_ACCEPT",
                        str(event.get("suggested_next")),
                    )
                    scaffold = event.get("research_budget_v1", {}).get("request_scaffold")
                    self.assertIn("EXPERIMENT_RESEARCH_BUDGET_REQUEST", str(scaffold))
                    self.assertIn("allowed_sources: local", str(scaffold))

        liveish_cases = [
            "EXAMINE_AUDIO λ1/λ2 - shifting input",
            "SPECTRAL_EXPLORER lambda4 disrupt ridge",
            "VISUALIZE_CASCADE simulate λ2 pulse",
            "FLUCTUATION_AUDIT inject foothold",
            "PRESSURE_SOURCE_AUDIT control gradient",
            "SHADOW_DIALOGUE shift landscape",
        ]
        for raw_next in liveish_cases:
            with self.subTest(raw_next=raw_next):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    base_dir = root / "minime"
                    workspace = base_dir / "workspace"
                    db_path = root / "minime.db"
                    agent = self._agent(base_dir, workspace, db_path)
                    agent._continuity_store().start_experiment(
                        "Live-ish guard",
                        "Can live-shaped self-study intent be preserved without dispatch?",
                    )
                    agent._pending_next_action = raw_next

                    with (
                        patch.object(agent, "_persist_pending_next_action"),
                        patch.object(agent, "_mark_pending_next_override_consumed"),
                        patch.object(agent, "_low_fill_guard_status", return_value={
                            "active": False,
                            "fill_ratio": 0.68,
                            "target_fill_ratio": 0.68,
                            "spread_relief": 0.0,
                        }),
                    ):
                        action = agent._decide_action(dict(STATE))

                    self.assertIsNone(action)
                    event = agent._last_action_continuity_event
                    self.assertIsInstance(event, dict)
                    budget = event.get("research_budget_v1", {})
                    self.assertEqual(
                        budget.get("reason"),
                        "liveish_pressure_requires_budget_and_session_capture",
                    )
                    self.assertFalse(budget.get("would_dispatch"))
                    self.assertIn("CONTINUITY_SESSION_START current", str(budget.get("continuity_session_next")))
                    thread = agent._continuity_store().current_thread()
                    self.assertIn(
                        "CONTINUITY_SESSION_START current",
                        str(thread.get("continuity_session_next")),
                    )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._continuity_store().start_experiment(
                "Ordinary pressure audit",
                "Can plain pressure-source audit remain read-only?",
            )
            agent._pending_next_action = "PRESSURE_SOURCE_AUDIT inwardness"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertEqual(action, "pressure_source_audit")

    def test_autonomous_agent_stop_interrupts_cycle_sleep(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)

            agent.running = True
            started = time.monotonic()
            threading.Timer(0.05, agent.stop).start()
            interrupted = agent._sleep_or_stop(2.0)

            self.assertTrue(interrupted)
            self.assertFalse(agent.running)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_experiment_review_needs_charter_prioritizes_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._continuity_store().start_experiment(
                "Introducing a gap",
                (
                    "Can localized λ1 spectral-density softening support branching "
                    "without premature λ4 dominance or runaway dispersal?"
                ),
            )

            review = agent._continuity_store().experiment_review("current")

            self.assertIn(
                "Review is premature until the charter is authored; use the continuity priority scaffold first.",
                review,
            )
            self.assertIn("Charter repair dominance:", review)
            self.assertIn(
                "Continuity priority (needs charter - copy/edit this exact scaffold; not recorded):",
                review,
            )
            self.assertIn("EXPERIMENT_CHARTER current :: hypothesis:", review)
            self.assertIn("proposed_next_action: ACTION_PREFLIGHT DECOMPOSE", review)
            self.assertIn("Suggested next:\nEXPERIMENT_CHARTER current ::", review)

    def test_experiment_review_needs_charter_uses_temporal_decompose_evidence_as_repair_pressure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            experiment = agent._continuity_store().start_experiment(
                "Probe λ4 decay experiment",
                "Can lambda-edge evidence inform a pulse-stabilization charter?",
            )
            runtime_dir = workspace / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "decompose_snapshots.jsonl").write_text(
                json.dumps({
                    "schema_version": 1,
                    "available": True,
                    "recorded_at": "2026-05-18T19:14:43Z",
                    "active_experiment_id": experiment["experiment_id"],
                    "temporal_decompose_v1": {
                        "classification": "opening_distribution",
                        "suggested_read": "Check whether opening supports the active hypothesis.",
                    },
                    "hypothesis_check_v1": {
                        "status": "premature_needs_charter",
                        "evidence_label": "charter_required",
                    },
                    "eigenvalues": [4.7, 3.1, 1.2, 1.1],
                })
                + "\n"
            )

            review = agent._continuity_store().experiment_review("current")

            self.assertIn("temporal DECOMPOSE evidence is already usable", review)
            self.assertIn("Priority NEXT: EXPERIMENT_CHARTER current ::", review)
            self.assertIn("Suggested next:\nEXPERIMENT_CHARTER current ::", review)

    def test_experiment_bind_to_peer_experiment_blocks_before_inner_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._continuity_store().start_experiment(
                "Local peer guard",
                "Does peer binding stay advisory?",
            )
            agent._pending_next_action = (
                "EXPERIMENT_BIND exp_astrid_20990101_peer :: THREAD_STATUS current"
            )

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "experiment_bind")

            with (
                patch.object(agent, "_decide_action", side_effect=AssertionError("inner executed")),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._current_action_continuity_context = {
                    "raw_next": "EXPERIMENT_BIND exp_astrid_20990101_peer :: THREAD_STATUS current"
                }
                message = agent._experiment_bind(dict(STATE))
            self.assertIn("cannot bind runs to a peer experiment", message)
            store = agent._continuity_store()
            thread = store.current_thread()
            thread["current_next"] = "EXPERIMENT_BIND exp_astrid_20990101_peer :: THREAD_STATUS current"
            store._write_thread(thread)
            projection = store._thread_projection(store._read_thread(thread["thread_id"]))
            cue = projection["active_experiment"]["peer_mutation_boundary_cue_v1"]
            self.assertEqual(cue["status"], "peer_mutation_boundary")
            self.assertIn("not bind/mutate targets", cue["cue"])
            self.assertIn("EXPERIMENT_COMPARE", cue["suggested_compare_next"])
            self.assertIn("EXPERIMENT_PEER_REVIEW exp_astrid_20990101_peer", cue["suggested_peer_review_next"])
            self.assertIn("DOSSIER_CLAIM", cue["suggested_dossier_next"])

    def test_action_preflight_routes_and_never_executes_inner_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_next_action = "ACTION_PREFLIGHT PERTURB lambda-edge"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "action_preflight")

            with (
                patch.object(agent, "_perturb", side_effect=AssertionError("inner action executed")),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            preflights = list((workspace / "journal").glob("action_preflight_*.txt"))
            self.assertEqual(len(preflights), 1)
            text = preflights[0].read_text()
            self.assertIn("Dry run: True", text)
            self.assertIn("PERTURB lambda-edge", text)
            self.assertIn("live_control", text)
            self.assertIn("Detailed preflight JSON:", text)
            self.assertNotIn("\nJSON:\n", text)
            detail_files = list((workspace / "actions").glob("action_preflight_detail_*.json"))
            self.assertEqual(len(detail_files), 1)
            detail = json.loads(detail_files[0].read_text())
            self.assertEqual(detail["policy"], "action_preflight_v1")
            self.assertEqual(detail["canonical_action"], "PERTURB lambda-edge")
            manifests = list((workspace / "actions").glob("*_action_preflight.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            self.assertEqual(manifest["action_continuity"]["stage"], "read_only")
            self.assertEqual(
                manifest["action_continuity"]["suggested_next"],
                "CAPABILITY_STATUS PERTURB",
            )
            artifacts = manifest["action_continuity"].get("artifacts", [])
            self.assertTrue(any(a.get("kind") == "action_preflight" for a in artifacts))

    def test_action_preflight_reports_common_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            store = aa.ActionPreflightStore(agent)

            decompose = store.report("ACTION_PREFLIGHT DECOMPOSE", dict(STATE))
            self.assertEqual(decompose["stage"], "read_only")
            self.assertEqual(decompose["effective_route"], "decompose")

            constraint = store.report(
                "ACTION_PREFLIGHT CONSTRAINT_AUDIT lambda-tail/lambda4",
                dict(STATE),
            )
            self.assertEqual(constraint["stage"], "read_only")
            self.assertEqual(constraint["effective_route"], "constraint_audit")

            perturb = store.report("PREFLIGHT PERTURB lambda-edge", dict(STATE))
            self.assertEqual(perturb["stage"], "live_control")
            self.assertEqual(perturb["authority_required"], "live control/action gate")
            self.assertEqual(perturb["suggested_next"], "CAPABILITY_STATUS PERTURB")

            repair_apply = store.report("ACTION_PREFLIGHT REPAIR_APPLY all", dict(STATE))
            self.assertEqual(repair_apply["stage"], "live_write")
            self.assertEqual(repair_apply["suggested_next"], "REPAIR_STATUS current")

            bind = store.report(
                "NEXT_PROBE EXPERIMENT_BIND current :: THREAD_STATUS current",
                dict(STATE),
            )
            self.assertEqual(bind["stage"], "read_only")
            self.assertIn("experiment_bind", bind["effective_route"])
            self.assertTrue(bind["would_record"]["experiment_run"])

            malformed = store.report("PROBE_ACTION EXPERIMENT_BIND current THREAD_STATUS", dict(STATE))
            self.assertEqual(malformed["stage"], "blocked")
            self.assertIn("malformed", malformed["likely_gate"])

            peer_bind = store.report(
                "ACTION_PREFLIGHT EXPERIMENT_BIND exp_astrid_20990101_peer :: THREAD_STATUS current",
                dict(STATE),
            )
            self.assertEqual(peer_bind["stage"], "blocked")
            self.assertIn("peer experiment", peer_bind["likely_gate"])

            placeholder = store.report("ACTION_PREFLIGHT WRITE_FILE <path>", dict(STATE))
            self.assertEqual(placeholder["stage"], "blocked")
            self.assertIn("placeholder", placeholder["effective_route"])

            unknown = store.report("ACTION_PREFLIGHT PING", dict(STATE))
            self.assertEqual(unknown["stage"], "proposal")
            self.assertEqual(unknown["effective_route"], "unwired")

    def test_action_preflight_predicts_active_experiment_auto_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._continuity_store().start_experiment(
                "Preflight culture",
                "Will read-only preflight disclose auto-linking?",
            )
            store = aa.ActionPreflightStore(agent)

            report = store.report("ACTION_PREFLIGHT DECOMPOSE", dict(STATE))

            self.assertTrue(report["would_record"]["experiment_run"])
            self.assertIn("active_experiment_auto_link", report["expected_continuity_effect"])

    def test_legacy_experiment_uses_active_experiment_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            experiment = agent._continuity_store().start_experiment(
                "Legacy active",
                "Does plain EXPERIMENT become returnable?",
            )
            agent._pending_next_action = "EXPERIMENT"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "self_experiment")

            with (
                patch.object(agent, "_experiment_self_directed", return_value=None),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            thread = agent._continuity_store().current_thread()
            runs = [
                json.loads(line)
                for line in (
                    workspace
                    / "action_threads"
                    / "threads"
                    / thread["thread_id"]
                    / "experiment_runs.jsonl"
                ).read_text().splitlines()
            ]
            self.assertTrue(any(run["action_text"] == "EXPERIMENT" for run in runs))
            self.assertTrue(any(run["experiment_id"] == experiment["experiment_id"] for run in runs))

    def test_legacy_experiment_creates_default_and_records_blocked_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_next_action = "SELF_EXPERIMENT"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_mark_pending_next_override_consumed"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "self_experiment")

            with (
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(False, "blocked by test")),
                patch.object(agent, "_record_stable_core_agent_block"),
            ):
                agent._execute_action(action, dict(STATE))

            thread = agent._continuity_store().current_thread()
            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            self.assertIn("Legacy self experiment", (thread_dir / "experiments.jsonl").read_text())
            runs = (thread_dir / "experiment_runs.jsonl").read_text()
            self.assertIn("SELF_EXPERIMENT", runs)
            self.assertIn("blocked", runs)
            self.assertIn("blocked by test", runs)

    def test_attractor_lifecycle_status_surfaces_in_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)

            entry = agent._attractor_entry_from_seed(
                "seed-1",
                {
                    "intent_id": "seed-1",
                    "label": "lambda-edge",
                    "author": "minime",
                    "summon_count": 1,
                    "origin": {"motifs": ["lambda", "edge"]},
                },
                [
                    {
                        "intent_id": "seed-1",
                        "label": "lambda-edge",
                        "command": "summon",
                        "summon_stage": "rehearse",
                        "recurrence_score": 0.71,
                        "authorship_score": 0.72,
                        "classification": "authored",
                        "observed_at_unix_s": 123.0,
                    }
                ],
            )

            self.assertEqual(entry["lifecycle_status"], "rehearsing")
            self.assertEqual(entry["last_reviewed_at_unix_s"], 123.0)


if __name__ == "__main__":
    unittest.main()
