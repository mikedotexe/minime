#!/usr/bin/env python3
"""Descriptive analysis of the fixed synthetic study; never executes model text."""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import re
import statistics
import unicodedata


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def words(text):
    return re.findall(r"\b\w+(?:['’]\w+)?\b", unicodedata.normalize("NFKC", text).casefold())


def metrics(texts):
    tokens = [words(text) for text in texts]
    openings = [tuple(row[:12]) for row in tokens]
    grams = [{tuple(row[i:i + 5]) for i in range(max(0, len(row) - 4))} for row in tokens]
    pairs = list(itertools.combinations(range(len(texts)), 2))
    overlaps = [len(grams[i] & grams[j]) / len(grams[i] | grams[j])
                for i, j in pairs if grams[i] | grams[j]]
    frequency = Counter(gram for sample in grams for gram in sample)
    return {
        "samples": len(texts), "pairs": len(pairs),
        "words": [len(row) for row in tokens],
        "median_words": statistics.median(map(len, tokens)),
        "matching_first_12_word_pairs": sum(bool(openings[i]) and openings[i] == openings[j] for i, j in pairs),
        "mean_pairwise_five_word_jaccard": statistics.mean(overlaps) if overlaps else None,
        "shared_five_word_phrases": [{"text": " ".join(gram), "samples": count}
                                      for gram, count in sorted(frequency.items(), key=lambda item: (-item[1], item[0]))[:10]
                                      if count > 1],
    }


def analyze(root, ratings_path):
    packet = read(root / "packet.json")
    assert sha(root / "packet.json") == (root / "packet.sha256").read_text().strip()
    summary = read(root / "summary.json")
    assert summary["completed"] == 24
    receipt = read(root / "resource-receipt.json")
    assert receipt["owned_group_empty"] and not receipt["cleanup_error"]
    blind = read(root / "blind-review.json")
    ratings = read(ratings_path)
    assert len(blind) == len(ratings) == 24
    by_id = {row["id"]: row for row in blind}
    rated = {row["id"]: row for row in ratings}
    assert len(by_id) == len(rated) == 24 and by_id.keys() == rated.keys()
    results = []
    cells = []
    for job in packet["jobs"]:
        result = read(root / (job["id"] + "-result.json"))
        response = result["response"]
        assert result["completed"] and result["job"] == job
        assert by_id[job["blind_id"]]["text"] == response["message"]["content"]
        assert result["request_sha256"] == sha(root / (job["id"] + "-request.json"))
        assert rated[job["blind_id"]]["administrative_uptake"] in ("absent", "passing", "organizing")
        results.append({"job": job, "response": response, "wall_seconds": result["wall_seconds"]})
    for cell in range(4):
        selected = [r for r in results if r["job"]["cell"] == cell]
        annotations = [rated[r["job"]["blind_id"]] for r in selected]
        row = metrics([r["response"]["message"]["content"] for r in selected])
        row.update(cell=cell, frame="old" if cell < 2 else "lighter", mailbox_notice=cell % 2 == 0,
                   sample_ids=[r["job"]["blind_id"] for r in selected],
                   administrative_uptake=dict(Counter(a["administrative_uptake"] for a in annotations)),
                   mechanism_flagged_samples=sum(bool(a["unsupported_mechanism_claims"]) for a in annotations),
                   prompt_tokens=[r["response"].get("prompt_eval_count") for r in selected],
                   output_tokens=[r["response"].get("eval_count") for r in selected],
                   wall_seconds=[r["wall_seconds"] for r in selected],
                   prefill_seconds=[r["response"].get("prompt_eval_duration", 0) / 1e9 for r in selected],
                   decode_seconds=[r["response"].get("eval_duration", 0) / 1e9 for r in selected])
        cells.append(row)
    return {"schema": "reflection_descriptive_analysis_v1", "packet_sha256": sha(root / "packet.json"),
            "blind_review_sha256": sha(root / "blind-review.json"), "ratings_sha256": sha(ratings_path),
            "analysis_source_sha256": sha(Path(__file__)), "cells": cells, "completion_summary": summary,
            "limits": "Descriptive fixed sample, including one repeated seed per cell. Full output counted, including any inert NEXT tail. Single blind reviewer, not an independently validated rubric. No significance, novelty, subjective or reservoir-effect claim."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("ratings", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = analyze(args.root, args.ratings)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
