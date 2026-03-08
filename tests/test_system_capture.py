# -*- coding: utf-8 -*-
"""
test_system_capture.py

Tests para SystemAudioCapture.
Se salta si no hay dispositivos loopback disponibles (entorno sin hardware).
"""

import platform
import queue
import pytest

from src.audio.system_capture import SystemAudioCapture, SystemAudioConfig


@pytest.fixture
def capture():
    cfg = SystemAudioConfig()
    q   = queue.Queue()
    return SystemAudioCapture(cfg, q)


def test_list_loopback_devices_retorna_lista(capture):
    """list_loopback_devices() debe retornar una lista (puede ser vacía)."""
    devs = capture.list_loopback_devices()
    assert isinstance(devs, list)


def test_list_loopback_devices_estructura(capture):
    """Cada dispositivo debe tener los campos requeridos."""
    devs = capture.list_loopback_devices()
    for d in devs:
        assert "index"       in d
        assert "name"        in d
        assert "sample_rate" in d
        assert "channels"    in d
        assert "backend"     in d
        assert isinstance(d["index"],       int)
        assert isinstance(d["name"],        str)
        assert isinstance(d["sample_rate"], int)
        assert d["sample_rate"] > 0
        assert d["channels"] >= 1


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="PyAudioWPatch solo disponible en Windows"
)
def test_windows_loopback_backend(capture):
    """En Windows debe haber al menos un dispositivo con backend pyaudiowpatch."""
    devs = capture.list_loopback_devices()
    if not devs:
        pytest.skip("No hay dispositivos loopback en este sistema")
    assert any(d["backend"] == "pyaudiowpatch" for d in devs)


def test_stop_sin_start_no_falla(capture):
    """Llamar stop() sin haber iniciado no debe lanzar excepción."""
    capture.stop()   # No debe lanzar


def test_chunks_llegan_a_queue():
    """Si hay dispositivo loopback con audio activo, llegan chunks de 512 samples.

    NOTA: El loopback WASAPI solo captura si HAY audio sonando en el sistema.
    En entornos CI/sin audio activo, el test se salta automáticamente.
    Para probar manualmente: reproduce audio en YouTube y corre este test.
    """
    import time
    import numpy as np

    cfg   = SystemAudioConfig()
    q     = queue.Queue()
    cap   = SystemAudioCapture(cfg, q)
    devs  = cap.list_loopback_devices()

    if not devs:
        pytest.skip("No hay dispositivos loopback disponibles")

    cap.start(devs[0]["index"])

    deadline = time.monotonic() + 3.0
    chunks   = []
    while time.monotonic() < deadline and len(chunks) < 5:
        try:
            chunk = q.get(timeout=0.1)
            chunks.append(chunk)
        except Exception:
            pass

    cap.stop()

    if len(chunks) == 0:
        pytest.skip(
            "No llegaron chunks: el loopback WASAPI solo captura cuando hay audio "
            "activo en el sistema. Reproduce audio y vuelve a correr el test."
        )

    for chunk in chunks:
        assert isinstance(chunk, np.ndarray)
        assert chunk.dtype == np.float32
        assert len(chunk) == 512
