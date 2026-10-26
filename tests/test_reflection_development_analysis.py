"""Descriptive joins must bind the frozen blind review and exact outputs."""
import json
from pathlib import Path
import runpy

import pytest

tool = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/reflection_development_analysis.py'))


def save(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def study(tmp_path):
    jobs, blind, ratings = [], [], []
    for index in range(24):
        ident = f'job-{index + 1:02d}'
        sample = f'sample-{index + 1:02d}'
        job = dict(id=ident, blind_id=sample, cell=index % 3)
        jobs.append(job)
        text = f'Synthetic public development {index}.'
        blind.append(dict(id=sample, text=text))
        ratings.append(dict(id=sample, distinctions=['Synthetic distinction'], examples=[],
                            counterarguments=[], qualifications=[], unsupported_mechanism_claims=[],
                            restatement='Synthetic restatement assessment', assessment='Synthetic review'))
        request = tmp_path / (ident + '-request.json')
        save(request, dict(synthetic=True, index=index))
        save(tmp_path / (ident + '-result.json'), dict(job=job, completed=True,
             request_sha256=tool['sha'](request), wall_seconds=1,
             response=dict(message=dict(content=text), done_reason='stop', prompt_eval_count=20,
                           eval_count=6, prompt_eval_duration=1, eval_duration=2)))
    save(tmp_path / 'packet.json', dict(schema='reflection-deliberate-development-v1', jobs=jobs))
    (tmp_path / 'packet.sha256').write_text(tool['sha'](tmp_path / 'packet.json') + '\n')
    save(tmp_path / 'summary.json', dict(completed=24))
    save(tmp_path / 'resource-receipt.json', dict(owned_group_empty=True, cleanup_error=None))
    save(tmp_path / 'blind-review.json', blind)
    annotations = tmp_path / 'annotations.json'
    save(annotations, ratings)
    return tmp_path, annotations, tool['sha'](annotations)


def test_fixed_join_is_descriptive_and_changes_nothing(study):
    root, ratings, digest = study
    before = {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob('*')}
    report = tool['analyze'](root, ratings, digest)
    assert len(report['cells']) == 3
    assert all(cell['samples'] == 8 for cell in report['cells'])
    assert all(cell['annotated_presence']['distinctions'] == 8 for cell in report['cells'])
    assert len(report['result_sha256']) == 24
    assert 'not validated scores' in report['limits']
    assert {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob('*')} == before


@pytest.mark.parametrize('target', ['annotation_digest', 'packet_digest', 'request', 'visible_text',
                                  'incomplete', 'cleanup', 'missing_rating', 'invalid_rating'])
def test_conflicts_are_not_presented_as_completed_analysis(study, target):
    root, ratings, digest = study
    if target == 'annotation_digest':
        digest = '0' * 64
    elif target == 'packet_digest':
        (root / 'packet.sha256').write_text('0' * 64)
    elif target == 'request':
        save(root / 'job-01-request.json', dict(changed=True))
    elif target == 'visible_text':
        value = json.loads((root / 'blind-review.json').read_bytes())
        value[0]['text'] = 'Changed text'
        save(root / 'blind-review.json', value)
    elif target == 'incomplete':
        save(root / 'summary.json', dict(completed=23))
    elif target == 'cleanup':
        save(root / 'resource-receipt.json', dict(owned_group_empty=False, cleanup_error='uncertain'))
    else:
        value = json.loads(ratings.read_bytes())
        if target == 'missing_rating':
            value.pop()
        else:
            value[0]['distinctions'] = 'not an array'
        save(ratings, value)
        digest = tool['sha'](ratings)
    with pytest.raises(AssertionError):
        tool['analyze'](root, ratings, digest)
