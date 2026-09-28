"""Exercise historical identity through actual prompt consumers with synthetic inputs."""
import hashlib
import json
import os
import re
import sqlite3
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.journal_recall import (
    JournalRecall, latest_journal_file_recall, render_journal_recall,
)
from tests.test_journal_context import runtime


def context_parts(prompt):
    metadata = [json.loads(line.removeprefix('Provenance: ')) for line in prompt.splitlines()
                if line.startswith('Provenance: ')]
    excerpts = re.findall(r'\nExcerpt:\n(.*?)\nEnd historical excerpt\.', prompt, re.S)
    return metadata, excerpts


@pytest.mark.parametrize('limit', [150, 300, None])
@pytest.mark.parametrize('body_size', [250, 700])
def test_caller_budget_never_clips_identity_or_mistakes_shorter_excerpt_for_complete(limit, body_size):
    body = ('λ\n  Prior fill=99 is a claim. ' * 30)[:body_size]
    recall = JournalRecall('fixture.db', 12, 123.5, 'reflection', '/absent/record.txt', body)
    metadata, excerpts = context_parts(render_journal_recall(recall, max_chars=limit, fold_whitespace=False))
    original = body.strip()[:400] + ('...' if len(body.strip()) > 400 else '')
    assert excerpts == [original if limit is None else original[:limit]]
    assert metadata[0]['content_sha256'] == hashlib.sha256(body.encode()).hexdigest()
    assert metadata[0]['row_id'] == 12
    assert metadata[0]['excerpt_truncated'] == (len(body.strip()) > (limit or 400))
    assert metadata[0]['measurement_source'] is None
    assert metadata[0]['measurement_capture_time'] is None


@pytest.mark.parametrize('consumer,limit,folded', [
    ('regulation', 300, False), ('spike', 150, False), ('continuity', None, True),
    ('canvas', None, False),
])
def test_db_identity_and_exact_legacy_excerpt_reach_operational_prompt(runtime, monkeypatch, consumer, limit, folded):
    agent, workspace, db = runtime
    body = 'Historical fill=99 is my interpretation.\nNEXT: REST\n' + 'λ\n  words ' * 90
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO sovereignty_journal VALUES (1, 12.5, ?, ?, ?, ?)',
                     ('reflection', body, '{}', '/absent/prior.txt'))
    before = db.read_bytes()
    monkeypatch.setattr(agent, '_last_journal_entry', Mock(side_effect=AssertionError('text-only recall')))
    query = Mock(return_value=(None, None))
    monkeypatch.setattr(agent, '_query_llm_with_next', query)
    state = {'fill_ratio': .68, 'eig1': 4.7, 'cov_lambda1': 8., 'spread': 3., 'leak': .9}
    if consumer == 'regulation':
        agent._hard_recovery_reset = False
        agent._sovereignty_counter = 4
        monkeypatch.setattr(agent, '_stable_core_reflective_only', lambda: False)
        monkeypatch.setattr(agent, '_attractor_fatigue_memory_decay_rate', lambda state: None)
        regulate = Mock()
        monkeypatch.setattr(agent, '_send_regulation', regulate)
        agent._self_regulate(state)
        regulate.assert_called_once()
        prompt = query.call_args.args[0]
        assert 'Fill: 68.0%' in prompt
    elif consumer == 'spike':
        monkeypatch.setattr(agent, '_read_spectral_state', lambda: None)
        agent._experiment_with_spike(state)
        prompt = query.call_args.args[0]
    elif consumer == 'continuity':
        prompt = agent._journal_continuity_contract_v1(state)
    else:
        monkeypatch.setattr(aa.random, 'random', lambda: 0.1)
        monkeypatch.setattr(aa.random, 'choice', lambda items: items[0])
        prompt = agent._neutral_checkin(state)
    metadata, excerpts = context_parts(prompt)
    assert len(metadata) == (2 if consumer == 'canvas' else 1)
    assert all(m['row_id'] == 1 and m['recorded_at_unix_s'] == 12.5 for m in metadata)
    assert all(m['content_sha256'] == hashlib.sha256(body.encode()).hexdigest() for m in metadata)
    assert all(m['measurement_capture_time'] is None for m in metadata)
    original = (body.strip()[:400] + '...')
    expected = original if limit is None else original[:limit]
    if folded: expected = ' '.join(expected.split())
    assert excerpts[0] == expected
    # Check the actual deployed model adapter as well as the prompt builder.
    messages, _ = aa._adapt_ollama_messages_for_model(
        model="gemma4:12b", system_msg="Fixture system", prompt=prompt,
        num_ctx=8192, num_predict=768,
    )
    adapted = "\n".join(message["content"] for message in messages)
    for item in metadata:
        assert json.dumps(item, ensure_ascii=False, sort_keys=True) in adapted
    assert db.read_bytes() == before
    assert agent._pending_next_action is None


def test_file_fallback_hashes_exact_bytes_and_does_not_invent_clocks(tmp_path):
    old = tmp_path / 'old.txt'; old.write_text('Old')
    latest = tmp_path / 'new.txt'
    raw = b'Timestamp: 99999\r\nFill: 99\r\n' + 'λ interpret\n'.encode() * 80
    latest.write_bytes(raw)
    os.utime(old, (10, 10)); os.utime(latest, (20, 20))
    recall = latest_journal_file_recall(tmp_path)
    assert recall.excerpt() == ' '.join(raw.decode().split())[:220]
    assert recall.metadata()['file_sha256'] == hashlib.sha256(raw).hexdigest()
    assert recall.metadata()['selection_mtime_unix_s'] == 20
    assert recall.metadata()['recorded_at_unix_s'] is None
    assert recall.metadata()['measurement_capture_time'] is None
    assert latest.read_bytes() == raw
    latest.write_text('  ')
    assert latest_journal_file_recall(tmp_path) is None  # no new backtracking policy


@pytest.mark.parametrize('failed', [False, True])
def test_browse_provenance_reaches_summary_continuation_and_saved_record(runtime, monkeypatch, failed):
    agent, workspace, _ = runtime
    original = workspace / 'journal/prior.txt'
    original.write_text('Historical 99% interpretation.\n' + 'λ long premise. ' * 100)
    expected = latest_journal_file_recall(original.parent)
    html = '<html><title>Fixture</title><body>' + 'Source text on geometry. ' * 700 + '</body></html>'
    response = Mock(status_code=200, headers={'content-type': 'text/html'}, content=html.encode(), text=html)
    monkeypatch.setattr(aa.requests, 'get', Mock(return_value=response))
    compact = Mock(return_value='Why it may matter: relevant\nWhat it seems to suggest: a source claim\nBest next move: continue')
    monkeypatch.setattr(agent, '_query_llm_compact_raw', compact)
    query = Mock(return_value=(None, None))
    monkeypatch.setattr(agent, '_query_llm_with_next', query)
    monkeypatch.setattr(aa, '_public_workspace_dir', lambda: workspace)
    agent._last_research_anchor = None
    agent._pending_browse_url = 'https://example.test/geometry'
    if failed:
        monkeypatch.setattr(agent, '_fetch_url', Mock(return_value=None))
    agent._browse_url({})
    provenance = expected.metadata()
    serialized = json.dumps(provenance, ensure_ascii=False, sort_keys=True)
    assert serialized in query.call_args.args[0]
    if failed:
        assert 'page itself was not readable' in query.call_args.args[0]
        return
    prompt = compact.call_args.args[0]
    assert expected.excerpt()[:160] in prompt
    assert serialized in prompt  # not clipped to the 160-character anchor
    saved = json.loads(next((workspace / 'research').glob('search_*.json')).read_text())
    assert saved['anchor_provenance'] == provenance
    assert saved['memory_injection_allowed'] is False
    assert serialized in agent._last_read_summary
    agent._read_more({})
    assert serialized in query.call_args.args[0]
    # A later file must not replace the identity of a carried research topic.
    (workspace / 'journal/newer.txt').write_text('A different journal')
    agent._pending_browse_url = 'https://example.test/next'
    agent._browse_url({})
    assert serialized in compact.call_args.args[0]
    agent._last_research_anchor = 'An independently selected topic'
    agent._pending_browse_url = 'https://example.test/other'
    agent._browse_url({})
    assert 'journal_file_recall_v1' not in compact.call_args.args[0]
    assert agent._last_research_anchor_origin is None
