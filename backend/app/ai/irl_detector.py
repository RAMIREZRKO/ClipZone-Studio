"""Puntuación de pasajes conversacionales a partir de Whisper, sin inferencia adicional."""
import re
from statistics import median

from .detector import normalize

TOKEN = re.compile(r"[^\W\d_]+")
ENDING = re.compile(r"[.!?…。！？][”’\"']*$")
ANNOTATION = re.compile(r"^[\[(].+[\])]$")
STOP_WORDS = set((
    "a al algo and are asi at aun bien but can como con creo cual cuando de del do el ella en es ese eso esta este "
    "esto for fue go ha hay here how i in is it la las le lo los me mi muy no nos o of oh ok on one or para pero "
    "por porque pues que se ser si so su te that the then there they this to tu un una vamos we what why with ya y yo you"
).split())

SETUP = re.compile(
    r"\b(?:el otro dia|aquella vez|una vez|la primera vez|cuando (?:era|estaba|vivia|tenia|fui|llegue|me)|"
    r"de pequeno|me acuerdo|recuerdo que|pens[ea] que|me dijo|me conto|me paso|imaginate|"
    r"the other day|when i|once i|the first time|i thought|told me)\b"
)
TURN = re.compile(
    r"\b(?:pero|hasta que|de repente|en realidad|al final|por eso|resulta que|en vez de|termine|termino|"
    r"me di cuenta|entonces|asi que|but|instead|turns out|it turned out|suddenly|ended up|so that)\b"
)
CONFESSION = re.compile(
    r"\b(?:te confieso|me confeso|tengo que admitir|me arrepiento|nunca (?:lo dije|lo conte|te dije|se lo dije|se lo conte)|"
    r"no (?:te habia contado|se lo habia contado)|fui yo (?:quien|el que|la que)|"
    r"i admit|i have to admit|i never told|to tell you the truth)\b"
)
HUMOR = re.compile(
    r"\b(?:se (?:empezo a reir|partio de risa)|me (?:rei|dio risa|hizo gracia)|nos reimos|"
    r"era una broma|estaba bromeando|started laughing|was kidding|it was a joke)\b"
)
DISAGREEMENT = re.compile(
    r"\b(?:no estoy de acuerdo|no es cierto|no es verdad|no tiene sentido|no me parece justo|"
    r"eso es mentira|me parece injusto|no deberia|i disagree|that s not true|that makes no sense)\b"
)
EXPLANATION = re.compile(r"\b(?:porque|por eso|ya que|el problema|la razon|because|the reason)\b")
POSITION = re.compile(
    r"\b(?:necesitamos|nos (?:cuesta|preocupa|afecta)|me (?:preocupa|indigna)|"
    r"no (?:debemos|deberian|podemos permitir)|estamos cansad[oa]s|el (?:problema|riesgo) es|"
    r"we need|we re worried|we can t allow|the (?:problem|risk) is)\b"
)
CONSEQUENCE = re.compile(
    r"\b(?:porque|asi que|por eso|por lo (?:tanto|que)|pero|aunque|sin embargo|"
    r"que pasa que no|que no (?:lo|la|los|las) tenemos|"
    r"because|which means|as a result|but|however|even though)\b"
)
EMOTION = re.compile(
    r"\b(?:me emocione|me emociono|me puse a llorar|me dio (?:miedo|verguenza|rabia)|"
    r"no me lo esperaba|no esperaba que|me quede (?:helado|helada|sin palabras)|me dolio|"
    r"i started crying|i was scared|i was embarrassed|i didn t expect|i couldn t believe)\b"
)
ANSWER = re.compile(
    r"^(?:porque|pues|bueno|en realidad|resulta|lo que pasa|es que|no\b|si\b|"
    r"because|well|actually|it turns out|no\b|yes\b)"
)
REASONS = {
    "anecdote": "el relato enlaza un hecho con un giro o una consecuencia",
    "confession": "la transcripción contiene una revelación personal con detalles",
    "humor": "hay un planteamiento y un remate o una referencia a humor",
    "discussion": "el desacuerdo viene acompañado de una explicación",
    "perspective": "se plantea una postura y se aporta un motivo o una consecuencia",
    "answer": "una pregunta recibe una respuesta con un giro",
    "emotion": "se expresa una emoción y se aporta su contexto",
}


def clean_text(text: str) -> str:
    return " ".join(TOKEN.findall(normalize(text)))


def content_words(text: str) -> set[str]:
    return {word for word in text.split() if len(word) > 1 and word not in STOP_WORDS}


def transcript_phrases(words: list[dict]) -> list[list[dict]]:
    phrases, phrase = [], []
    for word in words:
        text = word["text"].strip()
        if not text or ANNOTATION.fullmatch(text):
            continue
        if not TOKEN.search(text):
            if phrase and re.search(r"[.!?…。！？]", text):
                phrase = [*phrase[:-1], {**phrase[-1], "text": phrase[-1]["text"] + text}]
                phrases.append(phrase)
                phrase = []
            continue
        if phrase and (word["start"] - phrase[-1]["end"] > .85 or len(phrase) >= 28):
            phrases.append(phrase)
            phrase = []
        phrase.append(word)
        if ENDING.search(text):
            phrases.append(phrase)
            phrase = []
    if phrase:
        phrases.append(phrase)
    return phrases


def evidence(parts: list[str], text: str, detail: int) -> list[str]:
    # Las expresiones son indicios. Exige contenido que las desarrolle en el pasaje.
    if detail < 6:
        return []
    setup = SETUP.search(text)
    turn = TURN.search(text, setup.end() if setup else 0)
    story = bool(setup and turn and len(text[turn.end():].split()) >= 3)
    kinds = []
    if story:
        kinds.append("anecdote")
    disclosure = CONFESSION.search(text)
    if disclosure and len(text[disclosure.end():].split()) >= 4:
        kinds.append("confession")
    if HUMOR.search(text) and (story or len(parts) >= 2):
        kinds.append("humor")
    objection = DISAGREEMENT.search(text)
    if objection and (EXPLANATION.search(text, objection.end()) or (len(parts) >= 2 and TURN.search(text))):
        kinds.append("discussion")
    elif detail >= 10 and (position := POSITION.search(text)):
        link = CONSEQUENCE.search(text, position.end())
        if link and len(content_words(text[link.end():])) >= 4:
            kinds.append("perspective")
    for question, answer in zip(parts, parts[1:]):
        reply = clean_text(answer)
        if (re.search(r"[?？][”’\"']*$", question) and len(content_words(clean_text(question))) >= 2
                and ANSWER.match(reply) and len(content_words(reply)) >= 4
                and (TURN.search(reply) or CONFESSION.search(reply) or EMOTION.search(reply)
                     or re.match(r"^(?:en realidad|resulta|actually|it turns out)\b", reply))):
            kinds.append("answer")
            break
    if EMOTION.search(text) and (EXPLANATION.search(text) or story or detail >= 10):
        kinds.append("emotion")
    return kinds


def score_conversation(transcript: dict, event: float, voice: float) -> dict:
    phrases = transcript_phrases(transcript.get("words", []))
    best = {"score": 0, "title": "Conversación sin transcribir", "excerpt": "", "metrics": {},
            "reason": "no hay conversación transcrita cerca de la muestra", "filters": ["no_transcribed_voice"]}

    for start, first in enumerate(phrases):
        words, parts = [], []
        for part in phrases[start:start + 4]:
            if words and (part[0]["start"] - words[-1]["end"] > 1.8 or part[-1]["end"] - first[0]["start"] > 20):
                break
            words.extend(part)
            parts.append(" ".join(word["text"] for word in part))
            distance = max(first[0]["start"] - event, event - part[-1]["end"], 0.)
            if distance > 10:
                continue
            raw = " ".join(parts)
            text = clean_text(raw)
            tokens = text.split()
            details = len(content_words(text))
            pairs = list(zip(tokens, tokens[1:]))
            repetition = 1 - len(set(pairs)) / len(pairs) if pairs else 0.
            confidence = median(float(word.get("probability", 1)) * (1 - .65 * float(word.get("no_speech", 0)))
                                for word in words)
            alignment = 1 - distance / 12
            context = min(1., details / 12.)
            structure = min(1., (len(parts) + 1) / 3)
            kinds = evidence(parts, text, details)
            score = (24 * bool(kinds) + 14 * structure + 21 * context
                     + 23 * confidence + 12 * alignment + 6 * voice)
            filters = []
            if not kinds:
                score = min(score, 52)
                filters.append("no_irl_context")
            if confidence < .45:
                score = min(score, 39)
                filters.append("low_confidence")
            if repetition >= .4 or details < 4:
                score = min(score, 35)
                filters.append("repetitive_speech")
            elif details < 6 or len(tokens) < 10:
                score = min(score, 52)
                filters.append("short_context")
            score = round(score)
            if score <= best["score"]:
                continue
            reasons = [REASONS[kind] for kind in kinds]
            if not kinds:
                reasons.append("la conversación no ofrece un pasaje con desarrollo editorial")
            for code, message in (("low_confidence", "Whisper tiene baja confianza en el pasaje"),
                                  ("repetitive_speech", "fragmento repetitivo o con poco contenido"),
                                  ("short_context", "el pasaje necesita más contexto")):
                if code in filters:
                    reasons.append(message)
            metrics = {"voice": voice, "alignment": alignment, "confidence": confidence,
                       "context": context, "repetition": repetition, "dialogue": structure}
            best = {"score": score, "title": raw if len(raw) <= 88 else raw[:85].rsplit(" ", 1)[0] + "…",
                    "excerpt": raw[:600], "reason": " · ".join(reasons), "filters": filters,
                    "metrics": {key: round(value * 100) for key, value in metrics.items()}}
    return best
