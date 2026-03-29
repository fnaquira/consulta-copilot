# -*- coding: utf-8 -*-
"""
SlidingWindowWorker — Algoritmo de confirmacion por solapamiento.

Soporta una o dos fuentes de audio (microfono + sistema).
Cada fuente tiene su propio buffer acumulativo, VAD y ciclo de transcripcion.
Las signals emiten (source_label, text) para identificar el hablante.

Backwards-compatible: si system_queue y system_vad son None, el worker
se comporta exactamente igual que antes (solo microfono).

Algoritmo de overlap:
  1. Audio se acumula en buffer sin recortar (hasta max_buffer_seconds)
  2. Cada transcribe_interval segundos, se transcribe una ventana de los
     ultimos window_duration segundos del buffer
  3. Se compara con la transcripcion anterior usando SequenceMatcher
  4. Palabras del inicio de prev que ya no aparecen en curr se confirman
     (su audio "salio" de la ventana y fueron validadas por el solapamiento)
  5. Buffer se recorta solo despues de confirmar texto

NOTA: faster-whisper NO es thread-safe; ambos streams corren en el
MISMO QThread procesados secuencialmente.
"""

import queue
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import numpy as np
from PySide6.QtCore import QThread, Signal


# ------------------------------------------------------------------ #
# Patrones de alucinacion conocidos de Whisper
# ------------------------------------------------------------------ #
HALLUCINATION_PATTERNS = [
    "gracias por ver",
    "thanks for watching",
    "thank you",
    "subtitulos",
    "subtitulado por",
    "suscribete",
    "gracias por su atencion",
    "muchas gracias",
]


# ------------------------------------------------------------------ #
# Estado de una fuente de audio individual
# ------------------------------------------------------------------ #
@dataclass
class _AudioStream:
    """Encapsula todo el estado de una fuente (mic o sistema)."""
    name: str           # "mic" o "system"
    label: str          # "Tu" o "Reunion"
    audio_queue: queue.Queue
    vad: object         # VoiceActivityDetector

    # Parametros configurables
    window_duration: float = 15.0       # ventana de transcripcion (segundos)
    transcribe_interval: float = 3.0    # intervalo minimo entre transcripciones
    max_buffer_seconds: float = 60.0    # tope de seguridad del buffer
    sample_rate: int = 16000

    # Estado mutable — buffer acumulativo
    accumulating_buffer: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.float32)
    )
    confirmed_text: str = ""
    last_transcribe_time: float = 0.0
    has_speech: bool = False
    last_vad_state: bool | None = None

    # Historial de transcripciones para comparacion overlap
    prev_transcription: list[str] | None = None

    @property
    def window_samples(self) -> int:
        return int(self.window_duration * self.sample_rate)

    @property
    def max_buffer_samples(self) -> int:
        return int(self.max_buffer_seconds * self.sample_rate)


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

        # Parametros desde config
        window_dur   = getattr(config, "window_duration",     15.0) if config else 15.0
        interval     = getattr(config, "transcribe_interval",  3.0) if config else 3.0
        max_buf_sec  = getattr(config, "max_buffer_seconds",  60.0) if config else 60.0
        halluc_filt  = getattr(config, "hallucination_filter", True) if config else True

        mic_label    = getattr(config, "mic_label",    "Tu")      if config else "Tu"
        system_label = getattr(config, "system_label", "Reunion") if config else "Reunion"

        self._hallucination_filter = halluc_filt

        # Fuente principal: microfono
        self._mic = _AudioStream(
            name="mic",
            label=mic_label,
            audio_queue=mic_queue,
            vad=mic_vad,
            window_duration=window_dur,
            transcribe_interval=interval,
            max_buffer_seconds=max_buf_sec,
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
                max_buffer_seconds=max_buf_sec,
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

                    buf_dur      = len(stream.accumulating_buffer) / stream.sample_rate
                    time_elapsed = now - stream.last_transcribe_time

                    if (
                        buf_dur      >= 1.0
                        and stream.has_speech
                        and time_elapsed >= stream.transcribe_interval
                    ):
                        self._do_transcription(stream)
                        stream.last_transcribe_time = now

                    # Safety cap: si el buffer crece demasiado, forzar confirmacion
                    if len(stream.accumulating_buffer) > stream.max_buffer_samples:
                        self._force_trim(stream)

                if not any_added:
                    time.sleep(0.01)

            except Exception as exc:
                self.error_occurred.emit(str(exc))

    # ------------------------------------------------------------------ #
    # Drenar queue -> VAD -> acumular buffer
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

            stream.accumulating_buffer = np.concatenate(
                [stream.accumulating_buffer, chunk]
            )
            added = True
        return added

    # ------------------------------------------------------------------ #
    # Transcripcion con overlap
    # ------------------------------------------------------------------ #
    def _do_transcription(self, stream: _AudioStream):
        self.status_changed.emit(f"Transcribiendo ({stream.label})...")

        # 1. Tomar ventana de los ultimos window_duration segundos
        audio_window = stream.accumulating_buffer[-stream.window_samples:]

        # 2. Transcribir
        prompt = stream.confirmed_text[-200:] if stream.confirmed_text else ""
        full_text = self.engine.transcribe(audio_window, initial_prompt=prompt)
        curr_words = full_text.strip().split()

        if not curr_words:
            stream.has_speech = False
            self.status_changed.emit("Escuchando...")
            return

        # 3. Filtrar alucinaciones
        if self._hallucination_filter and self._is_hallucination(curr_words):
            stream.has_speech = False
            self.status_changed.emit("Escuchando...")
            return

        # 4. Comparar con transcripcion anterior
        if stream.prev_transcription is not None:
            confirmed, _ = self._compare_transcriptions(
                stream.prev_transcription, curr_words
            )
            if confirmed:
                confirmed_text = " ".join(confirmed)
                stream.confirmed_text += " " + confirmed_text
                self.text_confirmed.emit(stream.label, confirmed_text)

                # Recortar buffer: quitar audio proporcional al texto confirmado
                trim_samples = int(stream.transcribe_interval * stream.sample_rate)
                stream.accumulating_buffer = stream.accumulating_buffer[trim_samples:]

        # 5. Emitir parcial = texto de la transcripcion actual completa
        self.text_partial.emit(stream.label, " ".join(curr_words))

        # 6. Guardar para siguiente comparacion
        stream.prev_transcription = curr_words
        stream.has_speech = False
        self.status_changed.emit("Escuchando...")

    # ------------------------------------------------------------------ #
    # Comparacion de transcripciones solapadas
    # ------------------------------------------------------------------ #
    @staticmethod
    def _compare_transcriptions(
        prev_words: list[str], curr_words: list[str]
    ) -> tuple[list[str], list[str]]:
        """Compara dos transcripciones solapadas.

        Returns:
            (confirmed, stable):
              confirmed = palabras del inicio de prev que ya no estan en curr
                          (su audio salio de la ventana, se confirman)
              stable = palabras que aparecen en ambas (zona de solapamiento)
        """
        if not prev_words:
            return [], []

        matcher = SequenceMatcher(None, prev_words, curr_words, autojunk=False)
        blocks = matcher.get_matching_blocks()

        # Buscar el primer bloque de match significativo
        first_match = None
        for block in blocks:
            if block.size > 0:
                first_match = block
                break

        if first_match is None:
            # Sin solapamiento — confirmar todo lo anterior
            return prev_words, []

        # Palabras antes del primer match en prev = confirmadas
        confirmed = prev_words[:first_match.a]
        stable = prev_words[first_match.a: first_match.a + first_match.size]
        return confirmed, stable

    # ------------------------------------------------------------------ #
    # Filtro de alucinaciones
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_hallucination(words: list[str]) -> bool:
        """Detecta alucinaciones tipicas de Whisper (frases cortas repetitivas)."""
        if len(words) > 5:
            return False
        text = " ".join(words).lower().strip()
        return any(p in text for p in HALLUCINATION_PATTERNS)

    # ------------------------------------------------------------------ #
    # Safety cap: forzar trim cuando buffer crece demasiado
    # ------------------------------------------------------------------ #
    def _force_trim(self, stream: _AudioStream):
        """Fuerza confirmacion y trim cuando el buffer excede max_buffer_seconds."""
        if stream.prev_transcription:
            # Confirmar todo lo que tengamos de la transcripcion previa
            confirmed_text = " ".join(stream.prev_transcription)
            stream.confirmed_text += " " + confirmed_text
            self.text_confirmed.emit(stream.label, confirmed_text)
            stream.prev_transcription = None

        # Recortar a max_buffer_samples
        excess = len(stream.accumulating_buffer) - stream.max_buffer_samples
        if excess > 0:
            stream.accumulating_buffer = stream.accumulating_buffer[excess:]

    # ------------------------------------------------------------------ #
    # Parada + flush
    # ------------------------------------------------------------------ #
    def stop(self):
        self._running = False
        self.wait()

        # Flush: transcribir buffer restante de cada stream y confirmar todo
        for stream in self._streams:
            if len(stream.accumulating_buffer) > self.SAMPLE_RATE * 0.3:
                try:
                    remaining = self.engine.transcribe(stream.accumulating_buffer)
                    if remaining.strip():
                        self.text_confirmed.emit(stream.label, remaining.strip())
                except Exception:
                    pass
