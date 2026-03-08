# -*- coding: utf-8 -*-
import queue
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QPushButton, QComboBox, QLabel,
    QFrame, QSizePolicy, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QSize, Slot, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut

from src.ui.transcript_view import TranscriptView
from src.audio.capture import AudioCapture, AudioConfig


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


class ModelLoader(QThread):
    loaded  = Signal(object)
    failed  = Signal(str)
    progress = Signal(str)

    def __init__(self, model_size: str, compute_type: str, language: str):
        super().__init__()
        self._model_size   = model_size
        self._compute_type = compute_type
        self._language     = language

    def run(self):
        try:
            self.progress.emit(f"Cargando modelo '{self._model_size}'...")
            from src.transcription.engine import TranscriptionEngine
            engine = TranscriptionEngine(
                model_size=self._model_size,
                compute_type=self._compute_type,
                language=self._language,
            )
            self.loaded.emit(engine)
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self._config     = config
        self._capture    = None
        self._vad        = None
        self._engine     = None
        self._worker     = None
        self._audio_queue = None
        self._is_running  = False

        # loaders
        self._vad_loader   = None
        self._model_loader = None

        self.setWindowTitle("Transcriptor en Tiempo Real")
        self.resize(960, 640)
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._populate_devices()

        # Cargar VAD al iniciar
        self.statusBar().showMessage("Cargando VAD...")
        self._load_vad()

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

        self._vad_indicator = QFrame()
        self._vad_indicator.setFixedSize(16, 16)
        self._vad_indicator.setStyleSheet("background:#666;border-radius:8px;")
        toolbar.addWidget(self._vad_indicator)

        lbl_vad = QLabel("  Voz")
        lbl_vad.setStyleSheet("color:#555;font-size:12px;")
        toolbar.addWidget(lbl_vad)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # Controles
        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)

        ctrl.addWidget(QLabel("Modelo:"))
        self.cb_modelo = QComboBox()
        self.cb_modelo.addItems(MODELOS)
        self.cb_modelo.setCurrentText("small")
        self.cb_modelo.setMinimumWidth(140)
        ctrl.addWidget(self.cb_modelo)

        ctrl.addWidget(QLabel("Dispositivo audio:"))
        self.cb_dispositivo = QComboBox()
        self.cb_dispositivo.setMinimumWidth(220)
        ctrl.addWidget(self.cb_dispositivo)

        ctrl.addWidget(QLabel("Idioma:"))
        self.cb_idioma = QComboBox()
        for nombre, codigo in IDIOMAS:
            self.cb_idioma.addItem(nombre, codigo)
        self.cb_idioma.setCurrentIndex(0)
        ctrl.addWidget(self.cb_idioma)

        ctrl.addStretch()
        root.addLayout(ctrl)

        self._transcript_view = TranscriptView()
        self._transcript_view.setMinimumHeight(400)
        root.addWidget(self._transcript_view, stretch=1)

        self.btn_limpiar.clicked.connect(self._on_limpiar)
        self.btn_iniciar.clicked.connect(self._on_iniciar)
        self.btn_detener.clicked.connect(self._on_detener)

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
            cap   = AudioCapture(AudioConfig(), queue.Queue())
            devs  = cap.list_devices()
            self.cb_dispositivo.clear()
            self.cb_dispositivo.addItem("Dispositivo predeterminado", None)
            for d in devs:
                self.cb_dispositivo.addItem(
                    f"[{d['index']}] {d['name']} ({d['channels']}ch)", d["index"]
                )
        except Exception as e:
            self.cb_dispositivo.addItem("Error al listar dispositivos", None)
            print(f"[MainWindow] Error listando dispositivos: {e}")

    def _selected_device(self) -> int | None:
        return self.cb_dispositivo.currentData()

    # ------------------------------------------------------------------ #
    # Carga VAD en background
    # ------------------------------------------------------------------ #
    def _load_vad(self):
        self._vad_loader = VADLoader(threshold=0.5)
        self._vad_loader.loaded.connect(self._on_vad_loaded)
        self._vad_loader.failed.connect(self._on_vad_failed)
        self._vad_loader.start()

    @Slot(object)
    def _on_vad_loaded(self, vad):
        self._vad = vad
        self.statusBar().showMessage("VAD listo. Selecciona un modelo y pulsa Iniciar.")
        self.btn_iniciar.setEnabled(True)
        print("[MainWindow] Silero VAD cargado OK")

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
        compute_type = "int8"

        # Deshabilitar controles mientras carga el modelo
        self.btn_iniciar.setEnabled(False)
        self.cb_modelo.setEnabled(False)
        self.cb_idioma.setEnabled(False)

        self._model_loader = ModelLoader(model_size, compute_type, language)
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
        """Arranca captura de audio + SlidingWindowWorker."""
        device_index      = self._selected_device()
        self._audio_queue = queue.Queue(maxsize=500)
        audio_cfg         = AudioConfig()
        self._capture     = AudioCapture(audio_cfg, self._audio_queue)

        try:
            self._capture.start(device_index)
        except Exception as e:
            QMessageBox.critical(self, "Error de audio",
                f"No se pudo iniciar la captura:\n{e}")
            self._capture = None
            self.btn_iniciar.setEnabled(True)
            self.cb_modelo.setEnabled(True)
            self.cb_idioma.setEnabled(True)
            return

        from src.transcription.worker import SlidingWindowWorker
        self._worker = SlidingWindowWorker(
            self._audio_queue, self._engine, self._vad, self._config
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
        print(f"[MainWindow] Transcripción iniciada — dispositivo: {device_index}")

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

        if self._vad is not None:
            self._vad.reset()

        self._is_running = False
        self.btn_iniciar.setEnabled(True)
        self.btn_detener.setEnabled(False)
        self.cb_modelo.setEnabled(True)
        self.cb_idioma.setEnabled(True)
        self._update_vad_indicator(False)
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
        QMessageBox.information(self, "Exportar SRT",
            "Exportación SRT con timestamps disponible en Fase 7.")

    @Slot()
    def _on_abrir_settings(self):
        if self._config is None:
            QMessageBox.information(self, "Configuración",
                "Configuración disponible en Fase 6.")
            return
        from src.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            for k, v in dlg.get_values().items():
                setattr(self._config, k, v)
            self.statusBar().showMessage(
                "Configuración guardada. Reinicia la transcripción.")

    # ------------------------------------------------------------------ #
    # Indicador VAD
    # ------------------------------------------------------------------ #
    @Slot(bool)
    def _update_vad_indicator(self, is_speech: bool):
        color = "#4CAF50" if is_speech else "#666"
        self._vad_indicator.setStyleSheet(
            f"background:{color};border-radius:8px;"
        )

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
