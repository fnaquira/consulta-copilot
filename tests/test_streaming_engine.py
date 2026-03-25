# -*- coding: utf-8 -*-
"""
Tests para DeepgramStreamEngine y StreamingTranscriptionEngine.
No requiere API key real — testea la conversión y el contrato de la interfaz.
"""

import numpy as np
from unittest.mock import MagicMock, patch

from src.transcription.streaming_engine import DeepgramStreamEngine


def test_send_audio_converts_to_int16_pcm():
    """send_audio convierte float32 a int16 PCM bytes."""
    engine = DeepgramStreamEngine(api_key="test-key")
    engine._running = True

    # Mock de la conexión
    mock_conn = MagicMock()
    engine._connection = mock_conn

    chunk = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    engine.send_audio(chunk)

    mock_conn.send.assert_called_once()
    pcm_bytes = mock_conn.send.call_args[0][0]

    # Verificar que es bytes de longitud correcta (5 muestras × 2 bytes)
    assert isinstance(pcm_bytes, bytes)
    assert len(pcm_bytes) == 10

    # Verificar valores
    import struct
    values = struct.unpack(f"<{len(chunk)}h", pcm_bytes)
    assert values[0] == 0       # 0.0
    assert values[1] == 16383   # 0.5 * 32767 ≈ 16383
    assert values[2] == -16383  # -0.5 * 32767 ≈ -16383


def test_send_audio_noop_when_not_running():
    """send_audio no hace nada si el engine no está corriendo."""
    engine = DeepgramStreamEngine(api_key="test-key")
    engine._running = False
    engine._connection = MagicMock()

    engine.send_audio(np.zeros(512, dtype=np.float32))
    engine._connection.send.assert_not_called()


def test_on_transcript_callback_final():
    """_on_transcript invoca on_final para resultados finales."""
    engine = DeepgramStreamEngine(api_key="test-key")

    finals = []
    engine.on_final = lambda t: finals.append(t)

    # Simular resultado de Deepgram
    result = MagicMock()
    result.channel.alternatives = [MagicMock()]
    result.channel.alternatives[0].transcript = "hola mundo"
    result.is_final = True

    engine._on_transcript(None, result)
    assert finals == ["hola mundo"]


def test_on_transcript_callback_partial():
    """_on_transcript invoca on_partial para resultados interim."""
    engine = DeepgramStreamEngine(api_key="test-key")

    partials = []
    engine.on_partial = lambda t: partials.append(t)

    result = MagicMock()
    result.channel.alternatives = [MagicMock()]
    result.channel.alternatives[0].transcript = "hola"
    result.is_final = False

    engine._on_transcript(None, result)
    assert partials == ["hola"]


def test_on_transcript_empty_ignored():
    """_on_transcript ignora transcripciones vacías."""
    engine = DeepgramStreamEngine(api_key="test-key")

    finals = []
    partials = []
    engine.on_final = lambda t: finals.append(t)
    engine.on_partial = lambda t: partials.append(t)

    result = MagicMock()
    result.channel.alternatives = [MagicMock()]
    result.channel.alternatives[0].transcript = "   "
    result.is_final = True

    engine._on_transcript(None, result)
    assert finals == []
    assert partials == []


def test_stop_calls_finish():
    """stop() llama finish() en la conexión."""
    engine = DeepgramStreamEngine(api_key="test-key")
    engine._running = True
    mock_conn = MagicMock()
    engine._connection = mock_conn

    engine.stop()

    mock_conn.finish.assert_called_once()
    assert engine._running is False
    assert engine._connection is None
