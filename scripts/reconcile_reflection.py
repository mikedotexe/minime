#!/usr/bin/env python3
"""Inspect one public reflection finalization; apply only verified local writes."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from minime_autonomy.reflection_publication import ReflectionPublication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--action-id", required=True)
    parser.add_argument("--database", type=Path, help="Exact bound database; required to apply or inspect indexing")
    parser.add_argument("--apply", action="store_true", help="Complete sealed local publication/indexing; never generate or replay NEXT")
    args = parser.parse_args()
    if args.apply and args.database is None:
        parser.error("--apply requires --database")
    try:
        operation = ReflectionPublication.for_action(args.workspace.absolute(), args.action_id)
        result = operation.reconcile(apply=args.apply, database=args.database)
        print(json.dumps({"action_id": args.action_id, "applied": args.apply, **result.status()}, sort_keys=True))
        if args.apply:
            return 0 if result.publication == "published" and result.indexing == "indexed" and result.reason is None else 1
        return 0 if result.publication in {"published", "prepared"} else 1
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        # Never print exception text: SQLite/path errors can contain supplied data.
        print(json.dumps({"action_id": args.action_id, "applied": False,
                          "reason": "invalid_or_unavailable_evidence", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
