# -*- coding: utf-8 -*-
"""
Tests del CopilotWorker configurable por dominio.
Usa mocks — no requiere API keys ni LLM real.
"""
from src.ai.copilot import CopilotWorker
from src.ai.prompts import CLINICAL_PROMPT, MEETING_PROMPT, DOMAIN_PROMPTS


# ------------------------------------------------------------------ #
# Tests de prompts.py
# ------------------------------------------------------------------ #

def test_domain_prompts_contiene_clinical():
    assert "clinical" in DOMAIN_PROMPTS
    assert "psicologo" in DOMAIN_PROMPTS["clinical"].lower() or \
           "clinico" in DOMAIN_PROMPTS["clinical"].lower()


def test_domain_prompts_contiene_meeting():
    assert "meeting" in DOMAIN_PROMPTS
    assert "reunion" in DOMAIN_PROMPTS["meeting"].lower() or \
           "resumen" in DOMAIN_PROMPTS["meeting"].lower()


def test_clinical_prompt_es_discreto():
    """El prompt clinico enfatiza ser discreto."""
    assert "discreto" in CLINICAL_PROMPT.lower()


def test_meeting_prompt_tiene_formato_estructurado():
    """El prompt de meeting pide resumen, temas, decisiones."""
    text = MEETING_PROMPT.lower()
    assert "resumen" in text
    assert "temas" in text
    assert "decisiones" in text


# ------------------------------------------------------------------ #
# Tests de CopilotWorker
# ------------------------------------------------------------------ #

def test_copilot_acepta_system_prompt():
    """CopilotWorker se inicializa con system_prompt inyectado."""
    worker = CopilotWorker(system_prompt="Test prompt")
    assert worker._system_prompt == "Test prompt"


def test_copilot_acepta_context_text():
    """CopilotWorker recibe contexto generico."""
    worker = CopilotWorker(
        system_prompt="Test",
        context_text="Paciente: Juan, Diagnostico: Ansiedad",
    )
    assert "Juan" in worker._context_text


def test_copilot_acepta_previous_summaries():
    """CopilotWorker recibe historial de sesiones."""
    history = ["Sesion 1: tema A", "Sesion 2: tema B"]
    worker = CopilotWorker(
        system_prompt="Test",
        previous_summaries=history,
    )
    assert len(worker._previous_summaries) == 2


def test_append_text_acumula_con_labels():
    """append_text agrega texto con label de fuente."""
    worker = CopilotWorker(system_prompt="Test")
    worker.append_text("Tu", "hola como estas")
    worker.append_text("Reunion", "bien gracias")

    assert "[Tu]: hola como estas" in worker._full_transcript
    assert "[Reunion]: bien gracias" in worker._full_transcript


def test_append_text_ambas_fuentes():
    """Ambas fuentes se acumulan en el mismo transcript."""
    worker = CopilotWorker(system_prompt="Test")
    worker.append_text("Tu", "texto del mic")
    worker.append_text("Reunion", "texto del sistema")
    worker.append_text("Tu", "mas texto del mic")

    assert worker._full_transcript.count("[Tu]") == 2
    assert worker._full_transcript.count("[Reunion]") == 1


def test_throttle_defaults():
    """Verificar los defaults de throttling."""
    worker = CopilotWorker(system_prompt="Test")
    assert worker.THROTTLE_SECONDS == 30
    assert worker.MIN_NEW_CHARS == 80


def test_copilot_initial_state():
    """Estado inicial correcto."""
    worker = CopilotWorker(system_prompt="Test")
    assert worker._full_transcript == ""
    assert worker._last_analyzed_len == 0
    assert worker._previous_summary == ""
    assert worker._running is False


def test_copilot_with_clinical_domain():
    """CopilotWorker funciona con prompt clinico."""
    worker = CopilotWorker(
        system_prompt=CLINICAL_PROMPT,
        context_text="Paciente: Maria, Diagnostico: Depresion",
    )
    assert "clinico" in worker._system_prompt.lower() or \
           "psicologo" in worker._system_prompt.lower()


def test_copilot_with_meeting_domain():
    """CopilotWorker funciona con prompt de meeting."""
    worker = CopilotWorker(
        system_prompt=MEETING_PROMPT,
        context_text="Proyecto: MeetPilot",
    )
    assert "reunion" in worker._system_prompt.lower() or \
           "resumen" in worker._system_prompt.lower()
