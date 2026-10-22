"""Synthetic adapter qualification. No grants, network, services, or real helper calls."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from minime_autonomy import public_web as web
from minime_autonomy.deployment import source_inputs


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


class PublicWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        package = self.root / "minime_autonomy"
        package.mkdir()
        for name in ("runtime.py", "deployment.py", "public_web.py"):
            (package / name).write_text("# synthetic source\n")
        self.agent = SimpleNamespace(_agent_inputs_at_start=source_inputs(self.root))
        self.trust_root = self.root / "public-trust"
        self.trust_root.mkdir(mode=0o700)
        self.trust_path = self.trust_root / "trust.json"
        self.trust = {"schema": "minime.self_control.trust_store.v1", "target_being": "minime",
                      "pinned_public_keys": {"minime": "a" * 64, "astrid": "b" * 64}}
        self.trust_path.write_bytes(wire(self.trust))
        self.trust_path.chmod(0o600)
        self.helper = self.root / "synthetic-helper-never-executed"
        self.helper.write_bytes(b"synthetic immutable native helper fixture")
        self.helper.chmod(0o700)
        self.config_path = self.root / "config.json"
        self.env = {"MINIME_PUBLIC_WEB_HELPER": str(self.helper),
                    "MINIME_PUBLIC_WEB_HELPER_SHA256": digest(self.helper.read_bytes()),
                    "MINIME_PUBLIC_WEB_CONFIG": str(self.config_path),
                    "MINIME_SELF_CONTROL_ROOT": str(self.trust_root)}
        self.addCleanup(patch.stopall)
        patch.object(web, "BASE_DIR", self.root).start()
        patch.dict(os.environ, self.env, clear=True).start()
        self.owner = web._owner(self.agent)
        self.config = {"schema": "astrid.public_web.config.v2", "expected_owner": self.owner,
                       "expected_policy_sha256": "c" * 64}
        self.save_config()
        self.invoke = patch.object(web, "_invoke").start()

    def save_config(self):
        self.config_path.write_bytes(wire(self.config))
        self.config_path.chmod(0o600)

    def response(self, operation="page", target="https://example.com/", body=b"page"):
        request = {"schema": web.REQUEST_SCHEMA, "operation": operation, "target": target}
        url = "https://example.com/"
        return {"body": list(body), "final_url": url, "content_type": "text/html",
                "receipt": {"schema": web.RECEIPT_SCHEMA, "complete": True,
                            "request_sha256": digest(wire(request)),
                            "policy_sha256": "c" * 64,
                            "owner_sha256": digest(wire(["minime", "minime", "a" * 64])),
                            "final_url_sha256": digest(url.encode()), "body_sha256": digest(body),
                            "decoded_bytes_observed": len(body), "wire_bytes_observed": len(body),
                            "redirects_followed": 0, "http_status": 200}}

    def metadata(self):
        return {"policy_sha256": "c" * 64,
                "owner_sha256": digest(wire(["minime", "minime", "a" * 64])),
                "state_revision": 1, "expires_at_unix_ms": int(time.time() * 1000) + 60_000,
                "operations": ["search", "page"], "implementation_scope": "transport_foundation",
                "limits": {"decoded_body_bytes": web.MAX_BODY, "wire_body_bytes": web.MAX_BODY,
                           "total_timeout_ms": 120_000, "connect_timeout_ms": 5000,
                           "search_hop_timeout_ms": 10_000, "page_hop_timeout_ms": 15_000,
                           "redirects": 5, "storage_headroom_bytes": 64 * 1024 * 1024}}

    def reject(self, code, operation="page", target="https://example.com/", *, preview=False):
        with self.assertRaises(web.PublicWebError) as caught:
            if preview:
                web.preview(self.agent, operation)
            else:
                web.fetch(self.agent, operation, target)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def test_exact_response_and_typed_request_with_derived_runtime_owner(self):
        response = self.response()
        self.invoke.return_value = (0, wire(response))
        self.assertEqual(web.fetch(self.agent, "page", "https://example.com/"), response)
        argv, request = self.invoke.call_args.args
        self.assertEqual(argv[:4], [str(self.helper), "fetch", "--config", str(self.config_path)])
        self.assertEqual(argv[4], "--runtime-owner")
        self.assertEqual(json.loads(argv[5]), self.owner)
        self.assertEqual(json.loads(request), {"schema": web.REQUEST_SCHEMA, "operation": "page",
                                              "target": "https://example.com/"})
        self.assertEqual(self.owner["deployment_identity"], digest(json.dumps(
            self.agent._agent_inputs_at_start, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode()))

    def test_search_target_is_literal_data_not_python_grammar(self):
        target = "\u03bb & q=other ; $(fixture)\n\"quoted\""
        self.invoke.return_value = (0, wire(self.response("search", target)))
        web.fetch(self.agent, "search", target)
        argv, request = self.invoke.call_args.args
        self.assertNotIn(target, argv)
        self.assertEqual(json.loads(request)["target"], target)
        self.assertEqual(digest(request), "ae878b570a047687447d4e05b59d4109d9c93da71ea0e774a34639e364420161")
        self.assertEqual(digest(wire(["minime", "minime", "a" * 64])),
                         "7829af495100bf9be54d51051b341c14b5f08a6a810df0581a743cb4de631f89")

    def test_pdf_remains_raw_bytes_for_the_existing_local_reader(self):
        response = self.response(body=b"%PDF-1.7\n\xff\x00\n%%EOF")
        response["content_type"] = "application/pdf"
        self.invoke.return_value = (0, wire(response))
        self.assertEqual(web.fetch(self.agent, "page", "https://example.com/"), response)

    def test_missing_environment_is_not_inferred_from_live_paths(self):
        for name, code in [("MINIME_PUBLIC_WEB_HELPER", "helper_unconfigured"),
                           ("MINIME_PUBLIC_WEB_HELPER_SHA256", "helper_unconfigured"),
                           ("MINIME_PUBLIC_WEB_CONFIG", "invalid_config")]:
            with self.subTest(name=name), patch.dict(os.environ, {**self.env, name: ""}, clear=True):
                self.reject(code)
        self.invoke.assert_not_called()

    def test_missing_null_or_incomplete_startup_inventory_is_not_authority(self):
        for startup in (None, {}, {"runtime.py": "a" * 64}, {"bad": None}):
            with self.subTest(startup=startup):
                self.agent._agent_inputs_at_start = startup
                self.reject("source_identity_unavailable")
        self.invoke.assert_not_called()

    def test_real_source_inventory_change_and_addition_refuse_before_helper(self):
        source = self.root / "minime_autonomy/runtime.py"
        source.write_text("# changed source\n")
        self.reject("source_changed")
        source.write_text("# synthetic source\n")
        (self.root / "additional.py").write_text("# extra source\n")
        self.reject("source_changed")
        self.invoke.assert_not_called()

    def test_configured_deployment_is_never_treated_as_actual(self):
        self.config["expected_owner"] = {**self.owner, "deployment_identity": "other"}
        self.save_config()
        self.reject("owner_mismatch")
        self.invoke.assert_not_called()

    def test_wrong_trust_target_schema_or_missing_minime_pin_refuses(self):
        for changes in ({"target_being": "astrid"}, {"schema": "other"},
                        {"pinned_public_keys": {"astrid": "b" * 64}},
                        {"pinned_public_keys": {"minime": None}}):
            with self.subTest(changes=changes):
                self.trust_path.write_bytes(wire({**self.trust, **changes}))
                self.reject("owner_identity_unavailable")
        self.invoke.assert_not_called()

    def test_existing_rust_home_default_resolves_only_public_trust(self):
        default = self.root / ".minime/self-control-v2"
        default.mkdir(parents=True)
        (default / "trust.json").write_bytes(wire(self.trust))
        with patch.dict(os.environ, {key: value for key, value in self.env.items()
                                     if key != "MINIME_SELF_CONTROL_ROOT"} | {"HOME": str(self.root)},
                        clear=True):
            self.assertEqual(web._owner(self.agent), self.owner)
        self.assertFalse((default / "identity.json").exists())

    def test_helper_pin_mismatch_symlink_and_writable_helper_refuse(self):
        with patch.dict(os.environ, {"MINIME_PUBLIC_WEB_HELPER_SHA256": "d" * 64}):
            self.reject("helper_identity_mismatch")
        alias = self.root / "helper-alias"
        alias.symlink_to(self.helper)
        with patch.dict(os.environ, {"MINIME_PUBLIC_WEB_HELPER": str(alias)}):
            self.reject("helper_identity_mismatch")
        self.helper.chmod(0o777)
        self.reject("helper_identity_mismatch")
        self.invoke.assert_not_called()

    def test_source_key_config_and_helper_drift_during_work_discard_payload(self):
        cases = [(lambda: (self.root / "new.py").write_text("# changed"), "source_changed"),
                 (lambda: self.trust_path.write_bytes(wire({**self.trust,
                    "pinned_public_keys": {"minime": "d" * 64}})), "owner_mismatch"),
                 (lambda: self.config_path.write_bytes(wire(self.config) + b" "), "config_changed"),
                 (lambda: self.helper.write_bytes(b"changed helper"), "helper_identity_mismatch")]
        for change, code in cases:
            with self.subTest(code=code):
                original_helper = self.helper.read_bytes()
                def respond(*_):
                    change()
                    return 0, wire(self.response())
                self.invoke.side_effect = respond
                self.reject(code)
                (self.root / "new.py").unlink(missing_ok=True)
                self.trust_path.write_bytes(wire(self.trust))
                self.save_config()
                self.helper.write_bytes(original_helper)

    def test_receipt_request_policy_owner_url_body_and_complete_are_bound(self):
        changes = {"request_sha256": "d" * 64, "policy_sha256": "d" * 64,
                   "owner_sha256": "d" * 64, "final_url_sha256": "d" * 64,
                   "body_sha256": "d" * 64, "schema": "other", "complete": False,
                   "http_status": 206, "decoded_bytes_observed": 3,
                   "wire_bytes_observed": web.MAX_BODY + 1, "redirects_followed": 6}
        for key, value in changes.items():
            with self.subTest(field=key):
                response = self.response()
                response["receipt"][key] = value
                self.invoke.return_value = (0, wire(response))
                self.reject("invalid_helper_response")

    def test_unknown_receipt_fields_cannot_leak_command_payload_into_logs(self):
        response = self.response()
        response["receipt"]["error"] = "PRIVATE_PAYLOAD command and raw exception"
        self.invoke.return_value = (0, wire(response))
        self.reject("invalid_helper_response")

    def test_boolean_noninteger_out_of_range_and_changed_body_are_invalid(self):
        for body in ([True], [-1], [256], [1.0], "page", None, [0]):
            with self.subTest(body=body):
                response = self.response()
                response["body"] = body
                self.invoke.return_value = (0, wire(response))
                self.reject("invalid_helper_response")

    def test_invalid_json_duplicate_keys_and_nonfinite_values_fail_closed(self):
        for raw in (b"PRIVATE_PAYLOAD", b"null", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"):
            with self.subTest(raw=raw):
                self.invoke.return_value = (0, raw)
                self.reject("invalid_helper_response")

    def test_failure_codes_are_preserved_but_raw_errors_are_not_exposed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            for code in ("revoked", "owner_busy", "unsafe_address", "state_pending", "storage_headroom"):
                self.invoke.return_value = (1, wire({"complete": False, "code": code,
                                                     "error": "PRIVATE_PAYLOAD"}))
                self.reject(code)
            self.invoke.return_value = (1, wire({"complete": False, "code": "PRIVATE_PAYLOAD"}))
            self.reject("invalid_helper_response")
            self.invoke.side_effect = RuntimeError("PRIVATE_PAYLOAD")
            self.reject("adapter_failed")
        self.assertEqual(output.getvalue(), "")

    def test_old_failure_without_http_status_and_explicit_null_are_supported(self):
        for code in ("http_status", "search_challenge", "deadline"):
            for metadata in ({}, {"http_status": None}):
                with self.subTest(code=code, metadata=metadata):
                    self.invoke.return_value = (1, wire({"complete": False, "code": code, **metadata}))
                    with self.assertRaises(web.PublicWebError) as caught:
                        web.fetch(self.agent, "search", "synthetic query")
                    self.assertEqual(caught.exception.code, code)
                    self.assertIsNone(caught.exception.http_status)
                    self.assertNotIn("HTTP", caught.exception.delivery_message())

    def test_failure_preserves_validated_http_status_and_only_safe_delivery_detail(self):
        for code in ("search_challenge", "http_status"):
            for status in (100, 200, 202, 403, 599):
                with self.subTest(code=code, status=status):
                    self.invoke.return_value = (1, wire({
                        "complete": False, "code": code, "http_status": status,
                        "error": "PRIVATE_RAW_ERROR", "body": "PRIVATE_RESPONSE_BODY",
                    }))
                    with self.assertRaises(web.PublicWebError) as caught:
                        web.fetch(self.agent, "search", "PRIVATE_QUERY")
                    error = caught.exception
                    self.assertEqual((error.code, error.http_status), (code, status))
                    self.assertEqual(str(error), code)
                    message = error.delivery_message()
                    self.assertIn(code, message)
                    self.assertIn(f"HTTP {status}", message)
                    self.assertEqual("human-verification challenge" in message, code == "search_challenge")
                    self.assertNotIn("PRIVATE_", message)

    def test_invalid_failure_http_status_is_rejected_without_coercion(self):
        for status in (False, True, "202", "PRIVATE_STATUS", 202.0, 99, 600, -1, [], {}):
            with self.subTest(status=status):
                self.invoke.return_value = (1, wire({"complete": False, "code": "search_challenge",
                                                     "http_status": status}))
                self.reject("invalid_helper_response", "search", "synthetic query")
                with self.assertRaises(web.PublicWebError) as caught:
                    web.PublicWebError("search_challenge", http_status=status)
                self.assertEqual(caught.exception.code, "invalid_helper_response")
                self.assertIsNone(caught.exception.http_status)

    def test_nonzero_exit_cannot_return_success_and_failure_request_cannot_drift(self):
        self.invoke.return_value = (1, wire(self.response()))
        self.reject("invalid_helper_response")
        self.invoke.return_value = (1, wire({"complete": False, "code": "deadline",
                                             "request_sha256": "d" * 64}))
        self.reject("invalid_helper_response")

    def test_invalid_operation_and_oversized_request_never_launch(self):
        for operation, target in (("browse", "url"), ("page", ""), ("page", None),
                                  ("search", "x" * 16_384)):
            with self.subTest(operation=operation, target_type=type(target)):
                self.reject("invalid_request", operation, target)
        self.invoke.assert_not_called()

    def test_preview_returns_only_validated_metadata_without_fetch_request(self):
        metadata = self.metadata()
        self.invoke.return_value = (0, wire(metadata))
        self.assertEqual(web.preview(self.agent, "search"), metadata)
        self.assertEqual(self.invoke.call_args.args, ([str(self.helper), "preview", "--config",
                                                      str(self.config_path)],))

    def test_preview_unavailable_operation_is_not_a_grant(self):
        metadata = self.metadata()
        metadata["operations"] = ["page"]
        self.invoke.return_value = (0, wire(metadata))
        self.reject("operation_not_granted", "search", preview=True)

    def test_preview_metadata_tamper_expiry_limits_and_payload_fail_closed(self):
        for key, value in {"policy_sha256": "d" * 64, "owner_sha256": "d" * 64,
                           "state_revision": True, "expires_at_unix_ms": 1,
                           "operations": ["page", "page"], "error": "PRIVATE_PAYLOAD"}.items():
            with self.subTest(key=key):
                metadata = self.metadata()
                metadata[key] = value
                self.invoke.return_value = (0, wire(metadata))
                self.reject("invalid_helper_response", preview=True)
        metadata = self.metadata()
        metadata["limits"]["decoded_body_bytes"] += 1
        self.invoke.return_value = (0, wire(metadata))
        self.reject("invalid_helper_response", preview=True)

    def test_preview_checks_source_and_helper_again_after_observation(self):
        def respond(*_):
            (self.root / "new.py").write_text("# drift")
            return 0, wire(self.metadata())
        self.invoke.side_effect = respond
        self.reject("source_changed", preview=True)

    def test_successful_preview_does_not_bypass_fetch_rechecks(self):
        self.invoke.return_value = (0, wire(self.metadata()))
        web.preview(self.agent, "page")
        (self.root / "new.py").write_text("# drift")
        self.reject("source_changed")
        self.assertEqual(self.invoke.call_count, 1)


class PipeProcess:
    """Real anonymous pipes, mocked process; never executes a helper."""
    def __init__(self, output=b"{}", *, hold_open=False, exit_code=0):
        self.input_reader, input_writer = os.pipe()
        output_reader, self.output_writer = os.pipe()
        self.stdin = os.fdopen(input_writer, "wb", buffering=0)
        self.stdout = os.fdopen(output_reader, "rb", buffering=0)
        os.write(self.output_writer, output)
        if not hold_open:
            os.close(self.output_writer)
            self.output_writer = None
        self.returncode = None
        self.exit_code = exit_code
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = -9 if self.killed else self.exit_code
        return self.returncode

    def kill(self):
        self.killed = True

    def close(self):
        self.stdin.close()
        self.stdout.close()
        os.close(self.input_reader)
        if self.output_writer is not None:
            os.close(self.output_writer)


class BoundedPipeTests(unittest.TestCase):
    def process(self, *args, **kwargs):
        process = PipeProcess(*args, **kwargs)
        self.addCleanup(process.close)
        return process

    def test_pipe_io_is_exact_shell_free_and_drops_stderr_and_ambient_environment(self):
        process = self.process(b'{"complete":false}')
        with patch.object(web.subprocess, "Popen", return_value=process) as launch:
            self.assertEqual(web._invoke(["/synthetic/helper", "fetch"], b"typed request"),
                             (0, b'{"complete":false}'))
        self.assertEqual(os.read(process.input_reader, 1024), b"typed request")
        self.assertIs(launch.call_args.kwargs["shell"], False)
        self.assertEqual(launch.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(launch.call_args.kwargs["env"], {"PATH": os.defpath})
        self.assertFalse(process.killed)

    def test_output_limit_kills_and_reaps_only_owned_helper(self):
        process = self.process(b"x" * 64)
        with patch.object(web.subprocess, "Popen", return_value=process), patch.object(web, "MAX_OUTPUT", 32):
            with self.assertRaises(web.PublicWebError) as caught:
                web._invoke(["/synthetic/helper"])
        self.assertEqual(caught.exception.code, "helper_output_limit")
        self.assertTrue(process.killed)
        self.assertEqual(process.returncode, -9)

    def test_stalled_pipe_deadline_kills_and_reaps_owned_helper(self):
        process = self.process(b"", hold_open=True)
        with patch.object(web.subprocess, "Popen", return_value=process), patch.object(web, "HELPER_TIMEOUT", .005):
            with self.assertRaises(web.PublicWebError) as caught:
                web._invoke(["/synthetic/helper"])
        self.assertEqual(caught.exception.code, "helper_timeout")
        self.assertTrue(process.killed)
        self.assertEqual(process.returncode, -9)

    def test_spawn_error_is_content_free(self):
        with patch.object(web.subprocess, "Popen", side_effect=OSError("PRIVATE_PAYLOAD")):
            with self.assertRaises(web.PublicWebError) as caught:
                web._invoke(["/synthetic/helper"])
        self.assertEqual(str(caught.exception), "helper_spawn_failed")

    def test_process_exit_timeout_after_pipe_eof_is_not_success(self):
        process = self.process()
        original_wait = process.wait
        def wait(timeout=None):
            if not process.killed:
                raise subprocess.TimeoutExpired("PRIVATE_PAYLOAD", timeout)
            return original_wait(timeout)
        process.wait = wait
        with patch.object(web.subprocess, "Popen", return_value=process):
            with self.assertRaises(web.PublicWebError) as caught:
                web._invoke(["/synthetic/helper"])
        self.assertEqual(caught.exception.code, "helper_timeout")
        self.assertTrue(process.killed)


if __name__ == "__main__":
    unittest.main()
