"""Durable owner-only storage and two-worker scheduling for inquiries."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Mapping

from .owner_inquiry_protocol import OwnerInquiryError, _json_tail


class OwnerInquiryStorageMixin:
    """Storage mechanics kept separate from inquiry and canary semantics."""

    @property
    def queue_path(self) -> Path:
        return self.root / "queue.json"

    def _schedule_locked(self, queue: dict[str, Any]) -> None:
        self._reap_locked()
        available = 2 - len(self._futures)
        if available <= 0:
            return
        status_by_id = {
            item["inquiry_id"]: item["status"] for item in queue["items"]
        }
        candidates = sorted(
            (
                item
                for item in queue["items"]
                if item["status"] == "queued"
                and not item["cancel_requested"]
                and item["inquiry_id"] not in self._futures
            ),
            key=lambda item: (
                -int(item.get("owner_priority", 0)),
                int(item.get("created_at_unix_ms", 0)),
            ),
        )
        changed = False
        for item in candidates:
            dependencies = item.get("dependency_inquiry_ids") or []
            failed = [
                dependency
                for dependency in dependencies
                if status_by_id.get(dependency) in {"failed", "cancelled"}
            ]
            if failed:
                item["status"] = "failed"
                item["error"] = "dependency failed or was cancelled: " + ", ".join(failed)
                item["updated_at_unix_ms"] = self._clock_ms()
                changed = True
                continue
            if any(status_by_id.get(dependency) != "completed" for dependency in dependencies):
                continue
            self._futures[item["inquiry_id"]] = self._executor.submit(
                self._run_job, item["inquiry_id"]
            )
            available -= 1
            if available == 0:
                break
        if changed:
            self._write_queue_locked(queue)

    def _reap_locked(self) -> None:
        for inquiry_id, future in list(self._futures.items()):
            if not future.done():
                continue
            try:
                future.result()
            except Exception:
                pass
            self._futures.pop(inquiry_id, None)

    def _recover_queue(self) -> None:
        with self._lock:
            queue = self._load_queue_locked()
            changed = False
            for item in queue["items"]:
                if item.get("status") == "running":
                    item["status"] = "queued"
                    item["updated_at_unix_ms"] = self._clock_ms()
                    changed = True
            if changed:
                self._write_queue_locked(queue)
            self._schedule_locked(queue)

    def _load_queue_locked(self) -> dict[str, Any]:
        if not self.queue_path.exists():
            return {
                "schema": "minime.owner_inquiry.queue.v1",
                "max_concurrent_read_compute": 2,
                "write_serialization": "per_resource",
                "items": [],
            }
        queue = self._read_json(self.queue_path)
        if (
            queue.get("schema") != "minime.owner_inquiry.queue.v1"
            or queue.get("max_concurrent_read_compute") != 2
            or not isinstance(queue.get("items"), list)
        ):
            raise OwnerInquiryError("owner inquiry queue is malformed")
        return queue

    def _write_queue_locked(self, queue: Mapping[str, Any]) -> None:
        self._write_json(self.queue_path, queue)

    @staticmethod
    def _select_item(
        queue: Mapping[str, Any],
        inquiry_id: str | None,
        *,
        required_status: str | None = None,
    ) -> dict[str, Any] | None:
        candidates = [
            item
            for item in queue.get("items", [])
            if (not inquiry_id or inquiry_id == "latest" or item.get("inquiry_id") == inquiry_id)
            and (required_status is None or item.get("status") == required_status)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: int(item.get("created_at_unix_ms", 0)))

    @staticmethod
    def _selector(action_text: str, base: str) -> str | None:
        tail = str(action_text)[len(base) :].strip().lstrip(":").strip()
        if not tail:
            return None
        if tail.startswith("{"):
            payload = _json_tail(action_text, base)
            value = payload.get("inquiry_id") or payload.get("canary_id")
            return str(value).strip() if value else None
        return tail.split()[0]

    def _required_selector(self, action_text: str, base: str) -> str:
        return self._selector(action_text, base) or "latest"

    def _invoke(
        self,
        args: list[str],
        *,
        timeout: float,
        sandbox_network: bool = False,
    ) -> dict[str, Any]:
        command = [str(self.binary), *args]
        if sandbox_network:
            sandbox = self.sandbox_binary
            if not sandbox.is_file():
                raise OwnerInquiryError(
                    "owner inquiry refused to run because the network/socket-denying "
                    "sandbox is unavailable"
                )
            command = [
                str(sandbox),
                "-p",
                "(version 1)\n(allow default)\n(deny network*)",
                *command,
            ]
        result = self._runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise OwnerInquiryError(
                f"owner inquiry command failed ({result.returncode}): "
                f"{(result.stderr or result.stdout).strip()[:500]}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise OwnerInquiryError("owner inquiry command returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise OwnerInquiryError("owner inquiry command returned a non-object")
        return payload

    def _ensure_dirs(self) -> None:
        for path in (
            self.root,
            self.root / "items",
            self.root / "canaries",
            self.self_control_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
            try:
                path.chmod(0o700)
            except OSError:
                pass

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {value}")
            ),
        )
        if not isinstance(value, dict):
            raise OwnerInquiryError(f"{path} does not contain a JSON object")
        return value

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            path.chmod(0o600)
        finally:
            if temp.exists():
                temp.unlink()

    @classmethod
    def _write_json(cls, path: Path, value: Any) -> None:
        cls._write_bytes(
            path,
            json.dumps(
                value,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n",
        )
