# -*- coding: utf-8 -*-
"""
Motor de transcripcion con soporte hibrido: local (faster-whisper) o cloud (Groq API).

Providers:
  - LocalWhisperProvider: faster-whisper local. Ideal con GPU.
  - GroqWhisperProvider: Groq API cloud (whisper-large-v3-turbo). Ideal sin GPU.
  - TranscriptionEngine: wrapper backwards-compatible que usa LocalWhisperProvider.
"""

import io
import logging
import sys
import wave
from typing import Protocol, runtime_checkable

import numpy as np

log = logging.getLogger(__name__)

AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]


# ------------------------------------------------------------------ #
# Protocol comun
# ------------------------------------------------------------------ #
@runtime_checkable
class TranscriptionProvider(Protocol):
    """Interfaz comun para cualquier motor de transcripcion."""

    def transcribe(self, audio: np.ndarray, initial_prompt: str = "") -> str: ...


# ------------------------------------------------------------------ #
# Provider local: faster-whisper
# ------------------------------------------------------------------ #
class LocalWhisperProvider:
    """faster-whisper local. Ideal con GPU, funcional en CPU con modelos pequenos."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "es",
        beam_size: int = 5,
        no_speech_threshold: float = 0.35,
        temperature: float = 0.0,
    ):
        from faster_whisper import WhisperModel

        self.language = language
        self.beam_size = beam_size
        self.no_speech_threshold = no_speech_threshold
        self.temperature = temperature

        # WhisperModel descarga el modelo y escribe en stdout/stderr.
        # En modo --windowed (sin consola) estos son None -> AttributeError.
        _stdout_bak = sys.stdout
        _stderr_bak = sys.stderr
        if sys.stdout is None:
            sys.stdout = io.StringIO()
        if sys.stderr is None:
            sys.stderr = io.StringIO()
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        finally:
            sys.stdout = _stdout_bak
            sys.stderr = _stderr_bak

        log.info("LocalWhisperProvider listo: model=%s device=%s compute=%s",
                 model_size, device, compute_type)

    def transcribe(self, audio: np.ndarray, initial_prompt: str = "") -> str:
        """Transcribe audio float32 a 16kHz. Retorna texto."""
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,
            initial_prompt=initial_prompt or None,
            no_speech_threshold=self.no_speech_threshold,
            temperature=self.temperature,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments)


# ------------------------------------------------------------------ #
# Provider cloud: Groq API
# ------------------------------------------------------------------ #
class GroqWhisperProvider:
    """Groq API cloud (whisper-large-v3-turbo). Ideal sin GPU.

    Usa el paquete `openai` (ya instalado) con base_url de Groq.
    Free tier: ~7000 audio-sec/dia (~116 min).
    """

    GROQ_BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "whisper-large-v3-turbo"
    SAMPLE_RATE = 16000

    def __init__(self, api_key: str, language: str = "es"):
        import openai
        self.language = language
        self._client = openai.OpenAI(
            base_url=self.GROQ_BASE_URL,
            api_key=api_key,
        )
        log.info("GroqWhisperProvider listo: model=%s language=%s", self.MODEL, language)

    def transcribe(self, audio: np.ndarray, initial_prompt: str = "") -> str:
        """Transcribe audio float32 a 16kHz via Groq API. Retorna texto."""
        # Convertir numpy float32 -> WAV bytes (PCM16)
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.SAMPLE_RATE)
            pcm16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            wf.writeframes(pcm16.tobytes())
        wav_buf.seek(0)

        resp = self._client.audio.transcriptions.create(
            file=("audio.wav", wav_buf),
            model=self.MODEL,
            language=self.language,
            prompt=initial_prompt or None,
        )
        return resp.text.strip()


# ------------------------------------------------------------------ #
# Wrapper backwards-compatible
# ------------------------------------------------------------------ #
class TranscriptionEngine:
    """Wrapper backwards-compatible que usa LocalWhisperProvider internamente.

    Mantiene la misma interfaz que la version anterior para que ModelLoader
    y otros consumidores no se rompan.
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "es",
        beam_size: int = 5,
        no_speech_threshold: float = 0.35,
        temperature: float = 0.0,
    ):
        self._provider = LocalWhisperProvider(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            language=language,
            beam_size=beam_size,
            no_speech_threshold=no_speech_threshold,
            temperature=temperature,
        )
        self.language = language

    def transcribe(self, audio: np.ndarray, initial_prompt: str = "") -> str:
        return self._provider.transcribe(audio, initial_prompt=initial_prompt)
