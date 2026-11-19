"""Encuadre dividido: dos recortes de origen y dos paneles sin relleno."""
from dataclasses import dataclass
from math import ceil, floor

from pydantic import BaseModel, Field, model_validator


SPLIT_RENDER_VERSION = 4
EMPTY_GAMEPLAY = "La región de gameplay queda dentro de la cámara. Amplíala o muévela en Original."
EPSILON = 1e-7


class SourceRect(BaseModel):
    x: float = Field(default=0, ge=0, le=1)
    y: float = Field(default=0, ge=0, le=1)
    width: float = Field(default=1, ge=.02, le=1)
    height: float = Field(default=1, ge=.02, le=1)

    @model_validator(mode="after")
    def inside_source(self):
        if self.x + self.width > 1 + 1e-9 or self.y + self.height > 1 + 1e-9:
            raise ValueError("La región debe quedar dentro del vídeo original.")
        return self


class SplitRegion(BaseModel):
    rect: SourceRect = Field(default_factory=SourceRect)
    zoom: int = Field(default=100, ge=100, le=300)
    pan_x: int = Field(default=0, ge=-100, le=100)
    pan_y: int = Field(default=0, ge=-100, le=100)


def default_camera() -> SplitRegion:
    return SplitRegion(rect=SourceRect(x=.02, y=.02, width=.26, height=.26))


class SplitLayout(BaseModel):
    camera_share: float = Field(default=25, ge=10, le=90)
    inverted: bool = False
    camera: SplitRegion = Field(default_factory=default_camera)
    gameplay: SplitRegion = Field(default_factory=SplitRegion)

    def camera_height(self, height: int) -> int:
        return 2 * floor(height * self.camera_share / 200 + .5)

    def seam(self, height: int) -> int:
        camera = self.camera_height(height)
        return height - camera if self.inverted else camera


class SourceGeometry(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    display_width: int = Field(gt=0)


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    def overlap(self, other: "PixelRect") -> int:
        width = max(0, min(self.right, other.right) - max(self.x, other.x))
        height = max(0, min(self.bottom, other.bottom) - max(self.y, other.y))
        return width * height


@dataclass(frozen=True)
class PanelGeometry:
    crop: PixelRect
    width: int
    height: int
    scaled_width: int
    scaled_height: int

    @property
    def trim_x(self) -> int:
        return (self.scaled_width - self.width) // 2

    @property
    def trim_y(self) -> int:
        return (self.scaled_height - self.height) // 2


def inward_axis(start: float, end: float, length: int) -> tuple[int, int]:
    # Keep chroma samples inside the selection where two aligned pixels fit.
    for step in (2, 1):
        left = max(0, step * ceil((start - EPSILON) / step))
        right = min(length, step * floor((end + EPSILON) / step))
        if right > left:
            return left, right - left
    return min(length - 1, floor((start + end) / 2)), 1


def pixel_bounds(rect: SourceRect, source: SourceGeometry, *, outward: bool = False) -> PixelRect:
    x, right = rect.x * source.width, (rect.x + rect.width) * source.width
    y, bottom = rect.y * source.height, (rect.y + rect.height) * source.height
    if outward:
        left = 2 * floor((x + EPSILON) / 2)
        top = 2 * floor((y + EPSILON) / 2)
        return PixelRect(left, top, min(source.width, 2 * ceil((right - EPSILON) / 2)) - left,
                         min(source.height, 2 * ceil((bottom - EPSILON) / 2)) - top)
    left, width = inward_axis(x, right, source.width)
    top, height = inward_axis(y, bottom, source.height)
    return PixelRect(left, top, width, height)


def crop_length(value: float, limit: int) -> int:
    return min(limit, max(2, 2 * floor((value + EPSILON) / 2)))


def aligned_offset(value: float, limit: int) -> int:
    return max(0, min(limit, 2 * floor(value / 2 + .5)))


def preferred_crop(region: SplitRegion, bounds: PixelRect, aspect: float) -> PixelRect:
    zoom = 100 / region.zoom
    w = crop_length(min(bounds.width, bounds.height * aspect) * zoom, bounds.width)
    h = crop_length(min(bounds.height, bounds.width / aspect) * zoom, bounds.height)
    x = bounds.x + aligned_offset((bounds.width - w) * (region.pan_x + 100) / 200, bounds.width - w)
    y = bounds.y + aligned_offset((bounds.height - h) * (region.pan_y + 100) / 200, bounds.height - h)
    return PixelRect(x, y, w, h)


def exclude_camera(desired: PixelRect, bounds: PixelRect, camera: PixelRect) -> PixelRect | None:
    if not desired.overlap(camera):
        return desired
    # Any rectangular crop that avoids the camera lies in at least one of these strips.
    strips = (
        PixelRect(bounds.x, bounds.y, camera.x - bounds.x, bounds.height),
        PixelRect(camera.right, bounds.y, bounds.right - camera.right, bounds.height),
        PixelRect(bounds.x, bounds.y, bounds.width, camera.y - bounds.y),
        PixelRect(bounds.x, camera.bottom, bounds.width, bounds.bottom - camera.bottom),
    )
    best, best_score = None, (0, 0, 0)
    for strip in strips:
        if min(strip.width, strip.height) < 1:
            continue
        scale = min(1, strip.width / desired.width, strip.height / desired.height)
        w = crop_length(desired.width * scale, min(strip.width, desired.width))
        h = crop_length(desired.height * scale, min(strip.height, desired.height))
        center_x = desired.x + (desired.width - w) / 2
        center_y = desired.y + (desired.height - h) / 2
        x = strip.x + aligned_offset(center_x - strip.x, strip.width - w)
        y = strip.y + aligned_offset(center_y - strip.y, strip.height - h)
        candidate = PixelRect(x, y, w, h)
        dx, dy = 2 * (x - center_x), 2 * (y - center_y)
        score = candidate.area, candidate.overlap(desired), -(dx * dx + dy * dy)
        if score > best_score:
            best, best_score = candidate, score
    return best


def panel_geometry(crop: PixelRect, width: int, height: int, pixel_aspect: float) -> PanelGeometry:
    aspect = crop.width * pixel_aspect / crop.height
    return PanelGeometry(crop, width, height, max(width, 2 * ceil((height * aspect - EPSILON) / 2)),
                         max(height, 2 * ceil((width / aspect - EPSILON) / 2)))


def split_geometry(layout: SplitLayout, dimensions: tuple[int, int], source: SourceGeometry
                   ) -> tuple[PanelGeometry, PanelGeometry] | None:
    """Use the same native-pixel geometry as splitFramingGeometry.ts."""
    width, height = dimensions
    camera_height = layout.camera_height(height)
    gameplay_height = height - camera_height
    pixel_aspect = source.display_width / source.width
    camera = preferred_crop(layout.camera, pixel_bounds(layout.camera.rect, source), width / camera_height / pixel_aspect)
    gameplay_bounds = pixel_bounds(layout.gameplay.rect, source)
    desired = preferred_crop(layout.gameplay, gameplay_bounds, width / gameplay_height / pixel_aspect)
    gameplay = exclude_camera(desired, gameplay_bounds, pixel_bounds(layout.camera.rect, source, outward=True))
    if gameplay is None:
        return None
    return (panel_geometry(camera, width, camera_height, pixel_aspect),
            panel_geometry(gameplay, width, gameplay_height, pixel_aspect))


def split_graph(layout: SplitLayout, geometry: tuple[PanelGeometry, PanelGeometry]) -> str:
    def filters(label: str, panel: PanelGeometry) -> str:
        region = panel.crop
        return (f"[{label}source]crop={region.width}:{region.height}:{region.x}:{region.y}:exact=1,"
                f"scale={panel.scaled_width}:{panel.scaled_height},setsar=1,"
                f"crop={panel.width}:{panel.height}:{panel.trim_x}:{panel.trim_y}:exact=1[{label}]")

    camera, gameplay = geometry
    order = "[gameplay][camera]" if layout.inverted else "[camera][gameplay]"
    return ";".join(("[0:V:0]split[camerasource][gameplaysource]", filters("camera", camera),
                     filters("gameplay", gameplay), f"{order}vstack=inputs=2[video]"))
