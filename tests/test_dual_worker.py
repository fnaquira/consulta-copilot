# -*- coding: utf-8 -*-
"""
test_dual_worker.py

Tests para SlidingWindowWorker en modo streaming (mic + sistema).
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


class _MockStreamEngine:
    """Engine streaming simulado que graba chunks recibidos."""
    def __init__(self):
        self.chunks_received = []
        self.started = False
        self.stopped = False
        self.on_partial = None
        self.on_final = None
        self.on_error = None

    def start(self):
        self.started = True

    def send_audio(self, chunk: np.ndarray):
        self.chunks_received.append(chunk.copy())

    def stop(self):
        self.stopped = True

    def set_has_speech(self, val: bool):
        pass


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
        name="mic", label="Tú",
        audio_queue=queue.Queue(),
        vad=_MockVAD(),
    )
    assert s.name == "mic"
    assert s.label == "Tú"
    assert s.engine is None
    assert s.last_vad_state is None


# ------------------------------------------------------------------ #
# Tests del worker en modo solo-mic (backwards compat)
# ------------------------------------------------------------------ #

def test_worker_solo_mic_crea_un_stream():
    """Sin system_queue, el worker tiene exactamente un stream."""
    q = queue.Queue()
    w = SlidingWindowWorker(
        mic_queue=q,
        mic_vad=_MockVAD(),
        mic_engine=_MockStreamEngine(),
    )
    assert len(w._streams) == 1
    assert w._system is None


def test_worker_dual_crea_dos_streams():
    """Con system_queue y system_vad, el worker tiene dos streams."""
    mic_q = queue.Queue()
    sys_q = queue.Queue()
    w = SlidingWindowWorker(
        mic_queue=mic_q,
        mic_vad=_MockVAD(),
        mic_engine=_MockStreamEngine(),
        system_queue=sys_q,
        system_vad=_MockVAD(),
        system_engine=_MockStreamEngine(),
    )
    assert len(w._streams) == 2
    assert w._system is not None


def test_worker_system_none_no_agrega_stream():
    """system_vad=None sin system_queue → solo un stream."""
    mic_q = queue.Queue()
    w = SlidingWindowWorker(
        mic_queue=mic_q,
        mic_vad=_MockVAD(),
        mic_engine=_MockStreamEngine(),
        system_queue=None,
        system_vad=None,
    )
    assert len(w._streams) == 1


# ------------------------------------------------------------------ #
# Tests de señales emitidas via engine callbacks
# ------------------------------------------------------------------ #

def test_engine_callbacks_emit_signals():
    """Los callbacks del engine emiten signals de Qt correctamente."""
    mic_q = queue.Queue()
    engine = _MockStreamEngine()
    w = SlidingWindowWorker(
        mic_queue=mic_q,
        mic_vad=_MockVAD(always_speech=True),
        mic_engine=engine,
    )

    confirmed_signals = []
    partial_signals = []
    w.text_confirmed.connect(lambda src, txt: confirmed_signals.append((src, txt)))
    w.text_partial.connect(lambda src, txt: partial_signals.append((src, txt)))

    # Simular que el engine invoca sus callbacks
    assert engine.on_final is not None
    assert engine.on_partial is not None
    engine.on_final("texto confirmado")
    engine.on_partial("texto parcial")

    assert ("Tú", "texto confirmado") in confirmed_signals
    assert ("Tú", "texto parcial") in partial_signals


def test_dual_emite_labels_correctos():
    """En modo dual, cada engine callback usa su propio label."""
    mic_q = queue.Queue()
    sys_q = queue.Queue()
    mic_engine = _MockStreamEngine()
    sys_engine = _MockStreamEngine()

    w = SlidingWindowWorker(
        mic_queue=mic_q,
        mic_vad=_MockVAD(always_speech=True),
        mic_engine=mic_engine,
        system_queue=sys_q,
        system_vad=_MockVAD(always_speech=True),
        system_engine=sys_engine,
    )

    confirmed = []
    w.text_confirmed.connect(lambda src, txt: confirmed.append(src))

    mic_engine.on_final("hola")
    sys_engine.on_final("mundo")

    assert "Tú" in confirmed
    assert "Reunión" in confirmed


# ------------------------------------------------------------------ #
# Tests de forwarding de audio al engine
# ------------------------------------------------------------------ #

def test_drain_forwards_chunks_to_engine():
    """_drain_queue envía chunks al engine."""
    mic_q = queue.Queue()
    engine = _MockStreamEngine()
    w = SlidingWindowWorker(
        mic_queue=mic_q,
        mic_vad=_MockVAD(always_speech=False),
        mic_engine=engine,
    )

    for _ in range(5):
        mic_q.put(_make_chunk())

    w._drain_queue(w._mic)
    assert len(engine.chunks_received) == 5


def test_buffers_independientes():
    """Los chunks de mic y sistema van a engines separados."""
    mic_q = queue.Queue()
    sys_q = queue.Queue()
    mic_engine = _MockStreamEngine()
    sys_engine = _MockStreamEngine()

    w = SlidingWindowWorker(
        mic_queue=mic_q,
        mic_vad=_MockVAD(always_speech=False),
        mic_engine=mic_engine,
        system_queue=sys_q,
        system_vad=_MockVAD(always_speech=False),
        system_engine=sys_engine,
    )

    # Solo agregar al mic
    for _ in range(10):
        mic_q.put(_make_chunk())

    w._drain_queue(w._mic)
    if w._system:
        w._drain_queue(w._system)

    assert len(mic_engine.chunks_received) == 10
    assert len(sys_engine.chunks_received) == 0


# ------------------------------------------------------------------ #
# Tests de stop + engine lifecycle
# ------------------------------------------------------------------ #

def test_stop_no_falla_sin_audio():
    """stop() no debe fallar con buffer vacío."""
    engine = _MockStreamEngine()
    w = SlidingWindowWorker(
        mic_queue=queue.Queue(),
        mic_vad=_MockVAD(),
        mic_engine=engine,
    )
    w.start()
    time.sleep(0.1)
    w.stop()
    assert engine.stopped


def test_engines_start_on_run():
    """Los engines se inician cuando el worker arranca."""
    engine = _MockStreamEngine()
    w = SlidingWindowWorker(
        mic_queue=queue.Queue(),
        mic_vad=_MockVAD(),
        mic_engine=engine,
    )
    w.start()
    time.sleep(0.2)
    w._running = False
    w.wait(2000)
    assert engine.started


def test_vad_activity_emite_source_name():
    """vad_activity debe emitir el source_name, no solo bool."""
    mic_q = queue.Queue()
    vad_signals = []

    w = SlidingWindowWorker(
        mic_queue=mic_q,
        mic_vad=_MockVAD(always_speech=True),
        mic_engine=_MockStreamEngine(),
    )
    w.vad_activity.connect(lambda src, val: vad_signals.append((src, val)))

    mic_q.put(_make_chunk())
    w._drain_queue(w._mic)

    assert len(vad_signals) > 0
    src, val = vad_signals[0]
    assert src == "mic"
    assert isinstance(val, bool)
