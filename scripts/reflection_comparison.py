#!/usr/bin/env python3
"""Preregister and run 24 synthetic reflections on an owned isolated Ollama server.

Never uses a running provider, live letters, reservoir handles or action dispatch.
An interrupted cell is retained and never implicitly replayed. The prompt release
does not depend on this experiment completing.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
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
import urllib.request

POLICY = "fresh-reflection-four-cell-v1"
SEEDS = [7, 17, 29, 43, 61]
MODEL = "gemma4:12b"
OPTIONS = {"temperature": 0.7, "top_p": 0.95, "num_predict": 4096, "num_ctx": 65536}
PROTECTED_PORTS = [7878, 7879, 7880, 8090, 8091, 8092, 11434]
NOTICE = ("\n\nMailbox availability: 2 file(s) await inspection. "
          "No message contents were supplied in this reflection. "
          "NEXT: CHECK_MAILBOX opens one eligible letter; CHECK_MAILBOX LARGE "
          "allows a larger letter. MAILBOX_STATUS inspects delivery state. "
          "Inspection and replies are optional; continuing reflection or REST remains available.")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def helper_frame(helper):
    with tempfile.TemporaryDirectory(prefix="synthetic-reflection-") as temp:
        root = Path(temp)
        (root / "sources").mkdir()
        request = {"operation": "prepare", "action": "INTROSPECT",
                   "roots": {"astrid": str(root / "sources")},
                   "state_directory": str(root / "state"),
                   "runtime_workspace": str(root / "workspace"), "being": "minime"}
        result = subprocess.run([str(helper)], input=json.dumps(request), text=True,
                                capture_output=True, check=True, timeout=30)
        output = json.loads(result.stdout)
        assert output["input_kind"] == "reflection" and not output["page"]
        return output


def schedule():
    # Counterbalanced rotations, then repeats of seed 7; order is frozen pre-output.
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


def freeze(old, new, models, provider, out):
    out.mkdir()
    frames = [helper_frame(old), helper_frame(new)]
    manifest_path = models / "manifests/registry.ollama.ai/library/gemma4/12b"
    manifest = json.loads(manifest_path.read_bytes())
    blobs = {}
    for entry in [manifest["config"], *manifest["layers"]]:
        name = entry["digest"].replace(":", "-")
        path = models / "blobs" / name
        actual = file_hash(path)
        if actual != entry["digest"].split(":")[1] or path.stat().st_size != entry["size"]:
            raise ValueError("model asset identity mismatch")
        blobs[name] = {"sha256": actual, "bytes": path.stat().st_size, "media_type": entry["mediaType"]}
    cells = []
    for frame in frames:
        for notice in [True, False]:
            cells.append({"messages": [{"role": "system", "content": "You are Minime.\n" + frame["system_prompt"]},
                                       {"role": "user", "content": frame["text"] + (NOTICE if notice else "")}],
                          "legacy_notice": notice, "scope_metadata": frame["evidence_scope"]})
    packet = {"schema": POLICY, "model": MODEL, "options": OPTIONS, "think": False,
              "seeds": SEEDS, "jobs": schedule(), "cells": cells,
              "helpers": [{"path": str(p), "sha256": file_hash(p)} for p in [old, new]],
              "model_manifest": manifest, "model_manifest_sha256": file_hash(manifest_path),
              "model_blobs": blobs, "model_root": str(models),
              "provider": str(provider), "provider_sha256": file_hash(provider),
              "harness_sha256": file_hash(Path(__file__)),
              "resource_policy": {"max_owned_rss_bytes": 10*1024**3, "min_system_free_percent": 7,
                                  "deadline_seconds": 1800, "one_active_generation": True,
                                  "hard_allocation_cap": False},
              "analysis": ["opening and phrase reuse", "administrative-context uptake", "unsupported mechanism claims", "substantive development"],
              "limits": "24 completions only; no outcome-dependent expansion. No previous prose, live mail, reservoir, action execution or causal claim about Astrid. Length/topic variety descriptive only. Seed reproducibility is measured, not assumed."}
    save(out / "packet.json", packet)
    return packet


def free_percent():
    value = subprocess.check_output(["/usr/bin/memory_pressure", "-Q"], text=True)
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", value)
    if not match:
        raise RuntimeError("memory headroom unavailable")
    return int(match[1])


def group_rss(pgid):
    rows = subprocess.check_output(["/bin/ps", "-axo", "pgid=,rss="], text=True)
    return sum(int(parts[1])*1024 for row in rows.splitlines()
               if len(parts := row.split()) == 2 and int(parts[0]) == pgid)


def sandbox_profile(root, models, port):
    # Loopback is required by Ollama's internal runner; protected service ports
    # and all Unix sockets are denied independently. No writes outside this job.
    quote = json.dumps
    protected = " ".join(f'(remote ip "localhost:{p}")' for p in PROTECTED_PORTS)
    ancestors = " ".join(f'(literal {quote(str(path))})' for path in root.parents)
    return f'''(version 1)
(allow default)
(deny network*)
(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
(deny network-outbound {protected})
(deny file-read* (subpath "/Users/v/other") (subpath "/Users/v/.astrid") (subpath "/Users/v/.codex"))
(allow file-read-metadata {ancestors})
(allow file-read* (subpath {quote(str(root))}) (subpath {quote(str(models))}))
(deny file-write*)
(allow file-write* (subpath {quote(str(root))}) (literal "/dev/null"))
'''


def http(port, path, payload=None, timeout=10):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(16*1024**2))


def stop_owned(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=15)


def execute(out):
    packet = json.loads((out / "packet.json").read_bytes())
    if packet["schema"] != POLICY or len(packet["jobs"]) != 24 or packet["jobs"] != schedule():
        raise ValueError("unsupported or changed schedule")
    if file_hash(Path(__file__)) != packet["harness_sha256"]:
        raise ValueError("harness changed since preregistration")
    if file_hash(packet["provider"]) != packet["provider_sha256"]:
        raise ValueError("provider changed since preregistration")
    models = Path(packet["model_root"])
    for name, entry in packet["model_blobs"].items():
        if file_hash(models / "blobs" / name) != entry["sha256"]:
            raise ValueError("model changed since preregistration")
    if (out / "execution.json").exists():
        raise ValueError("execution already attempted; no automatic replay")
    if free_percent() < 20:
        raise RuntimeError("isolated launch needs 20% system headroom; retain packet for a resource window")
    home = out / "isolated-home"
    home.mkdir()
    model_copy = home / "models"
    target = model_copy / "manifests/registry.ollama.ai/library/gemma4/12b"
    target.parent.mkdir(parents=True)
    save(target, packet["model_manifest"])
    (model_copy / "blobs").symlink_to(models / "blobs", target_is_directory=True)
    (home / "tmp").mkdir()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    if port in PROTECTED_PORTS:
        raise RuntimeError("isolated port conflicts with protected service")
    profile = sandbox_profile(out, models, port)
    profile_path = out / "isolation.sb"
    profile_path.write_text(profile)
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), "TMPDIR": str(home / "tmp"),
           "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(model_copy),
           "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_QUEUE": "1",
           "OLLAMA_KEEP_ALIVE": "0", "OLLAMA_CONTEXT_LENGTH": str(OPTIONS["num_ctx"]),
           "OLLAMA_NO_CLOUD": "1"}
    # Probe the same profile before it can launch a model.
    positive = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile_path), "/bin/cat", str(out / "packet.json")],
                              env=env, capture_output=True)
    if positive.returncode != 0:
        raise RuntimeError("sandbox profile could not read its approved packet: " + positive.stderr.decode()[:500])
    probe = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile_path), "/bin/cat", "/Users/v/other/minime/AGENTS.md"],
                           env=env, capture_output=True)
    if probe.returncode == 0 or b"Operation not permitted" not in probe.stderr:
        raise RuntimeError("isolation did not deny live workspace reads")
    save(out / "execution.json", {"packet_sha256":file_hash(out/"packet.json"), "isolated_port":port,
         "isolation_sha256":file_hash(profile_path), "live_read_probe_denied":True, "started_at":time.time()})
    log = (out / "provider.log").open("x")
    process = subprocess.Popen(["/usr/bin/sandbox-exec", "-f", str(profile_path), packet["provider"], "serve"],
                               env=env, cwd=home, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    finished = threading.Event()
    measurements = []
    guard_errors = []
    def monitor():
        while not finished.wait(2):
            try:
                row={"time":time.time(), "free_percent":free_percent(), "owned_rss_bytes":group_rss(process.pid)}
                measurements.append(row)
                if row["free_percent"] < 7 or row["owned_rss_bytes"] > 10*1024**3:
                    raise RuntimeError("resource boundary reached")
            except Exception as error:
                guard_errors.append(str(error))
                stop_owned(process)
                return
    guard=threading.Thread(target=monitor, daemon=True)
    guard.start()
    results=[]
    try:
        deadline=time.monotonic()+30
        while True:
            try:
                version=http(port,"/api/version")
                break
            except Exception:
                if time.monotonic()>deadline or process.poll() is not None:
                    raise RuntimeError("isolated provider did not start")
                time.sleep(.5)
        show=http(port,"/api/show",{"model":MODEL})
        save(out/"provider-identity.json", {"version":version,"show":show,"provider_sha256":packet["provider_sha256"]})
        for job in packet["jobs"]:
            if guard_errors or process.poll() is not None:
                raise RuntimeError("isolated provider stopped or resource guard refused")
            payload={"model":MODEL,"messages":packet["cells"][job["cell"]]["messages"], "stream":False,
                     "think":False, "keep_alive":0, "options":OPTIONS|{"seed":job["seed"]}}
            save(out/(job["id"]+"-request.json"),payload)
            start=time.monotonic()
            try:
                response=http(port,"/api/chat",payload,timeout=packet["resource_policy"]["deadline_seconds"])
                record={"job":job,"response":response,"wall_seconds":time.monotonic()-start,
                        "completed":response.get("done") is True,"request_sha256":file_hash(out/(job["id"]+"-request.json"))}
            except Exception as error:
                record={"job":job,"error":str(error),"completed":False,"wall_seconds":time.monotonic()-start}
                save(out/(job["id"]+"-result.json"),record)
                results.append(record)
                raise
            save(out/(job["id"]+"-result.json"),record)
            results.append(record)
            print(f"{job['id']} retained; completed={record['completed']}",flush=True)
        review=[]
        for result in results:
            body=result["response"].get("message",{}).get("content","")
            review.append({"id":result["job"]["blind_id"],"text":body})
        save(out/"blind-review.json",sorted(review,key=lambda x:x["id"]))
        repetitions=[]
        for cell in range(4):
            pair=[r for r in results if r["job"]["cell"]==cell and r["job"]["seed"]==SEEDS[0]]
            texts=[r["response"].get("message",{}).get("content","") for r in pair]
            repetitions.append({"cell":cell,"exact_text_match":texts[0]==texts[1]})
        save(out/"summary.json",{"schema":POLICY,"attempts":len(results),"seed_repeats":repetitions,
             "completion_reasons":dict(Counter(r["response"].get("done_reason","unknown") for r in results)),
             "review_required":True,"effects_on_beings_or_reservoir":"not tested"})
    except Exception as error:
        save(out/"failure.json",{"error":str(error),"attempted":len(results),"guard_errors":guard_errors})
        raise
    finally:
        finished.set()
        guard.join(timeout=20)
        stop_owned(process)
        log.close()
        save(out/"resource-receipt.json",{"measurements":measurements,"errors":guard_errors,
             "owned_provider_exit":process.returncode,"live_services_interrupted":False})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="operation",required=True)
    prepare=sub.add_parser("freeze")
    for name in ["old-helper","new-helper","models","provider","out"]:
        prepare.add_argument("--"+name,type=Path,required=True)
    run=sub.add_parser("run")
    run.add_argument("--packet-dir",type=Path,required=True)
    args=parser.parse_args()
    if args.operation=="freeze":
        freeze(args.old_helper.resolve(),args.new_helper.resolve(),args.models.resolve(),args.provider.resolve(),args.out.absolute())
    else:
        execute(args.packet_dir.resolve())


if __name__=="__main__":
    main()
