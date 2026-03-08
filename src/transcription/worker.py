# -*- coding: utf-8 -*-
"""
SlidingWindowWorker — Fase 9 (Audio Dual)

Soporta una o dos fuentes de audio (micrófono + sistema).
Cada fuente tiene su propio buffer, VAD y ciclo de transcripción.
Las signals ahora emiten (source_label, text) para identificar el hablante.

Backwards-compatible: si system_queue y system_vad son None, el worker
se comporta exactamente igual que antes (solo micrófono).

Flujo:
  para cada stream en [mic, system]:
    drain_queue → VAD por chunk → buffer rolling (5s máx)
    cada ~1s (si hay voz): transcribir buffer → emit (label, text)

NOTA: faster-whisper NO es thread-safe; ambos streams corren en el
MISMO QThread procesados secuencialmente. Latencia máx ~1.5s en peor caso.
"""

import queue
import time
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QThread, Signal


# ------------------------------------------------------------------ #
# Estado de una fuente de audio individual
# ------------------------------------------------------------------ #
@dataclass
class _AudioStream:
    """Encapsula todo el estado de una fuente (mic o sistema)."""
    name: str           # "mic" o "system"
    label: str          # "Tú" o "Reunión"
    audio_queue: queue.Queue
    vad: object         # VoiceActivityDetector

    # Parámetros configurables (se asignan en __post_init__)
    window_duration: float = 5.0
    transcribe_interval: float = 1.0
    confirm_threshold: float = 3.0
    sample_rate: int = 16000

    # Estado mutable
    audio_buffer: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.float32)
    )
    confirmed_text: str = ""
    last_transcribe_time: float = 0.0
    has_speech: bool = False
    last_vad_state: bool | None = None

    @property
    def buffer_max_samples(self) -> int:
        return int(self.window_duration * self.sample_rate)

    @property
    def confirm_samples(self) -> int:
        return int(self.confirm_threshold * self.sample_rate)


# ------------------------------------------------------------------ #
# Worker principal
# ------------------------------------------------------------------ #
class SlidingWindowWorker(QThread):
    # Signals llevan (source_label, text)
    text_confirmed = Signal(str, str)   # (label, texto confirmado)
    text_partial   = Signal(str, str)   # (label, texto parcial)
    vad_activity   = Signal(str, bool)  # (source_name, is_speech)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    SAMPLE_RATE = 16000

    def __init__(
        self,
        mic_queue: queue.Queue,
        engine,
        mic_vad,
        config=None,
        system_queue: queue.Queue | None = None,
        system_vad=None,
    ):
        super().__init__()
        self.engine   = engine
        self._running = False

        # Parámetros desde config
        window_dur  = getattr(config, "window_duration",    5.0) if config else 5.0
        interval    = getattr(config, "transcribe_interval", 1.0) if config else 1.0
        confirm_thr = getattr(config, "confirm_threshold",   3.0) if config else 3.0

        mic_label    = getattr(config, "mic_label",    "Tú")      if config else "Tú"
        system_label = getattr(config, "system_label", "Reunión") if config else "Reunión"

        # Fuente principal: micrófono
        self._mic = _AudioStream(
            name="mic",
            label=mic_label,
            audio_queue=mic_queue,
            vad=mic_vad,
            window_duration=window_dur,
            transcribe_interval=interval,
            confirm_threshold=confirm_thr,
        )

        # Fuente opcional: audio del sistema
        self._system: _AudioStream | None = None
        if system_queue is not None and system_vad is not None:
            self._system = _AudioStream(
                name="system",
                label=system_label,
                audio_queue=system_queue,
                vad=system_vad,
                window_duration=window_dur,
                transcribe_interval=interval,
                confirm_threshold=confirm_thr,
            )

        self._streams = [s for s in [self._mic, self._system] if s is not None]

    # ------------------------------------------------------------------ #
    # Hilo principal
    # ------------------------------------------------------------------ #
    def run(self):
        self._running = True
        self.status_changed.emit("Escuchando...")

        while self._running:
            try:
                any_added = False
                now = time.monotonic()

                for stream in self._streams:
                    added = self._drain_queue(stream)
                    any_added = any_added or added

                    buf_dur      = len(stream.audio_buffer) / stream.sample_rate
                    time_elapsed = now - stream.last_transcribe_time

                    if (
                        buf_dur      >= 0.5
                        and stream.has_speech
                        and time_elapsed >= stream.transcribe_interval
                    ):
                        self._do_transcription(stream)
                        stream.last_transcribe_time = now

                    # Trim buffer
                    if len(stream.audio_buffer) > stream.buffer_max_samples:
                        excess = len(stream.audio_buffer) - stream.buffer_max_samples
                        stream.audio_buffer = stream.audio_buffer[excess:]

                if not any_added:
                    time.sleep(0.01)

            except Exception as exc:
                self.error_occurred.emit(str(exc))

    # ------------------------------------------------------------------ #
    # Drenar queue → VAD → acumular buffer
    # ------------------------------------------------------------------ #
    def _drain_queue(self, stream: _AudioStream) -> bool:
        added = False
        while True:
            try:
                chunk = stream.audio_queue.get_nowait()
            except queue.Empty:
                break

            is_speech = stream.vad.is_speech(chunk)

            # Emitir VAD solo cuando cambia el estado
            if is_speech != stream.last_vad_state:
                self.vad_activity.emit(stream.name, is_speech)
                stream.last_vad_state = is_speech

            if is_speech:
                stream.has_speech = True

            stream.audio_buffer = np.concatenate([stream.audio_buffer, chunk])
            added = True
        return added

    # ------------------------------------------------------------------ #
    # Transcripción del buffer de un stream
    # ------------------------------------------------------------------ #
    def _do_transcription(self, stream: _AudioStream):
        self.status_changed.emit(f"Transcribiendo ({stream.label})...")

        prompt    = stream.confirmed_text[-200:] if stream.confirmed_text else ""
        full_text = self.engine.transcribe(stream.audio_buffer, initial_prompt=prompt)

        if not full_text.strip():
            stream.has_speech = False
            self.status_changed.emit("Escuchando...")
            return

        buf_dur = len(stream.audio_buffer) / stream.sample_rate

        if buf_dur > stream.confirm_threshold:
            ratio       = stream.confirm_threshold / buf_dur
            words       = full_text.split()
            confirm_idx = max(1, int(len(words) * ratio))

            confirmed = " ".join(words[:confirm_idx])
            partial   = " ".join(words[confirm_idx:])

            if confirmed:
                stream.confirmed_text += " " + confirmed
                self.text_confirmed.emit(stream.label, confirmed)
            self.text_partial.emit(stream.label, partial)
        else:
            self.text_partial.emit(stream.label, full_text)

        stream.has_speech = False
        self.status_changed.emit("Escuchando...")

    # ------------------------------------------------------------------ #
    # Parada + flush
    # ------------------------------------------------------------------ #
    def stop(self):
        self._running = False
        self.wait()

        # Flush del buffer del micrófono (comportamiento original)
        mic = self._mic
        if len(mic.audio_buffer) > self.SAMPLE_RATE * 0.3:
            try:
                remaining = self.engine.transcribe(mic.audio_buffer)
                if remaining.strip():
                    self.text_confirmed.emit(mic.label, remaining.strip())
            except Exception:
                pass

        # Flush del buffer del sistema (si existe)
        if self._system and len(self._system.audio_buffer) > self.SAMPLE_RATE * 0.3:
            try:
                remaining = self.engine.transcribe(self._system.audio_buffer)
                if remaining.strip():
                    self.text_confirmed.emit(self._system.label, remaining.strip())
            except Exception:
                pass
