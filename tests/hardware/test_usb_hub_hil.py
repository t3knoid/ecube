import sys
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _auth_headers() -> dict[str, str]:
    payload = {
        "sub": "hil-operator",
        "username": "hil-operator",
        "groups": ["evidence-team"],
        "roles": ["admin"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return {"Authorization": f"Bearer {token}"}


def _operator_prompt(message: str) -> None:
    if not sys.stdin or not sys.stdin.isatty():
        pytest.skip("Hardware HIL tests require interactive terminal input. Run with -s in a local terminal.")
    input(f"\n[HIL OPERATOR STEP] {message}\nPress Enter to continue...")


def _usb_device_count(client: TestClient) -> int:
    response = client.get("/introspection/usb/topology")
    assert response.status_code == 200
    body = response.json()
    assert "devices" in body
    assert isinstance(body["devices"], list)
    return len(body["devices"])


@pytest.mark.hardware
def test_usb_hub_connect_disconnect_hil_skeleton():
    """Hardware-in-the-loop skeleton for validating USB hub + device lifecycle.

    Preconditions:
    - Run on Linux host with USB sysfs visibility.
    - API dependencies installed and test token secret configured.
    - Execute with: pytest tests/hardware/test_usb_hub_hil.py -s --run-hardware
    """
    with TestClient(app) as client:
        client.headers.update(_auth_headers())

        _operator_prompt(
            "Ensure the target USB hub is disconnected and no test USB drive is attached."
        )
        baseline_count = _usb_device_count(client)

        _operator_prompt(
            "Connect the USB hub and attach exactly one known test USB device to a hub port."
        )

        expected_min_delta = 1
        observed_after_connect = None
        for _ in range(15):
            observed_after_connect = _usb_device_count(client)
            if observed_after_connect >= baseline_count + expected_min_delta:
                break
            time.sleep(1)

        assert observed_after_connect is not None
        assert observed_after_connect >= baseline_count + expected_min_delta, (
            "USB topology did not reflect newly connected hardware. "
            "Verify hub power, cable integrity, and Linux /sys visibility."
        )

        block_response = client.get("/introspection/block-devices")
        assert block_response.status_code == 200
        assert "block_devices" in block_response.json()
        assert isinstance(block_response.json()["block_devices"], list)

        _operator_prompt(
            "Disconnect the test USB device (leave the hub connected), then reconnect it."
        )
        reconnect_count = _usb_device_count(client)
        assert reconnect_count >= baseline_count + expected_min_delta

        _operator_prompt(
            "Disconnect the test USB device and hub so the system returns to baseline."
        )
        observed_after_disconnect = _usb_device_count(client)

        assert observed_after_disconnect <= observed_after_connect, (
            "USB topology count did not decrease after disconnect. "
            "Check whether additional external USB devices were attached during the test."
        )
