# -*- coding: utf-8 -*-
"""
SessionWindow — Ventana de sesión en vivo con copiloto IA.

Recibe patient_id y db_manager. Integra la transcripción dual existente
con un panel lateral de copiloto y notas manuales.
"""
import queue
import time as _time

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTextEdit, QPushButton, QLabel,
    QMessageBox, QFrame, QComboBox, QCheckBox,
)
from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor

from src.db.manager import DBManager
from src.utils.config import TranscriberConfig
from src.ui.transcript_view import TranscriptView
from src.audio.capture import AudioCapture, AudioConfig
from src.audio.system_capture import SystemAudioCapture, SystemAudioConfig


# Reutilizamos los loaders de main_window
from src.ui.main_window import VADLoader, DualVADLoader, ModelLoader

MODELOS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
IDIOMAS = [("Español", "es"), ("Inglés", "en"), ("Automático", None)]


class SessionWindow(QMainWindow):
    closed = Signal()  # emitida al cerrar la ventana

    def __init__(self, db: DBManager, patient_id: int, config: TranscriberConfig | None = None, parent=None):
        super().__init__(parent)
        self._db = db
        self._patient_id = patient_id
        self._config = config or TranscriberConfig()

        # Estado de sesión
        patient = self._db.get_patient(patient_id)
        self._patient_name = patient["name"] if patient else f"Paciente #{patient_id}"
        self._diagnosis = patient.get("diagnosis", "") if patient else ""
        self._general_notes = patient.get("general_notes", "") if patient else ""
        self._session_number = self._db.get_next_session_number(patient_id)

        # Audio / transcripción
        self._capture = None
        self._sys_capture = None
        self._mic_vad = None
        self._system_vad = None
        self._engine = None
        self._worker = None
        self._audio_queue = None
        self._system_queue = None
        self._is_running = False
        self._is_paused = False

        # Copiloto
        self._copilot_worker = None

        # Loaders
        self._vad_loader = None
        self._model_loader = None

        # Timer de sesión
        self._session_start_time = None
        self._elapsed_seconds = 0
        self._timer = QTimer()
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_timer)

        # Textos acumulados
        self._transcript_psi = ""
        self._transcript_pac = ""
        self._all_ai_suggestions = []

        self.setWindowTitle(f"Sesión #{self._session_number} — {self._patient_name}")
        self.resize(1100, 720)
        self._build_ui()
        self._populate_devices()

        # Cargar VAD
        vad_threshold = self._config.vad_threshold
        self.statusBar().showMessage("Cargando VAD...")
        self._load_vad(vad_threshold)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Barra superior ---
        top = QHBoxLayout()

        title = QLabel(f"Sesión #{self._session_number} — {self._patient_name}")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        title.setFont(font)
        top.addWidget(title, 1)

        # Controles de audio
        top.addWidget(QLabel("Modelo:"))
        self.cb_modelo = QComboBox()
        self.cb_modelo.addItems(MODELOS)
        self.cb_modelo.setCurrentText(self._config.model_size)
        self.cb_modelo.setMinimumWidth(100)
        top.addWidget(self.cb_modelo)

        top.addWidget(QLabel("Mic:"))
        self.cb_dispositivo = QComboBox()
        self.cb_dispositivo.setMinimumWidth(160)
        top.addWidget(self.cb_dispositivo)

        top.addWidget(QLabel("Idioma:"))
        self.cb_idioma = QComboBox()
        for nombre, codigo in IDIOMAS:
            self.cb_idioma.addItem(nombre, codigo)
        top.addWidget(self.cb_idioma)

        self.chk_sistema = QCheckBox("Audio sistema")
        self.chk_sistema.setChecked(self._config.enable_system_audio)
        top.addWidget(self.chk_sistema)

        self.cb_sistema = QComboBox()
        self.cb_sistema.setMinimumWidth(140)
        top.addWidget(self.cb_sistema)

        root.addLayout(top)

        # --- Botones de control ---
        btn_row = QHBoxLayout()

        self.btn_iniciar = QPushButton("▶ Iniciar")
        self.btn_iniciar.setEnabled(False)
        self.btn_iniciar.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border-radius:4px;padding:4px 14px;font-weight:bold;}"
            "QPushButton:hover{background:#43A047;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        self.btn_iniciar.clicked.connect(self._on_iniciar)
        btn_row.addWidget(self.btn_iniciar)

        self.btn_pausar = QPushButton("⏸ Pausar")
        self.btn_pausar.setEnabled(False)
        self.btn_pausar.setStyleSheet(
            "QPushButton{background:#FF9800;color:white;border-radius:4px;padding:4px 14px;font-weight:bold;}"
            "QPushButton:hover{background:#F57C00;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        self.btn_pausar.clicked.connect(self._on_pausar)
        btn_row.addWidget(self.btn_pausar)

        self.btn_finalizar = QPushButton("⏹ Finalizar")
        self.btn_finalizar.setStyleSheet(
            "QPushButton{background:#F44336;color:white;border-radius:4px;padding:4px 14px;font-weight:bold;}"
            "QPushButton:hover{background:#E53935;}"
        )
        self.btn_finalizar.clicked.connect(self._on_finalizar)
        btn_row.addWidget(self.btn_finalizar)

        btn_row.addStretch()

        # LEDs VAD
        self._vad_mic = QFrame()
        self._vad_mic.setFixedSize(14, 14)
        self._vad_mic.setStyleSheet("background:#666;border-radius:7px;")
        btn_row.addWidget(self._vad_mic)
        btn_row.addWidget(QLabel("Mic"))

        self._vad_system = QFrame()
        self._vad_system.setFixedSize(14, 14)
        self._vad_system.setStyleSheet("background:#666;border-radius:7px;")
        btn_row.addWidget(self._vad_system)
        btn_row.addWidget(QLabel("Sistema"))

        btn_row.addWidget(QLabel("  "))
        self._lbl_timer = QLabel("00:00:00")
        self._lbl_timer.setStyleSheet("font-weight:bold; font-size:14px;")
        btn_row.addWidget(self._lbl_timer)

        root.addLayout(btn_row)

        # --- Splitter principal: transcripción | copiloto ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Panel izquierdo: transcripción
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        lbl_trans = QLabel("Transcripción")
        lbl_trans.setStyleSheet("font-weight:bold; font-size:13px;")
        left_layout.addWidget(lbl_trans)

        self._transcript_view = TranscriptView()
        left_layout.addWidget(self._transcript_view, 1)

        splitter.addWidget(left)

        # Panel derecho: copiloto
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        lbl_copilot = QLabel("Copiloto")
        lbl_copilot.setStyleSheet("font-weight:bold; font-size:13px; color:#9C27B0;")
        right_layout.addWidget(lbl_copilot)

        self._copilot_view = QTextEdit()
        self._copilot_view.setReadOnly(True)
        self._copilot_view.setStyleSheet("background:#f5f0ff; color:#1a1a1a; border:1px solid #ddd; border-radius:4px;")
        self._copilot_view.setPlaceholderText("Las sugerencias del copiloto aparecerán aquí...")
        right_layout.addWidget(self._copilot_view, 1)

        splitter.addWidget(right)
        splitter.setSizes([700, 300])

        root.addWidget(splitter, 1)

        # --- Notas manuales ---
        lbl_notes = QLabel("Notas del psicólogo:")
        lbl_notes.setStyleSheet("font-weight:bold;")
        root.addWidget(lbl_notes)

        self._notes_edit = QTextEdit()
        self._notes_edit.setFixedHeight(90)
        self._notes_edit.setPlaceholderText("Escribe tus notas de la sesión aquí...")
        root.addWidget(self._notes_edit)

    def _populate_devices(self):
        try:
            cap = AudioCapture(AudioConfig(), queue.Queue())
            devs = cap.list_devices()
            self.cb_dispositivo.clear()
            self.cb_dispositivo.addItem("Predeterminado", None)
            for d in devs:
                self.cb_dispositivo.addItem(
                    f"[{d['index']}] {d['name']} ({d['channels']}ch)", d["index"]
                )
        except Exception:
            self.cb_dispositivo.addItem("Error al listar", None)

        try:
            cap = SystemAudioCapture(SystemAudioConfig(), queue.Queue())
            devs = cap.list_loopback_devices()
            self.cb_sistema.clear()
            if not devs:
                self.cb_sistema.addItem("No disponible", None)
                self.chk_sistema.setEnabled(False)
                self.chk_sistema.setChecked(False)
            else:
                self.cb_sistema.addItem("Auto-detectar", None)
                for d in devs:
                    self.cb_sistema.addItem(
                        f"[{d['index']}] {d['name']}", d["index"]
                    )
        except Exception:
            self.cb_sistema.addItem("Error", None)

    # ------------------------------------------------------------------
    # VAD
    # ------------------------------------------------------------------
    def _load_vad(self, threshold: float):
        if self.chk_sistema.isChecked():
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
        self._mic_vad = vad
        self._system_vad = None
        self.statusBar().showMessage("VAD listo. Pulsa Iniciar.")
        self.btn_iniciar.setEnabled(True)

    @Slot(object, object)
    def _on_dual_vad_loaded(self, mic_vad, system_vad):
        self._mic_vad = mic_vad
        self._system_vad = system_vad
        self.statusBar().showMessage("VAD dual listo. Pulsa Iniciar.")
        self.btn_iniciar.setEnabled(True)

    @Slot(str)
    def _on_vad_failed(self, error: str):
        self.statusBar().showMessage(f"Error VAD: {error}")
        QMessageBox.critical(self, "Error VAD", error)
        self.btn_iniciar.setEnabled(True)

    # ------------------------------------------------------------------
    # Iniciar transcripción
    # ------------------------------------------------------------------
    @Slot()
    def _on_iniciar(self):
        if self._is_running:
            return

        model_size = self.cb_modelo.currentText()
        language = self.cb_idioma.currentData() or "es"
        compute_type = self._config.compute_type

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
        self._start_capture_and_worker()

    @Slot(str)
    def _on_model_failed(self, error: str):
        self.statusBar().showMessage(f"Error modelo: {error}")
        QMessageBox.critical(self, "Error al cargar modelo", error)
        self.btn_iniciar.setEnabled(True)
        self.cb_modelo.setEnabled(True)
        self.cb_idioma.setEnabled(True)

    def _start_capture_and_worker(self):
        device_index = self.cb_dispositivo.currentData()

        # Micrófono
        self._audio_queue = queue.Queue(maxsize=500)
        self._capture = AudioCapture(AudioConfig(), self._audio_queue)
        try:
            self._capture.start(device_index)
        except Exception as e:
            QMessageBox.critical(self, "Error de audio", str(e))
            self.btn_iniciar.setEnabled(True)
            self.cb_modelo.setEnabled(True)
            self.cb_idioma.setEnabled(True)
            return

        # Audio del sistema (opcional)
        system_queue = None
        if self.chk_sistema.isChecked() and self._system_vad is not None:
            system_device = self.cb_sistema.currentData()
            self._system_queue = queue.Queue(maxsize=500)
            self._sys_capture = SystemAudioCapture(SystemAudioConfig(), self._system_queue)
            try:
                self._sys_capture.start(system_device)
                system_queue = self._system_queue
            except Exception:
                self._sys_capture = None
                self._system_queue = None

        # Worker de transcripción
        from src.transcription.worker import SlidingWindowWorker
        self._worker = SlidingWindowWorker(
            mic_queue=self._audio_queue,
            engine=self._engine,
            mic_vad=self._mic_vad,
            config=self._config,
            system_queue=system_queue,
            system_vad=self._system_vad if system_queue else None,
        )
        self._worker.text_confirmed.connect(self._on_text_confirmed)
        self._worker.text_partial.connect(self._transcript_view.update_partial)
        self._worker.vad_activity.connect(self._update_vad_indicator)
        self._worker.status_changed.connect(self.statusBar().showMessage)
        self._worker.error_occurred.connect(
            lambda e: self.statusBar().showMessage(f"Error: {e}")
        )
        self._worker.start()

        # Copiloto IA
        self._start_copilot()

        # Timer
        self._session_start_time = _time.monotonic()
        self._timer.start()

        self._is_running = True
        self.btn_iniciar.setEnabled(False)
        self.btn_pausar.setEnabled(True)
        self.statusBar().showMessage("Escuchando...")

    # ------------------------------------------------------------------
    # Copiloto IA
    # ------------------------------------------------------------------
    def _start_copilot(self):
        from src.ai.copilot import CopilotWorker
        from src.ui.config_dialog import load_ai_settings

        settings = load_ai_settings()
        has_key = bool(settings.get("openai_api_key") or settings.get("azure_api_key")
                       or settings.get("ai_provider") == "ollama")
        if not has_key:
            self._copilot_view.setPlainText("Configure un proveedor de IA en Configuración para activar el copiloto.")
            return

        # Historial de sesiones previas (últimos resúmenes)
        sessions = self._db.get_sessions_by_patient(self._patient_id)
        history = []
        for s in sessions[-3:]:
            notes = s.get("manual_notes") or ""
            ai = s.get("ai_suggestions") or ""
            if notes or ai:
                history.append(f"S#{s['session_number']}: {notes[:200]} | IA: {ai[:200]}")

        self._copilot_worker = CopilotWorker(
            patient_name=self._patient_name,
            diagnosis=self._diagnosis,
            general_notes=self._general_notes,
            session_history=history,
        )
        self._copilot_worker.chunk_received.connect(self._on_copilot_chunk)
        self._copilot_worker.analysis_done.connect(self._on_copilot_done)
        self._copilot_worker.error_occurred.connect(self._on_copilot_error)
        self._copilot_worker.start()

    @Slot(str)
    def _on_copilot_chunk(self, text: str):
        cursor = self._copilot_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._copilot_view.setTextCursor(cursor)
        self._copilot_view.ensureCursorVisible()

    @Slot(str)
    def _on_copilot_done(self, full_text: str):
        self._all_ai_suggestions.append(full_text)
        # Separador visual para el siguiente análisis
        self._copilot_view.append("\n" + "─" * 40 + "\n")

    @Slot(str)
    def _on_copilot_error(self, error: str):
        self._copilot_view.append(f"\n⚠ Error: {error}\n")

    # ------------------------------------------------------------------
    # Señales de transcripción
    # ------------------------------------------------------------------
    @Slot(str, str)
    def _on_text_confirmed(self, label: str, text: str):
        self._transcript_view.append_confirmed(label, text)

        # Acumular texto por fuente
        psi_label = self._config.mic_label
        pac_label = self._config.system_label

        if label == psi_label:
            self._transcript_psi += " " + text
        elif label == pac_label:
            self._transcript_pac += " " + text

        # Alimentar copiloto con todo el texto (ambas fuentes)
        if self._copilot_worker is not None:
            self._copilot_worker.append_patient_text(text)

    @Slot(str, bool)
    def _update_vad_indicator(self, source: str, is_speech: bool):
        if source == "mic":
            color = "#2196F3" if is_speech else "#666"
            self._vad_mic.setStyleSheet(f"background:{color};border-radius:7px;")
        elif source == "system":
            color = "#4CAF50" if is_speech else "#666"
            self._vad_system.setStyleSheet(f"background:{color};border-radius:7px;")

    # ------------------------------------------------------------------
    # Pausar / Reanudar
    # ------------------------------------------------------------------
    @Slot()
    def _on_pausar(self):
        if not self._is_running:
            return
        if not self._is_paused:
            self._timer.stop()
            self._is_paused = True
            self.btn_pausar.setText("▶ Reanudar")
            self.statusBar().showMessage("Pausado")
        else:
            self._timer.start()
            self._is_paused = False
            self.btn_pausar.setText("⏸ Pausar")
            self.statusBar().showMessage("Escuchando...")

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------
    def _update_timer(self):
        if self._session_start_time is not None:
            self._elapsed_seconds = int(_time.monotonic() - self._session_start_time)
            h = self._elapsed_seconds // 3600
            m = (self._elapsed_seconds % 3600) // 60
            s = self._elapsed_seconds % 60
            self._lbl_timer.setText(f"{h:02d}:{m:02d}:{s:02d}")

    # ------------------------------------------------------------------
    # Finalizar sesión
    # ------------------------------------------------------------------
    @Slot()
    def _on_finalizar(self):
        if self._is_running:
            self._stop_all()

        # Guardar en BD
        manual_notes = self._notes_edit.toPlainText().strip()
        ai_text = "\n---\n".join(self._all_ai_suggestions)

        self._db.add_session(
            patient_id=self._patient_id,
            session_number=self._session_number,
            manual_notes=manual_notes,
            transcript_patient=self._transcript_pac.strip(),
            transcript_psychologist=self._transcript_psi.strip(),
            ai_suggestions=ai_text,
            duration_seconds=self._elapsed_seconds,
        )

        QMessageBox.information(
            self, "Sesión guardada",
            f"Sesión #{self._session_number} guardada correctamente.\n"
            f"Duración: {self._elapsed_seconds // 60} minutos."
        )
        self.close()

    def _stop_all(self):
        self._timer.stop()

        if self._copilot_worker is not None:
            self._copilot_worker.stop()
            self._copilot_worker = None

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

    # ------------------------------------------------------------------
    # Cierre con confirmación
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        if self._is_running:
            resp = QMessageBox.question(
                self, "Sesión activa",
                "¿Deseas guardar la sesión antes de cerrar?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if resp == QMessageBox.StandardButton.Save:
                self._on_finalizar()
                event.accept()
                return
            elif resp == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            else:
                self._stop_all()

        # Esperar loaders
        for loader in (self._vad_loader, self._model_loader):
            if loader and loader.isRunning():
                loader.wait()

        self.closed.emit()
        event.accept()
