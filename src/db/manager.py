# -*- coding: utf-8 -*-
"""
DBManager — Gestión de base de datos SQLite para el Copiloto Psicológico.

Archivo: ~/.consulta_copilot/copilot.db
"""

import sqlite3
from pathlib import Path


_DEFAULT_DB_PATH = Path.home() / ".consulta_copilot" / "copilot.db"

_CREATE_PATIENTS = """
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    diagnosis TEXT,
    general_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    session_date TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    session_number INTEGER NOT NULL,
    manual_notes TEXT DEFAULT '',
    transcript_patient TEXT DEFAULT '',
    transcript_psychologist TEXT DEFAULT '',
    ai_suggestions TEXT DEFAULT '',
    duration_seconds INTEGER DEFAULT 0,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE
);
"""

_CREATE_INDEX_SESSIONS = """
CREATE INDEX IF NOT EXISTS idx_sessions_patient ON sessions(patient_id);
"""

_TRIGGER_PATIENTS_UPDATED = """
CREATE TRIGGER IF NOT EXISTS trg_patients_updated
AFTER UPDATE ON patients
BEGIN
    UPDATE patients SET updated_at = datetime('now','localtime') WHERE id = NEW.id;
END;
"""


class DBManager:
    """
    Singleton-compatible. Todas las operaciones son síncronas (SQLite es local y rápido).

    Acepta db_path para testing (pasar ':memory:' o ruta temporal).
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            path = _DEFAULT_DB_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path = str(path)
        else:
            self._db_path = db_path

        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def init_db(self) -> None:
        """Crea tablas e índices si no existen."""
        conn = self._get_conn()
        conn.execute(_CREATE_PATIENTS)
        conn.execute(_CREATE_SESSIONS)
        conn.execute(_CREATE_INDEX_SESSIONS)
        conn.execute(_TRIGGER_PATIENTS_UPDATED)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Pacientes
    # ------------------------------------------------------------------

    def add_patient(self, name: str, **kwargs) -> int:
        """Crea un paciente. Retorna el id generado."""
        allowed = {"age", "gender", "diagnosis", "general_notes"}
        fields = {"name": name}
        fields.update({k: v for k, v in kwargs.items() if k in allowed})

        cols = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        conn = self._get_conn()
        cur = conn.execute(
            f"INSERT INTO patients ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
        conn.commit()
        return cur.lastrowid

    def update_patient(self, patient_id: int, **kwargs) -> None:
        """Modifica campos de un paciente existente."""
        allowed = {"name", "age", "gender", "diagnosis", "general_notes"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn = self._get_conn()
        conn.execute(
            f"UPDATE patients SET {set_clause} WHERE id = ?",
            [*fields.values(), patient_id],
        )
        conn.commit()

    def delete_patient(self, patient_id: int) -> None:
        """Elimina paciente y sus sesiones (ON DELETE CASCADE)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        conn.commit()

    def get_patient(self, patient_id: int) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_patients(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM patients ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Sesiones
    # ------------------------------------------------------------------

    def get_next_session_number(self, patient_id: int) -> int:
        """Retorna el próximo número de sesión para el paciente."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COALESCE(MAX(session_number), 0) + 1 FROM sessions WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()
        return row[0]

    def add_session(self, patient_id: int, **kwargs) -> int:
        """Crea una sesión. Retorna el id generado."""
        allowed = {
            "session_date",
            "manual_notes",
            "transcript_patient",
            "transcript_psychologist",
            "ai_suggestions",
            "duration_seconds",
        }
        fields: dict = {"patient_id": patient_id}
        fields["session_number"] = kwargs.pop(
            "session_number", self.get_next_session_number(patient_id)
        )
        fields.update({k: v for k, v in kwargs.items() if k in allowed})

        cols = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        conn = self._get_conn()
        cur = conn.execute(
            f"INSERT INTO sessions ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
        conn.commit()
        return cur.lastrowid

    def get_sessions_by_patient(self, patient_id: int) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions WHERE patient_id = ? ORDER BY session_number",
            (patient_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: int) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id: int, **kwargs) -> None:
        """Modifica campos de una sesión existente."""
        allowed = {
            "manual_notes",
            "transcript_patient",
            "transcript_psychologist",
            "ai_suggestions",
            "duration_seconds",
        }
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn = self._get_conn()
        conn.execute(
            f"UPDATE sessions SET {set_clause} WHERE id = ?",
            [*fields.values(), session_id],
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Búsqueda global
    # ------------------------------------------------------------------

    def search_all(self, keyword: str) -> list[dict]:
        """
        Busca keyword (LIKE) en pacientes y sesiones.

        Retorna lista de dicts con:
            type: "patient" | "session"
            patient_id: int
            session_id: int | None
            match_field: str
            snippet: str (~100 chars alrededor del match)
        """
        if not keyword:
            return []

        results: list[dict] = []
        conn = self._get_conn()
        like = f"%{keyword}%"

        # --- Pacientes ---
        patient_fields = ["name", "diagnosis", "general_notes"]
        for field in patient_fields:
            rows = conn.execute(
                f"SELECT id, {field} FROM patients WHERE {field} LIKE ?", (like,)
            ).fetchall()
            for row in rows:
                snippet = _make_snippet(row[field], keyword)
                results.append(
                    {
                        "type": "patient",
                        "patient_id": row["id"],
                        "session_id": None,
                        "match_field": field,
                        "snippet": snippet,
                    }
                )

        # --- Sesiones ---
        session_fields = [
            "manual_notes",
            "transcript_patient",
            "transcript_psychologist",
        ]
        for field in session_fields:
            rows = conn.execute(
                f"SELECT id, patient_id, {field} FROM sessions WHERE {field} LIKE ?",
                (like,),
            ).fetchall()
            for row in rows:
                snippet = _make_snippet(row[field], keyword)
                results.append(
                    {
                        "type": "session",
                        "patient_id": row["patient_id"],
                        "session_id": row["id"],
                        "match_field": field,
                        "snippet": snippet,
                    }
                )

        return results


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_snippet(text: str, keyword: str, context: int = 50) -> str:
    """Extrae ~100 chars alrededor de la primera aparición de keyword."""
    if not text:
        return ""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return text[:100]
    start = max(0, idx - context)
    end = min(len(text), idx + len(keyword) + context)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
