#!/usr/bin/env python3
"""Join already frozen blind annotations to the completed fixed study."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from reflection_comparison_analysis import metrics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def analyze(root, annotations, expected):
    assert sha(annotations) == expected, 'annotations must be frozen before unblinding'
    packet = read(root / 'packet.json')
    assert sha(root / 'packet.json') == (root / 'packet.sha256').read_text().strip()
    assert packet['schema'] == 'reflection-deliberate-development-v1'
    summary = read(root / 'summary.json')
    resources = read(root / 'resource-receipt.json')
    assert summary['completed'] == 24 and resources['owned_group_empty'] and not resources['cleanup_error']
    blind = {row['id']: row for row in read(root / 'blind-review.json')}
    ratings = {row['id']: row for row in read(annotations)}
    assert len(blind) == len(ratings) == 24 and blind.keys() == ratings.keys()
    fields = ('distinctions', 'examples', 'counterarguments', 'qualifications', 'unsupported_mechanism_claims')
    for rating in ratings.values():
        assert all(isinstance(rating[field], list) and all(isinstance(item, str) for item in rating[field])
                   for field in fields)
        assert isinstance(rating['restatement'], str) and isinstance(rating['assessment'], str)
    rows = []
    for job in packet['jobs']:
        result = read(root / (job['id'] + '-result.json'))
        assert result['completed'] and result['job'] == job
        assert result['request_sha256'] == sha(root / (job['id'] + '-request.json'))
        assert blind[job['blind_id']]['text'] == result['response']['message']['content']
        rows.append(result)
    cells = []
    for cell, name in enumerate(('fresh', 'selected_public_context', 'native_private_continuation')):
        chosen = [row for row in rows if row['job']['cell'] == cell]
        assert len(chosen) == 8
        values = metrics([row['response']['message']['content'] for row in chosen])
        values.update(cell=cell, condition=name, sample_ids=[row['job']['blind_id'] for row in chosen],
            completion_reasons=dict(Counter(row['response']['done_reason'] for row in chosen)),
            prompt_tokens=[row['response']['prompt_eval_count'] for row in chosen],
            output_tokens=[row['response']['eval_count'] for row in chosen],
            wall_seconds=[row['wall_seconds'] for row in chosen],
            prefill_seconds=[row['response'].get('prompt_eval_duration', 0) / 1e9 for row in chosen],
            decode_seconds=[row['response'].get('eval_duration', 0) / 1e9 for row in chosen],
            annotated_presence={field: sum(bool(ratings[row['job']['blind_id']][field]) for row in chosen)
                                for field in fields})
        cells.append(values)
    return dict(schema='reflection_development_descriptive_analysis_v1',
        packet_sha256=sha(root / 'packet.json'), annotations_sha256=sha(annotations),
        blind_review_sha256=sha(root / 'blind-review.json'), analysis_sha256=sha(Path(__file__)),
        metrics_source_sha256=sha(ROOT / 'scripts/reflection_comparison_analysis.py'),
        result_sha256={job['id']: sha(root / (job['id'] + '-result.json')) for job in packet['jobs']},
        resource_receipt_sha256=sha(root / 'resource-receipt.json'),
        cells=cells, summary=summary,
        limits='Fixed one-model, one-step sample with one repeated seed per cell. One condition-blinded qualitative reviewer; labels are interpretive, not validated scores. Text itself can reveal supplied context. Full visible output includes inert NEXT tails. No significance, subjective, reservoir or live-policy claim.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('annotations', type=Path)
    parser.add_argument('annotations_sha256')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = analyze(args.root, args.annotations, args.annotations_sha256)
    with args.output.open('x') as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': 'passed', 'output': str(args.output), 'sha256': sha(args.output)}))
