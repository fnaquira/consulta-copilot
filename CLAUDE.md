# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- Python 3.11 via `uv` in `.venv/`
- **Always use** `.venv/Scripts/python.exe` (not `python` — system Python is 2.7)
- **Always prefix** commands with `export PATH="$PATH:/c/Users/favio/.local/bin"` if `uv` is needed

## Commands

```bash
# Run the app
.venv/Scripts/python.exe main.py

# Run all tests
.venv/Scripts/python.exe -m pytest tests/ -v

# Run a single test file
.venv/Scripts/python.exe -m pytest tests/test_sliding_window.py -v

# Run a single test
.venv/Scripts/python.exe -m pytest tests/test_sliding_window.py::test_buffer_corto_emite_solo_parcial -v

# Install a new dependency
export PATH="$PATH:/c/Users/favio/.local/bin"
uv pip install <package> --python .venv/Scripts/python.exe

# Install PyTorch (CPU, special index)
uv pip install torch torchaudio --python .venv/Scripts/python.exe --index-url https://download.pytorch.org/whl/cpu
```

## Architecture

The app is a real-time audio transcriber. The data flow is:

```
Microphone → AudioCapture (sounddevice) → queue.Queue
    → SlidingWindowWorker (QThread)
        → VoiceActivityDetector (silero-vad) — per 512-sample chunk
        → rolling audio buffer (max 5 sec)
        → TranscriptionEngine (faster-whisper) — every ~1 sec if speech detected
        → text_confirmed Signal → TranscriptView.append_confirmed()  [black text]
        → text_partial Signal  → TranscriptView.update_partial()     [grey italic]
```

### Threading model

All heavy work runs in QThreads, never blocking the Qt main thread:
- `VADLoader` — loads silero-vad on startup; enables Iniciar button when done
- `ModelLoader` — loads the Whisper model when Iniciar is pressed
- `SlidingWindowWorker` — the main loop: drains queue, runs VAD, triggers transcription
- Signals/Slots are the only cross-thread communication. Never touch Qt widgets from workers.

### Key design decisions

- **VAD role**: Silero VAD only signals presence/absence of speech (for the LED indicator and to gate transcription). It does NOT segment audio — the worker uses a time-based rolling buffer instead.
- **Sliding window**: The buffer holds the last 5 seconds of audio. Text older than `confirm_threshold` (3 sec) is proportionally split: confirmed words are appended permanently; recent words remain as mutable partial text.
- **initial_prompt**: The last 200 chars of confirmed text are passed to Whisper on each call, giving it context to avoid hallucinations at boundaries.
- **Chunk size**: Exactly 512 samples (30ms at 16kHz) — required by silero-vad. `blocksize=512` in `AudioCapture.start()` guarantees this.
- **Queue overflow**: If the queue fills (maxsize=500), the oldest chunk is discarded before adding the new one (`audio_queue.get_nowait()` then `put()`).

### Config

`TranscriberConfig` (pydantic-settings) reads from env vars prefixed `TRANSCRIBER_`. Passed to `MainWindow` at startup and forwarded to `SlidingWindowWorker`. Key fields: `window_duration`, `transcribe_interval`, `confirm_threshold`, `vad_threshold`, `model_size`, `compute_type`.

### Tests without hardware

`tests/test_sliding_window.py` mocks `engine` and `vad` — safe to run anywhere. `test_audio.py`, `test_vad.py`, `test_engine.py` require a microphone/GPU and internet (first run downloads models).

### Models downloaded on first use

- silero-vad: cached at `C:\Users\favio\.cache\torch\hub\snakers4_silero-vad_master`
- Whisper models: cached by HuggingFace hub (`~/.cache/huggingface/`)
