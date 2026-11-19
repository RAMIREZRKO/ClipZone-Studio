from uuid import uuid4
from base64 import b64decode
import subprocess

import pytest

from app.composition import CAPTION_RENDER_VERSION, CaptionStyle, ass_script
from app.services.media import MediaService
from test_api import upload, wait_job


def make_track(client, video, text="¡Acción en Bogotá! {literal}"):
    result = client.post(f"/api/videos/{video['id']}/captions", json={"segments": [{
        "id": uuid4().hex, "start": .6, "end": 1.6, "text": text,
    }]})
    assert result.status_code == 200, result.text
    return result.json()


def run(client, endpoint, body):
    response = client.post(endpoint, json=body)
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    return job


def test_karaoke_marks_active_word_only_during_timestamp():
    words = [{"start": .15, "end": .46, "text": "¡Hola"},
             {"start": .46, "end": .81, "text": "Bogotá!"}]
    document = ass_script([{"start": .1, "end": 1, "words": words}], CaptionStyle(preset="karaoke"), (480, 854), 10, 22)
    lines = [line for line in document.splitlines() if line.startswith("Dialogue:")]
    assert len(lines) == 4
    assert r"{\1c&H5AF6B1&}¡Hola" in lines[1]
    assert "0:00:00.15,0:00:00.46" in lines[1]
    assert r"{\1c&H5AF6B1&}Bogotá!" in lines[2]
    assert "0:00:00.46,0:00:00.81" in lines[2]
    assert r"\1c" not in lines[0] and r"\1c" not in lines[-1]


@pytest.mark.parametrize("ratio,preset,dimensions", [
    ("9:16", "hormozi", (480, 854)), ("1:1", "minimal", (480, 480)),
    ("4:5", "karaoke", (480, 600)), ("16:9", "classic", (854, 480)),
])
@pytest.mark.parametrize("fit", ["contain", "cover", "blur"])
def test_crisp_burn_in_sidecars_and_exact_preview(client, settings, sample_video, tmp_path, ratio, preset, dimensions, fit):
    video = upload(client, sample_video)
    track = make_track(client, video)
    body = {"video_id": video["id"], "start": .35, "end": 1.85, "resolution": 480, "ratio": ratio,
            "fit": fit, "captions": {"revision": track["revision"], "style": {"preset": preset,
            "background_opacity": 64 if preset == "minimal" else 0}}}
    draft = run(client, "/api/clips/preview", body)
    exported = run(client, "/api/clips", body)
    preview = client.get(draft["preview_url"]).content
    assert preview == client.get(exported["download_url"]).content
    output = tmp_path / "áé clip.mp4"
    output.write_bytes(preview)
    info = MediaService(settings).probe(output)
    assert (info["width"], info["height"]) == dimensions and info["has_audio"]
    assert info["duration"] == pytest.approx(1.5, abs=.1)
    srt = client.get(exported["subtitles"]["srt"]).text
    vtt = client.get(exported["subtitles"]["vtt"]).text
    assert "00:00:00,250 --> 00:00:01,250" in srt and "¡Acción en Bogotá! {literal}" in srt
    assert vtt.startswith("WEBVTT") and "00:00:00.250 --> 00:00:01.250" in vtt

    plain = run(client, "/api/clips", {**body, "captions": {"revision": track["revision"], "enabled": False}})
    uncaptioned = tmp_path / "plain.mp4"
    uncaptioned.write_bytes(client.get(plain["download_url"]).content)
    assert plain["subtitles"]  # Sidecars can be exported independently.
    def frame_hash(file):
        return subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-ss", "0.6", "-i",
                               str(file), "-map", "0:v:0", "-frames:v", "1", "-f", "hash", "-"],
                              capture_output=True, check=True).stdout
    assert frame_hash(output) != frame_hash(uncaptioned)


def test_live_layer_has_correct_box_transparency_and_stays_within_the_canvas_safe_area(client, settings, tmp_path):
    body = {"ratio": "16:9", "resolution": 480, "start": .81, "end": 3, "time": .4,
            "safe_top": 35, "safe_bottom": 40, "style": {
                "color": "#ff00ff", "position": 100, "outline": 6, "shadow": 8,
                "background": "#00ee00", "background_opacity": 64,
            }, "segment": {"id": uuid4().hex, "start": .1, "end": 2.8, "text": "¡Límite de zona segura!"}}
    response = client.post("/api/captions/layer", json=body)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["start"] == 0 and page["end"] == pytest.approx(1.99)
    assert page["frames"] == [{"start": 0, "end": 1.99, "image": 0}]
    output = tmp_path / "capa.png"
    output.write_bytes(b64decode(page["images"][0]))
    data = subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-i", str(output),
                           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-threads", "1", "-"],
                          check=True, capture_output=True).stdout
    width, height = 854, 480
    assert len(data) == width * height * 4
    visible = [(i // (width * 4), tuple(data[i:i + 4])) for i in range(0, len(data), 4) if data[i + 3] > 0]
    assert visible and all(height * .35 <= y < height * .60 for y, pixel in visible)
    assert any(r < 12 and g >= 220 and b < 12 and 161 <= a <= 165 for y, (r, g, b, a) in visible)
    assert any(r >= 235 and g < 12 and b >= 235 and a == 255 for y, (r, g, b, a) in visible)


def test_exact_preview_invalidates_caption_style_revision_and_legacy_cache(client, sample_video):
    video = upload(client, sample_video)
    track = make_track(client, video)
    body = {"video_id": video["id"], "start": .5, "end": 1.7, "resolution": 480,
            "captions": {"revision": track["revision"], "style": {"position": 80}}}
    preview = run(client, "/api/clips/preview", body)
    assert preview["settings"]["caption_render_version"] == CAPTION_RENDER_VERSION
    assert client.post("/api/clips/preview", json=body).json()["id"] == preview["id"]
    styled = {**body, "captions": {**body["captions"], "style": {"position": 20, "size": 82, "align": "left"}}}
    changed = run(client, "/api/clips/preview", styled)
    assert changed["id"] != preview["id"]
    assert client.get(changed["preview_url"]).content != client.get(preview["preview_url"]).content

    updated = client.post(f"/api/videos/{video['id']}/captions", json={
        "revision": track["revision"], "segments": [{**track["segments"][0], "text": "Texto corregido"}],
    }).json()
    assert client.post("/api/clips/preview", json=styled).status_code == 409
    revised = {**styled, "captions": {**styled["captions"], "revision": updated["revision"]}}
    fresh = run(client, "/api/clips/preview", revised)
    assert fresh["id"] != changed["id"]
    db = client.app.state.db
    legacy = db.get("jobs", fresh["id"])
    legacy["settings"].pop("caption_render_version")
    db.put("jobs", legacy)
    assert run(client, "/api/clips/preview", revised)["id"] != legacy["id"]
