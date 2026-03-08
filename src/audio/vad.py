# -*- coding: utf-8 -*-
import numpy as np
import torch
from silero_vad import load_silero_vad


class VoiceActivityDetector:
    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        try:
            self.model = load_silero_vad()
        except Exception as e:
            raise RuntimeError(
                f"No se pudo cargar Silero VAD.\nError: {e}"
            )
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._speech_active = False

    def is_speech(self, chunk_512: np.ndarray) -> bool:
        """Evalúa un chunk de exactamente 512 samples."""
        tensor = torch.from_numpy(chunk_512).float()
        prob = self.model(tensor, self.sample_rate).item()
        self._speech_active = prob >= self.threshold
        return self._speech_active

    def reset(self):
        """Resetear estado interno del modelo."""
        self.model.reset_states()
        self._speech_active = False
