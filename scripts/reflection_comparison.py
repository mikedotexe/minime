#!/usr/bin/env python3
"""Run a digest-pinned, synthetic 24-result study on an owned Ollama process.

Continuations preserve completed samples. Retrying an operator-stopped attempt
requires explicit opt-in and a hash-bound witness. No live inputs/action dispatch.
Dynamic localhost ports are necessary for Ollama's runner: this is NOT universal
localhost isolation. Known live ports, Unix sockets and non-loopback are denied.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection, IncompleteRead
import json
import os
from pathlib import Path
import random
import re
import signal
import socket
import subprocess
import tempfile
import threading
import time

POLICY = "fresh-reflection-four-cell-v1"
SEEDS = [7, 17, 29, 43, 61]
MODEL = "gemma4:12b"
OPTIONS = {"temperature": 0.7, "top_p": 0.95, "num_predict": 4096, "num_ctx": 65536}
RESOURCE_POLICY = {"max_owned_rss_bytes": 14*1024**3, "min_system_free_percent": 13,
                   "launch_free_percent": 20, "deadline_seconds": 1800,
                   "one_active_generation": True, "hard_allocation_cap": False}
PROTECTED_PORTS = [3040, 7878, 7879, 7880, 7881, 7900, 7901, 7902, 8090, 8091, 8092, 11434]
NOTICE = ("\n\nMailbox availability: 2 file(s) await inspection. "
          "No message contents were supplied in this reflection. "
          "NEXT: CHECK_MAILBOX opens one eligible letter; CHECK_MAILBOX LARGE "
          "allows a larger letter. MAILBOX_STATUS inspects delivery state. "
          "Inspection and replies are optional; continuing reflection or REST remains available.")
MANIFEST = "manifests/registry.ollama.ai/library/gemma4/12b"
MAX_WIRE_BYTES = 1024**2
MAX_FILE_BYTES = 16*1024**2
MEASURE_TIMEOUT = 3
STOP_TIMEOUT = 5
RUBRIC = Path(__file__).resolve().parents[1] / "docs/steward-notes/2026-10-25-reflection-comparison.md"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_bytes(path):
    if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"invalid evidence file: {path.name}")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("evidence file grew beyond limit")
    return data


def read_json(path):
    return json.loads(read_bytes(path))


def save_bytes(path, data):
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def save(path, value):
    save_bytes(path, encoded(value) + b"\n")


def clean_env(home):
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), "TMPDIR": str(home / "tmp")}


def sandbox_profile(root, models, port, provider=None, *, network=True):
    # Deny ambient reads, including other homes/credentials. Permit dyld/OS
    # frameworks and only the selected executable's adjacent runtime libraries.
    provider = Path(provider or "/Applications/Ollama.app/Contents/Resources/ollama")
    directories = [root, Path("/System/Library"), Path("/usr/lib"),
                   Path("/Library/Apple/System/Library"), Path("/private/var/db/dyld"), provider.parent / "lib"]
    if provider.parent.name == "Resources" and provider.parent.parent.name == "Contents":
        # The packaged llama-server and Metal backends are siblings of ollama,
        # not necessarily under lib/. This is application code, not user state.
        directories.extend([provider.parent, provider.parent.parent / "Frameworks"])
    # macOS process startup needs the root directory itself, not its contents
    # recursively; denying this aborts before exec even for a permitted /bin/cat.
    literals = [Path("/"), provider, Path("/bin/cat"), Path("/dev/null"), Path("/dev/urandom"),
                Path("/dev/random"), Path("/private/etc/localtime"), *map(Path, models)]
    ancestors = sorted({str(parent) for path in directories + literals for parent in path.parents})
    quote = json.dumps
    reads = " ".join(f'(subpath {quote(str(p))})' for p in directories)
    reads += " " + " ".join(f'(literal {quote(str(p))})' for p in literals)
    metadata = " ".join(f'(literal {quote(p)})' for p in ancestors)
    networking = ""
    if network:
        if port in PROTECTED_PORTS:
            raise ValueError("isolated port conflicts with protected service")
        remote = " ".join(f'(remote ip "localhost:{p}")' for p in PROTECTED_PORTS)
        local = " ".join(f'(local ip "localhost:{p}")' for p in PROTECTED_PORTS)
        networking = f'''
; Internal runner needs dynamic loopback. Unlisted localhost services remain reachable.
(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
(deny network-outbound {remote})
(deny network-bind {local})
(deny network-inbound {local})'''
    return f'''(version 1)
(allow default)
(deny network*)
{networking}
(deny file-read*)
(allow file-read-metadata {metadata})
(allow file-read* {reads})
(deny file-write*)
(allow file-write* (subpath {quote(str(root))}) (literal "/dev/null"))
'''


def helper_frame(helper):
    with tempfile.TemporaryDirectory(prefix="synthetic-reflection-") as temp:
        root = Path(temp).resolve()
        for name in ("sources", "tmp"):
            (root / name).mkdir()
        profile = root / "helper.sb"
        save_bytes(profile, sandbox_profile(root, [], None, helper, network=False).encode())
        request = {"operation": "prepare", "action": "INTROSPECT",
                   "roots": {"astrid": str(root / "sources")}, "state_directory": str(root / "state"),
                   "runtime_workspace": str(root / "workspace"), "being": "minime"}
        result = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), str(helper)],
                                input=json.dumps(request), text=True, capture_output=True, check=True,
                                timeout=30, env=clean_env(root), cwd=root)
        output = json.loads(result.stdout)
        if output["input_kind"] != "reflection" or output["page"]:
            raise ValueError("helper did not prepare a synthetic reflection")
        return output


def schedule():
    order = [0, 1, 3, 2]
    jobs = []
    for index, seed in enumerate(SEEDS):
        shift = index % 4
        for cell in order[shift:] + order[:shift]:
            jobs.append({"cell": cell, "seed": seed, "repeat": False})
    jobs += [{"cell": cell, "seed": SEEDS[0], "repeat": True} for cell in [2, 3, 1, 0]]
    blinded = list(range(1, 25))
    random.Random(20261025).shuffle(blinded)
    for index, job in enumerate(jobs):
        job.update(id=f"job-{index+1:02d}", blind_id=f"sample-{blinded[index]:02d}")
    return jobs


def request_for(packet, job):
    return {"model": packet["model"], "messages": packet["cells"][job["cell"]]["messages"],
            "stream": False, "think": packet["think"], "keep_alive": 0,
            "options": packet["options"] | {"seed": job["seed"]}}


def validate_design(packet):
    expected = {"schema": POLICY, "model": MODEL, "options": OPTIONS, "think": False,
                "seeds": SEEDS, "jobs": schedule(), "resource_policy": RESOURCE_POLICY}
    for key, value in expected.items():
        if encoded(packet.get(key)) != encoded(value):
            raise ValueError(f"changed frozen {key}")
    cells = packet["cells"]
    if len(cells) != 4:
        raise ValueError("exactly four cells required")
    for index, cell in enumerate(cells):
        messages = cell["messages"]
        if (cell["legacy_notice"] is not (index % 2 == 0) or len(messages) != 2
                or [m["role"] for m in messages] != ["system", "user"]
                or any(not isinstance(m["content"], str) or not m["content"] for m in messages)
                or not messages[0]["content"].startswith("You are Minime.\n")
                or not isinstance(cell["scope_metadata"], str)):
            raise ValueError("invalid frozen cell")
    for on, off in (cells[:2], cells[2:]):
        if (on["messages"][0] != off["messages"][0]
                or on["messages"][1]["content"] != off["messages"][1]["content"] + NOTICE
                or on["scope_metadata"] != off["scope_metadata"]):
            raise ValueError("mailbox cells differ beyond the frozen notice")
    if cells[1]["messages"] == cells[3]["messages"]:
        raise ValueError("old and candidate frames must differ")


def manifest_blobs(manifest):
    blobs = {}
    for entry in [manifest["config"], *manifest["layers"]]:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", entry["digest"]):
            raise ValueError("invalid model blob digest")
        if type(entry["size"]) is not int or entry["size"] < 0:
            raise ValueError("invalid model blob size")
        name = entry["digest"].replace(":", "-")
        value = {"sha256": entry["digest"][7:], "bytes": entry["size"], "media_type": entry["mediaType"]}
        if name in blobs and blobs[name] != value:
            raise ValueError("conflicting model blob")
        blobs[name] = value
    return blobs


def validate_assets(packet):
    if len(packet["helpers"]) != 2:
        raise ValueError("two helper identities required")
    for entry in [*packet["helpers"], {"path": packet["provider"], "sha256": packet["provider_sha256"]}]:
        path = Path(entry["path"])
        if not path.is_absolute() or path.resolve() != path or file_hash(path) != entry["sha256"]:
            raise ValueError("provider/helper identity changed")
    models = Path(packet["model_root"])
    if not models.is_absolute() or models.resolve() != models:
        raise ValueError("model root must be canonical")
    raw = read_bytes(models / MANIFEST)
    if digest(raw) != packet["model_manifest_sha256"] or json.loads(raw) != packet["model_manifest"]:
        raise ValueError("model manifest identity changed")
    if packet["model_blobs"] != manifest_blobs(packet["model_manifest"]):
        raise ValueError("manifest/blob identity mismatch")
    for name, entry in packet["model_blobs"].items():
        path = models / "blobs" / name
        if path.is_symlink() or path.stat().st_size != entry["bytes"] or file_hash(path) != entry["sha256"]:
            raise ValueError("model blob identity changed")
    return raw


def validate_completion(response):
    """Accept terminal observations, not just nonempty, naturally stopped prose."""
    if (not isinstance(response, dict) or response.get("done") is not True
            or response.get("model") != MODEL or response.get("done_reason") not in ("stop", "length")
            or "error" in response or not isinstance(response.get("message"), dict)
            or response["message"].get("role") != "assistant"
            or not isinstance(response["message"].get("content"), str)):
        raise ValueError("nonterminal, malformed, errored or mismatched completion")
    ceiling_limited = response["done_reason"] == "length"
    # A provider stop marker is not proof that an argument is substantively complete.
    return {"protocol_terminal": True, "natural_ending": not ceiling_limited,
            "ceiling_limited": ceiling_limited, "text_incomplete": ceiling_limited,
            "empty_text": not response["message"]["content"].strip()}


def continuation_files(source, packet, retry_stopped):
    """Validate retained evidence without executing anything or displaying prose."""
    names = ["packet.json", "execution.json", "resource-receipt.json"]
    previous = read_json(source / "packet.json")
    validate_design(previous)
    for key in ("jobs", "cells", "model", "options", "think", "helpers", "provider", "provider_sha256",
                "model_manifest", "model_manifest_sha256", "model_blobs", "model_root"):
        if previous[key] != packet[key]:
            raise ValueError(f"continuation conflicts with prior {key}")
    execution = read_json(source / "execution.json")
    receipt = read_json(source / "resource-receipt.json")
    if execution["packet_sha256"] != digest(read_bytes(source / "packet.json")):
        raise ValueError("prior execution packet identity mismatch")
    if type(receipt.get("owned_provider_exit")) is not int:
        raise ValueError("prior provider has no terminal receipt")
    if receipt.get("cleanup_error"):
        raise ValueError("prior provider cleanup was not confirmed")
    isolated_name = "isolated-home/models/" + MANIFEST
    isolated_raw = read_bytes(source / isolated_name)
    if json.loads(isolated_raw) != packet["model_manifest"]:
        raise ValueError("prior isolated manifest contents differ")
    names.append(isolated_name)
    isolated_identity = {"sha256": digest(isolated_raw),
                         "source_sha256": packet["model_manifest_sha256"],
                         "raw_matches_source": digest(isolated_raw) == packet["model_manifest_sha256"],
                         "semantic_manifest_and_blobs_match": True,
                         "note": "JSON reserialization is setup provenance, not a weight change or sample exclusion."}
    completed, failed = [], []
    missing = False
    for job in packet["jobs"]:
        request_name, result_name = job["id"] + "-request.json", job["id"] + "-result.json"
        if not (source / result_name).exists():
            if (source / request_name).exists():
                raise ValueError("prior attempt lacks a terminal result")
            missing = True
            continue
        if missing or failed:
            raise ValueError("prior attempts are not a sequential terminal prefix")
        names.extend([request_name, result_name])
        raw_request = read_bytes(source / request_name)
        result = read_json(source / result_name)
        if json.loads(raw_request) != request_for(packet, job) or result["job"] != job:
            raise ValueError("conflicting prior request/result identity")
        if result.get("request_sha256") not in (None, digest(raw_request)):
            raise ValueError("prior request hash mismatch")
        if result.get("completed") is True:
            validate_completion(result["response"])
            if result.get("request_sha256") != digest(raw_request):
                raise ValueError("completed request is not hash-bound")
            completed.append(job["id"])
        elif result.get("completed") is False and result.get("error"):
            failed.append(job["id"])
        else:
            raise ValueError("ambiguous prior result")
    witness_path = source / "operator-stop.json"
    if failed or receipt.get("owned_group_empty") is not True:
        if not witness_path.exists():
            raise ValueError("prior terminal group requires operator-stop evidence")
        names.append("operator-stop.json")
        witness = read_json(witness_path)
        if (witness.get("schema") != "isolated_reflection_operator_stop_v1"
                or witness.get("signal") != "SIGTERM"
                or witness.get("remaining_group_members_after_signal") != []
                or witness.get("provider_exit_code") != 0 or receipt["owned_provider_exit"] != 0
                or type(witness.get("owned_provider_pid")) is not int or witness["owned_provider_pid"] <= 0
                or witness.get("owned_provider_pgid") != witness["owned_provider_pid"]
                or witness.get("verified_command") != packet["provider"] + " serve"
                or witness.get("response_prose_reviewed") is not False
                or witness.get("completed_jobs_retained") != completed or witness.get("interrupted_jobs") != failed
                or witness.get("packet_sha256") != execution["packet_sha256"]
                or witness.get("resource_receipt_sha256") != file_hash(source / "resource-receipt.json")
                or receipt.get("errors") or receipt.get("live_services_interrupted") is not False):
            raise ValueError("operator-stop evidence does not match terminal receipt")
        for job_id in failed:
            result_name = job_id + "-result.json"
            result = read_json(source / result_name)
            if (witness.get(job_id.replace("-", "_") + "_result_sha256") != file_hash(source / result_name)
                    or result["error"] != "Remote end closed connection without response"):
                raise ValueError("failed attempt is not the witnessed operator-stop disconnect")
    if failed:
        if not retry_stopped:
            raise ValueError("explicit --retry-stopped-attempts required; no automatic crash replay")
        names.append("failure.json")
        failure = read_json(source / "failure.json")
        if (failure.get("attempted") != len(completed) + len(failed) or failure.get("guard_errors")
                or failure.get("error") != "Remote end closed connection without response"):
            raise ValueError("prior failure does not match operator containment stop")
    return {"source": str(source), "files": {name: file_hash(source / name) for name in names},
            "completed_jobs": completed, "retry_jobs": failed, "isolated_manifest": isolated_identity}


def freeze(old, new, models, provider, out, *, continue_from=None, retry_stopped_attempts=False):
    if retry_stopped_attempts and continue_from is None:
        raise ValueError("retry opt-in requires --continue-from")
    out.mkdir()
    helpers = [{"path": str(p), "sha256": file_hash(p)} for p in (old, new)]
    if continue_from:
        cells = read_json(continue_from / "packet.json")["cells"]
    else:
        cells = []
        for frame in (helper_frame(old), helper_frame(new)):
            for notice in (True, False):
                cells.append({"messages": [{"role": "system", "content": "You are Minime.\n" + frame["system_prompt"]},
                                           {"role": "user", "content": frame["text"] + (NOTICE if notice else "")}],
                              "legacy_notice": notice, "scope_metadata": frame["evidence_scope"]})
    raw_manifest = read_bytes(models / MANIFEST)
    manifest = json.loads(raw_manifest)
    packet = {"schema": POLICY, "model": MODEL, "options": OPTIONS, "think": False,
              "seeds": SEEDS, "jobs": schedule(), "cells": cells,
              "cell_sha256": [digest(encoded(cell)) for cell in cells], "helpers": helpers,
              "model_manifest": manifest, "model_manifest_sha256": digest(raw_manifest),
              "model_blobs": manifest_blobs(manifest), "model_root": str(models),
              "provider": str(provider), "provider_sha256": file_hash(provider),
              "harness_sha256": file_hash(Path(__file__)), "resource_policy": RESOURCE_POLICY,
              "analysis": ["opening and phrase reuse", "administrative-context uptake", "unsupported mechanism claims", "substantive development"],
              "limits": "24 planned results; no outcome-dependent expansion. No prior prose, live mail, reservoir or action execution supplied to generation. Seed reproducibility is measured, not assumed."}
    rubric = read_bytes(RUBRIC)
    packet["rubric"] = {"source": str(RUBRIC), "sha256": digest(rubric)}
    save_bytes(out / "rubric.md", rubric)
    validate_design(packet)
    validate_assets(packet)  # Also catches helpers rebuilt during preparation.
    if continue_from:
        continuation = continuation_files(continue_from, packet, retry_stopped_attempts)
        packet["continuation"] = continuation
        prior = out / "prior"
        prior.mkdir()
        for name, expected in continuation["files"].items():
            data = read_bytes(continue_from / name)
            if digest(data) != expected:
                raise ValueError("continuation evidence changed while importing")
            (prior / name).parent.mkdir(parents=True, exist_ok=True)
            save_bytes(prior / name, data)
        for job_id in continuation["completed_jobs"]:
            for suffix in ("-request.json", "-result.json"):
                save_bytes(out / (job_id + suffix), read_bytes(prior / (job_id + suffix)))
    save(out / "packet.json", packet)
    save_bytes(out / "packet.sha256", (file_hash(out / "packet.json") + "\n").encode())
    return packet


def load_packet(out, expected_sha256):
    raw = read_bytes(out / "packet.json")
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") or digest(raw) != expected_sha256
            or read_bytes(out / "packet.sha256").decode().strip() != expected_sha256):
        raise ValueError("packet does not match the explicitly pinned digest")
    packet = json.loads(raw)
    validate_design(packet)
    if packet["cell_sha256"] != [digest(encoded(cell)) for cell in packet["cells"]]:
        raise ValueError("frozen cell identity mismatch")
    if packet["harness_sha256"] != file_hash(Path(__file__)):
        raise ValueError("harness changed since preregistration")
    if digest(read_bytes(out / "rubric.md")) != packet["rubric"]["sha256"]:
        raise ValueError("frozen blind rubric changed")
    validate_assets(packet)
    if "continuation" in packet:
        prior = out / "prior"
        expected = packet["continuation"]
        for name, sha in expected["files"].items():
            if Path(name).is_absolute() or ".." in Path(name).parts or file_hash(prior / name) != sha:
                raise ValueError("continuation evidence identity mismatch")
        actual = continuation_files(prior, packet, bool(expected["retry_jobs"]))
        if any(actual[key] != expected[key] for key in ("files", "completed_jobs", "retry_jobs", "isolated_manifest")):
            raise ValueError("continuation plan changed")
        for job_id in expected["completed_jobs"]:
            for suffix in ("-request.json", "-result.json"):
                name = job_id + suffix
                if file_hash(out / name) != expected["files"][name]:
                    raise ValueError("imported completion changed")
    return packet


def free_percent():
    value = subprocess.check_output(["/usr/bin/memory_pressure", "-Q"], text=True, timeout=MEASURE_TIMEOUT)
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", value)
    if not match:
        raise RuntimeError("memory headroom unavailable")
    return int(match[1])


def group_rss(pgid):
    rows = subprocess.check_output(["/bin/ps", "-axo", "pgid=,rss="], text=True, timeout=MEASURE_TIMEOUT)
    return sum(int(parts[1])*1024 for row in rows.splitlines()
               if len(parts := row.split()) == 2 and int(parts[0]) == pgid)


def signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Darwin can report EPERM while the last process is exiting. Establish
        # absence independently; never interpret a denied signal as termination.
        rows = subprocess.check_output(["/bin/ps", "-axo", "pgid="], text=True, timeout=MEASURE_TIMEOUT)
        if not any(int(row.strip()) == pgid for row in rows.splitlines() if row.strip()):
            return False
        if sig == 0:
            return True
        raise


def stop_owned(process):
    # A dead/reaped leader does not establish that its runner group is empty.
    process.poll()
    signal_group(process.pid, signal.SIGTERM)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        deadline = time.monotonic() + STOP_TIMEOUT
        while signal_group(process.pid, 0):
            process.poll()
            if time.monotonic() >= deadline:
                break
            time.sleep(.05)
        else:
            process.wait(timeout=STOP_TIMEOUT)
            return True
        if sig == signal.SIGTERM:
            signal_group(process.pid, signal.SIGKILL)
    raise RuntimeError("owned process group did not become empty after SIGKILL")


class RunInterrupted(KeyboardInterrupt):
    pass


@contextmanager
def interruptions():
    state, old = [], {}
    def retain(signum, _frame):
        state.append(signum)
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old[sig] = signal.signal(sig, retain)
        yield state
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


class Guard:
    """Deadline watcher is independent of bounded but potentially slow RSS probes."""
    def __init__(self, process, interrupted):
        self.process, self.interrupted = process, interrupted
        self.finished = threading.Event()
        self.errors, self.measurements = [], []
        self.deadline = None
        self.lock = threading.Lock()
        self.threads = []

    def fail(self, reason):
        with self.lock:
            if self.errors:
                return
            self.errors.append(reason)
        try:
            signal_group(self.process.pid, signal.SIGKILL)
        except OSError as error:
            self.errors.append(f"owned stop failed: {error}")

    def check(self):
        if self.interrupted:
            self.fail(f"interrupted by signal {self.interrupted[0]}")
            raise RunInterrupted(self.errors[0])
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.fail("monotonic wall deadline reached")
        if self.process.poll() is not None:
            self.fail("owned provider stopped; stopping remaining group members")
        if self.errors:
            raise RuntimeError(self.errors[0])

    def watch(self):
        while not self.finished.wait(.1):
            try:
                self.check()
            except BaseException:
                return

    def measure(self):
        while not self.finished.is_set():
            try:
                row = {"time": time.time(), "free_percent": free_percent(), "owned_rss_bytes": group_rss(self.process.pid)}
                self.measurements.append(row)
                if (row["free_percent"] < RESOURCE_POLICY["min_system_free_percent"]
                        or row["owned_rss_bytes"] > RESOURCE_POLICY["max_owned_rss_bytes"]):
                    raise RuntimeError("resource boundary reached")
            except Exception as error:
                self.fail(f"resource monitor: {type(error).__name__}: {error}")
                return
            if self.finished.wait(2):
                return

    def start(self):
        for target in (self.watch, self.measure):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.finished.set()
        for thread in self.threads:
            thread.join(timeout=2*MEASURE_TIMEOUT + 1)
        return stop_owned(self.process)


def http(port, path, payload=None, timeout=10, evidence_path=None):
    """Direct connection: no ambient proxies, redirects or unbounded wire retention."""
    connection = HTTPConnection("127.0.0.1", port, timeout=timeout)
    transport, raw = [], bytearray()
    expired = threading.Event()
    status, error, response = None, None, None
    deadline = time.monotonic() + timeout
    def expire():
        expired.set()
        if transport:
            try:
                transport[0].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        connection.connect()
        transport.append(connection.sock)
        if expired.is_set():
            raise TimeoutError("HTTP wall deadline reached")
        connection.request("GET" if payload is None else "POST", path,
                           body=None if payload is None else encoded(payload), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        status = response.status
        while len(raw) <= MAX_WIRE_BYTES:
            if expired.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("HTTP wall deadline reached")
            chunk = response.read1(min(65536, MAX_WIRE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if expired.is_set() or time.monotonic() >= deadline:
            raise TimeoutError("HTTP wall deadline reached")
        if len(raw) > MAX_WIRE_BYTES:
            raise ValueError("provider response exceeded bounded wire allowance")
        if status != 200:
            raise RuntimeError(f"provider HTTP status {status}")
        return json.loads(raw)
    except BaseException as exc:
        if isinstance(exc, IncompleteRead):
            raw.extend(exc.partial[:max(0, MAX_WIRE_BYTES + 1 - len(raw))])
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        timer.cancel()
        if response is not None:
            response.close()
        connection.close()
        if evidence_path is not None:
            retained = bytes(raw[:MAX_WIRE_BYTES])
            save(evidence_path, {"status": status, "body_base64": base64.b64encode(retained).decode(),
                 "retained_bytes": len(retained), "observed_bytes": len(raw), "retained_sha256": digest(retained),
                 "truncated": len(raw) > MAX_WIRE_BYTES, "error": error, "deadline_expired": expired.is_set()})


def probe_sandbox(profile_path, out, env):
    positive = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile_path), "/bin/cat", str(out / "packet.json")],
                              env=env, cwd=out, capture_output=True, timeout=MEASURE_TIMEOUT)
    if positive.returncode != 0:
        raise RuntimeError("sandbox could not read approved packet: " + positive.stderr.decode(errors="replace")[:500])
    # Owned synthetic canary, never a production file or credential.
    with tempfile.TemporaryDirectory(prefix="reflection-denial-probe-") as temp:
        canary = Path(temp).resolve() / "canary"
        save_bytes(canary, b"synthetic deny probe\n")
        probe = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile_path), "/bin/cat", str(canary)],
                               env=env, cwd=out, capture_output=True, timeout=MEASURE_TIMEOUT)
        if probe.returncode == 0 or b"Operation not permitted" not in probe.stderr:
            raise RuntimeError("sandbox did not deny unapproved reads")


def verify_listener(process, port):
    output = subprocess.check_output(["/usr/sbin/lsof", "-nP", "-a", f"-iTCP:{port}",
                                      "-sTCP:LISTEN", "-Fp"], text=True, timeout=MEASURE_TIMEOUT)
    if {line for line in output.splitlines() if line.startswith("p")} != {f"p{process.pid}"}:
        raise RuntimeError("listener is not the owned provider")


def execute(out, expected_sha256):
    packet = load_packet(out, expected_sha256)
    if (out / "execution.json").exists():
        raise ValueError("execution already attempted; no automatic replay")
    if free_percent() < RESOURCE_POLICY["launch_free_percent"]:
        raise RuntimeError("isolated launch needs 20% system headroom")
    home = out / "isolated-home"
    home.mkdir()
    model_copy = home / "models"
    target = model_copy / MANIFEST
    target.parent.mkdir(parents=True)
    save_bytes(target, read_bytes(Path(packet["model_root"]) / MANIFEST))
    if file_hash(target) != packet["model_manifest_sha256"]:
        raise ValueError("isolated manifest is not byte-identical to frozen source")
    (model_copy / "blobs").mkdir()
    blobs = [Path(packet["model_root"]) / "blobs" / name for name in packet["model_blobs"]]
    for blob in blobs:
        (model_copy / "blobs" / blob.name).symlink_to(blob)
    (home / "tmp").mkdir()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    profile_path = out / "isolation.sb"
    save_bytes(profile_path, sandbox_profile(out, blobs, port, Path(packet["provider"])).encode())
    env = clean_env(home) | {"OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(model_copy),
          "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_QUEUE": "1",
          "OLLAMA_KEEP_ALIVE": "0", "OLLAMA_CONTEXT_LENGTH": str(OPTIONS["num_ctx"]), "OLLAMA_NO_CLOUD": "1"}
    probe_sandbox(profile_path, out, env)
    process = guard = log = None
    results = []
    summary = None
    imported = set(packet.get("continuation", {}).get("completed_jobs", []))
    with interruptions() as interrupted:
        try:
            save(out / "execution.json", {"packet_sha256": expected_sha256, "isolated_port": port,
                 "isolated_manifest_sha256": file_hash(target),
                 "isolation_sha256": file_hash(profile_path), "synthetic_read_probe_denied": True,
                 "localhost_boundary": "dynamic loopback allowed except protected ports; Unix/non-loopback denied",
                 "started_at": time.time()})
            if interrupted:
                raise RunInterrupted("interrupted before provider launch")
            log = (out / "provider.log").open("x")
            process = subprocess.Popen(["/usr/bin/sandbox-exec", "-f", str(profile_path), packet["provider"], "serve"],
                                       env=env, cwd=home, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            guard = Guard(process, interrupted)
            guard.deadline = time.monotonic() + 30
            guard.start()
            while True:
                guard.check()
                try:
                    verify_listener(process, port)
                    version = http(port, "/api/version", timeout=min(10, guard.deadline - time.monotonic()))
                    break
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    guard.check()
                    time.sleep(.1)
            guard.check()
            show = http(port, "/api/show", {"model": MODEL})
            guard.check()
            guard.deadline = None
            save(out / "provider-identity.json", {"version": version, "show": show,
                 "owned_pid": process.pid, "owned_pgid": process.pid, "provider_sha256": packet["provider_sha256"]})
            for job in packet["jobs"]:
                if job["id"] in imported:
                    results.append(read_json(out / (job["id"] + "-result.json")))
                    continue
                guard.check()
                verify_listener(process, port)
                request_path = out / (job["id"] + "-request.json")
                payload = request_for(packet, job)
                save(request_path, payload)
                start = time.monotonic()
                record = {"job": job, "completed": False, "request_sha256": file_hash(request_path)}
                try:
                    guard.deadline = start + RESOURCE_POLICY["deadline_seconds"]
                    response = http(port, "/api/chat", payload, timeout=RESOURCE_POLICY["deadline_seconds"],
                                    evidence_path=out / (job["id"] + "-wire.json"))
                    record["response"] = response
                    guard.check()
                    record.update(validate_completion(response))
                    # Completed means a valid terminal sample, including silence/length.
                    record["completed"] = True
                except BaseException as error:
                    record.update(error=str(error) or type(error).__name__, error_type=type(error).__name__)
                    raise
                finally:
                    guard.deadline = None
                    record["wall_seconds"] = time.monotonic() - start
                    save(out / (job["id"] + "-result.json"), record)
                    results.append(record)
                print(f"{job['id']} retained; completed=True", flush=True)
            guard.check()
            # Derive labels for imported samples without rewriting their original bytes.
            endings = [validate_completion(r["response"]) for r in results]
            review = [{"id": r["job"]["blind_id"], "text": r["response"]["message"]["content"], **ending}
                      for r, ending in zip(results, endings)]
            save(out / "blind-review.json", sorted(review, key=lambda x: x["id"]))
            repetitions = []
            for cell in range(4):
                texts = [r["response"]["message"]["content"] for r in results
                         if r["job"]["cell"] == cell and r["job"]["seed"] == SEEDS[0]]
                exact_match = texts[0] == texts[1]
                empty_pair = all(not text.strip() for text in texts)
                repetitions.append({"cell": cell, "exact_text_match": exact_match,
                                    "empty_pair_trivial": empty_pair,
                                    "nonempty_exact_text_match": exact_match and not empty_pair})
            summary = {"schema": POLICY, "attempts": len(results), "completed": len(results),
                 "imported": len(imported), "generated_this_run": len(results) - len(imported),
                 "protocol_terminal": sum(e["protocol_terminal"] for e in endings),
                 "natural_endings": sum(e["natural_ending"] for e in endings),
                 "ceiling_limited": sum(e["ceiling_limited"] for e in endings),
                 "empty_stops": sum(e["empty_text"] and e["natural_ending"] for e in endings),
                 "seed_repeats": repetitions, "completion_reasons": dict(Counter(r["response"]["done_reason"] for r in results)),
                 "review_required": True, "effects_on_beings_or_reservoir": "not tested"}
        except BaseException as error:
            save(out / "failure.json", {"error": str(error) or type(error).__name__, "error_type": type(error).__name__,
                 "attempted": len(results), "guard_errors": guard.errors if guard else []})
            raise
        finally:
            empty, cleanup_error = process is None, None
            try:
                if process is not None:
                    empty = guard.close() if guard else stop_owned(process)
            except BaseException as error:
                cleanup_error = f"{type(error).__name__}: {error}"
                raise
            finally:
                if log is not None:
                    log.close()
                save(out / "resource-receipt.json", {"measurements": guard.measurements if guard else [],
                     "errors": guard.errors if guard else [], "cleanup_error": cleanup_error,
                     "owned_provider_exit": process.returncode if process else None,
                     "owned_pgid": process.pid if process else None, "owned_group_empty": empty,
                     "interruption_signals": interrupted, "live_services_interrupted": False})
    # A normal completion summary requires successful cleanup and its durable receipt.
    save(out / "summary.json", summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    prepare = sub.add_parser("freeze")
    for name in ["old-helper", "new-helper", "models", "provider", "out"]:
        prepare.add_argument("--" + name, type=Path, required=True)
    prepare.add_argument("--continue-from", type=Path)
    prepare.add_argument("--retry-stopped-attempts", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--packet-dir", type=Path, required=True)
    run.add_argument("--packet-sha256", required=True, help="explicitly reviewed frozen packet digest")
    args = parser.parse_args()
    if args.operation == "freeze":
        freeze(args.old_helper.resolve(), args.new_helper.resolve(), args.models.resolve(), args.provider.resolve(),
               args.out.absolute(), continue_from=args.continue_from.resolve() if args.continue_from else None,
               retry_stopped_attempts=args.retry_stopped_attempts)
        print("Frozen packet SHA-256:", file_hash(args.out / "packet.json"))
    else:
        execute(args.packet_dir.resolve(), args.packet_sha256)


if __name__ == "__main__":
    main()
