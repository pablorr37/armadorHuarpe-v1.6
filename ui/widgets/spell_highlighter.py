from __future__ import annotations
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor

from services.spell_service import SpellService


class _CheckWorker(QThread):
    results_ready = pyqtSignal(list)

    def __init__(self, spell: SpellService):
        super().__init__()
        self._spell = spell
        self._text = ""

    def set_text(self, text: str):
        self._text = text

    def run(self):
        try:
            results = self._spell.check(self._text)
        except Exception:
            results = []
        self.results_ready.emit(results)


class SpellHighlighter(QSyntaxHighlighter):
    """
    Resalta errores ortográficos y repeticiones.
    - Rojo    (#ff4444): error ortográfico
    - Naranja (#ff8c00): repetición adyacente
    - Violeta (#b388ff): repetición por proximidad (párrafos cercanos)
    """

    errors_updated = pyqtSignal(list)   # emite la lista de errores cuando termina el check

    def __init__(self, document, spell_service: SpellService, field_name: str = ""):
        super().__init__(document)
        self._spell = spell_service
        self._field_name = field_name
        self._errors: list[dict] = []
        self._ignored: set[str] = set()
        self._full_text = ""
        self._pending_text = ""

        # Solo el FONDO es de color: el texto conserva siempre el color del editor
        # (gris oscuro en el cuerpo claro). Alpha algo más alto para leerse sobre el hueso.
        self._fmt_spell = QTextCharFormat()
        self._fmt_spell.setBackground(QColor(255, 80, 80, 70))

        self._fmt_repeat = QTextCharFormat()
        self._fmt_repeat.setBackground(QColor(255, 140, 0, 90))   # naranja semitransparente

        self._fmt_proximity = QTextCharFormat()
        self._fmt_proximity.setBackground(QColor(179, 136, 255, 90))  # violeta semitransparente

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._dispatch_check)

        self._worker = _CheckWorker(spell_service)
        self._worker.results_ready.connect(self._on_results)

    def highlightBlock(self, text: str):
        if not self._errors:
            return
        block_start = self.currentBlock().position()
        block_end = block_start + len(text)
        for err in self._errors:
            s, e = err["start"], err["end"]
            if s >= block_start and e <= block_end:
                t = err["type"]
                if t == "repeat":
                    fmt = self._fmt_repeat
                elif t == "proximity":
                    fmt = self._fmt_proximity
                else:
                    fmt = self._fmt_spell
                self.setFormat(s - block_start, e - s, fmt)

    def schedule_check(self, full_text: str):
        self._full_text = full_text
        self._timer.start()

    def _dispatch_check(self):
        if self._worker.isRunning():
            self._pending_text = self._full_text
            return
        self._pending_text = ""
        self._worker.set_text(self._full_text)
        self._worker.start()

    def _on_results(self, errors: list):
        if self._ignored:
            errors = [e for e in errors if e["word"].lower() not in self._ignored]
        self._errors = errors
        self.rehighlight()
        self.errors_updated.emit(errors)
        if self._pending_text:
            text = self._pending_text
            self._pending_text = ""
            self._worker.set_text(text)
            self._worker.start()

    def get_suggestions_at(self, position: int) -> tuple[str, list[str]] | None:
        for err in self._errors:
            if err["start"] <= position <= err["end"]:
                word = err["word"]
                suggestions = err.get("suggestions")
                if suggestions is None:
                    suggestions = self._spell.get_suggestions(word)
                    err["suggestions"] = suggestions
                return word, suggestions
        return None

    def ignore_word(self, word: str):
        """Descarta los errores de esta palabra sin agregarla al diccionario."""
        self._ignored.add(word.lower())
        self._errors = [e for e in self._errors if e["word"].lower() != word.lower()]
        self.rehighlight()
        self.errors_updated.emit(self._errors)

    def ignore_words(self, words: set):
        """Descarta múltiples palabras con un solo rehighlight."""
        lower = {w.lower() for w in words}
        self._ignored.update(lower)
        self._errors = [e for e in self._errors if e["word"].lower() not in lower]
        self.rehighlight()
        self.errors_updated.emit(self._errors)

    def add_word_to_dict(self, word: str):
        self._spell.add_word(word)
        self._ignored.discard(word.lower())
        self._errors = [e for e in self._errors if e["word"].lower() != word.lower()]
        self.rehighlight()
        self.errors_updated.emit(self._errors)

    def add_words_to_dict(self, words: set):
        """Agrega múltiples palabras al diccionario con un solo rehighlight."""
        lower = {w.lower() for w in words}
        for w in lower:
            self._spell.add_word(w)
            self._ignored.discard(w)
        self._errors = [e for e in self._errors if e["word"].lower() not in lower]
        self.rehighlight()
        self.errors_updated.emit(self._errors)

    def stop(self):
        self._timer.stop()
        if self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(500)
