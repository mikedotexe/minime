"""Thin host adapter for the shared Rust source reader; no catalog or paging policy."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any
from .source_study_diagnostics import StudyAttemptDiagnostics
from .writing import WRITING_GUIDANCE

# Kept within the existing prompt budget when ambient context is compacted.
SOURCE_STUDY_GUIDANCE = (
    "Local source reading: NEXT: SELF_STUDY MAP opens the shared system map. "
    "SELF_STUDY QUESTION manages your study inquiries; SELF_STUDY RELATE follows one exact symbol, SELF_STUDY SESSION reads chosen pages together, and SELF_STUDY TRACE LAST inspects retained delivery. "
    "Use SELF_STUDY FIND <literal text>, SELF_STUDY OPEN repository/path [one-based line], "
    "SELF_STUDY RESUME repository/path, or SELF_STUDY CONTINUE. Choose exact paths from the map/search; "
    "if a target is unknown, use SELF_STUDY MAP. Source INTROSPECT is the same budget-free reader "
    "(legacy offsets start at 0); preserved workspace artifacts keep their research policy. "
    "A recovery map is navigation, not delivery of the requested source. "
    "SELF_STUDY CONTINUE reads the next code page; READ_MORE is a separate saved-document reader. "
) + WRITING_GUIDANCE


def selected_reader(astrid_root: Path) -> Path:
    """Use the same immutable release as Astrid when staged deployment is active."""
    selection_path = astrid_root / ".runtime/bridge-deployment/active.json"
    if not selection_path.exists():
        return astrid_root / "target/release/astrid-source-study"
    def record(path: Path) -> tuple[dict[str, Any], bytes]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_048_576:
            raise RuntimeError("invalid shared reader release record")
        data = path.read_bytes()
        return json.loads(data), data
    selection, _ = record(selection_path)
    if selection.get("schema") != "bridge_release_selection_v1":
        raise RuntimeError("unsupported shared reader release selection")
    stage = Path(selection["stage"])
    if not stage.is_absolute() or stage.resolve() != stage:
        raise RuntimeError("shared reader release path is not canonical")
    manifest, raw = record(stage / "manifest.json")
    if hashlib.sha256(raw).hexdigest() != selection.get("manifest_sha256"):
        raise RuntimeError("shared reader release manifest changed")
    artifact = manifest.get("artifacts", {}).get("source-study-reader")
    if not artifact:
        raise RuntimeError("selected Astrid release has no shared source reader; deploy source-study parity first")
    executable = stage / "helpers/astrid-source-study"
    if (artifact.get("path") != str(executable) or executable.resolve() != executable
            or executable.is_symlink() or not executable.is_file()):
        raise RuntimeError("shared reader release executable path mismatch")
    with executable.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != artifact.get("sha256"):
        raise RuntimeError("shared reader release executable changed")
    return executable


class StudyClient:
    def __init__(self, minime_root: Path, workspace: Path, *, astrid_root: Path | None = None,
                 executable: Path | None = None):
        self.astrid_root = astrid_root or Path(os.environ.get("ASTRID_SOURCE_ROOT", str(minime_root.parent / "astrid")))
        self.minime_root = minime_root
        self.workspace = workspace
        override = os.environ.get("ASTRID_SOURCE_STUDY_BIN")
        self.executable = executable or (Path(override) if override else selected_reader(self.astrid_root))

    def call(self, **operation: Any) -> dict[str, Any]:
        if not self.executable.is_file():
            raise RuntimeError("shared source reader is unavailable; build Astrid's astrid-source-study executable before enabling source study")
        request = {"astrid_root": str(self.astrid_root), "minime_root": str(self.minime_root),
                   "state_directory": str(self.workspace / "diagnostics/source_first_v3/shared_reader"),
                   "runtime_workspace": str(self.workspace), "being": "minime", **operation}
        result = subprocess.run([str(self.executable)], input=json.dumps(request), text=True,
                                capture_output=True, timeout=45, check=False)
        try:
            value = json.loads(result.stdout)
        except (ValueError, TypeError) as error:
            raise RuntimeError("shared source reader returned an invalid response") from error
        if value is None and operation.get("operation") == "recover_navigation" and not result.returncode:
            return {}
        if not isinstance(value, dict):
            raise RuntimeError("shared source reader returned an invalid response")
        if result.returncode or "error" in value:
            raise RuntimeError(value.get("error", "shared source reader failed"))
        return value

    def recover_navigation(self, action: str) -> dict[str, Any] | None:
        """Stateless guidance only: never prepare input or alter reader state."""
        return self.call(operation="recover_navigation", action=action) or None

    def prepare(self, action: str) -> SourceStudyPrompt:
        return SourceStudyPrompt(self, self.call(operation="prepare", action=action))


class SourceStudyPrompt(str):
    """One immutable page survives provider adaptation and fallback as one unit."""
    def __new__(cls, client: StudyClient, output: dict[str, Any]):
        value = super().__new__(cls, output["text"])
        value.client = client
        value.output = output
        value.receipt = None
        value._wire = None
        value._diagnostics = None
        return value

    @property
    def input_budget_bytes(self) -> int:
        return int(self.output.get("input_budget_bytes", 16000))

    @property
    def context_tokens(self) -> int:
        return int(self.output.get("context_tokens", 10240))

    def messages(self, system: str, budget: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
        if len((system + self).encode("utf-8")) > budget:
            raise ValueError("complete source page does not fit this provider lane; bookmark unchanged")
        return [{"role": "system", "content": system}, {"role": "user", "content": str(self)}], {
            "adapted_prompt_chars": len(self), "adapted_system_chars": len(system),
            "prompt_template_mode": "source_study_intact", "prompt_compacted": False,
            "prompt_compaction": {"applied": False, "parts": [], "budget_chars": budget},
            "protected_inbox_chars": 0,
        }

    def post(self, post, url: str, payload: dict[str, Any], timeout: float):
        # These are the actual bytes sent, rather than a reconstructed approximation.
        request_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if not any(m.get("role") == "user" and str(self) in m.get("content", "")
                   for m in payload.get("messages", [])):
            raise ValueError("source page was shortened before submission; bookmark unchanged")
        self._wire = None
        self._diagnostics = StudyAttemptDiagnostics(self.client.workspace, self.output, request_json)
        try:
            response = post(url, data=request_json.encode("utf-8"),
                            headers={"Content-Type": "application/json"}, timeout=timeout)
        except Exception as error:
            self._diagnostics.fail("transport_error", error)
            raise
        self._diagnostics.response(response)
        if response.status_code == 200:
            self._wire = (request_json, response.text)
        return response

    @property
    def diagnostic_summary(self) -> dict:
        return dict(self._diagnostics.summary) if self._diagnostics else {}

    def clean_content(self, cleaner, content):
        try:
            cleaned = cleaner(content)
        except Exception as error:
            if self._diagnostics:
                self._diagnostics.fail("cleanup_error", error)
            raise
        if self._diagnostics:
            self._diagnostics.cleaned(cleaned)
        return cleaned

    def accepted(self):
        """Called by dispatch after a nonempty visible completion survives cleanup."""
        if self._wire is None:
            raise RuntimeError("source delivery has no retained provider wire bodies")
        request_json, response_json = self._wire
        page = self.output.get("page")
        try:
            if page:
                self.receipt = self.client.call(operation="delivered", page_id=page["id"],
                                               request_json=request_json, response_json=response_json)
            else:
                self.receipt = self.client.call(operation="navigation_delivered",
                                               navigation_id=self.output["navigation_id"],
                                               request_json=request_json, response_json=response_json)
        except Exception as error:
            if self._diagnostics:
                self._diagnostics.fail("delivery_rejected", error)
            raise
