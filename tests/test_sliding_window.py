# -*- coding: utf-8 -*-
"""
Tests del SlidingWindowWorker con algoritmo de confirmacion por overlap.
Se testea sin audio real ni modelo: se parchea engine y vad con mocks.

Actualizado para el nuevo algoritmo de overlap (reemplaza ratio-split).
"""
import queue
import numpy as np
from unittest.mock import MagicMock

from src.transcription.worker import SlidingWindowWorker, _AudioStream


def make_worker(window=15.0, interval=3.0, max_buf=60.0):
    engine = MagicMock()
    vad    = MagicMock()
    vad.is_speech.return_value = True

    cfg = MagicMock()
    cfg.window_duration     = window
    cfg.transcribe_interval = interval
    cfg.max_buffer_seconds  = max_buf
    cfg.hallucination_filter = True
    cfg.mic_label    = "Tu"
    cfg.system_label = "Reunion"

    q = queue.Queue()
    worker = SlidingWindowWorker(q, engine, vad, cfg)
    return worker, engine, vad, q


def _setup_stream(worker, n_samples, has_speech=True, prev_transcription=None):
    """Prepara el stream mic del worker con un buffer de n_samples."""
    s = worker._mic
    s.accumulating_buffer = np.zeros(n_samples, dtype=np.float32)
    s.has_speech = has_speech
    s.prev_transcription = prev_transcription
    return s


def test_primera_transcripcion_solo_parcial():
    """Sin transcripcion previa (prev=None), todo se emite como parcial."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "hola que tal"

    confirmed = []
    partial = []
    worker.text_confirmed.connect(lambda src, t: confirmed.append(t))
    worker.text_partial.connect(lambda src, t: partial.append(t))
    worker.status_changed.connect(lambda _: None)

    stream = _setup_stream(worker, n_samples=3 * 16000, prev_transcription=None)
    worker._do_transcription(stream)

    assert confirmed == [], "Primera transcripcion no debe confirmar nada"
    assert "hola que tal" in partial
    assert stream.prev_transcription == ["hola", "que", "tal"]


def test_segunda_transcripcion_confirma_inicio():
    """Con prev_transcription, las palabras que caen se confirman."""
    worker, engine, _, _ = make_worker()
    # Simula la segunda transcripcion: "hola" ya no aparece
    engine.transcribe.return_value = "que tal como estas"

    confirmed = []
    partial = []
    worker.text_confirmed.connect(lambda src, t: confirmed.append(t))
    worker.text_partial.connect(lambda src, t: partial.append(t))
    worker.status_changed.connect(lambda _: None)

    stream = _setup_stream(
        worker,
        n_samples=5 * 16000,
        prev_transcription=["hola", "que", "tal"],
    )
    worker._do_transcription(stream)

    assert len(confirmed) > 0, "Deberia confirmar 'hola'"
    assert "hola" in confirmed[0]
    assert stream.prev_transcription == ["que", "tal", "como", "estas"]


def test_transcripcion_identica_no_confirma():
    """Si la transcripcion es identica a la anterior, nada se confirma."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "uno dos tres"

    confirmed = []
    worker.text_confirmed.connect(lambda src, t: confirmed.append(t))
    worker.text_partial.connect(lambda src, t: None)
    worker.status_changed.connect(lambda _: None)

    stream = _setup_stream(
        worker,
        n_samples=3 * 16000,
        prev_transcription=["uno", "dos", "tres"],
    )
    worker._do_transcription(stream)

    assert confirmed == [], "Transcripcion identica no debe confirmar"


def test_texto_vacio_no_emite():
    """Transcripcion vacia no emite nada."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "   "

    confirmed = []
    partial = []
    worker.text_confirmed.connect(lambda src, t: confirmed.append(t))
    worker.text_partial.connect(lambda src, t: partial.append(t))
    worker.status_changed.connect(lambda _: None)

    stream = _setup_stream(worker, n_samples=16000)
    worker._do_transcription(stream)

    assert confirmed == []
    assert partial == []


def test_has_speech_se_resetea_tras_transcripcion():
    """has_speech del stream debe ser False despues de _do_transcription."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "algo"

    worker.text_confirmed.connect(lambda src, t: None)
    worker.text_partial.connect(lambda src, t: None)
    worker.status_changed.connect(lambda _: None)

    stream = _setup_stream(worker, n_samples=16000, has_speech=True)
    worker._do_transcription(stream)

    assert stream.has_speech is False


def test_hallucination_filtrada():
    """Las alucinaciones de Whisper se filtran y no emiten nada."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "Gracias por ver"

    confirmed = []
    partial = []
    worker.text_confirmed.connect(lambda src, t: confirmed.append(t))
    worker.text_partial.connect(lambda src, t: partial.append(t))
    worker.status_changed.connect(lambda _: None)

    stream = _setup_stream(worker, n_samples=16000, prev_transcription=["algo"])
    worker._do_transcription(stream)

    assert confirmed == []
    assert partial == []


def test_flush_al_stop_confirma_todo():
    """Al hacer stop(), el buffer restante se transcribe y confirma."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "texto final del buffer"

    confirmed = []
    worker.text_confirmed.connect(lambda src, t: confirmed.append(t))
    worker.text_partial.connect(lambda src, t: None)
    worker.status_changed.connect(lambda _: None)

    # Poner audio en el buffer
    worker._mic.accumulating_buffer = np.zeros(16000, dtype=np.float32)
    # worker.run() no se invoca; solo simulamos stop() que hace flush
    worker._running = False
    worker.stop()

    assert len(confirmed) > 0
    assert "texto final del buffer" in confirmed[0]


def test_force_trim_cuando_buffer_excede_max():
    """Si el buffer excede max_buffer_seconds, se fuerza confirmacion."""
    worker, engine, _, _ = make_worker(max_buf=2.0)  # max 2 segundos

    confirmed = []
    worker.text_confirmed.connect(lambda src, t: confirmed.append(t))
    worker.text_partial.connect(lambda src, t: None)
    worker.status_changed.connect(lambda _: None)

    stream = worker._mic
    stream.prev_transcription = ["estas", "palabras", "se", "confirman"]
    # Buffer mas grande que 2 segundos
    stream.accumulating_buffer = np.zeros(3 * 16000, dtype=np.float32)

    worker._force_trim(stream)

    assert len(confirmed) > 0
    assert "estas palabras se confirman" in confirmed[0]
    assert stream.prev_transcription is None
    # Buffer recortado
    assert len(stream.accumulating_buffer) <= 2 * 16000


def test_signal_labels_correctos():
    """Las signals usan el label correcto (Tu/Reunion)."""
    worker, engine, _, _ = make_worker()
    engine.transcribe.return_value = "hola mundo nuevo"

    labels = []
    worker.text_partial.connect(lambda src, t: labels.append(src))
    worker.text_confirmed.connect(lambda src, t: labels.append(src))
    worker.status_changed.connect(lambda _: None)

    stream = _setup_stream(
        worker,
        n_samples=5 * 16000,
        prev_transcription=["algo", "hola", "mundo"],
    )
    worker._do_transcription(stream)

    # Todos los labels deben ser "Tu" (mic stream)
    assert all(l == "Tu" for l in labels)
