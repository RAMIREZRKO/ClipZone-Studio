"""Identidad y estado de un directo mediante los metadatos públicos de YouTube."""
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .obs import LiveError

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
YT = "https://www.youtube.com"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
HANDLE = re.compile(r"[\w][\w.-]{0,39}")
BroadcastState = Literal["live", "scheduled", "vod", "offline", "ended"]
STATE_MESSAGES = {
    "scheduled": "La transmisión de YouTube está programada y aún no ha empezado.",
    "vod": "El enlace de YouTube corresponde a un vídeo bajo demanda.",
    "offline": "El canal de YouTube no está en directo.",
    "ended": "El directo de YouTube finalizó. Puedes guardar el fragmento disponible.",
}


def youtube_url(parts) -> tuple[str, str]:
    """Devuelve la URL normalizada y un identificador provisional hasta consultar el canal."""
    host, path = parts.hostname, unquote(parts.path, errors="strict").rstrip("/")
    query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    video = [value for key, value in query if key == "v"]
    allowed = {"si", "t", "feature", "v"} if host != "youtu.be" and path == "/watch" else {"si", "t", "feature"}
    if any(key not in allowed for key, _ in query):
        raise ValueError
    if host == "youtu.be":
        candidate = path.removeprefix("/")
    elif path == "/watch":
        candidate = video[0] if len(video) == 1 else ""
    elif path.startswith("/live/"):
        candidate = path.removeprefix("/live/")
    else:
        match = re.fullmatch(r"/@([^/]+)/live", path)
        if match and HANDLE.fullmatch(match[1]):
            handle = match[1].lower()
            return f"{YT}/@{quote(handle)}/live", handle
        match = re.fullmatch(r"/channel/(UC[A-Za-z0-9_-]{22})/live", path)
        if match:
            return f"{YT}{path}", match[1]
        raise ValueError
    if VIDEO_ID.fullmatch(candidate):
        return f"{YT}/watch?v={candidate}", candidate
    raise ValueError


def denied() -> LiveError:
    return LiveError("direct_access", "YouTube requiere acceso adicional. Usa un directo público y autorizado.", 403)


class YouTubeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != "https" or parts.netloc.lower() not in YOUTUBE_HOSTS:
            raise denied()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_page(url: str) -> tuple[str, str]:
    try:
        opener = build_opener(ProxyHandler({}), YouTubeRedirects())
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
                                        "Accept-Language": "en-US,en;q=0.8"})
        with opener.open(request, timeout=6) as page:
            return page.url, page.read(6 * 1024**2).decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code == 404:
            raise LiveError("youtube_missing", "No se encontró ese canal o vídeo de YouTube.", 404) from exc
        if exc.code in {401, 403, 451}:
            raise denied() from exc
        raise LiveError("direct_network", "No se pudo consultar el estado del directo de YouTube.", 502) from exc
    except (URLError, OSError) as exc:
        raise LiveError("direct_network", "No se pudo consultar el estado del directo de YouTube.", 502) from exc


def embedded_json(html: str, variable: str) -> dict:
    pattern = rf'(?:\b{variable}|["\x27]{variable}["\x27]\])\s*=\s*(?=\{{)'
    for match in re.finditer(pattern, html):
        try:
            value, _ = json.JSONDecoder().raw_decode(html, match.end())
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    return {}


class ChannelMetadata(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.identifier = ""
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        if tag == "meta":
            attrs = dict(attributes)
            if attrs.get("itemprop") == "channelId":
                self.identifier = attrs.get("content") or ""


@dataclass(frozen=True)
class YouTubeBroadcast:
    channel: str
    name: str
    state: BroadcastState
    video_id: str | None = None
    manifest: str | None = None

    @property
    def watch_url(self) -> str:
        return f"{YT}/watch?v={self.video_id}"


def public_manifest(player: dict) -> str | None:
    url = (player.get("streamingData") or {}).get("hlsManifestUrl")
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    if (parts.scheme == "https" and parts.netloc == parts.hostname
            and (parts.hostname or "").endswith(".googlevideo.com")):
        return url
    return None


def broadcast_state(player: dict) -> BroadcastState:
    playability = player.get("playabilityStatus") or {}
    details = player.get("videoDetails") or {}
    microformat = (player.get("microformat") or {}).get("playerMicroformatRenderer") or {}
    dates = microformat.get("liveBroadcastDetails") or {}
    status = playability.get("status")
    if details.get("isPrivate") or status in {"LOGIN_REQUIRED", "AGE_CHECK_REQUIRED", "CONTENT_CHECK_REQUIRED", "UNPLAYABLE", "ERROR"}:
        raise denied()
    if status not in {"OK", "LIVE_STREAM_OFFLINE"}:
        raise LiveError("youtube_metadata", "YouTube no confirmó si el vídeo está en directo.", 502)
    if dates.get("endTimestamp"):
        return "ended"
    if status == "OK" and not playability.get("reason") and (details.get("isLive") is True or dates.get("isLiveNow") is True):
        return "live"
    if status == "OK" and playability.get("reason"):
        raise denied()
    slate = (playability.get("liveStreamability") or {}).get("liveStreamabilityRenderer") or {}
    slate = (slate.get("offlineSlate") or {}).get("liveStreamOfflineSlateRenderer") or {}
    if slate.get("scheduledStartTime"):
        return "scheduled"
    if dates.get("startTimestamp"):
        try:
            if datetime.fromisoformat(dates["startTimestamp"]) > datetime.now(timezone.utc):
                return "scheduled"
        except (ValueError, TypeError):
            pass
    if status == "LIVE_STREAM_OFFLINE":
        return "offline"
    return "ended" if details.get("isLiveContent") else "vod"


def resolve_youtube(url: str) -> YouTubeBroadcast:
    parts = urlsplit(url)
    channel_page = parts.path.endswith("/live")
    try:
        _, html = public_page(url)
    except LiveError as exc:
        if not channel_page or exc.code != "youtube_missing":
            raise
        html = ""
    player = embedded_json(html, "ytInitialPlayerResponse")
    if player:
        state = broadcast_state(player)
        details = player.get("videoDetails") or {}
        microformat = (player.get("microformat") or {}).get("playerMicroformatRenderer") or {}
        channel = details.get("channelId") or microformat.get("externalChannelId") or ChannelMetadata(html).identifier
        requested = next((value for key, value in parse_qsl(parts.query) if key == "v"), None)
        video = details.get("videoId") or requested or ""
        if requested and video != requested:
            raise LiveError("youtube_metadata", "YouTube devolvió un vídeo distinto del solicitado.", 422)
        if CHANNEL_ID.fullmatch(channel) and VIDEO_ID.fullmatch(video):
            name = details.get("author") or microformat.get("ownerChannelName") or channel
            return YouTubeBroadcast(channel, name[:100], state, video, public_manifest(player) if state == "live" else None)
        if not channel_page:
            raise LiveError("youtube_metadata", "YouTube no publicó la identidad del canal de este vídeo.", 422)
    elif not channel_page:
        raise LiveError("youtube_metadata", "YouTube no publicó el estado de este vídeo.", 502)

    if not html or not (embedded_json(html, "ytInitialData").get("metadata") or {}).get("channelMetadataRenderer"):
        _, html = public_page(url.removesuffix("/live"))
    metadata = (embedded_json(html, "ytInitialData").get("metadata") or {}).get("channelMetadataRenderer") or {}
    channel = metadata.get("externalId") or ChannelMetadata(html).identifier
    if CHANNEL_ID.fullmatch(channel):
        return YouTubeBroadcast(channel, (metadata.get("title") or channel)[:100], "offline")
    raise LiveError("youtube_metadata", "YouTube no publicó la identidad del canal. Prueba con el enlace de un directo público.", 422)
