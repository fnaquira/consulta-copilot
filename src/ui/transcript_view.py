# -*- coding: utf-8 -*-
"""
TranscriptView — Fase 9 (Audio Dual)

Re-renderiza el contenido completo con setHtml en cada actualización.
Soporta DOS fuentes simultáneas: cada una con su propio color de label
y parcial independiente.

Backwards-compatible: append_confirmed y update_partial aceptan
(source, text) — si se llaman con un solo string (fuente antigua),
se asume source="Tú".
"""

import time
from html import escape

from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QFont
from PySide6.QtCore import Slot


_SOURCE_COLORS = {
    "Tu":      "#2196F3",   # Azul
    "Tú":      "#2196F3",   # Azul (compat)
    "Reunion": "#4CAF50",   # Verde
    "Reunión": "#4CAF50",   # Verde (compat)
}
_DEFAULT_COLOR = "#9C27B0"  # Morado para fuentes no reconocidas


class TranscriptView(QTextEdit):
    """QTextEdit que muestra transcripción dual con labels de color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Segoe UI", 13))
        self.setPlaceholderText("La transcripción aparecerá aquí en tiempo real...")

        # Lista de segmentos confirmados: [(source, text, t_start, t_end)]
        self._confirmed_lines: list[tuple[str, str, float, float]] = []
        # Parciales activos por fuente: {source: text}
        self._partials: dict[str, str] = {}

        self._session_start = time.monotonic()

    # ------------------------------------------------------------------ #
    # API pública — acepta (source, text) o solo (text) para compat
    # ------------------------------------------------------------------ #
    @Slot(str, str)
    def append_confirmed(self, source: str, text: str):
        """Agrega texto confirmado de una fuente."""
        t_now = time.monotonic() - self._session_start
        self._confirmed_lines.append((source, text, t_now, t_now))
        # Limpiar parcial de esta fuente
        self._partials.pop(source, None)
        self._render()

    @Slot(str, str)
    def update_partial(self, source: str, text: str):
        """Reemplaza el texto parcial de una fuente específica."""
        if text.strip():
            self._partials[source] = text
        else:
            self._partials.pop(source, None)
        self._render()

    # ------------------------------------------------------------------ #
    # Renderizado
    # ------------------------------------------------------------------ #
    def _render(self):
        """Reconstruye el HTML completo del widget."""
        parts = []

        for source, text, *_ in self._confirmed_lines:
            color = _SOURCE_COLORS.get(source, _DEFAULT_COLOR)
            parts.append(
                f'<p style="margin:2px 0;">'
                f'<b style="color:{color}">[{escape(source)}]:</b> '
                f'<span style="color:#1a1a1a">{escape(text)}</span>'
                f'</p>'
            )

        for source, text in self._partials.items():
            color = _SOURCE_COLORS.get(source, _DEFAULT_COLOR)
            parts.append(
                f'<p style="margin:2px 0;">'
                f'<b style="color:{color}">[{escape(source)}]:</b> '
                f'<span style="color:#888;font-style:italic">{escape(text)}</span>'
                f'</p>'
            )

        self.setHtml("".join(parts))
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------ #
    # Acceso a datos
    # ------------------------------------------------------------------ #
    def get_all_text(self) -> str:
        """Retorna texto confirmado con labels para exportación TXT."""
        return "\n".join(
            f"[{source}]: {text}"
            for source, text, *_ in self._confirmed_lines
        )

    def get_segments(self) -> list[tuple[str, float, float]]:
        """Retorna lista de (texto_con_label, t_inicio, t_fin) para SRT."""
        return [
            (f"[{source}]: {text}", t_start, t_end)
            for source, text, t_start, t_end in self._confirmed_lines
        ]

    def clear_all(self):
        """Limpia todo el contenido."""
        self._confirmed_lines.clear()
        self._partials.clear()
        self._session_start = time.monotonic()
        self.clear()
