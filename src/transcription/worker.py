# -*- coding: utf-8 -*-
"""
SlidingWindowWorker — Arquitectura streaming (Deepgram / Local fallback).

Soporta una o dos fuentes de audio (micrófono + sistema).
Cada fuente tiene su propio motor de transcripción streaming y VAD.

Flujo:
  para cada stream en [mic, system]:
    drain_queue → VAD por chunk (solo para LEDs) → engine.send_audio(chunk)
  El motor streaming (Deepgram o Local) maneja la transcripción asincrónicamente
  y emite callbacks que se traducen a signals de Qt.

NOTA: Con Deepgram, ambos streams son completamente paralelos (cada uno tiene
su propio WebSocket). Con Local, cada stream tiene su propio hilo interno.
"""

import queue
import time
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QThread, Signal

from src.transcription.streaming_engine import StreamingTranscriptionEngine


# ------------------------------------------------------------------ #
# Estado de una fuente de audio individual
# ------------------------------------------------------------------ #
@dataclass
class _AudioStream:
    """Encapsula el estado de una fuente (mic o sistema)."""
    name: str           # "mic" o "system"
    label: str          # "Tú" o "Reunión"
    audio_queue: queue.Queue
    vad: object         # VoiceActivityDetector
    engine: StreamingTranscriptionEngine | None = None

    # Estado VAD (solo para LEDs)
    last_vad_state: bool | None = None


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
        mic_vad,
        config=None,
        system_queue: queue.Queue | None = None,
        system_vad=None,
        mic_engine: StreamingTranscriptionEngine | None = None,
        system_engine: StreamingTranscriptionEngine | None = None,
        # Legacy: mantener compatibilidad con tests que pasan engine posicional
        engine=None,
    ):
        super().__init__()
        self._running = False

        mic_label    = getattr(config, "mic_label",    "Tú")      if config else "Tú"
        system_label = getattr(config, "system_label", "Reunión") if config else "Reunión"

        # Fuente principal: micrófono
        self._mic = _AudioStream(
            name="mic",
            label=mic_label,
            audio_queue=mic_queue,
            vad=mic_vad,
            engine=mic_engine,
        )

        # Fuente opcional: audio del sistema
        self._system: _AudioStream | None = None
        if system_queue is not None and system_vad is not None:
            self._system = _AudioStream(
                name="system",
                label=system_label,
                audio_queue=system_queue,
                vad=system_vad,
                engine=system_engine,
            )

        self._streams = [s for s in [self._mic, self._system] if s is not None]

        # Registrar callbacks en cada engine
        for stream in self._streams:
            if stream.engine is not None:
                self._bind_engine_callbacks(stream)

    def _bind_engine_callbacks(self, stream: _AudioStream) -> None:
        """Conecta callbacks del engine a signals de Qt."""
        def on_final(text, _label=stream.label):
            self.text_confirmed.emit(_label, text)

        def on_partial(text, _label=stream.label):
            self.text_partial.emit(_label, text)

        def on_error(error):
            self.error_occurred.emit(error)

        stream.engine.on_final = on_final
        stream.engine.on_partial = on_partial
        stream.engine.on_error = on_error

    # ------------------------------------------------------------------ #
    # Hilo principal
    # ------------------------------------------------------------------ #
    def run(self):
        self._running = True

        # Iniciar engines
        for stream in self._streams:
            if stream.engine is not None:
                try:
                    stream.engine.start()
                except Exception as exc:
                    self.error_occurred.emit(f"Error iniciando motor ({stream.label}): {exc}")

        self.status_changed.emit("Escuchando...")

        while self._running:
            try:
                any_added = False

                for stream in self._streams:
                    added = self._drain_queue(stream)
                    any_added = any_added or added

                if not any_added:
                    time.sleep(0.01)

            except Exception as exc:
                self.error_occurred.emit(str(exc))

    # ------------------------------------------------------------------ #
    # Drenar queue → VAD (LEDs) → forward a engine
    # ------------------------------------------------------------------ #
    def _drain_queue(self, stream: _AudioStream) -> bool:
        added = False
        while True:
            try:
                chunk = stream.audio_queue.get_nowait()
            except queue.Empty:
                break

            # VAD solo para indicadores LED
            is_speech = stream.vad.is_speech(chunk)
            if is_speech != stream.last_vad_state:
                self.vad_activity.emit(stream.name, is_speech)
                stream.last_vad_state = is_speech

            # Notificar speech al engine local (si aplica)
            if is_speech and hasattr(stream.engine, 'set_has_speech'):
                stream.engine.set_has_speech(True)

            # Forward a streaming engine
            if stream.engine is not None:
                stream.engine.send_audio(chunk)

            added = True
        return added

    # ------------------------------------------------------------------ #
    # Parada + flush
    # ------------------------------------------------------------------ #
    def stop(self):
        self._running = False
        self.wait()

        # Stop engines (hace flush internamente)
        for stream in self._streams:
            if stream.engine is not None:
                try:
                    stream.engine.stop()
                except Exception:
                    pass
