"""Rasteriza las páginas de subtítulos con la misma composición y libass que el MP4."""
from base64 import b64encode
from functools import lru_cache
import logging
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock

from pydantic import Field, model_validator

from ..captions import CaptionSegment, clip_captions
from ..composition import CaptionLanguage, CaptionStyle, GraphicLayer, ass_header, caption_pages, caption_position, caption_rows, graphic_ass
from ..models import RenderOptions
from .media import CREATE_NO_WINDOW, MediaError, MediaService

logger = logging.getLogger("clipzone.captions")


class CaptionLayerRequest(RenderOptions):
    segment: CaptionSegment
    style: CaptionStyle
    language: CaptionLanguage = "original"
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    time: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def interval(self):
        if not 0 <= self.time < self.end - self.start:
            raise ValueError("El tiempo de previsualización debe estar dentro del clip.")
        return self


class HookLayerRequest(RenderOptions):
    layer: GraphicLayer


class CaptionLayers:
    def __init__(self, media: MediaService):
        self.media = media
        self.lock = Lock()
        self._render_cached = lru_cache(maxsize=32)(self._render)

    def page(self, body: CaptionLayerRequest) -> dict:
        cues = clip_captions([body.segment], body.start, body.end, body.language)
        pages = caption_pages(cues, body.style)
        selected = next((page for page in pages if page.start <= body.time < page.end), None)
        if selected is None:
            # Los límites ASS se guardan en centésimas. No tapes una página próxima
            # con una entrada vacía que abarque todo el segmento.
            start = max(0, body.segment.start - body.start)
            end = min(body.end, body.segment.end) - body.start
            rounded_start = round(start * 100) / 100
            return {"start": min(start, body.time), "end": rounded_start if body.time < rounded_start else max(end, body.time),
                    "frames": [], "images": []}
        dimensions = body.dimensions()
        position = caption_position(body.style, dimensions, body.safe_top, body.safe_bottom, body.caption_seam())
        indexes = {}
        frames = []
        for start, end, text in selected.frames:
            index = indexes.setdefault(text, len(indexes))
            frames.append({"start": start, "end": end, "image": index})
        rows = []
        for text, index in indexes.items():
            rows.extend(caption_rows(index, index + 1, text, selected.box, position))
        document = ass_header(body.style, dimensions) + "\n".join(rows) + "\n"
        with self.lock:
            images = self._render_cached(dimensions, document, len(indexes))
        return {"start": selected.start, "end": selected.end, "frames": frames, "images": images}

    def hook(self, body: HookLayerRequest) -> str:
        layer = body.layer.model_copy(update={"start": 0})
        dimensions = body.dimensions()
        document = graphic_ass(layer, dimensions, 1, body.caption_seam())
        with self.lock:
            return self._render_cached(dimensions, document, 1)[0]

    def _render(self, dimensions, document: str, count: int) -> tuple[str, ...]:
        width, height = dimensions
        matte = f"s={width}x{height}:r=1,format=yuv444p"
        # Two mattes recover the true coverage of overlapping glyphs, outlines,
        # shadows and boxes. PNG needs straight RGB because the browser applies alpha.
        divide = ":".join(f"c{i}='if(y,min(255,255*x/y),0)'" for i in range(3))
        graph = (
            "[0:v]ass=captions.ass,format=gbrp,split[color][black];"
            "[1:v]ass=captions.ass,format=gbrp[white];"
            "[white][black]blend=all_mode=subtract,negate,split[denominator][coverage];"
            f"[color][denominator]lut2={divide}[rgb];"
            "[coverage]format=gray[alpha];[rgb][alpha]alphamerge,format=rgba[caption]"
        )
        with TemporaryDirectory(prefix="clipzone-captions-") as workspace:
            directory = Path(workspace)
            (directory / "captions.ass").write_text(document, encoding="utf-8")
            command = [self.media.require("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin",
                       "-f", "lavfi", "-i", f"color=black:{matte}", "-f", "lavfi", "-i", f"color=white:{matte}",
                       "-filter_complex_threads", "1", "-filter_complex", graph, "-map", "[caption]",
                       "-frames:v", str(count), "-threads", "1", "-compression_level", "4", "caption-%02d.png"]
            try:
                result = subprocess.run(command, capture_output=True, cwd=directory, timeout=18, creationflags=CREATE_NO_WINDOW)
                if result.returncode:
                    logger.warning("No se pudo dibujar la capa de subtítulos: %s", result.stderr.decode("utf-8", errors="replace")[-1000:])
                    raise MediaError("FFmpeg no pudo dibujar los subtítulos en directo.")
                return tuple(b64encode((directory / f"caption-{index:02d}.png").read_bytes()).decode("ascii")
                             for index in range(1, count + 1))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise MediaError("No se pudo generar la capa de subtítulos en directo.") from exc
