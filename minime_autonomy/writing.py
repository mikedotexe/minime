"""Thin preference adapter. The shared Rust reader owns profile and draft mutations."""
import json
import logging
import re
from pathlib import Path

EXPRESSIVE_CLASSES = {"aspiration", "private_journal", "moment_capture", "private_writing"}
EXPRESSION_ROOM = (
    "Up to 8192 output tokens are available. There is room here for a sustained piece, "
    "several times longer than a usual entry. You may follow a thought through examples, "
    "complications and changes of direction without compressing it into a conclusion. "
    "Brief writing or stopping is equally available. For voluntary private continuation, "
    "WRITE START <topic> begins a draft; WRITE CONTINUE develops the selected draft, "
    "and WRITE HELP shows the choices. No continuation is scheduled automatically."
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
    "WRITE PROFILE EXTENDED allows up to 8192 output tokens across journals; SHORT sets 512; "
    "DEFAULT restores ordinary preferences. No minimum length. New drafts start without study notes. WRITE EVIDENCE <text> attaches or replaces references; bare WRITE EVIDENCE clears them. Existing drafts and branches retain their context; sharing is separate."
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
