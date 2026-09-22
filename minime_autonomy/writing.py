"""Thin preference adapter. The shared Rust reader owns profile and draft mutations."""
import json
import logging
import re
from pathlib import Path

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
