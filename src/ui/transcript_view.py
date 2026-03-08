# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QFont
from PySide6.QtCore import Slot


class TranscriptView(QTextEdit):
    """QTextEdit que distingue texto confirmado (negro) de parcial (gris)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Segoe UI", 13))
        self.setPlaceholderText("La transcripción aparecerá aquí en tiempo real...")

        self._fmt_confirmed = QTextCharFormat()
        self._fmt_confirmed.setForeground(QColor("#1a1a1a"))

        self._fmt_partial = QTextCharFormat()
        self._fmt_partial.setForeground(QColor("#888888"))
        self._fmt_partial.setFontItalic(True)

        self._partial_start = -1  # Posición donde empieza el texto parcial

    @Slot(str)
    def append_confirmed(self, text: str):
        """Agrega texto confirmado (inmutable, negro)."""
        self._remove_partial()

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if cursor.position() > 0:
            cursor.insertText(" ", self._fmt_confirmed)
        cursor.insertText(text, self._fmt_confirmed)
        self.setTextCursor(cursor)
        self._scroll_to_bottom()

    @Slot(str)
    def update_partial(self, text: str):
        """Reemplaza el texto parcial (mutable, gris itálica)."""
        self._remove_partial()

        if not text.strip():
            return

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._partial_start = cursor.position()

        if self._partial_start > 0:
            cursor.insertText(" ", self._fmt_partial)
        cursor.insertText(text, self._fmt_partial)
        self.setTextCursor(cursor)
        self._scroll_to_bottom()

    def _remove_partial(self):
        """Elimina el texto parcial actual."""
        if self._partial_start < 0:
            return
        cursor = self.textCursor()
        cursor.setPosition(self._partial_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        self._partial_start = -1

    def _scroll_to_bottom(self):
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def get_all_text(self) -> str:
        """Retorna solo el texto confirmado (sin parcial)."""
        self._remove_partial()
        return self.toPlainText()

    def clear_all(self):
        """Limpia todo el contenido incluyendo el parcial."""
        self._partial_start = -1
        self.clear()
