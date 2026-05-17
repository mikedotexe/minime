"""Tests for being-owned experimental continuity."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa


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
            self.assertIn(
                f"EXPERIMENT_BIND {experiment['experiment_id']} :: ACTION_PREFLIGHT DECOMPOSE",
                text,
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
                status = store._format_thread_status(store._read_thread(thread["thread_id"]))

            self.assertFalse(cue["authority_change"])
            self.assertEqual(cue["peer_experiment_id"], astrid_exp["experiment_id"])
            self.assertIn("EXPERIMENT_COMPARE current WITH exp_astrid", cue["suggested_next"])
            self.assertIn("Peer convergence cue", status)

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
                "DECOMPOSE",
                "DECOMPOSE",
                "decompose",
                "decompose",
                dict(STATE),
            )
            finished = store.finish_action(event, "handled", "Decomposition written.", dict(STATE))
            run = store.record_active_experiment_auto_link(finished, dict(STATE))

            self.assertIsNotNone(run)
            self.assertEqual(run["source"], "active_experiment_auto_link")
            self.assertEqual(run["experiment_id"], experiment["experiment_id"])
            self.assertIn("DECOMPOSE", run["action_text"])
            latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
            self.assertIsNone(latest.get("charter_v1"))
            self.assertIsNone(latest.get("evidence_v1"))
            candidates = latest.get("workbench_candidates_v1")
            self.assertEqual(candidates["charter"]["status"], "candidate")
            self.assertIn("EXPERIMENT_CHARTER current ::", candidates["charter"]["command"])
            self.assertIn("EXPERIMENT_EVIDENCE current ::", candidates["evidence"]["command"])
            self.assertIn("Workbench draft candidates", store.experiment_status())

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

    def test_blocked_inner_action_becomes_blocked_experiment_run(self):
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
                patch.object(agent, "_stable_core_action_allowed", side_effect=allow),
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
            self.assertIn("PERTURB lambda-edge", runs)
            self.assertIn("blocked", runs)
            self.assertIn("stable-core test block", runs)

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

    def test_needs_charter_allows_read_only_return_actions(self):
        allowed = [
            ("EXAMINE λ1/λ2", "decompose"),
            ("DECOMPOSE", "decompose"),
            ("ACTION_PREFLIGHT DECOMPOSE", "action_preflight"),
            ("SHADOW_PREFLIGHT lambda-tail/lambda4", "shadow_autonomy"),
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
            self.assertIn(
                "Continuity priority (needs charter - copy/edit this exact scaffold; not recorded):",
                review,
            )
            self.assertIn("EXPERIMENT_CHARTER current :: hypothesis:", review)
            self.assertIn("proposed_next_action: ACTION_PREFLIGHT DECOMPOSE", review)

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
