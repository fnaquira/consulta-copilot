# Transcriptor en Tiempo Real

Aplicación de escritorio para transcripción de audio en tiempo real usando Whisper + Silero VAD.

## Tecnologías

- **PySide6** — UI (LGPL)
- **faster-whisper** — Motor de transcripción (CTranslate2)
- **silero-vad** — Detección de actividad de voz
- **sounddevice** — Captura de audio
- **PyTorch** — Backend para Silero VAD

## Instalación

### Requisitos previos

- [uv](https://docs.astral.sh/uv/) (gestor de Python y entornos virtuales)

```
# Instalar uv (Windows PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

### Configurar entorno

```
cd rindecaja-desktop
uv venv --python 3.11 .venv
uv pip install -r requirements.txt --python .venv/Scripts/python.exe
uv pip install torch torchaudio --python .venv/Scripts/python.exe --index-url https://download.pytorch.org/whl/cpu
```

> La primera ejecución descarga los modelos de Silero VAD y Whisper desde internet.

## Uso

```
.venv\Scripts\python.exe main.py
```

1. Espera a que el statusbar diga **"VAD listo"**
2. Selecciona el modelo Whisper (`tiny` = rápido, `small` = equilibrado, `medium`+ = preciso)
3. Selecciona el dispositivo de audio (micrófono)
4. Pulsa **Iniciar** (o `Espacio`)
5. Habla — el texto aparece en **gris itálica** (provisional) y se confirma en **negro**
6. Pulsa **Detener** para parar

### Exportar transcripción

- `Ctrl+S` o **Archivo → Exportar como TXT**
- **Archivo → Exportar como SRT** (con timestamps reales)

### Configuración

**Archivo → Configuración → Preferencias** permite ajustar:
- Modelo Whisper y tipo de cómputo
- Umbral VAD (0.1–0.95)
- Duración del buffer deslizante
- Intervalo de transcripción
- Umbral de confirmación de texto

También se puede configurar via variables de entorno con prefijo `TRANSCRIBER_`:
```
TRANSCRIBER_MODEL_SIZE=small
TRANSCRIBER_VAD_THRESHOLD=0.5
TRANSCRIBER_WINDOW_DURATION=5.0
```

## Tests

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

## Estructura

```
rindecaja-desktop/
├── main.py                        # Entrada principal
├── requirements.txt
├── src/
│   ├── audio/
│   │   ├── capture.py             # AudioCapture (sounddevice)
│   │   ├── vad.py                 # VoiceActivityDetector (silero-vad)
│   │   └── vad_worker.py          # VADWorker QThread (Fase 3, legado)
│   ├── transcription/
│   │   ├── engine.py              # TranscriptionEngine (faster-whisper)
│   │   └── worker.py              # SlidingWindowWorker QThread
│   ├── ui/
│   │   ├── main_window.py         # Ventana principal
│   │   ├── transcript_view.py     # Widget de transcripción con parcial/confirmado
│   │   └── settings_dialog.py     # Diálogo de preferencias
│   └── utils/
│       ├── config.py              # TranscriberConfig (pydantic-settings)
│       └── export.py              # export_to_txt, export_to_srt
└── tests/
    ├── test_audio.py
    ├── test_engine.py
    ├── test_vad.py
    └── test_sliding_window.py
```
