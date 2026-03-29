# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox,
    QDialogButtonBox, QGroupBox, QDoubleSpinBox, QSpinBox, QLabel
)
from PySide6.QtCore import Qt


class SettingsDialog(QDialog):
    """Diálogo de configuración de la aplicación."""

    MODELOS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
    COMPUTE_TYPES = ["int8", "float16", "float32"]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.setMinimumWidth(400)
        self._config = config
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Grupo: Modelo
        grp_modelo = QGroupBox("Modelo de Transcripción")
        form_modelo = QFormLayout(grp_modelo)

        self.cb_modelo = QComboBox()
        self.cb_modelo.addItems(self.MODELOS)
        self.cb_modelo.setCurrentText(self._config.model_size)
        form_modelo.addRow("Modelo Whisper:", self.cb_modelo)

        self.cb_compute = QComboBox()
        self.cb_compute.addItems(self.COMPUTE_TYPES)
        self.cb_compute.setCurrentText(self._config.compute_type)
        form_modelo.addRow("Tipo de cómputo:", self.cb_compute)

        layout.addWidget(grp_modelo)

        # Grupo: VAD
        grp_vad = QGroupBox("Detección de Voz (VAD)")
        form_vad = QFormLayout(grp_vad)

        self.sb_threshold = QDoubleSpinBox()
        self.sb_threshold.setRange(0.1, 0.95)
        self.sb_threshold.setSingleStep(0.05)
        self.sb_threshold.setDecimals(2)
        self.sb_threshold.setValue(self._config.vad_threshold)
        form_vad.addRow("Umbral de voz:", self.sb_threshold)

        layout.addWidget(grp_vad)

        # Grupo: Ventana deslizante
        grp_window = QGroupBox("Ventana Deslizante")
        form_window = QFormLayout(grp_window)

        self.sb_window = QDoubleSpinBox()
        self.sb_window.setRange(5.0, 30.0)
        self.sb_window.setSingleStep(1.0)
        self.sb_window.setSuffix(" seg")
        self.sb_window.setValue(self._config.window_duration)
        form_window.addRow("Ventana de audio:", self.sb_window)

        self.sb_interval = QDoubleSpinBox()
        self.sb_interval.setRange(1.0, 10.0)
        self.sb_interval.setSingleStep(0.5)
        self.sb_interval.setSuffix(" seg")
        self.sb_interval.setValue(self._config.transcribe_interval)
        form_window.addRow("Intervalo transcripción:", self.sb_interval)

        self.sb_max_buffer = QDoubleSpinBox()
        self.sb_max_buffer.setRange(30.0, 120.0)
        self.sb_max_buffer.setSingleStep(10.0)
        self.sb_max_buffer.setSuffix(" seg")
        self.sb_max_buffer.setValue(self._config.max_buffer_seconds)
        form_window.addRow("Buffer máximo:", self.sb_max_buffer)

        layout.addWidget(grp_window)

        # Botones
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> dict:
        return {
            "model_size": self.cb_modelo.currentText(),
            "compute_type": self.cb_compute.currentText(),
            "vad_threshold": self.sb_threshold.value(),
            "window_duration": self.sb_window.value(),
            "transcribe_interval": self.sb_interval.value(),
            "max_buffer_seconds": self.sb_max_buffer.value(),
        }
