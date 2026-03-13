# -*- coding: utf-8 -*-
"""
SystemAudioCapture — Captura audio del sistema (loopback) según plataforma.

Windows : PyAudioWPatch + WASAPI loopback (pip install PyAudioWPatch)
Linux   : sounddevice + dispositivos "Monitor of ..." de PulseAudio/PipeWire
macOS   : ScreenCaptureKit (nativo, macOS 13+) o dispositivo virtual (BlackHole)

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
        self._process = None          # subprocess de ScreenCaptureKit
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

    # Nombres conocidos de dispositivos virtuales de audio en macOS
    _VIRTUAL_KEYWORDS = (
        "blackhole", "soundflower", "loopback", "virtual",
        "teams audio", "loom", "obs", "screencapture",
    )

    def _list_manual_devices(self) -> list[dict]:
        """Para macOS: ScreenCaptureKit (nativo) + dispositivos virtuales como fallback."""
        devices = []

        # ScreenCaptureKit (macOS 13+, captura nativa sin dispositivo virtual)
        try:
            source = self._helper_source_path()
            if source.exists():
                devices.append({
                    "index": -1,
                    "name": "Audio del sistema (nativo)",
                    "sample_rate": 48000,
                    "channels": 1,
                    "backend": "screencapturekit",
                })
        except Exception:
            pass

        # Dispositivos virtuales (BlackHole, etc.) como alternativa
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] <= 0:
                    continue
                name_lower = d["name"].lower()
                if any(kw in name_lower for kw in self._VIRTUAL_KEYWORDS):
                    devices.append({
                        "index": i,
                        "name": d["name"],
                        "sample_rate": int(d["default_samplerate"]),
                        "channels": d["max_input_channels"],
                        "backend": "sounddevice",
                        "virtual": True,
                    })
        except Exception as e:
            logger.error("Error listando dispositivos de audio: %s", e)

        if not devices:
            logger.warning(
                "No se encontraron opciones de captura de audio del sistema en macOS."
            )
        return devices

    # ------------------------------------------------------------------ #
    # ScreenCaptureKit helper (macOS)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _helper_source_path():
        from pathlib import Path
        return Path(__file__).parent / "screencapture_audio.swift"

    @staticmethod
    def _helper_binary_path():
        from pathlib import Path
        return Path(__file__).parent / "bin" / "screencapture_audio"

    def _ensure_helper_compiled(self):
        """Compila el helper Swift si no existe o está desactualizado."""
        import subprocess as sp
        binary = self._helper_binary_path()
        source = self._helper_source_path()

        if not source.exists():
            raise FileNotFoundError(f"Fuente Swift no encontrada: {source}")

        # Recompilar solo si el binario no existe o es más viejo que el source
        if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
            return binary

        binary.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Compilando helper ScreenCaptureKit...")
        result = sp.run(
            [
                "swiftc", "-O", "-o", str(binary), str(source),
                "-framework", "ScreenCaptureKit",
                "-framework", "CoreMedia",
                "-framework", "Foundation",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Error compilando helper Swift:\n{result.stderr}"
            )
        binary.chmod(0o755)
        logger.info("Helper compilado: %s", binary)
        return binary

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
        elif device_info.get("backend") == "screencapturekit":
            self._start_screencapturekit()
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
                from math import gcd
                from scipy.signal import resample_poly
                # resample_poly usa up/down enteros para mejor calidad
                g = gcd(self.config.target_sample_rate, native_rate)
                self._resample_up = self.config.target_sample_rate // g
                self._resample_down = native_rate // g
                self._resample_poly = resample_poly
                logger.info(
                    "Resampleo activo: %d Hz → %d Hz (up=%d, down=%d)",
                    native_rate, self.config.target_sample_rate,
                    self._resample_up, self._resample_down,
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
                audio = self._resample_poly(
                    audio, self._resample_up, self._resample_down
                ).astype(np.float32)

            # Acumular y emitir chunks de exactamente 512 samples
            combined = np.concatenate([self._leftover, audio])
            while len(combined) >= self.config.chunk_samples:
                chunk = combined[: self.config.chunk_samples]
                combined = combined[self.config.chunk_samples:]
                if self.audio_queue.full():
                    try:
                        self.audio_queue.get_nowait()
                        logger.debug("[SystemAudioCapture] Cola llena — chunk descartado")
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

    def _start_screencapturekit(self):
        """Backend macOS con ScreenCaptureKit (sin dispositivo virtual)."""
        import subprocess as sp
        import threading

        binary = self._ensure_helper_compiled()
        self._leftover = np.array([], dtype=np.float32)
        self._raw_leftover = np.array([], dtype=np.float32)

        self._process = sp.Popen(
            [str(binary)],
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            bufsize=0,
        )

        # Preparar resampleo 48kHz → 16kHz (ratio exacto 1:3)
        from scipy.signal import resample_poly
        self._resample_poly_fn = resample_poly
        _DOWNSAMPLE = 3  # 48000 / 16000

        ready_event = threading.Event()
        error_msg = [None]

        # Leer stderr: READY o ERROR
        def _stderr_reader():
            for raw_line in self._process.stderr:
                msg = raw_line.decode("utf-8", errors="replace").strip()
                if not msg:
                    continue
                if msg == "READY":
                    ready_event.set()
                    logger.info("[ScreenCaptureKit] Captura iniciada")
                elif msg.startswith("ERROR:"):
                    error_msg[0] = msg
                    ready_event.set()
                    logger.error("[ScreenCaptureKit] %s", msg)
                else:
                    logger.info("[ScreenCaptureKit] %s", msg)

        # Leer stdout: audio PCM float32 mono 48kHz → resamplear → cola
        def _audio_reader():
            READ_SIZE = 4800 * 4  # 100ms de audio a 48kHz, float32
            while self._process and self._process.poll() is None:
                data = self._process.stdout.read(READ_SIZE)
                if not data:
                    break

                audio = np.frombuffer(data, dtype=np.float32).copy()
                combined = np.concatenate([self._raw_leftover, audio])

                # Procesar en múltiplos de DOWNSAMPLE para resampleo exacto
                usable = len(combined) - (len(combined) % _DOWNSAMPLE)
                if usable == 0:
                    self._raw_leftover = combined
                    continue

                self._raw_leftover = combined[usable:]
                resampled = self._resample_poly_fn(
                    combined[:usable], 1, _DOWNSAMPLE
                ).astype(np.float32)

                # Acumular y emitir chunks de exactamente 512 samples
                chunk_buf = np.concatenate([self._leftover, resampled])
                while len(chunk_buf) >= self.config.chunk_samples:
                    chunk = chunk_buf[: self.config.chunk_samples]
                    chunk_buf = chunk_buf[self.config.chunk_samples :]
                    if self.audio_queue.full():
                        try:
                            self.audio_queue.get_nowait()
                            logger.debug(
                                "[SystemAudioCapture/sck] Cola llena — chunk descartado"
                            )
                        except Exception:
                            pass
                    self.audio_queue.put(chunk)
                self._leftover = chunk_buf

            logger.info("[ScreenCaptureKit] Audio reader terminado")

        self._stderr_thread = threading.Thread(
            target=_stderr_reader, daemon=True
        )
        self._audio_thread = threading.Thread(
            target=_audio_reader, daemon=True
        )
        self._stderr_thread.start()

        # Esperar READY o error (hasta 15s para diálogo de permisos)
        if not ready_event.wait(timeout=15):
            self._process.kill()
            self._process = None
            raise RuntimeError(
                "ScreenCaptureKit: timeout esperando inicio de captura. "
                "Verifica que la app tenga permiso de 'Grabación de pantalla' "
                "en Ajustes del Sistema → Privacidad y seguridad."
            )

        if error_msg[0]:
            self._process.kill()
            self._process = None
            raise RuntimeError(f"ScreenCaptureKit: {error_msg[0]}")

        # Todo OK — iniciar reader de audio
        self._audio_thread.start()
        logger.info("SystemAudioCapture (ScreenCaptureKit) iniciado")

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
                        logger.debug("[SystemAudioCapture] Cola llena — chunk descartado")
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
        # ScreenCaptureKit subprocess
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            self._leftover = np.array([], dtype=np.float32)
            self._raw_leftover = np.array([], dtype=np.float32)
            logger.info("SystemAudioCapture (ScreenCaptureKit) detenido")
            return

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
