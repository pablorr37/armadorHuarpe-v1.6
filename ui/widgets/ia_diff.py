"""
Utilidades para resaltar en amarillo los fragmentos reescritos por IA.

El resaltado es NO intrusivo (solo fondo semitransparente; el texto conserva
su color), del mismo estilo que las marcas de ortografía. Para saber qué
cambió se compara el texto reescrito contra el original con difflib.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QTextEdit, QPlainTextEdit

# Amarillo semitransparente (mismo criterio de alpha que spell_highlighter)
IA_HIGHLIGHT_COLOR = QColor(255, 220, 0, 70)


def diff_ranges(original: str, nuevo: str) -> list[tuple[int, int]]:
    """Rangos (start, end) en `nuevo` que difieren del `original`
    (opcodes 'replace' e 'insert' de SequenceMatcher)."""
    if not nuevo:
        return []
    if not original:
        return [(0, len(nuevo))]
    sm = SequenceMatcher(None, original, nuevo, autojunk=False)
    rangos: list[tuple[int, int]] = []
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert") and j2 > j1:
            rangos.append((j1, j2))
    return rangos


def build_highlight_selections(widget, ranges: list[tuple[int, int]]) -> list:
    """Arma (sin aplicar) las extra-selections amarillas para un
    QTextEdit/QPlainTextEdit. No llama setExtraSelections: quien la use debe
    fusionar el resultado con cualquier otra capa de highlighting existente
    sobre el mismo widget (límite, recursos, fragmentos), en vez de
    sobrescribirla directo."""
    if not isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return []
    fmt = QTextCharFormat()
    fmt.setBackground(IA_HIGHLIGHT_COLOR)
    doc = widget.document()
    char_count = doc.characterCount()  # incluye el \n final
    selections = []
    for start, end in ranges:
        start = max(0, min(start, char_count - 1))
        end = max(start, min(end, char_count - 1))
        if end <= start:
            continue
        sel = QTextEdit.ExtraSelection()
        sel.format = fmt
        cur = QTextCursor(doc)
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.KeepAnchor)
        sel.cursor = cur
        selections.append(sel)
    return selections


def apply_text_edit_highlight(widget, ranges: list[tuple[int, int]]) -> None:
    """Aplica extra-selections amarillas directo sobre el widget (overwrite).
    Solo apta para widgets que no compongan otras capas de highlighting
    encima; ver build_highlight_selections() para el caso general."""
    if not isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return
    widget.setExtraSelections(build_highlight_selections(widget, ranges))


def clear_text_edit_highlight(widget) -> None:
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        widget.setExtraSelections([])
