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

## Fase 3 — VAD (Voice Activity Detection)
- [ ] Implementar VoiceActivityDetector en src/audio/vad.py
- [ ] Cargar silero-vad via torch.hub
- [ ] Procesar chunks de 512 samples (30ms a 16kHz)
- [ ] Acumular buffer durante speech, retornar segmento al detectar silencio
- [ ] Integrar con captura: solo loguear "VOZ DETECTADA" / "SILENCIO" en consola
- [ ] Conectar indicador visual de voz en la UI
- [ ] Verificar: al hablar aparece "VOZ DETECTADA", al callar "SILENCIO"

## Fase 4 — Transcripción Básica (por segmentos)
- [ ] Implementar TranscriptionEngine en src/transcription/engine.py
- [ ] Implementar TranscriptionWorker como QThread en src/transcription/worker.py
- [ ] Worker: recibe segmentos del VAD, transcribe, emite Signal text_ready
- [ ] Conectar text_ready → QTextEdit.append()
- [ ] Verificar: al hablar y pausar, aparece texto transcrito en la UI

## Fase 5 — Sliding Window (Transcripción Continua)
- [ ] Reemplazar lógica de "segmento completo" por rolling buffer
- [ ] Implementar ventana deslizante de ~5 segundos
- [ ] Transcribir cada ~1 segundo el buffer actual
- [ ] Mostrar texto parcial (gris/itálica) que se va refinando
- [ ] Confirmar texto cuando el segmento sale de la ventana (negro/normal)
- [ ] Usar initial_prompt con texto confirmado previo para coherencia
- [ ] Verificar: al hablar continuamente, el texto aparece y se refina en tiempo real

## Fase 6 — Configuración y Polish
- [ ] Implementar config.py con Pydantic BaseSettings
- [ ] Implementar settings_dialog.py (QDialog)
- [ ] Carga del modelo en thread separado con progress en statusbar
- [ ] Manejo de queue overflow (maxsize + descarte de chunks viejos)
- [ ] closeEvent limpio (detener worker + capture antes de cerrar)
- [ ] Shortcuts: Ctrl+S exportar, Ctrl+Q salir, Espacio iniciar/detener
- [ ] Verificar: cambiar modelo en settings, reiniciar transcripción, todo fluido

## Fase 7 — Exportación
- [ ] Implementar export_to_txt con timestamps
- [ ] Implementar export_to_srt con timestamps reales
- [ ] Botón y menú de exportación con QFileDialog
- [ ] Verificar: exportar transcripción, abrir archivo, contenido correcto con ñ/acentos

## Fase 8 — Tests y Cleanup
- [ ] test_audio.py: list_devices retorna al menos 1 dispositivo
- [ ] test_engine.py: transcribir silencio retorna string vacío
- [ ] test_vad.py: chunk de silencio → is_speech=False
- [ ] test_sliding_window.py: verificar lógica de confirmación de texto
- [ ] README.md con instrucciones de instalación y uso
- [ ] Verificar: pytest pasa todo verde
