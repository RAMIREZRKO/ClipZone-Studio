import json
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from test_api import upload
from test_phase3_render import run


def track_from_whisper(client, sample_video):
    video = upload(client, sample_video)
    analysis = {"id": uuid4().hex, "video_id": video["id"], "status": "completed",
                "result": {"transcript": {"language": "es", "words": [
                    {"start": .5, "end": .75, "text": "¡Hola!"},
                    {"start": 1.1, "end": 1.7, "text": "Despedida."},
                ]}}}
    client.app.state.db.put("analyses", analysis)
    path = f"/api/videos/{video['id']}/captions"
    track = client.post(path + "/generate", json={"analysis_id": analysis["id"]}).json()
    return video, analysis, path, track


@pytest.mark.parametrize("kind,content", [
    ("srt", "1\r\n00:00:10,000 --> 00:00:11,000\r\nHello Bogotá!\r\n\r\n2\r\n00:00:12,000 --> 00:00:13,000\r\nGoodbye.\r\n"),
    ("vtt", "WEBVTT\n\n00:10.000 --> 00:11.000\nHello Bogotá!\n\n00:12.000 --> 00:13.000\nGoodbye."),
])
def test_import_translation_preserves_original_and_exports_target(client, sample_video, kind, content):
    video, analysis, path, track = track_from_whisper(client, sample_video)
    bad = client.post(path + "/translation/import", json={"revision": track["revision"], "language": "en",
                                                          "content": "1\n00:00:00,000 --> 00:00:01,000\nOnly one cue"})
    assert bad.status_code == 422
    imported = client.post(path + "/translation/import", json={"revision": track["revision"], "language": "en", "content": content})
    assert imported.status_code == 200, imported.text
    updated = imported.json()
    for before, translated in zip(track["segments"], updated["segments"]):
        assert {k: value for k, value in before.items() if k != "translations"} == {
            k: value for k, value in translated.items() if k != "translations"
        }
    assert updated["segments"][0]["translations"]["en"] == "Hello Bogotá!"
    assert client.app.state.db.get("analyses", analysis["id"]) == analysis

    exported = run(client, "/api/clips", {"video_id": video["id"], "start": .3, "end": 1.8, "resolution": 480,
        "captions": {"revision": updated["revision"], "language": "en", "style": {"preset": "karaoke"}}})
    sidecar = client.get(exported["subtitles"][kind]).text
    assert "Hello Bogotá!" in sidecar and "¡Hola!" not in sidecar
    assert ("00:00:00,200" if kind == "srt" else "00:00:00.200") in sidecar


def test_optional_translator_unavailable_and_adapter_bound_to_target(client, sample_video, monkeypatch):
    _, _, path, track = track_from_whisper(client, sample_video)
    monkeypatch.setattr("app.translation.argos_python", lambda: None)
    body = {"revision": track["revision"], "language": "en", "segment_ids": [track["segments"][0]["id"]]}
    response = client.post(path + "/translation/local", json=body)
    assert response.status_code == 503
    assert client.get(path).json() == track

    def installed_pair(source, target, texts):
        assert (source, target, texts) == ("es", "en", ["¡Hola!"])
        return ["Hello!"]

    monkeypatch.setattr("app.captions.translate_local", installed_pair)
    result = client.post(path + "/translation/local", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["segments"][0]["translations"] == {"en": "Hello!"}
    assert result.json()["segments"][1]["translations"] == {}


def test_existing_database_loads_without_phase3_fields(settings):
    settings.data_dir.mkdir()
    db = settings.data_dir / "clipzone.sqlite3"
    video = {"id": uuid4().hex, "name": "Anterior.mp4", "duration": 2.5, "preview_status": "ready"}
    job = {"id": uuid4().hex, "kind": "export", "status": "completed", "output_path": "old.mp4",
           "settings": {"ratio": "16:9", "fit": "cover"}}
    with sqlite3.connect(db) as conn:
        for table in ("videos", "jobs", "analyses", "removals"):
            conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("INSERT INTO videos VALUES (?,?)", (video["id"], json.dumps(video)))
        conn.execute("INSERT INTO jobs VALUES (?,?)", (job["id"], json.dumps(job)))
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/videos").json()[0]["id"] == video["id"]
        assert client.get("/api/jobs").json()[0]["settings"] == job["settings"]
        assert client.get(f"/api/videos/{video['id']}/captions").json()["segments"] == []
        assert len(client.get("/api/templates").json()) == 2
