import json

import pytest

from app.services import direct_capture, multistream, youtube_live
from app.services.direct_source import DirectSource, StreamlinkSource, source_from_url
from app.services.obs import LiveError

CHANNEL = "UCaB" + "x" * 20
VIDEO = "abcdefghijk"
WATCH = f"https://www.youtube.com/watch?v={VIDEO}"
HANDLE = "https://www.youtube.com/@canal/live"


@pytest.mark.parametrize("url", [
    WATCH, f"https://www.youtube.com/live/{VIDEO}", f"https://youtu.be/{VIDEO}",
    f"https://youtu.be/{VIDEO}?si=compartido",
])
def test_normalizes_video_links(url):
    assert source_from_url(url) == DirectSource("youtube", VIDEO, WATCH)
    assert source_from_url("https://youtube.com/@MiCanal/live").url == "https://www.youtube.com/@micanal/live"


def page(player):
    return f"<script>var ytInitialPlayerResponse = {json.dumps(player)};</script>"


def player(**changes):
    return {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {"videoId": VIDEO, "channelId": CHANNEL, "author": "Canal de prueba"},
        **changes,
    }


@pytest.mark.parametrize(("data", "state"), [
    (player(microformat={"playerMicroformatRenderer": {"liveBroadcastDetails": {"isLiveNow": True}}}), "live"),
    (player(playabilityStatus={"status": "LIVE_STREAM_OFFLINE"}), "offline"),
    (player(microformat={"playerMicroformatRenderer": {"liveBroadcastDetails": {"startTimestamp": "2099-01-01T00:00:00Z"}}}), "scheduled"),
    (player(microformat={"playerMicroformatRenderer": {"liveBroadcastDetails": {"endTimestamp": "2025-01-01T00:00:00Z"}}}), "ended"),
    (player(), "vod"),
])
def test_distinguishes_broadcast_states_from_public_metadata(monkeypatch, data, state):
    monkeypatch.setattr(youtube_live, "public_page", lambda url: (url, page(data)))
    metadata = youtube_live.resolve_youtube(WATCH)
    assert metadata.state == state and metadata.channel == CHANNEL


def test_offline_handle_reads_channel_identity_when_live_page_is_missing(monkeypatch):
    def fetch(url):
        if url == HANDLE:
            raise LiveError("youtube_missing", "No hay directo.", 404)
        assert url == HANDLE.removesuffix("/live")
        metadata = {"metadata": {"channelMetadataRenderer": {"externalId": CHANNEL, "title": "Canal sin directo"}}}
        return url, "<script>var ytInitialData = " + json.dumps(metadata) + ";</script>"

    monkeypatch.setattr(youtube_live, "public_page", fetch)
    assert youtube_live.resolve_youtube(HANDLE) == youtube_live.YouTubeBroadcast(CHANNEL, "Canal sin directo", "offline")


def test_never_opens_streamlink_for_restricted_youtube(client, monkeypatch):
    restricted = player(playabilityStatus={"status": "LOGIN_REQUIRED", "reason": "Sign in"})
    monkeypatch.setattr(youtube_live, "public_page", lambda url: (url, page(restricted)))

    def unexpected(*args):
        pytest.fail("Streamlink no debe consultar calidades de una emisión restringida.")

    monkeypatch.setattr(client.app.state.direct.engine, "inspect", unexpected)
    assert client.post("/api/live/streamers", json={"url": WATCH}).status_code == 403
    assert client.post("/api/live/direct/probe", json={"url": WATCH}).json()["code"] == "direct_access"
    with pytest.raises(LiveError, match="público"):
        StreamlinkSource.input_url(source_from_url(WATCH))


def test_registration_deduplicates_a_channel_and_keeps_its_configuration(client, monkeypatch):
    live = youtube_live.YouTubeBroadcast(CHANNEL, "Canal de prueba", "live", VIDEO)
    monkeypatch.setattr(multistream, "resolve_youtube", lambda url: live)
    identifier = f"youtube:{CHANNEL}"
    params = {"streamer": identifier}
    response = client.post("/api/live/streamers", json={"url": HANDLE, "seconds": 120, "quality": "1080p60"})
    assert response.json()["id"] == identifier
    assert client.post("/api/live/auto/config", params=params, json={"minimum_score": 72, "detection_mode": "irl"}).is_success
    monkeypatch.setattr(direct_capture, "resolve_youtube", lambda url: live)
    monkeypatch.setattr(client.app.state.direct.engine, "inspect", lambda *_: ["1080p60", "1080p", "720p"])
    assert client.post("/api/live/direct/probe", params=params, json={"url": HANDLE}).json()["qualities"] == ["1080p60", "1080p", "720p"]
    response = client.post("/api/live/streamers", json={"url": f"https://youtu.be/{VIDEO}"})
    assert response.json() == {**client.get("/api/live/streamers").json()[0], "seconds": 120, "quality": "1080p60"}
    assert client.post("/api/live/streamers", params=params, json={"url": WATCH, "seconds": 300}).is_success
    rows = client.get("/api/live/direct/channels").json()["channels"]
    assert len(rows) == 1 and rows[0]["url"] == WATCH and rows[0]["seconds"] == 300
    assert rows[0]["autoclip"]["options"]["minimum_score"] == 72
    assert rows[0]["autoclip"]["options"]["detection_mode"] == "irl"


def test_different_video_identifier_is_rejected(monkeypatch):
    monkeypatch.setattr(youtube_live, "public_page", lambda url: (url, page(player())))
    with pytest.raises(LiveError, match="distinto"):
        youtube_live.resolve_youtube("https://www.youtube.com/watch?v=12345678901")
