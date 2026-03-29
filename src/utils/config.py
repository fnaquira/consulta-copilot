# -*- coding: utf-8 -*-
from pydantic_settings import BaseSettings


class TranscriberConfig(BaseSettings):
    model_size: str = "small"
    language: str = "es"
    sample_rate: int = 16000
    vad_threshold: float = 0.3
    compute_type: str = "int8"
    queue_maxsize: int = 200

    # --- Engine params ---
    beam_size: int = 5
    no_speech_threshold: float = 0.35
    temperature: float = 0.0

    # --- STT provider ---
    stt_provider: str = "auto"           # "auto" | "local" | "groq"
    groq_api_key: str = ""

    # --- Overlap algorithm ---
    window_duration: float = 15.0        # ventana de transcripcion (segundos)
    transcribe_interval: float = 3.0     # intervalo entre transcripciones
    max_buffer_seconds: float = 60.0     # tope de seguridad del buffer
    hallucination_filter: bool = True

    # Audio dual
    enable_system_audio: bool = True
    system_audio_device: int | None = None  # None = auto-detect
    mic_label: str = "Tu"
    system_label: str = "Reunion"

    # --- AI Provider (copiloto LLM) ---
    ai_provider: str = "openai"          # "openai" | "azure" | "ollama"
    ai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    azure_api_key: str = ""
    azure_endpoint: str = ""
    azure_deployment: str = ""
    azure_api_version: str = "2024-02-01"
    ollama_host: str = "http://localhost:11434"

    # --- Audio loopback ---
    loopback_device: str = ""

    # --- DB ---
    db_path: str = ""                    # vacio = default (~/.consulta_copilot/copilot.db)

    # --- Dominio ---
    app_domain: str = "clinical"         # "clinical" | "meeting"

    model_config = {"env_prefix": "TRANSCRIBER_"}

    def get_ai_client(self):
        """Retorna un cliente openai-compatible segun el provider configurado."""
        import openai
        if self.ai_provider == "openai":
            return openai.OpenAI(api_key=self.openai_api_key)
        elif self.ai_provider == "azure":
            return openai.AzureOpenAI(
                api_key=self.azure_api_key,
                azure_endpoint=self.azure_endpoint,
                api_version=self.azure_api_version,
            )
        elif self.ai_provider == "ollama":
            return openai.OpenAI(base_url=f"{self.ollama_host}/v1", api_key="ollama")
        raise ValueError(f"Provider desconocido: {self.ai_provider}")
