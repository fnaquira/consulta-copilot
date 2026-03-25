# -*- coding: utf-8 -*-
"""
LocalStreamEngine — Adapter que envuelve TranscriptionEngine (faster-whisper)
en la interfaz StreamingTranscriptionEngine usando un buffer circular y un
hilo interno de transcripción periódica.
"""

import logging
import threading
import time

import numpy as np

from src.transcription.streaming_engine import StreamingTranscriptionEngine

logger = logging.getLogger(__name__)


class LocalStreamEngine(StreamingTranscriptionEngine):
    """Motor local que acumula audio y transcribe periódicamente."""

    def __init__(
        self,
        engine,
        window_duration: float = 5.0,
        transcribe_interval: float = 0.8,
        confirm_threshold: float = 2.0,
        sample_rate: int = 16000,
    ):
        self._engine = engine
        self._sample_rate = sample_rate
        self._window_samples = int(window_duration * sample_rate)
        self._interval = transcribe_interval
        self._confirm_threshold = confirm_threshold

        # Buffer circular pre-allocated
        self._buffer = np.zeros(self._window_samples, dtype=np.float32)
        self._write_pos = 0  # Posición de escritura en el buffer
        self._buf_len = 0    # Cantidad de muestras válidas en el buffer

        self._confirmed_text = ""
        self._has_speech = False
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._transcription_loop, daemon=True)
        self._thread.start()

    def send_audio(self, chunk: np.ndarray) -> None:
        """Acumula audio en el buffer circular (thread-safe)."""
        with self._lock:
            n = len(chunk)
            if n >= self._window_samples:
                # Chunk más grande que el buffer: tomar los últimos window_samples
                self._buffer[:] = chunk[-self._window_samples:]
                self._write_pos = 0
                self._buf_len = self._window_samples
                return

            # Espacio restante hasta el final del buffer
            space = self._window_samples - self._write_pos
            if n <= space:
                self._buffer[self._write_pos:self._write_pos + n] = chunk
            else:
                self._buffer[self._write_pos:] = chunk[:space]
                self._buffer[:n - space] = chunk[space:]
            self._write_pos = (self._write_pos + n) % self._window_samples
            self._buf_len = min(self._buf_len + n, self._window_samples)

    def set_has_speech(self, val: bool) -> None:
        """Llamado por el worker cuando VAD detecta voz."""
        if val:
            self._has_speech = True

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        # Flush final
        self._do_transcribe(flush=True)

    def _get_buffer_audio(self) -> np.ndarray:
        """Retorna una copia linealizada del buffer circular."""
        with self._lock:
            if self._buf_len == 0:
                return np.array([], dtype=np.float32)
            if self._buf_len < self._window_samples:
                # Buffer aún no lleno: datos van de 0 a write_pos
                start = self._write_pos - self._buf_len
                if start >= 0:
                    return self._buffer[start:self._write_pos].copy()
                else:
                    return np.concatenate([
                        self._buffer[start % self._window_samples:],
                        self._buffer[:self._write_pos],
                    ])
            else:
                # Buffer lleno: linealizar desde write_pos
                return np.concatenate([
                    self._buffer[self._write_pos:],
                    self._buffer[:self._write_pos],
                ])

    def _transcription_loop(self) -> None:
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break
            if self._has_speech and self._buf_len >= self._sample_rate * 0.5:
                self._do_transcribe()

    def _do_transcribe(self, flush: bool = False) -> None:
        audio = self._get_buffer_audio()
        if len(audio) < self._sample_rate * 0.3:
            return

        prompt = self._confirmed_text[-200:] if self._confirmed_text else ""
        try:
            full_text = self._engine.transcribe(audio, initial_prompt=prompt)
        except Exception as exc:
            logger.error("Error en transcripción local: %s", exc)
            if self.on_error:
                self.on_error(str(exc))
            return

        if not full_text.strip():
            self._has_speech = False
            return

        buf_dur = len(audio) / self._sample_rate

        if flush or buf_dur <= self._confirm_threshold:
            if flush:
                # En flush final, confirmar todo
                self._confirmed_text += " " + full_text
                if self.on_final:
                    self.on_final(full_text)
            else:
                if self.on_partial:
                    self.on_partial(full_text)
        else:
            ratio = self._confirm_threshold / buf_dur
            words = full_text.split()
            confirm_idx = max(1, int(len(words) * ratio))
            confirmed = " ".join(words[:confirm_idx])
            partial = " ".join(words[confirm_idx:])

            if confirmed:
                self._confirmed_text += " " + confirmed
                if self.on_final:
                    self.on_final(confirmed)
            if partial and self.on_partial:
                self.on_partial(partial)

        self._has_speech = False
