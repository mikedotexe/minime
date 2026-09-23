"""Synthetic real-adapter qualification; no provider or live writes."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.expressive_journal import expression_invitation, save_expression
from minime_autonomy.measurement_history import format_fill_history
from tests.test_journal_context import runtime


@pytest.mark.parametrize("kind", ["aspiration", "daydream", "rest"])
def test_complete_expression_adapter_omits_ambient_metrics_and_preserves_output(runtime, monkeypatch, kind):
    agent, workspace, db = runtime
    state = {"fill_ratio": .68, "eig1": 5., "timestamp": 100., "nested": {"value": 7}}
    prior = "I chose this observation: 0.90.\nNEXT: REST"
    response = "My own passage.\n\nI disagree with the framing.\nNEXT: REST"
    monkeypatch.setattr(agent, "_last_journal_entry", lambda: prior)
    for method in ("_journal_continuity_contract_v1", "_neutral_checkin", "_read_whisper_context",
                   "_low_fill_prompt_guidance", "_reservoir_prompt_context"):
        monkeypatch.setattr(agent, method, Mock(side_effect=AssertionError(method)))
    captured = {}
    def generate(prompt, system, *args, **kwargs):
        captured.update(prompt=prompt, system=system)
        state["fill_ratio"] = .90
        state["nested"]["value"] = 9
        return response
    monkeypatch.setattr(agent, "_query_llm_raw", generate)
    monkeypatch.setattr(agent, "_format_metrics", lambda state, **kwargs: "All measured fields: late fixture")
    saved = Mock()
    monkeypatch.setattr(agent, "_write_journal_entry", saved)
    method = "_journal_rest_reflection" if kind == "rest" else "_recess_" + kind
    getattr(agent, method)(state)
    assert captured["prompt"].count(prior) == 1
    for absent in ("68.0", "Current native lane", "Continuity posture:", "Delta:", "Your body's readings"):
        assert absent not in captured["prompt"]
    assert "FACULTIES / CAPABILITY_MAP" in captured["system"]
    assert "SPECTRAL_EXPLORER" in captured["system"]
    assert "CONCRETE" not in captured["system"]
    assert "CORRESPONDENCE_MICRODOSE_REQUEST" not in captured["system"]
    assert len(captured["system"]) < 6000
    path = next((workspace / "journal").glob("*.txt"))
    document = path.read_text()
    assert document.split("\n\n", 1)[1] == response + "\n"
    stamp = document.splitlines()[1].removeprefix("Timestamp: ")
    assert datetime.fromisoformat(stamp)
    assert stamp.replace(":", "-") in path.name
    metadata = json.loads(next((workspace / "journal_metadata").glob("*.json")).read_text())
    assert metadata["document_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert metadata["state_at_invitation_not_supplied"]["snapshot"]["state"]["nested"] == {"value": 7}
    assert metadata["post_generation_observation_not_generation_input"]["snapshot"]["state"]["nested"] == {"value": 9}
    assert metadata["invitation"]["automatic_telemetry_supplied"] is False
    assert saved.call_args.args[:2] == ("reflection" if kind == "rest" else kind, response)


def test_invitation_keeps_explicit_form_and_history_exact_without_metrics():
    passage = 'Keep "Delta:" as a word I chose.\n0.123 is my observation.'
    text = expression_invitation("aspiration", form="a plain list", prior=passage)
    assert passage in text and "a plain list" in text
    assert "Include one" not in text and "fill=" not in text


@pytest.mark.parametrize("kind", ["aspiration", "daydream", "rest"])
def test_later_state_refresh_is_archival_not_generation_input(runtime, monkeypatch, kind):
    agent, workspace, _ = runtime
    monkeypatch.setattr(agent, "_query_llm_with_next", Mock(return_value=("Exact prose", None)))
    refresh = Mock(return_value={"timestamp": 150., "fill_ratio": .71})
    monkeypatch.setattr(agent, "_state_for_live_surfaces", refresh)
    monkeypatch.setattr(agent, "_write_journal_entry", Mock())
    method = "_journal_rest_reflection" if kind == "rest" else "_recess_" + kind
    getattr(agent, method)({"timestamp": 100., "fill_ratio": .68})
    refresh.assert_called_once()
    data = json.loads(next((workspace / "journal_metadata").glob("*.json")).read_text())
    assert data["state_at_invitation_not_supplied"]["snapshot"]["state"]["timestamp"] == 100.
    assert data["post_generation_observation_not_generation_input"]["snapshot"]["state"]["timestamp"] == 150.


def test_failed_provider_creates_no_expression_record(runtime, monkeypatch):
    agent, workspace, _ = runtime
    monkeypatch.setattr(agent, "_query_llm_with_next", Mock(return_value=(None, None)))
    agent._recess_aspiration({})
    assert not list((workspace / "journal").glob("*.txt"))
    assert not (workspace / "journal_metadata").exists()


def test_metadata_failure_preserves_prose_and_does_not_overwrite(tmp_path):
    directory = tmp_path / "journal"
    directory.mkdir()
    (tmp_path / "journal_metadata").write_text("foreign file")
    path = directory / "aspiration_fixture.txt"
    args = dict(title="GROWTH ASPIRATION", timestamp="fixture", response="Exact prose",
                invitation="Invitation", before={}, after={}, metrics="measured")
    assert save_expression(path, **args)
    before = path.read_bytes()
    assert b"Exact prose" in before
    with pytest.raises(FileExistsError):
        save_expression(path, **args)
    assert path.read_bytes() == before
    assert (tmp_path / "journal_metadata").read_text() == "foreign file"


@pytest.mark.parametrize("samples,reference,expected", [
    ([], 10, "no recorded samples"),
    ([(1, 60)], 5, "interval/change unavailable"),
    ([(1, 60), (2, 61), (10, 62)], 14, "largest_between_sample_gap=8.000s"),
    ([(1, 60), (1, 61)], 5, "duplicate, regressed or future"),
    ([(1, 60), (0, 61)], 5, "duplicate, regressed or future"),
    ([(1, 60), (6, 61)], 5, "duplicate, regressed or future"),
    ([(1, float("nan"))], 5, "invalid sample"),
    ([(1, 10 ** 1000)], 5, "invalid sample"),
    ([(1, -1e308), (2, 1e308)], 5, "nonfinite interval or difference"),
    ([(1, 60)], None, "reference clock unknown"),
])
def test_history_reports_actual_span_gaps_and_unknowns(samples, reference, expected):
    before = deepcopy(samples)
    text = format_fill_history(samples, reference_time=reference, clock="fixture")
    assert expected in text
    assert "not continuous coverage" in text
    if len(samples) == 3:
        assert "span=9.000s" in text and "latest_gap_to_reference=4.000s" in text
        assert "endpoint_change=+2.000 percentage points" in text
    assert repr(samples) == repr(before)
