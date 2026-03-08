# -*- coding: utf-8 -*-
"""
Tests de la lógica de confirmación del SlidingWindowWorker.
Se testea sin audio real ni modelo: se parchea engine y vad con mocks.

Actualizado para Fase 9: _do_transcription(stream) y signals (str, str).
"""
import queue
import numpy as np
from unittest.mock import MagicMock

from src.transcription.worker import SlidingWindowWorker, _AudioStream


def make_worker(window=5.0, interval=1.0, confirm=3.0):
    engine = MagicMock()
    vad    = MagicMock()
    vad.is_speech.return_value = True

    cfg = MagicMock()
    cfg.window_duration     = window
    cfg.transcribe_interval = interval
    cfg.confirm_threshold   = confirm
    cfg.mic_label    = "Tú"
    cfg.system_label = "Reunión"

    q = queue.Queue()
    worker = SlidingWindowWorker(q, engine, vad, cfg)
    return worker, engine, vad, q


def _make_stream(worker, n_samples, has_speech=True):
    """Crea un _AudioStream de prueba vinculado al worker."""
    s = worker._mic
    s.audio_buffer = np.zeros(n_samples, dtype=np.float32)
    s.has_speech   = has_speech
    return s


def test_buffer_corto_emite_solo_parcial():
    """Si el buffer dura menos que confirm_threshold, todo es parcial."""
    worker, engine, _, q = make_worker(window=5.0, interval=1.0, confirm=3.0)
    engine.transcribe.return_value = "hola mundo"

    confirmed_texts = []
    partial_texts   = []
    worker.text_confirmed.connect(lambda src, t: confirmed_texts.append(t))
    worker.text_partial.connect(lambda src, t: partial_texts.append(t))
    worker.status_changed.connect(lambda _: None)

    stream = _make_stream(worker, n_samples=16000)  # 1 segundo < 3s threshold
    worker._do_transcription(stream)

    assert confirmed_texts == [], "No debería haber texto confirmado con buffer corto"
    assert "hola mundo" in partial_texts


def test_buffer_largo_divide_confirmado_y_parcial():
    """Con buffer > confirm_threshold, parte se confirma y parte queda parcial."""
    worker, engine, _, q = make_worker(window=5.0, interval=1.0, confirm=3.0)
    # 6 palabras; ratio = 3/5 = 0.6 → 3 palabras confirmadas, 3 parciales
    engine.transcribe.return_value = "uno dos tres cuatro cinco seis"

    confirmed_texts = []
    partial_texts   = []
    worker.text_confirmed.connect(lambda src, t: confirmed_texts.append(t))
    worker.text_partial.connect(lambda src, t: partial_texts.append(t))
    worker.status_changed.connect(lambda _: None)

    stream = _make_stream(worker, n_samples=5 * 16000)  # 5s > 3s threshold
    worker._do_transcription(stream)

    assert len(confirmed_texts) > 0, "Debería haber texto confirmado con buffer largo"
    assert len(partial_texts)   > 0, "Debería haber texto parcial"
    palabras_total = (
        len(" ".join(confirmed_texts).split()) +
        len(" ".join(partial_texts).split())
    )
    assert palabras_total == 6


def test_texto_vacio_no_emite():
    """Transcripción vacía no emite nada."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "   "

    confirmed_texts = []
    partial_texts   = []
    worker.text_confirmed.connect(lambda src, t: confirmed_texts.append(t))
    worker.text_partial.connect(lambda src, t: partial_texts.append(t))
    worker.status_changed.connect(lambda _: None)

    stream = _make_stream(worker, n_samples=16000)
    worker._do_transcription(stream)

    assert confirmed_texts == []
    assert partial_texts   == []


def test_has_speech_se_resetea_tras_transcripcion():
    """has_speech del stream debe ser False después de _do_transcription."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "algo"

    worker.text_confirmed.connect(lambda src, t: None)
    worker.text_partial.connect(lambda src, t: None)
    worker.status_changed.connect(lambda _: None)

    stream = _make_stream(worker, n_samples=16000, has_speech=True)
    worker._do_transcription(stream)

    assert stream.has_speech is False
