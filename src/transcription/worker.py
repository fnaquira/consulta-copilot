# -*- coding: utf-8 -*-
"""
SlidingWindowWorker — Fases 4 + 5

Flujo:
  queue → _drain_queue() → VAD por chunk → buffer rolling (5 seg máx)
  Cada ~1 seg (si hay voz): transcribir buffer completo
  Dividir resultado en confirmado / parcial
  text_confirmed → append (negro)   text_partial → reemplaza (gris itálica)
"""
import queue
import time
from PySide6.QtCore import QThread, Signal
import numpy as np


class SlidingWindowWorker(QThread):
    text_confirmed = Signal(str)   # Texto inmutable → append
    text_partial   = Signal(str)   # Texto provisional → sobreescribir
    vad_activity   = Signal(bool)  # Para indicador LED
    status_changed = Signal(str)
    error_occurred = Signal(str)

    SAMPLE_RATE = 16000

    def __init__(self, audio_queue: queue.Queue, engine, vad, config=None):
        super().__init__()
        self.audio_queue  = audio_queue
        self.engine       = engine
        self.vad          = vad
        self._running     = False

        # Parámetros (sobreescribibles desde config)
        self._window_dur   = getattr(config, "window_duration",    5.0) if config else 5.0
        self._interval     = getattr(config, "transcribe_interval", 1.0) if config else 1.0
        self._confirm_thr  = getattr(config, "confirm_threshold",   3.0) if config else 3.0

        self._buf_max   = int(self._window_dur  * self.SAMPLE_RATE)
        self._conf_samp = int(self._confirm_thr * self.SAMPLE_RATE)

        self._audio_buffer      : np.ndarray = np.array([], dtype=np.float32)
        self._confirmed_text    : str        = ""
        self._last_transcribe   : float      = 0.0
        self._has_speech        : bool       = False
        self._last_vad_state    : bool | None = None

    # ------------------------------------------------------------------ #
    # Hilo principal
    # ------------------------------------------------------------------ #
    def run(self):
        self._running = True
        self.status_changed.emit("Escuchando...")

        while self._running:
            try:
                added = self._drain_queue()

                now            = time.monotonic()
                buf_dur        = len(self._audio_buffer) / self.SAMPLE_RATE
                time_elapsed   = now - self._last_transcribe

                if (
                    buf_dur       >= 0.5
                    and self._has_speech
                    and time_elapsed >= self._interval
                ):
                    self._do_transcription()
                    self._last_transcribe = now

                # Trim buffer si excede ventana
                if len(self._audio_buffer) > self._buf_max:
                    excess = len(self._audio_buffer) - self._buf_max
                    self._audio_buffer = self._audio_buffer[excess:]

                if not added:
                    time.sleep(0.01)

            except Exception as exc:
                self.error_occurred.emit(str(exc))

    # ------------------------------------------------------------------ #
    # Drenar queue → VAD por chunk → acumular buffer
    # ------------------------------------------------------------------ #
    def _drain_queue(self) -> bool:
        added = False
        while True:
            try:
                chunk = self.audio_queue.get_nowait()
            except queue.Empty:
                break

            is_speech = self.vad.is_speech(chunk)

            # Emitir VAD solo cuando cambia el estado
            if is_speech != self._last_vad_state:
                self.vad_activity.emit(is_speech)
                self._last_vad_state = is_speech

            if is_speech:
                self._has_speech = True

            self._audio_buffer = np.concatenate([self._audio_buffer, chunk])
            added = True
        return added

    # ------------------------------------------------------------------ #
    # Transcripción del buffer completo
    # ------------------------------------------------------------------ #
    def _do_transcription(self):
        self.status_changed.emit("Transcribiendo...")

        prompt    = self._confirmed_text[-200:] if self._confirmed_text else ""
        full_text = self.engine.transcribe(self._audio_buffer, initial_prompt=prompt)

        if not full_text.strip():
            self._has_speech = False
            self.status_changed.emit("Escuchando...")
            return

        buf_dur = len(self._audio_buffer) / self.SAMPLE_RATE

        if buf_dur > self._confirm_thr:
            ratio       = self._confirm_thr / buf_dur
            words       = full_text.split()
            confirm_idx = max(1, int(len(words) * ratio))

            confirmed = " ".join(words[:confirm_idx])
            partial   = " ".join(words[confirm_idx:])

            if confirmed:
                self._confirmed_text += " " + confirmed
                self.text_confirmed.emit(confirmed)
            self.text_partial.emit(partial)
        else:
            self.text_partial.emit(full_text)

        self._has_speech = False
        self.status_changed.emit("Escuchando...")

    # ------------------------------------------------------------------ #
    # Parada + flush
    # ------------------------------------------------------------------ #
    def stop(self):
        self._running = False
        self.wait()
        if len(self._audio_buffer) > self.SAMPLE_RATE * 0.3:
            try:
                remaining = self.engine.transcribe(self._audio_buffer)
                if remaining.strip():
                    self.text_confirmed.emit(remaining.strip())
            except Exception:
                pass
