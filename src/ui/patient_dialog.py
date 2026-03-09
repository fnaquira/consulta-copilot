# -*- coding: utf-8 -*-
"""
PatientDialog — Crear o editar un paciente.
"""
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QSpinBox, QComboBox, QTextEdit, QVBoxLayout, QMessageBox,
)
from src.db.manager import DBManager


class PatientDialog(QDialog):
    def __init__(self, db: DBManager, mode: str = "create", patient_id: int | None = None, parent=None):
        super().__init__(parent)
        self._db = db
        self._mode = mode
        self._patient_id = patient_id

        self.setWindowTitle("Nuevo Paciente" if mode == "create" else "Editar Paciente")
        self.setMinimumWidth(420)
        self._build_ui()

        if mode == "edit" and patient_id is not None:
            self._load_patient(patient_id)

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Nombre completo (requerido)")
        form.addRow("Nombre:", self._name)

        self._age = QSpinBox()
        self._age.setRange(0, 120)
        self._age.setSpecialValueText("—")   # 0 = sin especificar
        form.addRow("Edad:", self._age)

        self._gender = QComboBox()
        self._gender.addItems(["", "Masculino", "Femenino", "Otro"])
        form.addRow("Género:", self._gender)

        self._diagnosis = QLineEdit()
        self._diagnosis.setPlaceholderText("Diagnóstico principal")
        form.addRow("Diagnóstico:", self._diagnosis)

        self._notes = QTextEdit()
        self._notes.setPlaceholderText("Notas generales del paciente...")
        self._notes.setFixedHeight(100)
        form.addRow("Notas:", self._notes)

        layout.addLayout(form)

        btn_label = "Crear" if self._mode == "create" else "Guardar"
        buttons = QDialogButtonBox(parent=self)
        buttons.addButton(btn_label, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_patient(self, patient_id: int):
        patient = self._db.get_patient(patient_id)
        if not patient:
            return
        self._name.setText(patient.get("name", ""))
        self._age.setValue(patient.get("age") or 0)
        gender = patient.get("gender") or ""
        idx = self._gender.findText(gender)
        self._gender.setCurrentIndex(max(idx, 0))
        self._diagnosis.setText(patient.get("diagnosis") or "")
        self._notes.setPlainText(patient.get("general_notes") or "")

    def _on_accept(self):
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Campo requerido", "El nombre del paciente no puede estar vacío.")
            return

        age = self._age.value() if self._age.value() > 0 else None
        gender = self._gender.currentText() or None
        diagnosis = self._diagnosis.text().strip() or None
        notes = self._notes.toPlainText().strip() or None

        if self._mode == "create":
            self._db.add_patient(
                name, age=age, gender=gender, diagnosis=diagnosis, general_notes=notes
            )
        else:
            self._db.update_patient(
                self._patient_id,
                name=name, age=age, gender=gender, diagnosis=diagnosis, general_notes=notes,
            )
        self.accept()
