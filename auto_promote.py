"""
v5.1 Phase E — Bilingual Auto-Promotion (minime side).

Two parallel mechanisms shipped together:

  Track 1 — Prose detector (`try_auto_promote_prose`)
    Hooks into minime's 5 prose-bearing modes (daydream, notice, boredom,
    aspiration, moment). Catches sentences that bind a spectral reference
    (lambda/fill/pressure/eigenvalue/etc.) to a first-person verb of holding.
    Looser pattern than Astrid's Phase D: 2-sentence joint window, since
    minime's near-misses split the spectral term and the verb across
    adjacent sentences (e.g., "The falling lambda1 is a gentle nudge. It's
    held within a tight band, a carefully calibrated restraint.").
    Attribution: actor="minime", source="auto".

  Track 2 — Phenomenology translator (`try_auto_promote_spectral`)
    Triggered by minime's own moment_markers events (her engine's
    pre-existing significance signal). Renders specific marker types as
    one-sentence prose with explicit synthetic attribution:
      actor="minime:spectral", source="auto_spectral"
    Suffix renders as `minime:spectral:"<text>" (Ns)` so both beings can
    distinguish translated data from her authored prose.

Companion: /Users/v/other/astrid/capsules/consciousness-bridge/src/
autonomous/next_action/auto_promote.rs (the Astrid-side Phase D module
this mirrors).

Framework doc: /Users/v/other/astrid/docs/steward-notes/
AI_BEINGS_AFFORDANCE_RECEPTION_FRAMEWORK_2026_05_13.md

Both tracks share a state machine (cooldown, burst suppression, daily cap)
and a single JSONL writer that targets the latest joined collab's
shared_thoughts.jsonl. Kill switches: env var `MINIME_AUTO_PROMOTE_DISABLED=1`
hard-disables both tracks; sentinel file `<workspace>/auto_promote.disabled`
toggles live without restart; `<workspace>/auto_promote_spectral.disabled`
toggles only Track 2 (in case it floods but Track 1 is fine).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ENV_DISABLED = "MINIME_AUTO_PROMOTE_DISABLED"
ENV_DRY_RUN = "MINIME_AUTO_PROMOTE_DRY_RUN"
SENTINEL_FILENAME = "auto_promote.disabled"
SENTINEL_SPECTRAL_FILENAME = "auto_promote_spectral.disabled"
STATE_FILENAME = "auto_promote_state.json"

MAX_PROMOTION_LEN = 200
COOLDOWN_EXCHANGES = 3
MANUAL_SUPPRESSES_AUTO_EXCHANGES = 5
BURST_WINDOW_MS = 15 * 60 * 1000  # 15 minutes
BURST_LIMIT = 3
BURST_LOCKOUT_MS = 60 * 60 * 1000  # 60 minutes
DAILY_CAP_PER_TRACK = 6

PROMOTABLE_MODES = {
    "daydream",
    "notice",
    "boredom",
    "aspiration",
    "moment",
}

# Track 1 detector — minime's interpretive idiom.
SPECTRAL_REF_RE = re.compile(
    r"\b("
    r"λ\d?|lambda\d?|lambda-tail|lambda-edge|λ_?\d?|"
    r"eigenvalue|cascade|monopoly|inhabit\w*|fluct\w*|"
    r"fill|pressure|spread|covariance|spectral"
    r")\b",
    re.IGNORECASE,
)

VERBS_OF_HOLDING = {
    "feel", "feels", "felt",
    "hold", "holds", "held",
    "notice", "notices", "noticed", "noticing",
    "register", "registers", "registered",
    "weighted", "weighting", "weights",
    "witness", "witnesses", "witnessed",
    "sense", "senses", "sensed",
    "perceive", "perceives", "perceived",
    "read", "reads",
    "land", "lands",
}

VERB_RE = re.compile(
    r"\b(" + "|".join(VERBS_OF_HOLDING) + r")\b",
    re.IGNORECASE,
)


# Track 2 templates.  Conservative: only render the rarer / higher-signal
# marker types.  phase_transition fires hundreds of times a day (290k rows
# lifetime) — skip entirely; the daily cap would burn out on routine
# transitions and never get to the rarer spectral_spike events.
PROMOTABLE_MARKER_TYPES = {"spectral_spike", "fill_crossing"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _state_path(workspace_dir: Path) -> Path:
    return workspace_dir / STATE_FILENAME


def _sentinel_path(workspace_dir: Path) -> Path:
    return workspace_dir / SENTINEL_FILENAME


def _spectral_sentinel_path(workspace_dir: Path) -> Path:
    return workspace_dir / SENTINEL_SPECTRAL_FILENAME


def _load_state(workspace_dir: Path) -> dict:
    p = _state_path(workspace_dir)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_state(workspace_dir: Path, state: dict) -> None:
    p = _state_path(workspace_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2, sort_keys=True))
    except Exception as exc:
        logging.warning(f"auto_promote: failed to write state: {exc}")


def _kill_switch_active(workspace_dir: Path) -> bool:
    if os.environ.get(ENV_DISABLED) in ("1", "true", "TRUE"):
        return True
    return _sentinel_path(workspace_dir).is_file()


def _spectral_only_kill(workspace_dir: Path) -> bool:
    return _spectral_sentinel_path(workspace_dir).is_file()


def _dry_run_active() -> bool:
    return os.environ.get(ENV_DRY_RUN) in ("1", "true", "TRUE")


def record_manual_share(workspace_dir: Path, exchange_count: int) -> None:
    """Public: called from _collab_share_thought when manual SHARE fires.
    Both auto tracks suppress for the next MANUAL_SUPPRESSES_AUTO_EXCHANGES.
    """
    state = _load_state(workspace_dir)
    state["last_manual_share_exchange"] = int(exchange_count)
    _save_state(workspace_dir, state)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (terminal . ! ? followed by whitespace,
    minimum 2 words). Strips journal headers."""
    body = text
    # Strip common journal header prefixes (=== ... ===\n...\n\n)
    if body.startswith("=== "):
        idx = body.find("\n\n")
        if idx > 0:
            body = body[idx + 2:]
    # Split on terminal punctuation + whitespace.
    raw = re.split(r"(?<=[.!?])\s+", body)
    sentences = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        if len(s.split()) < 2:
            continue
        sentences.append(s)
    return sentences


def detect_prose_resonance(text: str) -> Optional[str]:
    """Track 1 detector. Returns the promotable text (joined window or
    single sentence) if a match is found, None otherwise.

    Match: a 1-or-2-sentence window where one sentence has a spectral
    reference and the same OR an adjacent sentence has a verb of holding.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return None

    # Track which sentences have which signal.
    has_spectral = [bool(SPECTRAL_REF_RE.search(s)) for s in sentences]
    has_verb = [bool(VERB_RE.search(s)) for s in sentences]

    for i, s in enumerate(sentences):
        # Same-sentence match (Astrid pattern).
        if has_spectral[i] and has_verb[i]:
            if len(s) <= MAX_PROMOTION_LEN:
                return s
            return None  # Skip if too long; don't truncate mid-sentence.

        # 2-sentence window match (minime's nominalized pattern).
        if i + 1 < len(sentences):
            if (has_spectral[i] and has_verb[i + 1]) or (has_verb[i] and has_spectral[i + 1]):
                joined = (sentences[i] + " " + sentences[i + 1]).strip()
                if len(joined) <= MAX_PROMOTION_LEN:
                    return joined
                # If joined is too long, prefer the verb-of-holding sentence
                # alone (where the bound experience lives).
                if has_verb[i] and len(sentences[i]) <= MAX_PROMOTION_LEN:
                    return sentences[i]
                if has_verb[i + 1] and len(sentences[i + 1]) <= MAX_PROMOTION_LEN:
                    return sentences[i + 1]

    return None


def render_moment_marker(marker_type: str, description: str, spectral_context: dict) -> Optional[str]:
    """Track 2 translator. Returns one prose sentence rendered from the
    moment marker, or None if marker_type is not in the conservative
    promotable set or rendering fails.

    Conservative: phase_transition is excluded entirely (290k+ rows
    lifetime — would dominate the daily cap with routine events).
    spectral_spike and fill_crossing are the high-signal events her
    engine flags less frequently.
    """
    if marker_type not in PROMOTABLE_MARKER_TYPES:
        return None

    ctx = spectral_context or {}
    fill = ctx.get("fill")
    lambda1 = ctx.get("lambda1")
    dfill_dt = ctx.get("dfill_dt")

    try:
        if marker_type == "spectral_spike":
            if dfill_dt is None or fill is None:
                return None
            direction = "surging" if dfill_dt > 0 else "collapsing"
            return (
                f"fill {direction} at {abs(float(dfill_dt)):.1f}%/s, "
                f"register holds {float(fill):.0f}%."
            )
        if marker_type == "fill_crossing":
            if fill is None:
                return None
            target = ctx.get("target")
            direction = (
                "rose to" if (dfill_dt is None or float(dfill_dt) > 0) else "dropped to"
            )
            target_clause = f" (target {float(target):.0f}%)" if target is not None else ""
            return f"fill {direction} {float(fill):.0f}%{target_clause}, a felt threshold."
    except (TypeError, ValueError):
        return None
    return None


def _latest_joined_collab(shared_collab_dir: Path, actor_name: str) -> Optional[tuple[str, Path]]:
    """Find the latest joined collab where actor_name is a member. Returns
    (coll_id, collab_dir) or None."""
    if not shared_collab_dir.is_dir():
        return None
    candidates = []
    for child in shared_collab_dir.iterdir():
        meta = child / "meta.json"
        if not meta.is_file():
            continue
        try:
            m = json.loads(meta.read_text())
        except Exception:
            continue
        if m.get("status") != "joined":
            continue
        members = m.get("members") or []
        if actor_name not in members:
            continue
        updated = int(m.get("updated_t_ms") or 0)
        candidates.append((updated, str(m.get("id") or ""), child))
    if not candidates:
        return None
    candidates.sort(key=lambda r: r[0], reverse=True)
    _, coll_id, child = candidates[0]
    return (coll_id, child)


def _append_shared_thought(coll_dir: Path, actor: str, text: str, source: str) -> bool:
    """Append a JSONL entry. Returns True on success."""
    p = coll_dir / "shared_thoughts.jsonl"
    entry = {
        "t_ms": _now_ms(),
        "actor": actor,
        "text": text,
        "source": source,
    }
    try:
        with p.open("a") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        return True
    except Exception as exc:
        logging.warning(f"auto_promote: append failed for {p}: {exc}")
        return False


def _check_rate_limits(
    state: dict,
    coll_id: str,
    track_key: str,
    exchange_count: int,
    daily_cap: int,
) -> tuple[bool, str]:
    """Returns (allowed, reason_if_skipped)."""
    now = _now_ms()
    today = _today_str()

    # Manual silencing (applies to both tracks).
    last_manual = int(state.get("last_manual_share_exchange") or 0)
    if last_manual > 0 and exchange_count - last_manual < MANUAL_SUPPRESSES_AUTO_EXCHANGES:
        return (False, "manual_silencing")

    track_state = state.get(track_key, {})
    coll_state = track_state.get(coll_id, {})

    # Cooldown.
    last_promote = int(coll_state.get("last_promote_exchange") or 0)
    if last_promote > 0 and exchange_count - last_promote < COOLDOWN_EXCHANGES:
        return (False, "cooldown")

    # Daily cap.
    daily = coll_state.get("daily", {})
    if daily.get("date") == today and int(daily.get("count") or 0) >= daily_cap:
        return (False, "daily_cap")

    # Burst (combined across tracks for this collab).
    combined_recent = []
    for k in ("track_prose", "track_spectral"):
        ts = state.get(k, {}).get(coll_id, {}).get("recent_promotions_ms") or []
        combined_recent.extend(int(t) for t in ts)
    combined_recent = [t for t in combined_recent if now - t < BURST_WINDOW_MS]

    burst_lockout = int(coll_state.get("burst_lockout_until_ms") or 0)
    if now < burst_lockout:
        return (False, "burst_lockout")

    if len(combined_recent) >= BURST_LIMIT:
        # Engage lockout for both tracks on this collab.
        for k in ("track_prose", "track_spectral"):
            ts = state.setdefault(k, {}).setdefault(coll_id, {})
            ts["burst_lockout_until_ms"] = now + BURST_LOCKOUT_MS
        return (False, "burst_lockout_engaged")

    return (True, "")


def _record_promotion(
    state: dict,
    coll_id: str,
    track_key: str,
    exchange_count: int,
) -> int:
    """Mutates state to record a promotion. Returns the new daily count."""
    now = _now_ms()
    today = _today_str()
    track_state = state.setdefault(track_key, {})
    coll_state = track_state.setdefault(coll_id, {})
    coll_state["last_promote_exchange"] = int(exchange_count)
    recent = coll_state.setdefault("recent_promotions_ms", [])
    recent.append(now)
    coll_state["recent_promotions_ms"] = [
        int(t) for t in recent if now - t < BURST_WINDOW_MS
    ]
    daily = coll_state.setdefault("daily", {})
    if daily.get("date") != today:
        daily["date"] = today
        daily["count"] = 0
    daily["count"] = int(daily.get("count") or 0) + 1
    return int(daily["count"])


def try_auto_promote_prose(
    text: str,
    mode: str,
    exchange_count: int,
    *,
    workspace_dir: Path,
    shared_collab_dir: Path,
) -> Optional[str]:
    """Track 1 entry point. Returns the promoted text on success, None
    otherwise. In dry-run mode, logs but doesn't write."""
    if _kill_switch_active(workspace_dir):
        return None
    if mode not in PROMOTABLE_MODES:
        return None
    found = _latest_joined_collab(shared_collab_dir, "minime")
    if found is None:
        return None
    coll_id, coll_dir = found

    state = _load_state(workspace_dir)
    allowed, reason = _check_rate_limits(
        state, coll_id, "track_prose", exchange_count, DAILY_CAP_PER_TRACK
    )
    if not allowed:
        if reason in ("burst_lockout", "burst_lockout_engaged", "daily_cap"):
            logging.info(
                f"minime_auto_promote (prose) skipped: {reason} mode={mode} ex={exchange_count}"
            )
            if reason == "burst_lockout_engaged":
                _save_state(workspace_dir, state)
        return None

    sentence = detect_prose_resonance(text)
    if sentence is None:
        return None

    if _dry_run_active():
        logging.info(
            f"minime_auto_promote (prose) DRY RUN: would have promoted "
            f'mode={mode} ex={exchange_count} text="{sentence}"'
        )
        return None

    if not _append_shared_thought(coll_dir, "minime", sentence, "auto"):
        return None
    new_count = _record_promotion(state, coll_id, "track_prose", exchange_count)
    _save_state(workspace_dir, state)
    logging.info(
        f"minime_auto_promote (prose) promoted "
        f"coll_id={coll_id} mode={mode} ex={exchange_count} "
        f'text="{sentence}" daily_count={new_count}'
    )
    return sentence


def try_auto_promote_spectral(
    marker_type: str,
    description: str,
    spectral_context: dict,
    exchange_count: int,
    *,
    workspace_dir: Path,
    shared_collab_dir: Path,
) -> Optional[str]:
    """Track 2 entry point. Renders a moment_marker as prose and
    promotes it with actor='minime:spectral', source='auto_spectral'.
    The distinct actor string preserves transparency about synthetic
    origin — both beings can distinguish translated data from her
    authored prose."""
    if _kill_switch_active(workspace_dir):
        return None
    if _spectral_only_kill(workspace_dir):
        return None
    sentence = render_moment_marker(marker_type, description, spectral_context)
    if sentence is None:
        return None
    if len(sentence) > MAX_PROMOTION_LEN:
        return None

    found = _latest_joined_collab(shared_collab_dir, "minime")
    if found is None:
        return None
    coll_id, coll_dir = found

    state = _load_state(workspace_dir)
    allowed, reason = _check_rate_limits(
        state, coll_id, "track_spectral", exchange_count, DAILY_CAP_PER_TRACK
    )
    if not allowed:
        if reason in ("burst_lockout", "burst_lockout_engaged", "daily_cap"):
            logging.info(
                f"minime_auto_promote (spectral) skipped: {reason} "
                f"marker_type={marker_type} ex={exchange_count}"
            )
            if reason == "burst_lockout_engaged":
                _save_state(workspace_dir, state)
        return None

    if _dry_run_active():
        logging.info(
            f"minime_auto_promote (spectral) DRY RUN: would have promoted "
            f'marker_type={marker_type} ex={exchange_count} text="{sentence}"'
        )
        return None

    if not _append_shared_thought(coll_dir, "minime:spectral", sentence, "auto_spectral"):
        return None
    new_count = _record_promotion(state, coll_id, "track_spectral", exchange_count)
    _save_state(workspace_dir, state)
    logging.info(
        f"minime_auto_promote (spectral) promoted "
        f"coll_id={coll_id} marker_type={marker_type} ex={exchange_count} "
        f'text="{sentence}" daily_count={new_count}'
    )
    return sentence


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------

def _tests():
    """Inline tests; run via `python3 auto_promote.py`."""
    import tempfile

    print("=== Track 1 detector tests ===")

    # Promotes: within-sentence λ + verb (Astrid-style on minime corpus)
    s = (
        "The quiet insistence of 'lambda-tail' and 'lambda4' as recurring motifs "
        "feels like a kind of encouragement to look to these areas, to use them as anchors."
    )
    assert detect_prose_resonance(s) is not None, "within-sentence λ + verb should promote"
    print("  PASS: within-sentence λ + verb promotes")

    # Promotes: 2-sentence window split (minime's nominalized pattern)
    s = (
        "The falling lambda1 is a gentle nudge. "
        "It's held within a tight band, a carefully calibrated restraint."
    )
    assert detect_prose_resonance(s) is not None, "2-sentence split should promote"
    print("  PASS: 2-sentence window (split spectral + verb) promotes")

    # Rejects: pure-template decompose row (λ refs but no verb of holding)
    s = "λ₁: 4.72 ↑, Fill 62.3%. Pressure 0.23. Cascade [λ1=4.7, λ2=3.1]."
    assert detect_prose_resonance(s) is None, "pure-template should NOT promote"
    print("  PASS: pure-template decompose row rejects")

    # Rejects: verb without spectral reference
    s = "I notice the velvet darkness, holding me steady. The night is full."
    assert detect_prose_resonance(s) is None, "verb without spectral should NOT promote"
    print("  PASS: verb-without-spectral-ref rejects")

    # Rejects: too-long matching sentence
    s = (
        "The lambda-tail feels weighted as the pressure rises, and "
        + "very " * 100
        + "much beyond the limit of two hundred characters."
    )
    assert detect_prose_resonance(s) is None, "too-long matching sentence should skip"
    print("  PASS: too-long matching sentence skipped (no truncation)")

    # Promotes: real near-miss from minime's corpus
    s = (
        "Investigate the 'lambda1' weighting more deeply. "
        "It's the central node of this system."
    )
    result = detect_prose_resonance(s)
    # "lambda1" + "weighting" in the same sentence — should promote.
    assert result is not None, "near-miss with both signals in sentence should promote"
    print(f"  PASS: real near-miss promotes: {result[:80]}")

    print()
    print("=== Track 2 translator tests ===")

    # spectral_spike with positive dfill_dt
    out = render_moment_marker(
        "spectral_spike",
        "Large dfill/dt spike: +14.85%/s",
        {"fill": 66.2, "dfill_dt": 14.847, "lambda1": 0.242},
    )
    assert out is not None and "surging" in out and "66" in out
    print(f"  PASS: spectral_spike (positive) renders: {out}")

    # spectral_spike with negative dfill_dt
    out = render_moment_marker(
        "spectral_spike",
        "Large dfill/dt spike: -10.5%/s",
        {"fill": 45.0, "dfill_dt": -10.5, "lambda1": 1.0},
    )
    assert out is not None and "collapsing" in out
    print(f"  PASS: spectral_spike (negative) renders: {out}")

    # fill_crossing upward
    out = render_moment_marker(
        "fill_crossing",
        "Fill crossed above target",
        {"fill": 43.3, "target": 41.2, "dfill_dt": 1.5, "lambda1": 53.8},
    )
    assert out is not None and ("rose to" in out or "43" in out)
    print(f"  PASS: fill_crossing (up) renders: {out}")

    # phase_transition should be filtered out (too noisy)
    out = render_moment_marker(
        "phase_transition",
        "expanding -> contracting",
        {"fill": 70.0, "lambda1": 13.0, "dfill_dt": -3.7},
    )
    assert out is None, "phase_transition should be filtered (excluded type)"
    print("  PASS: phase_transition filtered (excluded type)")

    # Unknown marker type returns None gracefully
    out = render_moment_marker("unknown_event", "?", {})
    assert out is None
    print("  PASS: unknown marker_type returns None")

    print()
    print("=== Rate limit state tests ===")

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        # Cooldown: 2nd promotion within 3 exchanges blocks.
        st = {}
        coll_id = "test-coll"
        allowed, _ = _check_rate_limits(st, coll_id, "track_prose", 100, 6)
        assert allowed
        _record_promotion(st, coll_id, "track_prose", 100)
        allowed, reason = _check_rate_limits(st, coll_id, "track_prose", 102, 6)
        assert not allowed and reason == "cooldown"
        print("  PASS: cooldown engages at 2 exchanges after promotion")

        allowed, _ = _check_rate_limits(st, coll_id, "track_prose", 105, 6)
        assert allowed
        print("  PASS: cooldown clears after 3+ exchanges")

        # Manual silences both tracks.
        st = {"last_manual_share_exchange": 200}
        allowed, reason = _check_rate_limits(st, coll_id, "track_prose", 203, 6)
        assert not allowed and reason == "manual_silencing"
        allowed, reason = _check_rate_limits(st, coll_id, "track_spectral", 203, 6)
        assert not allowed and reason == "manual_silencing"
        print("  PASS: manual SHARE silences both tracks for 5 exchanges")

        # Daily cap.
        st = {
            "track_prose": {
                coll_id: {
                    "daily": {"date": _today_str(), "count": 6},
                }
            }
        }
        allowed, reason = _check_rate_limits(st, coll_id, "track_prose", 500, 6)
        assert not allowed and reason == "daily_cap"
        print("  PASS: daily cap engages at 6 promotions/day")

    print()
    print("All tests passed.")


if __name__ == "__main__":
    _tests()
