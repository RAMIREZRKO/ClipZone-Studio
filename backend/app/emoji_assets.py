"""Emojis locales con el mismo PNG para el selector, la vista previa y FFmpeg."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile

from PIL import Image
import regex

GRAPHEMES = regex.compile(r"\X")
EMOJI = regex.compile(r"\p{Extended_Pictographic}|\p{Emoji_Presentation}|\u20e3")
ASSET_NAME = re.compile(r"[0-9a-f]+(?:-[0-9a-f]+)*")
ARTWORK = Path(__file__).with_name("emoji") / "twemoji-17.0.3.zip"


@lru_cache(maxsize=1)
def artwork() -> ZipFile:
    return ZipFile(ARTWORK)


@lru_cache(maxsize=512)
def emoji_png(identifier: str) -> bytes | None:
    if len(identifier) <= 90 and ASSET_NAME.fullmatch(identifier):
        try:
            return artwork().read(identifier + ".png")
        except KeyError:
            pass
    return None


def has_emoji(text: str) -> bool:
    return bool(EMOJI.search(text))


@lru_cache(maxsize=512)
def emoji_key(grapheme: str) -> str | None:
    if "\ufe0e" in grapheme or not has_emoji(grapheme):
        return None
    for variant in (grapheme, grapheme.replace("\ufe0f", "")):
        identifier = "-".join(f"{ord(char):x}" for char in variant)
        if emoji_png(identifier):
            return identifier
    if "\ufe0f" in grapheme or any(0x1F000 <= ord(char) for char in grapheme):
        for char in grapheme:
            identifier = f"{ord(char):x}"
            if has_emoji(char) and emoji_png(identifier):
                return identifier
        return "2753"
    return None


@lru_cache(maxsize=128)
def emoji_image(identifier: str, size: int) -> Image.Image:
    data = emoji_png(identifier)
    assert data is not None
    with Image.open(BytesIO(data)) as image:
        return image.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
