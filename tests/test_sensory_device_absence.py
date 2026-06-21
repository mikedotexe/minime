from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


camera_client = _load_module(
    "camera_client_under_test",
    ROOT / "minime" / "tools" / "camera_client.py",
)
mic_to_sensory = _load_module(
    "mic_to_sensory_under_test",
    ROOT / "tools" / "mic_to_sensory.py",
)


class _ClosedCapture:
    def isOpened(self) -> bool:
        return False

    def release(self) -> None:
        return None


class _OpenCapture:
    def isOpened(self) -> bool:
        return True

    def release(self) -> None:
        return None


def test_camera_start_absent_records_expected_fallback_status() -> None:
    client = camera_client.GpuCameraClient(camera_index=0, fps=0.2)

    with (
        mock.patch.object(camera_client, "probe_camera_devices", return_value=(False, [])),
        mock.patch.object(camera_client.cv2, "VideoCapture", return_value=_ClosedCapture()),
    ):
        assert client.start_camera() is False

    payload = client._status_payload(healthy=False)
    assert payload["state"] == "device_absent"
    assert payload["last_error"] == "no_video_input_device"
    assert payload["physical_device_present"] is False
    assert payload["fallback_expected"] is True


def test_camera_start_present_failure_remains_actionable_failure() -> None:
    client = camera_client.GpuCameraClient(camera_index=0, fps=0.2)

    with (
        mock.patch.object(camera_client, "probe_camera_devices", return_value=(True, ["cam-1"])),
        mock.patch.object(camera_client.cv2, "VideoCapture", return_value=_ClosedCapture()),
    ):
        assert client.start_camera() is False

    payload = client._status_payload(healthy=False)
    assert payload["state"] == "capture_error"
    assert payload["last_error"] == "camera_start_failed"
    assert payload["physical_device_present"] is True
    assert payload["physical_device_ids"] == ["cam-1"]
    assert payload["fallback_expected"] is False


def test_camera_success_overrides_profiler_absence_assumption() -> None:
    client = camera_client.GpuCameraClient(camera_index=0, fps=0.2)
    client.physical_device_present = False
    client.fallback_expected = True

    with mock.patch.object(camera_client.cv2, "VideoCapture", return_value=_OpenCapture()):
        assert client.start_camera() is True

    payload = client._status_payload(healthy=True)
    assert payload["physical_device_present"] is True
    assert payload["fallback_expected"] is False


def test_mic_capture_failure_without_input_records_expected_fallback_status() -> None:
    bridge = mic_to_sensory.MicToSensoryBridge("ws://127.0.0.1:7879", False)

    with mock.patch.object(mic_to_sensory, "probe_audio_input_devices", return_value=(False, [])):
        reason = bridge._record_capture_failure_device_context("capture_eof")

    payload = bridge._status_payload(healthy=False)
    assert reason == "no_audio_input_device"
    assert payload["state"] == "device_absent"
    assert payload["last_error"] == "no_audio_input_device"
    assert payload["physical_device_present"] is False
    assert payload["fallback_expected"] is True


def test_mic_capture_failure_with_input_remains_actionable_failure() -> None:
    bridge = mic_to_sensory.MicToSensoryBridge("ws://127.0.0.1:7879", False)

    with mock.patch.object(
        mic_to_sensory,
        "probe_audio_input_devices",
        return_value=(True, ["mic|maker|usb"]),
    ):
        reason = bridge._record_capture_failure_device_context("capture_eof")

    payload = bridge._status_payload(healthy=False)
    assert reason == "capture_eof"
    assert payload["physical_device_present"] is True
    assert payload["physical_device_ids"] == ["mic|maker|usb"]
    assert payload["fallback_expected"] is False

