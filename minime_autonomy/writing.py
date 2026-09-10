"""Thin preference adapter. The shared Rust reader owns profile and draft mutations."""
import json
import logging
from pathlib import Path

WRITING_GUIDANCE = (
    "Private writing: NEXT: WRITE START <topic>, WRITE CONTINUE, WRITE REVISE <direction>, "
    "WRITE BRANCH <direction>, WRITE RESUME dN, WRITE FINISH, or WRITE HELP. "
    "WRITE PROFILE EXTENDED allows up to 8192 output tokens across journals; SHORT sets 512; "
    "DEFAULT restores ordinary preferences. No minimum length. Drafts and references persist; sharing is separate."
)


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
