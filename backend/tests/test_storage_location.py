from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import os
import subprocess
import sys
from time import time

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.services import live, storage
from app.services.direct_capture import CaptureSession, StartRequest
from app.services.direct_buffer import DirectBuffer
from app.services.direct_source import source_from_url
from app.services.obs import LiveError
from app.storage_location import CAPTURE_STOP, DISK_WARN, digest
from test_api import upload
from test_phase3_render import run


@pytest.fixture
def location_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "check_obs_idle", lambda _: None)
    monkeypatch.setattr(storage, "check_obs_idle", lambda _: None)
    monkeypatch.setattr("app.main.check_obs_idle", lambda _: None)
    return Settings(data_dir=tmp_path / "Biblioteca anterior", location_file=tmp_path / "ubicación.json",
                    model_dir=tmp_path / "models", frontend_dir=tmp_path / "no-frontend")


def new_session(settings):
    return TestClient(create_app(settings))


def test_launcher_explains_locked_library_with_existing_server_intact(location_settings):
    with new_session(location_settings) as running:
        env = {**os.environ, "CLIPZONE_STORAGE_CONFIG": str(location_settings.location_file),
               "CLIPZONE_DATA_DIR": str(location_settings.data_dir), "PYTHONUTF8": "1"}
        attempt = subprocess.run([sys.executable, str(ROOT / "scripts" / "serve.py")], env=env, cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=10)
        assert attempt.returncode == 3 and "Otra instancia de ClipZone Studio" in attempt.stderr
        assert str(location_settings.data_dir) in attempt.stderr and "Ctrl+C" in attempt.stderr
        assert running.get("/api/storage").json()["directory"] == str(location_settings.data_dir)


def test_migration_preserves_files_database_and_settings_after_two_restarts(location_settings, tmp_path, sample_video):
    s = location_settings
    source = s.data_dir
    target = tmp_path / "Otra unidad" / "data"
    external = tmp_path / "Original externo.mp4"
    external.write_bytes(b"otro programa")
    with new_session(s) as client:
        video = upload(client, sample_video)
        body = {"video_id": video["id"], "title": "Vídeo exportado", "start": .1, "end": 1, "resolution": 480}
        exported = run(client, "/api/clips", body)
        db = client.app.state.db
        old_video = db.get("videos", video["id"])
        old_hash = digest(Path(old_video["source_path"]))
        db.put("caption_tracks", {"id": video["id"], "segments": [{"text": "Mi transcripción"}]})
        db.put("streamers", {"id": "kick:canal", "url": "https://kick.com/canal", "quality": "best"})
        template = client.post("/api/templates", json={"name": "Mi campaña", "options": {"fit": "split"}}).json()
        legacy_job = {**db.get("jobs", exported["id"]), "id": uuid4().hex, "output_path": str(external)}
        db.put("jobs", legacy_job)
        planned = client.post("/api/storage/location", json={"directory": str(target)})
        assert planned.status_code == 200, planned.text
        assert planned.json()["pending_directory"] == str(target)
        assert source.is_dir() and not target.exists()
    with new_session(s) as client:
        db = client.app.state.db
        stats = client.get("/api/storage").json()
        assert stats["directory"] == str(target)
        assert stats["pending_directory"] is None and stats["migration_warning"] is None
        assert stats["verified_files"] > 0 and stats["free_bytes"] > 0
        assert sorted(item["id"] for item in client.get("/api/videos").json()) == [video["id"]]
        moved = db.get("videos", video["id"])
        for key in ("source_path", "preview_path", "thumbnail_path"):
            assert Path(moved[key]).is_relative_to(target)
        assert digest(Path(moved["source_path"])) == old_hash
        assert client.get(exported["download_url"]).status_code == 200
        assert db.get("caption_tracks", video["id"])["segments"][0]["text"] == "Mi transcripción"
        assert db.get("streamers", "kick:canal")["quality"] == "best"
        assert db.get("templates", template["id"]) == template
        assert db.get("jobs", legacy_job["id"])["output_path"] == str(external)
        assert external.read_bytes() == b"otro programa" and not source.exists()
    # Nueva configuración en memoria, igual que tras un arranque real del proceso.
    restarted = Settings(data_dir=source, location_file=s.location_file, frontend_dir=s.frontend_dir,
                         model_dir=s.model_dir)
    with new_session(restarted) as client:
        assert client.get("/api/storage").json()["directory"] == str(target)
        assert client.get(video["preview_url"]).status_code == 200


def test_migration_rejects_active_capture_and_nonempty_destination(location_settings, tmp_path, monkeypatch):
    with new_session(location_settings) as client:
        url = "/api/storage/location"
        target = tmp_path / "destination"
        direct = client.app.state.direct
        with monkeypatch.context() as patch:
            patch.setattr(direct, "is_active", lambda: True)
            assert client.post(url, json={"directory": str(target)}).status_code == 409
        assert not location_settings.location_file.exists()
        target.mkdir()
        (target / "privado.txt").write_bytes(b"intacto")
        assert client.post(url, json={"directory": str(target)}).status_code == 422
        assert client.post(url, json={"directory": str(location_settings.data_dir / "perdido")}).status_code == 422
        assert (target / "privado.txt").read_bytes() == b"intacto"


def test_checksum_failure_leaves_source_in_service_and_can_cancel(location_settings, tmp_path, sample_video, monkeypatch):
    from app import storage_location

    source = location_settings.data_dir
    target = tmp_path / "Destino fallido"
    with new_session(location_settings) as client:
        video = upload(client, sample_video)
        assert client.post("/api/storage/location", json={"directory": str(target)}).status_code == 200
    copy = storage_location.shutil.copy2

    def broken(src, dst):
        copy(src, dst)
        if dst.suffix == ".mp4":
            dst.write_bytes("copia dañada".encode())

    monkeypatch.setattr(storage_location.shutil, "copy2", broken)
    with new_session(location_settings) as client:
        stats = client.get("/api/storage").json()
        assert stats["directory"] == str(source)
        assert "SHA-256" in stats["migration_error"]
        assert not target.exists()
        assert client.get(video["preview_url"]).status_code == 200
        assert client.post("/api/storage/location", json={"directory": None}).json()["pending_directory"] is None


def test_cleanup_caps_cache_and_retires_only_obsolete_temporary_files(client, settings, monkeypatch):
    monkeypatch.setattr(storage, "DRAFT_LIMIT", 10)
    state = client.app.state
    db = state.db

    def draft(size, age, status="completed"):
        identifier = uuid4().hex
        path = settings.data_dir / "drafts" / f"{identifier}.mp4"
        path.write_bytes(b"x" * size)
        os.utime(path, (time() - age,) * 2)
        db.put("jobs", {"id": identifier, "output_path": str(path), "kind": "draft", "status": status})
        return path

    stale = draft(3, storage.DRAFT_AGE + 10)
    early = draft(6, 30)
    recent = draft(6, 5)
    active = draft(8, 60, "running")
    old_temp = settings.data_dir / "analysis" / f"{uuid4().hex}.pcm"
    old_temp.write_bytes(b"temporal")
    os.utime(old_temp, (time() - storage.TEMP_AGE - 10,) * 2)
    fresh_temp = old_temp.with_suffix(".json")
    fresh_temp.write_bytes(b"en uso reciente")
    storage.cleanup_storage(state)
    assert not stale.exists() and not early.exists() and not old_temp.exists()
    assert recent.exists() and active.exists() and fresh_temp.exists()


def test_disk_thresholds_stop_direct_capture_and_block_new_ones(client, settings, monkeypatch):
    direct = client.app.state.direct
    monkeypatch.setattr(direct, "check_tools", lambda: None)
    monkeypatch.setattr(direct, "disk_free", lambda: CAPTURE_STOP)
    with pytest.raises(LiveError, match="5 GB"):
        direct.start(StartRequest(url="https://kick.com/canal", quality="720p"))
    path = settings.data_dir / "direct-buffer" / uuid4().hex
    path.mkdir()
    session = CaptureSession(source_from_url("https://kick.com/canal"), "720p", DirectBuffer(path))
    direct.run(session)
    assert session.state == "error" and "5 GB" in session.warning
    monkeypatch.setattr(storage, "disk_usage", lambda _: SimpleNamespace(free=DISK_WARN, total=DISK_WARN * 2))
    assert client.get("/api/health").json()["storage"]["free_bytes"] == DISK_WARN
    assert client.get("/api/storage").json()["capture_stop_bytes"] == CAPTURE_STOP
