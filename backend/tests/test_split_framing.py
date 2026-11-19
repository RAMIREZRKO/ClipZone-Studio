from base64 import b64decode
from array import array
import json
import subprocess
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.composition import CaptionStyle, caption_position
from app.models import RenderOptions
from app.split_layout import EMPTY_GAMEPLAY, SPLIT_RENDER_VERSION, PixelRect, SourceGeometry, SourceRect, SplitLayout, split_geometry
from test_api import upload, wait_job
from test_phase3_campaigns import asset
from test_phase3_render import make_track, run


LAYOUT = {
    "camera_share": 25, "inverted": False,
    "camera": {"rect": {"x": .1, "y": .1, "width": .2, "height": .4},
               "zoom": 200, "pan_x": 100, "fit": "contain"},
    "gameplay": {"rect": {"x": .5, "y": 0, "width": .5, "height": 1}, "fit": "blur"},
}


@pytest.fixture
def horizontal_gameplay(settings, tmp_path):
    path = tmp_path / "Cámara y gameplay.mp4"
    # La cámara ocupa una esquina y tiene dos colores para distinguir zoom y desplazamiento.
    source = ("color=blue:size=640x360:rate=24,drawbox=64:36:128:144:color=red:t=fill,"
              "drawbox=128:36:64:144:color=lime:t=fill,"
              "drawbox=320:0:320:360:color=white:t=fill:enable='between(t,0.9,1.2)'")
    subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", source,
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-af", "volume='between(t,0.9,1.2)':eval=frame",
                    "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
                   capture_output=True, check=True, timeout=25)
    return path


def frame(settings, path):
    return subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-ss", "0.5", "-i", str(path),
                           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "-"],
                          check=True, capture_output=True, timeout=25).stdout


def test_layout_bounds_defaults_and_safe_seam():
    assert RenderOptions().split_layout is None
    defaults = RenderOptions(fit="split")
    assert defaults.caption_seam() == 480
    legacy = SplitLayout.model_validate({**LAYOUT, "camera_exclusion": "off"}).model_dump()
    assert "fit" not in legacy["camera"] and "camera_exclusion" not in legacy
    options = RenderOptions(fit="split", split_layout={**LAYOUT, "camera_share": 27.3, "inverted": True})
    assert options.caption_seam() == 1396
    with pytest.raises(ValidationError, match="dentro del vídeo"):
        RenderOptions(fit="split", split_layout={"camera": {"rect": {"x": .8, "width": .5}}})
    style = CaptionStyle(anchor="split")
    assert r"\pos(540,480)" in caption_position(style, (1080, 1920), 10, 22, 480)
    assert r"\pos(540,745)" in caption_position(style, (1080, 1920), 35, 22, 480)
    custom = CaptionStyle(anchor="split", position_x=70)
    assert r"\pos(756,480)" in caption_position(custom, (1080, 1920), 10, 22, 480)


@pytest.mark.parametrize("ratio,resolution,dimensions,inverted,game_fit", [
    ("9:16", 1080, (1080, 1920), False, "blur"),
    ("1:1", 480, (480, 480), True, "cover"),
    ("4:5", 480, (480, 600), False, "contain"),
    ("16:9", 480, (854, 480), True, "blur"),
])
def test_split_preview_export_composition(client, settings, tmp_path, horizontal_gameplay,
                                          ratio, resolution, dimensions, inverted, game_fit):
    video = upload(client, horizontal_gameplay)
    track = make_track(client, video, "Cámara y gameplay")
    logo = asset(client, "Logo de prueba.png", True)
    width, height = dimensions
    seam = height * (3 if inverted else 1) // 4
    body = {"video_id": video["id"], "start": .2, "end": 1.7, "fit": "split", "ratio": ratio,
            "resolution": resolution, "safe_top": 0, "safe_bottom": 0,
            "split_layout": {**LAYOUT, "inverted": inverted, "gameplay": {**LAYOUT["gameplay"], "fit": game_fit}},
            "captions": {"revision": track["revision"], "style": {"anchor": "split", "color": "#ff00ff"}},
            "graphics": [
                {"id": uuid4().hex, "kind": "text", "text": "Promo", "x": 80, "y": 55,
                 "size": 45, "color": "#ffff00"},
                {"id": uuid4().hex, "kind": "image", "asset_id": logo, "x": 26,
                 "y": 50 if inverted else 60, "size": 20},
            ]}
    exact = run(client, "/api/clips/preview", body)
    exported = run(client, "/api/clips", body)
    output = tmp_path / "exportado.mp4"
    output.write_bytes(client.get(exported["download_url"]).content)
    assert client.get(exact["preview_url"]).content == output.read_bytes()
    info = json.loads(subprocess.run([settings.binary("ffprobe"), "-v", "error", "-show_streams",
                                      "-of", "json", str(output)], check=True, capture_output=True).stdout)
    picture, audio = info["streams"]
    assert (picture["width"], picture["height"], picture["sample_aspect_ratio"]) == (*dimensions, "1:1")
    assert audio["codec_name"] == "aac"
    for stream in [picture, audio]:
        assert float(stream["start_time"]) == pytest.approx(0, abs=.04)
        assert float(stream["duration"]) == pytest.approx(1.5, abs=.06)

    pixels = frame(settings, output)
    def pixel(x, y):
        offset = 3 * (y * width + x)
        return tuple(pixels[offset:offset + 3])

    camera_y, game_y = (height * 7 // 8, height * 3 // 8) if inverted else (height // 8, height * 5 // 8)
    assert pixel(int(width * .9), camera_y)[1] > 200  # El zoom se desplaza a la parte verde.
    assert pixel(width // 2, game_y)[2] > 200
    assert pixel(int(width * .05), camera_y)[1] > 200  # Llenar también se aplica a plantillas antiguas.
    logo_y = height // 2 if inverted else height * 3 // 5
    red, green, blue = pixel(round(width * .22), logo_y)
    assert red > 200 and max(green, blue) < 60
    assert pixel(round(width * .31), logo_y)[2] > 200  # Mitad transparente del PNG.
    ys = [i // 3 // width for i in range(0, len(pixels), 3)
          if pixels[i] > 175 and pixels[i + 1] < 75 and pixels[i + 2] > 175]
    assert ys and abs((min(ys) + max(ys)) / 2 - seam) < height * .035
    assert any(pixels[i] > 200 and pixels[i + 1] > 200 and pixels[i + 2] < 100 for i in range(0, len(pixels), 3))
    if resolution == 1080:
        ffmpeg = [settings.binary("ffmpeg"), "-v", "error", "-i", str(output)]
        signal = subprocess.run([*ffmpeg, "-an", "-vf", "crop=2:2:540:1152,scale=1:1",
                                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "-"],
                                check=True, capture_output=True, timeout=25).stdout
        flash = next(i / 3 / 24 for i in range(0, len(signal), 3) if min(signal[i:i+3]) > 200)
        pcm = subprocess.run([*ffmpeg, "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                             check=True, capture_output=True, timeout=25).stdout
        tone = next(i / 48000 for i, value in enumerate(array("h", pcm)) if abs(value) > 600)
        assert flash == pytest.approx(.7, abs=.06)
        assert tone == pytest.approx(flash, abs=.06)


def test_split_updates_exact_cache_and_live_caption_layer(client, settings, tmp_path, sample_video):
    video = upload(client, sample_video)
    track = make_track(client, video)
    style = {"anchor": "split"}
    options = {"fit": "split", "resolution": 480, "captions": {"revision": track["revision"], "style": style}}
    body = {**options, "video_id": video["id"], "start": .3, "end": 1.8}
    first = run(client, "/api/clips/preview", body)
    assert first["settings"]["split_render_version"] == SPLIT_RENDER_VERSION
    assert client.post("/api/clips/preview", json=body).json()["id"] == first["id"]
    db = client.app.state.db
    legacy = db.get("jobs", first["id"])
    legacy["settings"].pop("split_render_version")
    db.put("jobs", legacy)
    assert run(client, "/api/clips/preview", body)["id"] != first["id"]
    second = run(client, "/api/clips/preview", {**body, "split_layout": {"inverted": True, "camera_share": 40}})
    assert first["id"] != second["id"]
    layer = client.post("/api/captions/layer", json={**options, "split_layout": {"inverted": True, "camera_share": 40},
                        "style": style, "segment": track["segments"][0], "start": .3, "end": 1.8, "time": .5})
    assert layer.status_code == 200, layer.text
    png = tmp_path / "subtítulos.png"
    png.write_bytes(b64decode(layer.json()["images"][0]))
    data = subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-i", str(png), "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "rgba", "-threads", "1", "-"],
                          check=True, capture_output=True).stdout
    ys = [i // (480 * 4) for i in range(3, len(data), 4) if data[i] > 127]
    assert ys and abs((min(ys) + max(ys)) / 2 - 512) < 12


def test_camera_cover_fills_every_distribution_without_sampling_outside_its_rect(client, settings, tmp_path):
    original = tmp_path / "cámara con bordes impares.mp4"
    source = ("color=blue:size=640x360:rate=24,drawbox=65:37:128:144:color=red:t=fill,"
              "drawbox=119:99:20:20:color=lime:t=fill")
    subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", "0.8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(original)], check=True, timeout=20)
    video = upload(client, original)
    for share in (20, 25, 30, 40, 50):
        layout = SplitLayout(camera_share=share, camera={"rect": {"x": 65 / 640, "y": 37 / 360,
                                                                    "width": 128 / 640, "height": 144 / 360}})
        body = {"video_id": video["id"], "start": 0, "end": .7, "fit": "split", "resolution": 480,
                "split_layout": layout.model_dump(mode="json")}
        exact = run(client, "/api/clips/preview", body)
        output = tmp_path / f"cámara {share}.mp4"
        output.write_bytes(client.get(exact["preview_url"]).content)
        height = layout.camera_height(854)
        camera_pixels = frame(settings, output)[:3 * 480 * height]
        assert len(camera_pixels) == 3 * 480 * height
        assert max(camera_pixels[2::3]) < 75, share
        assert min(red + green for red, green in zip(camera_pixels[::3], camera_pixels[1::3])) > 125, share
        marker = [index for index, (red, green) in enumerate(zip(camera_pixels[::3], camera_pixels[1::3]))
                  if green > 180 and red < 65]
        xs = [index % 480 for index in marker]
        ys = [index // 480 for index in marker]
        assert abs((max(xs) - min(xs)) - (max(ys) - min(ys))) <= 2, share


def test_exclusion_moves_or_zooms_the_gameplay_inside_the_selected_bounds():
    source = SourceGeometry(width=640, height=360, display_width=640)
    layout = SplitLayout(camera={"rect": {"x": .1, "y": 40 / 360, "width": .125, "height": 80 / 360}},
                         gameplay={"pan_x": -100})
    assert split_geometry(layout, (480, 854), source)[1].crop == PixelRect(144, 0, 270, 360)
    layout.camera.rect = SourceRect(x=.25, width=.5)
    assert split_geometry(layout, (480, 854), source)[1].crop == PixelRect(0, 74, 160, 212)
    layout.gameplay.pan_x = 100
    assert split_geometry(layout, (480, 854), source)[1].crop == PixelRect(480, 74, 160, 212)


def test_fully_covered_gameplay_is_rejected_before_enqueuing(client, sample_video):
    video = upload(client, sample_video)
    rect = {"x": .25, "y": .25, "width": .5, "height": .5}
    body = {"video_id": video["id"], "start": 0, "end": .7, "fit": "split",
            "split_layout": {"camera": {"rect": rect}, "gameplay": {"rect": rect}}}
    for endpoint in ("/api/clips/preview", "/api/clips"):
        response = client.post(endpoint, json=body)
        assert response.status_code == 422
        assert response.json()["detail"] == EMPTY_GAMEPLAY


@pytest.mark.parametrize("share,inverted", [(25, False), (50, True), (90, False)])
def test_strict_exclusion_matches_exact_and_export(client, settings, tmp_path, share, inverted):
    original = tmp_path / "gameplay.mp4"
    source = "color=blue:size=640x360:rate=24,drawbox=64:40:80:80:color=white:t=fill,"
    source += ",".join(f"drawbox={x}:40:8:80:color=black:t=fill" for x in range(64, 144, 16))
    source += ",drawbox=180:160:20:20:color=lime:t=fill"
    subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", "0.8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(original)], check=True, timeout=20)
    video = upload(client, original)
    if inverted:
        db = client.app.state.db
        legacy = db.get("videos", video["id"])
        legacy.pop("display_width")
        db.put("videos", legacy)
        assert client.get(f"/api/videos/{video['id']}/geometry").json() == {
            "width": 640, "height": 360, "display_width": 640,
        }
    clip = {"video_id": video["id"], "start": 0, "end": .7, "fit": "split", "resolution": 480,
            "split_layout": {"camera_share": share, "inverted": inverted,
                             "camera": {"rect": {"x": .1, "y": 40 / 360, "width": .125, "height": 80 / 360}},
                             "gameplay": {"pan_x": -100}}}
    exact = run(client, "/api/clips/preview", clip)
    export = run(client, "/api/clips", clip)
    output = tmp_path / "exportado.mp4"
    output.write_bytes(client.get(export["download_url"]).content)
    assert output.read_bytes() == client.get(exact["preview_url"]).content
    pixels = frame(settings, output)

    camera_height = SplitLayout(camera_share=share).camera_height(854)
    start = 0 if inverted else camera_height
    stop = 854 - camera_height if inverted else 854
    # The gameplay contains only the blue source and the green marker, with no camera stripes or borders.
    panel = pixels[(start + 2) * 480 * 3:(stop - 2) * 480 * 3]
    # Allow isolated codec ringing at the blue/green boundary of the marker.
    unexpected = sum(red >= 55 or max(green, blue) <= 110
                     for red, green, blue in zip(panel[::3], panel[1::3], panel[2::3]))
    assert unexpected < len(panel) / 3000
    assert max(panel[1::3]) > 200


def test_streamer_template_persists_for_batch_export(client, horizontal_gameplay):
    video = upload(client, horizontal_gameplay)
    response = client.post("/api/templates", json={"name": "Mi streamer", "options": {
        "resolution": 480, "fit": "split", "split_layout": {**LAYOUT, "camera_share": 32.5, "camera_exclusion": "blur"}}})
    assert response.status_code == 200, response.text
    template = response.json()
    assert "camera_exclusion" not in template["options"]["split_layout"]
    assert client.get("/api/templates").json()[-1] == template
    analysis_id = uuid4().hex
    moments = [{"id": uuid4().hex, "start": start, "end": start + .6, "title": "Momento", "score": 88}
               for start in (.1, .9)]
    client.app.state.db.put("analyses", {"id": analysis_id, "video_id": video["id"], "status": "completed",
                                        "result": {"moments": moments}})
    batch = client.post("/api/clips/batch", json={**template["options"], "analysis_id": analysis_id,
                                                  "moment_ids": [moment["id"] for moment in moments]})
    assert batch.status_code == 202, batch.text
    for job in batch.json()["jobs"]:
        rendered = wait_job(client, job["id"])
        assert rendered["status"] == "completed", rendered
        assert rendered["settings"]["split_layout"] == template["options"]["split_layout"]

