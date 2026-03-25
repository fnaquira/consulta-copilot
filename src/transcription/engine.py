# -*- coding: utf-8 -*-
import io
import sys
from faster_whisper import WhisperModel
import numpy as np

AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]


class TranscriptionEngine:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "es",
        beam_size: int = 1,
    ):
        self.beam_size = beam_size
        self.language = language
        # WhisperModel descarga el modelo y escribe en stdout/stderr.
        # En modo --windowed (sin consola) estos son None → AttributeError.
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

    def transcribe(self, audio: np.ndarray, initial_prompt: str = "") -> str:
        """Transcribe audio float32 a 16kHz. Retorna texto."""
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,         # VAD externo con Silero
            initial_prompt=initial_prompt or None,
            no_speech_threshold=0.35,
            condition_on_previous_text=False,  # Nosotros manejamos el contexto
        )
        return " ".join(seg.text.strip() for seg in segments)
