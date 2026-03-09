# -*- coding: utf-8 -*-
"""
SessionReviewDialog — Vista de solo lectura de una sesión pasada.
(Implementación completa en Fase 4)
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QDialogButtonBox, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.db.manager import DBManager


class SessionReviewDialog(QDialog):
    def __init__(self, db: DBManager, session_id: int, parent=None):
        super().__init__(parent)
        self._db = db
        self._session_id = session_id
        self.setWindowTitle("Ver Sesión")
        self.setMinimumSize(700, 520)
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Encabezado
        self._lbl_title = QLabel()
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        self._lbl_title.setFont(font)
        layout.addWidget(self._lbl_title)

        self._lbl_meta = QLabel()
        layout.addWidget(self._lbl_meta)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Transcripción
        lbl_trans = QLabel("Transcripción:")
        lbl_trans.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_trans)

        self._transcript_view = QTextEdit()
        self._transcript_view.setReadOnly(True)
        layout.addWidget(self._transcript_view, 2)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # Notas
        lbl_notes = QLabel("Notas del psicólogo:")
        lbl_notes.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_notes)

        self._notes_view = QTextEdit()
        self._notes_view.setReadOnly(True)
        self._notes_view.setFixedHeight(80)
        layout.addWidget(self._notes_view)

        # Sugerencias IA
        lbl_ai = QLabel("Sugerencias del copiloto:")
        lbl_ai.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_ai)

        self._ai_view = QTextEdit()
        self._ai_view.setReadOnly(True)
        self._ai_view.setFixedHeight(80)
        layout.addWidget(self._ai_view)

        # Botones
        btn_row = QHBoxLayout()
        btn_export = QPushButton("Exportar TXT")
        btn_export.clicked.connect(self._on_export_txt)
        btn_row.addWidget(btn_export)
        btn_row.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _load_data(self):
        session = self._db.get_session(self._session_id)
        if not session:
            self.reject()
            return

        patient = self._db.get_patient(session["patient_id"])
        patient_name = patient["name"] if patient else f"Paciente #{session['patient_id']}"

        self._lbl_title.setText(f"Sesión #{session['session_number']} — {patient_name}")

        date_str = (session.get("session_date") or "")[:16]
        dur = session.get("duration_seconds") or 0
        dur_str = f"{dur // 60} min {dur % 60} seg" if dur else "—"
        self._lbl_meta.setText(f"Fecha: {date_str}  |  Duración: {dur_str}")

        # Transcripción combinada
        lines = []
        psy_text = session.get("transcript_psychologist") or ""
        pac_text = session.get("transcript_patient") or ""
        if psy_text:
            lines.append(f"[PSI]\n{psy_text}")
        if pac_text:
            lines.append(f"[PAC]\n{pac_text}")
        self._transcript_view.setPlainText("\n\n".join(lines) if lines else "(sin transcripción)")

        self._notes_view.setPlainText(session.get("manual_notes") or "")
        self._ai_view.setPlainText(session.get("ai_suggestions") or "")

    def _on_export_txt(self):
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path

        session = self._db.get_session(self._session_id)
        if not session:
            return

        patient = self._db.get_patient(session["patient_id"])
        patient_name = patient["name"] if patient else "paciente"

        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar sesión", f"sesion_{session['session_number']}_{patient_name}.txt",
            "Archivos de texto (*.txt)"
        )
        if not ruta:
            return

        lines = [
            f"=== Sesión #{session['session_number']} — {patient_name} — {session.get('session_date', '')[:16]} ===",
            f"Duración: {(session.get('duration_seconds') or 0) // 60} minutos",
            "",
            "--- TRANSCRIPCIÓN ---",
        ]
        if session.get("transcript_psychologist"):
            lines.append(f"[PSI] {session['transcript_psychologist']}")
        if session.get("transcript_patient"):
            lines.append(f"[PAC] {session['transcript_patient']}")
        if session.get("manual_notes"):
            lines += ["", "--- NOTAS DEL PSICÓLOGO ---", session["manual_notes"]]
        if session.get("ai_suggestions"):
            lines += ["", "--- SUGERENCIAS DEL COPILOTO ---", session["ai_suggestions"]]

        Path(ruta).write_text("\n".join(lines), encoding="utf-8")
