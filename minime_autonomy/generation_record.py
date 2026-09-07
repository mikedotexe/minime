"""Steward-only record of every LLM generation minime makes.

Tranche 1 (2026-09-06, Mike & Claude). One JSON file per backend attempt under
``workspace/generations/<UTC day>/`` (0600 files inside 0700 directories); the
system prompt is deduplicated by sha256 into
``workspace/generations/system_prompts/<sha>.txt``.

Why: until now nothing said, for a given journal entry, which model wrote it,
what prompt it actually saw (the Ollama adapter compacts the system prompt
before posting), or whether the primary model timed out and the small
stand-in answered instead. Each record carries all three, plus the lane the
generation served (the ``action`` of the enclosing ``_execute_action`` frame,
the same vocabulary as ``action_events`` and ``llm_jobs``) and the artifact
it produced.

Guarantees:

* never raises into the LLM path: every public function swallows and logs
  its own failures at DEBUG level and returns a harmless default;
* no runtime import: this module depends on the standard library only
  (``parse_next_action`` is imported lazily, at record time, from the sibling
  ``parsing`` module the runtime has already loaded);
* records are never surfaced into prompts; they exist for the stewards'
  analysis only (see the reservoir-llm-research repo);
* kill switch ``MINIME_GENERATION_RECORD=off``; directory override
  ``MINIME_GENERATION_RECORD_DIR``.
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import re
import stat
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1
CONTRACT_VERSION = "minime_query_llm_v1"
BEING = "minime"
ENV_ENABLED = "MINIME_GENERATION_RECORD"
ENV_DIR = "MINIME_GENERATION_RECORD_DIR"
ENV_IN_TESTS = "MINIME_GENERATION_RECORD_IN_TESTS"
RECORD_SUBDIR = "generations"
SYSTEM_PROMPTS_SUBDIR = "system_prompts"
LANE_UNKNOWN = "unknown"
#: An artifact may be linked to the last record written on this thread only
#: while that record is this fresh (seconds); older records are left alone.
LINK_RECENCY_S = 900.0
#: Without a content match, a journal link is accepted on recency alone only
#: this soon after the record was written.
RECENCY_MATCH_S = 120.0

_PROBE_CHARS = 48
_CALLER_CHAIN_MAX = 16
_LANE_FRAME_RE = re.compile(
    r"^_(recess_\w+|journal_\w+|check_moment_markers|self_study\w*|introspect\w*"
    r"|decompose\w*|verify_sovereignty\w*)$"
)
_SKIP_FRAME_RE = re.compile(r"^(_query_(llm|mlx|ollama)\w*|wrapper|run|_bootstrap\w*)$")
_INBOX_MARKERS = (
    "[A note was left for you:]",
    "=== MIKE FEEDBACK",
    "=== STEWARD FEEDBACK",
)
_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")

_THIS_FILE = __file__
_log = logging.getLogger(__name__)
_state = threading.local()


# --------------------------------------------------------------------------- #
# Safety wrapper
# --------------------------------------------------------------------------- #
def _never_raises(default: Any = None, default_factory: Optional[Callable[[], Any]] = None) -> Callable:
    """Wrap a public entry point so a failure here can never reach the LLM path."""

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - by design: never raise into the LLM path
                try:
                    _log.debug(
                        "generation_record.%s swallowed %s: %s",
                        fn.__name__,
                        type(exc).__name__,
                        exc,
                    )
                except Exception:  # pragma: no cover - logging must not raise either
                    pass
                return default_factory() if default_factory is not None else default

        return wrapper

    return decorate


def _tls() -> threading.local:
    if not getattr(_state, "ready", False):
        _state.ready = True
        _state.stash = None
        _state.last_record_path = None
        _state.last_record_at = 0.0
        _state.last_response_text = ""
        _state.linked_kinds = set()
    return _state


def reset_thread_state() -> None:
    """Forget this thread's stash and last record (tests, or a fresh worker)."""
    _state.ready = False
    _tls()


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def enabled() -> bool:
    """On by default; ``MINIME_GENERATION_RECORD=off`` disables.

    Under pytest the record stays off unless ``MINIME_GENERATION_RECORD_IN_TESTS``
    is set, so a test that drives the LLM path without redirecting
    ``WORKSPACE_DIR`` can never leave a stray record in a live workspace.
    """
    raw = os.environ.get(ENV_ENABLED, "on")
    if (raw or "").strip().lower() in {"off", "0", "false", "no"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        opt_in = os.environ.get(ENV_IN_TESTS, "")
        return opt_in.strip().lower() in {"1", "on", "true", "yes"}
    return True


def default_record_dir(workspace_dir: Any) -> Path:
    override = (os.environ.get(ENV_DIR) or "").strip()
    if override:
        return Path(override).expanduser()
    return Path(workspace_dir) / RECORD_SUBDIR


def last_record_path() -> Optional[Path]:
    return _tls().last_record_path


# --------------------------------------------------------------------------- #
# Per-generation context
# --------------------------------------------------------------------------- #
class GenerationContext:
    """Facts shared by every attempt record of one generation."""

    __slots__ = (
        "generation_id",
        "record_dir",
        "prompt",
        "system_msg",
        "prompt_class",
        "attempts",
        "kind",
        "models",
        "lane",
        "lane_source",
        "job_id",
        "caller_chain",
        "context_mode",
        "action_id",
        "thread_id",
        "inbox_present",
        "started_perf",
        "attempt_started_perf",
    )

    def __init__(
        self,
        record_dir: Path,
        *,
        prompt: str,
        system_msg: str,
        prompt_class: str,
        attempts: List[str],
        kind: str,
        models: Dict[str, Any],
        lane_info: Dict[str, Any],
        continuity: Dict[str, Any],
    ) -> None:
        now_ms = int(time.time() * 1000)
        self.generation_id = f"{now_ms}-{uuid.uuid4().hex[:8]}"
        self.record_dir = record_dir
        self.prompt = prompt
        self.system_msg = system_msg
        self.prompt_class = prompt_class
        self.attempts = attempts
        self.kind = kind
        self.models = models
        self.lane = str(lane_info.get("lane") or LANE_UNKNOWN)
        self.lane_source = str(lane_info.get("lane_source") or "none")
        self.job_id = lane_info.get("job_id")
        self.caller_chain = list(lane_info.get("caller_chain") or [])
        self.context_mode = lane_info.get("context_mode")
        self.action_id = continuity.get("action_id")
        self.thread_id = continuity.get("thread_id")
        self.inbox_present = any(marker in prompt for marker in _INBOX_MARKERS)
        self.started_perf = time.perf_counter()
        self.attempt_started_perf = self.started_perf


def _scalar(value: Any) -> Any:
    return value if isinstance(value, (str, int, float, bool)) else None


def _clean_models(models: Any) -> Dict[str, Any]:
    if not isinstance(models, dict):
        return {}
    return {str(key): _scalar(value) for key, value in models.items()}


# --------------------------------------------------------------------------- #
# Lane inference (a labeling aid, not ground truth)
# --------------------------------------------------------------------------- #
def _empty_lane_info() -> Dict[str, Any]:
    return {
        "lane": LANE_UNKNOWN,
        "lane_source": "none",
        "job_id": None,
        "caller_chain": [],
        "context_mode": None,
    }


@_never_raises(default_factory=_empty_lane_info)
def infer_lane() -> Dict[str, Any]:
    """Label the generation from the call stack.

    ``lane`` is the ``action`` local of the innermost ``_execute_action`` frame
    (the action vocabulary); failing that, the first frame whose name looks
    like a lane (``_recess_*``, ``_journal_*``, ``_check_moment_markers`` ...);
    failing that, ``unknown``. ``job_id`` comes from the same frame, from
    ``_run_llm_action_job``, or from the worker thread name. ``context_mode``
    is read from the enclosing ``_query_llm`` frame when present.
    """
    lane: Optional[str] = None
    fallback_lane: Optional[str] = None
    job_id: Optional[str] = None
    context_mode: Optional[str] = None
    chain: List[str] = []
    frame = sys._getframe(1)
    depth = 0
    while frame is not None and depth < 120:
        code = frame.f_code
        name = code.co_name
        if code.co_filename != _THIS_FILE:
            local = frame.f_locals
            if name == "_query_llm" and context_mode is None:
                value = local.get("context_mode")
                if isinstance(value, str):
                    context_mode = value
            if name == "_execute_action" and lane is None:
                value = local.get("action")
                if isinstance(value, str) and value.strip():
                    lane = value.strip()
                    job = local.get("_llm_job_id")
                    if isinstance(job, str) and job:
                        job_id = job
            elif fallback_lane is None and _LANE_FRAME_RE.match(name):
                fallback_lane = name[1:]
            if name == "_run_llm_action_job" and job_id is None:
                job = local.get("job_id")
                if isinstance(job, str) and job:
                    job_id = job
            if (
                len(chain) < _CALLER_CHAIN_MAX
                and not name.startswith("<")
                and not _SKIP_FRAME_RE.match(name)
            ):
                chain.append(name)
        frame = frame.f_back
        depth += 1
    if job_id is None:
        thread_name = threading.current_thread().name
        prefix = "minime-llm-job-"
        if thread_name.startswith(prefix):
            job_id = thread_name[len(prefix):]
    if lane:
        lane_source = "execute_action"
    elif fallback_lane:
        lane_source = "frame"
    else:
        lane_source = "none"
    return {
        "lane": lane or fallback_lane or LANE_UNKNOWN,
        "lane_source": lane_source,
        "job_id": job_id,
        "caller_chain": chain,
        "context_mode": context_mode,
    }


# --------------------------------------------------------------------------- #
# Hooks called from the runtime
# --------------------------------------------------------------------------- #
@_never_raises(default=None)
def begin(
    workspace_dir: Any,
    *,
    prompt: str,
    system_msg: str,
    prompt_class: str,
    attempts: Sequence[str],
    kind: str,
    models: Optional[Dict[str, Any]] = None,
    agent: Any = None,
) -> Optional[GenerationContext]:
    """Open a generation. Returns ``None`` when recording is off."""
    if not enabled():
        return None
    lane_info = infer_lane()
    continuity: Dict[str, Any] = {}
    event = getattr(agent, "_current_action_continuity_event", None) if agent is not None else None
    if isinstance(event, dict):
        continuity = {
            "action_id": _scalar(event.get("action_id")),
            "thread_id": _scalar(event.get("thread_id")),
        }
    ctx = GenerationContext(
        default_record_dir(workspace_dir),
        prompt=prompt or "",
        system_msg=system_msg or "",
        prompt_class=str(prompt_class or ""),
        attempts=[str(attempt) for attempt in (attempts or [])],
        kind=str(kind or "full"),
        models=_clean_models(models),
        lane_info=lane_info,
        continuity=continuity,
    )
    _tls().stash = None
    return ctx


@_never_raises(default=None)
def stash_attempt(messages: Any, timing: Any) -> None:
    """Called from the Ollama HTTP function's ``finally``: keep what was posted."""
    if not enabled():
        return None
    _tls().stash = {
        "messages": _copy_messages(messages),
        "timing": dict(timing) if isinstance(timing, dict) else {},
        "at": time.perf_counter(),
    }
    return None


@_never_raises(default=None)
def record_attempt(
    ctx: Optional[GenerationContext],
    attempt_index: int,
    backend: str,
    *,
    result: Optional[str] = None,
    error: Optional[BaseException] = None,
) -> Optional[Path]:
    """Write one attempt record. Returns its path, or ``None``."""
    if ctx is None or not enabled():
        return None
    tls = _tls()
    stash = tls.stash
    tls.stash = None
    timing: Dict[str, Any] = {}
    messages: List[Dict[str, str]] = []
    messages_source = "reconstructed"
    if isinstance(stash, dict) and float(stash.get("at") or 0.0) >= ctx.started_perf:
        timing = stash.get("timing") or {}
        messages = stash.get("messages") or []
        if messages:
            messages_source = "adapted"
    if messages_source == "reconstructed":
        messages = [
            {"role": "system", "content": ctx.system_msg},
            {"role": "user", "content": ctx.prompt},
        ]
    status, error_name = _classify(result, error, timing)
    model = _scalar(timing.get("model")) or _model_for_backend(backend, ctx.models)
    elapsed = timing.get("elapsed_s")
    if not isinstance(elapsed, (int, float)):
        elapsed = round(time.perf_counter() - ctx.attempt_started_perf, 3)
    response_text = result if isinstance(result, str) else None
    snapshot, system_prompts = snapshot_messages(messages)
    now = time.time()
    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "being": BEING,
        "generation_id": ctx.generation_id,
        "lane": ctx.lane,
        "lane_source": ctx.lane_source,
        "caller_chain": ctx.caller_chain,
        "context_mode": ctx.context_mode,
        "prompt_class": ctx.prompt_class,
        "kind": ctx.kind,
        "models": ctx.models,
        "model": model,
        "backend": str(backend),
        "attempt_index": int(attempt_index),
        "attempts_total": len(ctx.attempts),
        "attempts": ctx.attempts,
        "fallback_used": bool(int(attempt_index) > 0 or str(backend) == "ollama_fast"),
        "timeout_s": _scalar(timing.get("timeout_s")),
        "elapsed_s": elapsed,
        "status": status,
        "error": error_name,
        "http_status": _scalar(timing.get("http_status")),
        "backend_timing": {
            key: _scalar(timing.get(key))
            for key in ("total_duration", "eval_count", "eval_duration", "effective_num_predict", "num_ctx", "requested_max_tokens")
            if key in timing
        },
        "adapter": {
            "template_mode": _scalar(timing.get("prompt_template_mode")),
            "compacted": _scalar(timing.get("prompt_compacted")),
            "adapted_prompt_chars": _scalar(timing.get("adapted_prompt_chars")),
            "adapted_system_chars": _scalar(timing.get("adapted_system_chars")),
        } if timing else None,
        "messages": snapshot,
        "messages_source": messages_source,
        "inbox_present": ctx.inbox_present,
        "response_text": response_text,
        "response_sha256": _sha256(response_text) if response_text else None,
        "response_chars": len(response_text) if response_text else 0,
        "next_action_parsed": _parse_next_action_safe(response_text) if response_text else None,
        "linked_artifacts": [],
        "job_id": ctx.job_id,
        "action_id": ctx.action_id,
        "thread_id": ctx.thread_id,
        "thread": threading.current_thread().name,
        "pid": os.getpid(),
        "created_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "created_at_unix_ms": int(now * 1000),
    }
    path = write_record_at(ctx.record_dir, record, system_prompts)
    ctx.attempt_started_perf = time.perf_counter()
    if path is not None:
        tls.last_record_path = path
        tls.last_record_at = now
        tls.last_response_text = response_text or ""
        tls.linked_kinds = set()
    return path


@_never_raises(default=None)
def link_artifact(kind: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Attach an artifact (journal file, action, job) to this thread's last record.

    ``content`` (when given) is matched against the recorded response; a link
    is written with ``match: "content"`` when they overlap, ``"recency"`` when
    the record is younger than ``RECENCY_MATCH_S``, and not at all otherwise.
    One link per kind per record.
    """
    if not enabled():
        return None
    tls = _tls()
    path = tls.last_record_path
    if path is None:
        return None
    age = time.time() - float(tls.last_record_at or 0.0)
    if age > LINK_RECENCY_S or kind in tls.linked_kinds:
        return None
    content = fields.pop("content", None)
    match: Optional[str] = None
    if content is not None:
        if not tls.last_response_text:
            return None
        if _texts_overlap(tls.last_response_text, str(content)):
            match = "content"
        elif age <= RECENCY_MATCH_S:
            match = "recency"
        else:
            return None
    entry: Dict[str, Any] = {"kind": str(kind), "match": match, "linked_at": time.time()}
    entry.update({key: value for key, value in fields.items() if _scalar(value) is not None})

    def mutate(record: Dict[str, Any]) -> None:
        record.setdefault("linked_artifacts", []).append(entry)

    if not _update_record_file(path, mutate):
        return None
    tls.linked_kinds.add(kind)
    return entry


@_never_raises(default=False)
def note_next_action(next_action: Any) -> bool:
    """Record the NEXT the runtime accepted for this thread's last generation."""
    if not enabled():
        return False
    tls = _tls()
    path = tls.last_record_path
    if path is None or time.time() - float(tls.last_record_at or 0.0) > RECENCY_MATCH_S:
        return False
    value = next_action if isinstance(next_action, str) else (None if next_action is None else str(next_action))

    def mutate(record: Dict[str, Any]) -> None:
        record["next_action"] = value

    return _update_record_file(path, mutate)


# --------------------------------------------------------------------------- #
# Record construction helpers
# --------------------------------------------------------------------------- #
def _copy_messages(messages: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(messages, (list, tuple)):
        return out
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = item.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        out.append({"role": str(item.get("role", "")), "content": content})
    return out


def _classify(
    result: Optional[str], error: Optional[BaseException], timing: Dict[str, Any]
) -> Tuple[str, Optional[str]]:
    if error is not None:
        name = type(error).__name__
        if "timeout" in name.lower() or "timedout" in name.lower():
            return "timeout", name
        if timing.get("status") == "http_error":
            return "http_error", name
        return "error", name
    if timing.get("status") in ("http_error", "error"):
        return str(timing["status"]), _scalar(timing.get("error"))
    if result:
        return "ok", None
    return "empty", None


def _model_for_backend(backend: str, models: Dict[str, Any]) -> Optional[str]:
    if backend == "ollama":
        return models.get("primary")
    if backend == "ollama_fast":
        return models.get("fallback")
    if backend == "mlx":
        return models.get("mlx") or "mlx:default"
    return None


def snapshot_messages(messages: Sequence[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """System-role content becomes a sha256 reference; other roles are kept verbatim."""
    system_prompts: Dict[str, str] = {}
    out: List[Dict[str, Any]] = []
    for item in messages:
        role = str(item.get("role", ""))
        content = item.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if role == "system":
            sha = _sha256(content)
            system_prompts[sha] = content
            out.append({"role": role, "content_sha256": sha, "chars": len(content)})
        else:
            out.append({"role": role, "content": content, "chars": len(content)})
    return out, system_prompts


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_next_action_safe(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    try:
        from .parsing import parse_next_action  # lazy: already loaded by the runtime
    except Exception:
        return None
    try:
        parsed = parse_next_action(text)
    except Exception:
        return None
    if isinstance(parsed, tuple) and parsed:
        value = parsed[0]
        return value if isinstance(value, str) else None
    return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _probes(normalized: str) -> List[str]:
    length = len(normalized)
    if length <= _PROBE_CHARS:
        return [normalized] if normalized else []
    starts = sorted({int(length * fraction) for fraction in (0.25, 0.5, 0.75)})
    probes = [normalized[start:start + _PROBE_CHARS] for start in starts if start + _PROBE_CHARS <= length]
    return probes or [normalized[:_PROBE_CHARS]]


def _texts_overlap(response: str, content: str) -> bool:
    a = _normalize_text(response)
    b = _normalize_text(content)
    if not a or not b:
        return False
    return any(probe in a for probe in _probes(b)) or any(probe in b for probe in _probes(a))


# --------------------------------------------------------------------------- #
# Private file writing
# --------------------------------------------------------------------------- #
def _slug(value: str) -> str:
    return (_SLUG_RE.sub("_", value).strip("_") or LANE_UNKNOWN)[:40]


def _ensure_private_dir(path: Path) -> None:
    """Create if needed and keep steward-only (0700), tightening a looser mode."""
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
    try:
        if stat.S_IMODE(os.stat(path).st_mode) != 0o700:
            os.chmod(path, 0o700)
    except OSError:
        pass


def _write_private_file_once(path: Path, text: str) -> bool:
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def _update_record_file(path: Path, mutate: Callable[[Dict[str, Any]], None]) -> bool:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        record = json.load(handle)
    mutate(record)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return True


@_never_raises(default=None)
def write_record_at(
    record_dir: Any, record: Dict[str, Any], system_prompts: Optional[Dict[str, str]] = None
) -> Optional[Path]:
    """Write one record (0600) under ``record_dir/<UTC day>/`` and dedup system prompts."""
    root = Path(record_dir)
    day_dir = root / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _ensure_private_dir(root)
    _ensure_private_dir(day_dir)
    if system_prompts:
        prompts_dir = root / SYSTEM_PROMPTS_SUBDIR
        _ensure_private_dir(prompts_dir)
        for sha, text in system_prompts.items():
            _write_private_file_once(prompts_dir / f"{sha}.txt", text)
    lane = _slug(str(record.get("lane") or LANE_UNKNOWN))
    created_ms = int(record.get("created_at_unix_ms") or time.time() * 1000)
    base = f"gen_{created_ms}_{lane}_a{int(record.get('attempt_index') or 0)}"
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
    for suffix in ("", "_1", "_2", "_3", "_4"):
        path = day_dir / f"{base}{suffix}.json"
        if _write_private_file_once(path, payload):
            return path
    return None
