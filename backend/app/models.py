from enum import Enum
from pydantic import BaseModel, Field, model_validator


class Ratio(str, Enum):
    portrait = "9:16"
    square = "1:1"
    feed = "4:5"
    landscape = "16:9"


class ClipRequest(BaseModel):
    video_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    title: str = Field(default="Mi clip", min_length=1, max_length=100)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    ratio: Ratio = Ratio.portrait
    resolution: int = Field(default=1080)
    fit: str = Field(default="contain", pattern="^(contain|cover)$")
    platform: str = Field(default="tiktok", pattern="^(tiktok|reels|shorts|custom)$")
    safe_top: int = Field(default=10, ge=0, le=35)
    safe_bottom: int = Field(default=22, ge=0, le=40)
    focus_x: int = Field(default=50, ge=0, le=100)
    focus_y: int = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def check_clip(self):
        if self.resolution not in (480, 720, 1080):
            raise ValueError("La resolución debe ser 480, 720 o 1080.")
        if self.end - self.start < 0.1:
            raise ValueError("El clip debe durar al menos 0,1 segundos.")
        if self.end - self.start > 3600:
            raise ValueError("Cada clip puede durar como máximo una hora.")
        return self

    def dimensions(self) -> tuple[int, int]:
        a, b = map(int, self.ratio.value.split(":"))
        if a > b:
            return round(self.resolution * a / b / 2) * 2, self.resolution
        return self.resolution, round(self.resolution * b / a / 2) * 2
