# -*- coding: utf-8 -*-
import numpy as np
import torch
from silero_vad import load_silero_vad


class VoiceActivityDetector:
    # hangover_chunks: cuántos chunks de 30ms mantener estado "speech"
    # después de que la probabilidad cae debajo del threshold.
    # 10 chunks × 30ms = 300ms de suavizado.
    def __init__(self, threshold: float = 0.3, sample_rate: int = 16000,
                 hangover_chunks: int = 10):
        try:
            self.model = load_silero_vad()
        except Exception as e:
            raise RuntimeError(
                f"No se pudo cargar Silero VAD.\nError: {e}"
            )
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._speech_active = False
        self._hangover_max = hangover_chunks
        self._hangover_counter = 0

    def is_speech(self, chunk_512: np.ndarray) -> bool:
        """Evalúa un chunk de exactamente 512 samples con suavizado hangover."""
        tensor = torch.from_numpy(chunk_512).float()
        prob = self.model(tensor, self.sample_rate).item()

        if prob >= self.threshold:
            self._speech_active = True
            self._hangover_counter = self._hangover_max
        elif self._hangover_counter > 0:
            # Mantener speech activo durante el hangover
            self._hangover_counter -= 1
            self._speech_active = True
        else:
            self._speech_active = False

        return self._speech_active

    def reset(self):
        """Resetear estado interno del modelo."""
        self.model.reset_states()
        self._speech_active = False
        self._hangover_counter = 0
