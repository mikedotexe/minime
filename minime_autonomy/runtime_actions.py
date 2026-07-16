"""Runtime-action parsing and safe local experiment preflight primitives."""

import os
import re
import shlex
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple


BASE_DIR = Path(__file__).resolve().parents[1]


def _python_experiment_failure_hint(stderr: str) -> str:
    if not stderr:
        return ""
    lower = stderr.lower()
    if "same first dimension" in lower or ("shape" in lower and "mismatch" in lower):
        return (
            "Matplotlib x/y length mismatch. Make the x-axis the same length as "
            "the measured series, for example `time = np.linspace(start, stop, "
            "len(lambda1_relative))`, or plot against `range(len(values))`. "
            "The Minime experiment helper auto-aligns simple plot/scatter/bar "
            "calls, but generated arrays can still need an explicit shared length."
        )
    if "syntaxerror" in lower:
        return "Python syntax error. Check indentation, unmatched quotes, and CODE_START/CODE_END extraction."
    if "modulenotfounderror" in lower:
        return (
            "Missing module. The experiment lane reliably supports numpy, matplotlib, and scipy. "
            "If a local helper should import, check that it lives under the Minime workspace or is "
            "reachable through the experiment PYTHONPATH."
        )
    if "nameerror" in lower:
        return "Undefined name. Check variable names and whether the value was computed before use."
    return ""


def _experiment_pythonpath() -> str:
    paths: List[str] = [str(BASE_DIR)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        paths.extend(p for p in existing.split(os.pathsep) if p)
    try:
        import site

        paths.extend(site.getsitepackages())
        user_site = site.getusersitepackages()
        if user_site:
            paths.append(user_site)
    except Exception:
        pass
    unique_paths = []
    seen = set()
    for path in paths:
        if path and path not in seen:
            unique_paths.append(path)
            seen.add(path)
    return os.pathsep.join(unique_paths)


def _safe_experiment_script_name(name: str | None) -> Optional[str]:
    if not name:
        return None
    candidate = Path(name.strip().strip('"').strip("'")).name
    if not candidate:
        return None
    candidate = re.sub(r"[^A-Za-z0-9_.-]", "_", candidate)
    if not candidate.endswith(".py"):
        candidate = f"{candidate}.py"
    return candidate


def _run_python_request_flag(token: str) -> Optional[str]:
    stripped = token.lstrip("-")
    if not stripped:
        return None
    head = re.split(r"[:=]", stripped, maxsplit=1)[0].rstrip(":").lower()
    if head in {"filename", "text", "prompt"}:
        return head
    return None


def _run_python_text_boundary_flag(token: str) -> Optional[str]:
    if any(char.isspace() for char in token):
        return None
    flag = _run_python_request_flag(token)
    if not flag:
        return None
    stripped = token.lstrip("-")
    if token.startswith("-") or "=" in stripped:
        return flag
    return None


def _consume_run_python_value(
    tokens: List[str],
    start: int,
    *,
    text_like: bool,
) -> tuple[Optional[str], int]:
    if start >= len(tokens):
        return None, start
    if not text_like:
        return tokens[start], start + 1
    values: List[str] = []
    index = start
    quote: Optional[str] = None
    escaped = False
    in_comment = False
    while index < len(tokens):
        token = tokens[index]
        if not quote and not in_comment and _run_python_text_boundary_flag(token):
            if not values:
                return None, index
            break
        values.append(token)
        for char in token:
            if in_comment:
                if char == "\n":
                    in_comment = False
                continue
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "#":
                in_comment = True
        index += 1
    if not values:
        return None, start
    return " ".join(values), index


def _extract_run_python_code_boundary(raw: str) -> tuple[Optional[str], str]:
    pattern = re.compile(
        r"(?:^|\s)-{0,2}(?:text|prompt)\b\s*(?:[:=]\s*)?CODE_START",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(raw))
    if not matches:
        return None, raw
    match = matches[-1]
    body_start = match.end()
    code_end = re.search(r"\bCODE_END\b", raw[body_start:], re.IGNORECASE)
    if code_end:
        body_end = body_start + code_end.start()
        remove_end = body_start + code_end.end()
    else:
        body_end = len(raw)
        remove_end = body_end
        for candidate in _run_python_flag_matches(raw[body_start:]):
            if _run_python_match_is_text_boundary(candidate):
                body_end = body_start + candidate[0]
                remove_end = body_end
                break
    body = raw[body_start:body_end].strip()
    replacement = " "
    remainder = f"{raw[:match.start()]}{replacement}{raw[remove_end:]}"
    return body, remainder


def _run_python_flag_matches(raw: str) -> List[Tuple[int, int, int, str, int, str]]:
    matches: List[Tuple[int, int, int, str, int, str]] = []
    index = 0
    quote: Optional[str] = None
    escaped = False
    in_comment = False
    flag_names = ("filename", "prompt", "text")
    while index < len(raw):
        char = raw[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "#":
            in_comment = True
            index += 1
            continue
        if index > 0 and not raw[index - 1].isspace():
            index += 1
            continue

        dash_count = 0
        cursor = index
        while cursor < len(raw) and raw[cursor] == "-":
            dash_count += 1
            cursor += 1
        lower_tail = raw[cursor:].lower()
        flag = next(
            (
                name
                for name in flag_names
                if lower_tail.startswith(name)
                and (
                    cursor + len(name) >= len(raw)
                    or not (raw[cursor + len(name)].isalnum() or raw[cursor + len(name)] == "_")
                )
            ),
            None,
        )
        if not flag:
            index += 1
            continue

        after_name = cursor + len(flag)
        after_spaces = after_name
        while after_spaces < len(raw) and raw[after_spaces].isspace():
            after_spaces += 1
        separator = ""
        value_start = after_name
        if after_spaces < len(raw) and raw[after_spaces] in {":", "="}:
            separator = raw[after_spaces]
            value_start = after_spaces + 1
        if dash_count == 0 and not separator:
            index += 1
            continue
        while value_start < len(raw) and raw[value_start].isspace():
            value_start += 1
        matches.append((index, value_start, value_start, flag, dash_count, separator))
        index = value_start
    return matches


def _run_python_match_is_text_boundary(match: Tuple[int, int, int, str, int, str]) -> bool:
    _, _, _, _, dash_count, separator = match
    return dash_count > 0 or separator == "="


def _run_python_value_from_raw(value: str, *, text_like: bool) -> Optional[str]:
    stripped = value.strip()
    if not stripped:
        return None
    if text_like and stripped[0] not in {"'", '"'}:
        return stripped
    try:
        parts = shlex.split(stripped)
    except ValueError:
        parts = []
    if parts:
        return parts[0] if not text_like else parts[0]
    if text_like and stripped[0] in {"'", '"'}:
        return stripped[1:]
    return stripped.split(maxsplit=1)[0] if not text_like else stripped


def _parse_run_python_flags(raw: str) -> tuple[Optional[str], Optional[str]]:
    boundary_text, raw = _extract_run_python_code_boundary(raw)
    filename = None
    text = boundary_text
    matches = _run_python_flag_matches(raw)
    match_index = 0
    while match_index < len(matches):
        match = matches[match_index]
        start, _, value_start, flag, _, _ = match
        text_like = flag in {"text", "prompt"}
        value_end = len(raw)
        next_match_index = len(matches)
        for candidate_index in range(match_index + 1, len(matches)):
            candidate = matches[candidate_index]
            if not text_like or _run_python_match_is_text_boundary(candidate):
                value_end = candidate[0]
                next_match_index = candidate_index
                break
        value = _run_python_value_from_raw(
            raw[value_start:value_end],
            text_like=text_like,
        )
        if flag == "filename":
            filename = value
        else:
            text = value
        match_index = max(next_match_index, match_index + 1)
    return filename, text


def _parse_run_python_request(arg: str | None) -> tuple[Optional[str], Optional[str]]:
    if not arg:
        return None, None
    raw = arg.strip()
    filename, text = _parse_run_python_flags(raw)
    if filename or text:
        return _safe_experiment_script_name(filename), text
    return _safe_experiment_script_name(raw), None


def _run_python_workspace_hint(arg: str | None) -> str:
    if not arg:
        return ""
    raw = arg.strip().strip('"').strip("'")
    match = re.search(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+\.py)\b", raw)
    if not match:
        return ""
    workspace, script = match.groups()
    return (
        "\nBecause your request looked like a workspace script path, use:\n"
        f"  NEXT: EXPERIMENT_RUN {workspace} python3 {script}\n"
        f"  NEXT: CODEX {workspace} \"diagnose or create the missing script\"\n"
    )


def _workspace_python_scripts(work_dir: Path) -> list[str]:
    try:
        scripts = [
            path.name
            for path in work_dir.iterdir()
            if path.is_file() and path.name.endswith(".py")
        ]
    except OSError:
        return []
    return sorted(scripts)


def _format_workspace_python_scripts(work_dir: Path) -> str:
    scripts = _workspace_python_scripts(work_dir)
    if not scripts:
        return "No top-level Python scripts are present in this workspace."
    shown = ", ".join(scripts[:12])
    suffix = f" (+{len(scripts) - 12} more)" if len(scripts) > 12 else ""
    return f"Available top-level Python scripts: {shown}{suffix}."


def _missing_experiment_loop_key(workspace: str, missing_script: str) -> str:
    if re.fullmatch(r"being_experiment_\d{8}_\d{6}\.py", missing_script):
        return f"{workspace}:being_experiment_timestamped"
    return f"{workspace}:{missing_script}"


def _experiment_run_preflight(work_dir: Path, cmd_str: str) -> tuple[list[str], str, str, Optional[str]]:
    try:
        cmd_parts = shlex.split(cmd_str)
    except ValueError:
        cmd_parts = cmd_str.split()
    if not cmd_parts:
        return [], cmd_str, "", None

    first = cmd_parts[0]
    if first.endswith(".py"):
        script_path = work_dir / first
        if script_path.is_file():
            normalized = ["python3", *cmd_parts]
            return (
                normalized,
                " ".join(normalized),
                "Normalized bare Python script to `python3 <script.py>`.",
                None,
            )
        return cmd_parts, cmd_str, "", Path(first).name

    if first in {"python", "python3"} and len(cmd_parts) >= 2 and cmd_parts[1].endswith(".py"):
        script_path = work_dir / cmd_parts[1]
        if not script_path.is_file():
            return cmd_parts, cmd_str, "", Path(cmd_parts[1]).name

    return cmd_parts, cmd_str, "", None


class RuntimeActions(Protocol):
    def _decide_action(self, state: Dict[str, float]) -> str: ...

    def _execute_action(self, action: str, state: Dict[str, float]) -> None: ...


def __getattr__(name: str):
    if name in {"AutonomousAgent", "main"}:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(name)


__all__ = ["AutonomousAgent", "RuntimeActions", "main"]
