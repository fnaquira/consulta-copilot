# -*- coding: utf-8 -*-
"""
Tests para DBManager usando base de datos en memoria.
"""
import time
import pytest
from src.db.manager import DBManager


@pytest.fixture
def db():
    """DBManager con BD en memoria, tablas inicializadas."""
    manager = DBManager(db_path=":memory:")
    manager.init_db()
    return manager


# ------------------------------------------------------------------
# Tabla y estructura
# ------------------------------------------------------------------

def test_init_creates_tables(db):
    """Las tablas patients y sessions deben existir tras init_db()."""
    conn = db._get_conn()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "patients" in tables
    assert "sessions" in tables


# ------------------------------------------------------------------
# Pacientes
# ------------------------------------------------------------------

def test_add_get_patient(db):
    """Crear paciente y recuperarlo con todos sus campos."""
    pid = db.add_patient(
        "Ana García",
        age=30,
        gender="Femenino",
        diagnosis="Ansiedad GAD",
        general_notes="Derivada por médico",
    )
    assert isinstance(pid, int) and pid > 0

    patient = db.get_patient(pid)
    assert patient is not None
    assert patient["name"] == "Ana García"
    assert patient["age"] == 30
    assert patient["gender"] == "Femenino"
    assert patient["diagnosis"] == "Ansiedad GAD"
    assert patient["general_notes"] == "Derivada por médico"
    assert patient["created_at"]
    assert patient["updated_at"]


def test_update_patient(db):
    """Modificar campos y verificar que updated_at cambia."""
    pid = db.add_patient("Carlos López")
    patient_before = db.get_patient(pid)
    updated_at_before = patient_before["updated_at"]

    # Pequeña pausa para que el timestamp sea diferente
    time.sleep(1.1)

    db.update_patient(pid, diagnosis="TDM", age=45)
    patient_after = db.get_patient(pid)

    assert patient_after["diagnosis"] == "TDM"
    assert patient_after["age"] == 45
    # El trigger actualiza updated_at
    assert patient_after["updated_at"] >= updated_at_before


def test_delete_patient_cascades(db):
    """Al borrar paciente, sus sesiones se eliminan (CASCADE)."""
    pid = db.add_patient("Pedro Ruiz")
    db.add_session(pid, manual_notes="Primera sesión")
    db.add_session(pid, manual_notes="Segunda sesión")

    # Verificar que hay sesiones
    sessions = db.get_sessions_by_patient(pid)
    assert len(sessions) == 2

    db.delete_patient(pid)

    # Paciente eliminado
    assert db.get_patient(pid) is None
    # Sesiones eliminadas en cascada
    sessions_after = db.get_sessions_by_patient(pid)
    assert len(sessions_after) == 0


def test_get_all_patients(db):
    """get_all_patients retorna todos los pacientes ordenados por nombre."""
    db.add_patient("Zoe Torres")
    db.add_patient("Ana García")
    db.add_patient("Miguel Soto")

    patients = db.get_all_patients()
    assert len(patients) == 3
    names = [p["name"] for p in patients]
    assert names == sorted(names, key=str.casefold)


# ------------------------------------------------------------------
# Sesiones
# ------------------------------------------------------------------

def test_add_get_session(db):
    """Crear sesión y verificar que session_number auto-incrementa."""
    pid = db.add_patient("Laura Vega")

    sid1 = db.add_session(pid, manual_notes="Sesión inicial")
    sid2 = db.add_session(pid, transcript_patient="Hola doctor")

    s1 = db.get_session(sid1)
    s2 = db.get_session(sid2)

    assert s1["session_number"] == 1
    assert s2["session_number"] == 2
    assert s1["manual_notes"] == "Sesión inicial"
    assert s2["transcript_patient"] == "Hola doctor"


def test_get_next_session_number(db):
    """Sin sesiones retorna 1; con N sesiones retorna N+1."""
    pid = db.add_patient("Mario Díaz")

    assert db.get_next_session_number(pid) == 1

    db.add_session(pid)
    db.add_session(pid)
    db.add_session(pid)

    assert db.get_next_session_number(pid) == 4


# ------------------------------------------------------------------
# Búsqueda global
# ------------------------------------------------------------------

def test_search_all_by_name(db):
    """Buscar por nombre de paciente devuelve resultados correctos."""
    db.add_patient("Elena Montoya", diagnosis="Fobia social")
    db.add_patient("Roberto Paz")

    results = db.search_all("Elena")
    assert len(results) >= 1
    found = [r for r in results if r["type"] == "patient"]
    assert any("Elena" in r["snippet"] for r in found)


def test_search_all_by_transcript(db):
    """Buscar en transcripción de sesión devuelve resultados correctos."""
    pid = db.add_patient("Sandra Gil")
    db.add_session(pid, transcript_patient="El paciente menciona insomnio severo")

    results = db.search_all("insomnio")
    assert len(results) >= 1
    session_results = [r for r in results if r["type"] == "session"]
    assert any("insomnio" in r["snippet"] for r in session_results)
    assert all(r["patient_id"] == pid for r in session_results)


def test_search_all_no_results(db):
    """Keyword inexistente retorna lista vacía."""
    db.add_patient("Testuser")
    results = db.search_all("xyzzy_keyword_inexistente_12345")
    assert results == []
