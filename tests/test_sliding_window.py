# -*- coding: utf-8 -*-
"""
Tests de la lógica de transcripción del LocalStreamEngine.
Se testea sin audio real ni modelo: se parchea engine con mocks.
"""
import time
import numpy as np
from unittest.mock import MagicMock

from src.transcription.local_stream_engine import LocalStreamEngine


def make_engine(window=5.0, interval=0.5, confirm=3.0):
    """Crea un LocalStreamEngine con engine mock."""
    whisper = MagicMock()
    whisper.transcribe.return_value = ""

    engine = LocalStreamEngine(
        engine=whisper,
        window_duration=window,
        transcribe_interval=interval,
        confirm_threshold=confirm,
    )
    return engine, whisper


def test_buffer_corto_emite_solo_parcial():
    """Si el buffer dura menos que confirm_threshold, todo es parcial."""
    engine, whisper = make_engine(window=5.0, interval=0.5, confirm=3.0)
    whisper.transcribe.return_value = "hola mundo"

    confirmed_texts = []
    partial_texts = []
    engine.on_final = lambda t: confirmed_texts.append(t)
    engine.on_partial = lambda t: partial_texts.append(t)

    # Enviar 1s de audio (< 3s threshold)
    audio = np.zeros(16000, dtype=np.float32)
    engine.send_audio(audio)
    engine._has_speech = True
    engine._do_transcribe()

    assert confirmed_texts == [], "No debería haber texto confirmado con buffer corto"
    assert "hola mundo" in partial_texts


def test_buffer_largo_divide_confirmado_y_parcial():
    """Con buffer > confirm_threshold, parte se confirma y parte queda parcial."""
    engine, whisper = make_engine(window=5.0, interval=0.5, confirm=3.0)
    # 6 palabras; ratio = 3/5 = 0.6 → 3 palabras confirmadas, 3 parciales
    whisper.transcribe.return_value = "uno dos tres cuatro cinco seis"

    confirmed_texts = []
    partial_texts = []
    engine.on_final = lambda t: confirmed_texts.append(t)
    engine.on_partial = lambda t: partial_texts.append(t)

    # Enviar 5s de audio (> 3s threshold)
    audio = np.zeros(5 * 16000, dtype=np.float32)
    engine.send_audio(audio)
    engine._has_speech = True
    engine._do_transcribe()

    assert len(confirmed_texts) > 0, "Debería haber texto confirmado con buffer largo"
    assert len(partial_texts) > 0, "Debería haber texto parcial"
    palabras_total = (
        len(" ".join(confirmed_texts).split()) +
        len(" ".join(partial_texts).split())
    )
    assert palabras_total == 6


def test_texto_vacio_no_emite():
    """Transcripción vacía no emite nada."""
    engine, whisper = make_engine()
    whisper.transcribe.return_value = "   "

    confirmed_texts = []
    partial_texts = []
    engine.on_final = lambda t: confirmed_texts.append(t)
    engine.on_partial = lambda t: partial_texts.append(t)

    audio = np.zeros(16000, dtype=np.float32)
    engine.send_audio(audio)
    engine._has_speech = True
    engine._do_transcribe()

    assert confirmed_texts == []
    assert partial_texts == []


def test_has_speech_se_resetea_tras_transcripcion():
    """has_speech debe ser False después de _do_transcribe."""
    engine, whisper = make_engine()
    whisper.transcribe.return_value = "algo"

    engine.on_final = lambda t: None
    engine.on_partial = lambda t: None

    audio = np.zeros(16000, dtype=np.float32)
    engine.send_audio(audio)
    engine._has_speech = True
    engine._do_transcribe()

    assert engine._has_speech is False


def test_circular_buffer_wraps():
    """El buffer circular funciona correctamente al llenarse."""
    engine, whisper = make_engine(window=1.0)  # 1 segundo = 16000 muestras
    whisper.transcribe.return_value = "test"

    # Enviar 2s de audio (debería sobreescribir primera mitad)
    chunk1 = np.ones(16000, dtype=np.float32) * 0.5
    chunk2 = np.ones(16000, dtype=np.float32) * 0.9
    engine.send_audio(chunk1)
    engine.send_audio(chunk2)

    audio = engine._get_buffer_audio()
    assert len(audio) == 16000
    # El buffer debería contener solo chunk2 (el más reciente)
    np.testing.assert_allclose(audio, chunk2, atol=1e-6)


def test_flush_on_stop_confirms_all():
    """Al detener, flush confirma todo el texto pendiente."""
    engine, whisper = make_engine()
    whisper.transcribe.return_value = "texto final"

    confirmed = []
    engine.on_final = lambda t: confirmed.append(t)

    audio = np.zeros(16000, dtype=np.float32)
    engine.send_audio(audio)
    engine._has_speech = True
    engine.stop()

    assert "texto final" in confirmed
