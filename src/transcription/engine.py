# -*- coding: utf-8 -*-
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
    ):
        self.language = language
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, initial_prompt: str = "") -> str:
        """Transcribe audio float32 a 16kHz. Retorna texto."""
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=False,         # VAD externo con Silero
            initial_prompt=initial_prompt or None,
            no_speech_threshold=0.6,
            condition_on_previous_text=False,  # Nosotros manejamos el contexto
        )
        return " ".join(seg.text.strip() for seg in segments)
