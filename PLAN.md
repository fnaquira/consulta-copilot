# Plan de Ejecución: Transcriptor en Tiempo Real

## Fase 0 — Scaffolding y Entorno ✓
- [x] Crear estructura de directorios completa (src/audio, src/transcription, src/ui, src/utils, tests)
- [x] Crear requirements.txt con todas las dependencias
- [x] Crear main.py con QApplication mínima (ventana vacía con título)
- [x] Verificar: uv venv con Python 3.11, PySide6 instalado, sintaxis OK
- [x] Entorno: uv + .venv/Scripts/python.exe, ejecutar con .venv/Scripts/python.exe main.py

## Fase 1 — UI Esqueleto ✓
- [x] Implementar MainWindow con toolbar (botones Iniciar/Detener/Limpiar)
- [x] Agregar QComboBox para modelo, dispositivo audio, idioma
- [x] Agregar QTextEdit readonly como área de transcripción (TranscriptView)
- [x] Agregar QStatusBar con mensaje "Listo"
- [x] Agregar indicador visual de actividad de voz (LED circular 16x16)
- [x] Verificar: la app abre con todos los controles visibles y funcionales (sin lógica aún)
- [x] Stubs creados: capture.py, vad.py, engine.py, worker.py, export.py, config.py

## Fase 2 — Captura de Audio ✓
- [x] Implementar AudioCapture en src/audio/capture.py
- [x] list_devices() retorna 8 dispositivos con input channels
- [x] start(device_index) inicia InputStream, pushea chunks a queue con overflow protection
- [x] stop() cierra stream limpiamente
- [x] Poblar QComboBox de dispositivos con datos reales (_populate_devices en MainWindow)
- [x] Print debug cada ~30 chunks (~1 seg): chunk#, samples=512, rms
- [x] Verificar: al iniciar se ven prints de chunks, al detener se paran

## Fase 3 — VAD (Voice Activity Detection) ✓
- [x] Implementar VoiceActivityDetector en src/audio/vad.py
- [x] Cargar silero-vad via torch.hub (trust_repo=True, deps: torchaudio, packaging)
- [x] Procesar chunks de 512 samples (30ms a 16kHz) — silencio→False OK
- [x] Crear VADWorker (QThread) en src/audio/vad_worker.py — loguea solo cambios de estado
- [x] Integrar con captura: loguea "VOZ DETECTADA" / "SILENCIO" en consola
- [x] Conectar vad_activity Signal → _update_vad_indicator → LED verde/gris
- [x] VAD se carga en background (VADLoader QThread) — botón Iniciar habilitado al terminar
- [x] Verificar: al hablar LED se pone verde, al callar vuelve a gris; consola muestra cambios

## Fase 4 — Transcripción Básica ✓ (integrada en Fase 5)
- [x] Implementar TranscriptionEngine en src/transcription/engine.py
- [x] faster-whisper: silencio → "" OK; modelo tiny descargado y verificado
- [x] ModelLoader (QThread) carga el modelo en background → statusbar muestra progreso
- [x] Conectar text_confirmed → TranscriptView.append_confirmed (negro)
- [x] Conectar text_partial → TranscriptView.update_partial (gris itálica)

## Fase 5 — Sliding Window (Transcripción Continua) ✓
- [x] SlidingWindowWorker en src/transcription/worker.py
- [x] Buffer rolling máx 5 segundos (configurable)
- [x] Transcribir cada ~1 segundo si hay voz detectada
- [x] Texto parcial se va refinando; confirmado es inmutable
- [x] initial_prompt con últimos 200 chars para coherencia con Whisper
- [x] Flush al detener: transcribe buffer restante como texto confirmado
- [x] VAD en worker (emit solo cuando cambia estado para no saturar la UI)

## Fase 6 — Configuración y Polish ✓
- [x] config.py con Pydantic BaseSettings (env_prefix TRANSCRIBER_)
- [x] settings_dialog.py (QDialog) con modelo, compute_type, VAD threshold, ventana deslizante
- [x] ModelLoader QThread — carga modelo en background con progress en statusbar
- [x] Queue overflow: maxsize=500 + descarte de chunk más antiguo en callback
- [x] closeEvent limpio: detiene worker, captura y espera loaders
- [x] Shortcuts: Ctrl+S exportar, Ctrl+Q salir, Espacio iniciar/detener
- [x] Logging con logging.basicConfig en lugar de prints de debug
- [x] Config aplicada a combos al iniciar (model_size, language, vad_threshold, compute_type)

## Fase 7 — Exportación ✓
- [x] export_to_txt (UTF-8)
- [x] export_to_srt con timestamps reales (desde TranscriptView._segments)
- [x] TranscriptView lleva registro de segmentos (texto, t_inicio, t_fin)
- [x] Menú Archivo: Exportar TXT (Ctrl+S) y Exportar SRT con QFileDialog
- [x] Verificar: exporta con ñ/acentos correctamente (encoding UTF-8)

## Fase 8 — Tests y Cleanup ✓
- [x] test_audio.py: list_devices retorna ≥1 dispositivo + estructura correcta (2 tests)
- [x] test_engine.py: silencio → "" + initial_prompt no crashea (2 tests)
- [x] test_vad.py: silencio → False + reset + ruido suave (3 tests)
- [x] test_sliding_window.py: buffer corto/largo, texto vacío, reset _has_speech (4 tests)
- [x] README.md con instalación, uso, estructura y configuración
- [x] pytest: 11/11 tests verdes, 21 archivos sin errores de sintaxis

## Fase 9 — Audio Dual (Micrófono + Sistema)

### 9.1 — Captura de audio del sistema
- [x] Crear src/audio/system_capture.py con clase SystemAudioCapture
- [x] Windows: usar PyAudioWPatch para WASAPI loopback
- [x] Linux: usar sounddevice con dispositivo PulseAudio/PipeWire monitor
- [x] macOS: documentar que requiere BlackHole (no implementar auto-detect)
- [x] Agregar PyAudioWPatch a requirements.txt (dependencia condicional Windows)
- [x] Implementar auto-detección del dispositivo loopback por plataforma
- [ ] Test manual: reproducir audio en YouTube, verificar que se captura
- [ ] Verificar: chunks de 512 samples llegan a la queue correctamente

### 9.2 — Pipeline dual en el Worker
- [x] Crear segunda queue: system_audio_queue
- [x] Crear segunda instancia de VAD para audio del sistema
- [x] Agregar buffers separados en SlidingWindowWorker: _AudioStream por fuente
- [x] Cada buffer mantiene su propia sliding window independiente (5s)
- [x] Cada buffer tiene su propio ciclo de transcripción (~1s)
- [x] Cada buffer tiene su propio confirmed_text para initial_prompt
- [ ] Verificar: hablar al mic Y reproducir audio → ambos se transcriben

### 9.3 — Etiquetado de hablantes
- [x] Signals ahora emiten tuplas: (source, text) en vez de solo text
- [x] text_confirmed = Signal(str, str)  → (source_label, text)
- [x] text_partial = Signal(str, str)    → (source_label, text)
- [x] Labels: mic → "[Tú]", system → "[Reunión]"
- [ ] Verificar: transcripción muestra [Tú] y [Reunión] correctamente

### 9.4 — UI actualizada
- [x] TranscriptView: append_confirmed y update_partial reciben (source, text)
- [x] Prefijo [Tú] en azul, [Reunión] en verde
- [x] Texto parcial sigue en gris itálica pero con prefijo de color
- [x] Manejar DOS textos parciales simultáneos (uno por fuente)
- [x] Agregar QComboBox para dispositivo de sistema en toolbar
- [x] Agregar checkbox "Capturar audio del sistema" en toolbar
- [x] Agregar DOS indicadores VAD (uno por fuente)
- [ ] Verificar: UI muestra ambas fuentes con formato correcto

### 9.5 — Configuración y robustez
- [x] Extender TranscriberConfig con enable_system_audio, system_audio_device
- [x] Manejar caso: sistema no soporta loopback → deshabilitar opción, mostrar mensaje
- [x] Manejar caso: usuario desactiva audio del sistema → volver a modo single
- [x] Exportación: incluir labels de speaker en .txt y .srt
- [x] Verificar: todo funciona con solo mic (backwards compatible)

### 9.6 — Tests
- [x] test_system_capture.py: detecta dispositivo loopback (skip si no hay)
- [x] test_dual_worker.py: dos queues alimentan buffers independientes
- [x] Todos los tests anteriores siguen pasando
- [x] Verificar: pytest 25/25 tests verdes, 1 skipped (loopback sin audio activo)
