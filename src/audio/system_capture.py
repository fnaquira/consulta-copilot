# -*- coding: utf-8 -*-
"""
SystemAudioCapture — Captura audio del sistema (loopback) según plataforma.

Windows : PyAudioWPatch + WASAPI loopback (pip install PyAudioWPatch)
Linux   : sounddevice + dispositivos "Monitor of ..." de PulseAudio/PipeWire
macOS   : sin auto-detect; requiere BlackHole u otro dispositivo virtual;
          se listan todos los inputs para selección manual.

La interfaz pública es idéntica a AudioCapture:
    list_loopback_devices() → list[dict]
    start(device_index)
    stop()

Los chunks se colocan en audio_queue como np.ndarray float32 de exactamente
chunk_samples (512) samples a target_sample_rate (16000 Hz), mono.
"""

import logging
import platform
import queue
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SystemAudioConfig:
    target_sample_rate: int = 16000   # Lo que Whisper/VAD necesitan
    chunk_samples: int = 512          # Lo que Silero VAD necesita (30ms @16kHz)
    channels: int = 1
    dtype: str = "float32"


class SystemAudioCapture:
    """Captura audio del sistema (lo que suena por los parlantes)."""

    def __init__(self, config: SystemAudioConfig, audio_queue: queue.Queue):
        self.config = config
        self.audio_queue = audio_queue
        self._stream = None
        self._pyaudio = None
        self._resampler = None
        self._leftover = np.array([], dtype=np.float32)

    # ------------------------------------------------------------------ #
    # Listar dispositivos loopback disponibles
    # ------------------------------------------------------------------ #
    def list_loopback_devices(self) -> list[dict]:
        """Retorna dispositivos loopback disponibles según plataforma."""
        system = platform.system()
        if system == "Windows":
            return self._list_windows_loopback()
        elif system == "Linux":
            return self._list_linux_monitors()
        else:
            return self._list_manual_devices()

    def _list_windows_loopback(self) -> list[dict]:
        """Usa PyAudioWPatch para encontrar dispositivos WASAPI loopback."""
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            devices = []

            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev.get("isLoopbackDevice", False):
                    devices.append({
                        "index": i,
                        "name": dev["name"],
                        "sample_rate": int(dev["defaultSampleRate"]),
                        "channels": min(int(dev["maxInputChannels"]), 2),
                        "backend": "pyaudiowpatch",
                    })

            p.terminate()
            return devices
        except ImportError:
            logger.warning(
                "PyAudioWPatch no instalado. "
                "Instala con: pip install PyAudioWPatch"
            )
            return []
        except Exception as e:
            logger.error("Error listando dispositivos WASAPI loopback: %s", e)
            return []

    def _list_linux_monitors(self) -> list[dict]:
        """Busca dispositivos 'Monitor of ...' en PulseAudio/PipeWire."""
        try:
            import sounddevice as sd
            devices = []
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and "monitor" in d["name"].lower():
                    devices.append({
                        "index": i,
                        "name": d["name"],
                        "sample_rate": int(d["default_samplerate"]),
                        "channels": d["max_input_channels"],
                        "backend": "sounddevice",
                    })
            return devices
        except Exception as e:
            logger.error("Error listando dispositivos monitor Linux: %s", e)
            return []

    def _list_manual_devices(self) -> list[dict]:
        """Para macOS u otros: listar todos los inputs para selección manual.

        En macOS se recomienda instalar BlackHole (https://existential.audio/blackhole/)
        y configurarlo como salida de audio del sistema + entrada aquí.
        """
        try:
            import sounddevice as sd
            return [
                {
                    "index": i,
                    "name": d["name"],
                    "sample_rate": int(d["default_samplerate"]),
                    "channels": d["max_input_channels"],
                    "backend": "sounddevice",
                }
                for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0
            ]
        except Exception as e:
            logger.error("Error listando dispositivos de audio: %s", e)
            return []

    # ------------------------------------------------------------------ #
    # Iniciar captura
    # ------------------------------------------------------------------ #
    def start(self, device_index: int | None = None):
        """Inicia captura del dispositivo loopback.

        Si device_index es None, intenta auto-detectar el primer loopback
        disponible en la plataforma.
        """
        devices = self.list_loopback_devices()

        if device_index is None and devices:
            device_index = devices[0]["index"]
            logger.info(
                "Auto-detectado dispositivo loopback: [%s] %s",
                device_index, devices[0]["name"]
            )

        device_info = next(
            (d for d in devices if d["index"] == device_index), None
        )

        if device_info is None:
            # Si no encontramos en la lista de loopback, intentar como sounddevice genérico
            logger.warning(
                "Dispositivo %s no encontrado en lista loopback; "
                "intentando con sounddevice genérico.",
                device_index
            )
            self._start_sounddevice(device_index)
            return

        if device_info.get("backend") == "pyaudiowpatch":
            self._start_pyaudiowpatch(device_index, device_info)
        else:
            self._start_sounddevice(device_index)

    def _start_pyaudiowpatch(self, device_index: int, device_info: dict):
        """Backend Windows con PyAudioWPatch (WASAPI loopback)."""
        import pyaudiowpatch as pyaudio

        native_rate = device_info["sample_rate"]
        native_channels = device_info["channels"]
        needs_resample = native_rate != self.config.target_sample_rate

        # Resampleo usando scipy si es necesario (nativo ≠ 16kHz)
        if needs_resample:
            try:
                from scipy.signal import resample as scipy_resample
                ratio = self.config.target_sample_rate / native_rate
                self._resample_ratio = ratio
                self._scipy_resample = scipy_resample
                logger.info(
                    "Resampleo activo: %d Hz → %d Hz (ratio %.4f)",
                    native_rate, self.config.target_sample_rate, ratio
                )
            except ImportError:
                logger.error(
                    "scipy no instalado. Necesario para resamplear audio del sistema. "
                    "Instala con: pip install scipy"
                )
                raise

        self._pyaudio = pyaudio.PyAudio()
        self._leftover = np.array([], dtype=np.float32)

        # blocksize nativo para que tras resampleo tengamos ~512 samples
        if needs_resample:
            native_blocksize = int(
                self.config.chunk_samples / (self.config.target_sample_rate / native_rate)
            )
        else:
            native_blocksize = self.config.chunk_samples

        def callback(in_data, frame_count, time_info, status):
            if status:
                logger.warning("[SystemAudioCapture/win] %s", status)

            audio = np.frombuffer(in_data, dtype=np.float32).copy()

            # Mezclar a mono si es estéreo
            if native_channels > 1:
                audio = audio.reshape(-1, native_channels).mean(axis=1)

            # Resamplear a 16kHz si necesario
            if needs_resample:
                out_len = int(len(audio) * self._resample_ratio)
                audio = self._scipy_resample(audio, out_len).astype(np.float32)

            # Acumular y emitir chunks de exactamente 512 samples
            combined = np.concatenate([self._leftover, audio])
            while len(combined) >= self.config.chunk_samples:
                chunk = combined[: self.config.chunk_samples]
                combined = combined[self.config.chunk_samples:]
                if self.audio_queue.full():
                    try:
                        self.audio_queue.get_nowait()
                    except Exception:
                        pass
                self.audio_queue.put(chunk)
            self._leftover = combined

            return (None, pyaudio.paContinue)

        self._stream = self._pyaudio.open(
            format=pyaudio.paFloat32,
            channels=native_channels,
            rate=native_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=native_blocksize,
            stream_callback=callback,
        )
        self._stream.start_stream()
        logger.info(
            "SystemAudioCapture (WASAPI loopback) iniciado — dispositivo: %s, "
            "rate nativo: %d Hz, resampleo: %s",
            device_index, native_rate, needs_resample
        )

    def _start_sounddevice(self, device_index: int | None):
        """Backend Linux/macOS con sounddevice."""
        import sounddevice as sd

        self._leftover = np.array([], dtype=np.float32)

        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("[SystemAudioCapture/sd] %s", status)

            audio = indata.copy().flatten()

            # Acumular y emitir chunks de exactamente 512 samples
            combined = np.concatenate([self._leftover, audio])
            while len(combined) >= self.config.chunk_samples:
                chunk = combined[: self.config.chunk_samples]
                combined = combined[self.config.chunk_samples:]
                if self.audio_queue.full():
                    try:
                        self.audio_queue.get_nowait()
                    except Exception:
                        pass
                self.audio_queue.put(chunk)
            self._leftover = combined

        self._stream = sd.InputStream(
            samplerate=self.config.target_sample_rate,
            channels=self.config.channels,
            dtype=self.config.dtype,
            blocksize=self.config.chunk_samples,
            device=device_index,
            callback=callback,
        )
        self._stream.start()
        logger.info(
            "SystemAudioCapture (sounddevice) iniciado — dispositivo: %s", device_index
        )

    # ------------------------------------------------------------------ #
    # Detener captura
    # ------------------------------------------------------------------ #
    def stop(self):
        if self._stream is None:
            return

        if hasattr(self._stream, "stop_stream"):
            # PyAudioWPatch stream
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                logger.warning("Error deteniendo stream PyAudioWPatch: %s", e)
            if self._pyaudio:
                try:
                    self._pyaudio.terminate()
                except Exception:
                    pass
                self._pyaudio = None
        else:
            # sounddevice stream
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning("Error deteniendo stream sounddevice: %s", e)

        self._stream = None
        self._resampler = None
        self._leftover = np.array([], dtype=np.float32)
        logger.info("SystemAudioCapture detenido")
