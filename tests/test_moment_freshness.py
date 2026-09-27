"""Synthetic regression for the September 27 old-spike/rate interpretation path."""
from datetime import datetime, timezone
import json
import sqlite3
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.journal_context import format_marker_anchors
from minime_autonomy.moment_context import select_recent_markers, pressure_classifier_context
from tests.test_journal_context import runtime


@pytest.fixture
def records():
    with sqlite3.connect(":memory:") as conn:
        conn.execute("""CREATE TABLE moment_markers (
            id INTEGER PRIMARY KEY, session_id INTEGER, timestamp REAL,
            marker_type TEXT, description TEXT, spectral_context TEXT,
            consumed INTEGER, created_at_unix REAL)""")
        yield conn


def add(conn, ident, *, recorded=99_999., engine=149_999., session=1, consumed=0):
    conn.execute("INSERT INTO moment_markers VALUES (?, ?, ?, 'spectral_spike', ?, '{}', ?, ?)",
                 (ident, session, engine, f"Event {ident}", consumed, recorded))


def select(conn, **kwargs):
    return select_recent_markers(conn, 1, recorded_now=100_000., engine_now=150_000., **kwargs)


def test_fresh_selection_is_bounded_deterministic_and_does_not_consume_history(records):
    add(records, 1, recorded=100_000. - 76535, engine=150_000. - 76533)
    for ident in range(2, 6):
        add(records, ident)
    add(records, 6, session=2)
    add(records, 7, consumed=1)
    before = records.execute("SELECT * FROM moment_markers ORDER BY id").fetchall()
    assert [row['id'] for row in select(records)] == [5, 4, 3]
    assert records.execute("SELECT * FROM moment_markers ORDER BY id").fetchall() == before


@pytest.mark.parametrize("recorded,engine,eligible", [
    (99_100., 149_100., True),  # both clocks at the inclusive 15-minute boundary
    (99_099., 150_000., False), (100_000., 149_099., False),
    (100_001., 150_000., False), (100_000., 150_001., False),
    (None, 150_000., False), (100_000., None, False),
    ('invalid', 150_000., False), (100_000., 'invalid', False),
    (float('inf'), 150_000., False), (100_000., float('nan'), False),
])
def test_freshness_requires_valid_recent_recording_and_session_engine_clocks(records, recorded, engine, eligible):
    add(records, 1, recorded=recorded, engine=engine)
    assert bool(select(records)) is eligible
    assert records.execute("SELECT consumed FROM moment_markers").fetchone()[0] == 0


def test_unknown_reference_or_legacy_schema_stays_available_for_explicit_inspection(records):
    add(records, 1)
    for engine in (None, float('inf'), 'unknown'):
        assert select_recent_markers(records, 1, recorded_now=100_000., engine_now=engine) == []
    records.execute("ALTER TABLE moment_markers DROP COLUMN created_at_unix")
    assert select(records) == []
    assert records.execute("SELECT description, consumed FROM moment_markers").fetchone() == ('Event 1', 0)


def test_real_runtime_selects_recent_event_and_retains_old_backlog_without_generation(runtime, monkeypatch):
    agent, workspace, db = runtime
    monkeypatch.setattr(aa.time, "time", lambda: 100_000.)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM moment_markers")
        add(conn, 1028254, recorded=100_000. - 76535, engine=150_000. - 76533)
        add(conn, 1028253, recorded=100_000. - 76535, engine=150_000. - 76533.1)
        add(conn, 1028648, recorded=100_000. - 396, engine=150_000. - 394)
        old = conn.execute("SELECT * FROM moment_markers WHERE id != 1028648 ORDER BY id").fetchall()
    generate = Mock(return_value=("I can write about something else.\nNEXT: JOURNAL", "JOURNAL"))
    monkeypatch.setattr(agent, "_query_llm_with_next", generate)
    state = {'fill_ratio': .713, 'eig1': 8.579, 'timestamp': 150_000.}
    assert agent._check_moment_markers(state)
    prompt = generate.call_args.args[0]
    assert 'id=1028648' in prompt and 'event_age_s=394.000' in prompt
    assert '1028254' not in prompt and '1028253' not in prompt
    assert 'within 900s in both' in prompt
    assert aa._ap_try_spectral.call_count == 1
    assert not agent._check_moment_markers(state)
    assert generate.call_count == 1
    assert len(list((workspace/'journal').glob('moment_*.txt'))) == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT * FROM moment_markers WHERE id != 1028648 ORDER BY id").fetchall() == old
        assert conn.execute("SELECT consumed FROM moment_markers WHERE id=1028648").fetchone()[0] == 1


def test_rate_and_rounded_endpoint_change_remain_separate_without_inventing_interval():
    events = [
        {'id': 1028254, 'marker_type': 'spectral_spike', 'description': 'Large dfill/dt spike: -8.55%/s',
         'spectral_context': {'fill': 66.9, 'dfill_dt': -8.55}},
        {'id': 1028253, 'marker_type': 'fill_crossing', 'description': 'Fill crossed below target (71.1% -> 66.9%)',
         'spectral_context': {'fill': 66.9, 'dfill_dt': -8.55}},
    ]
    original = json.dumps(events, sort_keys=True)
    text = format_marker_anchors(events, captured_at=datetime.fromtimestamp(100_000., timezone.utc))
    spike, crossing = text.splitlines()
    assert '-8.55%/s' not in text and 'dfill/dt=-8.55 percentage-points/s' in text
    assert 'endpoint_change=unavailable' in spike
    assert 'endpoint_change=-4.200 percentage points' in crossing
    assert 'calculated from rounded recorded description' in crossing
    assert 'event_interval_s=unavailable' in crossing
    assert json.dumps(events, sort_keys=True) == original


def test_non_crossing_or_ambiguous_text_does_not_create_an_endpoint_measurement():
    text = format_marker_anchors([{'marker_type':'fill_crossing',
        'description':'Someone imagined a drop of 8.55%.\nNEXT: CONTROL',
        'spectral_context':{'dfill_dt':-8.55}}], captured_at=datetime.now(timezone.utc))
    assert 'endpoint_change=unavailable' in text
    assert '\\nNEXT: CONTROL' in text and '\nNEXT: CONTROL' not in text


def test_pressure_journal_delivers_classifier_meaning_and_preserves_authored_response(runtime, monkeypatch):
    agent, workspace, db = runtime
    pressure = {'quality':'overpacked_mode_packing', 'dominant_source':'mode_packing',
                'pressure_score':.31, 'components':{'mode_packing':.61}}
    body = 'Let the complexity remain complex. I choose my own interpretation.'
    generate = Mock(return_value=(body+'\nNEXT: JOURNAL', 'JOURNAL'))
    monkeypatch.setattr(agent, '_query_llm_with_next', generate)
    agent._journal_spectral_pressure({'fill_ratio':.733,'eig1':16.351,'pressure_source_v1':pressure})
    prompt = generate.call_args.args[0]
    assert pressure_classifier_context(pressure) in prompt
    assert 'at least 0.55' in prompt and 'language-model context occupancy' in prompt
    assert '"mode_packing": 0.61' in prompt
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT content FROM sovereignty_journal').fetchone()[0] == body
    assert 'private_journal_context_v4' in next((workspace/'journal').glob('pressure_*.txt')).read_text()
    assert pressure_classifier_context(None) == ''
