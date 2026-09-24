"""Thin preference adapter. The shared Rust reader owns profile and draft mutations."""
import json
import logging
import re
from pathlib import Path

EXPRESSIVE_CLASSES = {"aspiration", "private_journal", "moment_capture", "private_writing"}
EXPRESSION_ROOM = (
    "Follow the thought as far as you wish; a page is as welcome as a line, and stopping is welcome too. "
    "WRITE PROFILE EXTENDED or SHORT changes your length ceiling for every journal route; "
    "WRITE HELP shows the limits. For voluntary private continuation, "
    "WRITE START <topic> begins a draft; WRITE CONTINUE develops the selected draft. "
    "No continuation is scheduled automatically."
)


def completion_metadata(parsed: dict) -> dict:
    """Bounded provider-reported stopping metadata, never response content."""
    choices = parsed.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    reason = parsed.get("done_reason", choice.get("finish_reason"))
    known = {"stop", "length", "eos", "eos_token", "max_tokens", "tool_calls", "content_filter", "load", "unload"}
    reason = reason if isinstance(reason, str) and reason in known else "other_reported" if isinstance(reason, str) else None
    usage = parsed.get("usage")
    count = parsed.get("eval_count", usage.get("completion_tokens") if isinstance(usage, dict) else None)
    return {
        "native_finish": reason,
        "native_done": parsed.get("done") if isinstance(parsed.get("done"), bool) else None,
        "provider_eval_count": count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None,
    }

WRITING_GUIDANCE = (
    "Private writing: NEXT: WRITE START <topic>, WRITE CONTINUE, WRITE REVISE <direction>, "
    'WRITE OBSERVE {"owner":"minime","draft":"dN","present":true,"operation":{"kind":"status"}} for optional private observations on an existing exact draft ID, '
    "WRITE BRANCH <direction>, WRITE RESUME dN, WRITE FINISH, WRITE PARK, or WRITE HELP. "
    "WRITE STOPPING_POINT <text> retains an optional stopping point as reference, never an executed command. "
    "To keep developing the active draft, choose NEXT: WRITE CONTINUE. "
    "WRITE PROFILE DEFAULT uses normal route limits: expressive writing and private drafts allow up to 8192 output tokens; other journal routes keep their own limits. "
    "WRITE PROFILE SHORT selects 512; WRITE PROFILE EXTENDED applies 8192 across journal-producing modes. "
    "These are ceilings, never required lengths. New drafts start without study notes. WRITE EVIDENCE <text> attaches or replaces references; bare WRITE EVIDENCE clears them. Existing drafts and branches retain their context; sharing is separate."
)


def is_private_request(action: str) -> bool:
    """Classify intended private writing before validating command grammar."""
    return bool(re.match(
        r"(?i)^\s*(?:NEXT:\s*)?(?:(?:SELF_STUDY|INVESTIGATE):?\s+)?(?:REPLACE:?\s+)*WRITE(?:\s|:|$)",
        str(action or ""),
    ))


def diagnostic_action(action: str) -> str:
    """Privacy classification only; never parse or change executable commands."""
    return "WRITE [private payload withheld]" if is_private_request(action) else action


def selected_profile(workspace: Path) -> str:
    path = workspace / "diagnostics/source_first_v3/shared_reader/writing/profile.json"
    try:
        value = json.loads(path.read_text())
        if value not in {"default", "short", "extended"}:
            raise ValueError("unsupported writing preference")
        return value
    except FileNotFoundError:
        return "default"
    except (OSError, ValueError) as error:
        logging.warning("Writing preference unreadable; preserving ordinary limits: %s", error)
        return "default"


def profile_budget(profile: str, ordinary: tuple[int, float, int]) -> tuple[int, float, int]:
    tokens, timeout, context = ordinary
    if profile == "extended":
        return 8192, max(timeout, 1200), max(context, 65536)
    if profile == "short":
        return 512, timeout, context
    return ordinary
