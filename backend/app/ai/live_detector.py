"""Señales acústicas baratas y puntuación editorial posterior a Whisper."""
from array import array
from collections import deque
from dataclasses import dataclass
from math import log10
import re
from statistics import median
import sys

from .detector import normalize

RATE = 16000
FRAME_BYTES = RATE * 2 * 30 // 1000
BLOCK_BYTES = FRAME_BYTES * 10


@dataclass(frozen=True)
class AudioSignal:
    time: float
    intensity: float
    voice: float
    reasons: tuple[str, ...]


class LiveDetector:
    def __init__(self, sensitivity: str):
        import webrtcvad

        self.vad = webrtcvad.Vad({"low": 3, "balanced": 2, "high": 1}[sensitivity])
        self.threshold = {"low": 12, "balanced": 8, "high": 5}[sensitivity]
        self.levels: deque[float] = deque(maxlen=80)
        self.activity: deque[bool] = deque(maxlen=4)
        self.last_level = -65.
        self.armed = True

    def feed(self, pcm: bytes, start: float):
        for offset in range(0, len(pcm) - BLOCK_BYTES + 1, BLOCK_BYTES):
            chunk = pcm[offset:offset + BLOCK_BYTES]
            samples = array("h", chunk)
            if sys.byteorder != "little":
                samples.byteswap()
            rms = max(.0001, (sum(value * value for value in samples) / len(samples)) ** .5 / 32768)
            peak = max(abs(min(samples)), max(samples)) / 32768
            voice = sum(self.vad.is_speech(chunk[i:i + FRAME_BYTES], RATE)
                        for i in range(0, BLOCK_BYTES, FRAME_BYTES)) / 10
            signal = self.measure(20 * log10(rms), peak, voice, start + offset / (2 * RATE) + .15)
            if signal:
                yield signal

    def measure(self, level: float, peak: float, voice: float, time: float) -> AudioSignal | None:
        baseline = max(-55., median(self.levels)) if self.levels else level
        lift = level - baseline
        jump = level - self.last_level
        warmed = len(self.levels) >= 6
        self.levels.append(max(-65., level))
        self.last_level = level
        strong = warmed and level > -37 and voice >= .4 and lift >= self.threshold
        self.activity.append(strong)
        if not strong:
            if not any(self.activity):
                self.armed = True
            return None
        if not self.armed or (sum(self.activity) < 2 and not (jump >= self.threshold + 3 and voice >= .7 and peak >= .14)):
            return None
        self.armed = False
        reasons = ["actividad compatible con voz", "intensidad por encima del nivel reciente"]
        if jump >= self.threshold:
            reasons.append("cambio brusco de intensidad")
        if sum(self.activity) >= 2:
            reasons.append("señales acústicas acumuladas")
        if peak >= .35 and voice >= .7:
            reasons.append("posible reacción vocal intensa, sin identificar risa o grito")
        return AudioSignal(time, min(1., (lift + max(0., jump) / 2) / 23), voice, tuple(reasons))


def editorial_score(transcript: dict, event: float, signal: AudioSignal) -> dict | None:
    words = [word for word in transcript["words"] if word["text"].strip()]
    if len(words) < 3:
        return None
    phrases = []
    phrase = []
    for word in words:
        if phrase and word["start"] - phrase[-1]["end"] > .8:
            phrases.append(phrase)
            phrase = []
        phrase.append(word)
        if re.search(r"[.!?…][”’\x22\x27]*$", word["text"]) or len(phrase) >= 18:
            phrases.append(phrase)
            phrase = []
    if phrase:
        phrases.append(phrase)
    nearby = [part for part in phrases if len(part) >= 3] or phrases
    focus = min(nearby, key=lambda part: max(part[0]["start"] - event, event - part[-1]["end"], 0))
    sample = " ".join(word["text"] for word in focus)
    ready = normalize(sample)
    hook = min(1., .25 + .25 * sum(bool(re.search(pattern, ready)) for pattern in (
        r"[¿?]", r"\b(como|porque|por que|how|why)\b", r"\b(mira|imagina|increible|no puedo|wait|wow|incredible)\b",
    )))
    context = min(1., len(words) / 20)
    voiced = sum(max(0., word["end"] - word["start"]) for word in focus)
    span = max(.3, focus[-1]["end"] - focus[0]["start"])
    continuity = min(1., voiced / span)
    closure = float(bool(re.search(r"[.!?…][”’\x22\x27]*$", sample)))
    metrics = {"intensity": signal.intensity, "voice": signal.voice, "hook": hook, "context": context,
               "continuity": continuity, "closure": closure}
    weights = (.20, .16, .20, .17, .16, .11)
    score = round(100 * sum(weight * value for weight, value in zip(weights, metrics.values())))
    reasons = list(signal.reasons)
    if hook >= .5:
        reasons.append("frase con gancho")
    if context >= .45:
        reasons.append("contexto transcrito")
    if continuity >= .55:
        reasons.append("habla continua")
    if closure:
        reasons.append("cierre de frase")
    title = sample if len(sample) <= 88 else sample[:85].rsplit(" ", 1)[0] + "…"
    return {"score": min(100, max(0, score)), "title": title, "reason": " · ".join(reasons),
            "metrics": {key: round(value * 100) for key, value in metrics.items()},
            "excerpt": " ".join(word["text"] for word in words)[:600]}

