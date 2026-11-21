from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
from threading import Event, Thread
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import direct_capture, multistream
from app.services.direct_buffer import DirectBuffer, clean_session
from app.services.direct_capture import CaptureSession
from app.services.direct_source import DirectSource, StreamlinkSource, source_from_url
from app.services.obs import LiveError
from app.services.youtube_live import YouTubeBroadcast


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
    ("https://www.youtube.com/live/abcdef", "direct_url"),
    ("https://www.youtube.com/watch?v=JH-D4TkiOe4&token=fixture", "direct_url"),
    ("https://www.youtube.com/watch?v=JH-D4TkiOe4&v=12345678901", "direct_url"),
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
    buffer.release(pinned)
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


def test_missing_or_empty_segments_are_not_reported_as_saveable(tmp_path):
    buffer = DirectBuffer(tmp_path)
    paths = []
    for index in range(3):
        name = f"g00-{index:08d}.mkv"
        path = tmp_path / name
        path.write_bytes(b"segment")
        assert buffer.accept(f"{name},{index * 2},{index * 2 + 2}".encode(), 0)
        paths.append(path)
    paths[1].unlink()
    assert [segment.path for segment in buffer.snapshot(30)] == paths[2:]
    paths[2].write_bytes(b"")
    assert buffer.ready and [segment.path for segment in buffer.snapshot(30)] == paths[:1]
    paths[0].unlink()
    assert not buffer.ready and not buffer.snapshot(30)

def test_youtube_saves_requested_duration_when_the_start_is_between_keyframes(client, settings):
    direct = client.app.state.direct
    folder = direct.root / ("f" * 32)
    folder.mkdir()
    source = DirectSource("youtube", "UC" + "x" * 22, "https://www.youtube.com/watch?v=abcdefghijk")
    session = CaptureSession(source, "180p", DirectBuffer(folder), state="ended")
    direct.session = session
    command = [settings.binary("ffmpeg"), "-v", "error", "-y",
               "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
               "-t", "34", "-c:v", "libx264", "-threads:v", "2", "-preset", "ultrafast",
               "-g", "120", "-sc_threshold", "0", "-c:a", "aac", "-f", "segment",
               "-segment_time", "2", "-segment_list_type", "csv", "-segment_list", "pipe:1",
               "-reset_timestamps", "1", "g00-%08d.mkv"]
    result = subprocess.run(command, cwd=folder, check=True, capture_output=True, timeout=25)
    for row in result.stdout.splitlines():
        assert session.buffer.accept(row, 0)
    standard = session.buffer.snapshot(30)
    session.buffer.release(standard)
    assert sum(segment.duration for segment in standard) < 29.5
    response = client.post("/api/live/direct/captures", json={"seconds": 30})
    assert response.status_code == 201, response.text
    assert response.json()["duration"] == pytest.approx(30, abs=.15)
    assert response.json()["video"]["has_audio"]


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


def test_two_direct_streams_have_independent_buffers_and_stop_controls(client, monkeypatch, local_hls):
    parse = direct_capture.source_from_url

    def local_source(url):
        source = parse(url)
        return DirectSource(source.platform, source.channel, local_hls)

    monkeypatch.setattr(direct_capture, "source_from_url", local_source)
    first = {"url": "https://kick.com/primero", "quality": "180p"}
    second = {"url": "https://www.twitch.tv/segundo", "quality": "180p"}
    assert client.post("/api/live/direct/start", json=first).status_code == 202
    assert client.post("/api/live/direct/start?slot=1", json=first).status_code == 409
    assert client.post("/api/live/direct/start?slot=1", json=second).status_code == 202
    assert client.post("/api/live/direct/start?slot=2", json=second).status_code == 422
    deadline = monotonic() + 25
    while monotonic() < deadline:
        states = [client.get(f"/api/live/direct/status?slot={slot}").json() for slot in (0, 1)]
        if all(state["buffer_seconds"] > 0 for state in states):
            break
        sleep(.15)
    assert all(state["buffer_seconds"] > 0 for state in states), states
    assert [state["channel"] for state in states] == ["primero", "segundo"]
    assert client.post("/api/live/direct/stop").json()["state"] == "stopping"
    assert client.get("/api/live/direct/status?slot=1").json()["state"] == "capturing"
    clip = client.post("/api/live/direct/captures?slot=1", json={"seconds": 30})
    assert clip.status_code == 201, clip.text
    assert (clip.json()["platform"], clip.json()["channel"]) == ("twitch", "segundo")
    assert client.post("/api/live/direct/stop?slot=1").status_code == 200


@pytest.mark.parametrize("maximum", [4, 6, 8])
def test_registered_channels_capture_independently_and_release_capacity(client, monkeypatch, local_hls, maximum):
    def local_source(url):
        source = source_from_url(url)
        return DirectSource(source.platform, source.channel, local_hls)

    monkeypatch.setattr(direct_capture, "source_from_url", local_source)
    limit = client.put("/api/live/direct/settings", json={"max_active": maximum})
    assert limit.status_code == 200 and limit.json()["max_active"] == maximum
    streams = []
    channels = ["alfa", "bravo", "charlie", "delta", "eco", "foxtrot", "golf", "hotel", "india"]
    for index, channel in enumerate(channels[:maximum + 1]):
        host = ("kick.com", "twitch.tv")[index % 2]
        response = client.post("/api/live/streamers", json={"url": f"https://{host}/{channel}"})
        assert response.status_code == 200, response.text
        streams.append(response.json())

    def call(action, stream, body=None):
        return client.post(f"/api/live/direct/{action}", params={"streamer": stream["id"]}, json=body)

    def start(stream):
        return call("start", stream, {"url": stream["url"], "quality": "180p"})

    for stream in streams[:maximum]:
        response = start(stream)
        assert response.status_code == 202, response.text
    assert start(streams[-1]).json()["code"] == "direct_limit"
    assert client.delete("/api/live/streamers/" + streams[0]["id"]).json()["code"] == "streamer_busy"
    deadline = monotonic() + 25
    while monotonic() < deadline:
        overview = client.get("/api/live/direct/channels").json()
        states = {row["id"]: row["capture"] for row in overview["channels"]}
        if all(states[row["id"]]["buffer_ready"] and states[row["id"]]["bytes"] > 0 for row in streams[:maximum]):
            break
        sleep(.15)
    assert len(states) == maximum + 1 and overview["active"] == overview["max_active"] == maximum
    assert all(states[stream["id"]]["channel"] == stream["id"].split(":")[1] for stream in streams[:maximum])
    assert all(states[stream["id"]]["buffer_ready"] for stream in streams[:maximum])
    assert not states[streams[-1]["id"]]["buffer_ready"]
    assert all(state["max_bytes"] == 512 * 1024**2 for state in states.values())
    assert 0 < overview["bytes"] <= overview["max_bytes"]
    services = client.app.state.multistream.channels.values()
    assert {auto.analysis for _, auto in services} == {client.app.state.analysis_queue}
    if maximum > 4:
        lowered = client.put("/api/live/direct/settings", json={"max_active": 4}).json()
        assert lowered["active"] == maximum and lowered["max_active"] == 4
        assert lowered["max_bytes"] == 512 * maximum * 1024**2
        assert start(streams[-1]).json()["code"] == "direct_limit"
        assert client.put("/api/live/direct/settings", json={"max_active": maximum}).status_code == 200
    first, second = streams[:2]
    assert call("stop", first).json()["state"] == "stopping"
    for _ in range(75):
        overview = client.get("/api/live/direct/channels").json()
        if overview["active"] == maximum - 1:
            break
        sleep(.1)
    assert overview["active"] == maximum - 1
    assert client.get("/api/live/direct/status", params={"streamer": second["id"]}).json()["state"] == "capturing"
    saved = call("captures", first, {"seconds": 30})
    assert saved.status_code == 201 and saved.json()["channel"] == "alfa", saved.text
    assert start(streams[-1]).status_code == 202
    assert client.get("/api/live/direct/status", params={"streamer": first["id"]}).json()["buffer_seconds"] == 0
    assert client.delete("/api/live/streamers/" + first["id"]).status_code == 200
    assert client.get("/api/live/captures").json()[0]["id"] == saved.json()["id"]
    for stream in streams[1:]:
        call("stop", stream)


def test_probe_state_is_per_channel_and_offline_cannot_start(client, monkeypatch):
    sources = {"kick:fuera": "https://kick.com/fuera", "twitch:online": "https://www.twitch.tv/online"}
    for url in sources.values():
        assert client.post("/api/live/streamers", json={"url": url, "quality": "720p"}).status_code == 200
    checking, release = Event(), Event()
    qualities = {"fuera": [], "online": ["720p", "480p"]}

    def inspect(source):
        if source.channel == "fuera":
            checking.set()
            assert release.wait(10)
        return qualities[source.channel]

    monkeypatch.setattr(client.app.state.direct.engine, "inspect", inspect)

    def call(action, identifier):
        return client.post(f"/api/live/direct/{action}", params={"streamer": identifier},
                           json={"url": sources[identifier], "quality": "720p", "seconds": 30})

    def rows():
        return {row["id"]: row for row in client.get("/api/live/direct/channels").json()["channels"]}

    with ThreadPoolExecutor() as pool:
        offline = pool.submit(call, "probe", "kick:fuera")
        try:
            assert checking.wait(5)
            assert rows()["kick:fuera"]["connection"] == "checking"
            assert rows()["twitch:online"]["connection"] == "unknown"
            assert call("start", "kick:fuera").json()["code"] == "direct_busy"
            assert call("probe", "twitch:online").json()["live"]
        finally:
            release.set()
        assert offline.result(timeout=5).json()["live"] is False
    current = rows()
    assert current["kick:fuera"]["connection"] == "offline"
    assert not current["kick:fuera"]["capture"]["buffer_ready"]
    assert current["twitch:online"]["connection"] == "online"
    assert current["twitch:online"]["qualities"] == ["720p", "480p"]
    assert call("start", "kick:fuera").json()["code"] == "direct_offline"
    assert call("captures", "kick:fuera").json()["code"] == "direct_empty"
    qualities["fuera"] = ["720p"]
    assert call("probe", "kick:fuera").json()["live"]
    assert rows()["kick:fuera"]["connection"] == "online"


def test_simultaneous_kick_twitch_and_youtube_keep_buffers_on_youtube_end(client, monkeypatch, local_hls):
    channel = "UC" + "q" * 22
    video = "abcdefghijk"
    live_url = "https://www.youtube.com/@controlado/live"
    state = "live"
    looked_up = []

    def youtube(url):
        looked_up.append(url)
        return YouTubeBroadcast(channel, "YouTube de prueba", state, video, local_hls.removeprefix("hls://"))

    def local_source(url):
        original = source_from_url(url)
        if original.platform == "youtube":
            return original
        return DirectSource(original.platform, original.channel, local_hls)

    monkeypatch.setattr(multistream, "resolve_youtube", youtube)
    monkeypatch.setattr(direct_capture, "resolve_youtube", youtube)
    monkeypatch.setattr(direct_capture, "source_from_url", local_source)
    urls = {"kick:controlado": "https://kick.com/controlado", "twitch:controlado": "https://www.twitch.tv/controlado",
            f"youtube:{channel}": live_url}
    for key, url in urls.items():
        assert client.post("/api/live/streamers", json={"url": url}).json()["id"] == key
        assert client.post("/api/live/direct/start", params={"streamer": key}, json={"url": url, "quality": "180p"}).status_code == 202
    deadline = monotonic() + 30
    while monotonic() < deadline:
        overview = client.get("/api/live/direct/channels").json()
        if overview["active"] == 3 and all(row["capture"]["buffer_ready"] for row in overview["channels"]):
            break
        sleep(.15)
    assert overview["active"] == 3 and all(row["capture"]["buffer_ready"] for row in overview["channels"]), overview
    assert client.app.state.multistream.channels[f"youtube:{channel}"][1].analysis is client.app.state.analysis_queue
    assert all(row["capture"]["max_bytes"] == 512 * 1024**2 for row in overview["channels"])
    state = "ended"
    selected = {"streamer": f"youtube:{channel}"}
    deadline = monotonic() + 30
    while monotonic() < deadline:
        result = client.get("/api/live/direct/status", params=selected).json()
        if result["state"] == "ended":
            break
        sleep(.2)
    assert result["state"] == "ended" and result["broadcast_state"] == "ended" and result["buffer_ready"], result
    assert f"https://www.youtube.com/watch?v={video}" in looked_up
    saved = client.post("/api/live/direct/captures", params=selected, json={"seconds": 30})
    assert saved.is_success and saved.json()["video"]["has_audio"], saved.text
    assert saved.json()["channel_name"] == "YouTube de prueba"


def test_registered_channel_settings_are_independent_and_survive_restart(settings):
    one = "https://kick.com/primero"
    two = "https://www.twitch.tv/segundo"
    first = {"streamer": "kick:primero"}
    with TestClient(create_app(settings)) as client:
        assert client.put("/api/live/direct/settings", json={"max_active": 7}).status_code == 422
        assert client.put("/api/live/direct/settings", json={"max_active": 10}).status_code == 200
        assert client.post("/api/live/streamers", json={"url": one, "quality": "720p", "seconds": 120}).status_code == 200
        assert client.post("/api/live/streamers", json={"url": two, "seconds": 30}).status_code == 200
        template = client.post("/api/templates", json={"name": "Primero", "options": {"fit": "split"}}).json()
        assert client.post("/api/live/streamers", json={"url": one, "template_id": template["id"]}).status_code == 200
        assert client.post("/api/live/auto/config", params=first,
                           json={"sensitivity": "high", "duration": 60, "detection_mode": "reaction"}).status_code == 200
    with TestClient(create_app(settings)) as client:
        overview = client.get("/api/live/direct/channels").json()
        assert overview["max_active"] == 10 and overview["max_bytes"] == 5120 * 1024**2
        rows = overview["channels"]
        assert [(row["id"], row["seconds"]) for row in rows] == [("kick:primero", 120), ("twitch:segundo", 30)]
        assert rows[0]["quality"] == "720p" and rows[0]["template_id"] == template["id"]
        assert rows[0]["autoclip"]["options"]["sensitivity"] == "high"
        assert rows[0]["autoclip"]["options"]["duration"] == 60
        assert rows[0]["autoclip"]["options"]["detection_mode"] == "irl"
        assert rows[1]["autoclip"]["options"]["sensitivity"] == "balanced"
        assert rows[1]["autoclip"]["options"]["detection_mode"] == "mixed"
        assert client.delete("/api/live/streamers/kick:primero").status_code == 200
        assert client.get("/api/live/auto/status", params=first).status_code == 404
        assert client.post("/api/live/streamers", params=first, json={"url": one, "seconds": 90}).status_code == 404
        assert [row["id"] for row in client.get("/api/live/streamers").json()] == ["twitch:segundo"]

