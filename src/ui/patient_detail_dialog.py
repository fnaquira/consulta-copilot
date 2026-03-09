# -*- coding: utf-8 -*-
"""
PatientDetailDialog — Detalle de paciente + historial de sesiones.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from src.db.manager import DBManager
from src.ui.patient_dialog import PatientDialog


class PatientDetailDialog(QDialog):
    # Emitida cuando se quiere iniciar una nueva sesión
    session_requested = Signal(int)   # patient_id

    def __init__(self, db: DBManager, patient_id: int, parent=None):
        super().__init__(parent)
        self._db = db
        self._patient_id = patient_id
        self.setWindowTitle("Detalle del Paciente")
        self.setMinimumSize(700, 500)
        self._build_ui()
        self._load_data()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Encabezado ---
        header = QHBoxLayout()
        self._lbl_name = QLabel()
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self._lbl_name.setFont(font)
        header.addWidget(self._lbl_name, 1)

        btn_edit = QPushButton("Editar")
        btn_edit.clicked.connect(self._on_edit)
        header.addWidget(btn_edit)

        btn_delete = QPushButton("Eliminar")
        btn_delete.setStyleSheet("color: red;")
        btn_delete.clicked.connect(self._on_delete)
        header.addWidget(btn_delete)
        layout.addLayout(header)

        # --- Info básica ---
        self._lbl_info = QLabel()
        self._lbl_info.setWordWrap(True)
        layout.addWidget(self._lbl_info)

        # Separador
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep1)

        # --- Notas generales ---
        lbl_notes = QLabel("Notas generales:")
        lbl_notes.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_notes)

        self._notes_view = QTextEdit()
        self._notes_view.setReadOnly(True)
        self._notes_view.setFixedHeight(90)
        layout.addWidget(self._notes_view)

        # Separador
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # --- Historial de sesiones ---
        lbl_hist = QLabel("Historial de sesiones:")
        lbl_hist.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_hist)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["#", "Fecha", "Duración", "Ver"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        # --- Botón nueva sesión ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_new = QPushButton("+ Nueva Sesión")
        btn_new.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        btn_new.clicked.connect(self._on_new_session)
        btn_row.addWidget(btn_new)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    def _load_data(self):
        patient = self._db.get_patient(self._patient_id)
        if not patient:
            self.reject()
            return

        self._lbl_name.setText(patient["name"])

        age_str = str(patient["age"]) if patient.get("age") else "—"
        gender_str = patient.get("gender") or "—"
        dx_str = patient.get("diagnosis") or "—"
        self._lbl_info.setText(f"Edad: {age_str}  |  Género: {gender_str}  |  Dx: {dx_str}")
        self._notes_view.setPlainText(patient.get("general_notes") or "")

        sessions = self._db.get_sessions_by_patient(self._patient_id)
        self._table.setRowCount(0)
        for session in sessions:
            row = self._table.rowCount()
            self._table.insertRow(row)

            self._table.setItem(row, 0, QTableWidgetItem(str(session["session_number"])))
            date_str = (session.get("session_date") or "")[:16]
            self._table.setItem(row, 1, QTableWidgetItem(date_str))

            dur = session.get("duration_seconds") or 0
            dur_str = f"{dur // 60} min" if dur else "—"
            self._table.setItem(row, 2, QTableWidgetItem(dur_str))

            btn_view = QPushButton("Ver")
            session_id = session["id"]
            btn_view.clicked.connect(lambda _, sid=session_id: self._on_view_session(sid))
            self._table.setCellWidget(row, 3, btn_view)

    # ------------------------------------------------------------------
    def _on_edit(self):
        dlg = PatientDialog(self._db, mode="edit", patient_id=self._patient_id, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_data()

    def _on_delete(self):
        patient = self._db.get_patient(self._patient_id)
        name = patient["name"] if patient else "este paciente"
        resp = QMessageBox.question(
            self,
            "Eliminar paciente",
            f"¿Deseas eliminar a {name} y todas sus sesiones? Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._db.delete_patient(self._patient_id)
            self.accept()

    def _on_view_session(self, session_id: int):
        from src.ui.session_review_dialog import SessionReviewDialog
        dlg = SessionReviewDialog(self._db, session_id, parent=self)
        dlg.exec()

    def _on_new_session(self):
        self.session_requested.emit(self._patient_id)
        self.accept()
