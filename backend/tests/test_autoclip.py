from array import array
import json
from math import pi, sin
import os
from pathlib import Path
from shutil import copyfile
import subprocess
from threading import Event
from time import monotonic, sleep, time

import pytest
from fastapi.testclient import TestClient

from app.ai.live_detector import AudioSignal, BLOCK_BYTES, LiveDetector, editorial_score
from app.config import ROOT
from app.main import create_app
from app.services.autoclip import AutoOptions
from app.services.direct_buffer import DirectBuffer
from app.services.direct_capture import CaptureSession
from app.services.direct_source import DirectSource
from app.services.obs import LiveError
from app.storage_location import GB


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


def test_reactions_require_sustained_voice_and_gameplay_requires_separate_changes():
    require_vad()
    reaction = LiveDetector("balanced", "reaction")
    gameplay = LiveDetector("balanced", "gameplay")
    for detector in (reaction, gameplay):
        for count in range(12):
            assert detector.measure(-38, .08, 0., count) is None
        assert detector.measure(-8, .8, .95, 12) is None
        assert detector.measure(-36, .07, 0., 13) is None
    assert reaction.measure(-8, .8, 0., 14) is None
    effects = gameplay.measure(-8, .8, 0., 14)
    assert effects and effects.kind == "gameplay"
    for count in range(16, 25):
        reaction.measure(-39, .06, .15, count)
    assert reaction.measure(-18, .4, .9, 25) is None
    voiced = reaction.measure(-20, .3, .9, 26)
    assert voiced and voiced.voice >= .6 and voiced.kind == "reaction"


def test_constant_music_and_long_running_window_remain_bounded():
    require_vad()
    detector = LiveDetector("high", "gameplay")
    chord = array("h", (int(5600 * sum(sin(2 * pi * freq * i / 16000) for freq in (220, 330, 440)) / 3)
                        for i in range(BLOCK_BYTES // 2))).tobytes()
    # Procesa PCM con WebRTC. Después simula una sesión larga sin ampliar la memoria del modelo acústico.
    for seconds in range(35):
        assert list(detector.feed(chord * 3, seconds)) == []
    for sample in range(7200):
        assert detector.measure(-22 + sample % 3, .18, .88, sample) is None
    assert len(detector.levels) == 80
    assert len(detector.voices) == len(detector.attacks) == 6 and len(detector.accents) == 3


def transcript(text="¿Cómo conseguimos este resultado increíble? Mira el cambio y verás por qué funciona tan bien.", start=11):
    words = text.split()
    return {"words": [{"text": word, "start": start + i * .28, "end": start + .2 + i * .28}
                      for i, word in enumerate(words)]}


def test_editorial_score_is_explainable_and_rejects_speechless_candidates():
    wave = AudioSignal(24, .92, .87, ("intensidad alta",))
    scored = editorial_score(transcript(), 14, wave)
    assert 58 <= scored["score"] <= 100
    assert set(scored["metrics"]) == {"intensity", "voice", "alignment", "confidence", "context", "coherence", "repetition"}
    assert scored["title"] and "contexto variado" in scored["reason"]
    assert editorial_score({"words": []}, 14, wave)["score"] == 0
    noise = AudioSignal(14, 1., 0., ("picos de audio",), "gameplay")
    assert editorial_score({"words": []}, 14, noise, "gameplay")["score"] <= 34
    assert editorial_score(transcript(start=19), 14, noise, "mixed")["score"] <= 34


def test_modes_separate_editorial_evidence_and_penalize_repetition_or_low_confidence():
    signal = AudioSignal(14, .75, .86, ("voz sostenida",))
    reaction = transcript("¡Dios mío, qué locura! La cámara cayó justo al borde del puente y casi me tumba.")
    gameplay = transcript("En la última vida esquivé la barrera, encontré la salida y gané la ronda final.")
    repeated = transcript("Y si y si y si y si y si y si y si y si y si y si", start=11)
    dialogue = transcript("Quería preguntarte por aquel trabajo. Llámame cuando puedas para hablar sobre tu próxima visita.")
    uncertain = {"words": [{**word, "probability": .28, "no_speech": .53} for word in reaction["words"]]}
    assert editorial_score(reaction, 14, signal, "mixed")["detection_type"] == "reaction"
    assert editorial_score(reaction, 14, signal, "reaction")["score"] > editorial_score(reaction, 14, signal, "gameplay")["score"]
    assert editorial_score(gameplay, 14, signal, "gameplay")["score"] >= 70
    assert editorial_score(gameplay, 14, signal, "mixed")["detection_type"] == "gameplay"
    assert editorial_score(repeated, 14, signal)["score"] <= 35
    assert editorial_score(dialogue, 14, signal, "mixed")["score"] < 58
    assert "baja confianza" in editorial_score(uncertain, 14, signal)["reason"]
    quiet = AudioSignal(14, 0., signal.voice, signal.reasons)
    assert editorial_score(reaction, 14, signal)["score"] - editorial_score(reaction, 14, quiet)["score"] <= 4


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


@pytest.mark.parametrize("mode", ("mixed", "irl"))
def test_waits_for_postroll_renders_synchronised_video_and_keeps_or_discards_safely(client, settings, tmp_path, monkeypatch, mode):
    service = client.app.state.autoclip
    session = session_for(service)
    segments = generate_segments(settings, tmp_path / "recording")
    for index in range(8):
        put_segment(service, session, segments[index], index)
    called = []
    def transcribe(audio, model, output, cancellation, on_start=None):
        if on_start:
            on_start()
        called.append((audio.stat().st_size, model))
        if mode == "irl":
            return transcript("Cuando vivía con mi abuela, me escondía en el patio. Pero al final descubrió mi bicicleta detrás del cobertizo.")
        return transcript()
    monkeypatch.setattr(service.analysis, "transcribe_live", transcribe)
    options = AutoOptions(before=12, after=6, minimum_score=65 if mode == "irl" else 20, detection_mode=mode)
    signal = (AudioSignal(24, 0., .9, ("conversación sostenida",), "conversation") if mode == "irl"
              else AudioSignal(24, .95, .9, ("pico con voz",)))
    service.propose(session, 0, signal, options, service.cancel)
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
    if mode == "irl":
        assert candidate["score"] >= 65 and candidate["detection_type"] == "irl"
    window_seconds = 24 if mode == "irl" else 20
    assert called[0][0] == pytest.approx(window_seconds * 32000, abs=6400) and called[0][1] == "tiny"
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
    assert config.json()["options"]["model"] == "tiny" and config.json()["stage"] == "disabled"
    assert config.json()["options"]["detection_mode"] == "mixed"
    assert client.post("/api/live/auto/config", json={"detection_mode": "explosion"}).status_code == 422
    assert client.post("/api/live/auto/config", json={"enabled": True},
                       headers={"Origin": "https://example.test"}).status_code == 403


@pytest.mark.parametrize("platform", ["kick", "youtube"])
def test_live_detector_and_real_tiny_create_candidate_from_controlled_speech(client, tmp_path, platform):
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
    if platform == "youtube":
        session.source = DirectSource("youtube", "UC" + "x" * 22, "https://www.youtube.com/watch?v=abcdefghijk", "Canal de prueba")
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
    assert rows[0]["platform"] == platform
    if platform == "youtube":
        assert rows[0]["channel_name"] == "Canal de prueba" and client.get(rows[0]["preview_url"]).status_code == 200
    assert 24 <= rows[0]["duration"] <= 30.3


def test_ongoing_match_result_passes_without_accepting_out_of_context_loss():
    signal = AudioSignal(14, .32, .9, ("voz sostenida",))
    game = transcript("En el marcador del tercer partido van uno a uno. Miguel va perdiendo por el último penalti ahora.",
                      start=10.6)
    plain = transcript("El negocio va perdiendo dinero, con estos gastos de la oficina hay que revisar las cuentas.",
                       start=13)
    assert editorial_score(game, 14, signal, "mixed")["score"] >= 65
    assert editorial_score(plain, 14, signal, "mixed")["score"] <= 55


def test_rejected_attempt_does_not_spend_interval_and_preserves_alternative(client, monkeypatch):
    service = client.app.state.autoclip
    session = session_for(service)
    options = AutoOptions(interval=120, minimum_score=65)
    # Representa un Whisper en curso que aún no ha producido un clip.
    service.saved_channel = (session.source.platform, session.source.channel)
    service.last_attempt = monotonic()
    service.pending = object()
    service.propose(session, 0, AudioSignal(60, .28, .67, ("voz",)), options, service.cancel)
    service.propose(session, 0, AudioSignal(64, .58, .92, ("voz",)), options, service.cancel)
    assert len(service.deferred) == 2 and service.skipped == 0
    service.pending = None
    service.last_attempt -= 10
    calls = []
    monkeypatch.setattr(service.executor, "submit", lambda *args: calls.append(args) or object())
    service.drain()
    assert calls[0][4].time == 64 and service.pending is not None
    service.pending = None
    service.last_attempt -= 10
    service.saved.append(time())
    service.drain()
    assert service.omissions["saved_interval"] == 1 and not service.deferred


def test_audio_decode_error_is_exposed_in_channel_diagnostics(client, sample_video, monkeypatch):
    service = client.app.state.autoclip
    session = session_for(service)
    put_segment(service, session, sample_video, 0)
    def failure(*args, **kwargs):
        from app.services.media import MediaError
        raise MediaError("FFmpeg no pudo extraer el audio.")
    monkeypatch.setattr(service, "pcm", failure)
    service.apply_options(AutoOptions(enabled=True))
    details = wait_for(lambda: service.progress()["diagnostics"] if service.audio_failures else None)
    assert details["audio_failures"] == 1 and "extraer el audio" in details["last_error"]


@pytest.mark.parametrize("end", ["stopping", "ended", "error"])
def test_capture_end_cancels_candidate_and_keeps_preferences(client, sample_video, monkeypatch, end):
    service = client.app.state.autoclip
    session = session_for(service)
    options = AutoOptions(enabled=True, before=12, after=6)
    for index in range(10):
        put_segment(service, session, sample_video, index)
    began, cancelled = Event(), Event()

    def pcm(inputs, *args, **kwargs):
        return bytes(32000) if "concat" in inputs else b""

    def infer(audio, model, output, stop, on_start=None):
        on_start()
        began.set()
        if stop.wait(5):
            cancelled.set()
        return None

    monkeypatch.setattr(service, "pcm", pcm)
    monkeypatch.setattr(service.analysis, "transcribe_live", infer)
    service.apply_options(options)
    service.propose(session, 0, AudioSignal(24, .9, .8, ("voz",)), options, service.cancel)
    assert began.wait(6)
    if end == "stopping":
        assert client.post("/api/live/direct/stop").json()["state"] == end
    else:
        service.direct.transition(session, end)
    assert cancelled.wait(2)
    wait_for(lambda: service.pending is None and service.progress()["stage"] == "waiting")
    assert service.progress()["options"]["enabled"] and not session.buffer.pins and not service.deferred
    assert client.get("/api/live/auto/candidates").json() == []


def test_edits_offline_preferences_and_global_quota_survive_restart(settings, monkeypatch):
    status = "/api/live/auto/status"
    config = "/api/live/auto/config"
    storage = "/api/live/auto/storage"
    west, other = {"streamer": "kick:fuera"}, {"streamer": "twitch:otro"}
    with TestClient(create_app(settings)) as client:
        for url in ("https://kick.com/fuera", "https://www.twitch.tv/otro"):
            assert client.post("/api/live/streamers", json={"url": url}).status_code == 200
        state = client.app.state
        channel = state.db.get("streamers", west["streamer"])
        state.db.put("streamers", {**channel, "auto": {"enabled": True, "detection_mode": "reaction",
                                                     "duration": 90, "before": 50, "after": 8, "minimum_score": 65}})
        monkeypatch.setattr(state.direct.engine, "inspect", lambda *_: [])
        assert not client.post("/api/live/direct/probe", params=west, json={"url": channel["url"]}).json()["live"]
        original = client.get(status, params=west).json()
        assert original["stage"] == "waiting" and original["options"]["detection_mode"] == "irl"
        assert original["detection_modes"] == ["gameplay", "irl", "mixed"]
        assert original["max_bytes"] == 5 * GB

        def missing_dependencies(_):
            raise LiveError("auto_model", "Falta Whisper Tiny.")

        monkeypatch.setattr(state.autoclip, "check_options", missing_dependencies)
        assert client.post(config, params=west, json={"after": 10, "minimum_score": 74}).json()["options"] == {
            **original["options"], "after": 10, "minimum_score": 74}
        assert client.post(config, params=west, json={"before": 80, "after": 20}).status_code == 422
        assert client.post(config, params=west, json={"enabled": False}).json()["stage"] == "disabled"
        assert client.post(config, params=west, json={"enabled": True}).json()["code"] == "auto_model"
        assert client.get(status, params=other).json()["options"]["minimum_score"] == 58
        pending_id = "b" * 32
        path = state.autoclip.root / f"{pending_id}.mp4"
        path.write_bytes(b"candidato conservado")
        state.db.put("autoclips", {"id": pending_id, "status": "pending", "video_id": None})
        for limit in (1, 5, 10, 20):
            response = client.post(storage, json={"limit_gb": limit})
            assert response.json()["max_bytes"] == limit * GB
        assert client.post(storage, json={"limit_gb": 2}).status_code == 422
        assert client.post(storage, json={"limit_gb": 1}).status_code == 200
        assert client.get(status, params=other).json()["max_bytes"] == GB
        assert path.read_bytes() == b"candidato conservado"
    with TestClient(create_app(settings)) as client:
        options = client.get(status, params=west).json()
        assert options["candidate_limit_gb"] == 1 and options["options"]["minimum_score"] == 74
        assert options["options"]["detection_mode"] == "irl" and options["options"]["enabled"] is False
        assert options["options"]["before"] == 50 and options["options"]["after"] == 10
        assert client.get(f"/api/live/auto/candidates/{pending_id}/preview").content == b"candidato conservado"
        assert client.get("/api/live/direct/status", params=west).json()["max_bytes"] == 512 * 1024**2


def test_irl_samples_steady_voice_without_acoustic_peaks():
    require_vad()
    for mode in ("irl", "mixed", "gameplay"):
        detector = LiveDetector("balanced", mode)
        hits = [hit for i in range(250) if (hit := detector.measure(-31, .12, .9, i * .3))]
        if mode == "gameplay":
            assert not hits
        else:
            assert 2 <= len(hits) <= 4
            assert all(hit.kind == "conversation" and hit.intensity == 0 for hit in hits)
            assert all(second.time - first.time >= 23.99 for first, second in zip(hits, hits[1:]))
    irl = LiveDetector("high", "irl")
    assert not any(irl.measure(-15, .8, .1, i * .3) for i in range(200))


@pytest.mark.parametrize(("text", "reason"), [
    ("Cuando vivía con mi abuela, me escondía en el patio. Pero al final ella descubrió la bicicleta detrás del cobertizo.", "relato"),
    ("Nunca te dije que perdí todos mis ahorros intentando pagar la operación de mi hermano. Fue una temporada difícil para la familia.", "revelación personal"),
    ("Pensé que me pedía la llave del coche. En vez de eso, me pidió que recogiera el pollo. Nos reímos durante todo el camino.", "humor"),
    ("No estoy de acuerdo con ese contrato porque nosotros pagamos el alquiler del local y ellos se quedan con todos los ingresos.", "desacuerdo"),
    ("Necesitamos mantener abierto el centro cultural porque el barrio perdió la biblioteca y los jóvenes ensayan allí cada sábado.", "postura"),
    ("¿Quién pagó la reparación del apartamento? En realidad, la vecina vendió su bicicleta para ayudar a mi familia aquel invierno.", "pregunta recibe"),
    ("Me puse a llorar porque encontré la carta de mi madre dentro del abrigo que llevaba el día de su despedida.", "emoción"),
])
def test_irl_scores_developed_conversational_passages_without_volume(text, reason):
    signal = AudioSignal(15, 0., .74, ("habla sostenida",), "conversation")
    result = editorial_score(transcript(text, start=10), 15, signal, "irl")
    assert result["score"] >= 65 and result["detection_type"] == "irl"
    assert reason in result["reason"]
    assert editorial_score(transcript(text, start=10), 15, signal, "mixed")["score"] == result["score"]


def test_irl_clamps_chitchat_repetition_and_unreliable_transcripts():
    signal = AudioSignal(15, 1., .9, ("voz",), "conversation")
    ordinary = transcript("Los lunes suelo comprar fruta y pan en el mercado. Por la tarde preparo la comida para mañana.")
    repeated = transcript("Te confieso te confieso te confieso te confieso te confieso te confieso.")
    story = transcript("El otro día me escondí en el patio, pero al final encontraron mi bicicleta detrás de la puerta.")
    untrusted = {"words": [{**word, "probability": .3} for word in story["words"]]}
    assert editorial_score(ordinary, 15, signal, "irl")["filters"] == ["no_irl_context"]
    assert editorial_score(repeated, 15, signal, "irl")["score"] <= 35
    assert editorial_score(untrusted, 15, signal, "irl")["score"] <= 39
    assert editorial_score({"words": []}, 15, signal, "irl")["score"] == 0


def test_legacy_reaction_maps_to_irl_and_modes_are_independent_per_channel(client):
    first, second = "kick:preguntas", "twitch:torneo"
    for source in ("https://kick.com/preguntas", "https://www.twitch.tv/torneo"):
        assert client.post("/api/live/streamers", json={"url": source}).status_code == 200
    state = client.app.state.db
    channel = state.get("streamers", first)
    state.put("streamers", {**channel, "auto": {"enabled": False, "detection_mode": "reaction", "minimum_score": 65}})
    status = "/api/live/auto/status"
    config = "/api/live/auto/config"
    assert client.get(status, params={"streamer": first}).json()["options"]["detection_mode"] == "irl"
    for identifier, mode in ((first, "irl"), (second, "gameplay")):
        saved = client.post(config, params={"streamer": identifier}, json={"detection_mode": mode, "minimum_score": 65})
        assert saved.status_code == 200 and saved.json()["options"]["detection_mode"] == mode
    assert client.get(status, params={"streamer": first}).json()["options"]["detection_mode"] == "irl"
    assert client.get(status, params={"streamer": second}).json()["options"]["detection_mode"] == "gameplay"
    assert state.get("streamers", first)["auto"]["minimum_score"] == 65

