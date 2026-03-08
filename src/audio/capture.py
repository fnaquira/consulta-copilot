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

    _chunk_count = 0  # contador de clase para prints de debug (Fase 2)

    def start(self, device_index: int | None = None):
        AudioCapture._chunk_count = 0

        def callback(indata, frames, time_info, status):
            if status:
                print(f"[AudioCapture] {status}")
            chunk = indata.copy().flatten()
            # Debug Fase 2: imprimir cada ~30 chunks (~1 seg)
            AudioCapture._chunk_count += 1
            if AudioCapture._chunk_count % 30 == 0:
                rms = float((chunk ** 2).mean() ** 0.5)
                print(f"[AudioCapture] chunk #{AudioCapture._chunk_count} | "
                      f"samples={len(chunk)} | rms={rms:.5f}")
            if self.audio_queue.full():
                try:
                    self.audio_queue.get_nowait()  # descartar chunk más antiguo
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

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
