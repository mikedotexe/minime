"""Reconstructed coverage, not a recreation of the unavailable October 20 test.

Synthetic histories only; production readers are compared with a full-read
oracle. Counts describe traversal, not runtime performance or understanding.
"""
import json

import pytest
import autonomous_agent as aa


def oracle(raw, limit, display):
    rows, seen = [], set()
    for line in reversed(raw.decode().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if display:
            identity = value.get("action_id") or ":".join(
                value.get(key, "") for key in ("started_at", "canonical_action", "effective_action"))
            if identity in seen:
                continue
            seen.add(identity)
        rows.append(value)
        if len(rows) == limit:
            break
    return rows[::-1]


@pytest.mark.parametrize("display", [False, True])
@pytest.mark.parametrize("shape", ["empty", "unique", "duplicate", "long_utf8"])
def test_actual_recent_readers_match_full_history_without_rewriting(tmp_path, monkeypatch, display, shape):
    store = aa.ActionContinuityStore(tmp_path / "workspace")
    thread = store.create_thread("Synthetic retained action history")
    path = store._thread_dir(thread["thread_id"]) / "events.jsonl"
    count = 0 if shape == "empty" else 1200
    lines = [json.dumps({"action_id": f"synthetic-{i // 3 if shape == 'duplicate' else i}",
                        "status": "completed", "summary": ("\u03bb" * 40000 if shape == "long_utf8" and i == 1198 else "synthetic")},
                       ensure_ascii=False) for i in range(count)]
    raw = ("\n".join(lines + (["malformed synthetic tail"] if count else [])) + ("\n" if count else "")).encode()
    path.write_bytes(raw)
    before = path.stat()
    real = aa.continuity_history.reverse_lines
    examined = []
    def observe(source):
        for line in real(source):
            examined.append(len(line))
            yield line
    monkeypatch.setattr(aa.continuity_history, "reverse_lines", observe)
    reader = store._recent_display_events if display else store._recent_events
    assert reader(thread["thread_id"], 200) == oracle(raw, 200, display)
    assert path.read_bytes() == raw
    after = path.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
    if count:
        assert len(examined) < count
    else:
        assert not examined


def test_missing_history_is_empty_without_creating_it(tmp_path):
    store = aa.ActionContinuityStore(tmp_path / "workspace")
    assert store._recent_events("missing", 200) == []
    assert store._recent_display_events("missing", 200) == []
    assert not (store.root / "missing" / "events.jsonl").exists()
