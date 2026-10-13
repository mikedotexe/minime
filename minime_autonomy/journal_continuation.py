"""Host publication adapter. Rust owns source eligibility and exact transfer."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .source_study import StudyClient


@dataclass(frozen=True)
class JournalContinuation:
    client: StudyClient
    operation_id: str
    entry_id: str

    @classmethod
    def reserve(cls, client: StudyClient, operation_id: str):
        if not operation_id:
            raise ValueError("journal continuation requires a durable action identity")
        receipt = cls._register(client, "reserve", operation_id, {
            "operation": "reserve", "owner": "minime", "operation_id": operation_id,
            "source_kind": "authored_public_journal",
        })
        return cls(client, operation_id, receipt["entry_id"])

    @staticmethod
    def _register(client, phase, operation_id, request):
        revision = client.call(operation="preparation_revision")["revision"]
        result = client.call(operation="journal_registration",
            request_id="journal-" + phase + "-" + hashlib.sha256(operation_id.encode()).hexdigest(),
            expected_revision=revision, request=request)
        if result.get("generation_requested") is not False:
            raise RuntimeError("journal registration cannot request generation")
        return json.loads(result["text"])

    def hint(self):
        return ("Exact selected continuation: after this public entry is successfully saved, "
                f"NEXT: WRITE FROM_JOURNAL {self.entry_id} can start a new private draft "
                "from its exact authored prose. This is optional; no transfer occurs without your choice. "
                "WRITE JOURNALS and WRITE JOURNAL_READ make registered passages inspectable. "
                "Drafts are excluded from automatic public/peer delivery and locally inspectable by the operator.")

    def publish(self, path: Path, response: str):
        return self._register(self.client, "publish", self.operation_id, {
            "operation": "publish", "owner": "minime", "operation_id": self.operation_id,
            "entry_id": self.entry_id, "source_path": str(path.resolve()),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
            "authored_response": response, "response_span": None,
        })
