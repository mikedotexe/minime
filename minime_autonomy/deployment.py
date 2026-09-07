"""Source identity for the Python agent; no runtime control or workspace writes."""

import hashlib
from pathlib import Path


def source_inputs(root: Path) -> dict[str, str]:
    paths = set(root.glob("*.py"))
    for package in ("minime_autonomy", "mikemind"):
        paths.update((root / package).rglob("*.py"))
    paths.update(root / name for name in (
        "scripts/launchd_autonomous_agent.sh",
        "scripts/minime_rescue_investigation.py",
        "launchd/com.minime.autonomous-agent.plist",
    ))
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths) if path.is_file()
    }
