#!/usr/bin/env python3
"""Create and verify owner-only sovereign daughter runtime manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA = "division.runtime_manifest.v1"
INTERNAL_PORTS = {
    "parent_telemetry": 7900,
    "parent_sensory": 7901,
    "parent_av": 7902,
    "minime_telemetry": 7903,
    "minime_sensory": 7904,
    "astrid_telemetry": 7905,
    "astrid_sensory": 7906,
}


class ManifestError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_absolute_disjoint(runtime: Path, minime: Path, astrid: Path) -> None:
    paths = [runtime, minime, astrid]
    if any(not path.is_absolute() for path in paths):
        raise ManifestError("runtime and daughter roots must be absolute")
    if len(set(paths)) != len(paths):
        raise ManifestError("runtime and daughter roots must be distinct")
    for left in paths:
        for right in paths:
            if left != right and (left in right.parents or right in left.parents):
                raise ManifestError("runtime and daughter roots must be disjoint")


def validate(payload: dict[str, Any], *, require_free_ports: bool = False) -> None:
    required = {
        "schema",
        "mode",
        "division_id",
        "plan_digest",
        "parent_generation",
        "candidate_hash",
        "parent_process_identity",
        "parent_deployment_identity",
        "runtime_dir",
        "ceremony_ledger",
        "minime_root",
        "astrid_root",
        "endpoints",
        "created_at_unix_ms",
        "expires_at_unix_ms",
    }
    if set(payload) != required or payload["schema"] != SCHEMA:
        raise ManifestError("manifest fields or schema are invalid")
    if payload["mode"] not in {"dormant", "candidate_bound"}:
        raise ManifestError("mode must be dormant or candidate_bound")
    if payload["mode"] == "dormant" and payload["candidate_hash"] != "unbound":
        raise ManifestError("dormant manifest candidate must be unbound")
    if payload["mode"] == "candidate_bound" and len(payload["candidate_hash"]) < 16:
        raise ManifestError("candidate-bound manifest needs an exact candidate hash")
    if (
        not payload["division_id"]
        or len(payload["plan_digest"]) < 16
        or not payload["parent_process_identity"]
        or not payload["parent_deployment_identity"]
        or int(payload["created_at_unix_ms"]) > int(payload["expires_at_unix_ms"])
    ):
        raise ManifestError("manifest identity or lifetime is invalid")
    require_absolute_disjoint(
        Path(payload["runtime_dir"]),
        Path(payload["minime_root"]),
        Path(payload["astrid_root"]),
    )
    expected = {
        name: f"127.0.0.1:{port}" for name, port in INTERNAL_PORTS.items()
    }
    if payload["endpoints"] != expected:
        raise ManifestError("internal endpoint allocation is not the frozen 7900-7906 map")
    if require_free_ports:
        for port in INTERNAL_PORTS.values():
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as error:
                    raise ManifestError(f"internal port {port} is occupied") from error


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp = Path(handle.name)
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    os.chmod(path, 0o600)


def create(args: argparse.Namespace) -> dict[str, Any]:
    now = int(time.time() * 1000)
    payload = {
        "schema": SCHEMA,
        "mode": args.mode,
        "division_id": args.division_id,
        "plan_digest": args.plan_digest,
        "parent_generation": args.parent_generation,
        "candidate_hash": args.candidate_hash,
        "parent_process_identity": args.parent_process_identity,
        "parent_deployment_identity": args.parent_deployment_identity,
        "runtime_dir": str(args.runtime_dir.resolve()),
        "ceremony_ledger": str(args.ceremony_ledger.resolve()),
        "minime_root": str(args.minime_root.resolve()),
        "astrid_root": str(args.astrid_root.resolve()),
        "endpoints": {
            name: f"127.0.0.1:{port}" for name, port in INTERNAL_PORTS.items()
        },
        "created_at_unix_ms": now,
        "expires_at_unix_ms": args.expires_at_unix_ms,
    }
    validate(payload, require_free_ports=args.require_free_ports)
    write_atomic(args.output, payload)
    return {
        "ok": True,
        "path": str(args.output),
        "manifest_sha256": sha256(args.output.read_bytes()),
        "mode": payload["mode"],
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    payload = json.loads(args.manifest.read_text())
    validate(payload, require_free_ports=args.require_free_ports)
    mode = args.manifest.stat().st_mode & 0o777
    if mode & 0o077:
        raise ManifestError("manifest must be owner-only")
    return {
        "ok": True,
        "path": str(args.manifest),
        "manifest_sha256": sha256(args.manifest.read_bytes()),
        "mode": payload["mode"],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    create_cmd = commands.add_parser("create")
    create_cmd.add_argument("--output", type=Path, required=True)
    create_cmd.add_argument(
        "--mode", choices=("dormant", "candidate_bound"), required=True
    )
    create_cmd.add_argument("--division-id", required=True)
    create_cmd.add_argument("--plan-digest", required=True)
    create_cmd.add_argument("--parent-generation", type=int, required=True)
    create_cmd.add_argument("--candidate-hash", required=True)
    create_cmd.add_argument("--parent-process-identity", required=True)
    create_cmd.add_argument("--parent-deployment-identity", required=True)
    create_cmd.add_argument("--runtime-dir", type=Path, required=True)
    create_cmd.add_argument("--ceremony-ledger", type=Path, required=True)
    create_cmd.add_argument("--minime-root", type=Path, required=True)
    create_cmd.add_argument("--astrid-root", type=Path, required=True)
    create_cmd.add_argument("--expires-at-unix-ms", type=int, required=True)
    create_cmd.add_argument("--require-free-ports", action="store_true")
    create_cmd.set_defaults(func=create)

    verify_cmd = commands.add_parser("verify")
    verify_cmd.add_argument("--manifest", type=Path, required=True)
    verify_cmd.add_argument("--require-free-ports", action="store_true")
    verify_cmd.set_defaults(func=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.func(args)
    except (OSError, json.JSONDecodeError, ManifestError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
