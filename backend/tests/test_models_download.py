import hashlib
import io
import os
import socket
from threading import Event
import time
from urllib.error import HTTPError, URLError

import pytest

from app.ai import model_files


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


def status(client, model):
    return client.get("/api/ai/capabilities").json()["downloads"][model]


def wait(client, model, desired):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = status(client, model)
        if result["status"] == desired:
            return result
        time.sleep(.03)
    raise AssertionError(f"Descarga: {result}")


def test_installs_only_after_request_and_reuses_verified_file(client, settings, monkeypatch):
    data = b"sample model blocks"
    monkeypatch.setitem(model_files.MODEL_HASHES, "base", hashlib.sha256(data).hexdigest())
    urls = []

    def open_model(url, timeout):
        urls.append(url)
        return Response(data)

    monkeypatch.setattr(model_files, "urlopen", open_model)
    capabilities = client.get("/api/ai/capabilities").json()
    assert capabilities["device"] == "cpu" and not capabilities["downloads"] and not urls
    assert client.post("/api/ai/models/unknown/download").status_code == 422
    assert client.post("/api/ai/models/base/download").status_code == 202
    assert wait(client, "base", "completed")["received"] == len(data)
    assert urls[0].endswith("/base.pt")
    assert (settings.model_dir / "base.pt").read_bytes() == data
    assert client.post("/api/ai/models/base/download").status_code == 202
    wait(client, "base", "completed")
    assert len(urls) == 1
    assert client.get("/api/storage").json()["model_bytes"] == len(data)


def test_cancel_download_with_progress_and_reject_bad_hash(client, settings, monkeypatch):
    readable = Event()
    resume = Event()
    monkeypatch.setattr(model_files, "BLOCK_SIZE", 4)
    data = b"unverified data"

    class SlowResponse(Response):
        def read(self, size):
            if self.tell() == 4:
                readable.set()
                resume.wait(5)
            return super().read(size)

    monkeypatch.setattr(model_files, "urlopen", lambda url, timeout: SlowResponse(data))
    assert client.post("/api/ai/models/small/download").status_code == 202
    try:
        assert readable.wait(5)
        assert status(client, "small")["received"] == 4
        assert client.post("/api/ai/models/base/download").status_code == 409
        assert client.post("/api/ai/models/small/cancel").json()["status"] == "cancelling"
    finally:
        resume.set()
    wait(client, "small", "cancelled")
    assert not list(settings.model_dir.iterdir())
    assert client.post("/api/ai/models/base/download").status_code == 202
    assert "SHA256" in wait(client, "base", "failed")["error"]
    assert not list(settings.model_dir.iterdir())


def test_base_install_preserves_verified_tiny_and_small(client, settings, monkeypatch):
    payloads = {model: f"verified {model}".encode() for model in model_files.MODEL_HASHES}
    settings.model_dir.mkdir()
    for model, data in payloads.items():
        monkeypatch.setitem(model_files.MODEL_HASHES, model, hashlib.sha256(data).hexdigest())
        if model != "base":
            (settings.model_dir / f"{model}.pt").write_bytes(data)
    original_times = {model: (settings.model_dir / f"{model}.pt").stat().st_mtime_ns for model in ("tiny", "small")}
    monkeypatch.setattr(model_files, "urlopen", lambda url, timeout: Response(payloads["base"]))

    assert client.post("/api/ai/models/base/download").status_code == 202
    wait(client, "base", "completed")
    assert {m["id"]: m["integrity"] for m in client.get("/api/ai/capabilities").json()["models"]} == {
        "tiny": "verified", "base": "verified", "small": "verified",
    }
    for model, data in payloads.items():
        assert (settings.model_dir / f"{model}.pt").read_bytes() == data
    for model, stamp in original_times.items():
        assert (settings.model_dir / f"{model}.pt").stat().st_mtime_ns == stamp


def test_retries_dns_and_truncated_transfer_and_preserves_corrupt_file_until_verified(client, settings, monkeypatch):
    data = b"complete small payload"
    monkeypatch.setitem(model_files.MODEL_HASHES, "small", hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(model_files.MODEL_BYTES, "small", len(data))
    monkeypatch.setattr(model_files, "RETRY_DELAYS", (0, 0))
    settings.model_dir.mkdir()
    target = settings.model_dir / "small.pt"
    target.write_bytes(b"previous corrupt file")
    attempts = []

    def open_model(url, timeout):
        attempts.append(url)
        assert target.read_bytes() == b"previous corrupt file"
        if len(attempts) == 1:
            raise URLError(socket.gaierror(11001, "getaddrinfo failed"))
        if len(attempts) == 2:
            response = Response(data[:5])
            response.headers = {}
            return response
        return Response(data)

    monkeypatch.setattr(model_files, "urlopen", open_model)
    small = client.get("/api/ai/capabilities").json()["models"][2]
    assert small["integrity"] == "invalid" and not small["installed"]
    assert client.post("/api/ai/models/small/download").status_code == 202
    wait(client, "small", "completed")
    assert len(attempts) == 3 and target.read_bytes() == data
    assert list(settings.model_dir.iterdir()) == [target]
    log = (settings.data_dir / "whisper-downloads.log").read_text(encoding="utf-8")
    assert "code=dns" in log and "code=incomplete" in log and "getaddrinfo failed" in log
    assert model_files.MODEL_HASHES["small"] in log
    target.write_bytes(b"invalid after replacement")
    assert client.get("/api/ai/capabilities").json()["models"][2]["integrity"] == "invalid"


@pytest.mark.parametrize(("failure", "code", "message"), [
    (lambda: URLError(socket.gaierror(11001, "getaddrinfo failed")), "dns", "DNS"),
    (lambda: TimeoutError(), "timeout", "tardó"),
    (lambda: HTTPError("https://example.test", 404, "Not Found", {}, None), "http", "HTTP 404"),
])
def test_reports_network_failures_by_cause(client, settings, monkeypatch, failure, code, message):
    monkeypatch.setattr(model_files, "RETRY_DELAYS", ())

    def open_model(url, timeout):
        raise failure()

    monkeypatch.setattr(model_files, "urlopen", open_model)
    assert client.post("/api/ai/models/small/download").status_code == 202
    status = wait(client, "small", "failed")
    assert status["error_code"] == code and message in status["error"]
    assert not list(settings.model_dir.iterdir())


def test_recovers_verified_part_and_only_discards_old_invalid_part_for_requested_model(client, settings, monkeypatch):
    weights = b"intact official model"
    monkeypatch.setitem(model_files.MODEL_HASHES, "small", hashlib.sha256(weights).hexdigest())
    monkeypatch.setitem(model_files.MODEL_BYTES, "small", len(weights))
    settings.model_dir.mkdir()
    incomplete = settings.model_dir / "small.abandoned.part"
    incomplete.write_bytes(b"incomplete")
    old = time.time() - 25 * 3600
    os.utime(incomplete, (old, old))
    other = settings.model_dir / "base.abandoned.part"
    other.write_bytes(b"untouched")
    os.utime(other, (old, old))
    complete = settings.model_dir / "small.interrupted.part"
    complete.write_bytes(weights)

    def no_network(*args, **kwargs):
        pytest.fail("Un temporal verificado se debe reutilizar.")

    monkeypatch.setattr(model_files, "urlopen", no_network)
    assert client.post("/api/ai/models/small/download").status_code == 202
    wait(client, "small", "completed")
    assert (settings.model_dir / "small.pt").read_bytes() == weights
    assert other.exists() and not incomplete.exists() and not complete.exists()
