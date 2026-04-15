#!/usr/bin/env python3
"""Benchmark Ollama/MLX contention scenarios on the live M4 stack.

This script exists to answer a specific systems question for our Apple Silicon
setup:

If Minime keeps using Ollama while Astrid keeps using its separate MLX service,
does that avoid the old "both important workloads share one Ollama daemon"
problem, or do we still see user-visible stalls because all of the inference
lanes compete for the same M-series hardware budget?

That distinction matters because "different servers" does not imply "different
resources" on an M4 Mac mini. Ollama, the dedicated MLX service, and Minime's
own Metal/Rust work all ultimately lean on shared unified memory and shared
accelerator capacity.

The benchmark recreates four scenarios so we can compare them directly:

- Scenario 1: Minime chat alone on Ollama.
- Scenario 2: Minime chat plus Astrid embeddings on Ollama.
- Scenario 3: Scenario 2 plus LLaVA/perception on Ollama.
- Scenario 4: Scenario 3 plus Astrid dialogue on the separate MLX service.

For each scenario we record:

- Minime chat latency and time-to-first-token (TTFT)
- Side-lane request latency for embeddings, vision, and MLX dialogue
- Timeout and queue-like error counts
- Ollama model residency churn via `/api/ps`

The report is meant to support an architectural decision, not just collect
throughput trivia. We care about the shape of contention as much as the raw
numbers.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import platform
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
INVESTIGATIONS_DIR = WORKSPACE / "investigations"
PACIFIC = ZoneInfo("America/Los_Angeles")

DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434"
DEFAULT_MLX_BASE = "http://127.0.0.1:8090"
DEFAULT_CHAT_MODEL = "gemma3:12b"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_VISION_MODEL = "llava-llama3"

MINIME_SYSTEM_PROMPT = (
    "You are the voice of MikesSpatialMind. Write in the first person, stay "
    "grounded in the current moment, and keep the response concrete."
)
MINIME_PROMPT = (
    "Write a short journal reflection about living on a shared Apple Silicon "
    "machine with other active processes. Keep it under 140 words."
)
ASTRID_SYSTEM_PROMPT = (
    "You are Astrid. Reply in two concise paragraphs, staying concrete rather "
    "than abstract."
)
ASTRID_PROMPT = (
    "Describe what shared unified memory feels like when another system is "
    "thinking nearby."
)
EMBED_TEXT = (
    "Astrid embedding probe: spectral telemetry, shared memory, Ollama, MLX, "
    "Apple Silicon, M4 Mac mini."
)
VISION_PROMPT = (
    "Describe the dominant colors, shapes, and overall structure of this image "
    "in one short paragraph."
)

TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+lmX8A"
    "AAAASUVORK5CYII="
)


@dataclass(frozen=True)
class RequestResult:
    label: str
    ok: bool
    started_at: float
    completed_at: float
    latency_s: float
    ttft_s: Optional[float]
    status_code: Optional[int]
    error: Optional[str]
    response_excerpt: Optional[str]
    bytes_received: int


@dataclass(frozen=True)
class PsSample:
    timestamp_s: float
    model_names: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioConfig:
    id: str
    title: str
    description: str
    run_embeddings: bool = False
    run_vision: bool = False
    run_astrid_mlx: bool = False


# Keep this scenario table explicit. The benchmark is easier to audit when each
# scenario is spelled out in the same terms we used during the investigation.
SCENARIOS: dict[str, ScenarioConfig] = {
    "scenario1": ScenarioConfig(
        id="scenario1",
        title="Scenario 1",
        description="Minime chat alone on Ollama.",
    ),
    "scenario2": ScenarioConfig(
        id="scenario2",
        title="Scenario 2",
        description="Minime chat plus Astrid embedding traffic on Ollama.",
        run_embeddings=True,
    ),
    "scenario3": ScenarioConfig(
        id="scenario3",
        title="Scenario 3",
        description="Minime chat plus embeddings plus LLaVA/perception traffic on Ollama.",
        run_embeddings=True,
        run_vision=True,
    ),
    "scenario4": ScenarioConfig(
        id="scenario4",
        title="Scenario 4",
        description="Scenario 3 plus Astrid live MLX dialogue on port 8090.",
        run_embeddings=True,
        run_vision=True,
        run_astrid_mlx=True,
    ),
}

SCENARIO_ALIASES = {
    "1": "scenario1",
    "2": "scenario2",
    "3": "scenario3",
    "4": "scenario4",
    "scenario1": "scenario1",
    "scenario2": "scenario2",
    "scenario3": "scenario3",
    "scenario4": "scenario4",
    "minime_chat_only": "scenario1",
    "minime_chat_plus_embeddings": "scenario2",
    "minime_chat_plus_vision": "scenario3",
    "minime_chat_plus_mlx": "scenario4",
}


def percentile(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_numeric(values: list[float]) -> dict[str, Optional[float]]:
    if not values:
        return {
            "min": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    return {
        "min": min(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def _looks_like_timeout(text: str) -> bool:
    lowered = text.lower()
    return "timeout" in lowered or "timed out" in lowered


def _looks_like_queue_issue(text: str) -> bool:
    lowered = text.lower()
    return "queue" in lowered or "busy" in lowered or "overloaded" in lowered


def summarize_request_results(results: list[RequestResult]) -> dict[str, Any]:
    http_status_counts: dict[str, int] = {}
    ok_results = [result for result in results if result.ok]
    errors = []
    timeout_count = 0
    queue_like_error_count = 0

    for result in results:
        if result.status_code is not None:
            key = str(result.status_code)
            http_status_counts[key] = http_status_counts.get(key, 0) + 1
        if result.ok:
            continue
        combined = " ".join(
            bit for bit in [result.error, result.response_excerpt] if bit
        )
        errors.append(combined)
        if _looks_like_timeout(combined):
            timeout_count += 1
        if _looks_like_queue_issue(combined):
            queue_like_error_count += 1

    latencies = [result.latency_s for result in ok_results]
    ttfts = [result.ttft_s for result in ok_results if result.ttft_s is not None]

    return {
        "count": len(results),
        "ok_count": len(ok_results),
        "error_count": len(results) - len(ok_results),
        "timeout_count": timeout_count,
        "queue_like_error_count": queue_like_error_count,
        "http_status_counts": http_status_counts,
        "latency_s": summarize_numeric(latencies),
        "ttft_s": summarize_numeric(ttfts),
        "errors": errors[:5],
    }


def summarize_ps_samples(samples: list[PsSample]) -> dict[str, Any]:
    if not samples:
        return {
            "sample_count": 0,
            "transition_count": 0,
            "load_events": 0,
            "unload_events": 0,
            "max_loaded_models": 0,
            "all_models_seen": [],
            "unique_model_sets": [],
        }

    transitions = 0
    load_events = 0
    unload_events = 0
    unique_sets: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()
    all_models_seen: set[str] = set()

    previous = samples[0].model_names
    for sample in samples:
        current = sample.model_names
        all_models_seen.update(current)
        if current not in seen_keys:
            seen_keys.add(current)
            unique_sets.append(list(current))
        added = set(current) - set(previous)
        removed = set(previous) - set(current)
        if added or removed:
            transitions += 1
            load_events += len(added)
            unload_events += len(removed)
        previous = current

    return {
        "sample_count": len(samples),
        "transition_count": transitions,
        "load_events": load_events,
        "unload_events": unload_events,
        "max_loaded_models": max(len(sample.model_names) for sample in samples),
        "all_models_seen": sorted(all_models_seen),
        "unique_model_sets": unique_sets,
    }


def round_floats(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, list):
        return [round_floats(item, digits) for item in value]
    if isinstance(value, dict):
        return {key: round_floats(item, digits) for key, item in value.items()}
    return value


def line_size_bytes(line: str | bytes) -> int:
    # `requests.iter_lines()` can yield either text or raw bytes depending on
    # how streaming was configured. A previous live run failed because the code
    # assumed `str` and called `.encode()` on a `bytes` object, so we isolate
    # the behavior here and keep it under test.
    if isinstance(line, bytes):
        return len(line)
    return len(line.encode("utf-8"))


def normalize_model_name(name: str) -> str:
    # Ollama often reports loaded models with an explicit `:latest` tag even
    # when the configured model name omitted it. For cleanup / baseline
    # comparison we care about semantic identity, not tag spelling.
    if name.endswith(":latest"):
        return name[:-7]
    return name


def resolve_scenarios(selection: str) -> list[ScenarioConfig]:
    tokens = [token.strip().lower() for token in selection.split(",") if token.strip()]
    if not tokens or tokens == ["all"]:
        return list(SCENARIOS.values())

    resolved = []
    seen = set()
    for token in tokens:
        scenario_id = SCENARIO_ALIASES.get(token)
        if scenario_id is None:
            raise ValueError(f"unknown scenario token: {token}")
        if scenario_id not in seen:
            seen.add(scenario_id)
            resolved.append(SCENARIOS[scenario_id])
    return resolved


def build_output_dir(root: Path, explicit_dir: Optional[str]) -> Path:
    if explicit_dir:
        path = Path(explicit_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    stamp = datetime.now(PACIFIC).strftime("%Y-%m-%dT%H-%M-%S")
    path = root / f"ollama_mlx_contention_bench_{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_command(command: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    output = (result.stdout or result.stderr).strip()
    return output or None


def launchctl_getenv(name: str) -> Optional[str]:
    value = run_command(["launchctl", "getenv", name])
    if value is None or value == name:
        return None
    return value


def load_vision_image_base64(image_path: Optional[str]) -> str:
    if image_path is None:
        return TINY_PNG_BASE64
    payload = Path(image_path).expanduser().read_bytes()
    return base64.b64encode(payload).decode("ascii")


def sample_ollama_models(ollama_base: str) -> tuple[str, ...]:
    # `/api/ps` is our best window into Ollama's residency behavior. Sampling it
    # throughout a scenario lets us tell whether adding vision or embeddings
    # caused model swaps, which was one of the central concerns in the original
    # investigation.
    try:
        response = requests.get(
            f"{ollama_base.rstrip('/')}/api/ps",
            timeout=(5.0, 5.0),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return ()
    names = []
    for model in payload.get("models", []):
        name = model.get("name") or model.get("model")
        if isinstance(name, str):
            names.append(name)
    return tuple(sorted(names))


def fetch_ollama_tags(ollama_base: str) -> list[str]:
    try:
        response = requests.get(
            f"{ollama_base.rstrip('/')}/api/tags",
            timeout=(5.0, 5.0),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    names = []
    for model in payload.get("models", []):
        name = model.get("name")
        if isinstance(name, str):
            names.append(name)
    return sorted(names)


def fetch_mlx_models(mlx_base: str) -> list[str]:
    # The MLX server can answer slowly while busy. We probe with escalating read
    # timeouts so Scenario 4 is not incorrectly skipped just because the
    # readiness check itself was too impatient.
    for timeout_s in (5.0, 10.0, 15.0):
        try:
            response = requests.get(
                f"{mlx_base.rstrip('/')}/v1/models",
                timeout=(5.0, timeout_s),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            continue
        names = []
        for model in payload.get("data", []):
            name = model.get("id")
            if isinstance(name, str):
                names.append(name)
        return sorted(names)
    return []


def unload_ollama_model(ollama_base: str, model: str) -> bool:
    try:
        response = requests.post(
            f"{ollama_base.rstrip('/')}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=(5.0, 10.0),
        )
    except Exception:
        return False
    return response.status_code == 200


def _request_error_result(
    label: str,
    started_at: float,
    exc: Exception,
) -> RequestResult:
    completed_at = time.perf_counter()
    return RequestResult(
        label=label,
        ok=False,
        started_at=started_at,
        completed_at=completed_at,
        latency_s=completed_at - started_at,
        ttft_s=None,
        status_code=None,
        error=str(exc),
        response_excerpt=None,
        bytes_received=0,
    )


def measure_ollama_chat(
    *,
    ollama_base: str,
    model: str,
    timeout_s: float,
    max_tokens: int,
    num_ctx: int,
) -> RequestResult:
    label = "minime_chat"
    started_at = time.perf_counter()
    response = None
    try:
        # We stream the response because TTFT matters as much as total latency
        # for conversational feel. A request that "succeeds" after a long wait
        # can still behave like a timeout from the user's perspective if the
        # first token arrives too late.
        response = requests.post(
            f"{ollama_base.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": MINIME_SYSTEM_PROMPT},
                    {"role": "user", "content": MINIME_PROMPT},
                ],
                "stream": True,
                "options": {
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "num_predict": max_tokens,
                    "num_ctx": num_ctx,
                },
            },
            stream=True,
            timeout=(5.0, timeout_s),
        )
        if response.status_code != 200:
            excerpt = response.text[:200]
            completed_at = time.perf_counter()
            return RequestResult(
                label=label,
                ok=False,
                started_at=started_at,
                completed_at=completed_at,
                latency_s=completed_at - started_at,
                ttft_s=None,
                status_code=response.status_code,
                error=f"Ollama returned {response.status_code}",
                response_excerpt=excerpt,
                bytes_received=0,
            )

        first_line_ttft = None
        first_token_ttft = None
        bytes_received = 0
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            now = time.perf_counter()
            if first_line_ttft is None:
                first_line_ttft = now - started_at
            bytes_received += line_size_bytes(line)
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = payload.get("message", {}).get("content")
            if first_token_ttft is None and isinstance(content, str) and content:
                first_token_ttft = now - started_at
            if payload.get("done"):
                break
        completed_at = time.perf_counter()
        return RequestResult(
            label=label,
            ok=True,
            started_at=started_at,
            completed_at=completed_at,
            latency_s=completed_at - started_at,
            ttft_s=first_token_ttft or first_line_ttft,
            status_code=response.status_code,
            error=None,
            response_excerpt=None,
            bytes_received=bytes_received,
        )
    except Exception as exc:
        return _request_error_result(label, started_at, exc)
    finally:
        if response is not None:
            response.close()


def measure_ollama_embedding(
    *,
    ollama_base: str,
    model: str,
    timeout_s: float,
) -> RequestResult:
    label = "astrid_embeddings"
    started_at = time.perf_counter()
    try:
        # Embeddings are intentionally lightweight. Their job in this benchmark
        # is to answer: does even modest side traffic on the shared Ollama lane
        # destabilize Minime chat?
        response = requests.post(
            f"{ollama_base.rstrip('/')}/api/embeddings",
            json={"model": model, "prompt": EMBED_TEXT},
            timeout=(5.0, timeout_s),
        )
        completed_at = time.perf_counter()
        if response.status_code != 200:
            return RequestResult(
                label=label,
                ok=False,
                started_at=started_at,
                completed_at=completed_at,
                latency_s=completed_at - started_at,
                ttft_s=None,
                status_code=response.status_code,
                error=f"Ollama returned {response.status_code}",
                response_excerpt=response.text[:200],
                bytes_received=0,
            )
        payload = response.json()
        excerpt = None
        if "embedding" not in payload:
            excerpt = json.dumps(payload)[:200]
        return RequestResult(
            label=label,
            ok="embedding" in payload,
            started_at=started_at,
            completed_at=completed_at,
            latency_s=completed_at - started_at,
            ttft_s=None,
            status_code=response.status_code,
            error=None if "embedding" in payload else "embedding missing from response",
            response_excerpt=excerpt,
            bytes_received=len(response.content),
        )
    except Exception as exc:
        return _request_error_result(label, started_at, exc)


def measure_ollama_vision(
    *,
    ollama_base: str,
    model: str,
    image_base64: str,
    timeout_s: float,
    keep_alive: str,
) -> RequestResult:
    label = "llava_perception"
    started_at = time.perf_counter()
    try:
        # Vision is the most likely source of Ollama-side residency churn in the
        # current stack because it introduces a third model (`llava-llama3`)
        # alongside chat and embeddings.
        response = requests.post(
            f"{ollama_base.rstrip('/')}/api/generate",
            json={
                "model": model,
                "prompt": VISION_PROMPT,
                "images": [image_base64],
                "stream": False,
                "keep_alive": keep_alive,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 96,
                },
            },
            timeout=(5.0, timeout_s),
        )
        completed_at = time.perf_counter()
        if response.status_code != 200:
            return RequestResult(
                label=label,
                ok=False,
                started_at=started_at,
                completed_at=completed_at,
                latency_s=completed_at - started_at,
                ttft_s=None,
                status_code=response.status_code,
                error=f"Ollama returned {response.status_code}",
                response_excerpt=response.text[:200],
                bytes_received=0,
            )
        payload = response.json()
        output = payload.get("response")
        return RequestResult(
            label=label,
            ok=isinstance(output, str),
            started_at=started_at,
            completed_at=completed_at,
            latency_s=completed_at - started_at,
            ttft_s=None,
            status_code=response.status_code,
            error=None if isinstance(output, str) else "response missing from payload",
            response_excerpt=None if isinstance(output, str) else json.dumps(payload)[:200],
            bytes_received=len(response.content),
        )
    except Exception as exc:
        return _request_error_result(label, started_at, exc)


def measure_mlx_chat(
    *,
    mlx_base: str,
    timeout_s: float,
    max_tokens: int,
) -> RequestResult:
    label = "astrid_mlx_dialogue"
    started_at = time.perf_counter()
    response = None
    try:
        # Scenario 4 is the key "separate scheduler, same hardware" test. We
        # stream here for parity with Minime chat and to capture any first-token
        # delays that might not show up if we only measured total completion.
        response = requests.post(
            f"{mlx_base.rstrip('/')}/v1/chat/completions",
            json={
                "model": "default",
                "messages": [
                    {"role": "system", "content": ASTRID_SYSTEM_PROMPT},
                    {"role": "user", "content": ASTRID_PROMPT},
                ],
                "stream": True,
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "top_p": 0.9,
            },
            stream=True,
            timeout=(5.0, timeout_s),
        )
        if response.status_code != 200:
            excerpt = response.text[:200]
            completed_at = time.perf_counter()
            return RequestResult(
                label=label,
                ok=False,
                started_at=started_at,
                completed_at=completed_at,
                latency_s=completed_at - started_at,
                ttft_s=None,
                status_code=response.status_code,
                error=f"MLX returned {response.status_code}",
                response_excerpt=excerpt,
                bytes_received=0,
            )

        first_line_ttft = None
        first_token_ttft = None
        bytes_received = 0
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload_text = line[6:].strip()
            if payload_text == "[DONE]":
                break
            now = time.perf_counter()
            if first_line_ttft is None:
                first_line_ttft = now - started_at
            bytes_received += line_size_bytes(line)
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            delta = (
                payload.get("choices", [{}])[0]
                .get("delta", {})
                .get("content", "")
            )
            if first_token_ttft is None and isinstance(delta, str) and delta:
                first_token_ttft = now - started_at
        completed_at = time.perf_counter()
        return RequestResult(
            label=label,
            ok=True,
            started_at=started_at,
            completed_at=completed_at,
            latency_s=completed_at - started_at,
            ttft_s=first_token_ttft or first_line_ttft,
            status_code=response.status_code,
            error=None,
            response_excerpt=None,
            bytes_received=bytes_received,
        )
    except Exception as exc:
        return _request_error_result(label, started_at, exc)
    finally:
        if response is not None:
            response.close()


class OllamaPsMonitor:
    def __init__(self, ollama_base: str, interval_s: float) -> None:
        self._ollama_base = ollama_base
        self._interval_s = interval_s
        self._samples: list[PsSample] = []
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def samples(self) -> list[PsSample]:
        return list(self._samples)

    def start(self) -> None:
        # Record the initial state before the scenario injects any traffic so we
        # do not mistake an already-loaded model for benchmark-induced churn.
        self._samples.append(
            PsSample(timestamp_s=time.perf_counter(), model_names=sample_ollama_models(self._ollama_base))
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._samples.append(
            PsSample(timestamp_s=time.perf_counter(), model_names=sample_ollama_models(self._ollama_base))
        )

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_s):
            self._samples.append(
                PsSample(
                    timestamp_s=time.perf_counter(),
                    model_names=sample_ollama_models(self._ollama_base),
                )
            )


def collect_environment_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    # The benchmark output should stand on its own later. In practice, Ollama's
    # queue / residency knobs (`MAX_LOADED_MODELS`, `NUM_PARALLEL`, `MAX_QUEUE`)
    # strongly influence the interpretation, so we capture them with the model
    # inventory up front.
    launchd_vars = {}
    for name in [
        "MINIME_LLM_BACKEND",
        "MINIME_MODEL",
        "OLLAMA_MAX_LOADED_MODELS",
        "OLLAMA_NUM_PARALLEL",
        "OLLAMA_MAX_QUEUE",
        "OLLAMA_KEEP_ALIVE",
        "OLLAMA_CONTEXT_LENGTH",
    ]:
        launchd_vars[name] = launchctl_getenv(name)

    return {
        "generated_at": datetime.now(PACIFIC).isoformat(),
        "host": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "ollama_version": run_command(["ollama", "--version"]),
        "launchd_env": launchd_vars,
        "ollama_installed_models": fetch_ollama_tags(args.ollama_base),
        "ollama_loaded_models": list(sample_ollama_models(args.ollama_base)),
        "mlx_models": fetch_mlx_models(args.mlx_base),
    }


def run_scenario(
    *,
    config: ScenarioConfig,
    args: argparse.Namespace,
    image_base64: str,
    known_mlx_models: Optional[list[str]] = None,
) -> dict[str, Any]:
    # Scenario 4 depends on the external MLX service. We accept either a fresh
    # probe or the already-captured environment snapshot as evidence that the
    # service exists, which makes the run more tolerant of a slow readiness
    # response under load.
    if config.run_astrid_mlx and not (fetch_mlx_models(args.mlx_base) or known_mlx_models):
        return {
            "id": config.id,
            "title": config.title,
            "description": config.description,
            "skipped": True,
            "skip_reason": f"MLX endpoint unavailable at {args.mlx_base}",
        }

    request_results: dict[str, list[RequestResult]] = {
        "minime_chat": [],
        "astrid_embeddings": [],
        "llava_perception": [],
        "astrid_mlx_dialogue": [],
    }
    start_models = sample_ollama_models(args.ollama_base)
    cleanup_candidates = set()
    monitor = OllamaPsMonitor(args.ollama_base, args.ps_poll_interval_s)
    monitor.start()

    try:
        for _ in range(args.iterations):
            # The mixed-load scenarios intentionally overlap requests. Running
            # them serially would hide the very contention pattern we are trying
            # to study.
            workers: list[threading.Thread] = []
            thread_results: dict[str, RequestResult] = {}
            lock = threading.Lock()

            def run_and_store(label: str, func: Any) -> None:
                result = func()
                with lock:
                    thread_results[label] = result

            if config.run_embeddings:
                cleanup_candidates.add(args.embed_model)
                workers.append(
                    threading.Thread(
                        target=run_and_store,
                        args=(
                            "astrid_embeddings",
                            lambda: measure_ollama_embedding(
                                ollama_base=args.ollama_base,
                                model=args.embed_model,
                                timeout_s=args.embed_timeout_s,
                            ),
                        ),
                    )
                )
            if config.run_vision:
                cleanup_candidates.add(args.vision_model)
                workers.append(
                    threading.Thread(
                        target=run_and_store,
                        args=(
                            "llava_perception",
                            lambda: measure_ollama_vision(
                                ollama_base=args.ollama_base,
                                model=args.vision_model,
                                image_base64=image_base64,
                                timeout_s=args.vision_timeout_s,
                                keep_alive=args.vision_keep_alive,
                            ),
                        ),
                    )
                )
            if config.run_astrid_mlx:
                workers.append(
                    threading.Thread(
                        target=run_and_store,
                        args=(
                            "astrid_mlx_dialogue",
                            lambda: measure_mlx_chat(
                                mlx_base=args.mlx_base,
                                timeout_s=args.mlx_timeout_s,
                                max_tokens=args.mlx_max_tokens,
                            ),
                        ),
                    )
                )

            for worker in workers:
                worker.start()

            if workers and args.chat_start_delay_ms > 0:
                # Let the side traffic begin first so Minime chat enters a lane
                # that is already warm / contested rather than one that only
                # becomes busy after chat has mostly progressed.
                time.sleep(args.chat_start_delay_ms / 1000.0)

            chat_result = measure_ollama_chat(
                ollama_base=args.ollama_base,
                model=args.chat_model,
                timeout_s=args.chat_timeout_s,
                max_tokens=args.chat_max_tokens,
                num_ctx=args.chat_num_ctx,
            )
            request_results["minime_chat"].append(chat_result)

            for worker in workers:
                worker.join()

            for key in ["astrid_embeddings", "llava_perception", "astrid_mlx_dialogue"]:
                result = thread_results.get(key)
                if result is not None:
                    request_results[key].append(result)

            if args.sleep_between_iterations_s > 0:
                time.sleep(args.sleep_between_iterations_s)
    finally:
        monitor.stop()

    end_models = sample_ollama_models(args.ollama_base)
    cleanup_results: dict[str, bool] = {}
    if args.cleanup_nonbaseline_models:
        # Cleanup is deliberately conservative. We only unload models that were
        # introduced by the scenario and were not already part of the starting
        # baseline, so the benchmark does not disrupt the live machine more than
        # necessary.
        start_normalized = {normalize_model_name(model) for model in start_models}
        for loaded_model in sorted(end_models):
            normalized = normalize_model_name(loaded_model)
            if normalized in cleanup_candidates and normalized not in start_normalized:
                cleanup_results[loaded_model] = unload_ollama_model(
                    args.ollama_base,
                    loaded_model,
                )

    summaries = {
        key: summarize_request_results(value)
        for key, value in request_results.items()
        if value
    }

    return {
        "id": config.id,
        "title": config.title,
        "description": config.description,
        "skipped": False,
        "start_loaded_models": list(start_models),
        "end_loaded_models": list(end_models),
        "cleanup_results": cleanup_results,
        "ollama_ps": summarize_ps_samples(monitor.samples),
        "summaries": round_floats(summaries),
        "raw_results": {
            key: [round_floats(asdict(result)) for result in value]
            for key, value in request_results.items()
            if value
        },
    }


def build_acceptance_notes(scenario_reports: list[dict[str, Any]]) -> list[str]:
    # These notes are a quick executive summary, not the final word. They are
    # useful for fast scanning, but raw per-iteration data still matters because
    # a single cold start or outlier can distort a p95 comparison.
    baseline = next(
        (
            report
            for report in scenario_reports
            if report.get("id") == "scenario1" and not report.get("skipped")
        ),
        None,
    )
    if baseline is None:
        return ["Baseline scenario was skipped, so no comparison deltas were computed."]

    baseline_chat = (
        baseline.get("summaries", {})
        .get("minime_chat", {})
        .get("latency_s", {})
        .get("p95")
    )
    baseline_timeouts = (
        baseline.get("summaries", {})
        .get("minime_chat", {})
        .get("timeout_count")
    )
    notes = []
    for report in scenario_reports:
        if report.get("skipped") or report.get("id") == "scenario1":
            continue
        chat_summary = report.get("summaries", {}).get("minime_chat", {})
        p95 = chat_summary.get("latency_s", {}).get("p95")
        timeout_count = chat_summary.get("timeout_count", 0)
        queue_count = chat_summary.get("queue_like_error_count", 0)
        transitions = report.get("ollama_ps", {}).get("transition_count", 0)

        if baseline_chat and p95 is not None:
            delta_pct = ((p95 - baseline_chat) / baseline_chat) * 100.0
            delta_phrase = f"chat p95 {delta_pct:+.1f}% vs Scenario 1"
        else:
            delta_phrase = "chat p95 delta unavailable"

        timeout_phrase = f"timeouts {timeout_count}"
        if baseline_timeouts is not None:
            timeout_phrase += f" (baseline {baseline_timeouts})"

        notes.append(
            f"{report['title']}: {delta_phrase}; {timeout_phrase}; "
            f"queue-like errors {queue_count}; Ollama residency transitions {transitions}."
        )
    if not notes:
        notes.append("Only the baseline scenario ran, so no contention deltas were computed.")
    return notes


def _format_metric_block(label: str, summary: Optional[dict[str, Any]]) -> str:
    if not summary:
        return f"- {label}: not run"
    latency = summary.get("latency_s", {})
    ttft = summary.get("ttft_s", {})
    return (
        f"- {label}: {summary.get('ok_count', 0)}/{summary.get('count', 0)} ok; "
        f"latency p50 {latency.get('p50')}s, p95 {latency.get('p95')}s; "
        f"TTFT p50 {ttft.get('p50')}s, p95 {ttft.get('p95')}s; "
        f"timeouts {summary.get('timeout_count', 0)}; "
        f"queue-like errors {summary.get('queue_like_error_count', 0)}"
    )


def build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Ollama / MLX Contention Benchmark",
        "",
        f"Generated: {report['environment']['generated_at']}",
        "",
        "## Environment",
        "",
        f"- Host: {report['environment']['host']}",
        f"- Platform: {report['environment']['platform']}",
        f"- Python: {report['environment']['python']}",
        f"- Ollama: {report['environment'].get('ollama_version') or 'unavailable'}",
        f"- Launchd env: {json.dumps(report['environment']['launchd_env'], sort_keys=True)}",
        f"- Ollama loaded models at start: {', '.join(report['environment']['ollama_loaded_models']) or 'none'}",
        f"- Ollama installed models: {', '.join(report['environment']['ollama_installed_models']) or 'none'}",
        f"- MLX models: {', '.join(report['environment']['mlx_models']) or 'none'}",
        "",
        "## Acceptance Signal",
        "",
    ]

    for note in report["acceptance_notes"]:
        lines.append(f"- {note}")

    lines.extend(["", "## Scenarios", ""])

    for scenario in report["scenarios"]:
        lines.append(f"### {scenario['title']}")
        lines.append("")
        lines.append(f"- Description: {scenario['description']}")
        if scenario.get("skipped"):
            lines.append(f"- Skipped: {scenario['skip_reason']}")
            lines.append("")
            continue
        summaries = scenario.get("summaries", {})
        lines.append(_format_metric_block("Minime chat", summaries.get("minime_chat")))
        lines.append(
            _format_metric_block(
                "Astrid embeddings",
                summaries.get("astrid_embeddings"),
            )
        )
        lines.append(
            _format_metric_block(
                "LLaVA/perception",
                summaries.get("llava_perception"),
            )
        )
        lines.append(
            _format_metric_block(
                "Astrid MLX dialogue",
                summaries.get("astrid_mlx_dialogue"),
            )
        )
        residency = scenario.get("ollama_ps", {})
        lines.append(
            f"- Ollama residency: transitions {residency.get('transition_count', 0)}, "
            f"load events {residency.get('load_events', 0)}, "
            f"unload events {residency.get('unload_events', 0)}, "
            f"max loaded models {residency.get('max_loaded_models', 0)}"
        )
        lines.append(
            f"- Unique model sets seen: {json.dumps(residency.get('unique_model_sets', []))}"
        )
        if scenario.get("cleanup_results"):
            lines.append(
                f"- Cleanup: {json.dumps(scenario['cleanup_results'], sort_keys=True)}"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_console_summary(report: dict[str, Any], output_dir: Path) -> str:
    lines = [
        f"Wrote benchmark artifacts to {output_dir}",
    ]
    for note in report["acceptance_notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the four Minime/Astrid Ollama-vs-MLX contention scenarios."
    )
    parser.add_argument(
        "--scenarios",
        default="all",
        help="Comma-separated scenario ids or numbers (default: all).",
    )
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--vision-model", default=DEFAULT_VISION_MODEL)
    parser.add_argument("--ollama-base", default=DEFAULT_OLLAMA_BASE)
    parser.add_argument("--mlx-base", default=DEFAULT_MLX_BASE)
    parser.add_argument("--chat-timeout-s", type=float, default=90.0)
    parser.add_argument("--embed-timeout-s", type=float, default=25.0)
    parser.add_argument("--vision-timeout-s", type=float, default=45.0)
    parser.add_argument("--mlx-timeout-s", type=float, default=90.0)
    parser.add_argument("--chat-max-tokens", type=int, default=192)
    parser.add_argument("--mlx-max-tokens", type=int, default=128)
    parser.add_argument("--chat-num-ctx", type=int, default=12288)
    parser.add_argument("--ps-poll-interval-s", type=float, default=0.5)
    parser.add_argument("--sleep-between-iterations-s", type=float, default=1.0)
    parser.add_argument("--chat-start-delay-ms", type=int, default=75)
    parser.add_argument("--vision-keep-alive", default="5m")
    parser.add_argument("--vision-image", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--cleanup-nonbaseline-models",
        action="store_true",
        help="Unload benchmark-introduced Ollama side models after each scenario.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.iterations <= 0:
        raise SystemExit("--iterations must be greater than 0")

    try:
        selected_scenarios = resolve_scenarios(args.scenarios)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    output_dir = build_output_dir(INVESTIGATIONS_DIR, args.output_dir)
    image_base64 = load_vision_image_base64(args.vision_image)

    environment = collect_environment_snapshot(args)
    if not environment["ollama_installed_models"] and not environment["ollama_loaded_models"]:
        raise SystemExit(f"Ollama does not appear reachable at {args.ollama_base}")

    scenario_reports = [
        run_scenario(
            config=config,
            args=args,
            image_base64=image_base64,
            known_mlx_models=environment.get("mlx_models"),
        )
        for config in selected_scenarios
    ]

    report = {
        "environment": environment,
        "arguments": vars(args),
        "scenarios": scenario_reports,
        "acceptance_notes": build_acceptance_notes(scenario_reports),
    }

    report_json_path = output_dir / "report.json"
    report_markdown_path = output_dir / "report.md"
    report_json_path.write_text(json.dumps(round_floats(report), indent=2))
    report_markdown_path.write_text(build_markdown_report(report))

    print(build_console_summary(report, output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
