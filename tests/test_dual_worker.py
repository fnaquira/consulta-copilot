# -*- coding: utf-8 -*-
"""
test_dual_worker.py

Tests para SlidingWindowWorker en modo dual (mic + sistema).
Usa mocks para engine y vad — no requiere hardware ni modelos reales.
"""

import queue
import time
import numpy as np
import pytest

from src.transcription.worker import SlidingWindowWorker, _AudioStream


# ------------------------------------------------------------------ #
# Helpers / Mocks
# ------------------------------------------------------------------ #

class _MockVAD:
    """VAD simulado que siempre retorna is_speech según configuración."""
    def __init__(self, always_speech: bool = True):
        self._always = always_speech

    def is_speech(self, chunk: np.ndarray) -> bool:
        return self._always

    def reset(self):
        pass


class _MockEngine:
    """Engine simulado que retorna texto fijo."""
    def __init__(self, text: str = "hola mundo"):
        self._text = text

    def transcribe(self, audio: np.ndarray, initial_prompt: str = "") -> str:
        if len(audio) < 100:
            return ""
        return self._text


def _make_chunk(samples: int = 512) -> np.ndarray:
    return np.zeros(samples, dtype=np.float32)


def _run_worker_briefly(worker: SlidingWindowWorker, seconds: float = 1.5):
    """Arranca el worker, espera, y lo detiene."""
    worker.start()
    time.sleep(seconds)
    worker._running = False
    worker.wait(3000)


# ------------------------------------------------------------------ #
# Tests de _AudioStream
# ------------------------------------------------------------------ #

def test_audio_stream_defaults():
    """_AudioStream se inicializa con valores por defecto correctos."""
    s = _AudioStream(
        name="mic", label="Tu",
        audio_queue=queue.Queue(),
        vad=_MockVAD(),
    )
    assert s.name == "mic"
    assert s.label == "Tu"
    assert len(s.accumulating_buffer) == 0
    assert s.confirmed_text == ""
    assert s.has_speech is False
    assert s.max_buffer_samples == int(60.0 * 16000)


def test_audio_stream_max_buffer():
    """max_buffer_samples respeta max_buffer_seconds."""
    s = _AudioStream(
        name="sys", label="Reunion",
        audio_queue=queue.Queue(),
        vad=_MockVAD(),
        max_buffer_seconds=3.0,
    )
    assert s.max_buffer_samples == 3 * 16000


# ------------------------------------------------------------------ #
# Tests del worker en modo solo-mic (backwards compat)
# ------------------------------------------------------------------ #

def test_worker_solo_mic_crea_un_stream():
    """Sin system_queue, el worker tiene exactamente un stream."""
    q = queue.Queue()
    w = SlidingWindowWorker(
        mic_queue=q,
        engine=_MockEngine(),
        mic_vad=_MockVAD(),
    )
    assert len(w._streams) == 1
    assert w._system is None


def test_worker_dual_crea_dos_streams():
    """Con system_queue y system_vad, el worker tiene dos streams."""
    mic_q = queue.Queue()
    sys_q = queue.Queue()
    w = SlidingWindowWorker(
        mic_queue=mic_q,
        engine=_MockEngine(),
        mic_vad=_MockVAD(),
        system_queue=sys_q,
        system_vad=_MockVAD(),
    )
    assert len(w._streams) == 2
    assert w._system is not None


def test_worker_system_none_no_agrega_stream():
    """system_vad=None sin system_queue → solo un stream."""
    mic_q = queue.Queue()
    w = SlidingWindowWorker(
        mic_queue=mic_q,
        engine=_MockEngine(),
        mic_vad=_MockVAD(),
        system_queue=None,
        system_vad=None,
    )
    assert len(w._streams) == 1


# ------------------------------------------------------------------ #
# Tests de señales emitidas
# ------------------------------------------------------------------ #

def test_solo_mic_emite_label_correcto():
    """En modo solo-mic _do_transcription emite el label del mic."""
    mic_q  = queue.Queue()
    engine = _MockEngine("texto de prueba del mic largo para parcial")
    w = SlidingWindowWorker(
        mic_queue=mic_q,
        engine=engine,
        mic_vad=_MockVAD(always_speech=True),
    )

    confirmed_signals = []
    partial_signals   = []
    w.text_confirmed.connect(lambda src, txt: confirmed_signals.append((src, txt)))
    w.text_partial.connect(lambda src, txt: partial_signals.append((src, txt)))
    w.status_changed.connect(lambda _: None)

    # Llamar _do_transcription directamente (sin QThread)
    w._mic.accumulating_buffer = np.zeros(16000, dtype=np.float32)
    w._mic.has_speech   = True
    w._do_transcription(w._mic)

    all_signals = confirmed_signals + partial_signals
    assert len(all_signals) > 0, "No se emitieron señales"
    for src, _ in all_signals:
        assert src == "Tu", f"Label inesperado: {src!r}"


def test_dual_emite_labels_correctos():
    """En modo dual, cada fuente emite su propio label."""
    mic_q = queue.Queue()
    sys_q = queue.Queue()

    w = SlidingWindowWorker(
        mic_queue=mic_q,
        engine=_MockEngine("texto transcrito"),
        mic_vad=_MockVAD(always_speech=True),
        system_queue=sys_q,
        system_vad=_MockVAD(always_speech=True),
    )

    all_confirmed = []
    w.text_confirmed.connect(lambda src, txt: all_confirmed.append(src))

    # Alimentar ambas queues con ~2 segundos de audio
    for _ in range(64):
        mic_q.put(_make_chunk())
        sys_q.put(_make_chunk())

    _run_worker_briefly(w, seconds=2.0)

    if all_confirmed:
        labels = set(all_confirmed)
        # Deben aparecer solo labels válidos
        assert labels.issubset({"Tu", "Reunion"})


# ------------------------------------------------------------------ #
# Tests de buffers independientes
# ------------------------------------------------------------------ #

def test_buffers_independientes():
    """Los buffers de mic y sistema NO comparten datos."""
    mic_q = queue.Queue()
    sys_q = queue.Queue()

    mic_chunk = np.ones(512, dtype=np.float32) * 0.5
    sys_chunk = np.ones(512, dtype=np.float32) * 0.9

    w = SlidingWindowWorker(
        mic_queue=mic_q,
        engine=_MockEngine(),
        mic_vad=_MockVAD(always_speech=False),
        system_queue=sys_q,
        system_vad=_MockVAD(always_speech=False),
    )

    # Agregar solo al mic
    for _ in range(10):
        mic_q.put(mic_chunk.copy())

    # Drenar manualmente
    w._drain_queue(w._mic)
    if w._system:
        w._drain_queue(w._system)

    # El buffer del mic debe tener datos, el del sistema no
    assert len(w._mic.accumulating_buffer) > 0
    if w._system:
        assert len(w._system.accumulating_buffer) == 0


# ------------------------------------------------------------------ #
# Tests de stop + flush
# ------------------------------------------------------------------ #

def test_stop_no_falla_sin_audio():
    """stop() no debe fallar con buffer vacío."""
    w = SlidingWindowWorker(
        mic_queue=queue.Queue(),
        engine=_MockEngine(),
        mic_vad=_MockVAD(),
    )
    w.start()
    time.sleep(0.1)
    w.stop()  # No debe lanzar excepción


def test_vad_activity_emite_source_name():
    """vad_activity debe emitir el source_name, no solo bool."""
    mic_q = queue.Queue()
    vad_signals = []

    w = SlidingWindowWorker(
        mic_queue=mic_q,
        engine=_MockEngine(),
        mic_vad=_MockVAD(always_speech=True),
    )
    w.vad_activity.connect(lambda src, val: vad_signals.append((src, val)))

    mic_q.put(_make_chunk())
    w._drain_queue(w._mic)

    assert len(vad_signals) > 0
    src, val = vad_signals[0]
    assert src == "mic"
    assert isinstance(val, bool)
