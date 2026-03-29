# -*- coding: utf-8 -*-
"""
Tests puros del algoritmo de comparacion de transcripciones solapadas.
No requiere audio real ni modelo — solo logica de listas de palabras.
"""
from src.transcription.worker import SlidingWindowWorker, HALLUCINATION_PATTERNS


compare = SlidingWindowWorker._compare_transcriptions
is_hallucination = SlidingWindowWorker._is_hallucination


# ------------------------------------------------------------------ #
# _compare_transcriptions
# ------------------------------------------------------------------ #

def test_identical_transcriptions():
    """Mismas palabras exactas → nada confirmado (todo sigue en ventana)."""
    words = ["hola", "que", "tal", "como", "estas"]
    confirmed, stable = compare(words, words)
    assert confirmed == []
    assert stable == words


def test_prefix_drops_off():
    """Primeras palabras de prev no estan en curr → se confirman."""
    prev = ["hola", "que", "tal", "como", "estas"]
    curr = ["como", "estas", "yo", "bien"]
    confirmed, stable = compare(prev, curr)
    assert confirmed == ["hola", "que", "tal"]
    assert stable == ["como", "estas"]


def test_single_word_drops():
    """Una sola palabra cae de la ventana."""
    prev = ["primero", "segundo", "tercero"]
    curr = ["segundo", "tercero", "cuarto"]
    confirmed, stable = compare(prev, curr)
    assert confirmed == ["primero"]
    assert stable == ["segundo", "tercero"]


def test_no_overlap():
    """Textos completamente distintos → confirmar todo prev."""
    prev = ["alfa", "beta", "gamma"]
    curr = ["uno", "dos", "tres"]
    confirmed, stable = compare(prev, curr)
    assert confirmed == ["alfa", "beta", "gamma"]
    assert stable == []


def test_empty_prev():
    """Prev vacio → nada que confirmar."""
    confirmed, stable = compare([], ["hola", "mundo"])
    assert confirmed == []
    assert stable == []


def test_empty_curr():
    """Curr vacio → confirmar todo prev (audio desaparecio)."""
    prev = ["hola", "mundo"]
    confirmed, stable = compare(prev, [])
    assert confirmed == ["hola", "mundo"]
    assert stable == []


def test_both_empty():
    """Ambos vacios → nada que hacer."""
    confirmed, stable = compare([], [])
    assert confirmed == []
    assert stable == []


def test_real_spanish_overlap():
    """Ejemplo realista de dos transcripciones solapadas en español."""
    # Transcripcion N: audio segundos 0-15
    prev = "entonces el proyecto tiene tres fases la primera es la base de datos".split()
    # Transcripcion N+1: audio segundos 3-18 (3s nuevos)
    curr = "el proyecto tiene tres fases la primera es la base de datos y la segunda es la interfaz".split()
    confirmed, stable = compare(prev, curr)
    # "entonces" deberia caer (no aparece en curr)
    assert "entonces" in confirmed
    # El overlap debe incluir la parte comun
    assert len(stable) > 0


def test_partial_word_changes():
    """Whisper puede reformular ligeramente — el match parcial funciona."""
    prev = ["bueno", "entonces", "vamos", "a", "ver"]
    curr = ["entonces", "vamos", "a", "ver", "que", "pasa"]
    confirmed, stable = compare(prev, curr)
    assert confirmed == ["bueno"]
    assert stable == ["entonces", "vamos", "a", "ver"]


def test_many_words_drop():
    """Muchas palabras caen cuando el intervalo es largo."""
    prev = list("abcdefghij")  # 10 "palabras"
    curr = list("fghijklmno")  # solapan f-j
    confirmed, stable = compare(prev, curr)
    assert confirmed == list("abcde")
    assert stable == list("fghij")


# ------------------------------------------------------------------ #
# _is_hallucination
# ------------------------------------------------------------------ #

def test_hallucination_gracias_por_ver():
    assert is_hallucination(["Gracias", "por", "ver"]) is True


def test_hallucination_thank_you():
    assert is_hallucination(["Thank", "you"]) is True


def test_hallucination_suscribete():
    assert is_hallucination(["Suscribete"]) is True


def test_not_hallucination_normal_speech():
    assert is_hallucination(["hola", "como", "estas"]) is False


def test_not_hallucination_long_text():
    """Textos largos nunca son alucinacion (mas de 5 palabras)."""
    words = "gracias por ver este video que hemos preparado".split()
    assert is_hallucination(words) is False


def test_not_hallucination_empty():
    assert is_hallucination([]) is False
