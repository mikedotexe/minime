#!/usr/bin/env python3
"""Smoke read-only self-knowledge overrides for Astrid and Minime.

This harness writes one protected/read-only pending NEXT override at a time,
waits for the normal autonomous dispatcher to consume it, and verifies the
terminal override shape. It never starts services and never writes peer state.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SYSTEMS = {
    "minime": {
        "override": Path("/Users/v/other/minime/workspace/runtime/pending_next_override.json"),
        "continuity": Path("/Users/v/other/minime/workspace/action_threads"),
    },
    "astrid": {
        "override": Path(
            "/Users/v/other/astrid/capsules/spectral-bridge/workspace/runtime/pending_next_override.json"
        ),
        "continuity": Path(
            "/Users/v/other/astrid/capsules/spectral-bridge/workspace/action_threads"
        ),
    },
}

SMOKE_ACTIONS = (
    "FACULTIES",
    "CAPABILITY_STATUS EXPERIMENT_START",
    "REPAIR_SWEEP experiments",
    "REPAIR_APPLY all",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_override(path: Path, action: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "status": "pending",
        "active": True,
        "terminal": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "pending_next_action": action,
        "last_pending_next_action": None,
        "source": "codex_live_self_knowledge_smoke",
        "reason": "source validation of self-knowledge override lane",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def wait_terminal(path: Path, expected_action: str, timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        payload = read_json(path)
        if payload.get("terminal") is True and payload.get("pending_next_action") is None:
            last = payload.get("last_pending_next_action") or payload.get("consumed_action")
            if last == expected_action:
                return payload
        time.sleep(2.0)
    raise TimeoutError(f"{path} did not become terminal for {expected_action!r}")


def smoke(system: str, actions: Iterable[str], timeout_s: float) -> None:
    config = SYSTEMS[system]
    override = config["override"]
    print(f"== {system} ==")
    for action in actions:
        write_override(override, action)
        terminal = wait_terminal(override, action, timeout_s)
        status = terminal.get("status")
        if action.startswith("REPAIR_APPLY") and status == "pending":
            raise AssertionError("REPAIR_APPLY remained pending; expected terminal blocked/consumed shape")
        print(f"- {action}: terminal status={status} reason={terminal.get('reason')}")
    snapshot = config["continuity"] / "capability_map.json"
    if not snapshot.exists():
        raise AssertionError(f"{system} did not write {snapshot}")
    print(f"  capability snapshot: {snapshot}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", choices=sorted(SYSTEMS), action="append")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--action", action="append")
    args = parser.parse_args()

    systems = args.system or sorted(SYSTEMS)
    actions = tuple(args.action or SMOKE_ACTIONS)
    for system in systems:
        smoke(system, actions, args.timeout)


if __name__ == "__main__":
    main()
