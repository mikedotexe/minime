"""History parity and cache invalidation with synthetic files only."""
import json
import os
from pathlib import Path

import pytest

import autonomous_agent as aa
from minime_autonomy import continuity_history as history


@pytest.mark.parametrize("text", [
    "", "\n", "\n\n", "a", "a\n", "a\n\nb\n", "\na\nb",
    "a\rb\r", "a\r\nb\r\n", "a\r\r\nb\r",
    "a\v\n\fb\x1c\x1d\x1e\x85\u2028\u2029\nc",
    "α\n🙂middle𐀀\r\nlast", "prefix\n" + "🙂" * 1000 + "\nlast",
])
@pytest.mark.parametrize("block_size", [1, 7, 64 * 1024])
def test_reverse_lines_matches_legacy_splitlines(tmp_path, monkeypatch, text, block_size):
    path = tmp_path / "history.jsonl"
    path.write_text(text, encoding="utf-8", newline="")
    monkeypatch.setattr(history, "READ_BLOCK_BYTES", block_size)
    assert list(history.reverse_lines(path)) == list(reversed(path.read_text().splitlines()))


def test_recent_read_work_depends_on_requested_tail_not_history_size(tmp_path, monkeypatch):
    original_open = Path.open
    counts = []

    class CountingFile:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            self.handle.__enter__()
            return self
        def __exit__(self, *args):
            return self.handle.__exit__(*args)
        def seek(self, *args):
            return self.handle.seek(*args)
        def read(self, *args):
            data = self.handle.read(*args)
            counts[-1] += len(data)
            return data

    for n in (100, 10_000):
        path = tmp_path / f"history_{n}.jsonl"
        path.write_text((json.dumps({"old": "x" * 1000}) + "\n") * n + '{"tail":true}\n')
        counts.append(0)
        with monkeypatch.context() as patcher:
            patcher.setattr(Path, "open", lambda self, *args, **kw: CountingFile(original_open(self, *args, **kw)))
            lines = history.reverse_lines(path)
            assert next(lines) == '{"tail":true}'
            lines.close()
    assert counts == [history.READ_BLOCK_BYTES, history.READ_BLOCK_BYTES]


@pytest.mark.parametrize("limit", [0, 1, 3, 20])
def test_recent_event_readers_preserve_filtering_order_and_duplicates(tmp_path, limit):
    store = aa.ActionContinuityStore(tmp_path)
    path = store._thread_dir("fixture") / "events.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {"action_id": "old", "status": "pending"},
        {"action_id": "same", "status": "pending"},
        {"started_at": "one", "canonical_action": "NOTICE"},
        {"action_id": "same", "status": "handled"},
        {"action_id": "last", "status": "handled"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows[:2]) + "\nmalformed\n\n" +
                    "\n".join(json.dumps(row) for row in rows[2:]))
    expected = []
    unique = []
    seen = set()
    for row in reversed(rows):
        if len(expected) < max(1, limit):
            expected.append(row)
        key = row.get("action_id") or f"{row.get('started_at', '')}:{row.get('canonical_action', '')}:{row.get('effective_action', '')}"
        if key not in seen and len(unique) < max(1, limit):
            unique.append(row)
            seen.add(key)
    assert store._recent_events("fixture", limit) == list(reversed(expected))
    assert store._recent_display_events("fixture", limit) == list(reversed(unique))


def test_complete_action_catalog_keeps_old_ids_and_reuses_unchanged_files(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.write_text('\n'.join(json.dumps({"action_id": f"old_{i}"}) for i in range(2000)) +
                    '\nmalformed\n[1,2]\n{"action_id":0}\n{"action_id":""}\n')
    original = Path.open
    reads = []
    def opening(self, *args, **kwargs):
        if self == path:
            reads.append(self)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opening)
    expected = frozenset(f"old_{i}" for i in range(2000))
    assert history.action_ids(path) == expected
    assert history.action_ids(path) == expected
    assert len(reads) == 1


@pytest.mark.parametrize("change", ["append", "truncate", "replace", "same_mtime_rewrite", "delete"])
def test_action_catalog_invalidates_for_every_source_change(tmp_path, change):
    path = tmp_path / "events.jsonl"
    path.write_text('{"action_id":"old"}\n')
    assert history.action_ids(path) == {"old"}
    before = path.stat()
    if change == "append":
        with path.open("a") as handle:
            handle.write('{"action_id":"new"}\n')
        expected = {"old", "new"}
    elif change == "truncate":
        path.write_text("")
        expected = set()
    elif change == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_text('{"action_id":"new"}\n')
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, path)
        expected = {"new"}
    elif change == "same_mtime_rewrite":
        path.write_text('{"action_id":"new"}\n')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        expected = {"new"}
    else:
        path.unlink()
        expected = set()
    assert history.action_ids(path) == expected


def test_oversized_catalog_is_complete_but_not_retained(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.write_text('{"action_id":"one"}\n{"action_id":"two"}\n')
    monkeypatch.setattr(history, "MAX_CACHED_ACTION_IDS", 1)
    assert history.action_ids(path) == {"one", "two"}
    assert path not in history._action_ids_cache
    monkeypatch.setattr(history, "MAX_CACHED_ACTION_IDS", 100)
    monkeypatch.setattr(history, "MAX_CACHED_ID_CHARACTERS", 1)
    assert history.action_ids(path) == {"one", "two"}
    assert path not in history._action_ids_cache


def test_changed_during_read_catalog_is_not_cached(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.write_text('{"action_id":"old"}\n')
    original = history._signature
    calls = [0]
    def signature(candidate):
        calls[0] += 1
        if calls[0] == 2:
            with path.open("a") as handle:
                handle.write('{"action_id":"new"}\n')
        return original(candidate)
    monkeypatch.setattr(history, "_signature", signature)
    assert history.action_ids(path) == {"old"}
    assert path not in history._action_ids_cache
    assert history.action_ids(path) == {"old", "new"}


def test_source_fingerprint_detects_same_size_same_mtime_replacement(tmp_path):
    store = aa.ActionContinuityStore(tmp_path)
    path = store._thread_dir("fixture") / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"action_id":"old"}\n')
    prior_stat = path.stat()
    before = store._projection_source_fingerprints_v1("fixture")
    replacement = tmp_path / "replacement"
    replacement.write_text('{"action_id":"new"}\n')
    os.utime(replacement, ns=(prior_stat.st_atime_ns, prior_stat.st_mtime_ns))
    os.replace(replacement, path)
    after = store._projection_source_fingerprints_v1("fixture")
    assert before["events.jsonl"]["mtime_ns"] == after["events.jsonl"]["mtime_ns"]
    assert before["events.jsonl"]["size"] == after["events.jsonl"]["size"]
    assert before != after
    thread = {"thread_id": "fixture", "projection_freshness_v1": {
        "schema_version": store.projection_schema_version, "source_fingerprints": before}}
    assert store._projection_freshness_is_stale_v1(thread)
