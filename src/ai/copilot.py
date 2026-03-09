# -*- coding: utf-8 -*-
"""
CopilotAnalyzer — Análisis en tiempo real del discurso del paciente.

Acumula texto del paciente y envía análisis periódicamente al LLM.
Usa streaming para mostrar la respuesta progresivamente.
"""
import time
import logging

from PySide6.QtCore import QThread, Signal

from src.ui.config_dialog import load_ai_settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Eres un asistente clínico para un psicólogo durante una teleconsulta.
Tu rol es DISCRETO: proporcionas observaciones breves y relevantes.
NO diagnosticas. NO das consejos directos al paciente.
Solo asistes al psicólogo con:
1. Temas emocionales detectados en el discurso
2. Posibles distorsiones cognitivas
3. Patrones recurrentes comparados con sesiones anteriores
4. Preguntas sugeridas que el psicólogo podría hacer
5. Alertas sobre indicadores de riesgo (ideación suicida, autolesión)

Responde en español. Sé conciso (máx 3-4 líneas por análisis).
Si no hay nada relevante que señalar, responde "—".
"""


class CopilotWorker(QThread):
    """
    Hilo que acumula texto del paciente y periódicamente consulta al LLM.

    Señales:
        chunk_received(str): fragmento de respuesta streaming
        analysis_done(str): respuesta completa de un ciclo de análisis
        error_occurred(str): error de API u otro
    """
    chunk_received = Signal(str)
    analysis_done = Signal(str)
    error_occurred = Signal(str)

    # Segundos mínimos entre análisis
    THROTTLE_SECONDS = 30
    # Mínimo de caracteres nuevos de paciente antes de analizar
    MIN_NEW_CHARS = 80

    def __init__(self, patient_name: str = "", diagnosis: str = "",
                 general_notes: str = "", session_history: list[str] | None = None):
        super().__init__()
        self._running = False
        self._patient_name = patient_name
        self._diagnosis = diagnosis
        self._general_notes = general_notes
        self._session_history = session_history or []

        # Texto acumulado del paciente (thread-safe vía GIL para append)
        self._patient_text = ""
        self._last_analyzed_len = 0
        self._previous_analysis = ""

    def append_patient_text(self, text: str):
        """Llamado desde el hilo principal cuando llega texto del paciente."""
        self._patient_text += " " + text

    def run(self):
        self._running = True
        last_analysis_time = 0.0

        while self._running:
            now = time.monotonic()
            new_chars = len(self._patient_text) - self._last_analyzed_len
            elapsed = now - last_analysis_time

            if new_chars >= self.MIN_NEW_CHARS and elapsed >= self.THROTTLE_SECONDS:
                self._do_analysis()
                self._last_analyzed_len = len(self._patient_text)
                last_analysis_time = time.monotonic()

            # Esperar sin bloquear mucho
            for _ in range(50):  # 5 segundos en intervalos de 0.1
                if not self._running:
                    break
                time.sleep(0.1)

    def stop(self):
        self._running = False
        self.wait(5000)

    def _do_analysis(self):
        settings = load_ai_settings()
        provider = settings.get("ai_provider", "openai")
        model = settings.get("ai_model", "gpt-4o-mini")
        api_key = ""

        try:
            import openai

            if provider == "openai":
                api_key = settings.get("openai_api_key", "")
                if not api_key:
                    self.error_occurred.emit("Configure una API key de OpenAI en Configuración.")
                    return
                client = openai.OpenAI(api_key=api_key)
            elif provider == "azure":
                api_key = settings.get("azure_api_key", "")
                if not api_key:
                    self.error_occurred.emit("Configure una API key de Azure en Configuración.")
                    return
                client = openai.AzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=settings.get("azure_endpoint", ""),
                    api_version=settings.get("azure_api_version", "2024-02-01"),
                )
            elif provider == "ollama":
                client = openai.OpenAI(
                    base_url=f"{settings.get('ollama_host', 'http://localhost:11434')}/v1",
                    api_key="ollama",
                )
            else:
                self.error_occurred.emit(f"Provider desconocido: {provider}")
                return

            # Construir contexto
            context_parts = []
            if self._patient_name:
                context_parts.append(f"Paciente: {self._patient_name}")
            if self._diagnosis:
                context_parts.append(f"Diagnóstico: {self._diagnosis}")
            if self._general_notes:
                context_parts.append(f"Notas: {self._general_notes}")
            if self._session_history:
                history_text = "\n".join(f"- Sesión anterior: {s}" for s in self._session_history[-3:])
                context_parts.append(f"Historial reciente:\n{history_text}")
            if self._previous_analysis:
                context_parts.append(f"Tu análisis previo en esta sesión:\n{self._previous_analysis}")

            context_str = "\n".join(context_parts) if context_parts else "(sin contexto previo)"
            patient_excerpt = self._patient_text[-2000:]  # últimos 2000 chars

            user_msg = (
                f"Contexto del paciente:\n{context_str}\n\n"
                f"Discurso reciente del paciente:\n\"{patient_excerpt}\"\n\n"
                f"Proporciona tu análisis breve."
            )

            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=300,
                stream=True,
            )

            full_response = ""
            for chunk in stream:
                if not self._running:
                    break
                delta = chunk.choices[0].delta
                if delta.content:
                    full_response += delta.content
                    self.chunk_received.emit(delta.content)

            if full_response.strip():
                self._previous_analysis = full_response.strip()
                self.analysis_done.emit(full_response.strip())

        except Exception as exc:
            log.error("Error en análisis copiloto: %s", exc)
            self.error_occurred.emit(str(exc))
