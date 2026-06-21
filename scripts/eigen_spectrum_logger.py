#!/usr/bin/env python3
"""eigen_spectrum_logger.py — read-only logger of minime's full eigenvalue spectrum.

minime's `th_minime_20260605` investigation ("disrupted λ4 decay") had no per-tick record of
λ4 itself: her `observations.jsonl` logs λ1 + the derived pressure components + porosity, but
NOT the full spectrum. This logger fills that gap so the actual λ4 trace can be watched — it
polls the engine's live `spectral_state.json` (which carries the full `eigenvalues` vector
*plus* the pressure components and porosity) and appends a compact, de-duplicated time-series
to `workspace/diagnostics/eigen_spectrum_log.jsonl`.

READ-ONLY + non-engine: it never writes to the engine, never opens a socket, never touches
`minime/minime/src`. It only reads one JSON file and appends to a log. (File-poll, deliberately
NOT the port-7878 WebSocket — no socket means no reconnect/hang failure mode, the thing that
bit `astrid_feeder`.)

Robust by construction:
  * graceful SIGTERM/SIGINT (stop flag checked every ~0.25s; flush + clean exit — can't hang);
  * size-based rotation (bounded disk);
  * parse-tolerant (the engine writes spectral_state.json atomically, so reads are normally
    complete; a transient OSError / partial read is skipped, not fatal);
  * de-duplicated (a static state is not logged repeatedly — only changes are appended).
"""
import argparse
import json
import signal
import time
from pathlib import Path

MINIME_WS = Path("/Users/v/other/minime/workspace")
DEFAULT_STATE = MINIME_WS / "spectral_state.json"
DEFAULT_OUT = MINIME_WS / "diagnostics" / "eigen_spectrum_log.jsonl"

_stop = False


def _request_stop(*_a):
    global _stop
    _stop = True


def _rotate(path: Path, max_bytes: int, keep: int) -> None:
    """If `path` is at/over max_bytes, shift base->.1->.2->...(keep), dropping the oldest."""
    try:
        if not (path.exists() and path.stat().st_size >= max_bytes):
            return
        for i in range(keep, 1, -1):
            src = path.with_name(f"{path.name}.{i - 1}")
            if src.exists():
                src.replace(path.with_name(f"{path.name}.{i}"))
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass


def _extract(d: dict) -> dict | None:
    """Pull the spectrum + the metrics most relevant to the λ4 investigation."""
    ev = d.get("eigenvalues") or d.get("lambdas")
    if not isinstance(ev, list) or not ev:
        return None
    try:
        ev = [round(float(x), 5) for x in ev]
    except (TypeError, ValueError):
        return None
    ps = d.get("pressure_source_v1") or {}
    comp = ps.get("components") or {}
    prov = d.get("provenance") or {}
    lam4 = ev[3] if len(ev) > 3 else None
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "t_ms": d.get("t_ms"),
        "engine_t_s": prov.get("engine_t_s"),
        "snapshot_sequence": prov.get("snapshot_sequence"),
        "eigenvalues": ev,
        "lambda1": ev[0],
        "lambda4": lam4,
        "tail_floor": ev[-1],
        "lambda4_above_floor": round(lam4 - ev[-1], 5) if lam4 is not None else None,
        "active_mode_count": d.get("active_mode_count"),
        "mode_packing": comp.get("mode_packing"),
        "lambda_monopoly": comp.get("lambda_monopoly"),
        "porosity_score": ps.get("porosity_score"),
        "pressure_quality": ps.get("quality"),
        "fill_pct": d.get("fill_pct"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="read-only minime eigenvalue-spectrum logger")
    ap.add_argument("--interval", type=float, default=1.0, help="poll seconds (default 1.0)")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max-bytes", type=int, default=25_000_000, help="rotate at this size")
    ap.add_argument("--keep", type=int, default=3, help="rotated files to retain")
    ap.add_argument("--once", action="store_true", help="log one changed sample then exit (smoke test)")
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    last_key = None
    last_mtime = None
    wrote = 0
    print(f"[eigen-logger] polling {args.state} -> {args.out} every {args.interval}s", flush=True)
    while not _stop:
        try:
            mtime = args.state.stat().st_mtime
            if mtime != last_mtime:
                last_mtime = mtime
                rec = _extract(json.loads(args.state.read_text()))
                if rec is not None:
                    # Dedup on the engine's own snapshot_sequence (one record per real engine
                    # tick) — so a recurring spectrum in a genuine oscillation is still kept
                    # (each occurrence has a distinct sequence). Fall back to content if absent.
                    key = rec.get("snapshot_sequence")
                    if key is None:
                        key = (tuple(rec["eigenvalues"]), rec.get("fill_pct"))
                    if key != last_key:
                        last_key = key
                        _rotate(args.out, args.max_bytes, args.keep)
                        with args.out.open("a") as f:
                            f.write(json.dumps(rec) + "\n")
                        wrote += 1
                        if args.once:
                            print(f"[eigen-logger] wrote 1 sample: λ4={rec['lambda4']} "
                                  f"tail_floor={rec['tail_floor']} quality={rec['pressure_quality']}", flush=True)
                            return
        except (OSError, ValueError, json.JSONDecodeError):
            pass  # transient read/parse — retry next poll
        slept = 0.0
        while slept < args.interval and not _stop:
            time.sleep(min(0.25, args.interval - slept))
            slept += 0.25
    print(f"[eigen-logger] shutting down ({wrote} samples written this run)", flush=True)


if __name__ == "__main__":
    main()
