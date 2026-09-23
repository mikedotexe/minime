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
import os

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


LIVE_RESERVOIR_OUT = MINIME_WS / "diagnostics" / "live_reservoir_spectrum.json"
CAPACITY_DIR = MINIME_WS / "capacity"
HEALTH_PATH = MINIME_WS / "health.json"


def _live_reservoir_spectrum(dump_mtime: float) -> dict | None:
    """Read-only eigen-spectrum of the TRUE reservoir node space (2026-09-23).

    The engine refreshes workspace/capacity/esn_state_window.bin every ~30 s. While the
    stable-core scaffold holds, the published cascade/fill are rebuilt from the scaffold
    each tick, so this view is the only place the reservoir itself is visible. Same schema
    as the agent's `_live_reservoir_spectrum` (both may write; contents are equivalent).
    """
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        meta = json.loads((CAPACITY_DIR / "capacity_dump_meta.json").read_text())
        rows, n = int(meta.get("esn_window_rows") or 0), int(meta.get("esn_n") or 0)
        if rows <= 0 or n <= 0:
            return None
        states = np.fromfile(CAPACITY_DIR / "esn_state_window.bin", dtype=str(meta.get("dtype") or "<f4"))
        if states.size != rows * n:
            return None
        states = states.reshape(rows, n).astype(np.float64)
        if not np.isfinite(states).all():
            return None
        unc = np.clip(np.linalg.eigvalsh(states.T @ states / rows)[::-1], 0.0, None)
        cen = np.clip(np.linalg.eigvalsh(np.cov(states, rowvar=False))[::-1], 0.0, None)

        def summarize(w):
            total = float(w.sum()); top = [float(v) for v in w[:8]]
            if total <= 0.0:
                return {"top8": top, "trace": total, "lambda1_share": 0.0, "modes_for_90pct": 0, "effective_dim": 0.0}
            cum = np.cumsum(w) / total
            return {"top8": top, "trace": total, "lambda1_share": top[0] / total if top else 0.0,
                    "modes_for_90pct": int(np.searchsorted(cum, 0.90)) + 1,
                    "effective_dim": float((w.sum() ** 2) / ((w ** 2).sum()))}

        u, c = summarize(unc), summarize(cen)
        top8 = np.array(u["top8"]) if u["top8"] else np.zeros(0)
        thr = 0.12 * float(top8.mean()) ** 2 if top8.size else 0.0
        published = {}
        try:
            health = json.loads(HEALTH_PATH.read_text())
            sc = health.get("stable_core") if isinstance(health.get("stable_core"), dict) else {}
            published = {"fill_pct": health.get("fill_pct"), "lambda1_cov": health.get("lambda1_cov"),
                         "covariance_path": sc.get("covariance_path"), "structural_mode": sc.get("structural_mode"),
                         "scaffold_active": sc.get("scaffold_active")}
        except (OSError, ValueError, json.JSONDecodeError):
            published = {}
        return {
            "schema": "live_reservoir_spectrum_v1", "computed_at_unix_s": time.time(),
            "dump_mtime_unix_s": dump_mtime, "engine_t_ms": meta.get("t_ms"), "esn_n": n, "window_rows": rows,
            "state_rms": float(np.sqrt((states ** 2).mean())), "uncentered": u, "centered": c,
            "engine_style_fill_pct_top8": float((top8 > thr).mean() * 100.0) if top8.size else 0.0,
            "published": published, "writer": "eigen_spectrum_logger",
            "note": "read-only eigen-spectrum of the true reservoir node space from the engine capacity dump; the published cascade/fill may be scaffold-held",
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _refresh_live_reservoir(last_dump_mtime: float | None) -> float | None:
    """Recompute + atomically publish the live view when the capacity dump changed."""
    try:
        mtime = (CAPACITY_DIR / "esn_state_window.bin").stat().st_mtime
    except OSError:
        return last_dump_mtime
    if mtime == last_dump_mtime:
        return last_dump_mtime
    result = _live_reservoir_spectrum(mtime)
    if result is None:
        return last_dump_mtime
    try:
        LIVE_RESERVOIR_OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = LIVE_RESERVOIR_OUT.with_name(f"{LIVE_RESERVOIR_OUT.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(result, indent=1))
        os.replace(tmp, LIVE_RESERVOIR_OUT)
    except OSError:
        return last_dump_mtime
    return mtime


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
    last_dump_mtime = None
    print(f"[eigen-logger] polling {args.state} -> {args.out} every {args.interval}s", flush=True)
    while not _stop:
        last_dump_mtime = _refresh_live_reservoir(last_dump_mtime)
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
