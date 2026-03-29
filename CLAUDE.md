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
.venv/Scripts/python.exe -m pytest tests/test_sliding_window.py::test_primera_transcripcion_solo_parcial -v

# Install a new dependency
export PATH="$PATH:/c/Users/favio/.local/bin"
uv pip install <package> --python .venv/Scripts/python.exe

# Install PyTorch (CPU, special index)
uv pip install torch torchaudio --python .venv/Scripts/python.exe --index-url https://download.pytorch.org/whl/cpu
```

## Architecture

The app is a real-time audio transcriber + AI copilot supporting two simultaneous audio sources (microphone + system audio) and two domains (clinical psychology / meeting management).

### Data flow

```
Microphone → AudioCapture (sounddevice) → mic_queue
System audio → SystemAudioCapture (PyAudioWPatch/sounddevice) → system_queue
    → SlidingWindowWorker (QThread)
        → per source: VoiceActivityDetector (silero-vad) — per 512-sample chunk
        → per source: accumulating audio buffer (max 60 sec, window 15 sec)
        → per source: TranscriptionProvider — every ~3 sec if speech detected
            → overlap comparison (difflib.SequenceMatcher)
            → text_confirmed Signal(label, text) → TranscriptView
            → text_partial   Signal(label, text) → TranscriptView
        → vad_activity Signal(source_name, bool)

CopilotWorker (QThread) — every ~30 sec with ≥80 new chars:
    → reads accumulated transcript from both sources
    → sends to LLM (OpenAI/Azure/Ollama) with domain-specific system prompt
    → chunk_received Signal(str) → streaming display
    → analysis_done Signal(str) → full response
    → summary_updated Signal(str) → running summary
```

### Hybrid STT engine (`src/transcription/engine.py`)

The app uses a `TranscriptionProvider` protocol with two implementations:

- **`LocalWhisperProvider`**: faster-whisper local. Auto-selects `large-v3-turbo` on GPU, user-selected model on CPU. Configurable beam_size, temperature, no_speech_threshold.
- **`GroqWhisperProvider`**: Groq cloud API (free tier ~7000 audio-sec/day). Uses the `openai` package with `base_url="https://api.groq.com/openai/v1"`. Converts numpy→WAV in-memory, calls `whisper-large-v3-turbo`.
- **`TranscriptionEngine`**: backwards-compatible wrapper around `LocalWhisperProvider` for existing consumers.

Auto-detection in `ModelLoader` (`src/ui/main_window.py`):
1. GPU available → local `large-v3-turbo` on CUDA
2. No GPU + Groq API key → Groq cloud
3. No GPU + no key → local model on CPU (fallback)

### Overlap-based confirmation algorithm (`src/transcription/worker.py`)

Replaces the old word-ratio split. Each source maintains:
- `accumulating_buffer`: grows until text is confirmed, then trimmed
- `prev_transcription`: word list from previous transcription cycle
- `window_duration=15.0`: transcribes last 15s of buffer
- `transcribe_interval=3.0`: transcribes every 3s when speech detected

Confirmation logic:
1. Transcribe a 15s window → get current words
2. Compare with `prev_transcription` via `SequenceMatcher`
3. Words that "fell off" the start of the previous transcription → **confirmed**
4. Remaining words → **partial** (still mutable)
5. Safety cap: force-confirm when buffer exceeds `max_buffer_seconds` (60s)
6. Flush on stop: transcribe remaining buffer and confirm everything

Hallucination filter: drops known Whisper artifacts ("Gracias por ver", "Thank you", etc.) when transcription is ≤5 words.

### Domain-configurable copilot (`src/ai/copilot.py`)

`CopilotWorker` accepts an injected `system_prompt` — not hardcoded. Domain prompts live in `src/ai/prompts.py`:
- `CLINICAL_PROMPT`: discrete assistant for psychologist (emotions, distortions, risk alerts)
- `MEETING_PROMPT`: structured meeting summary (resumen, temas, decisiones, calidad)
- `DOMAIN_PROMPTS` dict maps `"clinical"` / `"meeting"` to the corresponding prompt

`append_text(label, text)` accumulates transcript from ALL sources with `[label]: text` format.

### Dual audio sources

- **Mic** (`AudioCapture` / `src/audio/capture.py`): captures microphone via sounddevice.
- **System** (`SystemAudioCapture` / `src/audio/system_capture.py`): captures speaker output. Backend by OS:
  - Windows: PyAudioWPatch + WASAPI loopback
  - Linux: sounddevice "Monitor of ..." devices (PulseAudio/PipeWire)
  - macOS: ScreenCaptureKit helper or BlackHole virtual device
  - Resampled to 16kHz with scipy if native rate differs.

### Threading model

All heavy work runs in QThreads, never blocking the Qt main thread:
- `VADLoader` / `DualVADLoader` — loads silero-vad instances on startup
- `ModelLoader` — loads Whisper model or connects to Groq when Iniciar is pressed
- `SlidingWindowWorker` — main transcription loop (faster-whisper is NOT thread-safe)
- `CopilotWorker` — periodic LLM analysis with streaming
- Signals/Slots are the only cross-thread communication. Never touch Qt widgets from workers.

### Multi-domain UI (`src/ui/session_window.py`)

`DOMAIN_LABELS` dict provides per-domain UI text:
- `"clinical"`: "Notas del psicologo", "Sesion #N", "Copiloto"
- `"meeting"`: "Notas", "Reunion", "Resumen de Reunion"

Domain is selected in `config_dialog.py` → saved in `ai_settings.json` as `app_domain`.

### Config

`TranscriberConfig` (pydantic-settings, `src/utils/config.py`) reads from env vars prefixed `TRANSCRIBER_`. Key fields:
- Transcription: `window_duration` (15.0), `transcribe_interval` (3.0), `max_buffer_seconds` (60.0), `hallucination_filter` (True)
- Engine: `beam_size` (5), `no_speech_threshold` (0.35), `temperature` (0.0)
- STT: `stt_provider` ("auto"), `groq_api_key` ("")
- Domain: `app_domain` ("clinical"), `mic_label` ("Tu"), `system_label` ("Reunion")
- Audio: `vad_threshold`, `model_size`, `compute_type`, `enable_system_audio`, `system_audio_device`

AI settings (LLM provider, API keys, STT provider, domain) are persisted separately in `ai_settings.json` via `config_dialog.py`.

### Tests without hardware

Safe to run anywhere (mock engine + VAD):
- `tests/test_sliding_window.py` — overlap algorithm, buffer behavior, flush, force_trim
- `tests/test_dual_worker.py` — dual-source worker, signal labels, independent buffers
- `tests/test_overlap_algorithm.py` — pure tests of `_compare_transcriptions()` and `_is_hallucination()`
- `tests/test_copilot_domains.py` — domain prompts, CopilotWorker initialization, append_text

Require hardware/models:
- `test_audio.py`, `test_vad.py`, `test_engine.py`, `test_system_capture.py`

### Models downloaded on first use

- silero-vad: cached at `C:\Users\favio\.cache\torch\hub\snakers4_silero-vad_master`
- Whisper models: cached by HuggingFace hub (`~/.cache/huggingface/`)
