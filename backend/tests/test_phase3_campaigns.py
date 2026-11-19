import hashlib
import struct
import subprocess
from uuid import uuid4
import zlib

from test_api import upload, wait_job
from test_phase3_render import make_track, run


def rgba_png(color):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    w = h = 32
    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    row = b"\0" + bytes(color) * 16 + b"\0" * 64
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(row * h)) + chunk(b"IEND", b"")


def asset(client, name, red):
    picture = rgba_png((245, 16, 16, 255) if red else (20, 235, 15, 255))
    result = client.post("/api/assets", files={"file": (name, picture, "image/png")})
    assert result.status_code == 201, result.text
    assert client.get(result.json()["url"]).content == picture
    return result.json()["id"]


def test_layers_with_alpha_timing_templates_and_multi_render(client, settings, sample_video, tmp_path):
    video = upload(client, sample_video)
    track = make_track(client, video, text="Material de campaña")
    one = asset(client, "Logo Ñ 01.png", True)
    two = asset(client, "Logo 02.png", False)
    assert client.post("/api/assets", files={"file": ("broken.png", b"fake png", "image/png")}).status_code == 415
    assert len(client.get("/api/templates").json()) == 2
    examples = client.get("/api/templates").json()
    assert {item["name"] for item in examples} == {"Campaña de YouTube", "Campaña de Kick"}
    assert all(item["options"]["graphics"][0]["asset_id"] is None for item in examples)

    graphics = [
        {"id": uuid4().hex, "kind": "image", "name": "Marca Á", "asset_id": one, "x": 26, "y": 24, "size": 26, "start": .3, "end": .9},
        {"id": uuid4().hex, "kind": "image", "asset_id": two, "x": 80, "y": 70, "size": 22, "opacity": 75},
        {"id": uuid4().hex, "kind": "text", "text": "Vívelo aquí", "x": 50, "y": 35, "size": 52},
        {"id": uuid4().hex, "kind": "text", "text": "Sigue el canal {texto}", "x": 50, "y": 75, "size": 40},
    ]
    options = {"resolution": 480, "ratio": "9:16", "fit": "blur", "graphics": graphics,
               "captions": {"revision": track["revision"], "style": {"preset": "hormozi"}}}
    stored = client.post("/api/templates", json={"name": "Mi campaña Ñ", "options": options})
    assert stored.status_code == 200, stored.text
    template = stored.json()
    assert template["options"]["captions"]["revision"] is None
    assert client.get("/api/templates").json()[-1]["id"] == template["id"]
    updated = client.post("/api/templates", json={"id": template["id"], "name": "Campaña actualizada", "options": options})
    assert updated.json()["id"] == template["id"]

    body = {**options, "video_id": video["id"], "start": .4, "end": 1.85}
    draft = run(client, "/api/clips/preview", body)
    output = run(client, "/api/clips", body)
    media = client.get(output["download_url"]).content
    assert hashlib.sha256(media).digest() == hashlib.sha256(client.get(draft["preview_url"]).content).digest()
    rendered = tmp_path / "Vídeo de campaña Ñ.mp4"
    rendered.write_bytes(media)

    def pixel(second, x, y):
        return tuple(subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-ss", str(second), "-i",
                                     str(rendered), "-vf", f"format=rgb24,crop=1:1:{x}:{y}", "-frames:v",
                                     "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout[:3])

    visible = pixel(.5, 92, 200)
    transparent = pixel(.5, 161, 200)
    assert visible[0] > 210 and visible[1] < 45 and visible[2] < 45
    assert transparent != visible and pixel(.12, 92, 200) != visible and pixel(1.05, 92, 200) != visible
    assert pixel(.5, 345, 590)[1] > 130
    assert client.get("/api/storage").json()["graphics_bytes"] > 0

    analysis = uuid4().hex
    moments = [{"id": uuid4().hex, "start": .2, "end": 1.35, "title": "Primero", "score": 90},
               {"id": uuid4().hex, "start": .9, "end": 2.3, "title": "Segundo", "score": 83}]
    client.app.state.db.put("analyses", {"id": analysis, "video_id": video["id"], "status": "completed",
                                        "result": {"moments": moments}})
    batch = client.post("/api/clips/batch", json={**template["options"], "captions": options["captions"],
                                                  "analysis_id": analysis, "moment_ids": [m["id"] for m in moments]})
    assert batch.status_code == 202, batch.text
    for row in batch.json()["jobs"]:
        finished = wait_job(client, row["id"])
        assert finished["status"] == "completed", finished
        assert finished["settings"]["graphics"][0]["asset_id"] == one
        assert client.get(finished["download_url"]).status_code == 200
