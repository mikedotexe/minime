import json

import pytest

from minime_autonomy.study_feedback import StudyFeedback, action_hash, delivery_origin
from minime_autonomy.source_study import StudyClient, SourceStudyPrompt
from unittest.mock import Mock

ORIGIN = {'input_id': 'delivered-input', 'request_sha256': 'a' * 64, 'response_sha256': 'b' * 64}


def test_supersession_survives_restart_without_exposing_private_replacement(tmp_path):
    store = StudyFeedback(tmp_path)
    ident = store.transition('REST', origin=ORIGIN, reason='llm next choice', selection_id='rest-choice')
    private = 'WRITE OBSERVE {"private": "DO_NOT_PUBLISH"}'
    store.transition(private, previous='REST', reason='llm next choice',
                     selection_id='replacement', previous_selection_id=ident)
    text = StudyFeedback(tmp_path).render()
    assert 'superseded' in text and ORIGIN['response_sha256'] in text
    assert action_hash(private) in text
    assert 'DO_NOT_PUBLISH' not in store.path.read_text()
    assert StudyFeedback(tmp_path).load()['pending'] is None


def test_identical_choices_and_late_completion_keep_separate_ids(tmp_path):
    store = StudyFeedback(tmp_path)
    first = store.transition('SELF_STUDY', reason='llm next choice', selection_id='first')
    assert store.transition(None, previous='SELF_STUDY', previous_selection_id=first, reason='honored') == first
    second = store.transition('SELF_STUDY', reason='llm next choice', selection_id='second')
    store.outcome(first, 'needs_choice', 'No new source.', input_id='eof-input', reader=True)
    store.outcome(first, 'completed', 'Host finished.', action_id='first-action')
    saved = store.load()
    assert saved['pending'] == second
    assert saved['records'][0]['reader_outcome']['status'] == 'needs_choice'
    assert saved['records'][1]['status'] == 'queued'
    assert 'needs_choice' in store.render()


def test_receipt_gap_does_not_claim_a_matching_origin(tmp_path):
    store = StudyFeedback(tmp_path)
    store.transition('SELF_STUDY', origin=ORIGIN, reason='llm next choice', selection_id='old')
    consumed = store.transition(None, previous='SELF_STUDY', previous_selection_id='unrecorded-choice', reason='honored')
    assert consumed == 'unrecorded-choice'
    assert store.load()['records'][-1]['origin'] == {}


def test_small_context_budget_does_not_silently_drop_outcome(tmp_path):
    store = StudyFeedback(tmp_path)
    store.transition('REST', origin=ORIGIN, selection_id='one')
    with pytest.raises(ValueError, match='no room'):
        store.render(100)
    assert json.loads(store.path.read_text())['records'][0]['status'] == 'queued'


def test_restoring_same_command_with_a_different_identity_does_not_join_receipts(tmp_path):
    store = StudyFeedback(tmp_path)
    store.transition('SELF_STUDY', origin=ORIGIN, reason='llm next choice', selection_id='old')
    restored = store.transition('SELF_STUDY', previous='SELF_STUDY', reason='state restoration',
                                selection_id='unrecorded', previous_selection_id='unrecorded')
    assert restored == 'unrecorded'
    old, new = store.load()['records']
    assert old['status'] == 'outcome_unknown'
    assert new['origin'] == {}


def test_unrelated_choice_does_not_create_feedback_or_private_context(tmp_path):
    store = StudyFeedback(tmp_path)
    store.transition('WRITE START private topic')
    assert not store.path.exists()
    assert store.render() == ''


def test_older_helper_cannot_execute_bare_question(tmp_path):
    client = StudyClient(tmp_path, tmp_path / 'workspace', executable=tmp_path / 'helper')
    client.call = Mock(return_value={})
    with pytest.raises(RuntimeError, match='was not executed'):
        client.prepare('QUESTION RESOLVE q1')
    client.call.assert_called_once_with(operation='recover_navigation', action='QUESTION RESOLVE q1')


def test_long_choice_is_an_explicit_preview_with_full_identity(tmp_path):
    store = StudyFeedback(tmp_path)
    action = 'SELF_STUDY FIND ' + 'uncertain_source_' * 40
    store.transition(action, selection_id='long-choice')
    record = store.load()['records'][0]
    assert '[preview;' in record['action']
    assert record['action_sha256'] == action_hash(action)


def test_origin_requires_the_current_wire_and_returned_response():
    prompt = SourceStudyPrompt(Mock(), {'text': 'Reader input', 'navigation_id': 'input', 'input_kind': 'map'})
    request = json.dumps({'messages': [{'role': 'user', 'content': str(prompt)}]})
    response = json.dumps({'message': {'content': 'NEXT: REST'}, 'done': True})
    prompt._wire = (request, response)
    prompt.receipt = {'page_id': 'input', 'request_sha256': action_hash(request),
                      'response_sha256': action_hash(response),
                      'choice_feedback': {'selected_next': 'REST'}}
    assert delivery_origin(prompt, 'NEXT: REST')['response_sha256'] == action_hash(response)
    assert delivery_origin(prompt, 'Another response.\nNEXT: REST') is None
    prompt._wire = (request, response + ' ')
    assert delivery_origin(prompt, 'NEXT: REST') is None
