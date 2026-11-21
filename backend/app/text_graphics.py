"""Rasteriza una capa de texto estática para el navegador y para FFmpeg."""
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from math import ceil
import os
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from .composition import GraphicLayer, GraphicTextStyle
from .emoji_assets import GRAPHEMES, emoji_image, emoji_key, has_emoji

FONT_DIR = Path(__file__).with_name("fonts")
SYSTEM_FONTS = {
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf", None, None),
    "Impact": ("impact.ttf", None, None, None),
}


@dataclass(frozen=True)
class TextTile:
    png: bytes
    width: int
    height: int


def open_font(name: str, size: int, bold: bool, italic: bool):
    if name in SYSTEM_FONTS:
        directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        variants = SYSTEM_FONTS[name]
        # Prefiere el peso real si el sistema no incluye la variante cursiva.
        for index in dict.fromkeys([int(bold) + 2 * int(italic), int(bold), 2 * int(italic), 0]):
            filename = variants[index]
            if filename and (directory / filename).is_file():
                return ImageFont.truetype(directory / filename, size), bold and not index % 2, italic and index < 2
        name = "Anton" if name == "Impact" else "Roboto"
    directory = FONT_DIR / name.lower()
    if name == "Anton":
        return ImageFont.truetype(directory / "Anton-Regular.ttf", size), bold, italic
    if name == "Poppins":
        variant = "BoldItalic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular"
        return ImageFont.truetype(directory / f"Poppins-{variant}.ttf", size), False, False
    axes = "wdth,wght" if name == "Roboto" else "wght"
    variant = "-Italic" if italic else ""
    font = ImageFont.truetype(directory / f"{name}{variant}[{axes}].ttf", size)
    if bold:
        font.set_variation_by_axes([
            700 if axis["name"] == b"Weight" else axis["default"] for axis in font.get_variation_axes()
        ])
    return font, False, False


def wrap_lines(text: str, measure: Callable[[str], float], limit: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if measure(candidate) <= limit:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            for letter in GRAPHEMES.findall(word):
                if line and measure(line + letter) > limit:
                    lines.append(line)
                    line = ""
                line += letter
        lines.append(line)
    return lines


def line_runs(line: str):
    plain = []
    for grapheme in GRAPHEMES.findall(line):
        emoji = emoji_key(grapheme)
        if emoji:
            if plain:
                yield "".join(plain), None
                plain.clear()
            yield "", emoji
        else:
            plain.append(grapheme)
    if plain:
        yield "".join(plain), None


def paint(target: Image.Image, mask: Image.Image, color: str, opacity: float) -> None:
    if opacity:
        ink = Image.new("RGBA", target.size, color)
        ink.putalpha(mask if opacity == 100 else mask.point([round(i * opacity / 100) for i in range(256)]))
        target.alpha_composite(ink)


def save_tile(image: Image.Image) -> TextTile:
    output = BytesIO()
    image.save(output, "PNG", compress_level=3)
    return TextTile(output.getvalue(), image.width, image.height)


@lru_cache(maxsize=48)
def rasterize(text: str, family: str, size: int, color: str, opacity: int,
              style: GraphicTextStyle, dimensions: tuple[int, int]) -> TextTile:
    text = text.replace("\0", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return save_tile(Image.new("RGBA", (2, 2)))
    width, height = dimensions
    factor = min(dimensions) / 1080
    size = max(3, round(size * factor))
    font, synthetic_bold, synthetic_italic = open_font(family, size, style.bold, style.italic)
    padding = round(style.padding * factor)
    extra = max(1, round(size * .025)) if synthetic_bold else 0
    stroke = round(style.outline_width * factor)
    offset = (round(style.shadow_x * factor), round(style.shadow_y * factor))
    blur = style.shadow_blur * factor
    bleed = 2 + extra + stroke
    if style.shadow_opacity and opacity:
        bleed += ceil(blur * 3) + max(map(abs, offset))

    ascent, descent = font.getmetrics()
    leading = ascent + descent + round(size * .12)
    max_lines = max(1, height // leading)
    limit = max(1, round(width * .9) - padding * 2)
    emoji_size = round(size * 1.08)
    emoji_top = -round(emoji_size * .88)
    emoji_advance = emoji_size + max(1, round(size * .06))

    @lru_cache(maxsize=256)
    def layout(line: str):
        runs, advance, bounds = [], 0., (0, 0, 0, 0)
        for fragment, emoji in line_runs(line):
            x = round(advance)
            runs.append((x, fragment, emoji))
            left, top, right, bottom = ((0, emoji_top, emoji_size, emoji_top + emoji_size) if emoji
                                        else font.getbbox(fragment, anchor="ls"))
            bounds = (min(bounds[0], left + x), min(bounds[1], top),
                      max(bounds[2], right + x), max(bounds[3], bottom))
            advance += emoji_advance if emoji else font.getlength(fragment)
        if len(runs) == 1 and not runs[0][2]:
            bounds = font.getbbox(line, anchor="ls")
        return advance, bounds, runs

    lines = wrap_lines(text, lambda line: layout(line)[0], limit)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        clusters = GRAPHEMES.findall(lines[-1])
        while clusters and layout("".join(clusters) + "…")[0] > limit:
            clusters.pop()
        lines[-1] = "".join(clusters) + "…"

    layouts = [layout(line) for line in lines]
    bounds = [box for _, box, _ in layouts]
    widths = [max(ceil(advance), box[2]) - min(box[0], 0) for advance, box, _ in layouts]
    content_width = max(1, max(widths))
    underline_y = max(1, round(size * .12))
    underline_width = max(1, round(size * .06))
    top = min(i * leading + box[1] for i, box in enumerate(bounds))
    bottom = max(i * leading + box[3] for i, box in enumerate(bounds))
    if style.underline:
        bottom = max(bottom, (len(lines) - 1) * leading + underline_y + underline_width)
    bottom = max(bottom, top + 1)
    slant = ceil((bottom - top) * .10) if synthetic_italic else 0
    box_width = content_width + 2 * (padding + slant)
    box_height = bottom - top + 2 * padding
    # Un tamaño par facilita centrar el PNG en las coordenadas de la salida YUV.
    tile_size = tuple((value + 1) // 2 * 2 for value in (box_width + 2 * bleed, box_height + 2 * bleed))
    image = Image.new("RGBA", tile_size)
    if not style.background_transparent and style.background_opacity:
        background = Image.new("L", tile_size)
        ImageDraw.Draw(background).rounded_rectangle(
            (bleed, bleed, bleed + box_width - 1, bleed + box_height - 1),
            radius=min(round(style.radius * factor), box_width // 2, box_height // 2), fill=255,
        )
        paint(image, background, style.background_color, style.background_opacity)

    def slant_image(art: Image.Image) -> Image.Image:
        if synthetic_italic:
            return art.transform(tile_size, Image.Transform.AFFINE, (1, .18, -.09 * tile_size[1], 0, 1, 0),
                                 resample=Image.Resampling.BICUBIC)
        return art

    origins = []
    for index, ((advance, box, runs), line_width) in enumerate(zip(layouts, widths)):
        space = content_width - line_width
        alignment = {"left": 0, "center": space / 2, "right": space}[style.align]
        x = bleed + padding + slant + round(alignment) - min(box[0], 0)
        y = bleed + padding - top + index * leading
        origins.append((x, y, advance, runs))

    def glyph_mask(border: int) -> Image.Image:
        mask = Image.new("L", tile_size)
        draw = ImageDraw.Draw(mask)
        for x, y, advance, runs in origins:
            for at, fragment, emoji in runs:
                if not emoji:
                    draw.text((x + at, y), fragment, fill=255, font=font, anchor="ls", stroke_width=border + extra)
            if style.underline and runs:
                start = y + underline_y - border
                draw.rectangle((x - border, start, x + ceil(advance) + border,
                                start + underline_width + 2 * border - 1), fill=255)
        return slant_image(mask)

    if opacity:
        fill = glyph_mask(0)
        outline = glyph_mask(stroke) if stroke else fill
        icons = Image.new("RGBA", tile_size) if has_emoji(text) else None
        if icons is not None:
            borders = Image.new("L", tile_size) if stroke else None
            for x, y, _, runs in origins:
                for at, _, emoji in runs:
                    if emoji:
                        icon = emoji_image(emoji, emoji_size)
                        point = (x + at, y + emoji_top)
                        icons.alpha_composite(icon, point)
                        if borders is not None:
                            expanded = ImageOps.expand(icon.getchannel("A"), border=stroke)
                            soft_edge = expanded.filter(ImageFilter.GaussianBlur(stroke * .55)).point(
                                [max(0, min(255, (value - 9) * 24)) for value in range(256)])
                            expanded = ImageChops.lighter(expanded, soft_edge)
                            borders.paste(255, (point[0] - stroke, point[1] - stroke,
                                                point[0] - stroke + expanded.width, point[1] - stroke + expanded.height),
                                          expanded)
            icons = slant_image(icons)
            composite_fill = ImageChops.lighter(fill, icons.getchannel("A"))
            outline = ImageChops.lighter(outline, slant_image(borders)) if borders is not None else composite_fill
        else:
            composite_fill = fill
        if style.shadow_opacity:
            shadow = Image.new("L", tile_size)
            shadow.paste(outline, offset)
            paint(image, shadow.filter(ImageFilter.GaussianBlur(blur)), style.shadow_color,
                  opacity * style.shadow_opacity / 100)
        if stroke:
            paint(image, ImageChops.subtract(outline, composite_fill), style.outline_color, opacity)
        paint(image, fill, color, opacity)
        if icons is not None:
            if opacity < 100:
                icons.putalpha(icons.getchannel("A").point([round(value * opacity / 100) for value in range(256)]))
            image.alpha_composite(icons)
    return save_tile(image)


def text_tile(layer: GraphicLayer, dimensions: tuple[int, int]) -> TextTile:
    style = layer.text_style or GraphicTextStyle(
        outline_width=min(24, round(layer.size * .068) if layer.hook else 3),
        shadow_opacity=0 if layer.hook else 45, shadow_blur=0, shadow_x=1, shadow_y=1,
    )
    return rasterize(layer.text, layer.font, layer.size, layer.color, layer.opacity,
                     style, dimensions)


def uses_text_tile(layer: GraphicLayer) -> bool:
    return layer.kind == "text" and (layer.text_style is not None or has_emoji(layer.text))
