import pytest
from app.ai.contracts import Word
from app.ai.detector import detect_moments


def speech(text, offset=0, step=.4):
    return [Word(token, offset + i * step, offset + (i + 1) * step - .02) for i, token in enumerate(text.split())]


def test_scores_real_content_signals_and_respects_bounds():
    words = speech('Esta es una charla normal con algunas palabras para rellenar el tiempo.')
    words += speech('¿Cómo descubrí el secreto? Este consejo evita un error increíble. El resultado fue aprender algo nuevo.', offset=15)
    moments = detect_moments(words, 35, 3, 9, 5, [.3] * 35)
    assert moments
    assert moments[0]['start'] > 10
    assert moments[0]['metrics']['hook'] > 0
    assert [m['score'] for m in moments] == sorted([m['score'] for m in moments], reverse=True)
    for m in moments:
        assert 3 <= m['end'] - m['start'] <= 9.001
        assert 0 <= m['start'] < m['end'] <= 35
        assert 0 <= m['score'] <= 100
        assert m['title'] and m['reason']
    for i, one in enumerate(moments):
        for two in moments[i + 1:]:
            overlap = max(0, min(one['end'], two['end']) - max(one['start'], two['start']))
            assert overlap / min(one['end'] - one['start'], two['end'] - two['start']) <= .35


@pytest.mark.parametrize('words,duration,minimum', [([], 30, 3), (speech('Hola.'), 30, 3), (speech('Hay tres palabras.'), 1, 5), ([Word('bad', float('nan'), 2)], 30, 3)])
def test_no_invented_moments_when_no_usable_speech(words, duration, minimum):
    assert detect_moments(words, duration, minimum, 10) == []


def test_shorter_ranges_and_candidate_limit():
    words = []
    for offset in range(0, 120, 10):
        words += speech('¿Cómo mejorar el resultado? Aprende este consejo práctico para crear un vídeo.', offset)
    result = detect_moments(words, 120, 2, 8, 3)
    assert len(result) == 3
