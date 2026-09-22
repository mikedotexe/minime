"""Host scheduling for the shared Rust attention contract; no local grammar/policy."""
from __future__ import annotations

import time
import uuid

from .source_study import StudyClient


COMMANDS = frozenset({"ACTIVITY_FOCUS", "ACTIVITY_STATUS", "END_ACTIVITY_FOCUS",
                      "PARK_ACTIVITY", "RETURN_ACTIVITY", "CHECK_MAILBOX"})


class ActivityFocus:
    def __init__(self, client: StudyClient, clock=None):
        self.client = client
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)

    @property
    def exists(self):
        root = self.client.workspace / "diagnostics/source_first_v3/shared_reader"
        return any((root / name).exists() for name in
                   ("activity-focus-v1.json", "activity-transition-v1.json"))

    def call(self, request, *, view=None, ident=None):
        return self.client.activity(request, request_id=ident or uuid.uuid4().hex,
                                   expected_revision=view["revision"] if view else None,
                                   now_ms=self.clock())

    def status(self):
        return self.call({"op": "status"}) if self.exists else {"protected": False, "revision": 0}

    def next(self):
        return self.call({"op": "next"}) if self.exists else self.status()

    def command(self, action, *, ident=None):
        return self.call({"op": "command", "action": action}, view=self.status(), ident=ident)

    def release_for_choice(self, action):
        current = self.next()
        if current.get("protected") and action != current.get("next_action"):
            self.command("END_ACTIVITY_FOCUS")

    def admit(self, prompt, action, job_id):
        current = self.next()
        if current.get("pending_job"):
            raise RuntimeError("protected job remains pending; do not repeat an uncertain provider invocation")
        if not current.get("protected"):
            return None
        if action != current.get("next_action"):
            raise RuntimeError("generation differs from the protected authored choice")
        input_id = (prompt.output.get("page") or {}).get("id") or prompt.output.get("navigation_id")
        admitted = self.call({"op": "admit", "job_id": job_id, "input_id": input_id, "action": action},
                             view=current, ident=f"admit-{job_id}")
        claimed = self.call({"op": "claim", "job_id": job_id}, view=admitted, ident=f"claim-{job_id}")
        if not claimed["invocation_granted"]:
            raise RuntimeError("protected provider invocation already claimed")
        return job_id, input_id

    def finish(self, admission, *, verified):
        if admission is None:
            return
        job_id, input_id = admission
        request = ({"op": "complete", "job_id": job_id, "input_id": input_id} if verified
                   else {"op": "failed", "job_id": job_id})
        return self.call(request, view=self.status())

    def recover_committed(self):
        """After host drain/restart, recover only a verified native delivery.

        Missing or corrupt receipts remain visible pending debt, never permission
        to repeat an invocation or silently discard a potentially accepted output.
        """
        current = self.status()
        if not current.get("pending_job"):
            return current
        return self.call({"op": "complete", "job_id": current["pending_job"],
                          "input_id": current["pending_input_id"]}, view=current)
