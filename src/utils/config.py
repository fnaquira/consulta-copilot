# -*- coding: utf-8 -*-
from pydantic_settings import BaseSettings


class TranscriberConfig(BaseSettings):
    model_size: str = "small"
    language: str = "es"
    sample_rate: int = 16000
    vad_threshold: float = 0.5
    compute_type: str = "int8"
    window_duration: float = 5.0
    transcribe_interval: float = 1.0
    confirm_threshold: float = 3.0
    queue_maxsize: int = 200

    model_config = {"env_prefix": "TRANSCRIBER_"}
