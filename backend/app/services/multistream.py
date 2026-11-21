"""Coordina la captura directa y conserva la configuración de cada canal."""
from collections import Counter
from threading import BoundedSemaphore, RLock
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .analysis import AnalysisQueue
from .autoclip import AutoClip, AutoFields, AutoOptions
from .direct_capture import ACTIVE, MIN_FREE, DirectCapture, SourceRequest, StartRequest
from .direct_source import QUALITY, DirectSource, source_from_url
from .library import VideoLibrary
from .obs import LiveError
from .youtube_live import STATE_MESSAGES, YouTubeBroadcast, resolve_youtube

class CaptureLimit(BaseModel):
    max_active: Literal[4, 6, 8, 10]


class StreamerSettings(SourceRequest):
    template_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    quality: str | None = Field(default=None, max_length=25, pattern=rf"^{QUALITY.pattern}$")
    seconds: Literal[30, 60, 90, 120, 300] = 60


class MultiStream:
    def __init__(self, library: VideoLibrary, analysis: AnalysisQueue):
        self.library, self.analysis, self.db = library, analysis, library.db
        self.lock = RLock()
        self.probes = BoundedSemaphore(2)
        self.channel_probes: dict[str, dict] = {}
        self.max_active = CaptureLimit.model_validate(self.db.get("settings", "multistream") or {"max_active": 4}).max_active
        direct = DirectCapture(library.settings, library)
        auto = AutoClip(direct, analysis)
        self.primary = (direct, auto)
        self.idle = direct.status(environment=False)
        self.idle_auto = auto.progress()
        self.legacy = (self.primary, self.new_capture())
        self.channels: dict[str, tuple[DirectCapture, AutoClip]] = {}
        self.saves: Counter[DirectCapture] = Counter()

    def new_capture(self) -> tuple[DirectCapture, AutoClip]:
        direct = DirectCapture(self.library.settings, self.library, shared=self.primary[0])
        return direct, AutoClip(direct, self.analysis, shared=self.primary[1])

    def settings(self, identifier: str) -> dict:
        stream = self.db.get("streamers", identifier)
        if stream is None:
            raise LiveError("streamer_missing", "El canal ya no está registrado.", 404)
        return stream

    def identify_youtube(self, source: DirectSource) -> YouTubeBroadcast:
        if not self.probes.acquire(blocking=False):
            raise LiveError("direct_probe_limit", "Ya se están comprobando dos canales. Inténtalo de nuevo en unos segundos.", 429)
        try:
            return resolve_youtube(source.url)
        finally:
            self.probes.release()

    def update(self, body: StreamerSettings, channel_id: str | None = None) -> dict:
        source = source_from_url(body.url)
        broadcast = self.identify_youtube(source) if source.platform == "youtube" and channel_id is None else None
        identifier = f"{source.platform}:{broadcast.channel if broadcast else source.channel}"
        changes = body.model_dump(exclude={"url"}, exclude_unset=True)
        with self.lock:
            previous = self.settings(channel_id) if channel_id is not None else self.db.get("streamers", identifier)
            if channel_id is not None:
                if previous["url"] != source.url or (source.platform != "youtube" and channel_id != identifier):
                    raise LiveError("direct_source", "La URL no corresponde al canal registrado.", 422)
                identifier = channel_id
            if broadcast:
                pair = self.channels.get(identifier)
                checking = self.channel_probes.get(identifier, {}).get("connection") == "checking"
                busy = pair and (pair[0].is_active() or self.saves[pair[0]] or pair[1].pending)
                if previous and (busy or checking):
                    return previous
                changes.update(url=source.url, name=broadcast.name)
            if changes.get("template_id"):
                template = self.db.get("templates", changes["template_id"])
                if not template or template["options"]["fit"] != "split":
                    raise LiveError("streamer_template", "Selecciona una plantilla guardada de Streamer + Gameplay.", 422)
            if previous is not None and not changes:
                return previous
            defaults = {"id": identifier, "url": source.url, "template_id": None, "quality": None, "seconds": 60}
            saved = self.db.put("streamers", {**defaults, **(previous or {}), **changes})
            if broadcast:
                self.channel_probes[identifier] = {"connection": "online" if broadcast.state == "live" else "offline",
                                                    "broadcast_state": broadcast.state, "qualities": []}
            return saved

    def remove(self, identifier: str) -> None:
        with self.lock:
            self.settings(identifier)
            if self.channel_probes.get(identifier, {}).get("connection") == "checking":
                raise LiveError("direct_busy", "Espera a que termine la comprobación del canal.")
            pair = self.channels.get(identifier)
            if pair and not self.release(identifier, pair):
                raise LiveError("streamer_busy", "Detén la captura y espera a que terminen los guardados antes de eliminar el canal.")
            self.db.delete("streamers", identifier)
            self.channel_probes.pop(identifier, None)

    def resolve(self, identifier: str | None, slot: int) -> tuple[DirectCapture, AutoClip] | None:
        if identifier is None:
            return self.legacy[slot]
        self.settings(identifier)
        return self.channels.get(identifier)

    def inspect(self, body: SourceRequest, identifier: str | None) -> dict:
        if not self.probes.acquire(blocking=False):
            raise LiveError("direct_probe_limit", "Ya se están comprobando dos canales. Inténtalo de nuevo en unos segundos.", 429)
        try:
            if identifier is None:
                return self.primary[0].inspect(body.url)
            with self.lock:
                url = self.settings(identifier)["url"]
                pair = self.channels.get(identifier)
                previous = self.channel_probes.get(identifier)
                if (pair and pair[0].is_active()) or (previous and previous["connection"] == "checking"):
                    raise LiveError("direct_busy", "El canal ya está comprobándose o capturando.")
                self.channel_probes[identifier] = {"connection": "checking", "qualities": []}
            try:
                result = self.primary[0].inspect(url)
                if result.get("platform") == "youtube" and identifier != f"youtube:{result['channel']}":
                    raise LiveError("direct_source", "La emisión de YouTube corresponde a otro canal.", 422)
            except Exception:
                with self.lock:
                    if previous:
                        self.channel_probes[identifier] = previous
                    else:
                        self.channel_probes.pop(identifier, None)
                raise
            with self.lock:
                self.channel_probes[identifier] = {"connection": "online" if result["live"] else "offline",
                                                    "qualities": result["qualities"],
                                                    "broadcast_state": result.get("broadcast_state")}
            return result
        finally:
            self.probes.release()

    def release(self, identifier: str | None, pair: tuple[DirectCapture, AutoClip]) -> bool:
        direct, auto = pair
        if self.saves[direct] or auto.pending or not direct.discard_buffer():
            return False
        if identifier is not None:
            auto.shutdown()
            del self.channels[identifier]
        return True

    def entries(self):
        return [*((None, pair) for pair in self.legacy), *self.channels.items()]

    def configure_limit(self, body: CaptureLimit) -> dict:
        with self.lock:
            self.db.put("settings", {"id": "multistream", **body.model_dump()})
            self.max_active = body.max_active
            return self.overview()

    def connection(self, identifier: str | None, capture: dict) -> dict:
        if capture["state"] in ACTIVE:
            return {"connection": "online" if capture["state"] == "capturing" else "checking", "qualities": [],
                    "broadcast_state": capture.get("broadcast_state")}
        return self.channel_probes.get(identifier, {"connection": "offline" if capture["state"] == "ended" else "unknown",
                                                    "qualities": [], "broadcast_state": capture.get("broadcast_state")})

    def start(self, body: StartRequest, identifier: str | None, slot: int) -> dict:
        source = source_from_url(body.url)
        if source.platform == "youtube" and identifier is None:
            broadcast = self.identify_youtube(source)
            source = DirectSource("youtube", broadcast.channel, source.url, broadcast.name)
        with self.lock:
            pair = self.resolve(identifier, slot)
            stream = self.settings(identifier) if identifier is not None else None
            if stream is not None and stream["url"] != source.url:
                raise LiveError("direct_source", "La URL no corresponde al canal registrado.", 422)
            if stream is not None and source.platform == "youtube":
                source = DirectSource("youtube", identifier.split(":", 1)[1], source.url, stream.get("name"))
            if identifier is not None:
                current = pair[0].status(environment=False) if pair else self.idle
                readiness = self.connection(identifier, current)
                connection = readiness["connection"]
                if connection == "offline":
                    message = STATE_MESSAGES.get(readiness.get("broadcast_state"))
                    raise LiveError("direct_offline", message or "El canal está desconectado. Comprueba el directo antes de iniciar.")
                if connection == "checking" and current["state"] not in ACTIVE:
                    raise LiveError("direct_busy", "Espera a que termine la comprobación del canal.")
            options = AutoOptions.model_validate(stream.get("auto", {})) if stream is not None else None
            if pair and (self.saves[pair[0]] or pair[0].is_active() or pair[1].pending):
                raise LiveError("direct_busy", "Ya hay una captura o un guardado en curso en este canal.")
            entries = self.entries()
            active = [direct for _, (direct, _) in entries if direct.is_active()]
            if any(direct.session and (direct.session.source.platform, direct.session.source.channel)
                   == (source.platform, source.channel) for direct in active):
                raise LiveError("direct_duplicate", "Ya se está capturando este canal.")
            if len(active) >= self.max_active:
                raise LiveError("direct_limit", f"Límite de {self.max_active} capturas simultáneas alcanzado.", 409)
            buffered = [(key, entry) for key, entry in entries if entry[0].session is not None]
            if (not pair or pair[0].session is None) and len(buffered) >= self.max_active:
                self.primary[0].check_tools()
                if (self.primary[0].disk_free() or 0) <= MIN_FREE:
                    raise LiveError("direct_disk", "Se necesitan más de 5 GB libres para iniciar una captura.", 507)
                buffered.sort(key=lambda item: item[1][0].session.started)
                if not any(self.release(key, entry) for key, entry in buffered):
                    raise LiveError("direct_budget", "Espera a que terminen los guardados para liberar un búfer.", 409)

            direct, auto = pair or self.new_capture()
            try:
                if stream is not None and stream.get("quality") != body.quality:
                    self.db.put("streamers", {**stream, "quality": body.quality})
                status = direct.start(body, source) if source.platform == "youtube" else direct.start(body)
            except Exception:
                if pair is None:
                    auto.shutdown()
                raise
            if identifier is not None and options is not None:
                self.channel_probes.pop(identifier, None)
                self.channels[identifier] = (direct, auto)
                auto.apply_options(options)
            return status

    def stop(self, identifier: str | None, slot: int) -> dict:
        with self.lock:
            pair = self.resolve(identifier, slot)
            return pair[0].stop() if pair else {**self.idle, **self.environment()}

    def capture_status(self, identifier: str | None, slot: int) -> dict:
        with self.lock:
            pair = self.resolve(identifier, slot)
            capture = pair[0].status() if pair else {**self.idle, **self.environment()}
            return {**capture, **self.connection(identifier, capture)} if identifier is not None else capture

    def save(self, seconds: int, identifier: str | None, slot: int) -> tuple[dict, dict]:
        with self.lock:
            pair = self.resolve(identifier, slot)
            if not pair:
                raise LiveError("direct_empty", "Aún no hay segmentos completos en el búfer.")
            direct = pair[0]
            if self.saves[direct]:
                raise LiveError("direct_saving", "Ya se está guardando un fragmento.")
            self.saves[direct] += 1
        try:
            return direct.save(seconds)
        finally:
            with self.lock:
                del self.saves[direct]

    def auto_progress(self, stream: dict, pair: tuple[DirectCapture, AutoClip] | None) -> dict:
        if pair:
            return pair[1].progress()
        options = AutoOptions.model_validate(stream.get("auto", {}))
        return {**self.idle_auto, "options": options.model_dump(), "stage": "waiting" if options.enabled else "disabled"}

    def auto_status(self, identifier: str | None, slot: int) -> dict:
        with self.lock:
            pair = self.resolve(identifier, slot)
            progress = pair[1].progress() if pair else self.auto_progress(self.settings(identifier), None)
        return {**progress, **self.primary[1].resources()}

    def configure_auto(self, changes: AutoFields, identifier: str | None, slot: int) -> dict:
        with self.lock:
            pair = self.resolve(identifier, slot)
            stream = self.settings(identifier) if identifier is not None else None
            current = AutoOptions.model_validate(stream.get("auto", {})) if stream is not None else pair[1].options
            try:
                options = AutoOptions.model_validate({**current.model_dump(), **changes.model_dump(exclude_unset=True)})
            except ValidationError as exc:
                message = exc.errors(include_url=False)[0]["msg"].removeprefix("Value error, ")
                raise LiveError("auto_options", message, 422) from exc
            if options.enabled and not current.enabled:
                self.primary[1].check_options(options)
            if stream is not None:
                self.db.put("streamers", {**stream, "auto": options.model_dump()})
            if pair:
                pair[1].apply_options(options)
            return self.auto_status(identifier, slot)

    def environment(self) -> dict:
        direct = self.primary[0]
        return {"installed": direct.engine.available(), "free_bytes": direct.disk_free()}

    def overview(self) -> dict:
        with self.lock:
            environment = self.environment()
            directs = [pair[0] for _, pair in self.entries()]
            statuses = {direct: direct.status(environment=False) for direct in directs}
            rows = []
            for stream in sorted(self.db.list("streamers"), key=lambda item: item["id"]):
                pair = self.channels.get(stream["id"])
                capture = statuses[pair[0]] if pair else self.idle
                rows.append({
                    "quality": None, "seconds": 60, **stream, **self.connection(stream["id"], capture),
                    "capture": {**capture, **environment},
                    "autoclip": self.auto_progress(stream, pair),
                })
            buffered = sum(direct.session is not None for direct in directs)
            return {
                "channels": rows, **environment, "active": sum(direct.is_active() for direct in directs),
                "max_active": self.max_active, "bytes": sum(status["bytes"] for status in statuses.values()),
                "max_bytes": self.primary[0].max_bytes * max(self.max_active, buffered),
            }

    def shutdown(self) -> None:
        entries = self.entries()
        for _, (direct, _) in entries:
            direct.stop()
        for _, (_, auto) in entries:
            auto.shutdown()
        for _, (direct, _) in entries:
            direct.shutdown()
