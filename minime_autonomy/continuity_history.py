"""Read existing continuity history without repeatedly loading its full text.

Recent readers traverse the same history backwards until their caller has enough
records. The complete action-ID catalog is reused only while filesystem identity
and change metadata are unchanged; no history is removed or age-limited.
"""
from collections import OrderedDict
import json
from pathlib import Path
import threading


READ_BLOCK_BYTES = 64 * 1024
MAX_CACHED_FILES = 16
MAX_CACHED_ACTION_IDS = 100_000
MAX_CACHED_ID_CHARACTERS = 2_000_000
_action_ids_cache = OrderedDict()
_cache_lock = threading.RLock()


def reverse_lines(path: Path):
    """Yield the equivalent of reversed(read_text().splitlines()), lazily.

    JSONL writers use LF separators. Decode only complete LF-delimited segments
    so UTF-8 characters can cross read-block boundaries. splitlines still handles
    CRLF, CR and Unicode separators inside each segment with its original rules.
    A single unusually long line may require more than one block in memory.
    """
    with Path(path).open("rb") as handle:
        position = handle.seek(0, 2)
        pending = []
        final_segment = True
        while position:
            start = max(0, position - READ_BLOCK_BYTES)
            handle.seek(start)
            pieces = handle.read(position - start).split(b"\n")
            if len(pieces) == 1:
                pending.append(pieces[0])
            else:
                pieces[-1] += b"".join(reversed(pending))
                for piece in reversed(pieces[1:]):
                    text = (piece if final_segment else piece + b"\n").decode("utf-8")
                    yield from reversed(text.splitlines())
                    final_segment = False
                pending = [pieces[0]]
            position = start
        prefix = b"".join(reversed(pending))
        text = (prefix if final_segment else prefix + b"\n").decode("utf-8")
        yield from reversed(text.splitlines())


def _signature(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_ctime_ns, stat.st_mtime_ns, stat.st_size)


def action_ids(path: Path):
    """Return every dict record's nonempty string action_id, including old rows.

    This cache stores identifiers only. Oversized sets are returned in full but
    not retained. Replacement, truncation, deletion and same-mtime rewrites all
    invalidate through the stat signature. An input changing during a read is
    returned as observed but is never installed in the cache.
    """
    path = Path(path)
    with _cache_lock:
        try:
            signature = _signature(path)
        except FileNotFoundError:
            _action_ids_cache.pop(path, None)
            return frozenset()
        cached = _action_ids_cache.get(path)
        if cached is not None and cached[0] == signature:
            _action_ids_cache.move_to_end(path)
            return cached[1]
        _action_ids_cache.pop(path, None)
        identifiers = set()
        with path.open(encoding="utf-8") as handle:
            for physical_line in handle:
                for line in physical_line.splitlines():
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    ident = row.get("action_id") if isinstance(row, dict) else None
                    if isinstance(ident, str) and ident:
                        identifiers.add(ident)
        result = frozenset(identifiers)
        try:
            unchanged = _signature(path) == signature
        except FileNotFoundError:
            unchanged = False
        characters = sum(len(ident) for ident in result)
        if unchanged and len(result) <= MAX_CACHED_ACTION_IDS and characters <= MAX_CACHED_ID_CHARACTERS:
            _action_ids_cache[path] = (signature, result, characters)
            total_ids = sum(len(entry[1]) for entry in _action_ids_cache.values())
            total_characters = sum(entry[2] for entry in _action_ids_cache.values())
            while (len(_action_ids_cache) > MAX_CACHED_FILES or total_ids > MAX_CACHED_ACTION_IDS
                   or total_characters > MAX_CACHED_ID_CHARACTERS):
                _, removed = _action_ids_cache.popitem(last=False)
                total_ids -= len(removed[1])
                total_characters -= removed[2]
        return result
