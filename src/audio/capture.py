# -*- coding: utf-8 -*-
import sounddevice as sd
import numpy as np
import queue
from dataclasses import dataclass


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
                print(f"[AudioCapture] {status}")
            self.audio_queue.put(indata.copy().flatten())

        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype=self.config.dtype,
            blocksize=self.config.chunk_samples,
            device=device_index,
            callback=callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
