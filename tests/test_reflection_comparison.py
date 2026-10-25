"""Synthetic assets only. All process, signal and network boundaries are mocked."""
import base64
from collections import Counter
import copy
from http.client import IncompleteRead, RemoteDisconnected
import io
import json
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import pytest

from scripts import reflection_comparison as r


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("test attempted an unmocked process, signal or network call")
    for name in ("run", "Popen", "check_output"):
        monkeypatch.setattr(r.subprocess, name, forbidden)
    monkeypatch.setattr(r.socket, "socket", forbidden)
    monkeypatch.setattr(r.os, "killpg", forbidden)
    monkeypatch.setattr(r, "HTTPConnection", forbidden)


@pytest.fixture
def assets(tmp_path, monkeypatch):
    tmp_path = tmp_path.resolve()
    old, new, provider = [tmp_path / name for name in ("old-helper", "new-helper", "provider")]
    for path in (old, new, provider):
        r.save_bytes(path, path.name.encode())
    models = tmp_path / "models"
    (models / "blobs").mkdir(parents=True)
    blob = b"synthetic weights, not executable"
    sha = r.digest(blob)
    r.save_bytes(models / "blobs" / ("sha256-" + sha), blob)
    manifest = {"schemaVersion": 2, "config": {"digest": "sha256:" + sha,
                "size": len(blob), "mediaType": "synthetic/config"}, "layers": []}
    (models / r.MANIFEST).parent.mkdir(parents=True)
    # Deliberately noncanonical whitespace to exercise exact-byte copying.
    r.save_bytes(models / r.MANIFEST, json.dumps(manifest, indent=3).encode())
    rubric = tmp_path / "rubric-source.md"
    r.save_bytes(rubric, b"Blind rubric; length and topic are not success criteria.\n")
    monkeypatch.setattr(r, "RUBRIC", rubric)
    monkeypatch.setattr(r, "helper_frame", lambda path: {"text": path.name + " reflection",
                        "system_prompt": path.name + " system", "evidence_scope": path.name})
    return SimpleNamespace(old=old, new=new, models=models, provider=provider, root=tmp_path)


def freeze(assets, name="packet", **kwargs):
    out = assets.root / name
    packet = r.freeze(assets.old, assets.new, assets.models, assets.provider, out, **kwargs)
    return out, packet, r.file_hash(out / "packet.json")


def completion(**changes):
    return {"model": r.MODEL, "done": True, "done_reason": "stop", "eval_count": 755,
            "message": {"role": "assistant", "content": "Synthetic retained text."}, **changes}


@pytest.fixture
def execution(monkeypatch):
    calls, stops, kills, handlers = [], [], [], {}
    process = Mock(pid=987654, returncode=None)
    process.poll.return_value = None
    monkeypatch.setattr(r.subprocess, "Popen", Mock(return_value=process))
    reservation = MagicMock()
    reservation.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 23456)
    monkeypatch.setattr(r.socket, "socket", Mock(return_value=reservation))
    monkeypatch.setattr(r, "free_percent", lambda: 50)
    monkeypatch.setattr(r, "probe_sandbox", Mock())
    monkeypatch.setattr(r, "verify_listener", Mock())
    monkeypatch.setattr(r.Guard, "start", lambda self: None)
    monkeypatch.setattr(r, "signal_group", lambda pid, sig: kills.append((pid, sig)) or True)
    def stop(proc):
        stops.append(proc.pid)
        proc.returncode = 0
        return True
    monkeypatch.setattr(r, "stop_owned", stop)
    def install(sig, handler):
        previous = handlers.get(sig, signal.SIG_DFL)
        handlers[sig] = handler
        return previous
    monkeypatch.setattr(r.signal, "signal", install)
    state = SimpleNamespace(calls=calls, stops=stops, kills=kills, process=process,
                            handlers=handlers, outcome=lambda: completion())
    def http(port, path, payload=None, **kwargs):
        if path != "/api/chat":
            return {"synthetic": True}
        calls.append(copy.deepcopy(payload))
        return state.outcome()
    monkeypatch.setattr(r, "http", http)
    return state


def test_literal_schedule_and_approved_policy():
    cells = [0, 1, 3, 2, 1, 3, 2, 0, 3, 2, 0, 1, 2, 0, 1, 3, 0, 1, 3, 2, 2, 3, 1, 0]
    blinds = [4, 2, 5, 9, 17, 11, 10, 21, 22, 6, 1, 20, 16, 23, 18, 12, 24, 3, 15, 19, 7, 8, 13, 14]
    expected = [{"cell": cell, "seed": [7, 17, 29, 43, 61, 7][i // 4], "repeat": i >= 20,
                 "id": f"job-{i+1:02d}", "blind_id": f"sample-{blinds[i]:02d}"} for i, cell in enumerate(cells)]
    assert r.schedule() == expected
    assert Counter(j["cell"] for j in expected) == {0: 6, 1: 6, 2: 6, 3: 6}
    assert r.OPTIONS == {"temperature": .7, "top_p": .95, "num_predict": 4096, "num_ctx": 65536}
    assert r.RESOURCE_POLICY == {"max_owned_rss_bytes": 14*1024**3, "min_system_free_percent": 13,
        "launch_free_percent": 20, "deadline_seconds": 1800, "one_active_generation": True, "hard_allocation_cap": False}


def test_sandbox_read_allowlist_and_explicit_localhost_exception(tmp_path):
    provider = Path("/Applications/Ollama.app/Contents/Resources/ollama")
    blob = tmp_path / "model-assets/blob"
    root = tmp_path / "output"
    profile = r.sandbox_profile(root, [blob], 23456, provider)
    assert "(deny file-read*)" in profile and "(deny file-write*)" in profile
    assert "(deny network*)" in profile
    assert '(literal "/")' in profile and '(subpath "/")' not in profile
    assert f'(literal "{blob}")' in profile
    assert f'(subpath "{blob.parent}")' not in profile
    for path in ("/Users", "/Users/v", "/private/var", str(tmp_path)):
        assert f'(subpath "{path}")' not in profile
    assert f'(subpath "{provider.parent}")' in profile
    for port in r.PROTECTED_PORTS:
        assert f'(remote ip "localhost:{port}")' in profile
        assert f'(local ip "localhost:{port}")' in profile
    assert "Unlisted localhost services remain reachable" in profile
    helper = r.sandbox_profile(root, [], None, provider, network=False)
    assert "(allow network" not in helper
    with pytest.raises(ValueError, match="protected"):
        r.sandbox_profile(root, [blob], 11434, provider)


def test_freeze_load_rubric_and_exact_manifest(assets, execution):
    out, packet, sha = freeze(assets)
    assert r.load_packet(out, sha) == packet
    assert packet["rubric"]["sha256"] == r.file_hash(out / "rubric.md")
    r.execute(out, sha)
    assert len(execution.calls) == 24 and execution.stops == [execution.process.pid]
    assert r.read_bytes(out / "isolated-home/models" / r.MANIFEST) == r.read_bytes(assets.models / r.MANIFEST)
    assert r.read_json(out / "summary.json")["completed"] == 24
    assert r.read_json(out / "resource-receipt.json")["owned_group_empty"] is True
    assert all(call["options"] == r.OPTIONS | {"seed": job["seed"]}
               for call, job in zip(execution.calls, packet["jobs"]))
    with pytest.raises(ValueError, match="already attempted"):
        r.execute(out, sha)


@pytest.mark.parametrize("key,value", [("model", "other"), ("think", True), ("seeds", [7]),
                                      ("jobs", []), ("cells", []), ("options", {})])
def test_invalid_design_refused(assets, key, value):
    _, packet, _ = freeze(assets)
    packet[key] = value
    with pytest.raises(ValueError):
        r.validate_design(packet)


def test_packet_digest_and_cell_conflict_refused(assets):
    out, packet, sha = freeze(assets)
    with pytest.raises(ValueError, match="pinned digest"):
        r.load_packet(out, "0"*64)
    packet["cells"][0]["messages"][1]["content"] += "changed"
    with pytest.raises(ValueError, match="notice"):
        r.validate_design(packet)
    (out / "packet.json").write_bytes(r.encoded(packet))
    with pytest.raises(ValueError, match="pinned digest"):
        r.load_packet(out, sha)


@pytest.mark.parametrize("kind", ["provider", "helper", "manifest", "blob", "rubric"])
def test_changed_asset_refused(assets, kind):
    out, packet, sha = freeze(assets)
    path = {"provider": assets.provider, "helper": assets.old, "manifest": assets.models / r.MANIFEST,
            "blob": assets.models / "blobs" / next(iter(packet["model_blobs"])), "rubric": out / "rubric.md"}[kind]
    path.write_bytes(b"changed synthetic asset")
    with pytest.raises(ValueError):
        r.load_packet(out, sha)


@pytest.mark.parametrize("response", [{"done": False}, completion(done=False), completion(done_reason="unknown"),
    completion(model="other"), completion(message={"role": "assistant", "content": None}),
    completion(error="failure"), completion(error=None),
    completion(message={"role": "user", "content": "wrong role"})])
def test_incomplete_response_retained_and_stops(assets, execution, response):
    out, _, sha = freeze(assets)
    execution.outcome = lambda: response
    with pytest.raises(ValueError, match="completion"):
        r.execute(out, sha)
    assert len(execution.calls) == 1
    result = r.read_json(out / "job-01-result.json")
    assert result["completed"] is False and result["response"] == response
    assert result["request_sha256"] == r.file_hash(out / "job-01-request.json")
    assert (out / "failure.json").exists() and not (out / "summary.json").exists()
    assert execution.stops


@pytest.mark.parametrize("reason,text", [("stop", "A line."), ("length", "Unfinished thought"),
                                        ("stop", ""), ("stop", " \n"), ("length", "")])
def test_terminal_length_and_silence_remain_in_fixed_sample(assets, execution, reason, text):
    out, _, sha = freeze(assets)
    response = completion(done_reason=reason, message={"role": "assistant", "content": text})
    execution.outcome = lambda: response
    r.execute(out, sha)
    assert len(execution.calls) == 24 and not (out / "failure.json").exists()
    expected = {"protocol_terminal": True, "natural_ending": reason == "stop",
                "ceiling_limited": reason == "length", "text_incomplete": reason == "length",
                "empty_text": not text.strip()}
    for job in r.schedule():
        record = r.read_json(out / (job["id"] + "-result.json"))
        assert record["completed"] is True and record["response"] == response
        assert {key: record[key] for key in expected} == expected
    for item in r.read_json(out / "blind-review.json"):
        assert item["text"] == text and {key: item[key] for key in expected} == expected
    summary = r.read_json(out / "summary.json")
    assert summary["completed"] == summary["protocol_terminal"] == 24
    assert summary["natural_endings"] == (24 if reason == "stop" else 0)
    assert summary["ceiling_limited"] == (24 if reason == "length" else 0)
    assert summary["empty_stops"] == (24 if reason == "stop" and not text.strip() else 0)
    assert summary["completion_reasons"] == {reason: 24}
    for repeat in summary["seed_repeats"]:
        assert repeat["exact_text_match"] is True
        assert repeat["empty_pair_trivial"] is (not text.strip())
        assert repeat["nonempty_exact_text_match"] is bool(text.strip())


@pytest.mark.parametrize("error", [KeyboardInterrupt(), RemoteDisconnected("operator stop"), RuntimeError("failure")])
def test_interruption_and_transport_failure_retained(assets, execution, error):
    out, _, sha = freeze(assets)
    def outcome():
        raise error
    execution.outcome = outcome
    with pytest.raises(type(error)):
        r.execute(out, sha)
    assert r.read_json(out / "job-01-result.json")["error_type"] == type(error).__name__
    assert r.read_json(out / "failure.json")["attempted"] == 1
    assert r.read_json(out / "resource-receipt.json")["owned_group_empty"]


def test_sigterm_retains_attempt_and_restores_handlers(assets, execution):
    out, _, sha = freeze(assets)
    def outcome():
        execution.handlers[signal.SIGTERM](signal.SIGTERM, None)
        return completion()
    execution.outcome = outcome
    with pytest.raises(r.RunInterrupted):
        r.execute(out, sha)
    assert r.read_json(out / "job-01-result.json")["completed"] is False
    assert r.read_json(out / "resource-receipt.json")["interruption_signals"] == [signal.SIGTERM]
    assert execution.handlers[signal.SIGTERM] == signal.SIG_DFL
    assert execution.kills == [(execution.process.pid, signal.SIGKILL)]


def test_monotonic_deadline_rejects_late_success(assets, execution, monkeypatch):
    out, _, sha = freeze(assets)
    now = [0.0]
    monkeypatch.setattr(r.time, "monotonic", lambda: now[0])
    def outcome():
        now[0] += 1801
        return completion()
    execution.outcome = outcome
    with pytest.raises(RuntimeError, match="wall deadline"):
        r.execute(out, sha)
    assert len(execution.calls) == 1 and execution.kills
    assert r.read_json(out / "job-01-result.json")["completed"] is False


def test_cleanup_escalates_after_leader_exit(monkeypatch):
    process = Mock(pid=12345)
    process.poll.return_value = 0
    now, alive, signals = [0.0], [True], []
    monkeypatch.setattr(r.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(r.time, "sleep", lambda _: now.__setitem__(0, now[0] + r.STOP_TIMEOUT))
    def killpg(pid, sig):
        assert pid == process.pid
        signals.append(sig)
        if sig == signal.SIGKILL:
            alive[0] = False
        elif not alive[0]:
            raise ProcessLookupError
    monkeypatch.setattr(r.os, "killpg", killpg)
    assert r.stop_owned(process)
    assert signal.SIGTERM in signals and signal.SIGKILL in signals
    process.wait.assert_called_once_with(timeout=r.STOP_TIMEOUT)


def test_cleanup_missing_group_is_idempotent(monkeypatch):
    monkeypatch.setattr(r.os, "killpg", Mock(side_effect=ProcessLookupError))
    assert r.stop_owned(Mock(pid=12345))


@pytest.mark.parametrize("sig", [0, signal.SIGTERM, signal.SIGKILL])
def test_permission_race_requires_independently_empty_group(monkeypatch, sig):
    monkeypatch.setattr(r.os, "killpg", Mock(side_effect=PermissionError))
    check = Mock(return_value="42\n43\n")
    monkeypatch.setattr(r.subprocess, "check_output", check)
    assert r.signal_group(12345, sig) is False
    assert check.call_args.kwargs["timeout"] == r.MEASURE_TIMEOUT


def test_denied_signal_never_claims_existing_group_was_stopped(monkeypatch):
    monkeypatch.setattr(r.os, "killpg", Mock(side_effect=PermissionError))
    monkeypatch.setattr(r.subprocess, "check_output", Mock(return_value="12345\n"))
    assert r.signal_group(12345, 0) is True
    with pytest.raises(PermissionError):
        r.signal_group(12345, signal.SIGKILL)


def test_unavailable_process_inventory_does_not_prove_cleanup(monkeypatch):
    monkeypatch.setattr(r.os, "killpg", Mock(side_effect=PermissionError))
    monkeypatch.setattr(r.subprocess, "check_output", Mock(side_effect=subprocess.TimeoutExpired("ps", 3)))
    with pytest.raises(subprocess.TimeoutExpired):
        r.signal_group(12345, 0)


def test_monitor_subprocesses_have_timeouts(monkeypatch):
    call = Mock(side_effect=["System-wide memory free percentage: 21%", "42 1024\n43 999"])
    monkeypatch.setattr(r.subprocess, "check_output", call)
    assert r.free_percent() == 21 and r.group_rss(42) == 1024**2
    assert all(c.kwargs["timeout"] == r.MEASURE_TIMEOUT for c in call.call_args_list)


def test_deadline_watch_is_independent_of_measurement_thread(monkeypatch):
    process = Mock(pid=12345)
    process.poll.return_value = None
    guard = r.Guard(process, [])
    guard.deadline = 10
    monkeypatch.setattr(r.time, "monotonic", lambda: 11)
    kill = Mock(return_value=True)
    monkeypatch.setattr(r, "signal_group", kill)
    guard.finished = Mock()
    guard.finished.wait.return_value = False
    guard.watch()
    assert "wall deadline" in guard.errors[0]
    kill.assert_called_once_with(process.pid, signal.SIGKILL)


def test_watch_stops_descendants_when_leader_exits(monkeypatch):
    process = Mock(pid=12345)
    process.poll.return_value = 0
    guard = r.Guard(process, [])
    kill = Mock(return_value=True)
    monkeypatch.setattr(r, "signal_group", kill)
    with pytest.raises(RuntimeError, match="remaining group"):
        guard.check()
    kill.assert_called_once_with(process.pid, signal.SIGKILL)


def test_cleanup_failure_still_writes_terminal_receipt(assets, execution, monkeypatch):
    out, _, sha = freeze(assets)
    monkeypatch.setattr(r, "stop_owned", Mock(side_effect=RuntimeError("group survived")))
    with pytest.raises(RuntimeError, match="group survived"):
        r.execute(out, sha)
    receipt = r.read_json(out / "resource-receipt.json")
    assert receipt["owned_group_empty"] is False and "group survived" in receipt["cleanup_error"]
    assert not (out / "summary.json").exists()
    assert len(r.read_json(out / "blind-review.json")) == 24
    assert all((out / (job["id"] + "-result.json")).exists() for job in r.schedule())


def test_summary_published_only_after_cleanup_receipt(assets, execution, monkeypatch):
    out, _, sha = freeze(assets)
    save = r.save
    def checked_save(path, value):
        if path.name == "resource-receipt.json":
            assert not (out / "summary.json").exists()
            assert execution.stops == [execution.process.pid]
        elif path.name == "summary.json":
            assert r.read_json(out / "resource-receipt.json")["owned_group_empty"] is True
        save(path, value)
    monkeypatch.setattr(r, "save", checked_save)
    r.execute(out, sha)
    assert (out / "summary.json").exists()


def test_receipt_write_failure_prevents_normal_summary(assets, execution, monkeypatch):
    out, _, sha = freeze(assets)
    save = r.save
    def fail_receipt(path, value):
        if path.name == "resource-receipt.json":
            raise OSError("synthetic receipt write failure")
        save(path, value)
    monkeypatch.setattr(r, "save", fail_receipt)
    with pytest.raises(OSError, match="receipt write failure"):
        r.execute(out, sha)
    assert not (out / "summary.json").exists()
    assert (out / "blind-review.json").exists() and execution.stops


def test_listener_ownership_refuses_foreign_pid(monkeypatch):
    probe = Mock(return_value="p42\n")
    monkeypatch.setattr(r.subprocess, "check_output", probe)
    with pytest.raises(RuntimeError, match="not the owned"):
        r.verify_listener(Mock(pid=43), 23456)
    assert probe.call_args.kwargs["timeout"] == r.MEASURE_TIMEOUT


@pytest.mark.parametrize("mode", ["rss", "reserve", "timeout"])
def test_monitor_fails_closed(monkeypatch, mode):
    proc = Mock(pid=12345)
    proc.poll.return_value = None
    guard = r.Guard(proc, [])
    monkeypatch.setattr(r, "signal_group", Mock(return_value=True))
    monkeypatch.setattr(r, "free_percent", lambda: 12 if mode == "reserve" else 50)
    if mode == "timeout":
        monkeypatch.setattr(r, "group_rss", Mock(side_effect=subprocess.TimeoutExpired("ps", 3)))
    else:
        monkeypatch.setattr(r, "group_rss", lambda pid: 15*1024**3 if mode == "rss" else 0)
    guard.measure()
    assert guard.errors
    r.signal_group.assert_called_once_with(proc.pid, signal.SIGKILL)


@pytest.fixture
def wire(monkeypatch):
    connection = Mock()
    response = Mock(status=200)
    connection.getresponse.return_value = response
    monkeypatch.setattr(r, "HTTPConnection", Mock(return_value=connection))
    timer = Mock()
    monkeypatch.setattr(r.threading, "Timer", Mock(return_value=timer))
    return connection, response, timer


@pytest.mark.parametrize("body,status,error", [(b"provider failure", 500, RuntimeError),
                                             (b"{broken", 200, ValueError)])
def test_http_error_and_malformed_raw_evidence(tmp_path, wire, body, status, error):
    connection, response, timer = wire
    response.status = status
    response.read1.side_effect = [body, b""]
    path = tmp_path / "wire.json"
    with pytest.raises(error):
        r.http(23456, "/api/chat", {}, evidence_path=path)
    receipt = r.read_json(path)
    assert base64.b64decode(receipt["body_base64"]) == body and receipt["status"] == status
    assert receipt["retained_sha256"] == r.digest(body)
    timer.cancel.assert_called_once()
    connection.close.assert_called_once()


def test_wire_evidence_bounded(tmp_path, wire, monkeypatch):
    monkeypatch.setattr(r, "MAX_WIRE_BYTES", 8)
    wire[1].read1.side_effect = io.BytesIO(b"123456789extra").read
    with pytest.raises(ValueError, match="bounded"):
        r.http(23456, "/api/chat", evidence_path=tmp_path / "wire.json")
    receipt = r.read_json(tmp_path / "wire.json")
    assert receipt["truncated"] and receipt["retained_bytes"] == 8 and receipt["observed_bytes"] == 9


def test_wire_wall_timer_interrupts_socket(tmp_path, wire, monkeypatch):
    connection, response, _ = wire
    def read(size):
        r.threading.Timer.call_args.args[1]()
        return b"partial"
    response.read1.side_effect = read
    with pytest.raises(TimeoutError, match="wall deadline"):
        r.http(23456, "/api/chat", evidence_path=tmp_path / "wire.json")
    connection.sock.shutdown.assert_called_once_with(r.socket.SHUT_RDWR)
    assert base64.b64decode(r.read_json(tmp_path / "wire.json")["body_base64"]) == b"partial"


def test_incomplete_wire_retains_partial_bytes(tmp_path, wire):
    wire[1].read1.side_effect = IncompleteRead(b"partial body", 20)
    with pytest.raises(IncompleteRead):
        r.http(23456, "/api/chat", evidence_path=tmp_path / "wire.json")
    receipt = r.read_json(tmp_path / "wire.json")
    assert base64.b64decode(receipt["body_base64"]) == b"partial body"
    wire[1].close.assert_called_once()


def prior_attempt(assets, retained_response=None):
    out, packet, sha = freeze(assets, "prior-packet")
    r.save(out / "execution.json", {"packet_sha256": sha})
    isolated = out / "isolated-home/models" / r.MANIFEST
    isolated.parent.mkdir(parents=True)
    r.save(isolated, packet["model_manifest"])
    r.save(out / "resource-receipt.json", {"owned_provider_exit": 0, "errors": [], "live_services_interrupted": False})
    for index, job in enumerate(packet["jobs"][:2]):
        request_path = out / (job["id"] + "-request.json")
        r.save(request_path, r.request_for(packet, job))
        record = {"job": job, "completed": index == 0, "wall_seconds": 1}
        if index == 0:
            record.update(response=completion() if retained_response is None else retained_response,
                          request_sha256=r.file_hash(request_path))
        else:
            record["error"] = "Remote end closed connection without response"
        r.save(out / (job["id"] + "-result.json"), record)
    r.save(out / "failure.json", {"error": "Remote end closed connection without response", "attempted": 2, "guard_errors": []})
    r.save(out / "operator-stop.json", {"schema": "isolated_reflection_operator_stop_v1", "signal": "SIGTERM",
        "remaining_group_members_after_signal": [], "provider_exit_code": 0, "owned_provider_pid": 42,
        "owned_provider_pgid": 42, "verified_command": str(assets.provider) + " serve", "response_prose_reviewed": False,
        "completed_jobs_retained": ["job-01"], "interrupted_jobs": ["job-02"], "packet_sha256": sha,
        "resource_receipt_sha256": r.file_hash(out / "resource-receipt.json"),
        "job_02_result_sha256": r.file_hash(out / "job-02-result.json")})
    return out, packet


@pytest.mark.parametrize("retained_response", [completion(), completion(done_reason="length"),
                        completion(message={"role": "assistant", "content": ""})])
def test_continuation_preserves_completed_bytes_and_only_generates_23(assets, execution, monkeypatch, retained_response):
    prior, previous = prior_attempt(assets, retained_response)
    before = {p.relative_to(prior): r.file_hash(p) for p in prior.rglob("*") if p.is_file()}
    monkeypatch.setattr(r, "helper_frame", Mock(side_effect=AssertionError("must reuse frozen cells")))
    out, packet, sha = freeze(assets, "continued", continue_from=prior, retry_stopped_attempts=True)
    assert packet["cells"] == previous["cells"] and packet["jobs"] == previous["jobs"]
    assert packet["continuation"]["completed_jobs"] == ["job-01"]
    assert packet["continuation"]["retry_jobs"] == ["job-02"]
    assert packet["continuation"]["isolated_manifest"]["raw_matches_source"] is False
    for suffix in ("-request.json", "-result.json"):
        assert r.read_bytes(out / ("job-01" + suffix)) == r.read_bytes(prior / ("job-01" + suffix))
    r.execute(out, sha)
    assert len(execution.calls) == 23
    assert execution.calls[0] == r.request_for(packet, packet["jobs"][1])
    summary = r.read_json(out / "summary.json")
    assert (summary["completed"], summary["imported"], summary["generated_this_run"]) == (24, 1, 23)
    assert summary["ceiling_limited"] == int(retained_response["done_reason"] == "length")
    assert summary["empty_stops"] == int(not retained_response["message"]["content"])
    assert before == {p.relative_to(prior): r.file_hash(p) for p in prior.rglob("*") if p.is_file()}


def test_retry_requires_explicit_opt_in(assets):
    prior, _ = prior_attempt(assets)
    with pytest.raises(ValueError, match="retry-stopped-attempts"):
        freeze(assets, "continued", continue_from=prior)


@pytest.mark.parametrize("kind", ["cell", "result", "witness", "receipt", "manifest"])
def test_conflicting_continuation_refused(assets, kind):
    prior, packet = prior_attempt(assets)
    if kind == "cell":
        candidate = copy.deepcopy(packet)
        candidate["cells"][0]["messages"][0]["content"] += "other"
        with pytest.raises(ValueError, match="prior cells"):
            r.continuation_files(prior, candidate, True)
        return
    paths = {"result": prior / "job-01-result.json", "witness": prior / "operator-stop.json",
             "receipt": prior / "resource-receipt.json", "manifest": prior / "isolated-home/models" / r.MANIFEST}
    path = paths[kind]
    value = r.read_json(path)
    if kind == "result":
        value["job"]["cell"] = 3
    elif kind == "witness":
        value["remaining_group_members_after_signal"] = [42]
    elif kind == "receipt":
        value["owned_provider_exit"] = None
    else:
        value["layers"] = ["different"]
    path.write_bytes(r.encoded(value))
    with pytest.raises(ValueError):
        freeze(assets, "continued", continue_from=prior, retry_stopped_attempts=True)


def test_imported_result_tampering_prevents_execution(assets, execution):
    prior, _ = prior_attempt(assets)
    out, _, sha = freeze(assets, "continued", continue_from=prior, retry_stopped_attempts=True)
    (out / "job-01-result.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="completion changed"):
        r.execute(out, sha)
    assert not execution.calls and not execution.stops


def test_probe_uses_only_owned_canary_and_bounded_calls(tmp_path, monkeypatch):
    observed = []
    def run(command, **kwargs):
        observed.append((command, kwargs))
        if len(observed) == 1:
            return Mock(returncode=0, stderr=b"")
        canary = Path(command[-1])
        assert canary.read_bytes() == b"synthetic deny probe\n"
        assert not canary.is_relative_to(tmp_path)
        return Mock(returncode=1, stderr=b"Operation not permitted")
    monkeypatch.setattr(r.subprocess, "run", run)
    r.probe_sandbox(tmp_path / "isolation.sb", tmp_path, r.clean_env(tmp_path))
    assert len(observed) == 2
    assert all(kw["cwd"] == tmp_path and kw["timeout"] == r.MEASURE_TIMEOUT for _, kw in observed)
