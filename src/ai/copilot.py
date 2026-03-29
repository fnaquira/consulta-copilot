# -*- coding: utf-8 -*-
"""
CopilotWorker — Analisis en tiempo real configurable por dominio.

Acumula texto de todas las fuentes de audio y envia analisis periodicos al LLM.
El system prompt es inyectado segun el dominio (clinico, meeting, etc.).
Usa streaming para mostrar la respuesta progresivamente.
"""
import time
import logging

from PySide6.QtCore import QThread, Signal

from src.ui.config_dialog import load_ai_settings

log = logging.getLogger(__name__)


class CopilotWorker(QThread):
    """
    Hilo que acumula texto de la transcripcion y periodicamente consulta al LLM.

    Signals:
        chunk_received(str): fragmento de respuesta streaming
        analysis_done(str): respuesta completa de un ciclo de analisis
        summary_updated(str): resumen actualizado (ultima respuesta completa)
        error_occurred(str): error de API u otro
    """
    chunk_received = Signal(str)
    analysis_done = Signal(str)
    summary_updated = Signal(str)
    error_occurred = Signal(str)

    # Segundos minimos entre analisis
    THROTTLE_SECONDS = 30
    # Minimo de caracteres nuevos antes de analizar
    MIN_NEW_CHARS = 80

    def __init__(
        self,
        system_prompt: str,
        context_text: str = "",
        previous_summaries: list[str] | None = None,
    ):
        super().__init__()
        self._running = False
        self._system_prompt = system_prompt
        self._context_text = context_text
        self._previous_summaries = previous_summaries or []

        # Texto acumulado de TODAS las fuentes con labels
        self._full_transcript = ""
        self._last_analyzed_len = 0
        self._previous_summary = ""

    def append_text(self, label: str, text: str):
        """Llamado desde el hilo principal cuando llega texto confirmado."""
        self._full_transcript += f"\n[{label}]: {text}"

    def run(self):
        self._running = True
        last_analysis_time = 0.0

        while self._running:
            now = time.monotonic()
            new_chars = len(self._full_transcript) - self._last_analyzed_len
            elapsed = now - last_analysis_time

            if new_chars >= self.MIN_NEW_CHARS and elapsed >= self.THROTTLE_SECONDS:
                self._do_analysis()
                self._last_analyzed_len = len(self._full_transcript)
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

        try:
            import openai

            if provider == "openai":
                api_key = settings.get("openai_api_key", "")
                if not api_key:
                    self.error_occurred.emit("Configure una API key de OpenAI en Configuracion.")
                    return
                client = openai.OpenAI(api_key=api_key)
            elif provider == "azure":
                api_key = settings.get("azure_api_key", "")
                if not api_key:
                    self.error_occurred.emit("Configure una API key de Azure en Configuracion.")
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
            if self._context_text:
                context_parts.append(f"Contexto:\n{self._context_text}")
            if self._previous_summaries:
                history_text = "\n".join(
                    f"- Analisis anterior: {s}" for s in self._previous_summaries[-3:]
                )
                context_parts.append(f"Historial:\n{history_text}")
            if self._previous_summary:
                context_parts.append(f"Tu resumen/analisis previo en esta sesion:\n{self._previous_summary}")

            context_str = "\n".join(context_parts) if context_parts else "(sin contexto previo)"
            transcript_excerpt = self._full_transcript[-3000:]  # ultimos 3000 chars

            user_msg = (
                f"{context_str}\n\n"
                f"Transcripcion reciente:\n\"{transcript_excerpt}\"\n\n"
                f"Proporciona tu analisis."
            )

            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=500,
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
                self._previous_summary = full_response.strip()
                self.analysis_done.emit(full_response.strip())
                self.summary_updated.emit(full_response.strip())

        except Exception as exc:
            log.error("Error en analisis copiloto: %s", exc)
            self.error_occurred.emit(str(exc))
