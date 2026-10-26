"""Synthetic finalization faults; never run providers, controls, or live stores."""

from dataclasses import FrozenInstanceError, fields, is_dataclass
import json
from pathlib import Path
import sqlite3

import pytest

from minime_autonomy import reflection_publication as publication
from minime_autonomy.mailbox_fs import Directory
from tests.test_reflection_publication import FILENAME, INPUT, TEXT, retained_delivery


ACTION = "act_finalization_fixture"
PUBLIC_TEXT = "=== INTROSPECTION: synthetic fixture ===\n\n" + TEXT + "\n"
V1 = "minime_reflection_publication_v1"
V2 = "minime_reflection_publication_v2"


class ProcessInterrupted(BaseException):
    """Bypass ordinary error handling to model an interrupted process."""


def make_database(path):
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE sovereignty_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER, timestamp REAL, entry_type TEXT,
            content TEXT, spectral_context TEXT, file_path TEXT)""")


@pytest.fixture
def store(tmp_path):
    workspace = tmp_path.resolve() / "workspace"
    workspace.mkdir()
    database = tmp_path.resolve() / "history.sqlite3"
    make_database(database)
    metadata = {
        "database": str(database),
        "session_id": 23,
        "timestamp": 1792972800.125,
        "entry_type": "introspect",
        "spectral_context": '{"fill_ratio":0.68,"fixture":"original"}',
        "implementation_sha256": "b" * 64,
        "job_id": "job_synthetic_reflection",
    }
    return workspace, database, metadata


def rows(database):
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT * FROM sovereignty_journal ORDER BY id")]


def snapshot(root):
    result = {}
    for path in sorted(root.rglob("*")):
        name = str(path.relative_to(root))
        if path.is_symlink():
            result[name] = ("symlink", str(path.readlink()))
        elif path.is_dir():
            result[name] = ("directory",)
        else:
            info = path.stat()
            result[name] = ("file", path.read_bytes(), info.st_ino, info.st_mtime_ns)
    return result


def begin(store):
    workspace, _, _ = store
    operation = publication.ReflectionPublication.begin(workspace, ACTION, INPUT)
    receipt, artifact = retained_delivery(workspace)
    return operation, receipt, artifact


def finalize(operation, receipt, metadata, **overrides):
    arguments = dict(filename=FILENAME, text=PUBLIC_TEXT, content=TEXT,
                     metadata=metadata, choice="recorded")
    arguments.update(overrides)
    return operation.finalize(receipt, **arguments)


def reopened(store):
    # Opening an existing operation is not permission to generate another turn.
    return publication.ReflectionPublication(store[0], ACTION, INPUT)


def assert_result(result, *, choice="recorded"):
    assert is_dataclass(result) and not isinstance(result, type)
    assert {field.name for field in fields(result)} >= {
        "publication", "indexing", "choice", "reason", "publication_id", "path"}
    assert result.publication == "published"
    assert result.indexing == "indexed"
    assert result.choice == choice
    assert isinstance(result.publication_id, str) and result.publication_id
    assert TEXT not in repr(result) and "NEXT:" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.choice = "unknown"


def assert_single_publication(store, result, *, location=None):
    workspace, database, metadata = store
    expected = location or workspace / "journal" / FILENAME
    assert Path(result.path) == expected
    assert expected.read_bytes() == PUBLIC_TEXT.encode("utf-8")
    assert list((workspace / "journal").rglob(FILENAME)) == [expected]
    recorded = rows(database)
    assert len(recorded) == 1
    row = recorded[0]
    assert row["publication_id"] == result.publication_id
    assert row["content"] == TEXT
    assert row["session_id"] == metadata["session_id"]
    assert row["timestamp"] == metadata["timestamp"]
    assert row["entry_type"] == "introspect"
    assert row["spectral_context"] == metadata["spectral_context"]
    assert row["file_path"] == str(workspace / "journal" / FILENAME)


def interrupt_public_write(monkeypatch, store, *, after=False, choice="recorded"):
    operation, receipt, artifact = begin(store)
    atomic = Directory.atomic
    reached = []

    def interrupt(directory, name, raw, **kwargs):
        if directory.path == store[0] / "journal" and name == FILENAME:
            reached.append(name)
            if after:
                atomic(directory, name, raw, **kwargs)
            raise ProcessInterrupted("synthetic public-write acknowledgement loss")
        return atomic(directory, name, raw, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "atomic", interrupt)
        with pytest.raises(ProcessInterrupted):
            finalize(operation, receipt, store[2], choice=choice)
    assert reached == [FILENAME]
    return operation, receipt, artifact


def assert_unresolved(call):
    try:
        result = call()
    except (ValueError, OSError, sqlite3.Error, publication.RecoveryRequired):
        return
    assert (result.publication, result.indexing) != ("published", "indexed")
    assert result.reason
    assert TEXT not in repr(result)


@pytest.mark.parametrize("choice", ["recorded", "none", "unknown"])
def test_new_finalization_is_v2_frozen_content_free_result(store, choice):
    operation, receipt, _ = begin(store)
    result = finalize(operation, receipt, store[2], choice=choice)
    assert_result(result, choice=choice)
    assert_single_publication(store, result)
    record = json.loads((store[0] / "runtime/reflection_publications" / operation.name).read_bytes())
    assert record["record"]["schema"] == V2


@pytest.mark.parametrize("after", [False, True], ids=["before-public-write", "after-public-write"])
def test_public_write_crash_recovers_frozen_bytes_exactly_once(store, monkeypatch, after):
    interrupt_public_write(monkeypatch, store, after=after)
    public_path = store[0] / "journal" / FILENAME
    assert public_path.exists() is after
    assert rows(store[1]) == []
    before = snapshot(store[0].parent)
    preview = reopened(store).reconcile()
    assert snapshot(store[0].parent) == before
    assert TEXT not in repr(preview)
    result = reopened(store).reconcile(apply=True, database=store[1])
    assert_result(result)
    assert_single_publication(store, result)
    inode = public_path.stat().st_ino
    for _ in range(3):
        repeated = reopened(store).reconcile(apply=True, database=store[1])
        assert_result(repeated)
        assert repeated.publication_id == result.publication_id
        assert_single_publication(store, repeated)
        assert public_path.stat().st_ino == inode


@pytest.mark.parametrize("after", [False, True], ids=["before-ack", "after-ack"])
@pytest.mark.parametrize("boundary", ["intent", "prepared", "published", "indexed"])
def test_durable_receipt_boundaries_recover_only_when_intent_is_sealed(store, monkeypatch, boundary, after):
    operation, receipt, _ = begin(store)
    atomic = Directory.atomic
    reached = []

    def interrupt(directory, name, raw, **kwargs):
        selected = boundary == "intent" and name == operation.intent_name
        if name == operation.name:
            record = json.loads(raw)["record"]
            selected = ((boundary == "prepared" and record["stage"] == "prepared")
                        or (boundary == "published" and record["stage"] == "published"
                            and record["indexing"] == "pending")
                        or (boundary == "indexed" and record.get("indexing") == "indexed"))
        if selected:
            reached.append(boundary)
            if after:
                atomic(directory, name, raw, **kwargs)
            raise ProcessInterrupted("synthetic receipt persistence interruption")
        return atomic(directory, name, raw, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "atomic", interrupt)
        with pytest.raises(ProcessInterrupted):
            finalize(operation, receipt, store[2])
    assert reached == [boundary]
    if boundary == "intent" and not after:
        before = snapshot(store[0].parent)
        assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
        assert snapshot(store[0].parent) == before
        assert rows(store[1]) == []
        return
    first = reopened(store).reconcile(apply=True, database=store[1])
    second = reopened(store).reconcile(apply=True, database=store[1])
    assert_result(first)
    assert_result(second)
    assert first.publication_id == second.publication_id
    assert_single_publication(store, second)
    directory = store[0] / "runtime/reflection_publications"
    for path in (directory / operation.name, directory / operation.index):
        assert TEXT.encode() not in path.read_bytes()
        assert b"NEXT:" not in path.read_bytes()


def test_reentry_recovers_original_frozen_metadata_not_mutated_callers_values(store, monkeypatch):
    original = dict(store[2])
    interrupt_public_write(monkeypatch, store)
    store[2].update(session_id=99, timestamp=0, spectral_context='{"fixture":"newer"}',
                    implementation_sha256="e" * 64, job_id="job_later")
    resumed = publication.ReflectionPublication.begin(store[0], ACTION, INPUT, database=store[1])
    assert resumed.completed
    assert_result(resumed.result)
    assert_single_publication((store[0], store[1], original), resumed.result)
    record = json.loads((store[0] / "runtime/reflection_publications" / resumed.intent_name).read_bytes())["record"]
    assert record["metadata"] == original


@pytest.mark.parametrize("damage", ["truncate", "changed-content", "newer-schema"])
def test_sealed_intent_damage_is_never_reconstructed_from_native_response(store, monkeypatch, damage):
    operation, _, _ = interrupt_public_write(monkeypatch, store)
    path = store[0] / "runtime/reflection_publications" / operation.intent_name
    if damage == "truncate":
        path.write_bytes(path.read_bytes()[:30])
    else:
        intent = json.loads(path.read_bytes())["record"]
        if damage == "changed-content":
            intent["text"] = "A different public text.\n" + intent["text"]
        else:
            intent["schema"] = "minime_reflection_publication_v999"
        path.write_bytes(publication._envelope(intent))
    before = snapshot(store[0].parent)
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert snapshot(store[0].parent) == before


def test_database_commit_acknowledgement_loss_does_not_duplicate_row(store, monkeypatch):
    operation, receipt, _ = begin(store)
    connect = sqlite3.connect
    interrupted = []

    class CommitAckLoss(sqlite3.Connection):
        def lose_ack(self):
            if self.execute("SELECT COUNT(*) FROM sovereignty_journal").fetchone()[0]:
                interrupted.append(True)
                raise ProcessInterrupted("synthetic committed transaction acknowledgement loss")

        def commit(self):
            super().commit()
            self.lose_ack()

        def __exit__(self, exc_type, exc, traceback):
            result = super().__exit__(exc_type, exc, traceback)
            if exc_type is None:
                self.lose_ack()
            return result

    def fault_connection(*args, **kwargs):
        kwargs["factory"] = CommitAckLoss
        return connect(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", fault_connection)
        with pytest.raises(ProcessInterrupted):
            finalize(operation, receipt, store[2])
    assert interrupted == [True]
    original = rows(store[1])
    assert len(original) == 1
    result = reopened(store).reconcile(apply=True, database=store[1])
    assert_result(result)
    assert_single_publication(store, result)
    assert rows(store[1]) == original


def test_database_failure_reports_saved_writing_and_later_recovers_index(store, monkeypatch):
    operation, receipt, _ = begin(store)

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic database unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", unavailable)
        result = finalize(operation, receipt, store[2])
    assert result.publication == "published"
    assert result.indexing != "indexed"
    assert result.reason
    assert (store[0] / "journal" / FILENAME).read_text() == PUBLIC_TEXT
    assert rows(store[1]) == []
    recovered = reopened(store).reconcile(apply=True, database=store[1])
    assert_result(recovered)
    assert_single_publication(store, recovered)


def test_unique_publication_identity_preserves_duplicate_historical_rows(store):
    workspace, database, metadata = store
    original = (metadata["session_id"], metadata["timestamp"], "introspect", TEXT,
                metadata["spectral_context"], str(workspace / "journal/introspect_2026-10-24.txt"))
    with sqlite3.connect(database) as connection:
        connection.executemany("""INSERT INTO sovereignty_journal
            (session_id, timestamp, entry_type, content, spectral_context, file_path)
            VALUES (?, ?, ?, ?, ?, ?)""", [original, original])
    historical = rows(database)
    operation, receipt, _ = begin(store)
    result = finalize(operation, receipt, metadata)
    assert_result(result)
    recovered = reopened(store).reconcile(apply=True, database=database)
    assert_result(recovered)
    recorded = rows(database)
    assert len(recorded) == 3
    assert [{key: row[key] for key in historical[0]} for row in recorded[:2]] == historical
    assert all(row["publication_id"] is None for row in recorded[:2])
    assert recorded[2]["publication_id"] == result.publication_id
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO sovereignty_journal (publication_id) VALUES (?)",
                               (result.publication_id,))


@pytest.mark.parametrize("schema", [
    "missing-table", "missing-columns", "nonunique-index", "wrong-column-index",
    "wrong-predicate-index", "other-table-index",
])
def test_unknown_database_schema_cannot_claim_success_or_modify_existing_rows(store, schema):
    with sqlite3.connect(store[1]) as connection:
        if schema in {"missing-table", "missing-columns"}:
            connection.execute("DROP TABLE sovereignty_journal")
            if schema == "missing-columns":
                connection.execute("CREATE TABLE sovereignty_journal (id INTEGER PRIMARY KEY, content TEXT)")
        else:
            connection.execute("ALTER TABLE sovereignty_journal ADD COLUMN publication_id TEXT")
            if schema == "nonunique-index":
                connection.execute("CREATE INDEX reflection_publication_identity ON sovereignty_journal(publication_id)")
            elif schema == "wrong-column-index":
                connection.execute("CREATE UNIQUE INDEX reflection_publication_identity ON sovereignty_journal(id)")
            elif schema == "wrong-predicate-index":
                connection.execute("CREATE UNIQUE INDEX reflection_publication_identity "
                                   "ON sovereignty_journal(publication_id) WHERE id < 0")
            else:
                connection.execute("CREATE TABLE unrelated_history (publication_id TEXT)")
                connection.execute("CREATE UNIQUE INDEX reflection_publication_identity "
                                   "ON unrelated_history(publication_id)")
    before = store[1].read_bytes()
    operation, receipt, _ = begin(store)
    result = finalize(operation, receipt, store[2])
    assert result.publication == "published"
    assert result.indexing != "indexed"
    assert result.reason
    assert store[1].read_bytes() == before
    assert (store[0] / "journal" / FILENAME).read_text() == PUBLIC_TEXT


def test_native_acceptance_without_frozen_intent_cannot_be_reconstructed(store):
    begin(store)
    before = snapshot(store[0].parent)
    assert reopened(store).reconcile().accepted is None
    assert_unresolved(lambda: reopened(store).reconcile())
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert snapshot(store[0].parent) == before
    assert not (store[0] / "journal" / FILENAME).exists()
    assert rows(store[1]) == []


def test_read_only_wal_preview_never_creates_or_changes_side_files(store):
    operation, receipt, _ = begin(store)
    connection = sqlite3.connect(store[1])
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        assert_result(finalize(operation, receipt, store[2]))
        connection.execute("PRAGMA user_version=1")
        assert Path(str(store[1]) + "-wal").exists()
        before = snapshot(store[0].parent)
        result = reopened(store).reconcile(database=store[1])
        assert result.publication == "published"
        assert result.indexing == "unavailable_live_sqlite_state"
        assert snapshot(store[0].parent) == before
    finally:
        connection.close()
    before = snapshot(store[0].parent)
    assert reopened(store).reconcile(database=store[1]).indexing == "indexed"
    assert snapshot(store[0].parent) == before


def test_preview_of_absent_record_does_not_create_runtime_or_lock(store):
    before = snapshot(store[0].parent)
    assert_unresolved(lambda: reopened(store).reconcile(apply=False))
    assert snapshot(store[0].parent) == before
    assert not (store[0] / "runtime").exists()


@pytest.mark.parametrize("database_selection", ["missing", "different", "relative"])
def test_recovery_requires_exact_explicit_database_authority(store, monkeypatch, database_selection):
    interrupt_public_write(monkeypatch, store)
    other = store[0].parent / "different.sqlite3"
    make_database(other)
    selected = {"missing": None, "different": other, "relative": Path(store[1].name)}[database_selection]
    before = snapshot(store[0].parent)
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=selected))
    assert snapshot(store[0].parent) == before


@pytest.mark.parametrize("after", [False, True])
def test_changed_native_delivery_is_never_used_for_recovery(store, monkeypatch, after):
    _, _, artifact = interrupt_public_write(monkeypatch, store, after=after)
    artifact.write_bytes(artifact.read_bytes() + b"changed evidence")
    before = snapshot(store[0].parent)
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert snapshot(store[0].parent) == before


def test_conflicting_public_bytes_are_not_replaced_or_indexed(store, monkeypatch):
    interrupt_public_write(monkeypatch, store, after=True)
    path = store[0] / "journal" / FILENAME
    path.write_bytes(b"independently edited public writing\n")
    before = path.read_bytes(), store[1].read_bytes()
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert (path.read_bytes(), store[1].read_bytes()) == before
    assert rows(store[1]) == []


@pytest.mark.parametrize("field,value", [
    ("content", "independent database prose"),
    ("session_id", 99),
    ("timestamp", 1.0),
    ("entry_type", "private_writing"),
    ("spectral_context", '{"fixture":"changed"}'),
    ("file_path", "/synthetic/not-the-recorded-publication.txt"),
])
def test_conflicting_database_row_remains_untouched(store, field, value):
    operation, receipt, _ = begin(store)
    result = finalize(operation, receipt, store[2])
    assert_result(result)
    with sqlite3.connect(store[1]) as connection:
        connection.execute(f"UPDATE sovereignty_journal SET {field} = ?", (value,))
    before = store[1].read_bytes(), (store[0] / "journal" / FILENAME).read_bytes()
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert (store[1].read_bytes(), (store[0] / "journal" / FILENAME).read_bytes()) == before
    assert len(rows(store[1])) == 1


@pytest.mark.parametrize("completed", [False, True])
def test_supported_archive_is_found_without_republishing(store, monkeypatch, completed):
    if completed:
        operation, receipt, _ = begin(store)
        finalize(operation, receipt, store[2])
    else:
        interrupt_public_write(monkeypatch, store, after=True)
    live = store[0] / "journal" / FILENAME
    archive = store[0] / "journal/archive/until_2026-10-26" / FILENAME
    archive.parent.mkdir(parents=True)
    live.rename(archive)
    inode = archive.stat().st_ino
    before = snapshot(store[0].parent)
    reopened(store).reconcile(apply=False)
    assert snapshot(store[0].parent) == before
    result = reopened(store).reconcile(apply=True, database=store[1])
    assert_result(result)
    assert_single_publication(store, result, location=archive)
    assert archive.stat().st_ino == inode and not live.exists()


@pytest.mark.parametrize("location", ["missing", "duplicate", "unsupported-archive"])
def test_missing_or_ambiguous_completed_publication_is_not_recreated(store, location):
    operation, receipt, _ = begin(store)
    finalize(operation, receipt, store[2])
    live = store[0] / "journal" / FILENAME
    if location == "missing":
        live.unlink()
    else:
        folder = "until_2026-10-26" if location == "duplicate" else "unrecognized"
        archive = store[0] / "journal/archive" / folder / FILENAME
        archive.parent.mkdir(parents=True)
        if location == "duplicate":
            archive.write_bytes(live.read_bytes())
        else:
            live.rename(archive)
    before = snapshot(store[0].parent)
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert snapshot(store[0].parent) == before


@pytest.mark.parametrize("choice", ["recorded", "none", "unknown"])
@pytest.mark.parametrize("pending", [None, "REST"], ids=["consumed", "superseded"])
def test_recovery_leaves_consumed_or_superseded_choice_and_private_stores_alone(store, monkeypatch, choice, pending):
    workspace = store[0]
    sentinels = {
        "sovereignty_state.json": json.dumps({
            "pending_next_action": pending,
            "pending_next_action_status": "cleared" if pending is None else "pending",
            "pending_next_selection_id": None if pending is None else "newer-selection",
            "pending_next_action_cleared": "INTROSPECT",
            "cycle_count": 42,
        }),
        "action_threads/threads/synthetic/next.md": "A newer choice governs this thread.\n",
        "private_writing/journal/draft.txt": "Synthetic private draft, not a publication source.\n",
        "private_writing/state.json": '{"parked":true,"draft_id":"synthetic"}',
        "diagnostics/source_first_v3/shared_reader/writing/drafts-v2.json": '{"synthetic":"parked"}',
        "runtime/action_continuity.jsonl": '{"action_id":"older","status":"failed"}\n',
        "llm_jobs/jobs/job_synthetic_reflection/job.json": '{"status":"failed","historical":true}',
    }
    for name, text in sentinels.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    before = {name: (workspace / name).read_bytes() for name in sentinels}
    interrupt_public_write(monkeypatch, store, choice=choice)
    for _ in range(2):
        result = reopened(store).reconcile(apply=True, database=store[1])
        assert_result(result, choice=choice)
        assert_single_publication(store, result)
    assert {name: (workspace / name).read_bytes() for name in sentinels} == before
    assert sorted(path.relative_to(workspace / "private_writing").as_posix()
                  for path in (workspace / "private_writing").rglob("*") if path.is_file()) == [
        "journal/draft.txt", "state.json"]


@pytest.mark.parametrize("field", ["page_id", "artifact_sha256", "request_sha256", "response_sha256"])
def test_false_native_receipt_never_publishes_or_indexes(store, field):
    operation, receipt, artifact = begin(store)
    false_receipt = dict(receipt, **{field: "f" * 64})
    before = artifact.read_bytes(), store[1].read_bytes()
    assert_unresolved(lambda: finalize(operation, false_receipt, store[2]))
    assert (artifact.read_bytes(), store[1].read_bytes()) == before
    assert not (store[0] / "journal" / FILENAME).exists()


@pytest.mark.parametrize("kind", ["unreadable", "invalid-json", "unknown-schema"])
def test_unreadable_or_unknown_receipt_is_preserved(store, monkeypatch, kind):
    operation, _, _ = interrupt_public_write(monkeypatch, store)
    record_path = store[0] / "runtime/reflection_publications" / operation.name
    if kind == "invalid-json":
        record_path.write_bytes(b'{"unreadable":')
    elif kind == "unknown-schema":
        record = json.loads(record_path.read_bytes())["record"]
        record["schema"] = "minime_reflection_publication_v999"
        record_path.write_bytes(publication._envelope(record))
    before = snapshot(store[0].parent)
    read = Directory.read

    def unreadable(directory, name, limit):
        if kind == "unreadable" and name == operation.name:
            raise PermissionError("synthetic unreadable receipt")
        return read(directory, name, limit)

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "read", unreadable)
        assert_unresolved(lambda: reopened(store).reconcile())
        assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert snapshot(store[0].parent) == before


@pytest.mark.parametrize("field,value", [
    ("database", False),
    ("database", "relative.sqlite3"),
    ("session_id", False),
    ("timestamp", False),
    ("timestamp", float("nan")),
    ("timestamp", float("inf")),
    ("entry_type", "private_writing"),
    ("spectral_context", "not JSON"),
    ("implementation_sha256", "not-a-hash"),
])
def test_false_or_invalid_metadata_never_publishes(store, field, value):
    operation, receipt, _ = begin(store)
    metadata = dict(store[2], **{field: value})
    with pytest.raises((ValueError, TypeError, OSError)):
        finalize(operation, receipt, metadata)
    assert not (store[0] / "journal" / FILENAME).exists()
    assert rows(store[1]) == []


@pytest.mark.parametrize("filename", ["../outside.txt", "/tmp/introspect_1.txt", "private_writing/draft.txt", "introspect_1.txt\0"])
def test_unsafe_filename_never_publishes(store, filename):
    operation, receipt, _ = begin(store)
    before = snapshot(store[0].parent)
    with pytest.raises((ValueError, TypeError, OSError)):
        finalize(operation, receipt, store[2], filename=filename)
    assert snapshot(store[0].parent) == before


@pytest.mark.parametrize("kind", ["file-symlink", "ancestor-symlink", "parent-traversal"])
def test_unsafe_database_path_is_not_followed(store, kind):
    operation, receipt, _ = begin(store)
    directory = store[0].parent
    if kind == "file-symlink":
        unsafe = directory / "alias.sqlite3"
        unsafe.symlink_to(store[1])
    elif kind == "ancestor-symlink":
        alias = directory / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        unsafe = alias / store[1].name
    else:
        unsafe = store[0] / ".." / store[1].name
    metadata = dict(store[2], database=str(unsafe))
    before = store[1].read_bytes()
    assert_unresolved(lambda: finalize(operation, receipt, metadata))
    assert store[1].read_bytes() == before
    assert not (store[0] / "journal" / FILENAME).exists()


def test_symlinked_journal_cannot_redirect_publication_into_private_writing(store):
    operation, receipt, _ = begin(store)
    private = store[0] / "private_writing/journal"
    private.mkdir(parents=True)
    (private / "draft.txt").write_text("Synthetic private draft.\n")
    (store[0] / "journal").symlink_to(private, target_is_directory=True)
    before = snapshot(private), store[1].read_bytes()
    assert_unresolved(lambda: finalize(operation, receipt, store[2]))
    assert (snapshot(private), store[1].read_bytes()) == before


def write_v1_fixture(store, stage):
    workspace = store[0]
    receipt, _ = retained_delivery(workspace)
    directory = workspace / "runtime/reflection_publications"
    directory.mkdir(parents=True)
    action_file = "action-" + publication._sha(ACTION.encode()) + ".json"
    binding = {"owner": "minime", "action_id": ACTION, "input_id": INPUT, "nonce": "c" * 32}
    record = {"schema": V1, "binding": binding, "stage": stage}
    if stage != "reserved":
        record["delivery"] = {key: receipt[key] for key in (
            "artifact_sha256", "request_sha256", "response_sha256")}
    if stage in {"publishing", "published", "completed"}:
        record["publication"] = {"filename": FILENAME, "sha256": publication._sha(PUBLIC_TEXT.encode())}
    if stage in {"published", "completed"}:
        (workspace / "journal").mkdir()
        (workspace / "journal" / FILENAME).write_text(PUBLIC_TEXT)
    (directory / action_file).write_bytes(publication._envelope(record))
    (directory / ("input-" + INPUT + ".json")).write_bytes(publication._envelope({
        "schema": V1, "action_file": action_file,
        "binding_sha256": publication._sha(publication._bytes(binding))}))
    # Existing lock presence is not evidence of migration or recovery authority.
    (directory / ".transaction.lock").touch()


@pytest.mark.parametrize("stage", ["reserved", "accepted", "publishing", "published", "completed"])
def test_v1_evidence_is_readable_but_never_migrated_or_automatically_completed(store, stage):
    write_v1_fixture(store, stage)
    before = snapshot(store[0].parent)
    if stage == "reserved":
        assert reopened(store).reconcile().accepted is None
    if stage == "completed":
        operation = publication.ReflectionPublication.begin(store[0], ACTION, INPUT)
        assert operation.completed
    else:
        with pytest.raises(publication.RecoveryRequired):
            publication.ReflectionPublication.begin(store[0], ACTION, INPUT)
    assert_unresolved(lambda: reopened(store).reconcile(apply=False))
    assert_unresolved(lambda: reopened(store).reconcile(apply=True, database=store[1]))
    assert snapshot(store[0].parent) == before
    assert rows(store[1]) == []
