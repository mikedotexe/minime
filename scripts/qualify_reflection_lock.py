#!/usr/bin/env python3
"""Bounded two-process reflection admission probe; synthetic retained state only.

Run with -I -B. Each round gets a fresh owned workspace; no state is deleted.
Production mode leaves runtime functions unchanged. Trace mode observes the
same os.open call, never retries it and never changes its flags.
"""
import argparse
import collections
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import selectors
import stat
import subprocess
import sys
import tempfile
import time
import traceback


INPUT = "a" * 64
FILES = ("minime_autonomy/__init__.py", "minime_autonomy/mailbox_fs.py",
         "minime_autonomy/reflection_publication.py")
DEFAULT_PARENT = "/Users/v/other/minime"
DEFAULT_CANDIDATE = "/Users/v/other/worktrees/reflection-finalization-20261026/minime"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def inventory(source):
    return {name: {"sha256": sha((source / name).read_bytes()),
                   "bytes": (source / name).stat().st_size} for name in FILES}


def info(value):
    return {name: getattr(value, name) for name in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}


def error_record(error):
    return {"type": type(error).__name__, "message": str(error),
            "errno": getattr(error, "errno", None),
            "filename": getattr(error, "filename", None),
            "filename2": getattr(error, "filename2", None)}


def observed(call):
    try:
        return call()
    except OSError as error:
        return {"error": error_record(error)}


def path_state(workspace, fd=None):
    family = workspace / "runtime/reflection_publications"
    result = {str(path.relative_to(workspace)) or ".": observed(lambda p=path: info(p.lstat()))
              for path in (workspace, workspace / "runtime", family, family / ".transaction.lock")}
    if fd is not None:
        result["dir_fd"] = fd
        result["fd_identity"] = observed(lambda: info(os.fstat(fd)))
        result["fd_lock_identity"] = observed(lambda: info(os.stat(
            ".transaction.lock", dir_fd=fd, follow_symlinks=False)))
        result["fd_names"] = observed(lambda: sorted(os.listdir(fd)))
    return result


def snapshot(workspace):
    result = {}
    for directory, dirs, files in os.walk(workspace, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            entry = info(path.lstat())
            if stat.S_ISREG(entry["st_mode"]):
                if entry["st_size"] > 16384:
                    raise ValueError("synthetic receipt exceeds 16 KiB")
                entry["sha256"] = sha(path.read_bytes())
            result[str(path.relative_to(workspace))] = entry
    return result


def validate_records(workspace):
    family = workspace / "runtime/reflection_publications"
    records, problems = {}, []
    if not family.exists():
        return {"records": {}, "problems": ["family_missing"], "one_owner": False}
    for path in sorted(family.iterdir()):
        if path.name == ".transaction.lock":
            continue
        if not path.name.startswith(("action-", "input-")) or path.suffix != ".json":
            problems.append("unexpected_entry:" + path.name)
            continue
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate field")
                    result[key] = value
                return result
            raw = path.read_bytes()
            envelope = json.loads(raw, object_pairs_hook=unique)
            if set(envelope) != {"record", "sha256"} or sha(canonical(envelope["record"])) != envelope["sha256"]:
                raise ValueError("invalid envelope")
            records[path.name] = envelope["record"]
        except (OSError, ValueError, TypeError) as error:
            problems.append(path.name + ":" + str(error))
    actions = {name: value for name, value in records.items() if name.startswith("action-")}
    indexes = {name: value for name, value in records.items() if name.startswith("input-")}
    if len(actions) != 1 or len(indexes) != 1:
        problems.append("expected_one_action_and_one_input")
    for name, record in actions.items():
        binding = record.get("binding", {})
        expected_name = "action-" + sha(str(binding.get("action_id")).encode()) + ".json"
        if (name != expected_name or binding.get("owner") != "minime"
                or binding.get("input_id") != INPUT or record.get("stage") != "reserved"):
            problems.append("invalid_action:" + name)
        expected_index = {"schema": record["schema"], "action_file": name,
                          "binding_sha256": sha(canonical(binding))}
        if indexes.get("input-" + INPUT + ".json") != expected_index:
            problems.append("input_binding_mismatch:" + name)
    return {"records": records, "problems": problems, "one_owner": not problems}


def worker(args):
    source = Path(args.source).resolve(strict=True)
    workspace = Path(args.workspace).resolve(strict=True)
    result = {"pid": os.getpid(), "source": str(source), "workspace": str(workspace),
              "action": args.action, "mode": args.mode, "events": []}
    # -B forbids writes but not stale pyc reads. Use an absent owned cache root.
    sys.pycache_prefix = str(workspace.parent / "never-written-pycache")
    sys.path.insert(0, str(source))
    before = inventory(source)
    publication = importlib.import_module("minime_autonomy.reflection_publication")
    fs = importlib.import_module("minime_autonomy.mailbox_fs")
    result["source_before"] = before
    result["module_paths"] = {module.__name__: str(Path(module.__file__).resolve())
                              for module in (publication, fs)}
    if any(not Path(path).is_relative_to(source) for path in result["module_paths"].values()):
        raise RuntimeError("worker imported the wrong source")
    if inventory(source) != before:
        raise RuntimeError("source changed during import")
    real_open = os.open
    if args.mode == "trace":
        def trace_open(path, flags, mode=0o777, *, dir_fd=None):
            if path != ".transaction.lock" or dir_fd is None:
                return real_open(path, flags, mode, dir_fd=dir_fd)
            event = {"call": "os.open", "path": path, "flags": flags, "mode": mode,
                     "flag_names": [name for name in ("O_RDWR", "O_CREAT", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
                                    if flags & getattr(os, name)],
                     "before": path_state(workspace, dir_fd), "start_ns": time.monotonic_ns()}
            try:
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
            except OSError as error:
                event.update(error=error_record(error), end_ns=time.monotonic_ns(),
                             after=path_state(workspace, dir_fd))
                result["events"].append(event)
                raise
            event.update(fd=descriptor, identity=info(os.fstat(descriptor)),
                         end_ns=time.monotonic_ns(), after=path_state(workspace, dir_fd))
            result["events"].append(event)
            return descriptor
        fs.os.open = trace_open
    print(json.dumps({"ready": True, "pid": os.getpid(), "source": before}), flush=True)
    if os.read(args.barrier_fd, 1) != b"G":
        raise RuntimeError("shared start barrier was not released")
    os.close(args.barrier_fd)
    result["begin_ns"] = time.monotonic_ns()
    try:
        publication.ReflectionPublication.begin(workspace, args.action, INPUT)
        result["outcome"] = "reserved"
    except publication.RecoveryRequired as error:
        result.update(outcome="refused", error=error_record(error))
    except BaseException as error:
        result.update(outcome="error", error=error_record(error), traceback=traceback.format_exc())
    finally:
        result["end_ns"] = time.monotonic_ns()
        fs.os.open = real_open
    result["path_state_after_return"] = path_state(workspace)
    result["source_after"] = inventory(source)
    result["source_stable"] = result["source_after"] == before
    write_json(Path(args.result), result)
    return 0 if result["outcome"] in {"reserved", "refused"} and result["source_stable"] else 1


def wait_ready(workers, timeout):
    ready = []
    with selectors.DefaultSelector() as selector:
        for index, process in enumerate(workers):
            selector.register(process.stdout, selectors.EVENT_READ, index)
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("worker readiness timeout")
            for key, _ in selector.select(remaining):
                line = key.fileobj.readline()
                value = json.loads(line)
                if value.get("ready") is not True:
                    raise RuntimeError("worker did not reach barrier")
                ready.append({"worker": key.data, **value})
                selector.unregister(key.fileobj)
    return ready


def one_round(args, source, directory, expected_source):
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700)
    before = snapshot(workspace)
    read_fd, write_fd = os.pipe()
    workers, records, failure = [], [], None
    try:
        for index in range(2):
            result_path = directory / f"worker-{index}.json"
            command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker",
                       "--source", str(source), "--workspace", str(workspace),
                       "--action", f"act_race_{index}", "--result", str(result_path),
                       "--barrier-fd", str(read_fd), "--mode", args.mode]
            process = subprocess.Popen(command, cwd=source, pass_fds=(read_fd,),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            workers.append(process)
        os.close(read_fd)
        read_fd = None
        ready = wait_ready(workers, args.timeout)
        if any(item["source"] != expected_source for item in ready):
            raise RuntimeError("source differs from run manifest")
        released_ns = time.monotonic_ns()
        os.write(write_fd, b"GG")
        os.close(write_fd)
        write_fd = None
        for index, process in enumerate(workers):
            stdout, stderr = process.communicate(timeout=args.timeout)
            result_path = directory / f"worker-{index}.json"
            record = json.loads(result_path.read_text()) if result_path.exists() else {"outcome": "missing_result"}
            records.append({"returncode": process.returncode, "stdout": stdout, "stderr": stderr, **record})
    except BaseException as error:
        failure = {"error": error_record(error), "traceback": traceback.format_exc()}
    finally:
        for descriptor in (read_fd, write_fd):
            if descriptor is not None:
                os.close(descriptor)
        # Only the two child PIDs created by this round are ever signaled.
        for process in workers:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
    after = snapshot(workspace)
    validation = validate_records(workspace)
    after_inspection = snapshot(workspace)
    outcomes = sorted(record.get("outcome", "missing") for record in records)
    source_after = inventory(source)
    result = {"workspace": str(workspace), "source": str(source), "mode": args.mode,
              "workers": records, "harness_failure": failure,
              "barrier_release_ns": locals().get("released_ns"),
              "before": before, "after": after, "validation": validation,
              "inspection_preserved_records": after == after_inspection,
              "source_stable": source_after == expected_source,
              "expected_outcomes": outcomes == ["refused", "reserved"]}
    result["ok"] = (not failure and result["expected_outcomes"] and validation["one_owner"]
                    and result["inspection_preserved_records"] and result["source_stable"]
                    and all(record.get("source_stable") and record["returncode"] == 0 for record in records))
    write_json(directory / "round.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, default=Path(DEFAULT_PARENT))
    parser.add_argument("--candidate", type=Path, default=Path(DEFAULT_CANDIDATE))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--mode", choices=("production", "trace"), default="production")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source", help=argparse.SUPPRESS)
    parser.add_argument("--workspace", help=argparse.SUPPRESS)
    parser.add_argument("--action", help=argparse.SUPPRESS)
    parser.add_argument("--result", help=argparse.SUPPRESS)
    parser.add_argument("--barrier-fd", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    if not args.output or not 1 <= args.rounds <= 1000 or not 1 <= args.timeout <= 60:
        parser.error("new --output required; --rounds 1..1000 and --timeout 1..60")
    output = args.output.absolute()
    output.mkdir(mode=0o700)
    sources = {"parent": args.parent.resolve(strict=True), "candidate": args.candidate.resolve(strict=True)}
    inventories = {name: inventory(path) for name, path in sources.items()}
    manifest = {"schema": "reflection_lock_probe_v1", "created_ns": time.time_ns(),
                "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                "script_sha256": sha(Path(__file__).read_bytes()), "rounds_per_source": args.rounds,
                "mode": args.mode, "max_workers": 2, "timeout_seconds": args.timeout,
                "sources": {name: {"path": str(path), "files": inventories[name]} for name, path in sources.items()},
                "state_policy": "fresh_owned_retained_each_round_no_cleanup_no_live_state",
                "flags_policy": "unchanged_single_os_open_no_retry_no_nofollow_weakening"}
    write_json(output / "manifest.json", manifest)
    counters = {name: collections.Counter() for name in sources}
    failures = []
    # Alternating sources keeps the two cohorts close in time without overlap.
    for round_number in range(args.rounds):
        for label, source in sources.items():
            directory = Path(tempfile.mkdtemp(prefix=f"{label}-{round_number:04d}-", dir=output))
            result = one_round(args, source, directory, inventories[label])
            counters[label]["rounds"] += 1
            counters[label]["ok" if result["ok"] else "failed"] += 1
            for record in result["workers"]:
                counters[label]["worker_" + record.get("outcome", "missing")] += 1
            if not result["ok"]:
                failures.append(str(directory / "round.json"))
                print(json.dumps({"failure": failures[-1], "workers": [
                    {key: record.get(key) for key in ("outcome", "error")} for record in result["workers"]]}), flush=True)
            if not result["source_stable"] or result["harness_failure"]:
                write_json(output / "aborted.json", {"round": str(directory), "counters": counters})
                return 2
        if (round_number + 1) % 10 == 0:
            print(json.dumps({"completed_per_source": round_number + 1, "counters": counters}), flush=True)
    summary = {"counters": counters, "failures": failures, "max_workers": 2,
               "all_state_retained": True, "production_changes": False,
               "interpretation": "A passing rerun does not clear the original unexplained qualification failure."}
    write_json(output / "summary.json", summary)
    print(json.dumps({"summary": str(output / "summary.json"), **summary}), flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
