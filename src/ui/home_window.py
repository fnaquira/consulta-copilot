# -*- coding: utf-8 -*-
"""
HomeWindow — Pantalla de inicio del Copiloto Psicológico.
"""
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from src.db.manager import DBManager
from src.utils.config import TranscriberConfig


class HomeWindow(QMainWindow):
    def __init__(self, db: DBManager, config: TranscriberConfig | None = None):
        super().__init__()
        self._db = db
        self._config = config or TranscriberConfig()
        self._session_windows: list = []
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)

        self.setWindowTitle("Copiloto Psicológico")
        self.resize(820, 600)
        self._build_ui()
        self._load_patients()

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # --- Encabezado ---
        header = QHBoxLayout()
        title = QLabel("Copiloto Psicológico")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)
        header.addWidget(title, 1)

        btn_config = QPushButton("⚙ Configuración")
        btn_config.clicked.connect(self._on_open_config)
        header.addWidget(btn_config)
        root.addLayout(header)

        # --- Búsqueda ---
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Buscar paciente...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        root.addWidget(self._search_edit)

        # --- Tabla de pacientes ---
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Nombre", "Diagnóstico", "Acciones"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        root.addWidget(self._table, 1)

        # --- Botón nuevo paciente ---
        btn_row = QHBoxLayout()
        self._btn_new = QPushButton("+ Nuevo Paciente")
        self._btn_new.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;font-weight:bold;"
            "padding:8px 20px;border-radius:4px;}"
            "QPushButton:hover{background:#43A047;}"
        )
        self._btn_new.clicked.connect(self._on_new_patient)
        btn_row.addWidget(self._btn_new)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------

    def _load_patients(self, patients: list | None = None):
        if patients is None:
            patients = self._db.get_all_patients()
        self._table.setRowCount(0)
        for patient in patients:
            self._add_patient_row(patient)

    def _add_patient_row(self, patient: dict):
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(patient["name"])
        name_item.setData(Qt.ItemDataRole.UserRole, patient["id"])
        self._table.setItem(row, 0, name_item)

        dx = patient.get("diagnosis") or "—"
        self._table.setItem(row, 1, QTableWidgetItem(dx))

        # Botones de acción
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(4, 2, 4, 2)
        actions_layout.setSpacing(4)

        pid = patient["id"]

        btn_session = QPushButton("▶ Sesión")
        btn_session.setStyleSheet(
            "QPushButton{background:#2196F3;color:white;border-radius:3px;padding:3px 8px;}"
            "QPushButton:hover{background:#1976D2;}"
        )
        btn_session.clicked.connect(lambda _, p=pid: self._on_start_session(p))
        actions_layout.addWidget(btn_session)

        btn_edit = QPushButton("📝")
        btn_edit.setToolTip("Ver detalle / editar")
        btn_edit.setFixedWidth(36)
        btn_edit.clicked.connect(lambda _, p=pid: self._on_open_detail(p))
        actions_layout.addWidget(btn_edit)

        self._table.setCellWidget(row, 2, actions)

    # ------------------------------------------------------------------
    # Búsqueda
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str):
        self._search_timer.start(300)  # debounce 300ms

    def _do_search(self):
        text = self._search_edit.text().strip()
        if not text:
            self._load_patients()
            return

        # Filtro local por nombre y diagnóstico
        all_patients = self._db.get_all_patients()
        filtered = [
            p for p in all_patients
            if text.lower() in (p.get("name") or "").lower()
            or text.lower() in (p.get("diagnosis") or "").lower()
        ]
        self._load_patients(filtered)

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def _on_new_patient(self):
        from src.ui.patient_dialog import PatientDialog
        dlg = PatientDialog(self._db, mode="create", parent=self)
        if dlg.exec():
            self._search_edit.clear()
            self._load_patients()

    def _on_row_double_clicked(self, index):
        pid = self._table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        self._on_open_detail(pid)

    def _on_open_detail(self, patient_id: int):
        from src.ui.patient_detail_dialog import PatientDetailDialog
        dlg = PatientDetailDialog(self._db, patient_id, parent=self)
        dlg.session_requested.connect(self._on_start_session)
        dlg.exec()
        self._load_patients()

    def _on_start_session(self, patient_id: int):
        from src.ui.session_window import SessionWindow
        win = SessionWindow(db=self._db, patient_id=patient_id, config=self._config)
        win.closed.connect(lambda: self._load_patients())
        # Limpiar ventanas ya cerradas antes de agregar la nueva
        self._session_windows = [w for w in self._session_windows if w.isVisible()]
        self._session_windows.append(win)
        win.show()

    def _on_open_config(self):
        from src.ui.config_dialog import ConfigDialog
        dlg = ConfigDialog(self._config, parent=self)
        dlg.exec()
