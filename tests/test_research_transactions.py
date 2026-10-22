"""Synthetic native-store admission; no network or live workspace access."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa
from minime_autonomy import research_transactions as tx


class ResearchTransactions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = aa.ActionContinuityStore(Path(self.tmp.name) / "workspace", session_id=7)
        self.exp = self.store.start_experiment("Synthetic admission", "Can exact operations remain bounded?")
        self.thread = self.store.current_thread()
        self.path = self.store._authority_gate_path(self.thread["thread_id"])
        self.budget = self.store._research_budget_record("research_budget_approval", "budget_fixture", self.thread, self.exp, {}, {
            "scope": "read_only_research", "status": "active", "max_actions": 4,
            "allowed_sources": ["web", "local"],
            "expires_at_unix_s": time.time() + 3600,
        })
        self.store._append_jsonl(self.path, self.budget)

    def admit(self, op, action="SEARCH fixture"):
        return tx.admit(self.store, self.exp["experiment_id"], action, op, {})

    def finish(self, op, action="SEARCH fixture", outcome="completed"):
        ticket = self.admit(op, action)
        tx.transition(self.store, ticket, "execution_started", {})
        tx.transition(self.store, ticket, outcome, {})
        return ticket

    def test_unbound_read_does_not_inherit_old_experiment(self):
        self.assertIsNone(self.store.research_budget_guard_assessment("SEARCH ordinary", {}))
        self.assertEqual(self.store.research_budget_preflight_for_action("SEARCH ordinary", {}), (True, None, ""))
        self.assertIsNone(self.store.charter_required_guard_assessment("SEARCH ordinary"))
        self.assertFalse(self.store.research_budget_preflight_for_action("AR_START change", {})[0])

    def test_diagnostic_labels_and_aliases_never_acquire_inherited_quotas(self):
        for base in sorted(tx.READ_ONLY_DIAGNOSTICS):
            for label in ("baseline", "pulse response", "CONTROL amplitude inject Vec<T>"):
                command = f"{base} {label}"
                with self.subTest(command=command):
                    self.assertTrue(tx.ordinary_exploration(self.store, command))
                    self.assertIsNone(self.store.research_budget_guard_assessment(command, {}))
                    self.assertIsNone(self.store.charter_required_guard_assessment(command))
        for command in ("CONTROL_APPLY_LEASE change", "RUN_PYTHON code", "UNRECOGNIZED pulse"):
            self.assertFalse(tx.ordinary_exploration(self.store, command), command)

    def test_latest_approval_and_close_review_never_revive_older_grant(self):
        for fields in ({"max_actions": 0}, {"expires_at_unix_s": 1},
                       {"status": "refused"}, {"experiment_id": "other"}):
            with self.subTest(fields=fields):
                self.assertIsNone(tx.active_budget([self.budget, {**self.budget, **fields}], self.exp["experiment_id"]))
        close = {"record_type": "research_budget_review", "budget_id": "budget_fixture", "outcome": "close"}
        continued = {**close, "outcome": "continue"}
        self.assertIsNone(tx.active_budget([self.budget, close, continued], self.exp["experiment_id"]))

    def test_worker_rechecks_refused_experiment_and_latest_source_scope(self):
        ticket = self.admit("scope-change")
        tx.transition(self.store, ticket, "queued", {}, job_id="queued")
        self.store._append_jsonl(self.path, {**self.budget, "allowed_sources": ["local"]})
        with self.assertRaisesRegex(ValueError, "source"):
            tx.transition(self.store, ticket, "execution_started", {})
        self.assertEqual(tx.current_operation(self.store, ticket)["lifecycle"], "queued")
        self.store._append_jsonl(self.path, self.budget)
        refused = {**self.exp, "status": "refused"}
        self.store._append_jsonl(self.store._experiments_path(self.thread["thread_id"]), refused)
        with self.assertRaisesRegex(ValueError, "experiment"):
            self.admit("refused-admission")
        with self.assertRaisesRegex(ValueError, "experiment"):
            tx.transition(self.store, ticket, "execution_started", {})
        marker = json.loads((self.store.root / "research-transactions-required.json").read_text())
        self.assertEqual(marker["required_research_transaction_version"], tx.RESEARCH_TRANSACTION_VERSION)

    def test_floor_fsync_failure_retry_resyncs_before_admission(self):
        floor = self.store.root / "research-transactions-required.json"
        sync = os.fsync
        for failure_at in (1, 2, 3):
            with self.subTest(failure_at=failure_at):
                floor.unlink(missing_ok=True)
                before = self.path.read_bytes()
                calls = []

                def fail_sync(fd):
                    calls.append(fd)
                    if len(calls) == failure_at:
                        raise OSError("synthetic floor fsync failure")
                    return sync(fd)

                with patch.object(tx.os, "fsync", side_effect=fail_sync):
                    with self.assertRaises(OSError):
                        self.admit(f"floor-retry-{failure_at}", f"SEARCH fixture-{failure_at}")
                self.assertEqual(self.path.read_bytes(), before)
                self.assertTrue(floor.is_file())
                original, stamp = floor.read_bytes(), floor.stat().st_mtime_ns
                synced = []

                def track_sync(fd):
                    synced.append(os.fstat(fd).st_ino)
                    return sync(fd)

                append = self.store._append_jsonl

                def checked_append(path, row):
                    self.assertEqual(synced, [p.stat().st_ino for p in
                                             (floor, self.store.root, self.store.root.parent)])
                    return append(path, row)

                with patch.object(tx.os, "fsync", side_effect=track_sync), \
                     patch.object(self.store, "_append_jsonl", side_effect=checked_append):
                    self.admit(f"floor-retry-{failure_at}", f"SEARCH fixture-{failure_at}")
                self.assertEqual(floor.read_bytes(), original)
                self.assertEqual(floor.stat().st_mtime_ns, stamp)

    def test_existing_floor_sync_failure_prevents_records(self):
        tx.require_capability(self.store)
        floor = self.store.root / "research-transactions-required.json"
        before, marker = self.path.read_bytes(), floor.read_bytes()
        for failure_at in (1, 2, 3):
            with self.subTest(failure_at=failure_at), \
                 patch.object(tx.os, "fsync", side_effect=[None] * (failure_at - 1) + [OSError("synthetic sync failure")]):
                with self.assertRaises(OSError):
                    self.admit("existing-floor")
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(floor.read_bytes(), marker)

    def test_invalid_floor_is_preserved_and_prevents_admission(self):
        floor = self.store.root / "research-transactions-required.json"
        valid = dict(schema_version=1, owner="minime", required_research_transaction_version=1)
        invalid = [b"{broken", b"{}", b"x" * 4097,
                   json.dumps({**valid, "schema_version": True}).encode(),
                   json.dumps({**valid, "required_research_transaction_version": True}).encode(),
                   json.dumps({**valid, "required_research_transaction_version": 1.0}).encode(),
                   json.dumps({**valid, "required_research_transaction_version": 2}).encode(),
                   json.dumps({**valid, "owner": "astrid"}).encode(),
                   json.dumps({**valid, "extra": 1}).encode(),
                   b'{"schema_version":1,"owner":"minime","required_research_transaction_version":2,"required_research_transaction_version":1}']
        before = {p: p.read_bytes() for p in self.store.root.rglob("*.jsonl")}
        for raw in invalid:
            with self.subTest(raw=raw[:120]):
                floor.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.admit("invalid-floor")
                self.assertEqual(floor.read_bytes(), raw)
                self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_floor_regular_and_dangling_symlinks_and_directory_are_refused(self):
        floor = self.store.root / "research-transactions-required.json"
        target = self.store.root / "synthetic-floor-target"
        before = self.path.read_bytes()
        for present in (False, True):
            with self.subTest(target_present=present):
                if present:
                    target.write_text(json.dumps(dict(schema_version=1, owner="minime",
                                                     required_research_transaction_version=1)))
                floor.symlink_to(target)
                with self.assertRaises(ValueError):
                    self.admit("symlink-floor")
                self.assertTrue(floor.is_symlink())
                self.assertEqual(target.exists(), present)
                self.assertEqual(self.path.read_bytes(), before)
                floor.unlink()
        floor.mkdir()
        with self.assertRaises(ValueError):
            self.admit("directory-floor")
        self.assertTrue(floor.is_dir())
        self.assertEqual(self.path.read_bytes(), before)

    def test_noncurrent_binding_failure_counts_and_never_replays(self):
        self.store.start_experiment("Other selected", "Unrelated")
        ticket = self.finish("failed-job", outcome="failed")
        active = tx.active_budget(tx.rows(self.path), self.exp["experiment_id"])
        self.assertEqual(active["spent_actions"], 1)
        for action in ("SEARCH fixture", "SEARCH other"):
            with self.assertRaises(ValueError):
                self.admit("failed-job", action)
        with self.assertRaises(ValueError):
            tx.transition(self.store, ticket, "released_unstarted", {})

    def test_cross_thread_exact_selector_is_refused_not_substituted(self):
        self.store.create_thread("Other native thread", "Independent selected work")
        other = self.store.start_experiment("Other selected experiment", "Unrelated")
        with self.assertRaises(ValueError):
            self.admit("cross-thread")
        self.assertEqual(self.store.resolve_experiment_bind_target("current"), other["experiment_id"])
        self.assertEqual(tx.rows(self.path), [self.budget])

    def test_repeated_reads_count_normally_without_editorial_veto(self):
        for operation in ("a", "b", "c", "d"):
            self.finish(operation)
        history = tx.rows(self.path)
        self.assertEqual(sum(row.get("record_type") == "research_budget_debit" for row in history), 4)
        self.assertFalse(any(row.get("reason") == "duplicate_query_or_url_review_required" for row in history))
        with self.assertRaisesRegex(ValueError, "allowance"):
            self.admit("exhausted")
        self.store.experiment_research_review("budget_fixture :: outcome: continue; observation: keep history", {})
        with self.assertRaises(ValueError):
            self.admit("not-replenished")

    def test_concurrent_reservations_crash_hold_and_release(self):
        results = []
        def attempt(index):
            try:
                results.append(self.admit(f"op-{index}", f"SEARCH fixture{index}"))
            except ValueError:
                pass
        workers = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len(results), 4)
        self.assertIsNone(tx.active_budget(tx.rows(self.path), self.exp["experiment_id"]))
        # A new store cannot replay a pre-crash reservation. An explicit local
        # unstarted release frees only that slot; started slots are never freed.
        with self.assertRaises(ValueError):
            self.admit(results[0]["operation_id"], results[0]["raw_action"])
        tx.transition(self.store, results[0], "released_unstarted", {})
        self.assertEqual(tx.active_budget(tx.rows(self.path), self.exp["experiment_id"])["remaining_actions"], 1)
        tx.transition(self.store, results[1], "execution_started", {})
        with self.assertRaises(ValueError):
            tx.transition(self.store, results[1], "released_unstarted", {})

    def test_corrupt_tail_owner_and_expiry_fail_closed(self):
        with self.assertRaises(ValueError):
            tx.admit(self.store, "exp_astrid_foreign", "SEARCH fixture", "foreign", {})
        ticket = self.admit("expiry")
        with patch.object(tx.time, "time", return_value=time.time() + 4000):
            with self.assertRaises(ValueError):
                tx.transition(self.store, ticket, "execution_started", {})
        damaged = self.path.read_bytes() + b'{"partial":'
        self.path.write_bytes(damaged)
        with self.assertRaises(ValueError):
            self.admit("corrupt")
        with self.assertRaises(ValueError):
            self.store._append_jsonl(self.path, self.budget)
        self.assertEqual(self.path.read_bytes(), damaged)

    def test_history_symlinks_refuse_read_and_append_without_creating_targets(self):
        directory = self.store.root / "synthetic-histories"
        directory.mkdir()
        for name in ("authority_gate.jsonl", "experiments.jsonl", "research_provider.jsonl"):
            for present in (False, True):
                with self.subTest(name=name, target_present=present):
                    path = directory / name
                    target = directory / f"target-{name}-{present}"
                    original = b'{"synthetic": true}\n'
                    if present:
                        target.write_bytes(original)
                    path.symlink_to(target)
                    try:
                        with self.assertRaisesRegex(ValueError, "symlink"):
                            tx.rows(path)
                        with self.assertRaisesRegex(ValueError, "symlink"):
                            tx.append(path, {"synthetic": "new"})
                        self.assertTrue(path.is_symlink())
                        self.assertEqual(target.exists(), present)
                        if present:
                            self.assertEqual(target.read_bytes(), original)
                    finally:
                        path.unlink()

    def test_history_missing_regular_and_corrupt_states_remain_distinct(self):
        path = self.store.root / "synthetic-history.jsonl"
        self.assertEqual(tx.rows(path), [])
        tx.append(path, {"synthetic": True})
        self.assertEqual(tx.rows(path), [{"synthetic": True}])
        for raw in (b'{"partial":', b'[]\n', b'{"research_transaction_version":true}\n',
                    b'{"research_transaction_version":2}\n', b'{"status":"held","status":"active"}\n'):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    tx.rows(path)
                with self.assertRaises(ValueError):
                    tx.append(path, {"synthetic": "new"})
                self.assertEqual(path.read_bytes(), raw)

    def test_deferred_worker_uses_strict_pinned_owner_state_after_selection_changes(self):
        ticket = self.admit("pinned-worker")
        tx.transition(self.store, ticket, "queued", {}, job_id="synthetic-worker")
        selected = self.store.create_thread("Unrelated reader thread", "Separate selection")
        self.store.start_experiment("Unrelated reader", "Not the reserved experiment")
        with patch.object(self.store, "resolve_experiment_bind_target", side_effect=AssertionError("UI selection used")), \
             patch.object(self.store, "_find_experiment_by_id", side_effect=AssertionError("permissive reader used")):
            tx.transition(self.store, ticket, "execution_started", {})
        self.assertEqual(tx.current_operation(self.store, ticket)["lifecycle"], "execution_started")
        self.assertEqual(json.loads(self.store.index_path.read_bytes())["active_thread_id"], selected["thread_id"])
        self.assertEqual(sum(row.get("record_type") == "research_budget_debit" for row in tx.rows(self.path)), 1)

    def test_deferred_owner_history_symlinks_never_create_targets(self):
        ticket = self.admit("symlink-worker")
        tx.transition(self.store, ticket, "queued", {}, job_id="synthetic-worker")
        gate_raw = self.path.read_bytes()
        for path in (self.store._thread_dir(ticket["thread_id"]) / "thread.json",
                     self.store._experiments_path(ticket["thread_id"])):
            original = path.read_bytes()
            for present in (False, True):
                with self.subTest(path=path.name, target_present=present):
                    target = self.store.root / f"synthetic-target-{path.name}-{present}"
                    if present:
                        target.write_bytes(original)
                    path.unlink()
                    path.symlink_to(target)
                    try:
                        with self.assertRaisesRegex(ValueError, "symlink"):
                            tx.transition(self.store, ticket, "execution_started", {})
                        self.assertTrue(path.is_symlink())
                        self.assertEqual(target.exists(), present)
                        if present:
                            self.assertEqual(target.read_bytes(), original)
                        self.assertEqual(self.path.read_bytes(), gate_raw)
                        self.assertEqual(tx.current_operation(self.store, ticket)["lifecycle"], "queued")
                    finally:
                        path.unlink()
                        path.write_bytes(original)

    def test_deferred_worker_rejects_foreign_reservation_and_grant(self):
        ticket = self.admit("foreign-worker")
        tx.transition(self.store, ticket, "queued", {}, job_id="synthetic-worker")
        changed = [{**row, "being": "astrid"} for row in tx.rows(self.path)]
        damaged = b"".join(json.dumps(row).encode() + b"\n" for row in changed)
        self.path.write_bytes(damaged)
        with self.assertRaisesRegex(ValueError, "owner"):
            tx.transition(self.store, {**ticket, "being": "astrid"}, "execution_started", {})
        self.assertEqual(self.path.read_bytes(), damaged)

    def test_deferred_worker_refuses_corrupt_pinned_experiment_and_owner_state(self):
        ticket = self.admit("strict-worker")
        tx.transition(self.store, ticket, "queued", {}, job_id="synthetic-worker")
        thread_path = self.store._thread_dir(ticket["thread_id"]) / "thread.json"
        experiments = self.store._experiments_path(ticket["thread_id"])
        thread_raw, history_raw, gate_raw = thread_path.read_bytes(), experiments.read_bytes(), self.path.read_bytes()
        thread = json.loads(thread_raw)
        # A valid current selection must not hide damage in the ticket's thread.
        selected = self.store.create_thread("Other selected thread", "Synthetic independent state")
        self.store._append_jsonl(self.store._experiments_path(selected["thread_id"]),
                                {**self.exp, "thread_id": selected["thread_id"]})
        encode = lambda value: json.dumps(value).encode() + b"\n"
        cases = [(experiments, history_raw + b'{"partial":'),
                 (experiments, history_raw + b'{broken}\n'),
                 (experiments, history_raw + b'[]\n'),
                 (experiments, b""),
                 (experiments, history_raw + encode({k: v for k, v in self.exp.items() if k != "status"})),
                 (experiments, history_raw + (json.dumps(self.exp)[:-1] + ',"status":"active"}\n').encode())]
        cases += [(experiments, history_raw + encode({**self.exp, **change})) for change in (
            {"schema_version": 2}, {"schema_version": True}, {"thread_id": "other-thread"},
            {"experiment_id": "exp_astrid_foreign"}, {"status": "paused"})]
        cases += [(thread_path, encode({**thread, **change})) for change in (
            {"system_origin": "astrid"}, {"thread_id": "other-thread"},
            {"schema_version": 2}, {"schema_version": True})]
        calls = []

        class Agent:
            running = False
            LLM_JOB_ACTIONS = {"synthetic"}
            _pending_action_continuity_context = {"raw_next": ticket["raw_action"], "research_reservation_v1": ticket}
            def _continuity_store(inner):
                return self.store
            @tx.execute_bound_action
            def execute(inner, action, state, **kwargs):
                calls.append(action)
                inner._last_action_continuity_event = {"status": "handled"}

        for path, damaged in cases:
            with self.subTest(path=path.name, damaged=damaged[-160:]):
                path.write_bytes(damaged)
                try:
                    with self.assertRaises((ValueError, OSError)):
                        Agent().execute("synthetic", {}, _from_llm_job=True)
                    self.assertEqual(calls, [])
                    self.assertEqual(path.read_bytes(), damaged)
                    self.assertEqual(self.path.read_bytes(), gate_raw)
                    self.assertEqual(tx.current_operation(self.store, ticket)["lifecycle"], "queued")
                finally:
                    thread_path.write_bytes(thread_raw)
                    experiments.write_bytes(history_raw)
                    self.path.write_bytes(gate_raw)
                    calls.clear()

    def test_scope_compound_uncertain_and_expiry_are_not_exemptions(self):
        for action in ("READ_MORE fixture AND AR_START mutate", "INTROSPECT AND SEARCH example",
                       "SEARCH fixture\nAR_START change", "UNRECOGNIZED read"):
            with self.assertRaises(ValueError):
                tx.is_metered(self.store, action)
        local = {**self.budget, "allowed_sources": ["local"]}
        self.path.write_text(json.dumps(local) + "\n")
        with self.assertRaisesRegex(ValueError, "source"):
            self.admit("web")
        self.assertIsNone(self.store.research_budget_guard_assessment("SEARCH ordinary", {}))
        for invalid in (None, float("nan"), float("inf"), True):
            self.assertIsNone(tx.active_budget([{**self.budget, "expires_at_unix_s": invalid}], self.exp["experiment_id"]))

    def test_pending_repeats_match_preflight_without_renewing_expiry(self):
        first = self.admit("pending-a")
        self.admit("pending-b")
        token = tx.binding.set(self.exp["experiment_id"])
        try:
            self.assertTrue(self.store.research_budget_preflight_for_action("SEARCH fixture", {})[0])
        finally:
            tx.binding.reset(token)
        tx.transition(self.store, first, "queued", {}, job_id="synthetic-job")
        self.assertEqual(tx.active_budget(tx.rows(self.path), self.exp["experiment_id"])["reserved_actions"], 2)
        with patch.object(tx.time, "time", return_value=time.time() + 4000):
            with self.assertRaises(ValueError):
                tx.transition(self.store, first, "execution_started", {})
        self.assertEqual(tx.current_operation(self.store, first)["lifecycle"], "queued")

    def test_worker_claim_carries_binding_and_refuses_uncertain_replay(self):
        ticket = self.admit("worker")
        tx.transition(self.store, ticket, "queued", {}, job_id="job")
        calls = []
        class Agent:
            running = False
            LLM_JOB_ACTIONS = {"synthetic"}
            _pending_action_continuity_context = {"raw_next": ticket["raw_action"], "research_reservation_v1": ticket}
            def _continuity_store(inner):
                return self.store
            @tx.execute_bound_action
            def execute(inner, action, state, **kwargs):
                calls.append(tx.binding.get())
                self.assertEqual(tx.executing.get(), ticket)
                inner._last_action_continuity_event = {"status": "failed"}
        agent = Agent()
        worker = threading.Thread(target=lambda: agent.execute("synthetic", {}, _from_llm_job=True))
        worker.start()
        worker.join()
        self.assertEqual(calls, [self.exp["experiment_id"]])
        self.assertEqual(tx.current_operation(self.store, ticket)["lifecycle"], "failed")
        self.assertIsNone(tx.binding.get())
        with self.assertRaises(ValueError):
            agent.execute("synthetic", {}, _from_llm_job=True)
        self.assertEqual(len(calls), 1)
