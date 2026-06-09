#!/usr/bin/env python3
"""Launchd-aware Minime Ollama model canary.

The daily Minime stack is launchd-managed, so this runner avoids the manual
debug start path. It sets launchd-domain environment overrides, starts the
requested Minime labels, monitors stable-core/model behavior, writes a JSON
record, and restores baseline launchd environment afterward.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


MINIME_ROOT = Path(__file__).resolve().parents[1]
ASTRID_ROOT = MINIME_ROOT.parent / "astrid"
WORKSPACE_DIR = MINIME_ROOT / "workspace"
LOG_DIR = MINIME_ROOT / "logs"
LLM_TIMING_PATH = WORKSPACE_DIR / "diagnostics/llm_timing.jsonl"
OUTPUT_ROOT = WORKSPACE_DIR / "diagnostics/model_canaries"
DOMAIN = f"gui/{os.getuid()}"

DEFAULT_MODEL = "gemma4:12b"
DEFAULT_FALLBACK_MODEL = "gemma3:4b"
BASELINE_MODEL = "gemma3:12b"
DEFAULT_NUM_CTX = 8192
DEFAULT_NUM_PREDICT_CAP = 768
DEFAULT_FALLBACK_NUM_CTX = 8192
DEFAULT_FALLBACK_NUM_PREDICT_CAP = 1024
DEFAULT_LLM_TIMEOUT_S = 60.0
DEFAULT_THIN_OUTPUT_MIN_CHARS = 20
DEFAULT_EDGE_SIDECAR_MODEL = "gemma4:e4b"

ENGINE_LABEL = "com.minime.engine"
HOST_LABEL = "com.minime.host-sensory"
AGENT_LABEL = "com.minime.autonomous-agent"
CAMERA_LABEL = "com.minime.camera-client"
MIC_LABEL = "com.minime.mic-to-sensory"
VISUAL_LABEL = "com.minime.visual-frame-service"
USB_WATCHDOG_LABEL = "com.minime.usb-hotplug-watchdog"
RESCUE_LABELS = (
    "com.minime.engine-rescue-watchdog",
    "com.minime.engine-rescue",
)
CORE_LABELS = (ENGINE_LABEL, HOST_LABEL, AGENT_LABEL)
SENSORY_LABELS = (CAMERA_LABEL, MIC_LABEL, VISUAL_LABEL)
NORMAL_LABELS = (
    ENGINE_LABEL,
    HOST_LABEL,
    CAMERA_LABEL,
    MIC_LABEL,
    VISUAL_LABEL,
    USB_WATCHDOG_LABEL,
    AGENT_LABEL,
)
ALL_MINIME_LABELS = tuple(dict.fromkeys((*RESCUE_LABELS, *NORMAL_LABELS, USB_WATCHDOG_LABEL)))

MATRIX_ROWS = [
    {
        "name": "baseline_gemma3_12b",
        "model": "gemma3:12b",
        "num_ctx": 12288,
        "num_predict_cap": 2048,
        "llm_timeout_s": 45.0,
    },
    {
        "name": "tuned_gemma4_12b",
        "model": "gemma4:12b",
        "num_ctx": 8192,
        "num_predict_cap": 768,
        "llm_timeout_s": 60.0,
    },
]

ARTIFACT_RE = re.compile(
    r"(?:<start_of_turn>|<end_of_turn>|<think>|</think>|/no_think|"
    r"<\|im_start\|>|<\|im_end\|>|<\|eot_id\|>|<\|endoftext\|>|"
    r"<turn\|>|<\|turn>|<channel\|>|<\|channel>|<eos>|<bos>|<pad>|<unk>|"
    r"\b(?:thought|analysis|final)\s*<channel\|>)",
    re.I,
)
FALLBACK_RE = re.compile(r"\bFalling back to\b", re.I)
PRIMARY_OLLAMA_FAILURE_RE = re.compile(r"\bLLM query failed \(ollama\):", re.I)
MALFORMED_NEXT_RE = re.compile(r"Unknown NEXT|Malformed NEXT|malformed/unknown NEXT", re.I)
NEXT_RE = re.compile(r"(?im)^NEXT:\s*(.+?)\s*$")


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path = MINIME_ROOT,
    timeout: float = 30.0,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "elapsed_s": round(time.monotonic() - started, 3),
            "stdout": proc.stdout,
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "cmd": cmd,
            "returncode": 127,
            "elapsed_s": round(time.monotonic() - started, 3),
            "stdout": str(exc),
        }


def run_json_request(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            parsed = json.loads(body)
            return {
                "ok": 200 <= response.status < 300,
                "status": response.status,
                "elapsed_s": round(time.monotonic() - started, 3),
                "json": parsed,
                "error": None,
            }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "elapsed_s": round(time.monotonic() - started, 3),
            "json": None,
            "error": str(exc),
        }


def is_gemma4_model(model: str) -> bool:
    normalized = (model or "").strip().lower().replace("_", "-")
    return normalized.startswith("gemma4") or "gemma-4" in normalized


def middle_trim_for_context(text: str, max_chars: int, label: str) -> tuple[str, dict[str, Any]]:
    text = text or ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, {
            "label": label,
            "trimmed": False,
            "original_chars": len(text),
            "retained_chars": len(text),
            "removed_chars": 0,
        }

    marker = (
        f"\n\n[{label} compacted for the Gemma 4 Ollama canary context budget; "
        "middle context omitted, latest/live instructions retained.]\n\n"
    )
    if max_chars <= len(marker) + 200:
        trimmed = text[-max(0, max_chars - len(marker)):]
        result = f"{marker}{trimmed}"
    else:
        remaining = max_chars - len(marker)
        head_len = max(200, remaining // 3)
        tail_len = max(200, remaining - head_len)
        result = f"{text[:head_len].rstrip()}{marker}{text[-tail_len:].lstrip()}"
    return result, {
        "label": label,
        "trimmed": True,
        "original_chars": len(text),
        "retained_chars": len(result),
        "removed_chars": max(0, len(text) - len(result)),
    }


def ollama_prompt_char_budget(num_ctx: int, num_predict: int) -> int:
    context_chars = max(6_000, int(num_ctx * 3.0))
    generation_reserve = max(1_200, int(num_predict * 3.0))
    return max(6_000, context_chars - generation_reserve)


def build_ollama_messages(
    *,
    model: str,
    system_msg: str,
    user_prompt: str,
    num_ctx: int,
    num_predict: int,
    compact_prompt: bool = False,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    gemma4 = is_gemma4_model(model)
    template_mode = "gemma4_think_false_native" if gemma4 else "legacy_no_think_user_prefix"
    adapted_system = system_msg or ""
    adapted_prompt = user_prompt or ""
    compaction: dict[str, Any] = {
        "applied": False,
        "budget_chars": ollama_prompt_char_budget(num_ctx, num_predict),
        "parts": [],
    }

    if gemma4:
        budget_chars = int(compaction["budget_chars"])
        original_total = len(adapted_system) + len(adapted_prompt)
        if compact_prompt or original_total > budget_chars:
            system_budget = min(len(adapted_system), max(4_000, min(10_000, budget_chars // 2)))
            prompt_budget = max(1_500, budget_chars - system_budget - 512)
            adapted_system, system_report = middle_trim_for_context(
                adapted_system,
                system_budget,
                "system prompt",
            )
            adapted_prompt, prompt_report = middle_trim_for_context(
                adapted_prompt,
                prompt_budget,
                "autonomous prompt",
            )
            compaction.update(
                {
                    "applied": bool(system_report["trimmed"] or prompt_report["trimmed"]),
                    "original_total_chars": original_total,
                    "adapted_total_chars": len(adapted_system) + len(adapted_prompt),
                    "parts": [system_report, prompt_report],
                }
            )

    user_content = adapted_prompt if gemma4 else "/no_think\n" + adapted_prompt
    return (
        [
            {"role": "system", "content": adapted_system},
            {"role": "user", "content": user_content},
        ],
        {
            "prompt_template_mode": template_mode,
            "prompt_compacted": bool(compaction["applied"]),
            "prompt_compaction": compaction,
            "adapted_system_chars": len(adapted_system),
            "adapted_prompt_chars": len(adapted_prompt),
            "user_prefix": "" if gemma4 else "/no_think",
        },
    )


def launchctl(*args: str, timeout: float = 15.0) -> dict[str, Any]:
    return run_cmd(["launchctl", *args], timeout=timeout)


def launchd_service(label: str) -> str:
    return f"{DOMAIN}/{label}"


def label_plist(label: str) -> Path:
    return MINIME_ROOT / "launchd" / f"{label}.plist"


def label_state(label: str) -> dict[str, Any]:
    result = launchctl("print", launchd_service(label), timeout=8.0)
    loaded = result["returncode"] == 0
    text = result.get("stdout") or ""
    state_match = re.search(r"\bstate = ([^\n]+)", text)
    pid_match = re.search(r"\bpid = (\d+)", text)
    last_exit_match = re.search(r"\blast exit code = ([^\n]+)", text)
    return {
        "label": label,
        "loaded": loaded,
        "state": state_match.group(1).strip() if state_match else None,
        "pid": int(pid_match.group(1)) if pid_match else None,
        "last_exit_code": last_exit_match.group(1).strip() if last_exit_match else None,
    }


def bootout_label(label: str) -> dict[str, Any]:
    if not label_state(label)["loaded"]:
        return {"label": label, "already_unloaded": True}
    result = launchctl("bootout", launchd_service(label), timeout=20.0)
    if result["returncode"] != 0:
        plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
        result = launchctl("bootout", DOMAIN, str(plist), timeout=20.0)
    return {"label": label, "result": result}


def bootstrap_label(label: str) -> dict[str, Any]:
    plist = label_plist(label)
    if not plist.exists():
        return {"label": label, "ok": False, "error": f"missing plist: {plist}"}
    result = launchctl("bootstrap", DOMAIN, str(plist), timeout=20.0)
    if result["returncode"] != 0 and label_state(label)["loaded"]:
        return {"label": label, "ok": True, "already_loaded": True, "result": result}
    return {"label": label, "ok": result["returncode"] == 0, "result": result}


def kickstart_label(label: str) -> dict[str, Any]:
    result = launchctl("kickstart", "-k", launchd_service(label), timeout=20.0)
    return {"label": label, "ok": result["returncode"] == 0, "result": result}


def wait_label_running(label: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last = label_state(label)
    while time.monotonic() < deadline:
        last = label_state(label)
        if last.get("state") == "running":
            return {"ok": True, "state": last}
        time.sleep(1)
    return {"ok": False, "state": last}


def wait_labels_running(labels: tuple[str, ...], timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    pending = set(labels)
    states = {label: label_state(label) for label in labels}
    while pending and time.monotonic() < deadline:
        for label in tuple(pending):
            states[label] = label_state(label)
            if states[label].get("state") == "running":
                pending.remove(label)
        if pending:
            time.sleep(1)
    for label in tuple(pending):
        states[label] = label_state(label)
    return {
        label: {
            "ok": states[label].get("state") == "running",
            "state": states[label],
        }
        for label in labels
    }


def set_launch_env(
    *,
    model: str,
    fallback_model: str,
    interval_s: int,
    llm_timeout_s: float,
    num_ctx: int,
    num_predict_cap: int,
    fallback_num_ctx: int,
    fallback_num_predict_cap: int,
) -> list[dict[str, Any]]:
    return [
        launchctl("setenv", "MINIME_MODEL", model),
        launchctl("setenv", "MINIME_FALLBACK_MODEL", fallback_model),
        launchctl("setenv", "AGENT_INTERVAL", str(interval_s)),
        launchctl("setenv", "MINIME_LLM_TIMEOUT_S", str(llm_timeout_s)),
        launchctl("setenv", "MINIME_OLLAMA_NUM_CTX", str(num_ctx)),
        launchctl("setenv", "MINIME_OLLAMA_NUM_PREDICT_CAP", str(num_predict_cap)),
        launchctl("setenv", "MINIME_OLLAMA_FALLBACK_NUM_CTX", str(fallback_num_ctx)),
        launchctl(
            "setenv",
            "MINIME_OLLAMA_FALLBACK_NUM_PREDICT_CAP",
            str(fallback_num_predict_cap),
        ),
    ]


def unset_launch_env() -> list[dict[str, Any]]:
    return [
        launchctl("unsetenv", "MINIME_MODEL"),
        launchctl("unsetenv", "MINIME_FALLBACK_MODEL"),
        launchctl("unsetenv", "AGENT_INTERVAL"),
        launchctl("unsetenv", "MINIME_LLM_TIMEOUT_S"),
        launchctl("unsetenv", "MINIME_OLLAMA_NUM_CTX"),
        launchctl("unsetenv", "MINIME_OLLAMA_NUM_PREDICT_CAP"),
        launchctl("unsetenv", "MINIME_OLLAMA_FALLBACK_NUM_CTX"),
        launchctl("unsetenv", "MINIME_OLLAMA_FALLBACK_NUM_PREDICT_CAP"),
    ]


def stop_minime_labels() -> list[dict[str, Any]]:
    return [bootout_label(label) for label in ALL_MINIME_LABELS]


def start_smoke_stack(start_timeout_s: float) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    actions.extend(stop_minime_labels())
    start_all = ASTRID_ROOT / "scripts/start_all.sh"
    result = run_cmd(
        ["bash", str(start_all), "--minime-only", "--skip-greeting", "--force"],
        cwd=ASTRID_ROOT,
        timeout=max(120.0, start_timeout_s + 90.0),
    )
    actions.append({"script": str(start_all), "result": result})
    waits = wait_labels_running(CORE_LABELS, start_timeout_s)
    for label in SENSORY_LABELS:
        actions.append(bootout_label(label))
    waits = wait_labels_running(CORE_LABELS, start_timeout_s)
    return {"mode": "smoke", "actions": actions, "waits": waits}


def start_normal_stack(start_timeout_s: float) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    actions.extend(stop_minime_labels())
    start_all = ASTRID_ROOT / "scripts/start_all.sh"
    result = run_cmd(
        ["bash", str(start_all), "--minime-only", "--skip-greeting", "--force"],
        cwd=ASTRID_ROOT,
        timeout=max(120.0, start_timeout_s + 90.0),
    )
    actions.append({"script": str(start_all), "result": result})
    waits = wait_labels_running(NORMAL_LABELS, start_timeout_s)
    return {"mode": "normal", "actions": actions, "waits": waits}


def restore_baseline_stack() -> dict[str, Any]:
    unset = unset_launch_env()
    stopped = stop_minime_labels()
    start_all = ASTRID_ROOT / "scripts/start_all.sh"
    result = run_cmd(
        ["bash", str(start_all), "--minime-only", "--skip-greeting", "--force"],
        cwd=ASTRID_ROOT,
        timeout=180.0,
    )
    return {"unset_env": unset, "stopped_after_unset": stopped, "restore_start_all": result}


def direct_ollama_probe(
    model: str,
    num_ctx: int,
    num_predict: int,
    timeout_s: float,
) -> dict[str, Any]:
    messages, adapter = build_ollama_messages(
        model=model,
        system_msg="Return exactly the requested text. No extra words.",
        user_prompt="Reply with exactly: MINIME_CANARY_OK",
        num_ctx=num_ctx,
        num_predict=min(num_predict, 64),
    )
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "top_p": 0.95,
            "num_predict": min(num_predict, 64),
            "num_ctx": num_ctx,
        },
    }
    result = run_json_request("http://127.0.0.1:11434/api/chat", payload, timeout_s)
    data = result.get("json") if isinstance(result.get("json"), dict) else {}
    text = ""
    if isinstance(data, dict):
        text = str((data.get("message") or {}).get("content") or "").strip()
    result.update(
        {
            "text_preview": compact(text, 240),
            "response_chars": len(text),
            "exact_ok": text == "MINIME_CANARY_OK",
            "artifacts": sorted(set(ARTIFACT_RE.findall(text))),
            "total_duration": data.get("total_duration") if isinstance(data, dict) else None,
            "eval_count": data.get("eval_count") if isinstance(data, dict) else None,
            "eval_duration": data.get("eval_duration") if isinstance(data, dict) else None,
            **adapter,
        }
    )
    result["ok"] = bool(result.get("ok")) and bool(result["exact_ok"]) and not result["artifacts"]
    return result


def compact(text: str, limit: int = 320) -> str:
    one_line = " ".join((text or "").split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: max(0, limit - 3)].rstrip() + "..."


def extract_ollama_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    return str((data.get("message") or {}).get("content") or "").strip()


def probe_case(
    *,
    name: str,
    model: str,
    system_msg: str,
    user_prompt: str,
    num_ctx: int,
    num_predict: int,
    timeout_s: float,
    thin_output_min_chars: int,
    compact_prompt: bool = False,
    exact: str | None = None,
    require_next: bool = False,
    max_elapsed_s: float | None = None,
) -> dict[str, Any]:
    messages, adapter = build_ollama_messages(
        model=model,
        system_msg=system_msg,
        user_prompt=user_prompt,
        num_ctx=num_ctx,
        num_predict=num_predict,
        compact_prompt=compact_prompt,
    )
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.2 if exact is None else 0,
            "top_p": 0.9,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        },
    }
    result = run_json_request("http://127.0.0.1:11434/api/chat", payload, timeout_s)
    data = result.get("json") if isinstance(result.get("json"), dict) else {}
    text = extract_ollama_text(data)
    artifacts = sorted(set(ARTIFACT_RE.findall(text)))
    next_matches = NEXT_RE.findall(text)
    eval_count = data.get("eval_count") if isinstance(data, dict) else None
    response_chars = len(text)
    non_thin = response_chars >= thin_output_min_chars
    eval_count_ok = isinstance(eval_count, int) and eval_count > 1
    exact_ok = exact is None or text == exact
    next_ok = (not require_next) or len(next_matches) == 1
    latency_ok = max_elapsed_s is None or float(result.get("elapsed_s") or 0.0) <= max_elapsed_s
    automated_ok = (
        bool(result.get("ok"))
        and exact_ok
        and next_ok
        and not artifacts
        and non_thin
        and eval_count_ok
        and latency_ok
    )
    result.update(
        {
            "name": name,
            "model": model,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "compact_prompt_requested": compact_prompt,
            "text_preview": compact(text, 320),
            "response_chars": response_chars,
            "artifacts": artifacts,
            "next_matches": next_matches,
            "exact_ok": exact_ok,
            "next_ok": next_ok,
            "non_thin": non_thin,
            "eval_count_ok": eval_count_ok,
            "latency_ok": latency_ok,
            "total_duration": data.get("total_duration") if isinstance(data, dict) else None,
            "eval_count": eval_count,
            "eval_duration": data.get("eval_duration") if isinstance(data, dict) else None,
            "automated_ok": automated_ok,
            "failure_reasons": [
                reason
                for reason, failed in (
                    ("http_failed", not bool(result.get("ok"))),
                    ("exact_mismatch", not exact_ok),
                    ("next_contract_failed", not next_ok),
                    ("artifact_detected", bool(artifacts)),
                    ("thin_output", not non_thin),
                    ("eval_count_too_low", not eval_count_ok),
                    ("latency_exceeded", not latency_ok),
                )
                if failed
            ],
            **adapter,
        }
    )
    return result


def prompt_template_probe_cases(
    model: str,
    *,
    timeout_s: float,
    thin_output_min_chars: int,
) -> list[dict[str, Any]]:
    long_system = (
        "You are running a Minime Gemma 4 prompt-template probe. "
        "Follow the user's instruction, write normal message content, and end with one NEXT line. "
        "Allowed NEXT actions: REST, PASS, DAYDREAM, INTROSPECT, SEARCH, BROWSE, READ_MORE, DECOMPOSE.\n"
        + (
            "Allowed action reference: REST PASS DAYDREAM INTROSPECT SEARCH BROWSE READ_MORE DECOMPOSE. "
            "Do not invent action verbs. "
            * 220
        )
    )
    long_user = (
        "Write two short sentences about stable-core telemetry, then a final line exactly NEXT: REST.\n"
        + ("Live context: fill is in the stable-core band; preserve action discipline. " * 260)
    )
    short_system = "Follow the user instruction. End with exactly one NEXT line from the allowed verbs."
    short_user = "Write two short sentences about stable-core telemetry, then a final line exactly NEXT: REST."
    return [
        probe_case(
            name="short_ctx8192",
            model=model,
            system_msg=short_system,
            user_prompt=short_user,
            num_ctx=8192,
            num_predict=96,
            timeout_s=timeout_s,
            thin_output_min_chars=thin_output_min_chars,
            require_next=True,
        ),
        probe_case(
            name="long_ctx8192",
            model=model,
            system_msg=long_system,
            user_prompt=long_user,
            num_ctx=8192,
            num_predict=128,
            timeout_s=timeout_s,
            thin_output_min_chars=thin_output_min_chars,
            require_next=True,
        ),
        probe_case(
            name="compacted_ctx8192",
            model=model,
            system_msg=long_system,
            user_prompt=long_user,
            num_ctx=8192,
            num_predict=128,
            timeout_s=timeout_s,
            thin_output_min_chars=thin_output_min_chars,
            compact_prompt=True,
            require_next=True,
        ),
        probe_case(
            name="compacted_ctx12288",
            model=model,
            system_msg=long_system,
            user_prompt=long_user,
            num_ctx=12288,
            num_predict=128,
            timeout_s=timeout_s,
            thin_output_min_chars=thin_output_min_chars,
            compact_prompt=True,
            require_next=True,
        ),
    ]


def run_prompt_template_probes(
    model: str,
    *,
    timeout_s: float,
    thin_output_min_chars: int,
) -> dict[str, Any]:
    if not is_gemma4_model(model):
        return {"skipped": True, "reason": "model is not Gemma 4", "automated_ok": True}
    cases = prompt_template_probe_cases(
        model,
        timeout_s=timeout_s,
        thin_output_min_chars=thin_output_min_chars,
    )
    return {
        "skipped": False,
        "model": model,
        "cases": cases,
        "automated_ok": all(case.get("automated_ok") for case in cases),
        "failed_cases": [case["name"] for case in cases if not case.get("automated_ok")],
    }


def run_edge_sidecar_probes(args: argparse.Namespace) -> int:
    current_run = now_utc()
    output_dir = args.output_dir / current_run
    output_dir.mkdir(parents=True, exist_ok=True)
    model = args.edge_model
    cases = [
        probe_case(
            name="exact_output",
            model=model,
            system_msg="Return exactly the requested text. No extra words.",
            user_prompt="Reply with exactly: MINIME_EDGE_OK",
            num_ctx=4096,
            num_predict=48,
            timeout_s=args.request_timeout_secs,
            thin_output_min_chars=min(args.thin_output_min_chars, len("MINIME_EDGE_OK")),
            exact="MINIME_EDGE_OK",
            max_elapsed_s=30.0,
        ),
        probe_case(
            name="compact_summary",
            model=model,
            system_msg="Summarize compactly for a sidecar helper. No raw prompts.",
            user_prompt=(
                "In two concise sentences, summarize why a fast edge model might help diagnostics. "
                "Do not mention promotion."
            ),
            num_ctx=4096,
            num_predict=128,
            timeout_s=args.request_timeout_secs,
            thin_output_min_chars=args.thin_output_min_chars,
            max_elapsed_s=45.0,
        ),
        probe_case(
            name="next_finalizer",
            model=model,
            system_msg="Answer briefly and end with exactly one NEXT line using REST, PASS, or INTROSPECT.",
            user_prompt="Name one safe sidecar task, then write NEXT: REST.",
            num_ctx=4096,
            num_predict=96,
            timeout_s=args.request_timeout_secs,
            thin_output_min_chars=args.thin_output_min_chars,
            require_next=True,
            max_elapsed_s=45.0,
        ),
        probe_case(
            name="latency",
            model=model,
            system_msg="Answer in one sentence.",
            user_prompt="Say that the sidecar latency probe is alive.",
            num_ctx=4096,
            num_predict=64,
            timeout_s=args.request_timeout_secs,
            thin_output_min_chars=args.thin_output_min_chars,
            max_elapsed_s=20.0,
        ),
    ]
    record = {
        "run_id": current_run,
        "started_at": iso_now(),
        "mode": "edge_sidecar_probes",
        "model": model,
        "cases": cases,
        "summary": {
            "automated_ok": all(case.get("automated_ok") for case in cases),
            "failed_cases": [case["name"] for case in cases if not case.get("automated_ok")],
            "promotion_target": False,
            "notes": [
                "This lane is for fast edge/sidecar assessment only.",
                "It does not promote Minime's autonomous conversation default.",
            ],
        },
    }
    path = output_dir / "edge_sidecar_result.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    return 0 if record["summary"]["automated_ok"] else 1


def load_stable_core_summary() -> dict[str, Any]:
    path = WORKSPACE_DIR / "stable_core_status.json"
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": str(path)}
    stable_core = data.get("stable_core") if isinstance(data.get("stable_core"), dict) else {}
    agency = data.get("agency_status") if isinstance(data.get("agency_status"), dict) else {}
    fill = agency.get("fill_pct")
    if fill is None:
        fill = data.get("fill_pct")
    return {
        "ok": True,
        "path": str(path),
        "updated_at_unix_s": data.get("updated_at_unix_s"),
        "telemetry_state": data.get("telemetry_state"),
        "watchdog_state": data.get("watchdog_state"),
        "stage": data.get("stage") or stable_core.get("stage"),
        "stable_core_stage": stable_core.get("stage"),
        "structural_mode": stable_core.get("structural_mode"),
        "fill_pct": fill,
        "health_budget_status": agency.get("health_budget_status"),
        "current_block_reason": agency.get("current_block_reason"),
    }


def ollama_ps_summary() -> dict[str, Any]:
    result = run_cmd(["ollama", "ps"], timeout=10.0)
    models: list[str] = []
    for line in (result.get("stdout") or "").splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return {"models": models, "raw": result.get("stdout"), "returncode": result["returncode"]}


def log_offsets() -> dict[str, int]:
    offsets: dict[str, int] = {}
    for path in (LOG_DIR / "autonomous-agent.log", LOG_DIR / "minime-engine.log"):
        try:
            offsets[str(path)] = path.stat().st_size
        except OSError:
            offsets[str(path)] = 0
    return offsets


def file_offset(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_new_log_text(offsets: dict[str, int]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_path, offset in offsets.items():
        path = Path(raw_path)
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                out[raw_path] = handle.read()
        except OSError:
            out[raw_path] = ""
    return out


def read_new_timing_records(offset: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with LLM_TIMING_PATH.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError:
        pass
    return records


def summarize_timing_records(
    records: list[dict[str, Any]],
    *,
    primary_model: str,
    thin_output_min_chars: int,
) -> dict[str, Any]:
    primary = [
        record
        for record in records
        if record.get("backend") == "ollama" and record.get("model") == primary_model
    ]
    thin = [
        record
        for record in primary
        if record.get("status") == "ok"
        and isinstance(record.get("response_chars"), int)
        and int(record["response_chars"]) < thin_output_min_chars
    ]
    timeouts = [
        record
        for record in primary
        if record.get("error") == "ReadTimeout" or record.get("status") == "timeout"
    ]
    return {
        "primary_model": primary_model,
        "thin_output_min_chars": thin_output_min_chars,
        "primary_call_count": len(primary),
        "primary_timeout_count": len(timeouts),
        "thin_primary_output_count": len(thin),
        "recent_thin_primary_outputs": thin[-10:],
    }


def count_log_events(texts: dict[str, str]) -> dict[str, Any]:
    joined = "\n".join(texts.values())
    fallback_lines = [line for line in joined.splitlines() if FALLBACK_RE.search(line)]
    fallback_incidents = 0
    in_fallback_incident = False
    for line in joined.splitlines():
        if PRIMARY_OLLAMA_FAILURE_RE.search(line):
            in_fallback_incident = False
        if FALLBACK_RE.search(line):
            if not in_fallback_incident:
                fallback_incidents += 1
            in_fallback_incident = True
            continue
        if "LLM fallback succeeded" in line or "Outbox: saved reply" in line:
            in_fallback_incident = False
    return {
        "fallback_count": fallback_incidents,
        "fallback_line_count": len(fallback_lines),
        "malformed_next_count": len(MALFORMED_NEXT_RE.findall(joined)),
        "artifact_count": len(ARTIFACT_RE.findall(joined)),
        "artifact_matches": sorted(set(ARTIFACT_RE.findall(joined))),
        "recent_fallback_lines": fallback_lines[-20:],
        "recent_malformed_next_lines": [
            line for line in joined.splitlines() if MALFORMED_NEXT_RE.search(line)
        ][-20:],
    }


def scan_recent_workspace_artifacts(started_at: float) -> dict[str, Any]:
    roots = [
        WORKSPACE_DIR / "journal",
        WORKSPACE_DIR / "outbox",
        WORKSPACE_DIR / "llm_jobs/jobs",
    ]
    scanned = 0
    hits: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".txt", ".json", ".jsonl", ".log"}:
                continue
            try:
                if path.stat().st_mtime < started_at:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")[:65536]
            except OSError:
                continue
            scanned += 1
            matches = sorted(set(ARTIFACT_RE.findall(text)))
            if matches:
                hits.append({"path": str(path), "matches": matches})
            if scanned >= 250:
                break
        if scanned >= 250:
            break
    return {"scanned_files": scanned, "artifact_hits": hits}


def sustained_above(samples: list[dict[str, Any]], threshold: float) -> float:
    longest = 0.0
    run_start: float | None = None
    last_ts: float | None = None
    for sample in samples:
        ts = float(sample.get("t_s") or 0.0)
        fill = sample.get("stable_core", {}).get("fill_pct")
        above = isinstance(fill, (int, float)) and float(fill) > threshold
        if above:
            if run_start is None:
                run_start = ts
            last_ts = ts
            longest = max(longest, (last_ts - run_start) if last_ts is not None else 0.0)
        else:
            run_start = None
            last_ts = None
    return round(longest, 3)


def max_fill(samples: list[dict[str, Any]]) -> float | None:
    fills = [
        float(sample["stable_core"]["fill_pct"])
        for sample in samples
        if isinstance(sample.get("stable_core", {}).get("fill_pct"), (int, float))
    ]
    return max(fills) if fills else None


def sample_status(labels: tuple[str, ...]) -> dict[str, Any]:
    return {
        "t_s": round(time.time(), 3),
        "stable_core": load_stable_core_summary(),
        "labels": {label: label_state(label) for label in labels},
        "ollama": ollama_ps_summary(),
    }


def start_failure_reasons(start: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for action in start.get("actions", []):
        if not isinstance(action, dict):
            continue
        result = action.get("result")
        if action.get("script") and isinstance(result, dict) and result.get("returncode") != 0:
            reasons.append("start_script_failed")
    waits = start.get("waits") if isinstance(start.get("waits"), dict) else {}
    missing = [label for label, wait in waits.items() if not wait.get("ok")]
    if missing:
        reasons.append("labels_not_running:" + ",".join(sorted(missing)))
    return reasons


def startup_failure_monitor(
    *,
    name: str,
    labels: tuple[str, ...],
    sample_interval_s: float,
    fallback_limit: int,
    malformed_next_limit: int,
    primary_model: str,
    thin_output_min_chars: int,
    failure_reasons: list[str],
) -> dict[str, Any]:
    started = time.time()
    return {
        "name": name,
        "started_at": dt.datetime.fromtimestamp(started, dt.UTC).isoformat(),
        "duration_s": 0.0,
        "sample_interval_s": sample_interval_s,
        "fallback_limit": fallback_limit,
        "malformed_next_limit": malformed_next_limit,
        "samples": [sample_status(labels)],
        "sample_count": 1,
        "max_fill_pct": None,
        "sustained_above_85_s": 0.0,
        "agent_bad_sample_count": 0,
        "log_counts": count_log_events({}),
        "timing_counts": {
            "primary_model": primary_model,
            "thin_output_min_chars": thin_output_min_chars,
            "primary_call_count": 0,
            "primary_timeout_count": 0,
            "thin_primary_output_count": 0,
            "recent_thin_primary_outputs": [],
        },
        "workspace_scan": {"scanned_files": 0, "artifact_hits": []},
        "automated_ok": False,
        "failure_reasons": ["startup_failed", *failure_reasons],
    }


def monitor_phase(
    *,
    name: str,
    duration_s: float,
    sample_interval_s: float,
    labels: tuple[str, ...],
    fallback_limit: int,
    malformed_next_limit: int,
    primary_model: str,
    thin_output_min_chars: int,
) -> dict[str, Any]:
    started = time.time()
    offsets = log_offsets()
    timing_offset = file_offset(LLM_TIMING_PATH)
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + duration_s
    while True:
        samples.append(sample_status(labels))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(sample_interval_s, remaining))

    log_texts = read_new_log_text(offsets)
    log_counts = count_log_events(log_texts)
    timing_counts = summarize_timing_records(
        read_new_timing_records(timing_offset),
        primary_model=primary_model,
        thin_output_min_chars=thin_output_min_chars,
    )
    workspace_scan = scan_recent_workspace_artifacts(started)
    fill_max = max_fill(samples)
    sustained_85 = sustained_above(samples, 85.0)
    agent_bad_samples = [
        sample
        for sample in samples
        if sample.get("labels", {}).get(AGENT_LABEL, {}).get("state") != "running"
    ]
    hit_92 = bool(fill_max is not None and fill_max >= 92.0)
    sustained_high = sustained_85 > 300.0
    workspace_artifact_count = len(workspace_scan["artifact_hits"])
    automated_ok = (
        not agent_bad_samples
        and not hit_92
        and not sustained_high
        and log_counts["fallback_count"] <= fallback_limit
        and log_counts["malformed_next_count"] <= malformed_next_limit
        and log_counts["artifact_count"] == 0
        and timing_counts["thin_primary_output_count"] == 0
        and workspace_artifact_count == 0
    )
    return {
        "name": name,
        "started_at": dt.datetime.fromtimestamp(started, dt.UTC).isoformat(),
        "duration_s": duration_s,
        "sample_interval_s": sample_interval_s,
        "fallback_limit": fallback_limit,
        "malformed_next_limit": malformed_next_limit,
        "samples": samples,
        "sample_count": len(samples),
        "max_fill_pct": fill_max,
        "sustained_above_85_s": sustained_85,
        "agent_bad_sample_count": len(agent_bad_samples),
        "log_counts": log_counts,
        "timing_counts": timing_counts,
        "workspace_scan": workspace_scan,
        "automated_ok": automated_ok,
        "failure_reasons": [
            reason
            for reason, failed in (
                ("agent_not_running", bool(agent_bad_samples)),
                ("fill_at_or_above_92", hit_92),
                ("fill_above_85_over_5m", sustained_high),
                ("fallback_limit_exceeded", log_counts["fallback_count"] > fallback_limit),
                (
                    "malformed_next_limit_exceeded",
                    log_counts["malformed_next_count"] > malformed_next_limit,
                ),
                ("log_artifacts_detected", log_counts["artifact_count"] > 0),
                (
                    "thin_primary_output_detected",
                    timing_counts["thin_primary_output_count"] > 0,
                ),
                ("workspace_artifacts_detected", workspace_artifact_count > 0),
            )
            if failed
        ],
    }


def preflight(
    model: str,
    num_ctx: int,
    num_predict_cap: int,
    direct_timeout_s: float,
    thin_output_min_chars: int,
) -> dict[str, Any]:
    return {
        "at": iso_now(),
        "model_stack_audit": run_cmd(
            ["python3", "scripts/model_stack_audit.py", "--candidate", model, "--no-stale-scan"],
            timeout=30.0,
        ),
        "ollama_show": run_cmd(["ollama", "show", model], timeout=30.0),
        "ollama_ps": run_cmd(["ollama", "ps"], timeout=15.0),
        "stable_core": load_stable_core_summary(),
        "direct_ollama_probe": direct_ollama_probe(
            model,
            num_ctx,
            num_predict_cap,
            direct_timeout_s,
        ),
        "prompt_template_probes": run_prompt_template_probes(
            model,
            timeout_s=direct_timeout_s,
            thin_output_min_chars=thin_output_min_chars,
        ),
    }


def write_record(output_dir: Path, record: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "canary_result.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def phase_order(phase_arg: str) -> list[str]:
    if phase_arg == "both":
        return ["smoke", "normal"]
    if phase_arg == "preflight":
        return []
    return [phase_arg]


def load_record_from_stdout(stdout: str) -> tuple[Path | None, dict[str, Any] | None]:
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if not text.endswith(".json"):
            continue
        path = Path(text)
        if not path.exists():
            continue
        try:
            return path, json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return path, None
    return None, None


def row_phase_command(
    *,
    row: dict[str, Any],
    phase: str,
    args: argparse.Namespace,
    row_output_dir: Path,
) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--phase",
        phase,
        "--model",
        str(row["model"]),
        "--fallback-model",
        args.fallback_model,
        "--agent-interval",
        str(args.agent_interval),
        "--num-ctx",
        str(row["num_ctx"]),
        "--num-predict-cap",
        str(row["num_predict_cap"]),
        "--fallback-num-ctx",
        str(args.fallback_num_ctx),
        "--fallback-num-predict-cap",
        str(args.fallback_num_predict_cap),
        "--llm-timeout-secs",
        str(row["llm_timeout_s"]),
        "--smoke-duration-secs",
        str(args.smoke_duration_secs),
        "--normal-duration-secs",
        str(args.normal_duration_secs),
        "--sample-interval-secs",
        str(args.sample_interval_secs),
        "--start-timeout-secs",
        str(args.start_timeout_secs),
        "--request-timeout-secs",
        str(max(float(args.request_timeout_secs), float(row["llm_timeout_s"]) + 30.0)),
        "--thin-output-min-chars",
        str(args.thin_output_min_chars),
        "--output-dir",
        str(row_output_dir),
    ]


def phase_timeout(phase: str, args: argparse.Namespace) -> float:
    duration = args.smoke_duration_secs if phase == "smoke" else args.normal_duration_secs
    return max(600.0, float(duration) + float(args.start_timeout_secs) + 420.0)


def run_matrix(args: argparse.Namespace) -> int:
    matrix_id = now_utc()
    matrix_dir = args.output_dir / matrix_id
    matrix_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "run_id": matrix_id,
        "started_at": iso_now(),
        "mode": "matrix",
        "fallback_model": args.fallback_model,
        "fallback_num_ctx": args.fallback_num_ctx,
        "fallback_num_predict_cap": args.fallback_num_predict_cap,
        "thin_output_min_chars": args.thin_output_min_chars,
        "rows": [],
        "notes": [
            "Smoke runs first for every row.",
            "Normal runs only for rows whose smoke phase passes.",
            "gemma4:e4b is evaluated by --edge-sidecar-probes, not this autonomous promotion matrix.",
            "This runner does not promote defaults.",
        ],
    }
    return_code = 0

    def write_matrix() -> Path:
        path = matrix_dir / "matrix_result.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    for row in MATRIX_ROWS:
        row_record: dict[str, Any] = {"row": row, "phases": []}
        row_output_dir = matrix_dir / "rows" / str(row["name"])
        smoke_cmd = row_phase_command(
            row=row,
            phase="smoke",
            args=args,
            row_output_dir=row_output_dir / "smoke",
        )
        smoke_result = run_cmd(smoke_cmd, timeout=phase_timeout("smoke", args))
        smoke_path, smoke_record = load_record_from_stdout(smoke_result.get("stdout") or "")
        row_record["phases"].append(
            {
                "name": "smoke",
                "cmd": smoke_cmd,
                "result": smoke_result,
                "record_path": str(smoke_path) if smoke_path else None,
                "summary": smoke_record.get("summary") if smoke_record else None,
            }
        )
        smoke_ok = bool(smoke_record and smoke_record.get("summary", {}).get("automated_ok"))
        if not smoke_ok:
            return_code = 1
            if smoke_path is None:
                row_record["restore_after_missing_report"] = restore_baseline_stack()
        else:
            normal_cmd = row_phase_command(
                row=row,
                phase="normal",
                args=args,
                row_output_dir=row_output_dir / "normal",
            )
            normal_result = run_cmd(normal_cmd, timeout=phase_timeout("normal", args))
            normal_path, normal_record = load_record_from_stdout(normal_result.get("stdout") or "")
            row_record["phases"].append(
                {
                    "name": "normal",
                    "cmd": normal_cmd,
                    "result": normal_result,
                    "record_path": str(normal_path) if normal_path else None,
                    "summary": normal_record.get("summary") if normal_record else None,
                }
            )
            normal_ok = bool(normal_record and normal_record.get("summary", {}).get("automated_ok"))
            if not normal_ok:
                return_code = 1
                if normal_path is None:
                    row_record["restore_after_missing_report"] = restore_baseline_stack()
        record["rows"].append(row_record)
        write_matrix()

    passing_rows = [
        row
        for row in record["rows"]
        if row.get("phases")
        and row["phases"][-1].get("summary", {}).get("automated_ok")
        and len(row["phases"]) == 2
    ]
    record["summary"] = {
        "automated_ok": bool(passing_rows),
        "passing_rows": [row["row"]["name"] for row in passing_rows],
        "operator_review_required": True,
    }
    if not passing_rows:
        return_code = 1
    path = write_matrix()
    print(path)
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--fallback-model", default=DEFAULT_FALLBACK_MODEL)
    parser.add_argument("--agent-interval", type=int, default=60)
    parser.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
    parser.add_argument("--num-predict-cap", type=int, default=DEFAULT_NUM_PREDICT_CAP)
    parser.add_argument("--fallback-num-ctx", type=int, default=DEFAULT_FALLBACK_NUM_CTX)
    parser.add_argument(
        "--fallback-num-predict-cap",
        type=int,
        default=DEFAULT_FALLBACK_NUM_PREDICT_CAP,
    )
    parser.add_argument("--llm-timeout-secs", type=float, default=DEFAULT_LLM_TIMEOUT_S)
    parser.add_argument("--thin-output-min-chars", type=int, default=DEFAULT_THIN_OUTPUT_MIN_CHARS)
    parser.add_argument("--phase", choices=["preflight", "smoke", "normal", "both"], default="both")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--prompt-template-probes", action="store_true")
    parser.add_argument("--edge-sidecar-probes", action="store_true")
    parser.add_argument("--edge-model", default=DEFAULT_EDGE_SIDECAR_MODEL)
    parser.add_argument("--smoke-duration-secs", type=float, default=900.0)
    parser.add_argument("--normal-duration-secs", type=float, default=7200.0)
    parser.add_argument("--sample-interval-secs", type=float, default=30.0)
    parser.add_argument("--start-timeout-secs", type=float, default=90.0)
    parser.add_argument("--request-timeout-secs", type=float, default=90.0)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--no-restore", action="store_true")
    parser.add_argument("--continue-after-failed-smoke", action="store_true")
    args = parser.parse_args()

    if args.edge_sidecar_probes:
        return run_edge_sidecar_probes(args)

    if args.prompt_template_probes:
        current_run = now_utc()
        output_dir = args.output_dir / current_run
        output_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": current_run,
            "started_at": iso_now(),
            "mode": "prompt_template_probes",
            "model": args.model,
            "probes": run_prompt_template_probes(
                args.model,
                timeout_s=args.request_timeout_secs,
                thin_output_min_chars=args.thin_output_min_chars,
            ),
        }
        record["summary"] = {
            "automated_ok": bool(record["probes"].get("automated_ok")),
            "failed_cases": record["probes"].get("failed_cases", []),
        }
        path = output_dir / "prompt_template_probe_result.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(path)
        return 0 if record["summary"]["automated_ok"] else 1

    if args.matrix:
        return run_matrix(args)

    current_run = now_utc()
    output_dir = args.output_dir / current_run
    record: dict[str, Any] = {
        "run_id": current_run,
        "started_at": iso_now(),
        "model": args.model,
        "fallback_model": args.fallback_model,
        "baseline_model": BASELINE_MODEL,
        "agent_interval_s": args.agent_interval,
        "num_ctx": args.num_ctx,
        "num_predict_cap": args.num_predict_cap,
        "fallback_num_ctx": args.fallback_num_ctx,
        "fallback_num_predict_cap": args.fallback_num_predict_cap,
        "llm_timeout_s": args.llm_timeout_secs,
        "thin_output_min_chars": args.thin_output_min_chars,
        "phase_request": args.phase,
        "output_dir": str(output_dir),
        "preflight": {},
        "phases": [],
        "restore": None,
        "notes": [
            "This runner does not promote defaults.",
            "Operator review of sampled output is still required before promotion.",
        ],
    }

    return_code = 0
    try:
        record["preflight"] = preflight(
            args.model,
            args.num_ctx,
            args.num_predict_cap,
            args.request_timeout_secs,
            args.thin_output_min_chars,
        )
        probe_ok = bool(record["preflight"].get("direct_ollama_probe", {}).get("ok"))
        show_ok = record["preflight"].get("ollama_show", {}).get("returncode") == 0
        template_ok = bool(
            record["preflight"].get("prompt_template_probes", {}).get("automated_ok")
        )
        if not probe_ok or not show_ok or not template_ok:
            record["summary"] = {
                "automated_ok": False,
                "reason": "preflight_failed",
                "probe_ok": probe_ok,
                "ollama_show_ok": show_ok,
                "prompt_template_ok": template_ok,
            }
            return_code = 1
            return return_code

        for phase in phase_order(args.phase):
            record.setdefault("env_set", []).extend(
                set_launch_env(
                    model=args.model,
                    fallback_model=args.fallback_model,
                    interval_s=args.agent_interval,
                    llm_timeout_s=args.llm_timeout_secs,
                    num_ctx=args.num_ctx,
                    num_predict_cap=args.num_predict_cap,
                    fallback_num_ctx=args.fallback_num_ctx,
                    fallback_num_predict_cap=args.fallback_num_predict_cap,
                )
            )
            if phase == "smoke":
                start = start_smoke_stack(args.start_timeout_secs)
                labels = CORE_LABELS
                duration = args.smoke_duration_secs
                fallback_limit = 1
                malformed_limit = 1
            else:
                start = start_normal_stack(args.start_timeout_secs)
                labels = NORMAL_LABELS
                duration = args.normal_duration_secs
                fallback_limit = 5
                malformed_limit = 5

            startup_failures = start_failure_reasons(start)
            if startup_failures:
                monitor = startup_failure_monitor(
                    name=phase,
                    labels=labels,
                    sample_interval_s=args.sample_interval_secs,
                    fallback_limit=fallback_limit,
                    malformed_next_limit=malformed_limit,
                    primary_model=args.model,
                    thin_output_min_chars=args.thin_output_min_chars,
                    failure_reasons=startup_failures,
                )
            else:
                monitor = monitor_phase(
                    name=phase,
                    duration_s=duration,
                    sample_interval_s=args.sample_interval_secs,
                    labels=labels,
                    fallback_limit=fallback_limit,
                    malformed_next_limit=malformed_limit,
                    primary_model=args.model,
                    thin_output_min_chars=args.thin_output_min_chars,
                )
            phase_record = {
                "name": phase,
                "start": start,
                "monitor": monitor,
            }
            record["phases"].append(phase_record)
            write_record(output_dir, record)

            if not phase_record["monitor"]["automated_ok"]:
                return_code = 1
                if phase == "smoke" and not args.continue_after_failed_smoke:
                    break

        failed = [
            phase["name"]
            for phase in record["phases"]
            if not phase.get("monitor", {}).get("automated_ok")
        ]
        record["summary"] = {
            "automated_ok": not failed and args.phase != "preflight",
            "failed_phases": failed,
            "operator_review_required": True,
        }
        if failed:
            return_code = 1
    finally:
        if not args.no_restore:
            record["restore"] = restore_baseline_stack()
        record["completed_at"] = iso_now()
        path = write_record(output_dir, record)
        print(path)

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
