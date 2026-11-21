import sys

import pytest
import uvicorn

from app.config import APP_VERSION, instance_identity
from scripts import serve


def test_instance_identifies_the_running_workspace_and_library(client, settings):
    response = client.get("/api/instance")
    assert response.json() == instance_identity(settings.data_dir)
    assert response.json()["version"] == APP_VERSION


def test_open_reuses_correct_server_without_checks_or_a_second_start(monkeypatch, settings):
    opened = []
    monkeypatch.setattr(sys, "argv", ["serve.py", "--open", "--check"])
    monkeypatch.setattr(serve, "Settings", lambda: settings)
    monkeypatch.setattr(serve, "local_json", lambda _: instance_identity(settings.data_dir))
    monkeypatch.setattr(serve, "open_browser", lambda: opened.append(serve.URL) or True)

    def unexpected(*args, **kwargs):
        pytest.fail("El iniciador debe reutilizar el servidor que ya está en ejecución.")

    monkeypatch.setattr(uvicorn, "run", unexpected)
    monkeypatch.setattr(serve.subprocess, "run", unexpected)
    assert serve.main() == 0
    assert opened == ["http://127.0.0.1:8000"]


def test_old_server_is_reported_without_opening_it(monkeypatch, settings, capsys):
    monkeypatch.setattr(sys, "argv", ["serve.py"])
    monkeypatch.setattr(serve, "Settings", lambda: settings)
    monkeypatch.setattr(serve, "port_occupied", lambda: True)
    monkeypatch.setattr(serve, "local_json", lambda endpoint: None if endpoint == "/api/instance" else {
        "version": "0.3.0", "max_upload_bytes": 20 * 1024**3,
    })
    assert serve.main() == 3
    assert "sigue usando ClipZone Studio 0.3.0" in capsys.readouterr().err


def test_cold_start_waits_for_matching_workspace_and_library(monkeypatch, settings):
    other = instance_identity(settings.data_dir.parent / "otra-biblioteca")
    incoming = iter([None, other, instance_identity(settings.data_dir)])
    opened = []
    monkeypatch.setattr(serve, "local_json", lambda _: next(incoming))
    monkeypatch.setattr(serve.time, "sleep", lambda _: None)
    monkeypatch.setattr(serve, "open_browser", lambda: opened.append(serve.URL) or True)
    serve.open_when_ready(settings)
    assert opened == [serve.URL]
