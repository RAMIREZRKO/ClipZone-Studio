import base64
import errno
import hashlib
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from app.config import Settings
from app.database import Database
from app.services import live


class ObsStub:
    password = "Clave de prueba áé"
    salt = "fixture-salt"
    challenge = "fixture-challenge"

    def __init__(self, folder):
        self.params = {("Output", "Mode"): "Simple", ("SimpleOutput", "FilePath"): str(folder),
                       ("SimpleOutput", "RecRBTime"): "90"}
        self.active = True
        self.path = folder / "Repetición de OBS.mp4"
        self.save_count = 0
        self.save_started = Event()
        self.release = Event()
        self.release.set()
        self.event_first = False
        self.auth_required = True

    def handle(self, socket):
        def send(opcode, data):
            socket.send(json.dumps({"op": opcode, "d": data}))

        try:
            hello = {"rpcVersion": 1, "obsWebSocketVersion": "5.5.0"}
            if self.auth_required:
                hello["authentication"] = {"challenge": self.challenge, "salt": self.salt}
            send(0, hello)
            identify = json.loads(socket.recv(timeout=5))
            assert identify["op"] == 1 and identify["d"]["rpcVersion"] == 1
            if self.auth_required:
                secret = base64.b64encode(hashlib.sha256((self.password + self.salt).encode()).digest())
                expected = base64.b64encode(hashlib.sha256(secret + self.challenge.encode()).digest()).decode()
                if identify["d"].get("authentication") != expected:
                    socket.close(4009, "authentication failed")
                    return
            send(2, {"negotiatedRpcVersion": 1})

            def send_saved():
                socket.send(json.dumps({
                    "op": 5, "d": {"eventType": "ReplayBufferSaved", "eventIntent": 64,
                                   "eventData": {"savedReplayPath": str(self.path)}},
                }))

            while True:
                packet = json.loads(socket.recv(timeout=7))
                assert packet["op"] == 6
                data = packet["d"]
                kind = data["requestType"]
                response = {}
                if kind == "GetReplayBufferStatus":
                    response = {"outputActive": self.active}
                elif kind == "GetProfileParameter":
                    values = data["requestData"]
                    response = {"parameterValue": self.params[(values["parameterCategory"], values["parameterName"])]}
                else:
                    assert kind == "SaveReplayBuffer"
                    assert identify["d"]["eventSubscriptions"] == 64
                    self.save_count += 1
                    self.save_started.set()
                    assert self.release.wait(5)
                    if self.event_first:
                        send_saved()
                send(7, {"requestType": kind, "requestId": data["requestId"],
                         "requestStatus": {"result": True, "code": 100}, "responseData": response})
                if kind == "SaveReplayBuffer" and not self.event_first:
                    send_saved()
        except ConnectionClosed:
            return


@pytest.fixture
def obs(settings):
    folder = settings.data_dir / "live-inbox"
    stub = ObsStub(folder)
    with serve(stub.handle, "127.0.0.1", 0, subprotocols=["obswebsocket.json"]) as server:
        settings.obs_port = str(server.socket.getsockname()[1])
        settings.obs_password = stub.password
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield stub
        finally:
            stub.release.set()
            server.shutdown()
            thread.join(5)


@pytest.fixture(scope="module")
def long_replay(tmp_path_factory):
    output = tmp_path_factory.mktemp("live-fixture") / "synthetic-replay.mp4"
    ffmpeg = Settings().binary("ffmpeg")
    parts = [("red", 5), ("green", 30), ("blue", 30), ("yellow", 30)]
    inputs = [argument for color, duration in parts for argument in
              ("-f", "lavfi", "-i", f"color={color}:s=96x64:r=12:d={duration}")]
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=95",
                    "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]",
                    "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-threads:v", "2", "-c:a", "aac", str(output)], check=True, timeout=30)
    return output


def test_live_imports_short_replay_persists_history_and_preserves_original(client, settings, obs, sample_video):
    shutil.copyfile(sample_video, obs.path)
    original = obs.path.read_bytes()
    obs.event_first = True
    state = client.get("/api/live/status").json()
    assert state["connected"] and state["buffer_active"] and state["ready"]
    assert state["buffer_seconds"] == 90 and state["library_free_bytes"] > 0 and state["replay_free_bytes"] > 0
    assert ObsStub.password not in str(state)

    response = client.post("/api/live/captures", json={"seconds": 60})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["duration"] == pytest.approx(3)
    assert saved["requested_seconds"] == 60 and saved["name"] == obs.path.name
    assert saved["video"]["has_audio"] and saved["video"]["thumbnail_url"]
    assert client.get(saved["video"]["preview_url"]).status_code == 200
    assert client.get("/api/videos").json() == [saved["video"]]
    assert client.get("/api/live/captures").json() == [saved]
    assert Database(settings.data_dir / "clipzone.sqlite3").live_captures()[0][0]["id"] == saved["id"]
    assert obs.path.read_bytes() == original

    removed = client.post("/api/videos/remove", json={"ids": [saved["id"]], "remove_files": True})
    assert removed.status_code == 200, removed.text
    assert client.get("/api/live/captures").json() == [{**saved, "video": None}]
    assert client.get("/api/videos").json() == []
    assert obs.path.read_bytes() == original


@pytest.mark.parametrize(("seconds", "color"), [(30, (255, 255, 0)), (60, (0, 0, 255)), (90, (0, 128, 0))])
def test_live_trims_the_tail_and_keeps_audio(client, settings, obs, long_replay, seconds, color):
    obs.auth_required = False
    settings.obs_password = ""
    obs.params = {("Output", "Mode"): "Advanced", ("AdvOut", "RecFilePath"): str(obs.path.parent),
                  ("AdvOut", "RecRBTime"): "90"}
    shutil.copyfile(long_replay, obs.path)
    response = client.post("/api/live/captures", json={"seconds": seconds})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["duration"] == pytest.approx(seconds, abs=0.09)
    assert saved["video"]["has_audio"]
    record = client.app.state.db.get("videos", saved["id"])
    pixel = subprocess.run([settings.binary("ffmpeg"), "-v", "error", "-ss", "0.4", "-i", record["source_path"],
                            "-frames:v", "1", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-threads", "1",
                            "-f", "rawvideo", "pipe:1"], capture_output=True, check=True, timeout=15).stdout
    assert tuple(pixel) == pytest.approx(color, abs=8)
    assert obs.path.stat().st_size == long_replay.stat().st_size


def test_live_rejects_invalid_port_password_and_disabled_buffer(client, settings, obs):
    real_port = settings.obs_port
    settings.obs_port = "invalid"
    state = client.get("/api/live/status").json()
    assert state["error_code"] == "obs_port"
    settings.obs_port = real_port
    settings.obs_password = ""
    assert client.get("/api/live/status").json()["error_code"] == "obs_auth"
    settings.obs_password = "contraseña incorrecta"
    state = client.get("/api/live/status").json()
    assert not state["connected"] and state["error_code"] == "obs_auth"
    assert settings.obs_password not in str(state)
    settings.obs_password = obs.password
    obs.active = False
    state = client.get("/api/live/status").json()
    assert state["connected"] and not state["ready"] and not state["buffer_active"]
    assert client.post("/api/live/captures", json={"seconds": 30}).json()["code"] == "buffer_inactive"
    assert client.post("/api/live/captures", json={"seconds": 42}).status_code == 422
    assert obs.save_count == 0


def test_live_validates_profile_and_reported_file(client, obs, sample_video):
    obs.params[("SimpleOutput", "RecRBTime")] = "180"
    assert client.post("/api/live/captures", json={"seconds": 30}).json()["code"] == "obs_buffer_limit"
    obs.params[("SimpleOutput", "RecRBTime")] = "90"
    folder = obs.path.parent
    obs.params[("SimpleOutput", "FilePath")] = str(sample_video.parent)
    assert client.post("/api/live/captures", json={"seconds": 30}).json()["code"] == "obs_folder"
    assert obs.save_count == 0
    obs.params[("SimpleOutput", "FilePath")] = str(folder)
    obs.path = sample_video
    assert client.post("/api/live/captures", json={"seconds": 30}).json()["code"] == "obs_file_outside"
    obs.path = folder / "missing.mp4"
    assert client.post("/api/live/captures", json={"seconds": 30}).json()["code"] == "obs_file"
    assert client.get("/api/live/captures").json() == []


def test_live_handles_insufficient_space_and_cleans_failed_import(client, settings, obs, sample_video, monkeypatch):
    shutil.copyfile(sample_video, obs.path)
    with monkeypatch.context() as patch:
        patch.setattr(live, "disk_usage", lambda _: SimpleNamespace(free=0))
        assert client.get("/api/live/status").json()["error_code"] == "disk_full"
        assert client.post("/api/live/captures", json={"seconds": 30}).status_code == 507
    assert obs.save_count == 0

    def incomplete_copy(_source, target):
        target.write_bytes(b"partial")
        raise OSError(errno.ENOSPC, "disco lleno")

    monkeypatch.setattr(live, "copyfile", incomplete_copy)
    assert client.post("/api/live/captures", json={"seconds": 30}).json()["code"] == "disk_full"
    assert obs.path.is_file()
    assert list((settings.data_dir / "uploads").iterdir()) == []
    assert client.get("/api/videos").json() == []
    assert client.get("/api/live/captures").json() == []


def test_live_only_saves_one_replay_at_a_time(client, obs, sample_video):
    shutil.copyfile(sample_video, obs.path)
    obs.release.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        saving = pool.submit(client.post, "/api/live/captures", json={"seconds": 90})
        try:
            assert obs.save_started.wait(4)
            assert client.get("/api/live/status").json()["busy"]
            result = client.post("/api/live/captures", json={"seconds": 30})
            assert result.status_code == 409 and result.json()["code"] == "capture_busy"
        finally:
            obs.release.set()
        assert saving.result().status_code == 201
    assert obs.save_count == 1


def test_live_blocks_external_web_origins_before_saving(client, obs):
    response = client.post("/api/live/captures", json={"seconds": 60}, headers={"Origin": "https://example.test"})
    assert response.status_code == 403
    assert obs.save_count == 0
