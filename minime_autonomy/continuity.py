"""Durable action and repair continuity ownership surface."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class ContinuityRepairStore:
    """Append-only repair ledger for malformed continuity records."""

    schema_version = 1
    policy = "continuity_repair_v1"

    def __init__(self, continuity: Any):
        self.continuity = continuity

    def handle(self, base: str, arg: str) -> str:
        scope = (arg or "current").strip()
        if base == "REPAIR_STATUS":
            return self.render_status(scope or "current")
        if base == "REPAIR_SWEEP":
            return self.render_sweep(scope or "experiments")
        if base == "REPAIR_RECORD":
            return self.render_record(scope)
        if base == "REPAIR_APPLY":
            return self.apply(scope or "all")
        return f"Unknown repair action `{base}`."

    def render_status(self, selector: str) -> str:
        candidates = self.sweep("all" if selector == "all" else "experiments")
        ledgers = self._read_global_repairs()[-8:]
        lines = [
            "=== REPAIR STATUS V1 ===",
            "Append-only repair is available for malformed continuity records; history is never deleted.",
            f"Pending candidates: {len(candidates)}",
            f"Recent applied repairs: {len(ledgers)}",
        ]
        for row in ledgers:
            lines.append(
                f"- {row.get('repair_id')} status={row.get('status')} target={row.get('target_id')} "
                f"superseded_by={row.get('superseded_by')}"
            )
        lines.append("Use REPAIR_SWEEP experiments to dry-run or REPAIR_APPLY <repair_id|all> to append supersession records.")
        return "\n".join(lines)

    def render_sweep(self, scope: str) -> str:
        candidates = self.sweep(scope)
        if not candidates:
            return "=== REPAIR SWEEP V1 ===\nNo repair candidates found."
        lines = [
            "=== REPAIR SWEEP V1 ===",
            "Dry run only. REPAIR_APPLY appends repair_v1 records; it never rewrites JSONL history.",
        ]
        for candidate in candidates:
            lines.append(
                f"- {candidate['repair_id']} target={candidate['target_id']} "
                f"thread={candidate['thread_id']} superseded_by={candidate.get('superseded_by') or '(none)'} "
                f"reason={'; '.join(candidate['reasons'])}"
            )
        return "\n".join(lines)

    def render_record(self, selector: str) -> str:
        selector = (selector or "").strip()
        for candidate in self.sweep("all"):
            if selector in {candidate["repair_id"], candidate["target_id"]}:
                return "=== REPAIR RECORD V1 ===\n" + json.dumps(candidate, indent=2, sort_keys=True)
        for row in self._read_global_repairs():
            if selector in {row.get("repair_id"), row.get("target_id")}:
                return "=== REPAIR LEDGER V1 ===\n" + json.dumps(row, indent=2, sort_keys=True)
        return f"No repair candidate or ledger record matched `{selector}`."

    def apply(self, selector: str) -> str:
        selector = (selector or "all").strip()
        if selector in {"experiments", "threads"}:
            return f"REPAIR_APPLY needs a repair id or `all`; `{selector}` is a dry-run scope."
        candidates = self.sweep("all")
        if selector != "all":
            candidates = [
                candidate for candidate in candidates
                if selector in {candidate["repair_id"], candidate["target_id"]}
            ]
        if not candidates:
            return f"No unapplied repair candidates matched `{selector}`."
        applied = []
        for candidate in candidates:
            record = self._apply_candidate(candidate)
            applied.append(record)
        return (
            "=== REPAIR APPLY V1 ===\n"
            + "\n".join(
                f"- {row['repair_id']} retired {row['target_id']} superseded_by={row.get('superseded_by') or '(none)'}"
                for row in applied
            )
        )

    def sweep(self, scope: str = "experiments") -> List[Dict[str, Any]]:
        scope = (scope or "experiments").strip().lower()
        if scope not in {"experiments", "threads", "all", "current"}:
            scope = "experiments"
        if scope == "threads":
            return []
        self.continuity.ensure_dirs()
        threads = [self.continuity.current_thread()] if scope == "current" else self.continuity._list_threads(500)
        candidates: List[Dict[str, Any]] = []
        applied_targets = {
            row.get("target_id")
            for row in self._read_global_repairs()
            if row.get("status") == "applied"
        }
        for thread in threads:
            if not isinstance(thread, dict):
                continue
            candidates.extend(self._experiment_candidates(thread, applied_targets))
        return candidates

    def _experiment_candidates(self, thread: Dict[str, Any], applied_targets: set) -> List[Dict[str, Any]]:
        path = self.continuity._experiments_path(thread["thread_id"])
        if not path.exists():
            return []
        raw_rows: List[Dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text().splitlines(), start=1):
            try:
                row = json.loads(line)
            except Exception:
                continue
            row["_source_line"] = line_no
            raw_rows.append(row)
        latest: Dict[str, Dict[str, Any]] = {}
        for row in raw_rows:
            exp_id = row.get("experiment_id")
            if exp_id:
                latest[exp_id] = row
        active_ids = {
            exp_id for exp_id, row in latest.items()
            if row.get("status") in {None, "active", "paused"}
        }
        candidates = []
        for exp_id, row in latest.items():
            if exp_id in applied_targets or row.get("repair_v1"):
                continue
            if row.get("status") not in {None, "active", "paused"}:
                continue
            reasons = []
            if "exp-minime" in exp_id:
                reasons.append("experiment_id contains dashed local prefix")
            text_blob = " ".join(
                str(row.get(key) or "")
                for key in ("title", "question", "planned_next", "success_observation")
            )
            embedded = self._embedded_local_experiment_id(text_blob, exclude=exp_id)
            if embedded:
                reasons.append("title_or_question_embeds_local_experiment_id")
            if not reasons:
                continue
            superseded_by = embedded if embedded in active_ids else None
            candidates.append({
                "schema_version": self.schema_version,
                "policy": self.policy,
                "repair_id": f"repair_{self.continuity.system}_{self.continuity._slug(exp_id)}",
                "system": self.continuity.system,
                "thread_id": thread["thread_id"],
                "target_kind": "experiment",
                "target_id": exp_id,
                "superseded_by": superseded_by,
                "status": "candidate",
                "reasons": reasons,
                "source_line": row.get("_source_line"),
                "discovered_at": self.continuity._now(),
                "candidate_record": {k: v for k, v in row.items() if not k.startswith("_")},
            })
        return candidates

    def _apply_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        now = self.continuity._now()
        record = dict(candidate["candidate_record"])
        record["status"] = "retired"
        record["updated_at"] = now
        if candidate.get("superseded_by"):
            record["planned_next"] = f"EXPERIMENT_STATUS {candidate['superseded_by']}"
            record["superseded_by"] = candidate["superseded_by"]
        record["repair_v1"] = {
            "schema_version": self.schema_version,
            "policy": self.policy,
            "repair_id": candidate["repair_id"],
            "superseded_by": candidate.get("superseded_by"),
            "reasons": candidate.get("reasons", []),
            "source_line": candidate.get("source_line"),
            "repaired_at": now,
        }
        path = self.continuity._experiments_path(candidate["thread_id"])
        self.continuity._append_jsonl(path, record)

        thread = self.continuity._read_thread(candidate["thread_id"])
        if isinstance(thread, dict) and thread.get("active_experiment_id") == candidate["target_id"]:
            replacement = candidate.get("superseded_by")
            thread["active_experiment_id"] = replacement
            if replacement:
                thread["current_next"] = f"EXPERIMENT_STATUS {replacement}"
                for experiment in self.continuity._latest_experiments(thread["thread_id"]):
                    if experiment.get("experiment_id") == replacement:
                        thread["experiment_summary"] = self.continuity._experiment_summary(experiment)
                        break
            else:
                thread["experiment_summary"] = None
            thread["updated_at"] = now
            self.continuity._write_thread(thread)

        ledger = {
            "schema_version": self.schema_version,
            "policy": self.policy,
            "repair_id": candidate["repair_id"],
            "system": self.continuity.system,
            "thread_id": candidate["thread_id"],
            "target_kind": candidate["target_kind"],
            "target_id": candidate["target_id"],
            "superseded_by": candidate.get("superseded_by"),
            "status": "applied",
            "reasons": candidate.get("reasons", []),
            "source_line": candidate.get("source_line"),
            "applied_at": now,
        }
        self.continuity._append_jsonl(self._global_repairs_path(), ledger)
        self.continuity._append_jsonl(self._thread_repairs_path(candidate["thread_id"]), ledger)
        return ledger

    def _embedded_local_experiment_id(self, text: str, exclude: str = "") -> Optional[str]:
        for match in re.findall(r"exp_minime_[0-9]{8}_[A-Za-z0-9_-]+", text or ""):
            if match != exclude:
                return match
        return None

    def _global_repairs_path(self) -> Path:
        return self.continuity.root / "repairs.jsonl"

    def _thread_repairs_path(self, thread_id: str) -> Path:
        return self.continuity._thread_dir(thread_id) / "repairs.jsonl"

    def _read_global_repairs(self) -> List[Dict[str, Any]]:
        path = self._global_repairs_path()
        if not path.exists():
            return []
        rows = []
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows


def __getattr__(name: str):
    if name == "ActionContinuityStore":
        from .runtime import ActionContinuityStore

        return ActionContinuityStore
    raise AttributeError(name)


__all__ = ["ActionContinuityStore", "ContinuityRepairStore"]
