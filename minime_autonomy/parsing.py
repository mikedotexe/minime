"""Action vocabulary, normalization, and parsing for Minime autonomy.

This module is intentionally pure: it turns model text into bounded action
requests and evidence envelopes without touching runtime state or live control.
"""

import re
import shlex
import struct
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .self_regulation import REGULATORY_REGIMES
from .action_vocabulary import *  # noqa: F403 - compatibility surface

from .research import extract_label_value, trim_chars
def normalize_action_arg(text: str) -> str:
    trimmed = text.strip()
    quote_pairs = [('"', '"'), ("'", "'"), ("“", "”")]
    for open_quote, close_quote in quote_pairs:
        if trimmed.startswith(open_quote) and trimmed.endswith(close_quote):
            return trimmed[len(open_quote):-len(close_quote)].strip()
    return trimmed


def first_sentence(raw_excerpt: str) -> str:
    for marker in [".", "!", "?"]:
        if marker in raw_excerpt:
            raw_excerpt = raw_excerpt.split(marker, 1)[0]
            break
    return trim_chars(" ".join(raw_excerpt.split()), 220)


def fallback_meaning_line(label: str, source_kind: str, anchor: str, subject: str, raw_excerpt: str) -> str:
    anchor = trim_chars(anchor, 120)
    subject = trim_chars(subject, 120)
    excerpt = first_sentence(raw_excerpt)
    if label == "Why it may matter:":
        if source_kind == "search":
            return f"These results look directly related to {anchor}."
        return f"This page appears relevant to the thread around {anchor}."
    if label == "What it seems to suggest:":
        if excerpt:
            return excerpt
        return f"The source points toward a concrete angle on {subject}."
    if label == "Best next move:":
        if source_kind == "search":
            return "BROWSE the most promising URL or SEARCH a narrower angle."
        return "Continue with NEXT: READ_MORE if the page stays useful."
    return ""


def normalize_meaning_summary(
    raw: Optional[str],
    source_kind: str,
    anchor: str,
    subject: str,
    raw_excerpt: str,
) -> str:
    why = extract_label_value(raw, "Why it may matter:") or fallback_meaning_line(
        "Why it may matter:", source_kind, anchor, subject, raw_excerpt
    )
    suggest = extract_label_value(raw, "What it seems to suggest:") or fallback_meaning_line(
        "What it seems to suggest:", source_kind, anchor, subject, raw_excerpt
    )
    next_move = extract_label_value(raw, "Best next move:") or fallback_meaning_line(
        "Best next move:", source_kind, anchor, subject, raw_excerpt
    )
    return (
        f"Why it may matter: {why}\n"
        f"What it seems to suggest: {suggest}\n"
        f"Best next move: {next_move}"
    )


def fallback_meaning_summary(source_kind: str, anchor: str, subject: str, raw_excerpt: str) -> str:
    return normalize_meaning_summary(None, source_kind, anchor, subject, raw_excerpt)


def clean_gesture_label(raw: str) -> str:
    label = raw.strip()
    while len(label) >= 2 and (
        (label[0] == "[" and label[-1] == "]")
        or (label[0] == "(" and label[-1] == ")")
        or (label[0] == "{" and label[-1] == "}")
    ):
        label = label[1:-1].strip()
    label = label.strip().strip("\"'")
    return re.sub(r"\s+", " ", label).strip()


def parse_reconvergence_next_request(
    base: str,
    raw_arg: str,
) -> tuple[str | None, str | None, str | None]:
    """Return (label, compare_baseline, save_baseline) for read-only maps."""
    try:
        tokens = shlex.split(raw_arg)
    except ValueError:
        tokens = raw_arg.split()
    label_parts: list[str] = []
    compare_baseline: str | None = None
    save_baseline: str | None = None
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        normalized = token.strip().lower().replace("_", "-")
        if normalized in {"--compare-baseline", "compare-baseline", "compare"}:
            if idx + 1 < len(tokens):
                compare_baseline = clean_gesture_label(tokens[idx + 1])
                idx += 2
                continue
        if normalized in {"--save-baseline", "save-baseline", "save", "baseline"}:
            if idx + 1 < len(tokens):
                save_baseline = clean_gesture_label(tokens[idx + 1])
                idx += 2
                continue
        label_parts.append(token)
        idx += 1

    if base in {"COMPARE_BASELINE", "COMPARE_RECONVERGENCE", "BASELINE_COMPARE"}:
        if compare_baseline is None and label_parts:
            compare_baseline = clean_gesture_label(label_parts[0])
            label_parts = label_parts[1:]
        label = clean_gesture_label(" ".join(label_parts)) or (
            f"compare_{compare_baseline}" if compare_baseline else "compare_baseline"
        )
    else:
        label = clean_gesture_label(" ".join(label_parts))

    return label or None, compare_baseline or None, save_baseline or None


def parse_bridge_trace_next_request(base: str, raw_arg: str) -> tuple[str, str | None]:
    try:
        tokens = shlex.split(raw_arg)
    except ValueError:
        tokens = raw_arg.split()
    mode = "m6"
    label_parts: list[str] = []
    for token in tokens:
        normalized = token.strip().lower().replace("_", "")
        if normalized in {"m6", "mode6", "lane6"}:
            mode = "m6"
        else:
            label_parts.append(token)
    label = clean_gesture_label(" ".join(label_parts)) or clean_gesture_label(base.lower())
    return mode, label or None


def is_experiment_run_transcript_action(action: str) -> bool:
    parts = action.strip().split(None, 1)
    if not parts or parts[0].upper() not in {"EXPERIMENT_RUN", "EXP_RUN"}:
        return False
    arg = parts[1].strip() if len(parts) > 1 else ""
    if not arg:
        return False
    lowered = arg.lower()
    if lowered.startswith(("failed:", "success:", "error:", "stderr:", "stdout:", "output:")):
        return True
    if lowered.startswith(("timed out", "timeout:", "timed_out:")):
        return True
    first = arg.split(None, 1)[0]
    return first.endswith(":") and first.rstrip(":").upper() in {
        "FAILED",
        "SUCCESS",
        "ERROR",
        "STDERR",
        "STDOUT",
        "OUTPUT",
        "TIMEOUT",
        "TIMED_OUT",
    }


_LAST_NEXT_NORMALIZATION_SIGNAL_V1 = None
_LAST_NEXT_CHOICE_ENVELOPE_V1 = None


def _publish_parse_evidence() -> None:
    """Keep the historical runtime-module evidence attributes live."""
    runtime = sys.modules.get("minime_autonomy.runtime")
    if runtime is None:
        return
    runtime._LAST_NEXT_NORMALIZATION_SIGNAL_V1 = _LAST_NEXT_NORMALIZATION_SIGNAL_V1
    runtime._LAST_NEXT_CHOICE_ENVELOPE_V1 = _LAST_NEXT_CHOICE_ENVELOPE_V1


def _parse_result(action: Optional[str], cleaned: str) -> tuple:
    _publish_parse_evidence()
    return (action, cleaned)
STABLE_CORE_STAGE_NEXT_ALIASES = {
    "STABLE_CORE_SELF_JOURNAL",
    "STABLE_CORE_LOCAL_REFLECTIVE",
    "STABLE_CORE_ASTRID_CONTACT",
    "STABLE_CORE_READ_ONLY_RESEARCH",
    "STABLE_CORE_BOUNDED_ACTIONS",
    "STABLE_CORE_EXPERIMENTS",
}


def _action_verb(action: str) -> str:
    text = str(action or "").strip()
    if not text:
        return ""
    return text.split(None, 1)[0].strip("`*[](){}<>").rstrip(":").upper()


def _clean_alias_arg(raw: str) -> str:
    return (
        str(raw or "")
        .strip()
        .lstrip(":-—")
        .strip()
        .strip("[]\"'`“”")
        .strip()
    )


def _clean_shadow_decompose_focus(raw: str) -> str:
    focus = _clean_alias_arg(raw)
    normalized = re.sub(r"[.,;]", "", focus.casefold())
    normalized = " ".join(normalized.split())
    if not focus or normalized == "observer with memory":
        return "lambda-tail/lambda4"
    return focus


def _clean_weave_trace_focus(raw: str) -> str:
    focus = _clean_alias_arg(raw)
    normalized = re.sub(r"[.,;]", "", focus.casefold())
    normalized = " ".join(normalized.split())
    if not focus or normalized == "observer with memory":
        return "weave/lambda4"
    if normalized.startswith("weave/") or normalized.startswith("weave "):
        return focus
    return f"weave/{focus}"


def _extract_regime_name(raw: str) -> Optional[str]:
    lowered = str(raw or "").casefold()
    match = re.search(
        r"\bregime\s*(?:=|:|\s)\s*(explore|recover|breathe|focus|calm)\b",
        lowered,
    )
    if match:
        return match.group(1)
    for regime in REGULATORY_REGIMES:
        if re.search(rf"\b{re.escape(regime)}\b", lowered):
            return regime
    return None


# Sovereignty dials minime may set via a trailing reply FOOTER (`KEY=value` /
# `KEY: value`) — the structured format she sometimes writes instead of the
# strict JSON params block the sovereignty reflection consumes (~25734). The
# footer form had no listener, so a stated intent (e.g. `exploration_noise=0.12`)
# silently dropped — the same bug class as the scar near line 23315 ("dropped
# ~6 days of minime's REGIME breathe requests"). Direct footers now use the
# same tranche-safe outer ranges as self-regulation leases, preserving the
# requested value in a negotiation ledger when a request is clamped. Regime + PI
# gains are intentionally EXCLUDED: those stay gated to the 5-cycle sovereignty
# reflection (stability params), and the steward `stated_param_intent` guard-probe
# surfaces a dropped regime footer instead.
SELF_REGULATION_DIRECT_SAFE_RANGES = {
    "exploration_noise": (0.0, 0.08),
    "regulation_strength": (0.4, 1.0),
    "geom_curiosity": (0.0, 0.3),
}
_FOOTER_DIRECTIVE_BOUNDS = dict(SELF_REGULATION_DIRECT_SAFE_RANGES)


def _footer_bounds(key: str) -> tuple:
    """Constitution C3a: footer clamp bounds come from the envelope
    registry's per-field `channel_ranges.footer` (intersected with the
    field's own envelope, so a channel can never reach past the envelope),
    with the compiled table as the fail-closed fallback. Today's registry
    records the compiled values verbatim, so behavior is byte-identical —
    but a future consent-backed grant (C6) widens her footer channel by
    editing the DOCUMENT, not this code. Clamp-with-negotiation-record
    semantics are unchanged: the ledger stays the ratchet's pressure signal.
    """
    try:
        from .envelope_registry import channel_range_for, envelope_for, load_registry

        registry = load_registry()
        if registry is not None:
            channel = channel_range_for(key, "footer", registry)
            if channel is not None:
                envelope = envelope_for(key, registry)
                if envelope is not None:
                    lo = max(channel[0], envelope[0])
                    hi = min(channel[1], envelope[1])
                    if lo <= hi:
                        return (lo, hi)
                return channel
    except Exception:  # noqa: BLE001 - any registry fault falls closed
        pass
    return _FOOTER_DIRECTIVE_BOUNDS[key]
# Whole-line anchored: optional leading bullet/whitespace, KEY, ':' or '=', a
# numeric value, optional trailing punctuation — and NOTHING ELSE on the line.
# That bare `KEY=value` isolation is exactly what separates an intentional footer
# directive from a prose mention ("I worry about exploration_noise" / "setting
# exploration_noise to 0.12 would help"), neither of which is a bare KEY=value line.
_FOOTER_DIRECTIVE_RE = re.compile(
    r"^[\s\-*>]*(" + "|".join(_FOOTER_DIRECTIVE_BOUNDS) + r")\s*[:=]\s*"
    r"([-+]?\d*\.?\d+)\s*[.;,]?\s*$",
    re.IGNORECASE,
)
_FOOTER_SCAN_TRAILING_LINES = 8  # a footer lives at the tail of the reply


def _parse_footer_directives(text: str) -> dict:
    """Parse a trailing structured footer of sovereignty dials from a reply.

    Scans only the last `_FOOTER_SCAN_TRAILING_LINES` lines for ISOLATED
    `KEY: value` / `KEY=value` lines (whole-line anchored) where KEY is a known
    sovereignty dial, validating + clamping each to its JSON-arm bounds. Returns
    `{key: clamped_value}` (last occurrence wins) or `{}` if none. A prose mention
    never matches (it is not a bare KEY=value line). Pure function — see
    `_apply_footer_directives` for the application + logging.
    """
    return {
        key: spec["applied_value"]
        for key, spec in _parse_footer_directive_requests(text).items()
    }


def _parse_footer_directive_requests(text: str) -> dict:
    """Parse footer dial requests while retaining requested-vs-applied values."""
    if not text:
        return {}
    tail = str(text).splitlines()[-_FOOTER_SCAN_TRAILING_LINES:]
    out: dict = {}
    for ln in tail:
        m = _FOOTER_DIRECTIVE_RE.match(ln)
        if not m:
            continue
        key = m.group(1).lower()
        try:
            requested = float(m.group(2))
        except (TypeError, ValueError):
            continue
        lo, hi = _footer_bounds(key)
        # Compare in the wire's f32 domain (bounds from the envelope registry
        # are f32-quantized): an exact-at-f32 request like 0.08 must still
        # read as within_safe_range, not spuriously clamped (the 2026-09-01
        # receipt-substitution scar, generalized to the footer ledger).
        requested_f32 = struct.unpack("<f", struct.pack("<f", requested))[0]
        applied = max(lo, min(hi, requested_f32))
        out[key] = {
            "candidate_control": key,
            "requested_value": round(requested, 4),
            "applied_value": round(applied, 4),
            "safe_cap_or_range": {"min": round(lo, 6), "max": round(hi, 6)},
            "clamp_or_defer_reason": (
                "clamped_to_lease_safe_range"
                if applied != requested
                else "within_safe_range"
            ),
        }
    return out


def _normalize_observed_gemma4_next_alias(raw_action: str) -> Optional[str]:
    """Narrow repairs for Gemma 4 canary-observed action inventions."""
    raw = str(raw_action or "").strip()
    if not raw:
        return None

    raw_verb = _action_verb(raw)
    lowered = raw.casefold()

    if raw_verb == "RESEARCH_BUDGET_STATUS":
        arg = _clean_alias_arg(raw[len("RESEARCH_BUDGET_STATUS"):])
        return (
            f"EXPERIMENT_RESEARCH_BUDGET_STATUS {arg}"
            if arg
            else "EXPERIMENT_RESEARCH_BUDGET_STATUS latest"
        )

    if raw_verb in STABLE_CORE_STAGE_NEXT_ALIASES:
        if raw_verb == "STABLE_CORE_EXPERIMENTS":
            return "ACTION_PREFLIGHT EXPERIMENT"
        return "ACTION_PREFLIGHT NOTICE"

    control_assignment = (
        raw_verb in {"KEEP_FLOOR", "SEEK_BALANCE"}
        or lowered.startswith("keep_floor")
        or "keep_floor" in lowered
        or "exploration_noise" in lowered
    )
    if control_assignment:
        regime = _extract_regime_name(raw)
        if regime:
            return f"ACTION_PREFLIGHT REGIME {regime}"
        label = "balance" if raw_verb == "SEEK_BALANCE" else "keep_floor"
        return f"ACTION_PREFLIGHT REGULATOR_AUDIT {label}"

    return None


def build_normalization_signal_v1(raw_action: str, normalized_action: str) -> Optional[Dict[str, Any]]:
    raw_verb = _action_verb(raw_action)
    normalized_verb = _action_verb(normalized_action)
    if raw_verb.startswith("EXEXPERIMENT_"):
        target = "EXPERIMENT_" + raw_verb[len("EXEXPERIMENT_"):]
        reason = "double-ex experiment typo normalized to experiment workbench verb"
        native_signal = "experiment typo still signals return-path intent"
    elif raw_verb == "EXPERIENCE_PLAN":
        target = "EXPERIMENT_PLAN"
        reason = "experience-plan near typo normalized to experiment planning"
        native_signal = "experience wording signals an experiment-plan return attempt"
    elif raw_verb in {"SHADOW_TRACE", "SHADOW_EXPLORER", "SHADOW_DECOMPOSE", "WEAVE_TRACE"}:
        target = "SHADOW_PREFLIGHT"
        reason = "shadow diagnostic alias normalized to read-only preflight route"
        native_signal = "shadow/weave wording signals observational/rehearsal inquiry"
    elif raw_verb == "UNSHAPED_BASELINE":
        target = "CONSTRAINT_AUDIT"
        reason = "unshaped-baseline alias normalized to read-only constraint counterfactual route"
        native_signal = "absence-of-structure wording signals counterfactual constraint inquiry"
    elif raw_verb == "RESEARCH_BUDGET_STATUS":
        target = "EXPERIMENT_RESEARCH_BUDGET_STATUS"
        reason = "research-budget shorthand normalized to the existing experiment budget status route"
        native_signal = "research budget wording signals read-only budget inspection"
    elif raw_verb in STABLE_CORE_STAGE_NEXT_ALIASES:
        target = "ACTION_PREFLIGHT"
        reason = "stable-core stage label normalized to protected preflight instead of a dispatch verb"
        native_signal = "stage-label wording signals an intent to inspect currently available safe lanes"
    elif (
        raw_verb in {"KEEP_FLOOR", "SEEK_BALANCE"}
        or str(raw_action or "").casefold().strip().startswith("keep_floor")
    ):
        target = "ACTION_PREFLIGHT"
        reason = "control-style Gemma 4 action syntax normalized to protected preflight"
        native_signal = "parameter/control wording signals regulator posture inquiry"
    else:
        return None
    if normalized_verb not in {target, raw_verb}:
        return None
    return {
        "schema_version": 1,
        "raw_verb": raw_verb,
        "normalized_verb": target,
        "reason": reason,
        "native_signal": native_signal,
        "authority_change": False,
    }


def _split_choice_residue_suffix(action: str) -> Tuple[str, Optional[str]]:
    text = str(action or "").strip()
    upper = text.upper()
    marker = "(RESIDUE:"
    if text.endswith(")") and marker in upper:
        marker_idx = upper.rfind(marker)
        residue = text[marker_idx + len(marker):-1].strip()
        if residue:
            return text[:marker_idx].rstrip(), residue
    return text, None


def _strip_choice_next_prefix(value: str) -> str:
    text = str(value or "").strip()
    if text[:5].upper() == "NEXT:":
        return text[5:].strip()
    return text


def _choice_label_value(line: str, labels: Iterable[str]) -> Optional[str]:
    trimmed = str(line or "").strip().lstrip("-*>•").strip()
    lowered = trimmed.lower()
    for label in labels:
        label_lower = label.lower()
        if lowered.startswith(label_lower):
            return trimmed[len(label):].strip()
    return None


def _choice_metadata_lines(text: str) -> List[str]:
    lines: List[str] = []
    in_fence = False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return lines


def _compact_choice_text(value: str, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _normalize_choice_primary(value: str) -> str:
    action, _residue = _split_choice_residue_suffix(_strip_choice_next_prefix(value))
    action = _normalize_observed_gemma4_next_alias(action) or action
    parts = action.split(None, 1)
    if parts:
        parts[0] = parts[0].strip("`*")
        if parts[0].upper().startswith("EXEXPERIMENT_"):
            parts[0] = parts[0][2:]
        if parts[0].upper() == "EXPERIENCE_PLAN":
            parts[0] = "EXPERIMENT_PLAN"
        if parts[0].upper() == "SHADOW_DECOMPOSE":
            focus = _clean_shadow_decompose_focus(parts[1] if len(parts) > 1 else "")
            parts = ["SHADOW_PREFLIGHT", f"{focus} --stage=rehearse"]
        elif parts[0].upper() == "WEAVE_TRACE":
            focus = _clean_weave_trace_focus(parts[1] if len(parts) > 1 else "")
            parts = ["SHADOW_PREFLIGHT", f"{focus} --stage=rehearse"]
        elif parts[0].upper() == "UNSHAPED_BASELINE":
            parts[0] = "CONSTRAINT_AUDIT"
        elif parts[0].upper() in {"SHADOW_TRACE", "SHADOW_EXPLORER"}:
            parts[0] = "SHADOW_PREFLIGHT"
        action = " ".join(parts)
    return action.strip()


def build_choice_envelope_v1(
    text: str,
    *,
    raw_next: str,
    executable_next: str,
    residue: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    primary_next: Optional[str] = None
    alternate_nexts: List[str] = []
    return_threads: List[str] = []
    residue_text = _compact_choice_text(residue) if residue else None
    why_this_path: Optional[str] = None
    defer_reason: Optional[str] = None

    for line in _choice_metadata_lines(text):
        if value := _choice_label_value(
            line,
            ("Primary NEXT:", "Primary path:", "Chosen NEXT:", "Chosen path:"),
        ):
            primary_next = _compact_choice_text(_strip_choice_next_prefix(value))
        elif value := _choice_label_value(
            line,
            (
                "Alternate NEXT:",
                "Alternative NEXT:",
                "Alternate path:",
                "Alternative path:",
            ),
        ):
            alternate_nexts.append(_compact_choice_text(_strip_choice_next_prefix(value)))
        elif value := _choice_label_value(
            line,
            ("Return thread:", "Return threads:", "Return to:"),
        ):
            return_threads.append(_compact_choice_text(value))
        elif value := _choice_label_value(
            line,
            ("Residue:", "Transition residue:", "Stickiness:"),
        ):
            residue_text = _compact_choice_text(value)
        elif value := _choice_label_value(
            line,
            ("Why this path:", "Why this NEXT:", "Why now:"),
        ):
            why_this_path = _compact_choice_text(value, 360)
        elif value := _choice_label_value(
            line,
            ("Defer reason:", "Deferred because:", "Deferring because:"),
        ):
            defer_reason = _compact_choice_text(value, 360)

    if not any([primary_next, alternate_nexts, return_threads, residue_text, why_this_path, defer_reason]):
        return None

    declared_primary = primary_next or executable_next
    mismatch_warning = None
    if _normalize_choice_primary(declared_primary) != str(executable_next or "").strip():
        mismatch_warning = (
            f"primary_next `{_compact_choice_text(declared_primary, 120)}` did not match "
            f"executable NEXT `{_compact_choice_text(executable_next, 120)}`; "
            "dispatch followed executable NEXT"
        )

    envelope: Dict[str, Any] = {
        "policy": "choice_envelope_v1",
        "schema_version": 1,
        "source": "minime_next_response",
        "authority": "diagnostic_context_not_command",
        "primary_next": declared_primary,
        "executable_next": executable_next,
        "raw_next": raw_next,
        "alternate_nexts": alternate_nexts,
        "return_threads": return_threads,
    }
    if residue_text:
        envelope["residue"] = residue_text
    if why_this_path:
        envelope["why_this_path"] = why_this_path
    if defer_reason:
        envelope["defer_reason"] = defer_reason
    if mismatch_warning:
        envelope["mismatch_warning"] = mismatch_warning
    return envelope


def parse_next_action(text: str) -> tuple:
    """Extract NEXT: action from LLM response.

    Returns (action, cleaned_text) where cleaned_text has the NEXT: line removed.
    Returns (None, original_text) if no NEXT: found.
    Strips model-specific tokens (e.g. gemma3's <end_of_turn>) and recurring
    LLM artifacts (markdown decorations on the action token, the EXEXPERIMENT_
    typo). See `project_unwired_actions_catalog.md` for the diagnostics that
    motivated each strip.
    """
    global _LAST_NEXT_NORMALIZATION_SIGNAL_V1, _LAST_NEXT_CHOICE_ENVELOPE_V1
    _LAST_NEXT_NORMALIZATION_SIGNAL_V1 = None
    _LAST_NEXT_CHOICE_ENVELOPE_V1 = None
    lines = text.split('\n')
    in_fence = False
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.upper().startswith('NEXT:'):
            action = stripped[5:].strip()
            # Strip model end-of-turn tokens that leak into the action.
            action = action.replace('<end_of_turn>', '').replace('</s>', '').strip()
            raw_action_with_metadata = action
            action, residue = _split_choice_residue_suffix(action)
            raw_action = action
            action = _normalize_observed_gemma4_next_alias(action) or action
            # Kink follow-up (2026-05-14, post-Tranche-5): strip markdown
            # decorations from the FIRST whitespace-separated token (the
            # action verb). Recurring LLM artifact: `**READ_MORE**`,
            # `**EXAMINE** lambda4`, `` `RELEASE_SHADOW lambda/lambda8` ``,
            # etc. land in NEXT lines because the model emits markdown
            # bold/code formatting around action names. We strip these
            # only from the action verb, not from arguments (which may
            # legitimately contain backticks in code-shaped labels).
            parts = action.split(None, 1)
            if parts:
                parts[0] = parts[0].strip('`*')
                # Kink follow-up (2026-05-14): the recurring `EXEXPERIMENT_*`
                # typo (3+ occurrences today) is an LLM glitch where the
                # model double-emits the `EX` prefix. Fuzzy-strip when the
                # remainder starts with `EXPERIMENT_`.
                if parts[0].upper().startswith('EXEXPERIMENT_'):
                    parts[0] = parts[0][2:]
                if parts[0].upper() == 'EXPERIENCE_PLAN':
                    parts[0] = 'EXPERIMENT_PLAN'
                if parts[0].upper() == 'SHADOW_DECOMPOSE':
                    focus = _clean_shadow_decompose_focus(parts[1] if len(parts) > 1 else "")
                    parts = ['SHADOW_PREFLIGHT', f"{focus} --stage=rehearse"]
                elif parts[0].upper() == 'WEAVE_TRACE':
                    focus = _clean_weave_trace_focus(parts[1] if len(parts) > 1 else "")
                    parts = ['SHADOW_PREFLIGHT', f"{focus} --stage=rehearse"]
                elif parts[0].upper() == 'UNSHAPED_BASELINE':
                    parts[0] = 'CONSTRAINT_AUDIT'
                elif parts[0].upper() in {'SHADOW_TRACE', 'SHADOW_EXPLORER'}:
                    parts[0] = 'SHADOW_PREFLIGHT'
                action = ' '.join(parts)
            action, residue_after_normalization = _split_choice_residue_suffix(action)
            residue = residue or residue_after_normalization
            _LAST_NEXT_NORMALIZATION_SIGNAL_V1 = build_normalization_signal_v1(raw_action, action)
            _LAST_NEXT_CHOICE_ENVELOPE_V1 = build_choice_envelope_v1(
                text,
                raw_next=raw_action_with_metadata,
                executable_next=action,
                residue=residue,
            )
            cleaned = '\n'.join(lines[:i] + lines[i+1:]).strip()
            if is_experiment_run_transcript_action(action):
                return _parse_result(None, cleaned)
            return _parse_result(action, cleaned)
    in_fence = False
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            continue
        if stripped == "ATTRACTOR_SUGGESTIONS":
            cleaned = '\n'.join(lines[:i] + lines[i+1:]).strip()
            return _parse_result(stripped, cleaned)
        break
    return _parse_result(None, text)


# Paths. The implementation lives one directory below the stable root facade.

# The runtime compatibility assembly historically exposed these private helpers
# and constants. Keep that surface while ownership moves into this module.
__all__ = [
    name
    for name in tuple(globals())
    if not name.startswith("__")
    and name
    not in {
        "Any",
        "Dict",
        "Iterable",
        "List",
        "Optional",
        "Tuple",
        "REGULATORY_REGIMES",
        "re",
        "shlex",
        "sys",
    }
]
