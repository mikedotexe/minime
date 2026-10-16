"""Deliberate comparison of two independently read continuity snapshots."""

import json
from pathlib import Path

from .continuity_snapshot import (
    EvidenceUnavailable, StableSnapshot, digest_sources, valid_identifier,
    validate_experiment, validate_thread,
)
from .return_support import retired_heuristic_line


def _current_thread(snapshot, root, owner):
    index = snapshot.json(root / "index.json")
    thread_id = index.get("active_thread_id")
    if not valid_identifier(thread_id):
        raise EvidenceUnavailable("no selected thread")
    path = root / "threads" / thread_id
    snapshot.directory(path)
    thread = snapshot.json(path / "thread.json")
    validate_thread(thread, thread_id, owner)
    return path, thread


def _resolve(snapshot, root, selector, owner, selected=None):
    if selected is not None or selector == "current" or not selector.startswith("exp_"):
        path, thread = selected or _current_thread(snapshot, root, owner)
        reference = (thread.get("active_experiment_id") if selector == "current" else
                     selector if selector.startswith("exp_") else None)
        if selector == "current" and not valid_identifier(reference):
            raise EvidenceUnavailable("no selected experiment; historical fallback is disabled")
        paths = [path]
    else:
        reference = selector
        paths = snapshot.thread_dirs(root / "threads")
    matches = []
    for path in paths:
        rows, data = snapshot.jsonl(path / "experiments.jsonl")
        latest = {}
        for record in rows:
            identity = record.get("experiment_id")
            if not valid_identifier(identity):
                raise EvidenceUnavailable("malformed experiment identity")
            validate_experiment(record, path.name)
            latest[identity] = record
        for identity, record in latest.items():
            if (identity == reference if reference is not None else
                    selector.casefold() in str(record.get("title", "")).casefold()):
                matches.append((path, record, data))
    if len(matches) != 1:
        raise EvidenceUnavailable("experiment missing or ambiguous")
    return matches[0]


def inspect_local_experiment(root, owner, selector):
    """Read selected context without invoking the store's projection-refresh read path."""
    root = Path(root)
    selector = selector or "current"
    snapshot = StableSnapshot()
    path, thread = _current_thread(snapshot, root, owner)
    record = None
    if selector != "current" or thread.get("active_experiment_id"):
        _, record, _ = _resolve(snapshot, root, selector, owner, selected=(path, thread))
    snapshot.verify()
    return thread, record


def _validate_run(run):
    required_text = ("run_id", "experiment_id", "action_text", "stage", "status",
                     "result_summary", "interpretation", "created_at", "updated_at")
    if (type(run.get("schema_version")) is not int or run["schema_version"] != 1
            or any(not isinstance(run.get(key), str) for key in required_text)
            or not isinstance(run.get("artifacts"), list)
            or any(not isinstance(item, dict) for item in run["artifacts"])):
        raise EvidenceUnavailable("malformed execution receipt")
    return run


def read_comparison_side(root, owner, selector):
    """No store methods: even its ordinary read helpers can refresh/write projections."""
    selector = selector or "current"
    if selector.lower() == "current":
        selector = "current"
    result = {"owner": owner, "requested_selector": selector, "experiment_id": None,
              "availability": "unavailable", "digest": None, "timestamps": None}
    if selector.startswith("exp_"):
        result["experiment_id"] = selector
    try:
        snapshot = StableSnapshot()
        path, record, experiment_bytes = _resolve(snapshot, Path(root), selector, owner)
        experiment_id = record["experiment_id"]
        if not experiment_id.startswith(f"exp_{owner}_"):
            raise EvidenceUnavailable("experiment owner mismatch")
        result["experiment_id"] = experiment_id
        rows, run_bytes = snapshot.jsonl(path / "experiment_runs.jsonl")
        runs = []
        for run in rows:
            if not isinstance(run.get("experiment_id"), str):
                raise EvidenceUnavailable("malformed execution receipt identity")
            _validate_run(run)
            if run["experiment_id"] == experiment_id:
                runs.append(run)
        retained_run_count = len(runs)
        runs = runs[-4:]
        dossier_status, dossier_records, dossier_bytes = "unavailable", [], b""
        dossier_claim_id = None
        # Optional dossier material never changes whether the experiment itself is readable.
        try:
            dossier_rows, dossier_bytes = snapshot.jsonl(path / "research_dossier.jsonl")
            for row in dossier_rows:
                if (row.get("record_schema") != "research_dossier_v1"
                        or not isinstance(row.get("being"), str)
                        or not isinstance(row.get("experiment_id"), str)
                        or not isinstance(row.get("thread_id"), str)
                        or not valid_identifier(row.get("record_id"))):
                    raise EvidenceUnavailable("malformed dossier record")
                if row.get("experiment_id") == experiment_id and row.get("being") == owner:
                    if row.get("thread_id") != path.name:
                        raise EvidenceUnavailable("malformed dossier record")
                    dossier_records.append(row["record_id"])
                    if row.get("record_type") == "claim":
                        if not valid_identifier(row.get("claim_id")):
                            raise EvidenceUnavailable("malformed dossier claim")
                        dossier_claim_id = row["claim_id"]
            dossier_status = "verified_readable"
        except EvidenceUnavailable:
            dossier_records, dossier_bytes = [], b""
            dossier_claim_id = None
        snapshot.verify()
        result.update({
            "availability": "verified_readable",
            "thread_id": path.name,
            "digest": digest_sources(experiment_bytes, run_bytes, dossier_bytes),
            "timestamps": {key: record.get(key) for key in ("created_at", "updated_at")},
            "record": record,
            "runs": runs,
            "retained_run_count": retained_run_count,
            "dossier_status": dossier_status,
            "dossier_record_ids": dossier_records[-4:],
            "dossier_claim_id": dossier_claim_id,
        })
    except EvidenceUnavailable as exc:
        result["reason"] = str(exc)
    return result


def _text(value, limit=1200):
    # JSON quoting keeps authored newlines distinct from comparison labels/instructions.
    rendered = json.dumps(value, ensure_ascii=True)
    return rendered if len(rendered) <= limit else rendered[:limit] + " [truncated]"


def _render_side(label, side):
    lines = [f"{label}: owner={side['owner']} id={side['experiment_id'] or '(unresolved)'}",
             f"Availability: {side['availability']}"]
    if side["availability"] != "verified_readable":
        lines += [f"Evidence unavailable: {side.get('reason', 'unknown')}",
                  "Digest: unavailable; timestamps: unavailable",
                  "Authored interpretation: unavailable",
                  "Execution receipts: unavailable",
                  "Artifact references (unverified): unavailable"]
        return "\n".join(lines)
    record = side["record"]
    lines += [f"Digest: {side['digest']}", f"Timestamps: {_text(side['timestamps'])}",
              "Authored interpretation (not an execution receipt):",
              f"  Title: {_text(record.get('title'))}",
              f"  Question: {_text(record.get('question'))}",
              f"  Hypothesis: {_text(record.get('hypothesis'))}",
              f"  Observation: {_text(record.get('success_observation'))}"]
    for run in side["runs"]:
        lines.append(f"  Run {_text(run['run_id'])} interpretation: {_text(run['interpretation'])}")
    lines += ["Execution receipts (at most 4 retained runs; no action executed by comparison):",
              f"  Retained run count: {side['retained_run_count']}. Recorded outcomes are not independently verified execution."]
    for run in side["runs"]:
        receipt = {key: run.get(key) for key in (
            "run_id", "action_text", "stage", "status", "result_summary", "created_at", "updated_at")}
        lines.append("  " + _text(receipt, 2400))
    if not side["runs"]:
        lines.append("  No runs in the readable snapshot.")
    lines.append("Artifact references (unverified; files not opened):")
    evidence = record.get("evidence_v1") or {}
    refs = evidence.get("artifact_refs")
    if isinstance(refs, list):
        lines.append("  Experiment: " + _text(refs[:8]))
    for run in side["runs"]:
        lines.append(f"  Run {_text(run['run_id'])}: {_text(run['artifacts'][:8])}")
    if not refs and not any(run["artifacts"] for run in side["runs"]):
        lines.append("  None recorded; artifact existence has not been checked.")
    retired = retired_heuristic_line(record.get("motif_allowance_v1"),
                                     *(run.get("motif_allowance_v1") for run in side["runs"]))
    if retired:
        lines.append(retired.rstrip())
    lines.append(f"Existing dossier: {side['dossier_status']}; record IDs: {_text(side['dossier_record_ids'])}")
    return "\n".join(lines)


def render_comparison(left, right, local_owner):
    lines = ["Experiment comparison (read-only bounded snapshots)",
             "No selection, peer mutation, saved-next execution, or automatic equivalence conclusion.",
             "Juxtaposition does not establish shared mechanism, causation, temporal correspondence, or equivalent experience.",
             _render_side("Left", left), "", _render_side("Right", right)]
    for side in (left, right):
        if (side["owner"] == local_owner and side["availability"] == "verified_readable"
                and side.get("dossier_claim_id")):
            identity = side["experiment_id"]
            claim_id = side["dossier_claim_id"]
            lines.append(
                f"Optional existing dossier review: DOSSIER_REVIEW {identity}. "
                f"Optional authored note: DOSSIER_EVIDENCE {identity} :: claim_id: {claim_id}; "
                "evidence: <your authored note>. No claim is prefilled or written here."
            )
    return "\n".join(lines)


def render_peer_inspection(side, command):
    return (
        f"Peer experiment reference ({command}) `{side['experiment_id']}` belongs to {side['owner']}.\n"
        + _render_side("Peer", side)
        + "\nRead-only inspection; no selection, peer mutation, or peer-reference work was recorded. "
          "Saved next actions were not executed.\n"
          "Suggested local next: ordinary local choices remain available; comparison or dossier notes are optional."
    )
