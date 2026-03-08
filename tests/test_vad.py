# -*- coding: utf-8 -*-
import numpy as np
import pytest
from src.audio.vad import VoiceActivityDetector


@pytest.fixture(scope="module")
def vad():
    return VoiceActivityDetector(threshold=0.5)


def test_silencio_no_es_voz(vad):
    chunk = np.zeros(512, dtype="float32")
    assert vad.is_speech(chunk) is False


def test_reset_no_lanza(vad):
    vad.reset()  # No debe lanzar excepción


def test_chunk_incorrecto_no_crashea(vad):
    # Chunk pequeño con valores aleatorios bajos (ruido ambiente suave)
    chunk = np.random.uniform(-0.001, 0.001, 512).astype("float32")
    result = vad.is_speech(chunk)
    assert isinstance(result, bool)
