from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


class Transcriber(Protocol):
    def transcribe(self, source: Path, language: str | None = None) -> list[Word]: ...


@dataclass(frozen=True)
class Moment:
    start: float
    end: float
    score: float
    reason: str


class MomentDetector(Protocol):
    def detect(self, words: list[Word], min_duration: float, max_duration: float) -> list[Moment]: ...
