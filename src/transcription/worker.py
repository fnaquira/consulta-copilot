# -*- coding: utf-8 -*-
from PySide6.QtCore import QThread, Signal
import queue
import numpy as np
import time


class SlidingWindowWorker(QThread):
    text_confirmed = Signal(str)     # Texto que ya no cambiará
    text_partial = Signal(str)       # Texto provisional (se sobreescribe)
    vad_activity = Signal(bool)      # Para indicador visual
    status_changed = Signal(str)
    error_occurred = Signal(str)

    WINDOW_DURATION = 5.0            # segundos de buffer
    TRANSCRIBE_INTERVAL = 1.0        # cada cuánto transcribir
    CONFIRM_THRESHOLD = 3.0          # audio más viejo que esto se confirma
    SAMPLE_RATE = 16000

    def __init__(self, audio_queue, engine, vad, config=None):
        super().__init__()
        self.audio_queue = audio_queue
        self.engine = engine
        self.vad = vad
        self._running = False

        if config:
            self.WINDOW_DURATION = config.window_duration
            self.TRANSCRIBE_INTERVAL = config.transcribe_interval
            self.CONFIRM_THRESHOLD = config.confirm_threshold

        # Buffer circular
        self._audio_buffer = np.array([], dtype=np.float32)
        self._buffer_max_samples = int(self.WINDOW_DURATION * self.SAMPLE_RATE)
        self._confirm_samples = int(self.CONFIRM_THRESHOLD * self.SAMPLE_RATE)

        # Contexto para Whisper
        self._confirmed_text = ""
        self._last_transcribe_time = 0
        self._has_speech = False

    def run(self):
        self._running = True
        self.status_changed.emit("Escuchando...")

        while self._running:
            try:
                # 1. Drenar la queue de audio al buffer
                chunks_added = self._drain_queue()

                # 2. Si hay suficiente audio y pasó el intervalo → transcribir
                now = time.monotonic()
                buffer_duration = len(self._audio_buffer) / self.SAMPLE_RATE

                if (
                    buffer_duration > 0.5
                    and self._has_speech
                    and now - self._last_transcribe_time >= self.TRANSCRIBE_INTERVAL
                ):
                    self._do_transcription()
                    self._last_transcribe_time = now

                # 3. Trim buffer si excede ventana
                if len(self._audio_buffer) > self._buffer_max_samples:
                    overflow = len(self._audio_buffer) - self._buffer_max_samples
                    self._audio_buffer = self._audio_buffer[overflow:]

                # Pequeño sleep para no spinear CPU
                if not chunks_added:
                    time.sleep(0.01)

            except Exception as e:
                self.error_occurred.emit(str(e))

    def _drain_queue(self) -> bool:
        """Saca todos los chunks disponibles de la queue y los agrega al buffer."""
        added = False
        while True:
            try:
                chunk = self.audio_queue.get_nowait()
                # VAD check en cada chunk
                is_speech = self.vad.is_speech(chunk)
                self.vad_activity.emit(is_speech)
                if is_speech:
                    self._has_speech = True

                self._audio_buffer = np.concatenate([self._audio_buffer, chunk])
                added = True
            except queue.Empty:
                break
        return added

    def _do_transcription(self):
        """Transcribe el buffer completo y emite parcial/confirmado."""
        self.status_changed.emit("Transcribiendo...")

        prompt = self._confirmed_text[-200:] if self._confirmed_text else ""
        full_text = self.engine.transcribe(self._audio_buffer, initial_prompt=prompt)

        if not full_text.strip():
            self.status_changed.emit("Escuchando...")
            return

        buffer_duration = len(self._audio_buffer) / self.SAMPLE_RATE

        if buffer_duration > self.CONFIRM_THRESHOLD:
            confirm_ratio = self.CONFIRM_THRESHOLD / buffer_duration
            words = full_text.split()
            confirm_idx = max(1, int(len(words) * confirm_ratio))

            confirmed_part = " ".join(words[:confirm_idx])
            partial_part = " ".join(words[confirm_idx:])

            if confirmed_part:
                self._confirmed_text += " " + confirmed_part
                self.text_confirmed.emit(confirmed_part)

            self.text_partial.emit(partial_part)
        else:
            # Buffer corto → todo es parcial
            self.text_partial.emit(full_text)

        self._has_speech = False
        self.status_changed.emit("Escuchando...")

    def stop(self):
        self._running = False
        self.wait()
        # Flush: si queda audio en buffer, transcribir una última vez
        if len(self._audio_buffer) > self.SAMPLE_RATE * 0.3:
            try:
                remaining = self.engine.transcribe(self._audio_buffer)
                if remaining.strip():
                    self.text_confirmed.emit(remaining.strip())
            except Exception:
                pass
