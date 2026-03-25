# -*- coding: utf-8 -*-
"""
Interfaz abstracta para motores de transcripción streaming
+ implementación con Deepgram Nova-2 WebSocket API.
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)


class StreamingTranscriptionEngine(ABC):
    """Interfaz común para motores de transcripción streaming."""

    on_partial: Callable[[str], None] | None = None
    on_final: Callable[[str], None] | None = None
    on_error: Callable[[str], None] | None = None

    @abstractmethod
    def start(self) -> None:
        """Inicia la conexión / hilo de transcripción."""

    @abstractmethod
    def send_audio(self, chunk: np.ndarray) -> None:
        """Envía un chunk float32 16kHz mono al motor."""

    @abstractmethod
    def stop(self) -> None:
        """Cierra la conexión y hace flush del audio pendiente."""


class DeepgramStreamEngine(StreamingTranscriptionEngine):
    """Motor de transcripción streaming via Deepgram Nova-2 WebSocket."""

    def __init__(
        self,
        api_key: str,
        language: str = "es",
        model: str = "nova-2",
        sample_rate: int = 16000,
        endpointing: int = 300,
        encoding: str = "linear16",
    ):
        self._api_key = api_key
        self._language = language
        self._model = model
        self._sample_rate = sample_rate
        self._endpointing = endpointing
        self._encoding = encoding
        self._connection = None
        self._client = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

        self._client = DeepgramClient(self._api_key)
        self._connection = self._client.listen.live.v("1")

        # Registrar callbacks
        self._connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
        self._connection.on(LiveTranscriptionEvents.Error, self._on_dg_error)

        options = LiveOptions(
            model=self._model,
            language=self._language,
            smart_format=True,
            interim_results=True,
            endpointing=self._endpointing,
            encoding=self._encoding,
            sample_rate=self._sample_rate,
            channels=1,
        )

        started = self._connection.start(options)
        if not started:
            raise RuntimeError("No se pudo conectar a Deepgram")
        self._running = True
        logger.info("Deepgram streaming iniciado (model=%s, lang=%s)", self._model, self._language)

    def send_audio(self, chunk: np.ndarray) -> None:
        if not self._running or self._connection is None:
            return
        # Convertir float32 [-1,1] a int16 PCM bytes
        pcm = (chunk * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        try:
            self._connection.send(pcm)
        except Exception as exc:
            logger.warning("Error enviando audio a Deepgram: %s", exc)
            if self.on_error:
                self.on_error(f"Deepgram send error: {exc}")

    def stop(self) -> None:
        self._running = False
        if self._connection is not None:
            try:
                self._connection.finish()
            except Exception:
                pass
            self._connection = None
        self._client = None

    # -- Callbacks internos de Deepgram --

    def _on_transcript(self, _client, result, **_kwargs):
        try:
            alt = result.channel.alternatives[0]
            text = alt.transcript.strip()
            if not text:
                return

            is_final = result.is_final
            if is_final:
                if self.on_final:
                    self.on_final(text)
            else:
                if self.on_partial:
                    self.on_partial(text)
        except Exception as exc:
            logger.warning("Error procesando resultado Deepgram: %s", exc)

    def _on_dg_error(self, _client, error, **_kwargs):
        logger.error("Deepgram error: %s", error)
        if self.on_error:
            self.on_error(str(error))
