from uuid import uuid4

from app.captions import CaptionSegment, clip_captions, group_words
from app.models import AnalysisRequest
from test_api import upload


def test_whisper_groups_and_rebases_at_both_clip_boundaries():
    rows = [
        {"text": "Uno", "start": 1.0, "end": 1.3},
        {"text": "dos.", "start": 1.4, "end": 1.8},
        {"text": "Tres", "start": 2.5, "end": 2.8},
        {"text": "cuatro.", "start": 2.8, "end": 3.4},
    ]
    groups = group_words(rows, 5)
    assert [item.text for item in groups] == ["Uno dos.", "Tres cuatro."]
    first, last = clip_captions(groups, 1.35, 2.7, "original")
    assert first["start"] == 0 and first["text"] == "dos."
    assert round(last["end"], 2) == 1.35 and last["text"] == "Tres"
    assert round(first["words"][0]["start"], 2) == .05


def test_generation_edits_revision_and_immutable_analysis(client, sample_video):
    assert AnalysisRequest().language == "auto"
    video = upload(client, sample_video)
    identifier = uuid4().hex
    transcript = {"language": "es", "text": "¡Hola mundo!", "words": [
        {"text": "¡Hola", "start": .4, "end": .7}, {"text": "mundo!", "start": .7, "end": 1.1},
    ]}
    analysis = {"id": identifier, "video_id": video["id"], "status": "completed",
                "options": {"model": "tiny", "language": "auto"}, "result": {"transcript": transcript}}
    client.app.state.db.put("analyses", analysis)
    path = f"/api/videos/{video['id']}/captions"
    generated = client.post(path + "/generate", json={"analysis_id": identifier})
    assert generated.status_code == 200, generated.text
    track = generated.json()
    assert track["audio_language"] == "es"
    track["segments"][0].update(text="¡Hola, Bogotá!", start=.2, end=1.4)
    saved = client.post(path, json=track)
    assert saved.status_code == 200, saved.text
    assert client.get(path).json()["segments"][0]["text"] == "¡Hola, Bogotá!"
    assert client.post(path, json=track).status_code == 409
    assert client.app.state.db.get("analyses", identifier) == analysis
    assert client.app.state.db.get("videos", video["id"]) is not None


def test_rejects_out_of_range_or_overlapping_segments(client, sample_video):
    video = upload(client, sample_video)
    path = f"/api/videos/{video['id']}/captions"
    segment = CaptionSegment(id=uuid4().hex, start=.1, end=1, text="Texto").model_dump()
    assert client.post(path, json={"segments": [{**segment, "end": 20}]}).status_code == 422
    assert client.post(path, json={"segments": [segment, {**segment, "id": uuid4().hex}]}).status_code == 422
    assert client.get(path).json()["segments"] == []
