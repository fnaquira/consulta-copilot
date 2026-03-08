# -*- coding: utf-8 -*-
import numpy as np
import pytest
from src.transcription.engine import TranscriptionEngine


@pytest.fixture(scope="module")
def engine():
    return TranscriptionEngine(model_size="tiny", device="cpu",
                               compute_type="int8", language="es")


def test_silencio_retorna_vacio_o_casi(engine):
    silencio = np.zeros(16000, dtype="float32")
    texto = engine.transcribe(silencio)
    # Whisper puede retornar vacío o algún artefacto muy corto
    assert len(texto.strip()) < 10, f"Se esperaba texto vacío, se obtuvo: '{texto}'"


def test_initial_prompt_no_crashea(engine):
    silencio = np.zeros(8000, dtype="float32")
    texto = engine.transcribe(silencio, initial_prompt="prueba de contexto")
    assert isinstance(texto, str)
