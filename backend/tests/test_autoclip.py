from array import array
import json
from math import pi, sin
import os
from pathlib import Path
from shutil import copyfile
import subprocess
from time import monotonic, sleep, time

import pytest

from app.ai.live_detector import AudioSignal, BLOCK_BYTES, LiveDetector, editorial_score
from app.config import ROOT
from app.services.autoclip import AutoOptions
from app.services.direct_buffer import DirectBuffer
from app.services.direct_capture import CaptureSession
from app.services.direct_source import DirectSource


def require_vad():
    pytest.importorskip("webrtcvad")


def wait_for(fn, timeout=16):
    limit = monotonic() + timeout
    while monotonic() < limit:
        value = fn()
        if value:
            return value
        sleep(.07)
    pytest.fail("La operación de AutoClipping no se completó a tiempo.")


def test_adaptive_peaks_require_voice_and_repeated_or_abrupt_signals():
    require_vad()
    detector = LiveDetector("balanced")
    for count in range(12):
        assert detector.measure(-31, .1, .85, count) is None
    assert detector.measure(-8, .8, 0., 12) is None
    assert detector.measure(-30, .08, .8, 13) is None
    signal = detector.measure(-10, .7, .9, 14)
    assert signal and signal.intensity > .8 and signal.voice == .9
    assert "cambio brusco de intensidad" in signal.reasons
    assert any("sin identificar risa o grito" in reason for reason in signal.reasons)
    assert detector.measure(-10, .7, .9, 15) is None
    for count in range(20):
        detector.measure(-31, .1, .7, 16 + count)
    assert detector.measure(-22, .11, .6, 40) is None
    assert "señales acústicas acumuladas" in detector.measure(-21, .12, .6, 41).reasons


def test_constant_music_and_long_running_window_remain_bounded():
    require_vad()
    detector = LiveDetector("high")
    chord = array("h", (int(5600 * sum(sin(2 * pi * freq * i / 16000) for freq in (220, 330, 440)) / 3)
                        for i in range(BLOCK_BYTES // 2))).tobytes()
    # Procesa PCM con WebRTC. Después simula una sesión larga sin ampliar la memoria del modelo acústico.
    for seconds in range(35):
        assert list(detector.feed(chord * 3, seconds)) == []
    for sample in range(7200):
        assert detector.measure(-22 + sample % 3, .18, .88, sample) is None
    assert len(detector.levels) == 80 and len(detector.activity) == 4


def transcript():
    words = "¿Cómo conseguimos este resultado increíble? Mira el cambio y verás por qué funciona tan bien.".split()
    return {"words": [{"text": word, "start": 11 + i * .28, "end": 11.2 + i * .28}
                      for i, word in enumerate(words)]}


def test_editorial_score_is_explainable_and_rejects_speechless_candidates():
    wave = AudioSignal(24, .92, .87, ("intensidad alta",))
    scored = editorial_score(transcript(), 14, wave)
    assert 58 <= scored["score"] <= 100
    assert set(scored["metrics"]) == {"intensity", "voice", "hook", "context", "continuity", "closure"}
    assert scored["title"] and "contexto transcrito" in scored["reason"]
    assert editorial_score({"words": []}, 14, wave) is None


def session_for(service):
    folder = service.direct.root / ("6" * 32)
    folder.mkdir()
    session = CaptureSession(DirectSource("kick", "prueba", "https://kick.com/prueba"),
                             "240p", DirectBuffer(folder), state="capturing")
    service.direct.session = session
    return session


def put_segment(service, session, original, index, generation=0, length=3):
    name = f"g{generation:02d}-{index:08d}.mkv"
    copyfile(original, session.buffer.folder / name)
    assert service.direct.publish(session, generation, f"{name},{index * length},{(index + 1) * length}".encode())


def generate_segments(settings, folder, speech=None):
    folder.mkdir()
    audio = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    maps = ["-map", "0:v", "-map", "1:a"]
    if speech:
        audio = ["-i", str(speech)]
        maps = ["-filter_complex", "[1:a]atrim=duration=14,volume=3,adelay=18000:all=1,apad[a]",
                "-map", "0:v", "-map", "[a]"]
    subprocess.run([settings.binary("ffmpeg"), "-hide_banner", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24", *audio, *maps,
                    "-t", "36", "-c:v", "libx264", "-threads:v", "2", "-preset", "ultrafast", "-g", "72",
                    "-sc_threshold", "0", "-c:a", "aac", "-f", "segment", "-segment_time", "3",
                    "-reset_timestamps", "1", "source-%02d.mkv"], cwd=folder, check=True, timeout=20)
    return sorted(folder.glob("*.mkv"))


def test_waits_for_postroll_renders_synchronised_video_and_keeps_or_discards_safely(client, settings, tmp_path, monkeypatch):
    service = client.app.state.autoclip
    session = session_for(service)
    segments = generate_segments(settings, tmp_path / "recording")
    for index in range(8):
        put_segment(service, session, segments[index], index)
    called = []
    def transcribe(audio, model, output, cancellation):
        called.append((audio.stat().st_size, model))
        return transcript()
    monkeypatch.setattr(service.analysis, "transcribe_live", transcribe)
    options = AutoOptions(before=12, after=6, minimum_score=20)
    service.propose(session, 0, AudioSignal(24, .95, .9, ("pico con voz",)), options, service.cancel)
    wait_for(lambda: session.buffer.pins)
    assert not called and client.get("/api/live/auto/candidates").json() == []
    manual = client.post("/api/live/direct/captures", json={"seconds": 30})
    assert manual.status_code == 201, manual.text
    assert session.buffer.pins
    for index in (8, 9):
        put_segment(service, session, segments[index], index)
    rows = wait_for(lambda: client.get("/api/live/auto/candidates").json())
    candidate = rows[0]
    assert candidate["status"] == "pending" and candidate["duration"] == pytest.approx(30, abs=.2)
    assert called[0][0] == pytest.approx(20 * 32000, abs=6400) and called[0][1] == "tiny"
    assert client.get(candidate["thumbnail_url"]).status_code == 200
    movie = service.root / (candidate["id"] + ".mp4")
    report = subprocess.run([service.settings.binary("ffprobe"), "-v", "error", "-show_entries",
                             "stream=codec_type,start_time,duration", "-of", "json", str(movie)],
                            check=True, capture_output=True, timeout=15)
    tracks = {row["codec_type"]: row for row in json.loads(report.stdout)["streams"]}
    for key in ("start_time", "duration"):
        assert abs(float(tracks["audio"][key]) - float(tracks["video"][key])) < .15
    assert client.get(candidate["preview_url"], headers={"Range": "bytes=0-4095"}).status_code == 206
    assert len(client.get("/api/videos").json()) == 1
    keep = f"/api/live/auto/candidates/{candidate['id']}/keep"
    saved = client.post(keep).json()
    assert saved["status"] == "kept" and saved["video"]["has_audio"]
    assert client.post(keep).json()["video"]["id"] == saved["video"]["id"]
    assert client.post(keep.replace("/keep", "/discard")).status_code == 409
    assert not movie.exists() and len(client.get("/api/videos").json()) == 2
    capture = [item for item in client.get("/api/live/captures").json() if item["method"] == "auto"][0]
    assert capture["id"] == saved["video"]["id"]
    temporary = "a" * 32
    service.db.put("autoclips", {**candidate, "id": temporary, "video_id": None})
    original = service.root / f"{temporary}.mp4"
    copyfile(segments[0], original)
    assert client.post(f"/api/live/auto/candidates/{temporary}/discard").json()["status"] == "discarded"
    assert not original.exists() and len(client.get("/api/videos").json()) == 2


def test_reconnect_retires_pinned_files_without_joining_sources(client, sample_video):
    service = client.app.state.autoclip
    session = session_for(service)
    for index in range(8):
        put_segment(service, session, sample_video, index)
    service.propose(session, 0, AudioSignal(24, .9, .8, ("voz",)), AutoOptions(after=6), service.cancel)
    wait_for(lambda: session.buffer.pins)
    put_segment(service, session, sample_video, 0, generation=1)
    wait_for(lambda: service.pending is None)
    assert service.skipped == 1 and not session.buffer.pins
    assert client.get("/api/live/auto/candidates").json() == []
    assert [segment.generation for segment in session.buffer.closed] == [1]
    assert not list(session.buffer.folder.glob("g00-*.mkv"))


def test_overlap_hour_limit_and_disabled_mode_config(client):
    service = client.app.state.autoclip
    session = session_for(service)
    options = AutoOptions(per_hour=1, interval=5)
    signal = AudioSignal(47, .8, .7, ("voz",))
    service.windows.append((f"{session.buffer.folder.name}:0", (20, 52)))
    service.propose(session, 0, signal, options, service.cancel)
    assert service.skipped == 1
    service.saved.append(time())
    service.propose(session, 1, signal, options, service.cancel)
    assert service.skipped == 2 and service.pending is None
    bad = client.post("/api/live/auto/config", json={"enabled": False, "before": 29, "after": 8})
    assert bad.status_code == 422
    config = client.post("/api/live/auto/config", json={"enabled": False, "model": "base", "duration": 60})
    assert config.json()["options"]["model"] == "base" and config.json()["stage"] == "disabled"
    assert client.post("/api/live/auto/config", json={"enabled": True},
                       headers={"Origin": "https://example.test"}).status_code == 403


def test_live_detector_and_real_tiny_create_candidate_from_controlled_speech(client, tmp_path):
    if os.getenv("CLIPZONE_REAL_AI_AUTO_E2E") != "1":
        pytest.skip("Activa CLIPZONE_REAL_AI_AUTO_E2E=1 con Tiny y la demo hablada instalados.")
    source = ROOT / "demo" / "phase2-spoken-demo.mp4"
    models = ROOT / "models" / "whisper"
    if not source.is_file() or not (models / "tiny.pt").is_file():
        pytest.skip("Falta la demo hablada o Tiny.")
    service = client.app.state.autoclip
    require_vad()
    service.settings.model_dir = models
    recorded = generate_segments(service.settings, tmp_path / "speech", speech=source)
    session = session_for(service)
    response = client.post("/api/live/auto/config", json={"enabled": True, "minimum_score": 25, "sensitivity": "high"})
    assert response.status_code == 200, response.text
    for index, file in enumerate(recorded):
        put_segment(service, session, file, index)
        sleep(.42)
    try:
        rows = wait_for(lambda: client.get("/api/live/auto/candidates").json(), timeout=32)
    except pytest.fail.Exception:
        pytest.fail(client.get("/api/live/auto/status").json())
    assert rows[0]["excerpt"] and rows[0]["model"] == "tiny" and rows[0]["score"] >= 25
    assert 24 <= rows[0]["duration"] <= 30.3

