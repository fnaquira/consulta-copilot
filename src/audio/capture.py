# -*- coding: utf-8 -*-
import logging
import queue
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


@dataclass
class AudioConfig:
    sample_rate: int = 16000       # Whisper requiere 16kHz
    chunk_samples: int = 512       # 30ms — requerido por Silero VAD
    channels: int = 1
    dtype: str = "float32"


class AudioCapture:
    """Captura audio del micrófono o dispositivo loopback."""

    def __init__(self, config: AudioConfig, audio_queue: queue.Queue):
        self.config = config
        self.audio_queue = audio_queue
        self._stream = None

    def list_devices(self) -> list[dict]:
        """Retorna dispositivos de entrada disponibles."""
        devices = sd.query_devices()
        return [
            {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]

    def start(self, device_index: int | None = None):
        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("[AudioCapture] %s", status)
            chunk = indata.copy().flatten()
            if self.audio_queue.full():
                try:
                    self.audio_queue.get_nowait()
                except Exception:
                    pass
            self.audio_queue.put(chunk)

        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype=self.config.dtype,
            blocksize=self.config.chunk_samples,
            device=device_index,
            callback=callback,
        )
        self._stream.start()
        logger.info("AudioCapture iniciado — dispositivo: %s", device_index)

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            logger.info("AudioCapture detenido")
