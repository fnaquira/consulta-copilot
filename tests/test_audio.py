# -*- coding: utf-8 -*-
import queue
from src.audio.capture import AudioCapture, AudioConfig


def test_list_devices_retorna_al_menos_uno():
    cap = AudioCapture(AudioConfig(), queue.Queue())
    devs = cap.list_devices()
    assert len(devs) >= 1, "Se esperaba al menos 1 dispositivo de entrada"


def test_list_devices_estructura():
    cap = AudioCapture(AudioConfig(), queue.Queue())
    devs = cap.list_devices()
    for d in devs:
        assert "index" in d
        assert "name" in d
        assert "channels" in d
        assert d["channels"] >= 1
