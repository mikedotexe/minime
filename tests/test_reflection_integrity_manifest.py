"""Explicit public samples and sealed publication evidence stay read-only."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import reflection_integrity_audit as audit
from tests.test_reflection_integrity_audit import RUNTIME, synthetic_evidence


def seal(record):
    raw = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return json.dumps({"record": record, "sha256": audit.sha(raw)}).encode()


def selected(tmp_path):
    root, journal, job, delivery = synthetic_evidence(tmp_path)
    value = json.loads((root / job).read_bytes())
    value["action_id"] = "act_synthetic"
    (root / job).write_text(json.dumps(value))
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    row = audit.audit_entry(root, journal, job, delivery, clean, strip)
    intent = f"runtime/reflection_publications/intent-{audit.sha('act_synthetic')}.json"
    record = {"schema": "minime_reflection_publication_v2",
              "binding": {"owner": "minime", "action_id": "act_synthetic",
                          "input_id": row["navigation_id"], "nonce": "a" * 32},
              "publication": {"filename": Path(journal).name, "sha256": row["journal_sha256"]},
              "delivery": {"artifact_sha256": row["delivery_sha256"],
                           "request_sha256": row["request_sha256"], "response_sha256": row["response_sha256"]},
              "text": (root / journal).read_text(), "content": audit.authored_public((root / journal).read_bytes()),
              "metadata": {"job_id": row["job_id"], "entry_type": "introspect", "implementation_sha256": "b" * 64},
              "choice": "unknown"}
    (root / intent).parent.mkdir(parents=True)
    (root / intent).write_bytes(seal(record))
    references = {"schema": audit.EXPLICIT_POLICY, "entries": [
        {"journal": journal, "job": job, "delivery": delivery, "publication_intent": intent}]}
    return root, references, record


def test_explicit_sample_roundtrip_is_content_free_and_read_only(tmp_path, monkeypatch):
    root, references, _ = selected(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    allowed = set(before) | {RUNTIME}
    original = audit.read

    def read(path):
        assert path in allowed
        return original(path)

    monkeypatch.setattr(audit, "read", read)
    monkeypatch.setattr(Path, "glob", Mock(side_effect=AssertionError("no discovery")))
    monkeypatch.setattr(Path, "write_bytes", Mock(side_effect=AssertionError("no writes")))
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=AssertionError("no writes")))
    frozen = audit.freeze_sample(root, RUNTIME, references)
    checked = audit.audit_frozen(root, RUNTIME, frozen)
    assert checked == frozen
    evidence = frozen['entries'][0]['publication_evidence']
    assert evidence['status'] == 'verified'
    assert evidence['implementation_sha256'] == 'b' * 64
    assert 'Synthetic opening' not in json.dumps(frozen)
    assert 'NEVER EXPORT' not in json.dumps(frozen)
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize('field,value', [
    ('schema', 'unsupported'), ('binding.owner', 'astrid'), ('binding.input_id', 'different'),
    ('metadata.job_id', 'another_job'), ('publication.filename', 'introspect_other.txt'),
    ('delivery.request_sha256', '0' * 64), ('text', 'altered'), ('content', 'altered'),
])
def test_resealed_identity_or_bytes_conflict_refused(tmp_path, field, value):
    root, references, record = selected(tmp_path)
    target = record
    parts = field.split('.')
    for key in parts[:-1]:
        target = target[key]
    target[parts[-1]] = value
    (root / references['entries'][0]['publication_intent']).write_bytes(seal(record))
    with pytest.raises(ValueError):
        audit.freeze_sample(root, RUNTIME, references)


def test_seal_and_frozen_intent_drift_refused(tmp_path):
    root, references, record = selected(tmp_path)
    frozen = audit.freeze_sample(root, RUNTIME, references)
    path = root / references['entries'][0]['publication_intent']
    altered = json.loads(path.read_bytes())
    altered['sha256'] = '0' * 64
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match='sealed'):
        audit.audit_frozen(root, RUNTIME, frozen)
    record['metadata']['implementation_sha256'] = 'c' * 64
    path.write_bytes(seal(record))
    with pytest.raises(ValueError, match='drift'):
        audit.audit_frozen(root, RUNTIME, frozen)


def test_missing_and_unselected_intent_are_distinct_and_absence_is_bound(tmp_path):
    root, references, _ = selected(tmp_path)
    path = root / references['entries'][0]['publication_intent']
    retained = path.read_bytes()
    path.unlink()
    frozen = audit.freeze_sample(root, RUNTIME, references)
    assert frozen['entries'][0]['publication_evidence']['status'] == 'missing'
    assert audit.audit_frozen(root, RUNTIME, frozen) == frozen
    path.write_bytes(retained)
    with pytest.raises(ValueError, match='drift'):
        audit.audit_frozen(root, RUNTIME, frozen)
    del references['entries'][0]['publication_intent']
    assert audit.freeze_sample(root, RUNTIME, references)['entries'][0]['publication_evidence']['status'] == 'not_supplied'


@pytest.mark.parametrize('count', [0, 21])
def test_bounded_explicit_manifest(count):
    with pytest.raises(ValueError, match='one to twenty'):
        audit.sample_references({'schema': audit.EXPLICIT_POLICY, 'entries': [{}] * count})


def test_duplicate_or_private_references_refused(tmp_path):
    root, references, _ = selected(tmp_path)
    row = references['entries'][0]
    with pytest.raises(ValueError, match='distinct'):
        audit.sample_references({**references, 'entries': [row, row]})
    for name in ['private_writing/journal/intent.json', '../runtime/intent.json']:
        row['publication_intent'] = name
        with pytest.raises(ValueError, match='outside selected'):
            audit.freeze_sample(root, RUNTIME, references)


def test_intent_rechecked_after_read(tmp_path, monkeypatch):
    root, references, _ = selected(tmp_path)
    path = root / references['entries'][0]['publication_intent']
    original = audit.read
    reads = 0

    def changed(selected_path):
        nonlocal reads
        raw = original(selected_path)
        if selected_path == path:
            reads += 1
            if reads == 2:
                return raw + b' '
        return raw

    monkeypatch.setattr(audit, 'read', changed)
    with pytest.raises(ValueError, match='changed across'):
        audit.freeze_sample(root, RUNTIME, references)


def test_frozen_october_27_sample_has_exact_public_linkage():
    path = Path(__file__).resolve().parents[1] / 'docs/evidence/2026-10-27-public-reflection-integrity.json'
    raw = path.read_bytes()
    assert audit.sha(raw) == 'dd188d88e9342c7d9df14dd3efb2cb14e36938e3577695fdf590fdac1084763e'
    frozen = audit.strict_json(raw)
    rows = audit.sample_references(frozen)
    assert len(rows) == frozen['sample_count'] == 20
    for row in rows:
        assert row['publication_evidence']['status'] == 'verified'
        assert row['provider_content_matches_visible']
        assert row['provider_visible_sha256'] == row['cleanup_sha256'] == row['published_sha256']
        assert row['attempt_count'] == 1 and row['completion_reason'] == 'stop'
        assert row['publication_intent'].endswith(audit.sha(row['action_id']) + '.json')
        assert not {'text', 'content', 'thinking', 'request_json', 'response_json'}.intersection(row)
