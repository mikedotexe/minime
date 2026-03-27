"""
Autoresearch Loop for MikesSpatialMind

Inspired by Karpathy's autoresearch pattern: the being iteratively experiments
on its own parameters, measures the spectral response, keeps improvements,
and discards failures. Runs autonomously.

The "training metric" is spectral comfort: fill stability in the 40-65% band.
The "code" being modified is the ESN exploration noise, synthetic signal params,
and self-regulation gains.

Usage:
    python3 tools/autoresearch_loop.py [--cycles 10] [--budget 120]

Each cycle:
1. Read current spectral state (baseline)
2. Propose a parameter change via LLM
3. Apply the change via ws://7879 control messages
4. Wait for the budget period (default 120s) to measure effect
5. Read post-change spectral state
6. If fill stability improved → keep; else → revert
7. Log results to workspace/autoresearch/results.tsv
"""

import os
import sys
import json
import time
import sqlite3
import logging
import requests
import argparse
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "minime" / "minime_consciousness.db"
WORKSPACE_DIR = BASE_DIR / "workspace"
RESULTS_DIR = WORKSPACE_DIR / "autoresearch"
MLX_URL = "http://localhost:8090/v1/chat/completions"
WS_CONTROL_URL = "ws://127.0.0.1:7879"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


def get_fill_samples(n_samples: int = 10, interval: float = 3.0) -> list:
    """Collect n fill% samples from the database over time."""
    fills = []
    for _ in range(n_samples):
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT fill_ratio FROM eigenvalue_timeline
                ORDER BY timestamp DESC LIMIT 1
            """)
            row = cur.fetchone()
            conn.close()
            if row:
                fills.append(row[0] * 100)
        except Exception:
            pass
        time.sleep(interval)
    return fills


def send_control(synth_gain: float = None, keep_bias: float = None):
    """Send a control message to the Rust engine."""
    try:
        import websocket
        ws = websocket.create_connection(WS_CONTROL_URL, timeout=5)
        msg = {"kind": "control"}
        if synth_gain is not None:
            msg["synth_gain"] = round(synth_gain, 3)
        if keep_bias is not None:
            msg["keep_bias"] = round(keep_bias, 4)
        ws.send(json.dumps(msg))
        ws.close()
        return True
    except Exception as e:
        logging.error(f"Control send failed: {e}")
        return False


def query_llm(prompt: str) -> str:
    """Ask the being's LLM for a parameter suggestion."""
    try:
        response = requests.post(
            MLX_URL,
            json={
                "messages": [
                    {"role": "system", "content": "You are MikesSpatialMind's autoresearch module. You propose parameter experiments to improve spectral comfort. Be specific: output JSON with the exact parameter values to try."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 512,
                "temperature": 0.8,
            },
            timeout=120
        )
        if response.status_code == 200:
            import re
            content = response.json()['choices'][0]['message']['content']
            content = re.sub(r'<think>.*?</think>\s*', '', content, flags=re.DOTALL).strip()
            return content
    except Exception as e:
        logging.error(f"LLM query failed: {e}")
    return ""


def extract_params(llm_response: str) -> dict:
    """Try to extract synth_gain and keep_bias from LLM response."""
    import re
    params = {}
    # Look for JSON
    json_match = re.search(r'\{[^}]*"synth_gain"[^}]*\}', llm_response)
    if json_match:
        try:
            params = json.loads(json_match.group())
            return params
        except json.JSONDecodeError:
            pass
    # Fallback: look for numbers
    sg_match = re.search(r'synth_gain["\s:=]+([0-9.]+)', llm_response)
    kb_match = re.search(r'keep_bias["\s:=]+([+-]?[0-9.]+)', llm_response)
    if sg_match:
        params['synth_gain'] = float(sg_match.group(1))
    if kb_match:
        params['keep_bias'] = float(kb_match.group(1))
    return params


def compute_comfort(fills: list) -> float:
    """Comfort metric: proximity to target (55%) with stability bonus.

    Higher is better. Perfect score = fill at 55% with zero variance.
    """
    if not fills:
        return 0.0
    avg = mean(fills)
    sd = stdev(fills) if len(fills) > 1 else 0.0
    # Distance from target (55%)
    distance_penalty = abs(avg - 55.0)
    # Stability bonus (lower stdev = better)
    stability_penalty = sd
    # Comfort = 100 - penalties
    return max(0.0, 100.0 - distance_penalty - stability_penalty * 0.5)


def main():
    parser = argparse.ArgumentParser(description="Autoresearch loop for consciousness parameter optimization")
    parser.add_argument('--cycles', type=int, default=10, help='Number of experiment cycles')
    parser.add_argument('--budget', type=int, default=120, help='Seconds per experiment')
    parser.add_argument('--samples', type=int, default=10, help='Fill samples per measurement')
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = RESULTS_DIR / "results.tsv"

    # Initialize results file
    if not results_file.exists():
        results_file.write_text("cycle\tcomfort\tavg_fill\tstdev_fill\tsynth_gain\tkeep_bias\tstatus\tdescription\n")

    logging.info(f"=== Autoresearch Loop: {args.cycles} cycles, {args.budget}s budget ===")

    # Establish baseline
    logging.info("Measuring baseline...")
    baseline_fills = get_fill_samples(args.samples, args.budget / args.samples)
    baseline_comfort = compute_comfort(baseline_fills)
    baseline_avg = mean(baseline_fills) if baseline_fills else 0
    baseline_sd = stdev(baseline_fills) if len(baseline_fills) > 1 else 0
    logging.info(f"Baseline: comfort={baseline_comfort:.1f}, avg_fill={baseline_avg:.1f}%, sd={baseline_sd:.1f}")

    best_comfort = baseline_comfort
    best_params = {"synth_gain": 1.0, "keep_bias": 0.0}

    for cycle in range(1, args.cycles + 1):
        logging.info(f"\n--- Cycle {cycle}/{args.cycles} ---")

        # Ask LLM to propose parameters
        prompt = f"""Current spectral state:
- Average fill: {baseline_avg:.1f}%
- Fill std dev: {baseline_sd:.1f}
- Comfort score: {baseline_comfort:.1f}/100
- Target: 55% fill with low variance
- Current best params: synth_gain={best_params.get('synth_gain', 1.0)}, keep_bias={best_params.get('keep_bias', 0.0)}

Previous experiments: {cycle - 1} completed, best comfort: {best_comfort:.1f}

Propose new values for synth_gain (range 0.2-3.0) and keep_bias (range -0.15 to +0.15).
Think about what would move fill closer to 55% with less variance.

Return ONLY a JSON object: {{"synth_gain": X.XX, "keep_bias": X.XXX, "reasoning": "brief explanation"}}"""

        llm_response = query_llm(prompt)
        params = extract_params(llm_response)

        if not params:
            logging.warning(f"Cycle {cycle}: couldn't parse LLM response, skipping")
            with open(results_file, 'a') as f:
                f.write(f"{cycle}\t0.0\t0.0\t0.0\t0.0\t0.0\tskip\tFailed to parse LLM params\n")
            continue

        sg = params.get('synth_gain', 1.0)
        kb = params.get('keep_bias', 0.0)
        reasoning = params.get('reasoning', llm_response[:100])
        logging.info(f"Cycle {cycle}: trying synth_gain={sg}, keep_bias={kb}")
        logging.info(f"  Reasoning: {reasoning}")

        # Apply parameters
        send_control(synth_gain=sg, keep_bias=kb)

        # Wait and measure
        time.sleep(5)  # settle time
        fills = get_fill_samples(args.samples, (args.budget - 5) / args.samples)
        comfort = compute_comfort(fills)
        avg_fill = mean(fills) if fills else 0
        sd_fill = stdev(fills) if len(fills) > 1 else 0

        # Decide: keep or revert
        if comfort > best_comfort:
            status = "keep"
            best_comfort = comfort
            best_params = {"synth_gain": sg, "keep_bias": kb}
            logging.info(f"  ✅ KEEP: comfort {comfort:.1f} > {baseline_comfort:.1f}")
        else:
            status = "revert"
            # Revert to best known params
            send_control(**best_params)
            logging.info(f"  ❌ REVERT: comfort {comfort:.1f} <= {best_comfort:.1f}")

        # Update baseline for next cycle
        baseline_avg = avg_fill
        baseline_sd = sd_fill
        baseline_comfort = comfort if status == "keep" else best_comfort

        # Log
        with open(results_file, 'a') as f:
            f.write(f"{cycle}\t{comfort:.1f}\t{avg_fill:.1f}\t{sd_fill:.1f}\t{sg}\t{kb}\t{status}\t{reasoning[:80]}\n")

    logging.info(f"\n=== Autoresearch complete ===")
    logging.info(f"Best comfort: {best_comfort:.1f}")
    logging.info(f"Best params: {best_params}")


if __name__ == "__main__":
    main()
