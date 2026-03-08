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

The app is a real-time audio transcriber supporting two simultaneous audio sources (microphone + system audio). The data flow is:

```
Microphone → AudioCapture (sounddevice) → mic_queue
System audio → SystemAudioCapture (PyAudioWPatch/sounddevice) → system_queue
    → SlidingWindowWorker (QThread)
        → per source: VoiceActivityDetector (silero-vad) — per 512-sample chunk
        → per source: rolling audio buffer (max 5 sec)
        → per source: TranscriptionEngine (faster-whisper) — every ~1 sec if speech
        → text_confirmed Signal(label, text) → TranscriptView.append_confirmed()
        → text_partial   Signal(label, text) → TranscriptView.update_partial()
        → vad_activity   Signal(source_name, bool)
```

### Dual audio sources

- **Mic** (`AudioCapture` / `src/audio/capture.py`): captures the microphone via sounddevice.
- **System** (`SystemAudioCapture` / `src/audio/system_capture.py`): captures what plays through the speakers. Backend differs by OS:
  - Windows: PyAudioWPatch + WASAPI loopback (install with `uv pip install PyAudioWPatch scipy`)
  - Linux: sounddevice "Monitor of ..." devices (PulseAudio/PipeWire)
  - macOS: manual selection; BlackHole virtual device recommended
  - System audio is resampled to 16kHz with scipy if the native device rate differs.

### Threading model

All heavy work runs in QThreads, never blocking the Qt main thread:
- `VADLoader` / `DualVADLoader` — loads one or two silero-vad instances on startup; enables Iniciar when done
- `ModelLoader` — loads the Whisper model when Iniciar is pressed
- `SlidingWindowWorker` — main loop: processes mic and system streams sequentially (faster-whisper is NOT thread-safe)
- Signals/Slots are the only cross-thread communication. Never touch Qt widgets from workers.

### Key design decisions

- **Dual stream state**: Each audio source is encapsulated in `_AudioStream` (worker.py), with its own buffer, VAD, confirmed text, and timing. The worker iterates `self._streams` each cycle.
- **VAD role**: Silero VAD only signals presence/absence of speech (LED indicators, gating transcription). It does NOT segment audio — the worker uses time-based rolling buffers.
- **Sliding window**: Buffer holds the last 5 seconds of audio. Text older than `confirm_threshold` (3 sec) is proportionally split: confirmed words are appended permanently; recent words remain mutable partial text.
- **initial_prompt**: The last 200 chars of confirmed text are passed to Whisper on each call for context continuity.
- **Chunk size**: Exactly 512 samples (30ms at 16kHz) — required by silero-vad. Guaranteed by `blocksize=512` for mic; SystemAudioCapture accumulates a leftover buffer to emit exact 512-sample chunks after resampling.
- **Signals carry `(label, text)`**: `text_confirmed` and `text_partial` now emit a source label string ("Tú" / "Reunión") as first argument. `TranscriptView` renders each source in its own color.

### Config

`TranscriberConfig` (pydantic-settings, `src/utils/config.py`) reads from env vars prefixed `TRANSCRIBER_`. Key fields: `window_duration`, `transcribe_interval`, `confirm_threshold`, `vad_threshold`, `model_size`, `compute_type`, `enable_system_audio`, `system_audio_device`, `mic_label`, `system_label`.

### Tests without hardware

Safe to run anywhere (mock engine + VAD):
- `tests/test_sliding_window.py` — core sliding window / buffer logic
- `tests/test_dual_worker.py` — dual-source worker, signal labels, independent buffers

Require hardware/models:
- `test_audio.py`, `test_vad.py`, `test_engine.py`, `test_system_capture.py`

### Models downloaded on first use

- silero-vad: cached at `C:\Users\favio\.cache\torch\hub\snakers4_silero-vad_master`
- Whisper models: cached by HuggingFace hub (`~/.cache/huggingface/`)
