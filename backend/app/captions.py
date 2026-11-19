"""Editable source-relative captions. Whisper analyses remain immutable."""
from bisect import bisect_left
from typing import Annotated
from uuid import uuid4
from threading import Lock

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
import math
from .translation import argos_python, import_subtitle_text, translate_local

Language = Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")]
Identifier = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Text = Annotated[str, Field(max_length=600)]


class TimedWord(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=200)]
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def interval(self):
        if self.end <= self.start:
            raise ValueError("El final de una palabra debe ser posterior a su inicio.")
        return self


class CaptionSegment(TimedWord):
    text: Text
    id: Identifier
    words: list[TimedWord] = Field(default_factory=list, max_length=60)
    translations: dict[Language, Text] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def minimum_length(self):
        if self.end - self.start < .01:
            raise ValueError("Cada segmento debe durar al menos 0,01 s.")
        return self


class SaveCaptions(BaseModel):
    revision: Identifier | None = None
    segments: list[CaptionSegment] = Field(max_length=15000)


class GenerateCaptions(BaseModel):
    analysis_id: Identifier
    revision: Identifier | None = None


class ImportTranslation(BaseModel):
    revision: Identifier
    language: Language
    content: str = Field(min_length=1, max_length=1024 * 1024)


class LocalTranslation(BaseModel):
    revision: Identifier
    language: Language
    segment_ids: list[Identifier] = Field(min_length=1, max_length=80)


def group_words(rows: list[dict], duration: float) -> list[CaptionSegment]:
    groups: list[list[TimedWord]] = []
    pending: list[TimedWord] = []
    for item in rows:
        start, end = item.get("start"), item.get("end")
        text = str(item.get("text", "")).strip()
        if not text or not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (start, end)):
            continue
        start, end = max(0, start), min(duration, end)
        if end - start < .011 or len(text) > 200:
            continue
        if pending and (len(pending) >= 7 or end - pending[0].start > 3.5 or start - pending[-1].end > .65):
            groups.append(pending)
            pending = []
        pending.append(TimedWord(text=text, start=start, end=end))
        if text.endswith((".", "?", "!", "…", "。", "？", "！")):
            groups.append(pending)
            pending = []
    if pending:
        groups.append(pending)

    segments = []
    for group in groups[:15000]:
        start = max(segments[-1].end if segments else 0, group[0].start)
        end = min(duration, group[-1].end)
        if end - start < .01:
            continue
        segments.append(CaptionSegment(id=uuid4().hex, start=start, end=end,
                                       text=" ".join(word.text for word in group)[:600], words=group))
    return segments


def selected_text(segment: CaptionSegment, language: str) -> str:
    return segment.text if language == "original" else segment.translations.get(language, "")


def word_timing(segment: CaptionSegment, text: str) -> list[TimedWord]:
    tokens = text.split()
    if not tokens:
        return []
    if tokens == [word.text for word in segment.words] and all(
        segment.start <= word.start < word.end <= segment.end for word in segment.words
    ):
        return segment.words
    step = (segment.end - segment.start) / len(tokens)
    # Edición de texto y traducción conservan el tiempo de la frase.
    return [TimedWord(text=token[:200], start=segment.start + i * step,
                      end=segment.start + (i + 1) * step) for i, token in enumerate(tokens)]


def clip_captions(segments: list[CaptionSegment], start: float, end: float, language: str) -> list[dict]:
    if not segments:
        return []
    result = []
    for segment in segments[bisect_left([item.end for item in segments], start):]:
        if segment.start >= end:
            break
        text = selected_text(segment, language).strip()
        if not text or segment.end <= start:
            continue
        words = []
        for word in word_timing(segment, text):
            from_, to = max(word.start, start), min(word.end, end)
            if to > from_:
                words.append({"text": word.text, "start": from_ - start, "end": to - start})
        result.append({
            "start": max(segment.start, start) - start, "end": min(segment.end, end) - start,
            "text": " ".join(word["text"] for word in words) if segment.start < start or segment.end > end else text,
            "words": words,
        })
    return [cue for cue in result if cue["text"]]


def register_captions(app, find_video):
    router = APIRouter(prefix="/api/videos", tags=["Subtítulos"])
    translation_lock = Lock()

    def read_track(video_id):
        return app.state.db.get("caption_tracks", video_id) or {
            "id": video_id, "revision": None, "audio_language": None, "analysis_id": None, "segments": [],
        }

    def commit(video_id, expected_revision, segments, *, source=None):
        with app.state.export_lock:
            video = find_video(video_id)
            previous = read_track(video_id)
            if previous["revision"] != expected_revision:
                raise HTTPException(409, "La pista cambió. Vuelve a cargarla antes de guardar.")
            ordered = sorted(segments, key=lambda item: item.start)
            if len({item.id for item in ordered}) != len(ordered):
                raise HTTPException(422, "Hay segmentos repetidos.")
            if any(item.end > video["duration"] + .001 for item in ordered):
                raise HTTPException(422, "Un subtítulo queda fuera del vídeo.")
            if any(a.end > b.start + .000001 for a, b in zip(ordered, ordered[1:])):
                raise HTTPException(422, "Hay subtítulos solapados. Ajusta el final o el inicio de las frases.")
            entry = {**previous, **(source or {}), "revision": uuid4().hex,
                     "segments": [segment.model_dump() for segment in ordered]}
            return app.state.db.put("caption_tracks", entry)

    @router.get("/{video_id}/captions")
    def get_captions(video_id: str):
        find_video(video_id)
        return read_track(video_id)

    @router.post("/{video_id}/captions")
    def save_captions(video_id: str, body: SaveCaptions):
        return commit(video_id, body.revision, body.segments)

    @router.post("/{video_id}/captions/generate")
    def generate_captions(video_id: str, body: GenerateCaptions):
        video = find_video(video_id)
        analysis = app.state.db.get("analyses", body.analysis_id)
        if not analysis or analysis.get("video_id") != video_id or analysis.get("status") != "completed":
            raise HTTPException(404, "No se encontró un análisis completo para este vídeo.")
        transcript = analysis["result"]["transcript"]
        return commit(video_id, body.revision, group_words(transcript["words"], video["duration"]), source={
            "audio_language": transcript.get("language") if transcript.get("language") != "auto" else None,
            "analysis_id": body.analysis_id,
        })

    def translation_track(video_id, revision):
        find_video(video_id)
        existing = read_track(video_id)
        if existing["revision"] != revision:
            raise HTTPException(409, "Guarda los cambios y vuelve a cargar la pista antes de traducir.")
        if not existing["segments"]:
            raise HTTPException(422, "La pista no contiene segmentos.")
        return existing, [CaptionSegment.model_validate(row) for row in existing["segments"]]

    @router.get("/{video_id}/captions/translation")
    def translation_status(video_id: str):
        find_video(video_id)
        return {"local_available": argos_python() is not None}

    @router.post("/{video_id}/captions/translation/import")
    def import_translation(video_id: str, body: ImportTranslation):
        _, segments = translation_track(video_id, body.revision)
        texts = import_subtitle_text(body.content)
        if len(texts) != len(segments):
            raise HTTPException(422, f"El archivo tiene {len(texts)} segmentos. La pista de origen tiene {len(segments)}.")
        for segment, text in zip(segments, texts):
            segment.translations[body.language] = text
        return commit(video_id, body.revision, segments)

    @router.post("/{video_id}/captions/translation/local")
    def local_translation(video_id: str, body: LocalTranslation):
        existing, segments = translation_track(video_id, body.revision)
        source = existing.get("audio_language")
        if not source or source == body.language:
            raise HTTPException(422, "Genera la pista desde Whisper y elige un idioma distinto del audio.")
        lookup = {segment.id: segment for segment in segments}
        if len(set(body.segment_ids)) != len(body.segment_ids) or not all(item in lookup for item in body.segment_ids):
            raise HTTPException(422, "La selección de segmentos no es válida.")
        selected = [lookup[item] for item in body.segment_ids]
        if not translation_lock.acquire(blocking=False):
            raise HTTPException(409, "Ya hay una traducción local en curso.")
        try:
            texts = translate_local(source, body.language, [segment.text for segment in selected])
            for segment, text in zip(selected, texts):
                segment.translations[body.language] = text
            return commit(video_id, body.revision, segments)
        finally:
            translation_lock.release()

    app.include_router(router)
