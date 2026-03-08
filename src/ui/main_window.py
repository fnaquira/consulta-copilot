# -*- coding: utf-8 -*-
import queue
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QPushButton, QComboBox, QLabel,
    QFrame, QSizePolicy, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QSize, Slot
from PySide6.QtGui import QAction, QKeySequence, QShortcut

from src.ui.transcript_view import TranscriptView
from src.audio.capture import AudioCapture, AudioConfig


MODELOS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
IDIOMAS = [("Español", "es"), ("Inglés", "en"), ("Automático", None)]


class MainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self._config = config
        self._capture = None
        self._worker = None
        self._audio_queue = None
        self._engine = None
        self._vad = None
        self._is_running = False

        self.setWindowTitle("Transcriptor en Tiempo Real")
        self.resize(960, 640)
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._populate_devices()
        self.statusBar().showMessage("Listo")

    # -------------------------------------------------------------------------
    # Construcción de la UI
    # -------------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Toolbar principal ---
        toolbar = QToolBar("Principal")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        self.btn_iniciar = QPushButton("▶  Iniciar")
        self.btn_iniciar.setFixedHeight(32)
        self.btn_iniciar.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; border-radius: 4px; padding: 0 12px; font-weight: bold; }"
            "QPushButton:hover { background: #43A047; }"
            "QPushButton:disabled { background: #aaa; }"
        )
        toolbar.addWidget(self.btn_iniciar)

        self.btn_detener = QPushButton("⏹  Detener")
        self.btn_detener.setFixedHeight(32)
        self.btn_detener.setEnabled(False)
        self.btn_detener.setStyleSheet(
            "QPushButton { background: #F44336; color: white; border-radius: 4px; padding: 0 12px; font-weight: bold; }"
            "QPushButton:hover { background: #E53935; }"
            "QPushButton:disabled { background: #aaa; }"
        )
        toolbar.addWidget(self.btn_detener)

        toolbar.addSeparator()

        self.btn_limpiar = QPushButton("🗑  Limpiar")
        self.btn_limpiar.setFixedHeight(32)
        self.btn_limpiar.setStyleSheet(
            "QPushButton { background: #9E9E9E; color: white; border-radius: 4px; padding: 0 12px; }"
            "QPushButton:hover { background: #757575; }"
        )
        toolbar.addWidget(self.btn_limpiar)

        toolbar.addSeparator()

        # Indicador VAD
        self._vad_indicator = QFrame()
        self._vad_indicator.setFixedSize(16, 16)
        self._vad_indicator.setStyleSheet("background: #666; border-radius: 8px;")
        toolbar.addWidget(self._vad_indicator)

        lbl_vad = QLabel("  Voz")
        lbl_vad.setStyleSheet("color: #555; font-size: 12px;")
        toolbar.addWidget(lbl_vad)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # --- Panel de controles ---
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(12)

        ctrl_bar.addWidget(QLabel("Modelo:"))
        self.cb_modelo = QComboBox()
        self.cb_modelo.addItems(MODELOS)
        self.cb_modelo.setCurrentText("small")
        self.cb_modelo.setMinimumWidth(140)
        ctrl_bar.addWidget(self.cb_modelo)

        ctrl_bar.addWidget(QLabel("Dispositivo audio:"))
        self.cb_dispositivo = QComboBox()
        self.cb_dispositivo.setMinimumWidth(220)
        ctrl_bar.addWidget(self.cb_dispositivo)

        ctrl_bar.addWidget(QLabel("Idioma:"))
        self.cb_idioma = QComboBox()
        for nombre, codigo in IDIOMAS:
            self.cb_idioma.addItem(nombre, codigo)
        self.cb_idioma.setCurrentIndex(0)
        ctrl_bar.addWidget(self.cb_idioma)

        ctrl_bar.addStretch()

        root.addLayout(ctrl_bar)

        # --- Área de transcripción ---
        self._transcript_view = TranscriptView()
        self._transcript_view.setMinimumHeight(400)
        root.addWidget(self._transcript_view, stretch=1)

        # --- Conexiones básicas de UI ---
        self.btn_limpiar.clicked.connect(self._on_limpiar)
        self.btn_iniciar.clicked.connect(self._on_iniciar)
        self.btn_detener.clicked.connect(self._on_detener)

    def _build_menu(self):
        menubar = self.menuBar()

        menu_archivo = menubar.addMenu("Archivo")

        act_exportar_txt = QAction("Exportar como TXT...", self)
        act_exportar_txt.setShortcut(QKeySequence("Ctrl+S"))
        act_exportar_txt.triggered.connect(self._on_exportar_txt)
        menu_archivo.addAction(act_exportar_txt)

        act_exportar_srt = QAction("Exportar como SRT...", self)
        act_exportar_srt.triggered.connect(self._on_exportar_srt)
        menu_archivo.addAction(act_exportar_srt)

        menu_archivo.addSeparator()

        act_salir = QAction("Salir", self)
        act_salir.setShortcut(QKeySequence("Ctrl+Q"))
        act_salir.triggered.connect(self.close)
        menu_archivo.addAction(act_salir)

        menu_config = menubar.addMenu("Configuración")
        act_settings = QAction("Preferencias...", self)
        act_settings.triggered.connect(self._on_abrir_settings)
        menu_config.addAction(act_settings)

    def _build_shortcuts(self):
        sc_space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        sc_space.activated.connect(self._on_toggle_space)

    # -------------------------------------------------------------------------
    # Dispositivos de audio
    # -------------------------------------------------------------------------
    def _populate_devices(self):
        """Llena el combo de dispositivos con los inputs reales del sistema."""
        try:
            temp_cfg = AudioConfig()
            temp_capture = AudioCapture(temp_cfg, queue.Queue())
            devices = temp_capture.list_devices()
            self.cb_dispositivo.clear()
            self.cb_dispositivo.addItem("Dispositivo predeterminado", None)
            for dev in devices:
                label = f"[{dev['index']}] {dev['name']} ({dev['channels']}ch)"
                self.cb_dispositivo.addItem(label, dev["index"])
            self.statusBar().showMessage(f"{len(devices)} dispositivo(s) de entrada encontrados")
        except Exception as e:
            self.cb_dispositivo.addItem("Error al listar dispositivos", None)
            self.statusBar().showMessage(f"Error al listar dispositivos: {e}")

    def _selected_device_index(self) -> int | None:
        return self.cb_dispositivo.currentData()

    # -------------------------------------------------------------------------
    # Iniciar / Detener captura
    # -------------------------------------------------------------------------
    @Slot()
    def _on_iniciar(self):
        if self._is_running:
            return

        device_index = self._selected_device_index()
        self._audio_queue = queue.Queue(maxsize=500)
        audio_cfg = AudioConfig()
        self._capture = AudioCapture(audio_cfg, self._audio_queue)

        try:
            self._capture.start(device_index)
        except Exception as e:
            QMessageBox.critical(self, "Error de audio", f"No se pudo iniciar la captura:\n{e}")
            self._capture = None
            return

        self._is_running = True
        self.btn_iniciar.setEnabled(False)
        self.btn_detener.setEnabled(True)
        self.statusBar().showMessage("Capturando audio... (ver consola para chunks)")
        print(f"[Fase 2] Captura iniciada — dispositivo: {device_index}")

    @Slot()
    def _on_detener(self):
        if not self._is_running:
            return

        if self._worker is not None:
            self._worker.stop()
            self._worker = None

        if self._capture is not None:
            self._capture.stop()
            self._capture = None

        self._is_running = False
        self.btn_iniciar.setEnabled(True)
        self.btn_detener.setEnabled(False)
        self._update_vad_indicator(False)
        self.statusBar().showMessage("Detenido")
        print("[Fase 2] Captura detenida")

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

    # -------------------------------------------------------------------------
    # Exportación
    # -------------------------------------------------------------------------
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
        QMessageBox.information(
            self, "Exportar SRT",
            "La exportación SRT con timestamps estará disponible en Fase 7."
        )

    @Slot()
    def _on_abrir_settings(self):
        if self._config is None:
            QMessageBox.information(self, "Configuración", "Configuración disponible en Fase 6.")
            return
        from src.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            valores = dlg.get_values()
            for k, v in valores.items():
                setattr(self._config, k, v)
            self.statusBar().showMessage("Configuración guardada. Reinicia la transcripción.")

    # -------------------------------------------------------------------------
    # VAD indicator (se usará en Fase 3)
    # -------------------------------------------------------------------------
    @Slot(bool)
    def _update_vad_indicator(self, is_speech: bool):
        if is_speech:
            self._vad_indicator.setStyleSheet("background: #4CAF50; border-radius: 8px;")
        else:
            self._vad_indicator.setStyleSheet("background: #666; border-radius: 8px;")

    # -------------------------------------------------------------------------
    # Cierre limpio
    # -------------------------------------------------------------------------
    def closeEvent(self, event):
        if self._is_running:
            self._on_detener()
        event.accept()
