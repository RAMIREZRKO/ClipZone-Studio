import pytest

from app.services.media import MediaService
from test_api import upload, wait_job


@pytest.mark.parametrize("ratio,dimensions", [
    ("9:16", (480, 854)), ("1:1", (480, 480)), ("4:5", (480, 600)), ("16:9", (854, 480)),
])
@pytest.mark.parametrize("fit", ["contain", "cover", "blur"])
def test_exact_preview_matches_export(client, settings, sample_video, tmp_path, ratio, dimensions, fit):
    video = upload(client, sample_video)
    body = {"video_id": video["id"], "start": .4, "end": 1.3, "fit": fit, "ratio": ratio,
            "resolution": 480, "blur_strength": 67, "focus_x": 24}
    response = client.post("/api/clips/preview", json=body)
    assert response.status_code == 202, response.text
    preview = wait_job(client, response.json()["id"])
    assert preview["status"] == "completed", preview
    assert client.post("/api/clips/preview", json={**body, "title": "Otro nombre"}).json()["id"] == preview["id"]
    assert preview["download_url"] is None
    export = client.post("/api/clips", json=body)
    job = wait_job(client, export.json()["id"])
    assert job["status"] == "completed", job
    preview_bytes = client.get(preview["preview_url"]).content
    export_bytes = client.get(job["download_url"]).content
    assert preview_bytes and export_bytes == preview_bytes
    output = tmp_path / "preview.mp4"
    output.write_bytes(preview_bytes)
    info = MediaService(settings).probe(output)
    assert (info["width"], info["height"]) == dimensions
    assert info["has_audio"]
