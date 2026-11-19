from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
from threading import Thread
from time import monotonic, sleep

import pytest

from app.config import Settings
from app.services import direct_capture
from app.services.direct_buffer import DirectBuffer, clean_session
from app.services.direct_source import DirectSource, StreamlinkSource, source_from_url
from app.services.obs import LiveError


def wait_state(client, condition, timeout=15):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        status = client.get("/api/live/direct/status").json()
        if condition(status):
            return status
        sleep(.1)
    pytest.fail(f"El estado no llegó al esperado: {status}")


@pytest.mark.parametrize(("url", "code"), [
    ("http://127.0.0.1:8000/a", "direct_url"),
    ("https://www.twitch.tv.ejemplo.test/a", "direct_url"),
    ("https://user:secret@kick.com/canal", "direct_url"),
    ("https://kick.com/canal?token=prueba", "direct_url"),
    ("https://www.twitch.tv/videos/123", "direct_url"),
    ("https://kick.com/canal/videos/id", "direct_url"),
    ("https://www.youtube.com/live/abcdef", "direct_youtube"),
])
def test_direct_source_rejects_urls_outside_supported_public_channels(client, url, code):
    response = client.post("/api/live/direct/probe", json={"url": url})
    assert response.status_code == 422 and response.json()["code"] == code


def test_direct_quality_probe_reports_restrictions_without_returning_secrets():
    assert source_from_url(" https://Twitch.tv/Canal_1/ ").url == "https://www.twitch.tv/canal_1"
    assert source_from_url("https://kick.com/Canal-1").platform == "kick"
    choices = {"streams": {"720p60": {}, "1080p": {}, "best": {}, "audio_only": {}, "worst": {}, "480p": {}}}
    assert StreamlinkSource.qualities(choices, b"", 0) == ["1080p", "720p60", "480p"]
    assert StreamlinkSource.qualities({"error": "No playable streams found on this URL"}, b"", 1) == []
    with pytest.raises(LiveError) as caught:
        StreamlinkSource.qualities({"error": "403 age-restricted token=fixture"}, b"", 1)
    assert caught.value.status == 403 and "fixture" not in str(caught.value)
    with pytest.raises(LiveError) as caught:
        StreamlinkSource.qualities({"error": "ConnectTimeout"}, b"", 1)
    assert caught.value.code == "direct_network"


@pytest.mark.parametrize("url", ["https://kick.com/canal_de_prueba", "https://www.twitch.tv/canal_de_prueba"])
def test_installed_streamlink_recognises_channel_without_accessing_network(url):
    engine = StreamlinkSource()
    if not engine.available():
        pytest.skip("Instala backend/requirements-live.txt para verificar los conectores.")
    result = subprocess.run([*engine.command(), "--can-handle-url-no-redirect", url], capture_output=True, timeout=12)
    assert result.returncode == 0, result.stderr


def test_rolling_buffer_respects_time_bytes_and_pinned_segments(tmp_path):
    folder = tmp_path / ("a" * 32)
    folder.mkdir()
    buffer = DirectBuffer(folder, max_seconds=6)
    def push(sequence, generation=0):
        name = f"g{generation:02d}-{sequence:08d}.mkv"
        path = folder / name
        path.write_bytes(b"frame" * 20)
        assert buffer.accept(f"{name},{2 * sequence},{2 * sequence + 2}".encode(), generation)
        return path

    first, second, third = [push(sequence) for sequence in range(3)]
    pinned = buffer.snapshot(30)
    assert len(pinned) == 3
    fourth = push(3)
    assert first.exists() and not any(item.path == first for item in buffer.closed)
    buffer.release()
    assert not first.exists() and second.exists() and third.exists() and fourth.exists()
    next_generation = push(0, generation=1)
    assert [item.path for item in buffer.closed] == [next_generation]
    assert not second.exists() and not third.exists()
    assert buffer.enforce_bytes(80) == 0 and not next_generation.exists()
    assert not buffer.accept(b"../../uploads/guardado.mp4,0,2", 1)
    unrelated = folder / "manual.txt"
    unrelated.write_text("conservar")
    clean_session(folder)
    assert unrelated.exists()


@pytest.mark.parametrize("length", [30, 60, 90, 120, 300])
def test_snapshot_uses_final_contiguous_segments_for_all_lengths(tmp_path, length):
    buffer = DirectBuffer(tmp_path)
    for t in range(0, 310, 2):
        name = f"g00-{t // 2:08d}.mkv"
        (tmp_path / name).write_bytes(b"test")
        assert buffer.accept(f"{name},{t},{t + 2}".encode(), 0)
    assert buffer.seconds == 300 and len(list(tmp_path.iterdir())) == 150
    selected = buffer.snapshot(length)
    assert sum(item.duration for item in selected) == length
    assert selected[-1].start == 308 and selected[0].start == 310 - length


def test_direct_handles_missing_dependency_and_blocks_external_origin(client, monkeypatch):
    monkeypatch.setattr(client.app.state.direct.engine, "available", lambda: False)
    assert client.get("/api/live/direct/status").json()["installed"] is False
    body = {"url": "https://kick.com/canal", "quality": "480p"}
    assert client.post("/api/live/direct/start", json=body).status_code == 503
    assert client.post("/api/live/direct/start", json=body, headers={"Origin": "https://example.test"}).status_code == 403
    assert client.post("/api/live/direct/start", json={**body, "quality": "--player"}).status_code == 422
    assert client.post("/api/live/direct/captures", json={"seconds": 61}).status_code == 422
    assert client.get("/api/live/captures").json() == []


@pytest.mark.parametrize("offline", [True, False])
def test_direct_distinguishes_end_of_stream_from_exhausted_retries(client, monkeypatch, offline):
    service = client.app.state.direct
    monkeypatch.setattr(service.engine, "available", lambda: True)
    monkeypatch.setattr(direct_capture, "RETRY_DELAYS", (0, 0, 0))
    attempts = []
    monkeypatch.setattr(service.engine, "inspect", lambda source, cancelled: [] if offline and attempts else ["720p"])
    monkeypatch.setattr(service, "capture_attempt", lambda session, generation: attempts.append(generation))
    body = {"url": "https://www.twitch.tv/canal", "quality": "720p"}
    assert client.post("/api/live/direct/start", json=body).status_code == 202
    status = wait_state(client, lambda item: item["state"] in {"ended", "error"})
    assert status["state"] == ("ended" if offline else "error")
    assert status["retries"] == (0 if offline else 3)
    assert attempts == ([0] if offline else [0, 1, 2, 3])


def test_direct_retries_a_transient_error_before_starting(client, monkeypatch):
    service = client.app.state.direct
    monkeypatch.setattr(service.engine, "available", lambda: True)
    monkeypatch.setattr(direct_capture, "RETRY_DELAYS", (0, 0, 0))
    options = iter([LiveError("direct_network", "Sin conexión", 502), ["480p"], []])
    def inspect(source, cancelled):
        value = next(options)
        if isinstance(value, LiveError):
            raise value
        return value
    monkeypatch.setattr(service.engine, "inspect", inspect)
    attempts = []
    monkeypatch.setattr(service, "capture_attempt", lambda session, generation: attempts.append(generation))
    body = {"url": "https://kick.com/canal", "quality": "480p"}
    assert client.post("/api/live/direct/start", json=body).status_code == 202
    status = wait_state(client, lambda item: item["state"] == "ended")
    assert status["retries"] == 1 and attempts == [1]


@pytest.fixture
def local_hls(tmp_path):
    if not StreamlinkSource().available():
        pytest.skip("Instala backend/requirements-live.txt para probar Streamlink con HLS local.")
    ffmpeg = Settings().binary("ffmpeg")
    directory = tmp_path / "broadcast"
    directory.mkdir()
    subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "64", "-c:v", "libx264",
                    "-threads:v", "2", "-preset", "ultrafast", "-g", "48", "-sc_threshold", "0", "-c:a", "aac",
                    "-f", "hls", "-hls_time", "2", "-hls_list_size", "0", "-hls_segment_filename", "part-%03d.ts", "fixture.m3u8"],
                   cwd=directory, check=True, timeout=25)
    fixture = (directory / "fixture.m3u8").read_text().splitlines()
    pairs = [(fixture[i - 1], name) for i, name in enumerate(fixture) if name.endswith(".ts")]
    began = None

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal began
            if self.path == "/master.m3u8":
                content = ["#EXTM3U", "#EXT-X-STREAM-INF:BANDWIDTH=450000,RESOLUTION=320x180", "live.m3u8"]
                data = ("\n".join(content) + "\n").encode()
                content_type = "application/vnd.apple.mpegurl"
            elif self.path == "/live.m3u8":
                if began is None:
                    began = monotonic()
                stop = min(len(pairs), 3 + int((monotonic() - began) / .4))
                start = max(0, stop - 12)
                content = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2", f"#EXT-X-MEDIA-SEQUENCE:{start}"]
                content += [line for pair in pairs[start:stop] for line in pair]
                if stop == len(pairs):
                    content.append("#EXT-X-ENDLIST")
                data = ("\n".join(content) + "\n").encode()
                content_type = "application/vnd.apple.mpegurl"
            else:
                name = self.path.removeprefix("/")
                if name not in {pair[1] for pair in pairs}:
                    self.send_error(404)
                    return
                data = (directory / name).read_bytes()
                content_type = "video/mp2t"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"hls://http://127.0.0.1:{server.server_port}/master.m3u8"
        finally:
            server.shutdown()
            thread.join(3)


def test_real_direct_hls_records_background_remuxes_av_and_preserves_saved_clip(client, settings, monkeypatch, local_hls):
    source = DirectSource("kick", "prueba", local_hls)
    monkeypatch.setattr(direct_capture, "source_from_url", lambda url: source)
    body = {"url": "https://kick.com/prueba", "quality": "180p"}
    info = client.post("/api/live/direct/probe", json={"url": body["url"]})
    assert info.status_code == 200 and "180p" in info.json()["qualities"], info.text
    assert client.post("/api/live/direct/captures", json={"seconds": 30}).json()["code"] == "direct_empty"
    assert client.post("/api/live/direct/start", json=body).status_code == 202
    try:
        assert client.post("/api/live/direct/start", json=body).json()["code"] == "direct_busy"
        state = wait_state(client, lambda item: item["buffer_seconds"] >= 31 or item["state"] == "error", 36)
        assert state["buffer_seconds"] >= 31 and 0 < state["bytes"] <= state["max_bytes"], state
        response = client.post("/api/live/direct/captures", json={"seconds": 30})
        assert response.status_code == 201, response.text
        capture = response.json()
        assert capture["method"] == "direct" and capture["platform"] == "kick" and capture["quality"] == "180p"
        assert capture["video"]["has_audio"] and capture["video"]["preview_status"] == "ready"
        assert capture["video"]["width"] == 320 and capture["video"]["height"] == 180
        assert capture["duration"] == pytest.approx(30, abs=.3)
        assert client.get(capture["video"]["preview_url"], headers={"Range": "bytes=0-4095"}).status_code == 206
        assert client.get("/api/live/captures").json() == [capture]
        assert client.get("/api/videos").json() == [capture["video"]]
        video = Path(client.app.state.db.get("videos", capture["id"])["source_path"])
        dump = subprocess.run([settings.binary("ffprobe"), "-v", "error", "-show_entries",
                               "stream=codec_type,codec_name,start_time,duration,r_frame_rate", "-of", "json", str(video)],
                              check=True, capture_output=True, timeout=10)
        streams = {stream["codec_type"]: stream for stream in json.loads(dump.stdout)["streams"]}
        assert streams["video"]["codec_name"] == "h264" and streams["video"]["r_frame_rate"] == "24/1"
        assert streams["audio"]["codec_name"] == "aac"
        for key in ("start_time", "duration"):
            assert abs(float(streams["video"][key]) - float(streams["audio"][key])) < .15
        subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-xerror", "-i", str(video), "-f", "null", "-"],
                       check=True, capture_output=True, timeout=15)
    finally:
        client.post("/api/live/direct/stop")
        wait_state(client, lambda item: item["state"] in {"stopped", "ended", "error"}, 15)
    client.app.state.direct.shutdown()
    assert list((settings.data_dir / "direct-buffer").iterdir()) == []
    assert video.is_file() and client.get("/api/live/captures").json() == [capture]

