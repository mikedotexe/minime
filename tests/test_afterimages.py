import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from minime_autonomy.afterimages import AfterimageStore, HOUR_MS, atomic_json, fingerprint, read_json
from minime_autonomy.afterimage_prompts import AfterimagePrompt, selected_page_prompt, record_attempt

FIXTURE = Path(__file__).parent / "fixtures" / "transition_afterimage_v1.json"


class AfterimagesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.minime = self.root / "minime"
        self.astrid = self.root / "astrid"
        self.store = AfterimageStore(self.minime)
        self.peer = AfterimageStore(self.astrid, self.minime, "astrid")
        self.fixture = json.loads(FIXTURE.read_text())
        self.identifier = self.fixture["id"]
        self.timestamp = self.fixture["anchor_unix_ms"]
        atomic_json(self.store.archive / "2026-09-07" / (self.identifier + ".json"), self.fixture)
        atomic_json(self.store.archive / "recent.json", [self.store._summary(self.fixture)])

    def test_both_readers_open_same_physical_fixture(self):
        self.assertEqual(self.store.open_page(self.identifier), self.peer.open_page(self.identifier))
        self.assertEqual(len(self.store.list_page()["entries"]), 1)
        self.assertIn("incomplete", self.store.open_page(self.identifier)["text"])

    def test_explicit_later_note_is_shareable_without_refreshing_trace_age(self):
        text = f"RESIDUE: {self.identifier}\nLater words, still individual."
        source = {"path":"journal/later.txt", "generation_id":"generation_later", "timestamp_unix_ms":self.timestamp+10*HOUR_MS}
        self.store.link_context(source, text)
        self.store.link_context(source, text)
        notes = self.store._notes(self.identifier)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["text"], text)
        self.assertEqual(self.store.entries()[0]["anchor_unix_ms"], self.timestamp)
        self.assertNotIn(text, self.peer.open_page(self.identifier)["text"])
        self.store.share(notes[0]["note_id"])
        self.assertEqual(self.peer._notes(self.identifier)[0]["text"], text)

    def test_shared_symlink_cannot_publish_a_private_note(self):
        saved = self.store.keep("not shared", timestamp_ms=self.timestamp)
        shared = self.store.archive / "shared_notes" / saved["id"]
        shared.parent.mkdir(exist_ok=True, parents=True)
        shared.symlink_to(self.store.private / "by_artifact" / saved["id"], target_is_directory=True)
        with self.assertRaises(ValueError):
            self.peer.open_page(saved["id"])

    def test_astrid_optional_authorship_and_mirrored_minime_text(self):
        text = "RESIDUE: " + self.identifier + "\nMy own later account."
        self.peer.link_context({"authorship":None, "timestamp_unix_ms":self.timestamp}, text)
        notes = self.peer._notes(self.identifier)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["author"], "astrid")
        self.assertEqual(notes[0]["text"], text)
        self.peer.link_context({"authorship":"minime_owned_generated", "timestamp_unix_ms":self.timestamp},
                               "RESIDUE: " + self.identifier + "\nMinime's mirrored account.")
        self.assertEqual(len(self.peer._notes(self.identifier)), 1)
        self.assertEqual(self.store._notes(self.identifier), [])

    def test_source_reference_preserves_crlf_and_failed_capture_is_retrievable(self):
        source = self.minime / "crlf.txt"
        source.write_bytes(b"first\r\nsecond\r\n")
        saved = self.store.keep("", source_ref="crlf.txt")
        self.assertEqual(self.store._notes(saved["id"])[0]["text"], "first\r\nsecond\r\n")

    def test_selected_page_restarts_intact_and_wrong_ack_is_rejected(self):
        command = [sys.executable, str(Path(__file__).parents[1]/"minime_autonomy/afterimages.py"),
                   "--workspace", str(self.astrid), "--archive-workspace", str(self.minime), "--actor", "astrid", "--json-request"]
        selected = subprocess.run(command, input=json.dumps({"operation":"select", "artifact_id":self.identifier}),
                                  text=True, capture_output=True, check=True)
        value = json.loads(selected.stdout)
        pending = read_json(self.peer.private / "pending_open.json")
        self.assertEqual(pending["text"], self.peer.open_page(self.identifier)["text"])
        rejected = subprocess.run(command, input=json.dumps({"operation":"ack", "content_id":"wrong", "receipt":{}}), text=True, capture_output=True)
        self.assertNotEqual(rejected.returncode, 0)
        accepted = subprocess.run(command, input=json.dumps({"operation":"ack", "content_id":value["content_id"], "receipt":{"test_fixture":True}}), text=True, capture_output=True)
        self.assertEqual(accepted.returncode, 0, accepted.stdout)
        self.assertFalse((self.peer.private / "pending_open.json").exists())

    def test_unknown_source_time_is_not_replaced_by_current_generation(self):
        source = self.minime / "old.txt"
        source.write_text("older words")
        saved = self.store.keep("", {"timestamp_unix_ms":self.timestamp, "generation_id":"current"}, source_ref="old.txt")
        note = self.store._notes(saved["id"])[0]
        self.assertIsNone(note["source_timestamp_unix_ms"])
        self.assertEqual(saved["status"], "incomplete")
        self.assertFalse((self.store.archive / "requests").exists())

    def test_date_lookup_survives_recent_index_eviction(self):
        saved = self.store.keep("older private words", timestamp_ms=self.timestamp)
        atomic_json(self.store.private / "index.json", [])
        self.assertNotIn(saved["id"], [row["id"] for row in self.store.entries()])
        self.assertIn(saved["id"], [row["id"] for row in self.store.entries("2026-09-07")])
        self.assertIn("older private words", self.store.open_page(saved["id"])["text"])
        self.assertNotIn(saved["id"], [row["id"] for row in self.peer.entries("2026-09-07")])

    def test_private_fragment_survives_capture_off_and_restart(self):
        fragment = "  unresolved\nNEXT: CHANGE_CONTROLLER\n```\n  still mine  "
        result = self.store.keep(fragment, timestamp_ms=self.timestamp)
        self.assertEqual(result["status"], "incomplete")
        recovered = AfterimageStore(self.minime)
        notes = recovered._notes(result["id"])
        self.assertEqual(notes[0]["text"], fragment)
        self.assertEqual(notes[0]["content_fingerprint"], fingerprint(fragment))
        self.assertIn("> NEXT: CHANGE_CONTROLLER", recovered.open_page(result["id"])["text"])
        with self.assertRaises(ValueError):
            self.peer.open_page(result["id"])
        self.assertNotIn(result["id"], [row["id"] for row in self.peer.entries()])

    def test_sharing_preserves_attribution_without_publishing_other_notes(self):
        private = self.store.keep("Private A", timestamp_ms=self.timestamp)
        shared = self.store.keep("Shared B", timestamp_ms=self.timestamp)
        before = read_json(self.store.private / "notes" / (shared["note_id"] + ".json"))
        self.store.share(shared["note_id"])
        self.assertEqual(self.peer._notes(shared["id"])[0], before)
        with self.assertRaises(ValueError):
            self.peer.open_page(private["id"])
        with self.assertRaises(ValueError):
            self.peer.share(shared["note_id"])

    def test_whitespace_and_large_source_snapshot(self):
        result = self.store.handle("AFTERIMAGE_KEEP ::   keep this  ")
        self.assertEqual(self.store._notes(result["id"])[0]["text"], "  keep this  ")
        with self.assertRaises(ValueError):
            self.store.keep("x"*4097)
        source = self.minime / "journal.txt"
        source.parent.mkdir(exist_ok=True, parents=True)
        source.write_text("long original\n"*1000)
        result = self.store.keep("", source_ref="journal.txt")
        original = source.read_text()
        source.write_text("changed later")
        note = self.store._notes(result["id"])[0]
        self.assertEqual(note["text"], original)
        self.assertGreater(self.store.open_page(result["id"])["pages"], 1)
        with self.assertRaises(ValueError):
            self.store.keep("", source_ref="../astrid/private.txt")

    def test_note_is_saved_before_capture_request_failure(self):
        atomic_json(self.store.archive / "status.json", {"enabled": True, "updated_at_unix_ms": self.timestamp})
        original_atomic = atomic_json
        def failing_request(path, value):
            if "requests" in Path(path).parts:
                raise OSError("simulated disk failure")
            original_atomic(path, value)
        with patch("minime_autonomy.afterimages.now_ms", return_value=self.timestamp), patch("minime_autonomy.afterimages.atomic_json", side_effect=failing_request):
            result = self.store.keep("irreplaceable fragment")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.store._notes(result["id"])[0]["text"], "irreplaceable fragment")

    def test_capture_request_has_source_anchor_and_no_private_text(self):
        atomic_json(self.store.archive / "status.json", {"enabled": True, "updated_at_unix_ms": self.timestamp})
        with patch("minime_autonomy.afterimages.now_ms", return_value=self.timestamp):
            result = self.store.keep("private words", {"engine_t_ms": 42_000, "session_id": "17", "timestamp_unix_ms": self.timestamp-20_000})
        request = read_json(next((self.store.archive / "requests").glob("*.json")))
        self.assertEqual(request["anchor_engine_t_ms"], 42_000)
        self.assertEqual(request["anchor_unix_ms"], self.timestamp-20_000)
        self.assertNotIn("private words", json.dumps(request))
        self.assertEqual(result["status"], "pending")

    def test_cue_default_off_cadence_retry_and_decay(self):
        self.assertIsNone(self.store.prepare_cue("off", timestamp_ms=self.timestamp))
        self.assertFalse(self.store.private.exists())
        self.store.set_cues(True)
        self.assertIsNone(self.store.prepare_cue("one", timestamp_ms=self.timestamp))
        self.assertIsNone(self.store.prepare_cue("two", timestamp_ms=self.timestamp))
        selected = self.store.prepare_cue("three", timestamp_ms=self.timestamp)
        self.assertLessEqual(len(selected["text"]), 400)
        restarted = AfterimageStore(self.minime)
        self.assertEqual(selected, restarted.prepare_cue("three", timestamp_ms=self.timestamp+1))
        for index in range(4, 7):
            self.assertIsNone(restarted.prepare_cue(str(index), timestamp_ms=self.timestamp+HOUR_MS))
        for index in range(7, 9):
            self.assertIsNone(restarted.prepare_cue(str(index), timestamp_ms=self.timestamp+6*HOUR_MS))
        faint = restarted.prepare_cue("nine", timestamp_ms=self.timestamp+6*HOUR_MS)
        self.assertLessEqual(len(faint["text"]), 120)
        for index in range(10, 16):
            self.assertIsNone(restarted.prepare_cue(str(index), timestamp_ms=self.timestamp+12*HOUR_MS))
        self.assertEqual(self.fixture, read_json(self.store.archive / "2026-09-07" / (self.identifier+".json")))

    def test_expired_artifact_remains_retrievable_and_cues_are_actor_specific(self):
        self.store.set_cues(True)
        for index in range(1,4):
            self.assertIsNone(self.store.prepare_cue(str(index), timestamp_ms=self.timestamp+25*HOUR_MS))
        self.assertIsNone(self.peer.prepare_cue("peer", timestamp_ms=self.timestamp))
        self.assertIn(self.identifier,self.store.open_page(self.identifier)["text"])

    def test_exposure_records_inclusion_without_revising_artifact(self):
        selection = {"id": self.identifier, "text": "a bounded cue", "opportunity_id": "op"}
        prompt = AfterimagePrompt("ambient", selection, self.store)
        first = record_attempt(prompt, [{"content":str(prompt)}], "primary", "model1")
        second = record_attempt(prompt, [{"content":"trimmed"}], "fallback", "model2")
        self.assertTrue(first["included"])
        self.assertFalse(second["included"])
        self.assertEqual(first["opportunity_id"],second["opportunity_id"])
        self.assertEqual(first["content_fingerprint"],second["content_fingerprint"])

    def test_temporal_context_is_never_a_witness(self):
        self.store.link_context({"timestamp_unix_ms":self.timestamp, "action_id":"action1"})
        page = self.store.open_page(self.identifier)
        combined = "\n".join(self.store.open_page(self.identifier,i)["text"] for i in range(1,page["pages"]+1))
        self.assertIn("temporal_context",combined)
        self.assertNotIn("authored_reference",combined)

    def test_cli_parity_and_invalid_paths(self):
        script = Path(__file__).parents[1] / "minime_autonomy" / "afterimages.py"
        result = subprocess.run([sys.executable,str(script),"--workspace",str(self.astrid),"--archive-workspace",str(self.minime),
                                 "--actor","astrid","--json-request"], input=json.dumps({"action":"AFTERIMAGE_OPEN "+self.identifier}),
                                text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)["text"],self.peer.open_page(self.identifier)["text"])
        for identifier in ("../secret","ai_2026-99-99_bad","/tmp/file"):
            with self.assertRaises(ValueError): self.store.open_page(identifier)


if __name__ == "__main__":
    unittest.main()
