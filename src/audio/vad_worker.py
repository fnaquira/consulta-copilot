# -*- coding: utf-8 -*-
"""
VADWorker — Fase 3
Lee chunks de la queue, aplica VoiceActivityDetector en cada uno,
emite vad_activity Signal para el indicador visual y loguea en consola.
"""
import queue
import time
from PySide6.QtCore import QThread, Signal


class VADWorker(QThread):
    vad_activity = Signal(bool)   # True = voz, False = silencio
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, audio_queue: queue.Queue, vad):
        super().__init__()
        self.audio_queue = audio_queue
        self.vad = vad
        self._running = False
        self._last_state = None   # para loguear solo cambios de estado

    def run(self):
        self._running = True
        self.status_changed.emit("Escuchando (VAD activo)...")

        while self._running:
            try:
                chunk = self.audio_queue.get(timeout=0.05)
                is_speech = self.vad.is_speech(chunk)
                self.vad_activity.emit(is_speech)

                # Loguear solo cuando cambia el estado
                if is_speech != self._last_state:
                    if is_speech:
                        print("[VAD] VOZ DETECTADA")
                    else:
                        print("[VAD] SILENCIO")
                    self._last_state = is_speech

            except queue.Empty:
                continue
            except Exception as e:
                self.error_occurred.emit(str(e))

    def stop(self):
        self._running = False
        self.wait()
