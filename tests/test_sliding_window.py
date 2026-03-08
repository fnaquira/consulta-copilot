# -*- coding: utf-8 -*-
"""
Tests de la lógica de confirmación del SlidingWindowWorker.
Se testea sin audio real ni modelo: se parchea engine y vad con mocks.
"""
import queue
import time
import numpy as np
import pytest
from unittest.mock import MagicMock


def make_worker(window=5.0, interval=1.0, confirm=3.0):
    from src.transcription.worker import SlidingWindowWorker

    engine = MagicMock()
    vad    = MagicMock()
    vad.is_speech.return_value = True

    cfg = MagicMock()
    cfg.window_duration    = window
    cfg.transcribe_interval = interval
    cfg.confirm_threshold  = confirm

    q = queue.Queue()
    worker = SlidingWindowWorker(q, engine, vad, cfg)
    return worker, engine, vad, q


def test_buffer_corto_emite_solo_parcial():
    """Si el buffer dura menos que confirm_threshold, todo es parcial."""
    worker, engine, _, q = make_worker(window=5.0, interval=1.0, confirm=3.0)
    engine.transcribe.return_value = "hola mundo"

    # Buffer de 1 segundo (< 3s threshold)
    worker._audio_buffer = np.zeros(16000, dtype="float32")
    worker._has_speech   = True

    confirmed_texts = []
    partial_texts   = []
    worker.text_confirmed.connect(lambda t: confirmed_texts.append(t))
    worker.text_partial.connect(lambda t: partial_texts.append(t))
    worker.status_changed.connect(lambda _: None)

    worker._do_transcription()

    assert confirmed_texts == [], "No debería haber texto confirmado con buffer corto"
    assert "hola mundo" in partial_texts


def test_buffer_largo_divide_confirmado_y_parcial():
    """Con buffer > confirm_threshold, parte se confirma y parte queda parcial."""
    worker, engine, _, q = make_worker(window=5.0, interval=1.0, confirm=3.0)
    # Texto de 6 palabras; ratio = 3/5 = 0.6 → 3 palabras confirmadas, 3 parciales
    engine.transcribe.return_value = "uno dos tres cuatro cinco seis"

    # Buffer de 5 segundos (> 3s threshold)
    worker._audio_buffer = np.zeros(5 * 16000, dtype="float32")
    worker._has_speech   = True

    confirmed_texts = []
    partial_texts   = []
    worker.text_confirmed.connect(lambda t: confirmed_texts.append(t))
    worker.text_partial.connect(lambda t: partial_texts.append(t))
    worker.status_changed.connect(lambda _: None)

    worker._do_transcription()

    assert len(confirmed_texts) > 0, "Debería haber texto confirmado con buffer largo"
    assert len(partial_texts)   > 0, "Debería haber texto parcial"
    # La suma de palabras de ambas partes = 6
    palabras_total = (
        len(" ".join(confirmed_texts).split()) +
        len(" ".join(partial_texts).split())
    )
    assert palabras_total == 6


def test_texto_vacio_no_emite():
    """Transcripción vacía no emite nada."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "   "

    worker._audio_buffer = np.zeros(16000, dtype="float32")
    worker._has_speech   = True

    confirmed_texts = []
    partial_texts   = []
    worker.text_confirmed.connect(lambda t: confirmed_texts.append(t))
    worker.text_partial.connect(lambda t: partial_texts.append(t))
    worker.status_changed.connect(lambda _: None)

    worker._do_transcription()

    assert confirmed_texts == []
    assert partial_texts   == []


def test_has_speech_se_resetea_tras_transcripcion():
    """_has_speech debe ser False después de _do_transcription."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "algo"

    worker._audio_buffer = np.zeros(16000, dtype="float32")
    worker._has_speech   = True
    worker.text_confirmed.connect(lambda _: None)
    worker.text_partial.connect(lambda _: None)
    worker.status_changed.connect(lambda _: None)

    worker._do_transcription()

    assert worker._has_speech is False
