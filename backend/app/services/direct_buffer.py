"""Ventana de segmentos cerrados. El propietario serializa acceso y borrados."""
from collections import Counter, deque
from dataclasses import dataclass, replace
import csv
from math import isfinite
from pathlib import Path
import re

SESSION_NAME = re.compile(r"[a-f0-9]{32}")
SEGMENT_NAME = re.compile(r"g[0-9]{2}-[0-9]{8}\.mkv")
PLAYLIST_NAME = "snapshot.ffconcat"
AUTO_PLAYLIST = "autoclip.ffconcat"
BUFFER_SECONDS = 300


@dataclass
class Segment:
    path: Path
    generation: int
    start: float
    duration: float


class DirectBuffer:
    def __init__(self, folder: Path, max_seconds: float = BUFFER_SECONDS):
        self.folder = folder
        self.max_seconds = max_seconds
        self.closed: deque[Segment] = deque()
        self.pins: Counter[Path] = Counter()
        self.epoch = 0
        self.retired: set[Path] = set()
        self.bytes = 0

    @property
    def seconds(self) -> float:
        return sum(item.duration for item in self.closed)

    @staticmethod
    def pattern(generation: int) -> str:
        return f"g{generation:02d}-%08d.mkv"

    def accept(self, line: bytes, generation: int) -> bool:
        try:
            name, start, end = next(csv.reader([line.decode("ascii").strip()]))
            first, last = float(start), float(end)
            if (not SEGMENT_NAME.fullmatch(name) or not name.startswith(f"g{generation:02d}-")
                    or not all(isfinite(value) for value in (first, last)) or last - first < .025):
                return False
            path = self.folder / name
            if path.is_symlink() or not path.is_file() or not path.stat().st_size:
                return False
        except (OSError, ValueError, UnicodeError, csv.Error, StopIteration):
            return False
        if self.closed:
            previous = self.closed[-1]
            difference = first - previous.start
            if previous.generation != generation or difference <= 0 or difference > max(20, previous.duration * 3):
                self.retired.update(item.path for item in self.closed)
                self.closed.clear()
                self.epoch += 1
            else:
                # La referencia de vídeo del siguiente segmento evita sumar
                # padding de audio en cada unión al usar el demuxer concat.
                previous.duration = difference
        self.closed.append(Segment(path, generation, first, last - first))
        self.prune_duration()
        return True

    def prune_duration(self) -> None:
        duration = self.seconds
        while len(self.closed) > 1 and duration - self.closed[0].duration >= self.max_seconds:
            segment = self.closed.popleft()
            duration -= segment.duration
            self.retired.add(segment.path)
        self.reap()

    def measure(self) -> int:
        self.bytes = 0
        for path in self.folder.iterdir():
            if SEGMENT_NAME.fullmatch(path.name) and not path.is_symlink():
                try:
                    self.bytes += path.stat().st_size
                except FileNotFoundError:
                    continue
        return self.bytes

    def enforce_bytes(self, maximum: int) -> int:
        measured = self.measure()
        while measured > maximum and self.closed:
            self.retired.add(self.closed.popleft().path)
            self.reap()
            measured = self.measure()
        return measured

    def snapshot(self, seconds: int) -> tuple[Segment, ...]:
        chosen = []
        duration = 0.
        for segment in reversed(self.closed):
            if chosen and duration + segment.duration > seconds + .06:
                break
            chosen.append(segment)
            duration += segment.duration
        return self.hold(reversed(chosen))

    def hold(self, segments) -> tuple[Segment, ...]:
        frozen = tuple(replace(item) for item in segments)
        self.pins.update(item.path for item in frozen)
        return frozen

    def release(self, segments) -> None:
        for item in segments:
            self.pins[item.path] -= 1
            if self.pins[item.path] <= 0:
                del self.pins[item.path]
        self.reap()

    def discard_incomplete(self, generation: int) -> None:
        keep = {item.path for item in self.closed} | self.pins.keys()
        self.retired.update(path for path in self.folder.glob(f"g{generation:02d}-*.mkv")
                            if SEGMENT_NAME.fullmatch(path.name) and path not in keep)
        self.reap()

    def reap(self) -> None:
        for path in self.retired - self.pins.keys():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            self.retired.remove(path)


def clean_session(folder: Path, preserve=()) -> None:
    if not SESSION_NAME.fullmatch(folder.name) or folder.is_symlink() or folder.resolve() != folder or not folder.is_dir():
        return
    for child in folder.iterdir():
        if child not in preserve and (SEGMENT_NAME.fullmatch(child.name) or child.name == PLAYLIST_NAME or
                                      child.name == AUTO_PLAYLIST and not preserve):
            try:
                child.unlink(missing_ok=True)
            except OSError:
                continue
    try:
        folder.rmdir()
    except OSError:
        pass


def write_playlist(path: Path, segments: tuple[Segment, ...]) -> None:
    lines = ["ffconcat version 1.0"]
    for segment in segments:
        lines.extend((f"file {segment.path.name}", f"duration {segment.duration:.6f}"))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")

