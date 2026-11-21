"""Detecta cambios de audio y puntúa su respaldo en la transcripción."""
from array import array
from collections import deque
from dataclasses import dataclass
from math import log10
import re
from statistics import median
import sys
from typing import Literal

from .detector import normalize
from .irl_detector import ANNOTATION, ENDING, STOP_WORDS, TOKEN, score_conversation

RATE = 16000
FRAME_BYTES = RATE * 2 * 30 // 1000
BLOCK_BYTES = FRAME_BYTES * 10
DetectionMode = Literal["gameplay", "irl", "mixed"]
CONVERSATION_INTERVAL = 24
REACTION = re.compile(
    r"\b(?:dios mio|ay dios|que (?:miedo|susto|locura|barbaridad)|no (?:puede ser|me lo creo|me gusta)|"
    r"no jod(?:as|a[sn])|me (?:asuste|asust[ao]|cague)|increible|flipa\w*|hostia\w*|"
    r"oh my god|no way|what (?:the hell|just happened)|unbelievable|holy shit|wow)\b"
)
GAMEPLAY = re.compile(
    r"\b(?:lo (?:logr[eoa]|consegui|consiguio)|consegui(?:mos|do)?|gan(?:e|amos|aste|aron)|perd(?:i|imos|ieron)|"
    r"remont\w*|empate|gol(?:azo)?|penalti|ultima vida|ultimo (?:gol|tiro|nivel)|"
    r"checkpoint|nivel (?:superado|completado)|elimin(?:e|amos|ado)|derrib\w*|esquiv\w*|"
    r"escap(?:e|amos|aste)|choqu\w*|atropell\w*|"
    r"clutch|comeback|we won|i won|we lost|i lost|last (?:life|kill)|final round|"
    r"scored|goal|knocked (?:him|her|them)|i got him|we got him|i escaped)\b"
)
ONGOING_RESULT = re.compile(r"\b(?:va(?:s|n)?|voy|vamos|est[aá](?:s|n)?|sigue(?:n)?) (?:ganando|perdiendo|empatando)\b")
GAME_CONTEXT = re.compile(r"\b(?:partido|ronda|torneo|marcador|gol|goles|penalti|nivel|fut ?champions?|uno a uno|uno uno|score|match)\b")


@dataclass(frozen=True)
class AudioSignal:
    time: float
    intensity: float
    voice: float
    reasons: tuple[str, ...]
    kind: Literal["reaction", "gameplay", "conversation"] = "reaction"


class LiveDetector:
    def __init__(self, sensitivity: str, mode: DetectionMode | Literal["reaction"] = "mixed"):
        import webrtcvad

        self.vad = webrtcvad.Vad({"low": 3, "balanced": 2, "high": 2}[sensitivity])
        self.threshold = {"low": 12, "balanced": 8, "high": 5}[sensitivity]
        self.voice_floor = {"low": .8, "balanced": .7, "high": .6}[sensitivity]
        self.mode = mode
        self.levels: deque[float] = deque(maxlen=80)
        self.voices: deque[float] = deque(maxlen=6)
        self.accents: deque[bool] = deque(maxlen=3)
        self.attacks: deque[bool] = deque(maxlen=6)
        self.last_level = -65.
        self.armed = True
        self.dialogue: deque[float] = deque(maxlen=32)
        self.dialogue_floor = {"low": .48, "balanced": .40, "high": .33}[sensitivity]
        self.last_conversation = float("-inf")

    def conversation(self, time: float) -> AudioSignal | None:
        if self.mode not in {"irl", "mixed"} or len(self.dialogue) < 20 or time - self.last_conversation < CONVERSATION_INTERVAL:
            return None
        amount = sum(self.dialogue) / len(self.dialogue)
        if amount < self.dialogue_floor or not any(list(self.dialogue)[-6:]):
            return None
        self.last_conversation = time
        return AudioSignal(time - 3, 0., amount, ("muestra periódica de conversación sostenida",), "conversation")

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
        if self.mode in {"irl", "mixed"}:
            self.dialogue.append(voice if voice >= .5 else 0.)
            if self.mode == "irl":
                return self.conversation(time)
        baseline = max(-55., median(self.levels)) if self.levels else level
        lift, jump = level - baseline, level - self.last_level
        warmed = len(self.levels) >= 6
        self.levels.append(max(-65., level))
        self.last_level = level

        vocal = voice >= self.voice_floor and level > -43
        self.voices.append(voice if vocal else 0.)
        recent = list(self.voices)
        previous_voice = sum(recent[:-2])
        self.accents.append(vocal and lift >= self.threshold)
        nearby_voice = sum(recent) >= 3
        attack_threshold = max(4, self.threshold - 4) if nearby_voice else max(9, self.threshold)
        attack = jump >= 6 and lift >= attack_threshold and peak > .19
        self.attacks.append(attack)
        reaction = vocal and sum(v > 0 for v in recent[-3:]) >= 2 and (
            sum(self.accents) >= 2 or (sum(self.accents) >= 1 and previous_voice <= .6)
        )
        gameplay = self.mode != "reaction" and attack and any(list(self.attacks)[:-2])
        if not (reaction or gameplay):
            if not any(self.accents) and not any(self.attacks):
                self.armed = True
            return self.conversation(time)
        if not warmed or not self.armed:
            return self.conversation(time)
        self.armed = False
        intensity = min(1., max(0., lift + max(0., jump) / 3) / 24)
        if reaction:
            voice_support = sum(recent[-3:]) / 3
            return AudioSignal(time, intensity, voice_support,
                               ("actividad vocal sostenida alrededor del evento",))
        return AudioSignal(time, intensity, sum(recent[-3:]) / 3,
                           ("cambios de audio separados que requieren contexto",), "gameplay")


def has_speech_context(pcm: bytes) -> bool:
    """Comprueba si una señal de gameplay sin voz local merece un turno de Whisper."""
    import webrtcvad

    vad = webrtcvad.Vad(3)
    consecutive = 0
    for offset in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
        if vad.is_speech(pcm[offset:offset + FRAME_BYTES], RATE):
            consecutive += 1
            if consecutive >= 9:
                return True
        else:
            consecutive = 0
    return False


def editorial_score(transcript: dict, event: float, signal: AudioSignal,
                    mode: DetectionMode | Literal["reaction"] = "mixed") -> dict:
    if mode in {"gameplay", "reaction"}:
        return acoustic_editorial_score(transcript, event, signal, mode)
    conversation = {**score_conversation(transcript, event, signal.voice), "detection_mode": mode, "detection_type": "irl"}
    if mode == "irl" or signal.kind == "conversation":
        return conversation
    current = acoustic_editorial_score(transcript, event, signal, "mixed")
    if not conversation["filters"] and conversation["score"] > current["score"]:
        return conversation
    return current


def acoustic_editorial_score(transcript: dict, event: float, signal: AudioSignal,
                             mode: Literal["reaction", "gameplay", "mixed"]) -> dict:
    nearby = []
    for word in transcript.get("words", []):
        text = word["text"].strip()
        if text and TOKEN.search(text) and not ANNOTATION.fullmatch(text) and word["end"] >= event - 8 and word["start"] <= event + 8:
            nearby.append(word)
    phrases = []
    phrase = []
    for word in nearby:
        if phrase and (word["start"] - phrase[-1]["end"] > .8 or len(phrase) >= 18):
            phrases.append(phrase)
            phrase = []
        phrase.append(word)
        if ENDING.search(word["text"]):
            phrases.append(phrase)
            phrase = []
    if phrase:
        phrases.append(phrase)

    def distance(part):
        return max(part[0]["start"] - event, event - part[-1]["end"], 0.)

    close = [part for part in phrases if distance(part) <= 3]
    focus = min(close, key=lambda part: (distance(part), -len(part)), default=[])
    sample = " ".join(item["text"] for item in focus)
    excerpt = " ".join(item["text"] for item in nearby)
    local_text = " ".join(TOKEN.findall(normalize(" ".join(
        word["text"] for word in nearby if word["end"] >= event - 3.5 and word["start"] <= event + 3.5
    ))))
    tokens = TOKEN.findall(normalize(excerpt))
    content = [word for word in tokens if word not in STOP_WORDS and len(word) > 1]
    diversity = len(set(content)) / max(1, len(content))
    pairs = list(zip(tokens, tokens[1:]))
    repetition = 1 - len(set(pairs)) / max(1, len(pairs)) if pairs else 0.
    coherence = min(1., len(set(content)) / 6) * (1 - repetition) * min(1., diversity * 1.4)
    context = min(1., len(set(content)) / 12) * (1 - repetition)
    confidence = median(float(word.get("probability", 1.)) * (1 - float(word.get("no_speech", 0.)) * .65)
                        for word in focus) if focus else 0.
    alignment = max(0., 1 - distance(focus) / 3.5) if focus else 0.
    voice = signal.voice * alignment
    reaction = bool(REACTION.search(local_text))
    gameplay = bool(GAMEPLAY.search(local_text) or (
        ONGOING_RESULT.search(local_text) and GAME_CONTEXT.search(" ".join(tokens))
    ))
    shared = 22 * coherence + 17 * context + 13 * alignment + 12 * confidence + 4 * signal.intensity
    sustained_reaction = signal.kind == "reaction" and voice >= .45
    reaction_limit = 100 if reaction else 55
    if not sustained_reaction:
        reaction_limit = 54
    reaction_score = min(reaction_limit, shared + 23 * voice + 9 * reaction)
    gameplay_score = min(100 if gameplay else 52, shared + 15 * voice + 17 * gameplay)

    chosen = mode
    if mode == "mixed":
        chosen = "gameplay" if gameplay_score > reaction_score or (gameplay_score == reaction_score and signal.kind == "gameplay") else "reaction"
    score = reaction_score if chosen == "reaction" else gameplay_score
    reasons, filters = [], []
    if focus and voice >= .45:
        reasons.append("la voz coincide con el evento")
    if coherence >= .58:
        reasons.append("la transcripción cercana aporta contexto variado")
    if chosen == "reaction" and reaction:
        reasons.append("la frase contiene una expresión de reacción")
    if focus and chosen == "reaction" and not sustained_reaction:
        reasons.append("la señal vocal del instante es insuficiente para confirmar una reacción")
        filters.append("weak_reaction")
    if chosen == "gameplay" and gameplay:
        reasons.append("la transcripción menciona una acción o un resultado del juego")
    if focus and not (reaction if chosen == "reaction" else gameplay):
        reasons.append("el diálogo próximo no corrobora un momento destacado")
        filters.append("no_editorial_evidence")
    if not focus:
        score = 30 + 4 * signal.intensity if mode != "reaction" and signal.kind == "gameplay" else 0
        reasons.append("efectos, música o ruido sin voz transcrita cerca del evento")
        filters.append("no_transcribed_voice")
    elif confidence < .45:
        score = min(score, 39)
        reasons.append("Whisper tiene baja confianza en la frase")
        filters.append("low_confidence")
    if focus and (repetition >= .43 or len(set(content)) <= 1):
        score = min(score, 35)
        reasons.append("transcripción repetitiva o con poco contenido")
        filters.append("repetitive_speech")
    elif focus and coherence < .35:
        score = min(score, 52)
        reasons.append("la transcripción aporta poco contexto")
        filters.append("short_context")
    if signal.intensity >= .6:
        reasons.append("el cambio de intensidad solo aporta hasta 4 puntos")
    title = sample or "Posible acción de gameplay"
    if len(title) > 88:
        title = title[:85].rsplit(" ", 1)[0] + "…"
    metrics = {"voice": voice, "alignment": alignment, "confidence": confidence, "coherence": coherence,
               "context": context, "repetition": repetition, "intensity": signal.intensity}
    return {"score": round(score), "title": title, "reason": " · ".join(reasons or signal.reasons),
            "metrics": {key: round(value * 100) for key, value in metrics.items()}, "excerpt": excerpt[:600],
            "detection_mode": mode, "detection_type": chosen, "filters": filters}
