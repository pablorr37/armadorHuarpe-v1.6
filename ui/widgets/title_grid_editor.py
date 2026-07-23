from __future__ import annotations
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFontMetrics
from PyQt5.QtWidgets import QWidget, QApplication

_CLR_BG        = QColor("#1a2535")
_CLR_CELL      = QColor("#243247")
_CLR_CELL_WARN = QColor("#3a3015")
_CLR_CELL_OVR  = QColor("#3a1515")
_CLR_GRID      = QColor("#334155")
_CLR_SEP       = QColor("#e7885f")
_CLR_TEXT      = QColor("#f1f5f9")
_CLR_TEXT_WARN = QColor("#f5c542")
_CLR_TEXT_OVR  = QColor("#ff6b6b")

# Caracteres 1..cols: normal. cols+1..cols+2 (34/35 con cols=33): amarillo, todavía
# aceptable. cols+3 en adelante (36+): rojo, claramente excedido.
_WARN_COLS = 2
_CLR_CURSOR    = QColor("#82b4ff")
_CLR_FOCUS_BG  = QColor("#1e3450")
_CLR_FOCUS_BDR = QColor("#82b4ff")
_CLR_SEL       = QColor(82, 150, 255, 140)


class TitleGridEditor(QWidget):
    """Editor de título — grilla rows × cols con corte duro en cols."""

    textChanged = pyqtSignal()
    tab_pressed  = pyqtSignal()

    _OVERFLOW_COLS = 14

    def __init__(self, parent=None, cols_per_line: int = 33, rows: int = 2):
        super().__init__(parent)
        self.cols = cols_per_line
        self.rows = rows
        self.max_len = self.cols * self.rows

        self._text = ""
        self._cursor = 0
        self._row_starts: list[int] = [0]
        self._sel_anchor: int | None = None
        self._undo_stack: list[tuple[str, int]] = []
        self._redo_stack: list[tuple[str, int]] = []
        self._dragging = False

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(rows * 65 + 20)
        self.textChanged.connect(self._update_tooltip)

    # -----------------------------------------------------------------------
    # Interfaz pública
    # -----------------------------------------------------------------------

    def text(self) -> str:
        return self._text

    def get_lines(self) -> list[str]:
        """Devuelve lista de líneas (salto real o corte duro en cols) — para guardar/mostrar."""
        rs = self._row_starts
        result = []
        for row, start in enumerate(rs):
            end = rs[row + 1] if row + 1 < len(rs) else len(self._text)
            line = self._text[start:end]
            if line.endswith("\n"):
                line = line[:-1]
            # Saltos embebidos (solo posibles en la última fila, por paste con más
            # líneas que filas): no deben filtrarse al TXT.
            result.append(line.replace("\n", " "))
        return result if result else [""]

    def update_dims(self, cols: int, rows: int) -> None:
        """Reconfigura la grilla en caliente; redistribuye el texto actual."""
        if self.cols == cols and self.rows == rows:
            return
        self.cols = cols
        self.rows = rows
        self.max_len = cols * rows
        self.setMinimumHeight(rows * 65 + 20)
        self._row_starts = self._compute_row_starts(self._text)
        self.updateGeometry()
        self.update()
        self.textChanged.emit()

    def set_text(self, t: str) -> None:
        """Carga texto externamente; resetea historial de undo y selección."""
        if "\n" in t:
            t = " ".join(seg.strip() for seg in t.split("\n") if seg.strip())
        else:
            t = t.strip()
        self._text = t
        self._row_starts = self._compute_row_starts(t)
        self._cursor = len(t)
        self._sel_anchor = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.update()
        self.textChanged.emit()

    # -----------------------------------------------------------------------
    # Row layout helpers
    # -----------------------------------------------------------------------

    def _compute_row_starts(self, text: str) -> list[int]:
        """Una fila termina en un salto real ('\\n') o al llegar a cols (corte duro).
        Se limita a self.rows filas: en la última, el resto desborda horizontal (rojo)."""
        starts = [0]
        col = 0
        i = 0
        n = len(text)
        while i < n and len(starts) < self.rows:
            ch = text[i]
            if ch == "\n":
                starts.append(i + 1)
                col = 0
            else:
                col += 1
                if col >= self.cols and i + 1 < n:
                    if text[i + 1] == "\n":
                        # El corte duro coincide con un salto real: consumirlo junto
                        # (evita una fila vacía duplicada).
                        starts.append(i + 2)
                        i += 1
                    else:
                        starts.append(i + 1)
                    col = 0
            i += 1
        return starts

    def _row_end(self, row: int) -> int:
        """Fin (exclusivo) del contenido visible de la fila, sin contar su '\\n' final."""
        rs = self._row_starts
        if row + 1 < len(rs):
            end = rs[row + 1]
            if end > rs[row] and self._text[end - 1] == "\n":
                end -= 1
            return end
        return len(self._text)

    def _cursor_row_col(self, cur: int) -> tuple[int, int]:
        """Convierte posición plana en (row, col) visual."""
        rs = self._row_starts
        row = 0
        for i in range(len(rs) - 1):
            if cur >= rs[i + 1]:
                row = i + 1
            else:
                break
        return row, cur - rs[row]

    def _cursor_from_cell(self, row: int, col: int) -> int:
        """Convierte (row, col) visual en posición plana, acotada al contenido de la fila."""
        r = max(0, min(row, len(self._row_starts) - 1))
        return min(self._row_starts[r] + col, self._row_end(r))

    # -----------------------------------------------------------------------
    # Selección
    # -----------------------------------------------------------------------

    def _sel_range(self) -> tuple[int, int] | None:
        """Devuelve (start, end) de la selección activa, o None."""
        if self._sel_anchor is None or self._sel_anchor == self._cursor:
            return None
        a, c = self._sel_anchor, self._cursor
        return (min(a, c), max(a, c))

    def _selected_text(self) -> str:
        r = self._sel_range()
        return self._text[r[0]:r[1]] if r else ""

    # -----------------------------------------------------------------------
    # Navegación por palabra (Ctrl+←/→) — misma regla de borde que el doble clic
    # -----------------------------------------------------------------------
    _WORD_SEP = " \t\n"

    def _next_word(self, pos: int) -> int:
        """Inicio de la palabra siguiente: salta el resto de la palabra actual y los espacios."""
        n = len(self._text)
        i = max(0, min(pos, n))
        while i < n and self._text[i] not in self._WORD_SEP:
            i += 1
        while i < n and self._text[i] in self._WORD_SEP:
            i += 1
        return i

    def _prev_word(self, pos: int) -> int:
        """Inicio de la palabra anterior: salta espacios a la izquierda y luego la palabra."""
        i = max(0, min(pos, len(self._text)))
        while i > 0 and self._text[i - 1] in self._WORD_SEP:
            i -= 1
        while i > 0 and self._text[i - 1] not in self._WORD_SEP:
            i -= 1
        return i

    def _delete_selection(self) -> None:
        """Borra el texto seleccionado y ajusta cursor. Empuja undo."""
        r = self._sel_range()
        if r is None:
            return
        self._push_undo()
        self._text = self._text[:r[0]] + self._text[r[1]:]
        self._cursor = r[0]
        self._sel_anchor = None
        self._row_starts = self._compute_row_starts(self._text)

    # -----------------------------------------------------------------------
    # Undo
    # -----------------------------------------------------------------------

    def _push_undo(self) -> None:
        self._undo_stack.append((self._text, self._cursor))
        if len(self._undo_stack) > 200:
            self._undo_stack = self._undo_stack[-200:]
        self._redo_stack.clear()  # cualquier edición nueva invalida el redo pendiente

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append((self._text, self._cursor))
        self._text, self._cursor = self._undo_stack.pop()
        self._row_starts = self._compute_row_starts(self._text)
        self._sel_anchor = None
        self.update()
        self.textChanged.emit()

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append((self._text, self._cursor))
        self._text, self._cursor = self._redo_stack.pop()
        self._row_starts = self._compute_row_starts(self._text)
        self._sel_anchor = None
        self.update()
        self.textChanged.emit()

    # -----------------------------------------------------------------------
    # Inserción sin límite
    # -----------------------------------------------------------------------

    def _insert_text(self, text: str) -> None:
        if not text:
            return
        self._push_undo()
        # Reemplaza la selección activa antes de insertar
        if self._sel_anchor is not None:
            r = self._sel_range()
            if r:
                self._text = self._text[:r[0]] + self._text[r[1]:]
                self._cursor = r[0]
            self._sel_anchor = None
        for ch in text:
            self._text = self._text[:self._cursor] + ch + self._text[self._cursor:]
            self._cursor += 1
        self._row_starts = self._compute_row_starts(self._text)
        self.update()
        self.textChanged.emit()

    # -----------------------------------------------------------------------
    # Eventos de foco
    # -----------------------------------------------------------------------

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)

    # -----------------------------------------------------------------------
    # Teclado
    # -----------------------------------------------------------------------

    def keyPressEvent(self, e):
        key   = e.key()
        text  = e.text()
        mod   = e.modifiers()
        shift = bool(mod & Qt.ShiftModifier)
        ctrl  = bool(mod & Qt.ControlModifier)

        if key == Qt.Key_Tab:
            self.tab_pressed.emit()
            return

        # ── Flechas ──────────────────────────────────────────────────────────
        if key == Qt.Key_Left:
            if ctrl:
                # Ctrl+← salta al inicio de la palabra anterior; con Shift, selecciona.
                if shift and self._sel_anchor is None:
                    self._sel_anchor = self._cursor
                elif not shift:
                    self._sel_anchor = None
                self._cursor = self._prev_word(self._cursor)
            elif shift:
                if self._sel_anchor is None:
                    self._sel_anchor = self._cursor
                if self._cursor > 0:
                    self._cursor -= 1
            else:
                sel = self._sel_range()
                if sel:
                    self._cursor = sel[0]
                    self._sel_anchor = None
                elif self._cursor > 0:
                    self._cursor -= 1
            self.update()
            return

        if key == Qt.Key_Right:
            if ctrl:
                # Ctrl+→ salta al inicio de la palabra siguiente; con Shift, selecciona.
                if shift and self._sel_anchor is None:
                    self._sel_anchor = self._cursor
                elif not shift:
                    self._sel_anchor = None
                self._cursor = self._next_word(self._cursor)
            elif shift:
                if self._sel_anchor is None:
                    self._sel_anchor = self._cursor
                if self._cursor < len(self._text):
                    self._cursor += 1
            else:
                sel = self._sel_range()
                if sel:
                    self._cursor = sel[1]
                    self._sel_anchor = None
                elif self._cursor < len(self._text):
                    self._cursor += 1
            self.update()
            return

        if key == Qt.Key_Up:
            if shift and self._sel_anchor is None:
                self._sel_anchor = self._cursor
            elif not shift:
                self._sel_anchor = None
            row, col = self._cursor_row_col(self._cursor)
            if row > 0:
                self._cursor = min(self._cursor_from_cell(row - 1, col), len(self._text))
            self.update()
            return

        if key == Qt.Key_Down:
            if shift and self._sel_anchor is None:
                self._sel_anchor = self._cursor
            elif not shift:
                self._sel_anchor = None
            row, col = self._cursor_row_col(self._cursor)
            if row < self.rows - 1:
                self._cursor = min(self._cursor_from_cell(row + 1, col), len(self._text))
            self.update()
            return

        if key == Qt.Key_Home:
            if shift and self._sel_anchor is None:
                self._sel_anchor = self._cursor
            elif not shift:
                self._sel_anchor = None
            row, _ = self._cursor_row_col(self._cursor)
            self._cursor = self._cursor_from_cell(row, 0)
            self.update()
            return

        if key == Qt.Key_End:
            if shift and self._sel_anchor is None:
                self._sel_anchor = self._cursor
            elif not shift:
                self._sel_anchor = None
            row, _ = self._cursor_row_col(self._cursor)
            self._cursor = self._row_end(row)
            self.update()
            return

        # ── Borrar ───────────────────────────────────────────────────────────
        if key == Qt.Key_Backspace:
            changed = False
            if self._sel_range():
                self._delete_selection()
                changed = True
            elif self._cursor > 0:
                self._push_undo()
                self._text = self._text[:self._cursor - 1] + self._text[self._cursor:]
                self._cursor -= 1
                self._row_starts = self._compute_row_starts(self._text)
                changed = True
            if changed:
                self.update()
                self.textChanged.emit()
            return

        if key == Qt.Key_Delete:
            changed = False
            if self._sel_range():
                self._delete_selection()
                changed = True
            elif self._cursor < len(self._text):
                self._push_undo()
                self._text = self._text[:self._cursor] + self._text[self._cursor + 1:]
                self._row_starts = self._compute_row_starts(self._text)
                changed = True
            if changed:
                self.update()
                self.textChanged.emit()
            return

        # ── Ctrl ─────────────────────────────────────────────────────────────
        if ctrl:
            if key == Qt.Key_Z and shift:
                self._redo()          # Ctrl+Shift+Z
            elif key == Qt.Key_Z:
                self._undo()
            elif key == Qt.Key_Y:
                self._redo()          # Ctrl+Y
            elif key == Qt.Key_A:
                self._sel_anchor = 0
                self._cursor = len(self._text)
                self.update()
            elif key == Qt.Key_C:
                sel = self._selected_text()
                QApplication.clipboard().setText(sel if sel else self._text)
            elif key == Qt.Key_X:
                sel = self._selected_text()
                if sel:
                    QApplication.clipboard().setText(sel)
                    self._delete_selection()
                else:
                    QApplication.clipboard().setText(self._text)
                    self._push_undo()
                    self._text = ""
                    self._cursor = 0
                    self._row_starts = [0]
                self._sel_anchor = None
                self.update()
                self.textChanged.emit()
            elif key == Qt.Key_V:
                # Pegar conserva los saltos de línea (solo normaliza \r).
                paste = QApplication.clipboard().text()
                paste = paste.replace("\r\n", "\n").replace("\r", "\n")
                self._insert_text(paste)
            return

        # ── Enter — salto de línea real (como un campo de texto de Quark) ──
        if key in (Qt.Key_Return, Qt.Key_Enter):
            row, _col = self._cursor_row_col(self._cursor)
            if row < self.rows - 1:
                self._insert_text("\n")
            return

        if text and text.isprintable():
            self._insert_text(text)

    # -----------------------------------------------------------------------
    # IME (caracteres con tilde, ñ, etc.)
    # -----------------------------------------------------------------------

    def inputMethodEvent(self, e):
        commit = e.commitString()
        if commit:
            self._insert_text(commit)
        e.accept()

    def inputMethodQuery(self, query):
        if query == Qt.ImCursorPosition:
            return self._cursor
        if query == Qt.ImSurroundingText:
            return self._text
        return super().inputMethodQuery(query)

    # -----------------------------------------------------------------------
    # Mouse
    # -----------------------------------------------------------------------

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.setFocus(Qt.MouseFocusReason)
        idx = max(0, min(len(self._text),
                         self._index_from_pos(e.pos().x(), e.pos().y())))
        if e.modifiers() & Qt.ShiftModifier:
            if self._sel_anchor is None:
                self._sel_anchor = self._cursor
        else:
            self._sel_anchor = idx  # ancla drag desde el punto de clic
        self._cursor = idx
        self._dragging = True
        self.update()

    def mouseMoveEvent(self, e):
        if not self._dragging:
            return
        self._cursor = max(0, min(len(self._text),
                                  self._index_from_pos(e.pos().x(), e.pos().y())))
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = False
            if self._sel_anchor == self._cursor:
                self._sel_anchor = None

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        idx = max(0, min(len(self._text),
                         self._index_from_pos(e.pos().x(), e.pos().y())))
        start = idx
        while start > 0 and self._text[start - 1] not in " \t":
            start -= 1
        end = idx
        while end < len(self._text) and self._text[end] not in " \t":
            end += 1
        if start < end:
            self._sel_anchor = start
            self._cursor = end
        self._dragging = False
        self.update()

    def _index_from_pos(self, x: int, y: int) -> int:
        padding = 8
        r = self.rect()
        total_cols = self.cols + self._OVERFLOW_COLS
        grid_w = max(1, r.width() - 2 * padding)
        grid_h = max(1, r.height() - 2 * padding)
        cell_w = grid_w / total_cols
        cell_h = grid_h / self.rows
        col = int((x - padding) / cell_w)
        row = int((y - padding) / cell_h)
        col = max(0, min(total_cols - 1, col))
        row = max(0, min(self.rows - 1, row))
        return self._cursor_from_cell(row, col)

    def _update_tooltip(self):
        lines = self.get_lines()
        last = lines[-1] if lines else ""
        overflow = last[self.cols:] if len(last) > self.cols else ""
        if overflow:
            self.setToolTip(f"Texto sobrante ({len(overflow)} chars):\n\"{overflow}\"")
        else:
            self.setToolTip("")

    # -----------------------------------------------------------------------
    # Pintura
    # -----------------------------------------------------------------------

    def _char_display_pos(self, i: int) -> tuple[int, int]:
        """Devuelve (row, col) para el carácter en posición i."""
        rs = self._row_starts
        row = len(rs) - 1
        for r in range(len(rs) - 1, -1, -1):
            if i >= rs[r]:
                row = r
                break
        return row, i - rs[row]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        has_focus = self.hasFocus()
        r = self.rect()
        padding = 8

        p.fillRect(r, _CLR_FOCUS_BG if has_focus else _CLR_BG)

        total_cols = self.cols + self._OVERFLOW_COLS
        grid_w = r.width() - 2 * padding
        grid_h = r.height() - 2 * padding
        cell_w = grid_w / total_cols
        cell_h = grid_h / self.rows

        fm = QFontMetrics(self.font())

        # Celdas del grid
        pen_grid = QPen(_CLR_GRID)
        pen_grid.setWidth(1)
        p.setPen(pen_grid)
        for row in range(self.rows):
            for col in range(total_cols):
                x = int(padding + col * cell_w)
                y = int(padding + row * cell_h)
                if col >= self.cols + _WARN_COLS:
                    bg = _CLR_CELL_OVR
                elif col >= self.cols:
                    bg = _CLR_CELL_WARN
                else:
                    bg = _CLR_CELL
                p.fillRect(x, y, int(cell_w), int(cell_h), bg)
                p.drawRect(x, y, int(cell_w), int(cell_h))

        # Separadores entre filas
        pen_sep = QPen(_CLR_SEP)
        pen_sep.setWidth(2)
        p.setPen(pen_sep)
        for row in range(1, self.rows):
            sep_y = int(padding + row * cell_h)
            p.drawLine(padding, sep_y, r.width() - padding, sep_y)

        # Selección
        sel = self._sel_range()
        if sel:
            for i in range(sel[0], sel[1]):
                s_row, s_col = self._char_display_pos(i)
                if s_col >= total_cols:
                    break
                sx = int(padding + s_col * cell_w)
                sy = int(padding + s_row * cell_h)
                p.fillRect(sx, sy, int(cell_w), int(cell_h), _CLR_SEL)

        # Caracteres (los '\n' no se dibujan: solo marcan el fin de la fila)
        for i, ch in enumerate(self._text):
            if ch == "\n":
                continue
            row, col = self._char_display_pos(i)
            if col >= total_cols:
                break
            if col >= self.cols + _WARN_COLS:
                clr = _CLR_TEXT_OVR
            elif col >= self.cols:
                clr = _CLR_TEXT_WARN
            else:
                clr = _CLR_TEXT
            x = int(padding + col * cell_w)
            y = int(padding + row * cell_h)
            tw = fm.horizontalAdvance(ch)
            th = fm.height()
            tx = x + int((cell_w - tw) / 2)
            ty = y + int((cell_h + th) / 2) - fm.descent()
            p.setPen(QPen(clr))
            p.drawText(tx, ty, ch)

        # Caret de inserción — línea vertical fina ENTRE caracteres (no un rectángulo
        # sobre el siguiente): coincide con la edición real (Backspace borra a la izq.,
        # escribir inserta en el punto), como un campo de texto de Quark.
        if has_focus:
            cur = max(0, min(len(self._text), self._cursor))
            cur_row, cur_col = self._cursor_row_col(cur)
            if cur_col <= total_cols:
                cx = int(padding + cur_col * cell_w)
                cy = int(padding + cur_row * cell_h)
                pen_cursor = QPen(_CLR_CURSOR)
                pen_cursor.setWidth(2)
                p.setPen(pen_cursor)
                p.drawLine(cx, cy + 2, cx, cy + int(cell_h) - 2)

        # Borde de foco
        if has_focus:
            pen_focus = QPen(_CLR_FOCUS_BDR)
            pen_focus.setWidth(2)
            p.setPen(pen_focus)
            p.drawRect(1, 1, r.width() - 2, r.height() - 2)

        p.end()
