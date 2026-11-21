from base64 import b64decode
from io import BytesIO
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
from PIL import Image, ImageChops, ImageStat

from app.composition import GraphicLayer
from app.emoji_assets import emoji_key
from app.text_graphics import text_tile
from test_api import upload
from test_phase3_render import run


def layer(**changes):
    return {
        "id": uuid4().hex, "kind": "text", "name": "Prueba", "text": "Edición útil\nClipZone",
        "font": "Poppins", "size": 92, "color": "#231002",
        **changes,
    }


def image(tile):
    return Image.open(BytesIO(tile.png)).convert("RGBA")


@pytest.mark.parametrize("font", ["Montserrat", "Poppins", "Anton", "Arial", "Roboto", "Impact"])
def test_fonts_and_text_decorations(font):
    body = layer(font=font)
    regular = text_tile(GraphicLayer.model_validate({**body, "text_style": {"bold": False}}), (1080, 1920))
    styled = text_tile(GraphicLayer.model_validate({**body, "text_style": {
        "bold": True, "italic": True, "underline": True, "align": "right", "outline_width": 5,
    }}), (1080, 1920))
    assert image(regular).getbbox()
    assert image(styled).getbbox()
    assert regular.png != styled.png
    assert styled.width < 650 and styled.height > regular.height


def test_tight_rounded_background_has_independent_opacity():
    body = layer(text="Texto", opacity=0, text_style={
        "background_transparent": False, "background_color": "#00ff00", "background_opacity": 50, "padding": 30, "radius": 26,
    })
    tile = text_tile(GraphicLayer.model_validate(body), (1080, 1920))
    region = image(tile)
    x0, y0, _, _ = region.getbbox()
    assert tile.width < 400
    assert region.getpixel((tile.width // 2, tile.height // 2)) == (0, 255, 0, 128)
    assert region.getpixel((x0, y0))[3] == 0
    body["text_style"]["background_transparent"] = True
    assert image(text_tile(GraphicLayer.model_validate(body), (1080, 1920))).getbbox() is None


def test_raster_endpoint_is_independent_of_ffmpeg_and_styles_persist(client, monkeypatch):
    body = layer(text_style={"italic": True, "underline": True, "shadow_opacity": 56}, hidden=True,
                 start=.2, end=1.2, x=14, y=72)
    def wrong_engine(*_):
        pytest.fail("La vista en directo del nuevo texto no debe invocar FFmpeg.")

    monkeypatch.setattr(client.app.state.caption_layers, "hook", wrong_engine)
    request = {"ratio": "9:16", "resolution": 480, "layer": body}
    response = client.post("/api/graphics/text", json=request)
    assert response.status_code == 200, response.text
    art = response.json()
    assert Image.open(BytesIO(b64decode(art["image"]))).size == (art["width"], art["height"])
    moved = {"ratio": "9:16", "resolution": 480, "layer": {**body, "x": 60, "y": 33, "start": 0, "end": None}}
    assert client.post("/api/graphics/text", json=moved).json() == art
    saved = client.post("/api/templates", json={
        "name": "Estilo reutilizable", "kind": "text", "options": {"graphics": [body]},
    })
    assert saved.status_code == 200, saved.text
    reusable = saved.json()["options"]["graphics"][0]
    assert reusable["font"] == "Poppins"
    assert reusable["text_style"]["shadow_opacity"] == 56
    assert reusable["text"] == "" and reusable["end"] is None and reusable["hidden"] is False
    assert client.app.state.db.get("templates", saved.json()["id"]) == saved.json()


def decode_frame(settings, path: Path, time: float):
    process = subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-ss", str(time), "-i", str(path),
                              "-frames:v", "1", "-threads", "1", "-c:v", "png", "-f", "image2pipe", "pipe:1"],
                             capture_output=True, check=True, timeout=25)
    return Image.open(BytesIO(process.stdout)).convert("RGB")


def test_live_tile_matches_rendered_mp4_and_respects_clip_relative_timing(client, settings, sample_video, tmp_path):
    video = upload(client, sample_video)
    spec = layer(text="Texto\ncon color", x=50, y=37.5, opacity=65, start=.35, end=1.0, text_style={
        "bold": True, "italic": True, "underline": True, "align": "left",
        "background_transparent": False, "background_color": "#fee8c6", "background_opacity": 82,
        "padding": 23, "radius": 19, "outline_color": "#602b8d", "outline_width": 4,
        "shadow_color": "#302140", "shadow_opacity": 75, "shadow_x": -4, "shadow_y": 8,
    })
    hidden = layer(text="Ocultar", x=85, y=80, hidden=True, text_style={"background_transparent": False})
    body = {"video_id": video["id"], "start": .4, "end": 2, "ratio": "1:1", "resolution": 480}
    preview = run(client, "/api/clips/preview", {**body, "graphics": [spec, hidden]})
    exported = run(client, "/api/clips", {**body, "graphics": [spec, hidden]})
    plain = run(client, "/api/clips", body)
    data = client.get(exported["download_url"]).content
    assert client.get(preview["preview_url"]).content == data
    actual = tmp_path / "con texto.mp4"
    actual.write_bytes(data)
    baseline = tmp_path / "sin texto.mp4"
    baseline.write_bytes(client.get(plain["download_url"]).content)
    response = client.post("/api/graphics/text", json={"ratio": "1:1", "resolution": 480, "layer": spec})
    rgba = Image.open(BytesIO(b64decode(response.json()["image"]))).convert("RGBA")
    # La salida YUV coloca el origen en coordenadas pares.
    left, top = (240 - rgba.width // 2) & ~1, (180 - rgba.height // 2) & ~1
    rect = (left, top, left + rgba.width, top + rgba.height)
    source = decode_frame(settings, baseline, .6)
    shown = decode_frame(settings, actual, .6)
    expected = Image.alpha_composite(source.crop(rect).convert("RGBA"), rgba).convert("RGB")
    assert sum(ImageStat.Stat(ImageChops.difference(shown.crop(rect), expected)).mean) / 3 < 9
    assert sum(ImageStat.Stat(ImageChops.difference(shown.crop(rect), source.crop(rect))).mean) / 3 > 20
    for time in (.1, 1.2):
        difference = ImageChops.difference(decode_frame(settings, actual, time), decode_frame(settings, baseline, time))
        assert max(ImageStat.Stat(difference).mean) < 3


@pytest.mark.parametrize(("emoji", "code"), [
    ("🔥", "1f525"), ("🇨🇴", "1f1e8-1f1f4"), ("🧑🏽‍💻", "1f9d1-1f3fd-200d-1f4bb"),
    ("❤️", "2764"), ("1️⃣", "31-20e3"),
])
def test_emoji_assets_keep_complete_unicode_sequences_and_color(client, emoji, code):
    assert emoji_key(emoji) == code
    response = client.get(f"/api/graphics/emojis/{code}.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    icon = Image.open(BytesIO(response.content)).convert("RGBA")
    assert icon.getbbox() and count_colored(icon) > 100
    assert client.get("/api/graphics/emojis/00000.png").status_code == 404


def count_colored(art):
    return sum(1 for r, g, b, a in art.convert("RGBA").getdata() if a > 150 and max(r, g, b) - min(r, g, b) > 70)


def test_color_emoji_layers_match_live_preview_exact_and_export(client, settings, sample_video, tmp_path):
    real_source = os.environ.get("CLIPZONE_TEXT_TEST_VIDEO")
    video = upload(client, Path(real_source) if real_source else sample_video)
    options = {"video_id": video["id"], "start": .25, "end": 1.65, "ratio": "9:16", "resolution": 1080}
    layers = [
        layer(text="Partida 🔥 🇨🇴", y=30, size=110, text_style={"outline_width": 3, "shadow_opacity": 60}),
        layer(text="En directo 🧑🏽‍💻 ❤️", y=70, size=100, hook=True),
    ]
    renders = {**options, "graphics": layers}
    exact = run(client, "/api/clips/preview", renders)
    exported = run(client, "/api/clips", renders)
    clean = run(client, "/api/clips", options)
    data = client.get(exported["download_url"]).content
    assert data == client.get(exact["preview_url"]).content
    actual, baseline = tmp_path / "emojis.mp4", tmp_path / "limpio.mp4"
    actual.write_bytes(data)
    baseline.write_bytes(client.get(clean["download_url"]).content)
    shown = decode_frame(settings, actual, .5)
    source = decode_frame(settings, baseline, .5)
    assert shown.size == (1080, 1920)
    for spec in layers:
        result = client.post("/api/graphics/text", json={"ratio": "9:16", "resolution": 1080, "layer": spec})
        assert result.status_code == 200
        rgba = Image.open(BytesIO(b64decode(result.json()["image"]))).convert("RGBA")
        assert count_colored(rgba) > 1000
        x, y = (540 - rgba.width // 2) & ~1, (round(1920 * spec["y"] / 100) - rgba.height // 2) & ~1
        box = (x, y, x + rgba.width, y + rgba.height)
        expected = Image.alpha_composite(source.crop(box).convert("RGBA"), rgba).convert("RGB")
        difference = ImageChops.difference(shown.crop(box), expected)
        assert sum(ImageStat.Stat(difference).mean) / 3 < 10
        assert sum(ImageStat.Stat(ImageChops.difference(shown.crop(box), source.crop(box))).mean) / 3 > 8
