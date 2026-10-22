"""Thin, fail-closed adapter to the pinned shared public-web helper.

No HTTP client, command grammar, signing key, policy installation, or fallback.
Source equality is an in-process assertion, not remote runtime attestation.
Only the returned receipt is suitable for general logs; body/URL are payload.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import time
from typing import Any

from .deployment import source_inputs

BASE_DIR = Path(__file__).resolve().parents[1]
MAX_OUTPUT = 20 * 1024 * 1024
MAX_BODY = 4 * 1024 * 1024
HELPER_TIMEOUT = 125.0
MAX_METADATA = 65_536
REQUEST_SCHEMA = "astrid.public_web.request.v2"
RECEIPT_SCHEMA = "astrid.public_web.receipt.v2"
HELPER_CODES = frozenset("""
invalid_request invalid_config authority_unavailable untrusted_issuer
invalid_capability invalid_policy owner_mismatch invalid_state state_pending
invalid_approval stale_approval publication_failed revoked operation_not_granted
authority_changed unsafe_filesystem owner_busy storage_headroom unsafe_url
unsafe_address dns_failed transport_failed deadline body_limit incomplete_body
unsupported_encoding unsupported_media invalid_headers redirect_limit
invalid_redirect http_status
""".split())
LOCAL_CODES = frozenset("""
source_identity_unavailable source_changed owner_identity_unavailable
helper_unconfigured helper_identity_mismatch helper_changed helper_spawn_failed
helper_timeout helper_output_limit helper_failed invalid_helper_response
config_changed adapter_failed
""".split())


class PublicWebError(RuntimeError):
    """Content-free stable reason; never contains helper stderr or request text."""

    def __init__(self, code: str):
        self.code = code if code in HELPER_CODES | LOCAL_CODES else "adapter_failed"
        super().__init__(self.code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PublicWebError(code)


def _json(value: Any, *, sorted_keys: bool = False) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=sorted_keys,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def target_fingerprint(target: str) -> str:
    """Routine-log identity, never a URL, query, credential or source body."""
    return _hash(target.encode("utf-8"))


def source_not_delivered(agent, operation: str) -> None:
    agent._current_action_outcome_summary = (
        f"Requested {operation} incomplete: no readable source was delivered. "
        "No source was substituted and no reflection was generated. "
        "SEARCH, BROWSE with a public URL, SELF_STUDY MAP, MIKE_READ, writing "
        "and REST remain explicit choices. The previous reading position is unchanged."
    )
    event = getattr(agent, "_current_action_continuity_event", None)
    if isinstance(event, dict):
        event["continuity_action_result_v1"] = {
            "status": "failed", "reason": "web_source_not_delivered",
            "source_delivered": False, "generation_requested": False,
        }


def invalid_browse_choice(agent, chosen: str, state: dict) -> None:
    """Retain a rejected selection without scheduling an unrelated generation."""
    from . import action_scheduling
    summary = ("BROWSE reads web URLs only; no source was delivered or activity substituted. "
               "Choose BROWSE with a public HTTP(S) URL, SELF_STUDY MAP for catalog navigation, "
               "MIKE_READ for curated research, or REST.")
    store = agent._continuity_store()
    event = store.begin_action(chosen, chosen, "BROWSE", "web_recovery", state, source="next")
    agent._last_action_continuity_event = store.finish_action(event, "blocked", summary, state)
    agent._pending_notice_prompt = summary
    agent._pending_action_continuity_context = None
    action_scheduling.observation(agent, "web_source_selection_needed")


def _hex(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "invalid_helper_response")
        result[key] = value
    return result


def _parse(raw: bytes, code: str) -> dict:
    try:
        def invalid_constant(_):
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid_constant)
        _require(isinstance(value, dict), code)
        return value
    except (ValueError, TypeError, RecursionError, PublicWebError):
        raise PublicWebError(code) from None


def _path(path: Path, code: str) -> Path:
    _require(path.is_absolute() and ".." not in path.parts, code)
    _require(not any(part.is_symlink() for part in (path, *path.parents)), code)
    return path


def _read(path: Path, code: str, *, private: bool = False) -> bytes:
    try:
        path = _path(path, code)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                     and not info.st_mode & (0o077 if private else 0o022)
                     and info.st_size <= MAX_METADATA, code)
            raw = handle.read(MAX_METADATA + 1)
        _require(len(raw) <= MAX_METADATA, code)
        return raw
    except OSError:
        raise PublicWebError(code) from None


def _helper_identity(path: Path, pin: str) -> tuple:
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)
    try:
        path = _path(path, "helper_identity_mismatch")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.geteuid())
                     and not info.st_mode & 0o022 and info.st_mode & 0o111
                     and 0 < info.st_size <= 256 * 1024 * 1024,
                     "helper_identity_mismatch")
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
            _require(identity(os.fstat(handle.fileno())) == identity(info) and digest == pin,
                     "helper_identity_mismatch")
        _require(identity(path.stat()) == identity(info), "helper_identity_mismatch")
        return (*identity(info), digest)
    except OSError:
        raise PublicWebError("helper_identity_mismatch") from None


def _owner(agent) -> dict:
    startup = getattr(agent, "_agent_inputs_at_start", None)
    _require(isinstance(startup, dict) and bool(startup)
             and all(isinstance(key, str) and _hex(value) for key, value in startup.items())
             and {"minime_autonomy/runtime.py", "minime_autonomy/deployment.py",
                  "minime_autonomy/public_web.py"} <= startup.keys(),
             "source_identity_unavailable")
    try:
        snapshot = dict(startup)
        _require(source_inputs(BASE_DIR) == snapshot, "source_changed")
    except OSError:
        raise PublicWebError("source_identity_unavailable") from None
    # Match Rust default_self_control_root, reading only its public trust store.
    root = os.environ.get("MINIME_SELF_CONTROL_ROOT")
    if root is None:
        home = os.environ.get("HOME")
        root = str(Path(home) / ".minime/self-control-v2" if home is not None
                   else Path.cwd() / "workspace/self-control-v2")
    trust = _parse(_read(Path(root) / "trust.json", "owner_identity_unavailable"),
                   "owner_identity_unavailable")
    pins = trust.get("pinned_public_keys")
    _require(trust.get("schema") == "minime.self_control.trust_store.v1"
             and trust.get("target_being") == "minime" and isinstance(pins, dict)
             and _hex(pins.get("minime")), "owner_identity_unavailable")
    return {"being": "minime", "principal": "minime", "public_key_hex": pins["minime"],
            "deployment_identity": _hash(_json(snapshot, sorted_keys=True))}


def _context(agent) -> dict:
    owner = _owner(agent)
    helper = os.environ.get("MINIME_PUBLIC_WEB_HELPER")
    pin = os.environ.get("MINIME_PUBLIC_WEB_HELPER_SHA256")
    configured = os.environ.get("MINIME_PUBLIC_WEB_CONFIG")
    _require(bool(helper) and _hex(pin), "helper_unconfigured")
    _require(bool(configured), "invalid_config")
    helper = Path(helper)
    identity = _helper_identity(helper, pin)
    config_path = Path(configured)
    raw = _read(config_path, "invalid_config", private=True)
    config = _parse(raw, "invalid_config")
    _require(config.get("schema") == "astrid.public_web.config.v2"
             and _hex(config.get("expected_policy_sha256")), "invalid_config")
    _require(config.get("expected_owner") == owner, "owner_mismatch")
    return {"owner": owner, "helper": helper, "pin": pin, "identity": identity,
            "config_path": config_path, "config_raw": raw,
            "policy_sha256": config["expected_policy_sha256"]}


def _unchanged(agent, context: dict) -> None:
    _require(_owner(agent) == context["owner"], "owner_mismatch")
    _require(_read(context["config_path"], "invalid_config", private=True)
             == context["config_raw"], "config_changed")
    _require(_helper_identity(context["helper"], context["pin"]) == context["identity"],
             "helper_changed")


def _invoke(argv: list[str], wire: bytes = b"") -> tuple[int, bytes]:
    """Bound both pipe capture and wall time; stderr is never captured or logged."""
    process = None
    deadline = time.monotonic() + HELPER_TIMEOUT
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, shell=False, bufsize=0,
                                   close_fds=True, env={"PATH": os.defpath})
        output = bytearray()
        sent = 0
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            if wire:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE)
            else:
                process.stdin.close()
            while selector.get_map():
                remaining = deadline - time.monotonic()
                _require(remaining > 0, "helper_timeout")
                for key, _ in selector.select(remaining):
                    if key.fileobj is process.stdin:
                        try:
                            sent += os.write(key.fd, wire[sent:])
                        except BlockingIOError:
                            continue
                        if sent == len(wire):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        try:
                            chunk = os.read(key.fd, min(65_536, MAX_OUTPUT + 1 - len(output)))
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(process.stdout)
                        output.extend(chunk)
                        _require(len(output) <= MAX_OUTPUT, "helper_output_limit")
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "helper_timeout")
        return process.wait(timeout=remaining), bytes(output)
    except subprocess.TimeoutExpired:
        raise PublicWebError("helper_timeout") from None
    except OSError:
        raise PublicWebError("helper_spawn_failed" if process is None else "helper_failed") from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)
            process.stdin.close()
            process.stdout.close()


def _result(status: int, raw: bytes, request_hash: str | None = None) -> dict:
    _require(len(raw) <= MAX_OUTPUT, "helper_output_limit")
    value = _parse(raw, "invalid_helper_response")
    if status != 0:
        code = value.get("code")
        _require(value.get("complete") is False and isinstance(code, str)
                 and code in HELPER_CODES, "invalid_helper_response")
        if "request_sha256" in value:
            _require(value["request_sha256"] == request_hash, "invalid_helper_response")
        raise PublicWebError(code)
    _require("code" not in value and "error" not in value, "invalid_helper_response")
    return value


def _integer(value: Any, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _owner_hash(context: dict) -> str:
    owner = context["owner"]
    return _hash(_json([owner["being"], owner["principal"], owner["public_key_hex"]]))


def fetch(agent, operation: str, target: str) -> dict:
    """Return a validated PublicWebResponse dict, or a content-free error code."""
    try:
        _require(operation in ("search", "page") and isinstance(target, str)
                 and bool(target.strip()), "invalid_request")
        wire = _json({"schema": REQUEST_SCHEMA, "operation": operation, "target": target})
        _require(len(wire) <= 16_384, "invalid_request")
        context = _context(agent)
        status, raw = _invoke([str(context["helper"]), "fetch", "--config",
                               str(context["config_path"]), "--runtime-owner",
                               _json(context["owner"]).decode("utf-8")], wire)
        _unchanged(agent, context)
        value = _result(status, raw, _hash(wire))
        _require(set(value) == {"final_url", "content_type", "body", "receipt"},
                 "invalid_helper_response")
        receipt, body = value["receipt"], value["body"]
        _require(isinstance(receipt, dict) and isinstance(body, list) and len(body) <= MAX_BODY
                 and all(_integer(byte, 0, 255) for byte in body), "invalid_helper_response")
        _require(isinstance(value["final_url"], str) and len(value["final_url"]) <= 16_384
                 and value["content_type"] in ("text/html", "text/plain", "application/xhtml+xml",
                                                "application/json", "application/pdf"),
                 "invalid_helper_response")
        expected = {"schema": RECEIPT_SCHEMA, "complete": True,
                    "request_sha256": _hash(wire), "policy_sha256": context["policy_sha256"],
                    "owner_sha256": _owner_hash(context),
                    "final_url_sha256": _hash(value["final_url"].encode("utf-8")),
                    "body_sha256": _hash(bytes(body)), "http_status": 200}
        _require(set(receipt) == set(expected) | {"decoded_bytes_observed", "wire_bytes_observed",
                                                "redirects_followed"}
                 and receipt.get("complete") is True
                 and all(receipt.get(key) == item for key, item in expected.items())
                 and _integer(receipt.get("http_status"), 200, 200)
                 and _integer(receipt.get("decoded_bytes_observed"), len(body), MAX_BODY)
                 and _integer(receipt.get("wire_bytes_observed"), 0, MAX_BODY)
                 and _integer(receipt.get("redirects_followed"), 0, 5), "invalid_helper_response")
        return value
    except PublicWebError:
        raise
    except Exception:
        raise PublicWebError("adapter_failed") from None


def preview(agent, operation: str) -> dict:
    """Read-only availability observation, never a queue reservation or grant."""
    try:
        _require(operation in ("search", "page"), "invalid_request")
        context = _context(agent)
        status, raw = _invoke([str(context["helper"]), "preview", "--config",
                               str(context["config_path"])])
        _unchanged(agent, context)
        value = _result(status, raw)
        _require(set(value) == {"policy_sha256", "owner_sha256", "state_revision",
                                "expires_at_unix_ms", "operations", "limits", "implementation_scope"}
                 and value["policy_sha256"] == context["policy_sha256"]
                 and value["owner_sha256"] == _owner_hash(context)
                 and value["implementation_scope"] == "transport_foundation"
                 and _integer(value["state_revision"], 1, 2**64 - 1)
                 and _integer(value["expires_at_unix_ms"], int(time.time() * 1000) + 1, 2**64 - 1),
                 "invalid_helper_response")
        operations = value["operations"]
        _require(isinstance(operations, list) and 1 <= len(operations) <= 2
                 and all(item in ("search", "page") for item in operations)
                 and len(set(operations)) == len(operations), "invalid_helper_response")
        ceilings = {"decoded_body_bytes": MAX_BODY, "wire_body_bytes": MAX_BODY,
                    "total_timeout_ms": 120_000, "connect_timeout_ms": 5000,
                    "search_hop_timeout_ms": 10_000, "page_hop_timeout_ms": 15_000,
                    "redirects": 5, "storage_headroom_bytes": 2**64 - 1}
        limits = value["limits"]
        _require(isinstance(limits, dict) and set(limits) == set(ceilings)
                 and all(_integer(limits[key], 64 * 1024 * 1024 if key == "storage_headroom_bytes"
                                  else 0 if key == "redirects" else 1, ceiling)
                         for key, ceiling in ceilings.items()), "invalid_helper_response")
        _require(operation in operations, "operation_not_granted")
        return value
    except PublicWebError:
        raise
    except Exception:
        raise PublicWebError("adapter_failed") from None
