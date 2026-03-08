# -*- coding: utf-8 -*-
import io
import sys
import torch
import numpy as np


class VoiceActivityDetector:
    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        try:
            # torch.hub.load escribe en stdout/stderr internamente.
            # En modo --windowed (sin consola) estos son None → AttributeError.
            # Los reemplazamos temporalmente si es necesario.
            _stdout_bak = sys.stdout
            _stderr_bak = sys.stderr
            if sys.stdout is None:
                sys.stdout = io.StringIO()
            if sys.stderr is None:
                sys.stderr = io.StringIO()

            self.model, _ = torch.hub.load(
                "snakers4/silero-vad", "silero_vad",
                force_reload=False, trust_repo=True
            )
        except Exception as e:
            raise RuntimeError(
                f"No se pudo cargar Silero VAD. "
                f"Asegúrate de tener conexión a internet la primera vez.\nError: {e}"
            )
        finally:
            sys.stdout = _stdout_bak
            sys.stderr = _stderr_bak
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
