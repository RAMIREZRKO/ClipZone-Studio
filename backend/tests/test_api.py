import hashlib
import subprocess
import time
from pathlib import Path
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import ClipRequest
from app.services.media import MediaService


def upload(client, sample):
    with sample.open("rb") as file:
        response = client.post("/api/videos", files={"file": (sample.name, file, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()


def wait_job(client, identifier):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{identifier}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    pytest.fail("El trabajo no terminó en 45 segundos.")


def test_health_and_empty_library(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["ai_enabled"] is False
    assert client.get("/api/videos").json() == []
    assert client.get("/api/jobs").json() == []


def test_upload_probe_stream_ranges_and_persistence(client, settings, sample_video):
    digest = hashlib.sha256(sample_video.read_bytes()).hexdigest()
    video = upload(client, sample_video)
    assert video["width"] == 640 and video["height"] == 360
    assert video["duration"] == pytest.approx(3, abs=0.1)
    assert video["has_audio"] is True
    assert video["preview_status"] == "ready"
    assert not any(k.endswith("_path") for k in video)
    response = client.get(video["preview_url"], headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100
    assert client.get(video["thumbnail_url"]).headers["content-type"] == "image/jpeg"
    assert hashlib.sha256(sample_video.read_bytes()).hexdigest() == digest
    with TestClient(create_app(settings)) as reopened:
        assert reopened.get("/api/videos").json()[0]["id"] == video["id"]


@pytest.mark.parametrize("ratio,width,height", [("9:16", 480, 854), ("1:1", 480, 480), ("4:5", 480, 600), ("16:9", 854, 480)])
@pytest.mark.parametrize("fit", ["contain", "cover"])
def test_real_export_all_ratios_and_fits(client, settings, sample_video, ratio, width, height, fit):
    video = upload(client, sample_video)
    response = client.post("/api/clips", json={"video_id": video["id"], "title": "Clip de prueba", "start": 0.5, "end": 1.7,
                        "ratio": ratio, "resolution": 480, "fit": fit, "focus_x": 20, "focus_y": 80})
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    assert job["progress"] == 100
    assert "output_path" not in job
    output = settings.data_dir / "result.mp4"
    download = client.get(job["download_url"])
    assert download.status_code == 200
    assert 'attachment;' in download.headers["content-disposition"]
    output.write_bytes(download.content)
    metadata = MediaService(settings).probe(output)
    assert (metadata["width"], metadata["height"]) == (width, height)
    assert metadata["duration"] == pytest.approx(1.2, abs=0.15)
    assert metadata["codec"] == "h264"
    assert metadata["audio_codec"] == "aac"
    assert metadata["pixel_format"] == "yuv420p"
    assert client.get(job["preview_url"], headers={"Range": "bytes=0-999"}).status_code == 206


def test_invalid_upload_and_cleanup(client, settings):
    assert client.post("/api/videos", files={"file": ("danger.exe", b"MZ")}).status_code == 415
    assert client.post("/api/videos", files={"file": ("empty.mp4", b"")}).status_code == 422
    assert client.post("/api/videos", files={"file": ("fake.mp4", b"not a video")}).status_code == 422
    assert client.get("/api/videos").json() == []
    assert not list((settings.data_dir / "uploads").iterdir())


def test_upload_limit(client, settings):
    settings.max_upload_bytes = 8
    response = client.post("/api/videos", files={"file": ("large.mp4", b"x" * 9)})
    assert response.status_code == 413
    assert not list((settings.data_dir / "uploads").iterdir())


@pytest.mark.parametrize("changes", [{"start": -1}, {"end": 0}, {"start": 2, "end": 1}, {"end": 50}, {"resolution": 999},
                                     {"ratio": "3:2"}, {"fit": "stretch"}, {"safe_bottom": 99}, {"focus_x": -1}])
def test_invalid_clip_settings(client, sample_video, changes):
    video = upload(client, sample_video)
    assert client.post("/api/clips", json={"video_id": video["id"], "start": 0, "end": 1, **changes}).status_code == 422


def test_missing_media_and_untrusted_origin(client):
    assert client.get("/api/videos/missing/preview").status_code == 404
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/jobs/../../secret/download").status_code == 404
    assert client.post("/api/videos", headers={"origin": "https://untrusted.example"}).status_code == 403


def test_silent_video_and_mkv_proxy(client, settings, tmp_path):
    source = tmp_path / "sin audio.mkv"
    subprocess.run([settings.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=green:size=320x240:rate=24", "-t", "1", "-c:v", "libx264", str(source)], check=True, timeout=20)
    video = upload(client, source)
    assert video["has_audio"] is False
    assert video["preview_status"] == "processing"
    proxy = client.get("/api/jobs").json()[0]
    assert wait_job(client, proxy["id"])["status"] == "completed"
    ready = client.get("/api/videos").json()[0]
    assert ready["preview_status"] == "ready"
    assert client.get(ready["preview_url"]).status_code == 200
    response = client.post("/api/clips", json={"video_id": video["id"], "start": 0, "end": .5, "resolution": 480})
    assert wait_job(client, response.json()["id"])["status"] == "completed"


def test_anamorphic_normalization(client, settings, tmp_path):
    source = tmp_path / "anamorphic.mp4"
    subprocess.run([settings.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=720x576:rate=24", "-t", "1", "-vf", "setsar=64/45", "-c:v", "libx264", str(source)], check=True, timeout=20)
    video = upload(client, source)
    response = client.post("/api/clips", json={"video_id": video["id"], "start": 0, "end": .5, "resolution": 480, "ratio": "16:9"})
    job = wait_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    path = settings.data_dir / "exports" / next((settings.data_dir / "exports").iterdir()).name
    result = subprocess.run([settings.binary("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=sample_aspect_ratio", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "1:1"


def test_nonfinite_and_long_durations_rejected():
    with pytest.raises(ValidationError):
        ClipRequest(video_id="a" * 32, start=float("nan"), end=10)
    with pytest.raises(ValidationError):
        ClipRequest(video_id="a" * 32, start=0, end=3601)
