"""Ranking explicable del habla transcrita. No predice viralidad.

Busca frases completas, preguntas, revelaciones y densidad de voz; añade
actividad acústica cuando existe. El modelo de IA es Whisper, el ranking es local.
"""
from bisect import bisect_right
import math
import re
import unicodedata
from uuid import uuid4

from .contracts import Word


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def detect_moments(words: list[Word], duration: float, min_duration: float, max_duration: float,
                   limit: int = 8, energy: list[float] | None = None) -> list[dict]:
    clean = sorted((w for w in words if w.text.strip() and math.isfinite(w.start) and math.isfinite(w.end)
                    and 0 <= w.start < w.end <= duration + .05), key=lambda w: (w.start, w.end))
    if not clean or duration < min_duration:
        return []
    # Fronteras naturales: puntuación, pausas y un límite de longitud de frase.
    sentences: list[list[Word]] = []
    current: list[Word] = []
    for word in clean:
        if current and (word.start - current[-1].end > .65 or word.end - current[0].start > max_duration):
            sentences.append(current)
            current = []
        current.append(word)
        if re.search(r"[.!?。！？][\"'”’]*$", word.text):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    starts = [s[0].start for s in sentences]
    energy_peak = (max(energy) or 1) if energy else 1
    candidates = []
    # Como máximo ~3 finales por comienzo: O(n log n), incluso con vídeos largos.
    for i, sentence in enumerate(sentences):
        start = max(0, sentence[0].start - .08)
        last = bisect_right(starts, start + max_duration) - 1
        target = (min_duration + max_duration) / 2
        endings = {i, last, max(i, bisect_right(starts, start + target) - 1)}
        for j in endings:
            if j < i:
                continue
            group = [w for s in sentences[i:j + 1] for w in s if w.end <= start + max_duration]
            if not group:
                continue
            end = min(duration, group[-1].end + .12, start + max_duration)
            length = end - start
            if length + .001 < min_duration or len(group) < 3:
                continue
            text = " ".join(w.text for w in group)
            folded = normalize(text)
            coverage = min(1, sum(max(0, w.end - w.start) for w in group) / length)
            pace = min(1, len(group) / length / 2.7)
            hook = min(1, sum(bool(re.search(pattern, folded)) for pattern in (
                r"[¿?]", r"\b(como|why|how|por que)\b", r"\b(secreto|secret|error|mistake|increible|incredible)\b",
                r"\b(descubri|aprendi|learned|descubre|imagina|imagine)\b", r"\b(consejo|paso|tip|resultado|result)\b")) / 3)
            closure = float(bool(re.search(r"[.!?。！？][\"'”’]*$", group[-1].text)))
            activity = 0.0
            if energy:
                values = energy[max(0, int(start)):min(len(energy), math.ceil(end))]
                if values:
                    # Energía relativa, no un premio al volumen absoluto.
                    activity = min(1, sum(values) / len(values) / energy_peak)
            score = round(min(100, 15 + 24 * coverage + 16 * pace + 25 * hook + 12 * closure + 8 * activity))
            metrics = {"speech": round(coverage * 100), "hook": round(hook * 100), "closure": round(closure * 100), "energy": round(activity * 100)}
            reasons = []
            if hook > .3: reasons.append("pregunta o idea con gancho")
            if coverage > .55: reasons.append("habla continua")
            if closure: reasons.append("cierre de frase")
            if activity > .5: reasons.append("actividad de voz")
            candidates.append({"id": uuid4().hex, "start": round(start, 3), "end": round(end, 3), "score": score,
                               "title": " ".join(w.text for w in group[:10])[:90], "text": text,
                               "reason": ", ".join(reasons) or "fragmento de conversación", "metrics": metrics})
    selected = []
    for candidate in sorted(candidates, key=lambda c: (-c["score"], c["start"])):
        # Evita devolver el mismo contenido con límites apenas distintos.
        if any(max(0, min(candidate["end"], s["end"]) - max(candidate["start"], s["start"]))
               / min(candidate["end"] - candidate["start"], s["end"] - s["start"]) > .35 for s in selected):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected
