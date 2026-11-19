"""Validated caption appearance, ASS rendering and clip-relative sidecars."""
from typing import Annotated, Literal
from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

from .captions import Identifier, Language

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Font = Literal["Arial", "Segoe UI", "Verdana", "Tahoma", "Impact"]
Alignment = Literal["left", "center", "right"]
CaptionLanguage = Literal["original"] | Language
CAPTION_RENDER_VERSION = 2


class CaptionStyle(BaseModel):
    preset: Literal["classic", "hormozi", "karaoke", "minimal"] = "classic"
    font: Font = "Arial"
    size: int = Field(default=52, ge=24, le=104)
    color: Color = "#ffffff"
    active_color: Color = "#b1f65a"
    outline: float = Field(default=3, ge=0, le=10, allow_inf_nan=False)
    outline_color: Color = "#000000"
    shadow: float = Field(default=1, ge=0, le=10, allow_inf_nan=False)
    background: Color = "#000000"
    background_opacity: int = Field(default=0, ge=0, le=100)
    align: Alignment = "center"
    position: int = Field(default=90, ge=0, le=100)
    words_per_line: int = Field(default=5, ge=1, le=12)


class CaptionPreferences(BaseModel):
    enabled: bool = True
    sidecars: bool = True
    language: CaptionLanguage = "original"
    style: CaptionStyle = Field(default_factory=CaptionStyle)


class CaptionOptions(CaptionPreferences):
    revision: Identifier | None = None


class GraphicLayer(BaseModel):
    id: Identifier
    kind: Literal["image", "text"]
    name: str = Field(default="Capa", min_length=1, max_length=80)
    asset_id: Identifier | None = None
    text: str = Field(default="", max_length=180)
    font: Font = "Arial"
    color: Color = "#ffffff"
    x: float = Field(default=50, ge=0, le=100, allow_inf_nan=False)
    y: float = Field(default=18, ge=0, le=100, allow_inf_nan=False)
    size: int = Field(default=24, ge=5, le=100)
    opacity: int = Field(default=100, ge=0, le=100)
    start: float = Field(default=0, ge=0, le=3600, allow_inf_nan=False)
    end: float | None = Field(default=None, gt=0, le=3600, allow_inf_nan=False)

    @model_validator(mode="after")
    def interval(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError("El final de la capa debe ser posterior al inicio.")
        return self


def color_ass(color: str, opacity=100) -> str:
    alpha = round(255 * (1 - opacity / 100))
    return f"&H{alpha:02X}{color[5:7]}{color[3:5]}{color[1:3]}".upper()


def literal_ass(text: str) -> str:
    # Neutraliza etiquetas y saltos ASS escritos por el usuario.
    return text.replace("\0", "").replace("\\", "\\\u200b").replace("{", "｛").replace("}", "｝").replace("\r", "").replace("\n", r"\N")


def timecode(value: float, *, precision: int, separator: str, padded: bool) -> str:
    factor = 10 ** precision
    ticks = max(0, round(value * factor))
    seconds, remainder = divmod(ticks, factor)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    hour = f"{hours:02d}" if padded else str(hours)
    return f"{hour}:{minutes:02d}:{seconds:02d}{separator}{remainder:0{precision}d}"


def dialogue(start: float, end: float, text: str, *, layer=1, style="Captions") -> str | None:
    if round(end * 100) <= round(start * 100):
        return None
    first = timecode(start, precision=2, separator=".", padded=False)
    last = timecode(end, precision=2, separator=".", padded=False)
    return f"Dialogue: {layer},{first},{last},{style},,0,0,0,,{text}"


def wrap_words(tokens: list[str], limit: int) -> str:
    return r"\N".join(" ".join(tokens[i:i + limit]) for i in range(0, len(tokens), limit))


def caption_position(style: CaptionStyle, dimensions, safe_top: int, safe_bottom: int) -> str:
    width, height = dimensions
    factor = min(width, height) / 1080
    font_size = max(12, round(style.size * factor))
    # Reserve two lines of text including outline and shadow inside the safe area.
    decoration = max(10, style.outline + style.shadow + (5 if style.background_opacity else 0))
    pad = min(height * (100 - safe_top - safe_bottom) / 200, font_size * 1.22 + decoration * factor)
    top = height * safe_top / 100 + pad
    bottom = height * (100 - safe_bottom) / 100 - pad
    x = round(width * {"left": .08, "center": .5, "right": .92}[style.align])
    y = round(top + (bottom - top) * style.position / 100)
    anchor = {"left": 4, "center": 5, "right": 6}[style.align]
    # Coordinates describe the composed canvas, including bars or a blurred background.
    safe_y0 = (height * safe_top + 99) // 100
    safe_y1 = height * (100 - safe_bottom) // 100
    return f"{{\\an{anchor}\\pos({x},{y})\\clip(0,{safe_y0},{width},{safe_y1})}}"


@dataclass
class CaptionPage:
    start: float
    end: float
    box: str | None
    frames: list[tuple[float, float, str]]


def caption_pages(cues, style: CaptionStyle):
    active = "{\\1c&H" + color_ass(style.active_color)[4:] + "&}"
    reset = "{\\1c&H" + color_ass(style.color)[4:] + "&}"
    animated = style.preset in {"hormozi", "karaoke"}
    words_per_page = style.words_per_line * 2
    for cue in cues:
        words = cue["words"]
        for index in range(0, len(words), words_per_page):
            page = words[index:index + words_per_page]
            begin = cue["start"] if index == 0 else page[0]["start"]
            upcoming = index + words_per_page
            finish = words[upcoming]["start"] if upcoming < len(words) else cue["end"]
            cuts = [begin, finish]
            if animated:
                cuts = sorted(set(cuts + [t for word in page for t in (word["start"], word["end"]) if begin < t < finish]))
            plain = [literal_ass(word["text"]) for word in page]
            box = wrap_words(plain, style.words_per_line) if style.background_opacity else None
            frames = []
            for start, end in zip(cuts, cuts[1:]):
                start_cs, end_cs = round(start * 100), round(end * 100)
                if start_cs >= end_cs:
                    continue
                midpoint = (start + end) / 2
                active_word = next((word for word in reversed(page) if word["start"] <= midpoint < word["end"]), None) if animated else None
                tokens = [active + text + reset if word is active_word else text for word, text in zip(page, plain)]
                frames.append((start_cs / 100, end_cs / 100, wrap_words(tokens, style.words_per_line)))
            if frames:
                yield CaptionPage(frames[0][0], frames[-1][1], box, frames)


def caption_rows(start, end, text, box, position) -> list[str]:
    return [row for row in (
        dialogue(start, end, position + box, layer=0, style="CaptionBox") if box else None,
        dialogue(start, end, position + text),
    ) if row]


def caption_events(cues, style: CaptionStyle, dimensions, safe_top: int, safe_bottom: int) -> list[str]:
    position = caption_position(style, dimensions, safe_top, safe_bottom)
    events = []
    for page in caption_pages(cues, style):
        if page.box:
            box = dialogue(page.start, page.end, position + page.box, layer=0, style="CaptionBox")
            if box:
                events.append(box)
        for start, end, text in page.frames:
            events.extend(caption_rows(start, end, text, None, position))
    return events


def ass_header(style: CaptionStyle, dimensions) -> str:
    width, height = dimensions
    factor = min(width, height) / 1080
    size = max(12, round(style.size * factor))
    border = color_ass(style.outline_color)
    margin = round(width * .08)
    bold = -1 if style.preset in {"classic", "hormozi"} else 0
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Captions,{style.font},{size},{color_ass(style.color)},{color_ass(style.active_color)},{border},&H66000000,"
        f"{bold},0,0,0,100,100,0,0,1,{style.outline * factor:.3f},"
        f"{style.shadow * factor:.3f},5,{margin},{margin},0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if style.background_opacity:
        box = color_ass(style.background, style.background_opacity)
        header.insert(-3, f"Style: CaptionBox,{style.font},{size},&HFF000000,&HFF000000,{box},&HFF000000,"
                      f"{bold},0,0,0,100,100,0,0,3,{max(2, 5 * factor):.3f},0,5,{margin},{margin},0,1")
    return "\n".join(header) + "\n"


def ass_script(cues, style: CaptionStyle, dimensions, safe_top: int, safe_bottom: int) -> str:
    events = caption_events(cues, style, dimensions, safe_top, safe_bottom)
    return ass_header(style, dimensions) + "".join(row + "\n" for row in events)


def subtitle_sidecar(cues, kind: Literal["srt", "vtt"]) -> str:
    output = ["WEBVTT", ""] if kind == "vtt" else []
    separator = "." if kind == "vtt" else ","
    for index, cue in enumerate(cues, 1):
        start = timecode(cue["start"], precision=3, separator=separator, padded=True)
        end = timecode(cue["end"], precision=3, separator=separator, padded=True)
        content = cue["text"].strip()
        if kind == "vtt":
            content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        output.extend([str(index), f"{start} --> {end}", content, ""])
    return "\n".join(output) + "\n"


def graphic_ass(layer: GraphicLayer, dimensions, end: float) -> str:
    width, height = dimensions
    font_size = max(8, round(min(width, height) * layer.size / 1000))
    x = round(width * layer.x / 100)
    y = round(height * layer.y / 100)
    appearance = CaptionStyle(font=layer.font, color=layer.color, size=24)
    header = ass_script([], appearance, dimensions, 0, 0).splitlines()
    foreground = color_ass(layer.color, layer.opacity)
    outline = color_ass("#000000", layer.opacity * .8)
    shadow = color_ass("#000000", layer.opacity * .45)
    style = f"Style: Captions,{layer.font},{font_size},{foreground},{foreground},{outline},{shadow},-1,0,0,0,100,100,0,0,1,1.5,1,5,10,10,0,1"
    header = [style if line.startswith("Style: Captions,") else line for line in header]
    text = f"{{\\an5\\pos({x},{y})}}" + literal_ass(layer.text)
    row = dialogue(layer.start, end, text)
    return "\n".join(header + ([row] if row else [])) + "\n"
