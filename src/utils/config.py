# -*- coding: utf-8 -*-
from pydantic_settings import BaseSettings


class TranscriberConfig(BaseSettings):
    model_size: str = "small"
    language: str = "es"
    sample_rate: int = 16000
    vad_threshold: float = 0.3
    compute_type: str = "int8"
    window_duration: float = 5.0
    transcribe_interval: float = 1.0
    confirm_threshold: float = 2.0
    queue_maxsize: int = 200

    # Audio dual
    enable_system_audio: bool = True
    system_audio_device: int | None = None  # None = auto-detect
    mic_label: str = "Tú"
    system_label: str = "Reunión"

    # --- AI Provider ---
    ai_provider: str = "openai"          # "openai" | "azure" | "ollama"
    ai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    azure_api_key: str = ""
    azure_endpoint: str = ""
    azure_deployment: str = ""
    azure_api_version: str = "2024-02-01"
    ollama_host: str = "http://localhost:11434"

    # --- Audio loopback ---
    loopback_device: str = ""            # dispositivo para capturar audio del paciente

    # --- DB ---
    db_path: str = ""                    # vacío = default (~/.consulta_copilot/copilot.db)

    model_config = {"env_prefix": "TRANSCRIBER_"}

    def get_ai_client(self):
        """Retorna un cliente openai-compatible según el provider configurado."""
        import openai  # importación tardía para no requerir openai si no se usa
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
