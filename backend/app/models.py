from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from .composition import CaptionOptions, GraphicLayer


class Ratio(str, Enum):
    portrait = "9:16"
    square = "1:1"
    feed = "4:5"
    landscape = "16:9"


class RenderOptions(BaseModel):
    ratio: Ratio = Ratio.portrait
    resolution: int = Field(default=1080)
    fit: Literal["contain", "cover", "blur"] = "contain"
    blur_strength: int = Field(default=55, ge=0, le=100)
    platform: str = Field(default="tiktok", pattern="^(tiktok|reels|shorts|facebook|custom)$")
    safe_top: int = Field(default=10, ge=0, le=35)
    safe_bottom: int = Field(default=22, ge=0, le=40)
    focus_x: int = Field(default=50, ge=0, le=100)
    focus_y: int = Field(default=50, ge=0, le=100)
    captions: CaptionOptions | None = None
    graphics: list[GraphicLayer] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def check_resolution(self):
        if self.resolution not in (480, 720, 1080):
            raise ValueError("La resolución debe ser 480, 720 o 1080.")
        if len({layer.id for layer in self.graphics}) != len(self.graphics):
            raise ValueError("Hay capas gráficas repetidas.")
        return self

    def dimensions(self) -> tuple[int, int]:
        a, b = map(int, self.ratio.value.split(":"))
        if a > b:
            return round(self.resolution * a / b / 2) * 2, self.resolution
        return self.resolution, round(self.resolution * b / a / 2) * 2


class ClipRequest(RenderOptions):
    video_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    title: str = Field(default="Mi clip", min_length=1, max_length=100)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_clip(self):
        duration = Decimal(str(self.end)) - Decimal(str(self.start))
        if duration < Decimal("0.1"):
            raise ValueError("El clip debe durar al menos 0,1 segundos.")
        if duration > 3600:
            raise ValueError("Cada clip puede durar como máximo una hora.")
        return self


class AnalysisRequest(BaseModel):
    model: Literal["tiny", "base", "small"] = "tiny"
    language: str = Field(default="auto", pattern="^(auto|es|en|pt|fr|de|it|ja|zh|ru|ar|hi|ko|nl|pl|tr|uk)$")
    min_duration: float = Field(default=15, ge=1, le=180, allow_inf_nan=False)
    max_duration: float = Field(default=45, ge=1, le=180, allow_inf_nan=False)
    max_clips: int = Field(default=8, ge=1, le=20)
    reuse_transcript: bool = True
    cpu_threads: Literal[2, 4, 6] = 4

    @model_validator(mode="after")
    def check_interval(self):
        if self.max_duration < self.min_duration:
            raise ValueError("La duración máxima no puede ser menor que la mínima.")
        return self


class BatchRequest(RenderOptions):
    analysis_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    moment_ids: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check_unique(self):
        if len(set(self.moment_ids)) != len(self.moment_ids):
            raise ValueError("La selección contiene momentos repetidos.")
        return self
