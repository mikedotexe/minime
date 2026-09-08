"""Extract physical samples from a bounded saved evidence bundle, never its live sources."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--anchor-unix-ms", type=int, required=True)
    args = parser.parse_args()
    if args.bundle.stat().st_size > 16*1024*1024:
        raise ValueError("bundle exceeds 16 MiB")
    bundle_bytes = args.bundle.read_bytes()
    bundle = json.loads(bundle_bytes)
    records = [row for row in bundle["records"] if row["kind"] == "telemetry" and row["being"] == "minime"
               and row["source"]["locator"].get("table") == "eigenvalue_timeline"
               and args.anchor_unix_ms-30_000 <= round(row["occurred_at"]*1000) <= args.anchor_unix_ms+96_000]
    records.sort(key=lambda row: row["occurred_at"])
    if not records:
        raise ValueError("no physical observations in selected window")
    session = records[0]["source"]["locator"]["session"]
    session_id = str(session["session_id"])
    anchor_engine = args.anchor_unix_ms-round(session["start_time"]*1000)
    request = {"type":"request", "request":{"request_id":"historical_request", "afterimage_id":"ai_2026-09-06_historical_0919",
               "session_id":session_id, "anchor_engine_t_ms":anchor_engine, "anchor_unix_ms":args.anchor_unix_ms,
               "requested_at_unix_ms":args.anchor_unix_ms}}
    rows, requested = [], False
    for row in records:
        payload = row["payload"]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        if digest != row["source"]["sha256"] or str(payload["session_id"]) != session_id:
            raise ValueError("source digest or session mismatch")
        timestamp = round(payload["timestamp"]*1000)
        values = {"fill_pct":payload["fill_ratio"]*100, "cascade_lambda1":payload["lambda1"],
                  "source_record_id":row["source_record_id"], "source_payload_sha256":digest,
                  "source_session_mode":payload["phase"], "dfill_dt":None, "lambda_stress":None,
                  "phase":None, "geom_rel":None,
                  "source_bundle_sha256":hashlib.sha256(bundle_bytes).hexdigest()}
        rows.append({"type":"sample", "sample":{"channel":"body", "engine_t_ms":timestamp,
                    "wall_clock_unix_ms":round(row["occurred_at"]*1000), "expected_cadence_ms":2500, "values":values}})
        if not requested and timestamp >= anchor_engine:
            rows.append(request)
            requested = True
    if not requested:
        raise ValueError("anchor not reached")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps({"samples":len(records), "session_id":session_id, "bundle_sha256":hashlib.sha256(bundle_bytes).hexdigest(),
                      "output":str(args.output), "classification":"manually_selected_historical_episode_not_detected_event"}))


if __name__ == "__main__":
    main()
