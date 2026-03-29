# -*- coding: utf-8 -*-
import queue
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QPushButton, QComboBox, QLabel,
    QFrame, QSizePolicy, QMessageBox, QFileDialog, QCheckBox
)
from PySide6.QtCore import Qt, QSize, Slot, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut

from src.ui.transcript_view import TranscriptView
from src.audio.capture import AudioCapture, AudioConfig
from src.audio.system_capture import SystemAudioCapture, SystemAudioConfig


MODELOS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
IDIOMAS = [("Español", "es"), ("Inglés", "en"), ("Automático", None)]


# ---------------------------------------------------------------------------
# Loaders en background
# ---------------------------------------------------------------------------

class VADLoader(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, threshold: float = 0.5):
        super().__init__()
        self._threshold = threshold

    def run(self):
        try:
            from src.audio.vad import VoiceActivityDetector
            vad = VoiceActivityDetector(threshold=self._threshold)
            self.loaded.emit(vad)
        except Exception as e:
            self.failed.emit(str(e))


class DualVADLoader(QThread):
    """Carga dos instancias de VAD (mic + sistema). Emite cuando ambas listas."""
    loaded = Signal(object, object)   # (mic_vad, system_vad)
    failed = Signal(str)

    def __init__(self, threshold: float = 0.5):
        super().__init__()
        self._threshold = threshold

    def run(self):
        try:
            from src.audio.vad import VoiceActivityDetector
            mic_vad    = VoiceActivityDetector(threshold=self._threshold)
            system_vad = VoiceActivityDetector(threshold=self._threshold)
            self.loaded.emit(mic_vad, system_vad)
        except Exception as e:
            self.failed.emit(str(e))


class ModelLoader(QThread):
    loaded   = Signal(object)
    failed   = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        model_size: str,
        compute_type: str,
        language: str,
        stt_provider: str = "auto",
        groq_api_key: str = "",
        beam_size: int = 5,
        no_speech_threshold: float = 0.35,
        temperature: float = 0.0,
    ):
        super().__init__()
        self._model_size   = model_size
        self._compute_type = compute_type
        self._language     = language
        self._stt_provider = stt_provider
        self._groq_api_key = groq_api_key
        self._beam_size    = beam_size
        self._no_speech_threshold = no_speech_threshold
        self._temperature  = temperature

    def run(self):
        try:
            engine = self._create_provider()
            self.loaded.emit(engine)
        except Exception as e:
            self.failed.emit(str(e))

    def _create_provider(self):
        from src.transcription.engine import (
            LocalWhisperProvider, GroqWhisperProvider,
        )
        import torch

        provider = self._stt_provider
        has_gpu = torch.cuda.is_available()

        if provider == "groq" or (provider == "auto" and not has_gpu and self._groq_api_key):
            self.progress.emit("Conectando a Groq API (whisper-large-v3-turbo)...")
            return GroqWhisperProvider(
                api_key=self._groq_api_key,
                language=self._language,
            )

        # Local: con GPU usar large-v3-turbo, sin GPU usar el modelo seleccionado
        if provider == "auto" and has_gpu:
            model = "large-v3-turbo"
            device = "cuda"
            self.progress.emit(f"GPU detectada. Cargando '{model}' local...")
        else:
            model = self._model_size
            device = "auto"
            if provider == "auto" and not self._groq_api_key:
                self.progress.emit(
                    f"Sin GPU ni Groq key. Cargando '{model}' local (CPU)..."
                )
            else:
                self.progress.emit(f"Cargando modelo '{model}' local...")

        return LocalWhisperProvider(
            model_size=model,
            device=device,
            compute_type=self._compute_type,
            language=self._language,
            beam_size=self._beam_size,
            no_speech_threshold=self._no_speech_threshold,
            temperature=self._temperature,
        )


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self._config       = config
        self._capture      = None
        self._sys_capture  = None
        self._mic_vad      = None
        self._system_vad   = None
        self._engine       = None
        self._worker       = None
        self._audio_queue  = None
        self._system_queue = None
        self._is_running   = False

        # loaders
        self._vad_loader   = None
        self._model_loader = None

        self.setWindowTitle("Transcriptor en Tiempo Real")
        self.resize(960, 680)
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._populate_devices()
        self._populate_system_devices()

        # Aplicar config a los combos si está disponible
        if config:
            self.cb_modelo.setCurrentText(config.model_size)
            for i in range(self.cb_idioma.count()):
                if self.cb_idioma.itemData(i) == config.language:
                    self.cb_idioma.setCurrentIndex(i)
                    break
            # Estado inicial del checkbox de sistema
            if hasattr(config, "enable_system_audio"):
                self.chk_sistema.setChecked(config.enable_system_audio)

        # Cargar VAD al iniciar
        vad_threshold = config.vad_threshold if config else 0.5
        self.statusBar().showMessage("Cargando VAD...")
        self._load_vad(vad_threshold)

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        toolbar = QToolBar("Principal")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        self.btn_iniciar = QPushButton("▶  Iniciar")
        self.btn_iniciar.setFixedHeight(32)
        self.btn_iniciar.setEnabled(False)
        self.btn_iniciar.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border-radius:4px;padding:0 12px;font-weight:bold;}"
            "QPushButton:hover{background:#43A047;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        toolbar.addWidget(self.btn_iniciar)

        self.btn_detener = QPushButton("⏹  Detener")
        self.btn_detener.setFixedHeight(32)
        self.btn_detener.setEnabled(False)
        self.btn_detener.setStyleSheet(
            "QPushButton{background:#F44336;color:white;border-radius:4px;padding:0 12px;font-weight:bold;}"
            "QPushButton:hover{background:#E53935;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        toolbar.addWidget(self.btn_detener)

        toolbar.addSeparator()

        self.btn_limpiar = QPushButton("🗑  Limpiar")
        self.btn_limpiar.setFixedHeight(32)
        self.btn_limpiar.setStyleSheet(
            "QPushButton{background:#9E9E9E;color:white;border-radius:4px;padding:0 12px;}"
            "QPushButton:hover{background:#757575;}"
        )
        toolbar.addWidget(self.btn_limpiar)

        toolbar.addSeparator()

        # Indicador VAD micrófono
        self._vad_mic = QFrame()
        self._vad_mic.setFixedSize(16, 16)
        self._vad_mic.setStyleSheet("background:#666;border-radius:8px;")
        toolbar.addWidget(self._vad_mic)

        lbl_mic = QLabel("  Mic")
        lbl_mic.setStyleSheet("color:#2196F3;font-size:12px;font-weight:bold;")
        toolbar.addWidget(lbl_mic)

        toolbar.addWidget(QLabel("  "))

        # Indicador VAD sistema
        self._vad_system = QFrame()
        self._vad_system.setFixedSize(16, 16)
        self._vad_system.setStyleSheet("background:#333;border-radius:8px;")
        toolbar.addWidget(self._vad_system)

        lbl_sys = QLabel("  Reunión")
        lbl_sys.setStyleSheet("color:#4CAF50;font-size:12px;font-weight:bold;")
        toolbar.addWidget(lbl_sys)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # ---- Fila de controles ----
        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)

        ctrl.addWidget(QLabel("Modelo:"))
        self.cb_modelo = QComboBox()
        self.cb_modelo.addItems(MODELOS)
        self.cb_modelo.setCurrentText("small")
        self.cb_modelo.setMinimumWidth(140)
        ctrl.addWidget(self.cb_modelo)

        ctrl.addWidget(QLabel("Mic:"))
        self.cb_dispositivo = QComboBox()
        self.cb_dispositivo.setMinimumWidth(200)
        ctrl.addWidget(self.cb_dispositivo)

        ctrl.addWidget(QLabel("Idioma:"))
        self.cb_idioma = QComboBox()
        for nombre, codigo in IDIOMAS:
            self.cb_idioma.addItem(nombre, codigo)
        self.cb_idioma.setCurrentIndex(0)
        ctrl.addWidget(self.cb_idioma)

        ctrl.addStretch()
        root.addLayout(ctrl)

        # ---- Fila de controles de sistema ----
        sys_ctrl = QHBoxLayout()
        sys_ctrl.setSpacing(12)

        self.chk_sistema = QCheckBox("Capturar audio del sistema")
        self.chk_sistema.setStyleSheet("color:#4CAF50;font-weight:bold;")
        self.chk_sistema.setChecked(True)
        sys_ctrl.addWidget(self.chk_sistema)

        sys_ctrl.addWidget(QLabel("Dispositivo:"))
        self.cb_sistema = QComboBox()
        self.cb_sistema.setMinimumWidth(280)
        sys_ctrl.addWidget(self.cb_sistema)

        sys_ctrl.addStretch()
        root.addLayout(sys_ctrl)

        self._transcript_view = TranscriptView()
        self._transcript_view.setMinimumHeight(400)
        root.addWidget(self._transcript_view, stretch=1)

        self.btn_limpiar.clicked.connect(self._on_limpiar)
        self.btn_iniciar.clicked.connect(self._on_iniciar)
        self.btn_detener.clicked.connect(self._on_detener)
        self.chk_sistema.toggled.connect(self._on_sistema_toggled)

    def _build_menu(self):
        menubar = self.menuBar()

        menu_archivo = menubar.addMenu("Archivo")

        act_txt = QAction("Exportar como TXT...", self)
        act_txt.setShortcut(QKeySequence("Ctrl+S"))
        act_txt.triggered.connect(self._on_exportar_txt)
        menu_archivo.addAction(act_txt)

        act_srt = QAction("Exportar como SRT...", self)
        act_srt.triggered.connect(self._on_exportar_srt)
        menu_archivo.addAction(act_srt)

        menu_archivo.addSeparator()

        act_salir = QAction("Salir", self)
        act_salir.setShortcut(QKeySequence("Ctrl+Q"))
        act_salir.triggered.connect(self.close)
        menu_archivo.addAction(act_salir)

        menu_cfg = menubar.addMenu("Configuración")
        act_cfg = QAction("Preferencias...", self)
        act_cfg.triggered.connect(self._on_abrir_settings)
        menu_cfg.addAction(act_cfg)

    def _build_shortcuts(self):
        sc = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        sc.activated.connect(self._on_toggle_space)

    # ------------------------------------------------------------------ #
    # Dispositivos
    # ------------------------------------------------------------------ #
    def _populate_devices(self):
        try:
            cap  = AudioCapture(AudioConfig(), queue.Queue())
            devs = cap.list_devices()
            self.cb_dispositivo.clear()
            self.cb_dispositivo.addItem("Dispositivo predeterminado", None)
            for d in devs:
                self.cb_dispositivo.addItem(
                    f"[{d['index']}] {d['name']} ({d['channels']}ch)", d["index"]
                )
        except Exception as e:
            self.cb_dispositivo.addItem("Error al listar dispositivos", None)
            print(f"[MainWindow] Error listando dispositivos mic: {e}")

    def _populate_system_devices(self):
        """Llena el combo de dispositivos de sistema (loopback)."""
        try:
            cap  = SystemAudioCapture(SystemAudioConfig(), queue.Queue())
            devs = cap.list_loopback_devices()
            self.cb_sistema.clear()

            if not devs:
                self.cb_sistema.addItem(
                    "No hay dispositivos loopback disponibles", None
                )
                self.chk_sistema.setEnabled(False)
                self.chk_sistema.setChecked(False)
                self.chk_sistema.setToolTip(
                    "PyAudioWPatch no instalado o no hay dispositivos loopback."
                )
                return

            self.cb_sistema.addItem("Auto-detectar (primer loopback)", None)
            for d in devs:
                self.cb_sistema.addItem(
                    f"[{d['index']}] {d['name']} ({d['sample_rate']}Hz)", d["index"]
                )
        except Exception as e:
            self.cb_sistema.addItem("Error al listar dispositivos de sistema", None)
            print(f"[MainWindow] Error listando dispositivos sistema: {e}")

    def _selected_device(self) -> int | None:
        return self.cb_dispositivo.currentData()

    def _selected_system_device(self) -> int | None:
        return self.cb_sistema.currentData()

    # ------------------------------------------------------------------ #
    # Toggle checkbox sistema
    # ------------------------------------------------------------------ #
    @Slot(bool)
    def _on_sistema_toggled(self, checked: bool):
        self.cb_sistema.setEnabled(checked)
        # Actualizar indicador VAD sistema
        color = "#333" if not checked else "#666"
        self._vad_system.setStyleSheet(f"background:{color};border-radius:8px;")

    # ------------------------------------------------------------------ #
    # Carga VAD en background
    # ------------------------------------------------------------------ #
    def _load_vad(self, threshold: float = 0.5):
        if self.chk_sistema.isChecked():
            # Cargar dos instancias
            self._vad_loader = DualVADLoader(threshold=threshold)
            self._vad_loader.loaded.connect(self._on_dual_vad_loaded)
            self._vad_loader.failed.connect(self._on_vad_failed)
        else:
            self._vad_loader = VADLoader(threshold=threshold)
            self._vad_loader.loaded.connect(self._on_vad_loaded)
            self._vad_loader.failed.connect(self._on_vad_failed)
        self._vad_loader.start()

    @Slot(object)
    def _on_vad_loaded(self, vad):
        self._mic_vad   = vad
        self._system_vad = None
        self.statusBar().showMessage("VAD listo. Selecciona un modelo y pulsa Iniciar.")
        self.btn_iniciar.setEnabled(True)
        print("[MainWindow] Silero VAD (mic) cargado OK")

    @Slot(object, object)
    def _on_dual_vad_loaded(self, mic_vad, system_vad):
        self._mic_vad    = mic_vad
        self._system_vad = system_vad
        self.statusBar().showMessage("VAD dual listo. Selecciona un modelo y pulsa Iniciar.")
        self.btn_iniciar.setEnabled(True)
        print("[MainWindow] Silero VAD (mic + sistema) cargado OK")

    @Slot(str)
    def _on_vad_failed(self, error: str):
        self.statusBar().showMessage(f"Error VAD: {error}")
        QMessageBox.critical(self, "Error al cargar VAD",
            f"No se pudo cargar Silero VAD:\n{error}")
        self.btn_iniciar.setEnabled(True)

    # ------------------------------------------------------------------ #
    # Iniciar: carga modelo → arranca captura + worker
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_iniciar(self):
        if self._is_running:
            return

        model_size   = self.cb_modelo.currentText()
        language     = self.cb_idioma.currentData() or "es"
        compute_type = self._config.compute_type if self._config else "int8"

        self.btn_iniciar.setEnabled(False)
        self.cb_modelo.setEnabled(False)
        self.cb_idioma.setEnabled(False)

        from src.ui.config_dialog import load_ai_settings
        ai_settings = load_ai_settings()

        self._model_loader = ModelLoader(
            model_size=model_size,
            compute_type=compute_type,
            language=language,
            stt_provider=ai_settings.get("stt_provider", "auto"),
            groq_api_key=ai_settings.get("groq_api_key", ""),
            beam_size=self._config.beam_size if self._config else 5,
            no_speech_threshold=self._config.no_speech_threshold if self._config else 0.35,
            temperature=self._config.temperature if self._config else 0.0,
        )
        self._model_loader.progress.connect(self.statusBar().showMessage)
        self._model_loader.loaded.connect(self._on_model_loaded)
        self._model_loader.failed.connect(self._on_model_failed)
        self._model_loader.start()

    @Slot(object)
    def _on_model_loaded(self, engine):
        self._engine = engine
        print(f"[MainWindow] Modelo cargado: {self.cb_modelo.currentText()}")
        self._start_capture_and_worker()

    @Slot(str)
    def _on_model_failed(self, error: str):
        self.statusBar().showMessage(f"Error cargando modelo: {error}")
        QMessageBox.critical(self, "Error al cargar modelo",
            f"No se pudo cargar el modelo Whisper:\n{error}")
        self.btn_iniciar.setEnabled(True)
        self.cb_modelo.setEnabled(True)
        self.cb_idioma.setEnabled(True)

    def _start_capture_and_worker(self):
        """Arranca captura de audio (mic + sistema opcional) + SlidingWindowWorker."""
        device_index = self._selected_device()

        # --- Micrófono ---
        self._audio_queue = queue.Queue(maxsize=500)
        audio_cfg         = AudioConfig()
        self._capture     = AudioCapture(audio_cfg, self._audio_queue)

        try:
            self._capture.start(device_index)
        except Exception as e:
            QMessageBox.critical(self, "Error de audio",
                f"No se pudo iniciar la captura de micrófono:\n{e}")
            self._capture = None
            self.btn_iniciar.setEnabled(True)
            self.cb_modelo.setEnabled(True)
            self.cb_idioma.setEnabled(True)
            return

        # --- Audio del sistema (opcional) ---
        system_queue = None
        if self.chk_sistema.isChecked() and self._system_vad is not None:
            system_device = self._selected_system_device()
            self._system_queue = queue.Queue(maxsize=500)
            sys_cfg = SystemAudioConfig()
            self._sys_capture = SystemAudioCapture(sys_cfg, self._system_queue)
            try:
                self._sys_capture.start(system_device)
                system_queue = self._system_queue
                print(f"[MainWindow] Captura sistema iniciada — dispositivo: {system_device}")
            except Exception as e:
                print(f"[MainWindow] Error al iniciar captura sistema: {e}")
                self._sys_capture = None
                self._system_queue = None
                system_queue = None
                self.statusBar().showMessage(
                    f"Audio del sistema no disponible: {e}. Solo micrófono activo."
                )

        # --- Worker ---
        from src.transcription.worker import SlidingWindowWorker
        self._worker = SlidingWindowWorker(
            mic_queue=self._audio_queue,
            engine=self._engine,
            mic_vad=self._mic_vad,
            config=self._config,
            system_queue=system_queue,
            system_vad=self._system_vad if system_queue else None,
        )
        self._worker.text_confirmed.connect(self._transcript_view.append_confirmed)
        self._worker.text_partial.connect(self._transcript_view.update_partial)
        self._worker.vad_activity.connect(self._update_vad_indicator)
        self._worker.status_changed.connect(self.statusBar().showMessage)
        self._worker.error_occurred.connect(
            lambda e: self.statusBar().showMessage(f"Error: {e}")
        )
        self._worker.start()

        self._is_running = True
        self.btn_detener.setEnabled(True)
        print(f"[MainWindow] Transcripción iniciada — mic: {device_index}, sistema: {system_queue is not None}")

    # ------------------------------------------------------------------ #
    # Detener
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_detener(self):
        if not self._is_running:
            return

        self.statusBar().showMessage("Deteniendo...")

        if self._worker is not None:
            self._worker.stop()
            self._worker = None

        if self._capture is not None:
            self._capture.stop()
            self._capture = None

        if self._sys_capture is not None:
            self._sys_capture.stop()
            self._sys_capture = None

        if self._mic_vad is not None:
            self._mic_vad.reset()

        if self._system_vad is not None:
            self._system_vad.reset()

        self._is_running = False
        self.btn_iniciar.setEnabled(True)
        self.btn_detener.setEnabled(False)
        self.cb_modelo.setEnabled(True)
        self.cb_idioma.setEnabled(True)
        self._update_vad_indicator("mic", False)
        self._update_vad_indicator("system", False)
        self.statusBar().showMessage("Detenido")
        print("[MainWindow] Transcripción detenida")

    @Slot()
    def _on_toggle_space(self):
        if self._is_running:
            self._on_detener()
        else:
            self._on_iniciar()

    @Slot()
    def _on_limpiar(self):
        self._transcript_view.clear_all()
        self.statusBar().showMessage("Transcripción limpiada")

    # ------------------------------------------------------------------ #
    # Exportación
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_exportar_txt(self):
        texto = self._transcript_view.get_all_text().strip()
        if not texto:
            QMessageBox.information(self, "Sin contenido", "No hay texto para exportar.")
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar transcripción", "", "Archivos de texto (*.txt)"
        )
        if ruta:
            try:
                from src.utils.export import export_to_txt
                from pathlib import Path
                export_to_txt(texto, Path(ruta))
                self.statusBar().showMessage(f"Exportado: {ruta}")
            except Exception as e:
                QMessageBox.critical(self, "Error al exportar", str(e))

    @Slot()
    def _on_exportar_srt(self):
        segments = self._transcript_view.get_segments()
        if not segments:
            QMessageBox.information(self, "Sin contenido", "No hay segmentos para exportar.")
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar subtítulos", "", "Subtítulos SRT (*.srt)"
        )
        if ruta:
            try:
                from src.utils.export import export_to_srt
                from pathlib import Path
                export_to_srt(segments, Path(ruta))
                self.statusBar().showMessage(f"SRT exportado: {ruta}")
            except Exception as e:
                QMessageBox.critical(self, "Error al exportar SRT", str(e))

    @Slot()
    def _on_abrir_settings(self):
        if self._config is None:
            QMessageBox.information(self, "Configuración",
                "No hay configuración disponible.")
            return
        from src.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            for k, v in dlg.get_values().items():
                setattr(self._config, k, v)
            self.statusBar().showMessage(
                "Configuración guardada. Reinicia la transcripción.")

    # ------------------------------------------------------------------ #
    # Indicadores VAD
    # ------------------------------------------------------------------ #
    @Slot(str, bool)
    def _update_vad_indicator(self, source: str, is_speech: bool):
        if source == "mic":
            color = "#2196F3" if is_speech else "#666"
            self._vad_mic.setStyleSheet(f"background:{color};border-radius:8px;")
        elif source == "system":
            color = "#4CAF50" if is_speech else "#666"
            self._vad_system.setStyleSheet(f"background:{color};border-radius:8px;")

    # ------------------------------------------------------------------ #
    # Cierre limpio
    # ------------------------------------------------------------------ #
    def closeEvent(self, event):
        if self._is_running:
            self._on_detener()
        for loader in (self._vad_loader, self._model_loader):
            if loader and loader.isRunning():
                loader.wait()
        event.accept()
