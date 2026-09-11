"""Thin preference adapter. The shared Rust reader owns profile and draft mutations."""
import json
import logging
import re
from pathlib import Path

WRITING_GUIDANCE = (
    "Private writing: NEXT: WRITE START <topic>, WRITE CONTINUE, WRITE REVISE <direction>, "
    "WRITE BRANCH <direction>, WRITE RESUME dN, WRITE FINISH, or WRITE HELP. "
    "WRITE PROFILE EXTENDED allows up to 8192 output tokens across journals; SHORT sets 512; "
    "DEFAULT restores ordinary preferences. No minimum length. New drafts start without study notes. WRITE EVIDENCE <text> attaches or replaces references; bare WRITE EVIDENCE clears them. Existing drafts and branches retain their context; sharing is separate."
)


def is_private_request(action: str) -> bool:
    """Classify intended private writing before validating command grammar."""
    return bool(re.match(
        r"(?i)^\s*(?:NEXT:\s*)?(?:(?:SELF_STUDY|INVESTIGATE):?\s+)?(?:REPLACE:?\s+)*WRITE(?:\s|:|$)",
        str(action or ""),
    ))


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
