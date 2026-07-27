from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPoint, QThread, QPropertyAnimation, QEvent
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QScrollArea, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QMessageBox, QAction, QMenuBar, QShortcut,
    QTabWidget, QComboBox, QFrame, QSizePolicy, QSpinBox,
    QDialog, QDialogButtonBox, QCheckBox,
)
from PyQt5.QtGui import QKeySequence, QTextCursor, QTextCharFormat, QColor, QPainter, QPainterPath, QFont

from ui.widgets.field_block import FieldBlock
from ui.widgets.story_panel import StoryPanel, CharCounter

# ---------------------------------------------------------------------------
# Fórmulas de descuento al cuerpo
# ---------------------------------------------------------------------------

def _calc_deduction(tipo: str, textos: list[str], mq: dict) -> int:
    if tipo == "simple":
        n = len(textos[0]) if textos else 0
        base, umbral = mq.get("textual_simple_base", 400), mq.get("textual_simple_umbral", 100)
        return base + max(0, n - umbral)
    if tipo == "x2":
        t1 = len(textos[0]) if len(textos) > 0 else 0
        t2 = len(textos[1]) if len(textos) > 1 else 0
        base, umbral = mq.get("textual_x2_base", 675), mq.get("textual_x2_umbral", 132)
        return base + max(0, t1 - umbral) + max(0, t2 - umbral)
    if tipo == "x3":
        lens = [len(t) for t in textos[:3]]
        longest = max(lens) if lens else 0
        base, umbral = mq.get("textual_x3_base", 1225), mq.get("textual_x3_umbral", 130)
        return base + max(0, longest - umbral) * 3
    if tipo == "con_foto":
        n = len(textos[0]) if textos else 0
        base, umbral = mq.get("textual_con_foto_base", 500), mq.get("textual_con_foto_umbral", 110)
        return base + int(max(0, n - umbral) * 1.2)
    if tipo == "con_foto_xl":
        n = len(textos[0]) if textos else 0
        base, umbral = mq.get("textual_con_foto_xl_base", 740), mq.get("textual_con_foto_xl_umbral", 130)
        return base + max(0, n - umbral) * 3
    return 0

def _calc_deduction_seccion_especial(base: int, umbral: int, textos: list[str]) -> int:
    """Misma forma que _calc_deduction('x2', ...) pero con base/umbral configurados por
    sección especial (ver Config.secciones_textuales_deduccion) en vez de hardcodeados."""
    t1 = len(textos[0]) if len(textos) > 0 else 0
    t2 = len(textos[1]) if len(textos) > 1 else 0
    return base + max(0, t1 - umbral) + max(0, t2 - umbral)

def _calc_dato_deduction(texto: str, mq: dict) -> int:
    if not texto:
        return 0
    base, umbral = mq.get("dato_base", 300), mq.get("dato_umbral", 100)
    return base + max(0, len(texto) - umbral)

def _calc_numero_deduction(cabecera: str, texto: str, mq: dict) -> int:
    n = len((cabecera or "") + (texto or ""))
    if not n:
        return 0
    base, umbral = mq.get("numero_base", 375), mq.get("numero_umbral", 100)
    return base + max(0, n - umbral)
from ui.widgets.spell_highlighter import SpellHighlighter
from ui.widgets.fotos_browser import FotosBrowser
from ui.widgets.textual_cards_view import TextualCardsView
from ui.maqueta_config_dialog import MaquetaConfigDialog
from services.spell_service import SpellService
from services.textual_detector import TextualDetector
from config.config import config_global
import logging
_log = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Item de error ortográfico en la pestaña de corrección
# ---------------------------------------------------------------------------

class _SpellErrorItem(QFrame):
    clicked_item  = pyqtSignal(dict, str)  # error dict, field name
    navigate_item = pyqtSignal(dict, str)  # double-click: scroll + highlight

    _TYPE_CLR = {
        "spell":     ("#ff6060", "ortográfico"),
        "repeat":    ("#e08940", "repetida adyacente"),
        "proximity": ("#b388ff", "repetida cercana"),
    }

    def __init__(self, err: dict, field: str, parent=None):
        super().__init__(parent)
        self._err = err
        self._field = field
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)

        clr, lbl = self._TYPE_CLR.get(err["type"], ("#aaa", err["type"]))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)

        lbl_field = QLabel(f"[{field}]")
        lbl_field.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 10px;")
        lbl_word = QLabel(err["word"])
        lbl_word.setStyleSheet(f"color: {clr}; font-weight: bold;")
        lbl_type = QLabel(f"— {lbl}")
        lbl_type.setStyleSheet("color: rgba(255,255,255,0.35); font-size: 10px;")

        lay.addWidget(lbl_field)
        lay.addWidget(lbl_word)
        lay.addWidget(lbl_type)
        lay.addStretch(1)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked_item.emit(self._err, self._field)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.navigate_item.emit(self._err, self._field)
        super().mouseDoubleClickEvent(e)


# ---------------------------------------------------------------------------
# Popup flotante de sugerencias ortográficas
# ---------------------------------------------------------------------------

class _SuggestionPopup(QWidget):
    suggestion_chosen = pyqtSignal(str)
    add_to_dict_req = pyqtSignal()
    ignore_req = pyqtSignal()
    replace_requested = pyqtSignal(str)

    _BTN_BASE = (
        "QPushButton {{ text-align: left; padding: 5px 10px; border: none;"
        " border-radius: 5px; background: transparent; color: {clr}; }}"
        " QPushButton:hover {{ background: {hover}; }}"
    )

    def __init__(self, word: str, suggestions: list, err_type: str, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #1e293b; border: 1px solid rgba(255,255,255,0.15);"
            " border-radius: 10px; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(8, 8, 8, 8)
        card_lay.setSpacing(2)

        # Header
        hdr = QHBoxLayout()
        lbl_word = QLabel(f'  "{word}"')
        lbl_word.setStyleSheet(
            "color: #e2e8f0; font-weight: bold; font-size: 13px;"
            " border: none; background: transparent;"
        )
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(22, 22)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton { border: none; background: transparent;"
            " color: rgba(255,255,255,0.45); }"
            " QPushButton:hover { color: #fff; }"
        )
        btn_close.clicked.connect(self.close)
        hdr.addWidget(lbl_word, 1)
        hdr.addWidget(btn_close)
        card_lay.addLayout(hdr)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            "QFrame { border: none; border-top: 1px solid rgba(255,255,255,0.08);"
            " background: transparent; min-height: 1px; max-height: 1px; }"
        )
        card_lay.addWidget(sep)

        if suggestions:
            for sug in suggestions[:5]:
                btn = QPushButton(sug)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(
                    self._BTN_BASE.format(clr="#e2e8f0", hover="rgba(255,255,255,0.10)")
                )
                btn.clicked.connect(
                    lambda _, s=sug: (self.suggestion_chosen.emit(s), self.close())
                )
                card_lay.addWidget(btn)
        else:
            lbl_no = QLabel("Sin sugerencias")
            lbl_no.setStyleSheet(
                "color: rgba(255,255,255,0.4); font-size: 11px; padding: 4px;"
                " border: none; background: transparent;"
            )
            card_lay.addWidget(lbl_no)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(
            "QFrame { border: none; border-top: 1px solid rgba(255,255,255,0.08);"
            " background: transparent; min-height: 1px; max-height: 1px; }"
        )
        card_lay.addWidget(sep2)

        if err_type == "spell":
            btn_dict = QPushButton("Agregar al diccionario")
            btn_dict.setCursor(Qt.PointingHandCursor)
            btn_dict.setStyleSheet(
                self._BTN_BASE.format(clr="#82b4ff", hover="rgba(130,180,255,0.12)")
            )
            btn_dict.clicked.connect(lambda: (self.add_to_dict_req.emit(), self.close()))
            card_lay.addWidget(btn_dict)

        btn_replace_lbl = QPushButton("Reemplazar por...")
        btn_replace_lbl.setCursor(Qt.PointingHandCursor)
        btn_replace_lbl.setStyleSheet(
            self._BTN_BASE.format(clr="rgba(255,255,255,0.55)", hover="rgba(255,255,255,0.08)")
        )
        card_lay.addWidget(btn_replace_lbl)

        self._replace_row = QWidget()
        self._replace_row.setStyleSheet("QWidget { border: none; background: transparent; }")
        replace_lay = QHBoxLayout(self._replace_row)
        replace_lay.setContentsMargins(8, 2, 8, 2)
        replace_lay.setSpacing(4)
        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("Escribir reemplazo…")
        self._replace_edit.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2);"
            " border-radius: 4px; color: #e2e8f0; padding: 3px 6px; }"
        )
        btn_replace_ok = QPushButton("✓")
        btn_replace_ok.setFixedWidth(28)
        btn_replace_ok.setCursor(Qt.PointingHandCursor)
        btn_replace_ok.setStyleSheet(
            "QPushButton { background: rgba(90,188,138,0.25); color: #5abc8a;"
            " border: 1px solid rgba(90,188,138,0.4); border-radius: 4px; }"
            " QPushButton:hover { background: rgba(90,188,138,0.4); }"
        )
        replace_lay.addWidget(self._replace_edit)
        replace_lay.addWidget(btn_replace_ok)
        self._replace_row.setVisible(False)
        card_lay.addWidget(self._replace_row)

        btn_ignore = QPushButton("Omitir")
        btn_ignore.setCursor(Qt.PointingHandCursor)
        btn_ignore.setStyleSheet(
            self._BTN_BASE.format(
                clr="rgba(255,255,255,0.55)", hover="rgba(255,255,255,0.08)"
            )
        )
        btn_ignore.clicked.connect(lambda: (self.ignore_req.emit(), self.close()))
        card_lay.addWidget(btn_ignore)

        btn_replace_lbl.clicked.connect(lambda: (
            self._replace_row.setVisible(True),
            self._replace_edit.setFocus(),
            self.adjustSize(),
        ))
        btn_replace_ok.clicked.connect(self._on_replace_confirm)
        self._replace_edit.returnPressed.connect(self._on_replace_confirm)

        outer.addWidget(card)
        self.adjustSize()

    def _on_replace_confirm(self):
        text = self._replace_edit.text().strip()
        if text:
            self.replace_requested.emit(text)
            self.close()


# ---------------------------------------------------------------------------
# Card seleccionable para candidatos a "dato"
# ---------------------------------------------------------------------------

class _DatoCard(QFrame):
    selected = pyqtSignal(str)
    edit_requested = pyqtSignal()

    def __init__(self, text: str, limit: int, parent=None):
        super().__init__(parent)
        self._text = text
        self._edited_text = text
        self._titulo = ""
        self._limit = limit
        self._is_selected = False
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        self.lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outer.addWidget(self.lbl)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        _btn_style = (
            "QPushButton { font-size: 10px; padding: 0 6px;"
            " background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);"
            " border-radius: 4px; color: rgba(255,255,255,0.5); }"
            " QPushButton:hover { background: rgba(255,255,255,0.12); color: #e2e8f0; }"
        )
        self.btn_edit = QPushButton("✎ Editar")
        self.btn_edit.setFixedHeight(20)
        self.btn_edit.setStyleSheet(_btn_style)
        self.btn_edit.clicked.connect(self.edit_requested.emit)

        self.lbl_cnt = QLabel()
        self.lbl_cnt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.btn_edit)
        bottom.addStretch(1)
        bottom.addWidget(self.lbl_cnt)
        outer.addLayout(bottom)
        self.update_display()

    def update_display(self):
        t = self._edited_text
        base = t if len(t) <= 110 else t[:107] + "…"
        if self._titulo:
            base = f"{self._titulo}  ·  {base}"
        self.lbl.setText(base)
        self.lbl.setStyleSheet("border: none; background: transparent;")
        n = len(t)
        if n > self._limit:
            cnt_clr = "#ff6060"
        elif n >= int(self._limit * 0.90):
            cnt_clr = "#5abc8a"
        else:
            cnt_clr = "rgba(255,255,255,0.45)"
        self.lbl_cnt.setText(f"{n}/{self._limit}")
        self.lbl_cnt.setStyleSheet(f"color: {cnt_clr}; font-size: 10px; border: none; background: transparent;")

    def set_edited_text(self, text: str):
        self._edited_text = text
        self.update_display()

    def set_titulo(self, titulo: str):
        self._titulo = (titulo or "").strip()
        self.update_display()

    def get_data(self) -> dict:
        return {"titulo": self._titulo.strip(), "texto": self._edited_text.strip()}

    def set_selected(self, val: bool):
        self._is_selected = val
        self.setProperty("selected", val)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._is_selected = not self._is_selected
            self.set_selected(self._is_selected)
            self.selected.emit(self._text)
        super().mousePressEvent(e)


# ---------------------------------------------------------------------------
# Card para el número destacado
# ---------------------------------------------------------------------------

class _NumeroCard(QFrame):
    edit_requested = pyqtSignal()
    toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cabecera = ""
        self._texto = ""
        self._is_selected = False
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        self.lbl = QLabel("— sin número —")
        self.lbl.setWordWrap(True)
        self.lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.lbl.setStyleSheet("color: rgba(255,255,255,0.35); border: none; background: transparent;")
        outer.addWidget(self.lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_edit = QPushButton("✎ Editar")
        self.btn_edit.setFixedHeight(20)
        self.btn_edit.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 0 6px;"
            " background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);"
            " border-radius: 4px; color: rgba(255,255,255,0.5); }"
            " QPushButton:hover { background: rgba(255,255,255,0.12); color: #e2e8f0; }"
        )
        self.btn_edit.clicked.connect(self.edit_requested.emit)
        btn_row.addWidget(self.btn_edit)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

    def set_selected(self, val: bool):
        self._is_selected = val
        self.setProperty("selected", val)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_data(self, cabecera: str, texto: str):
        self._cabecera = cabecera.strip()
        self._texto = texto.strip()
        if self._cabecera or self._texto:
            display = self._texto
            if self._cabecera:
                display += f"  ·  {self._cabecera}"
            self.lbl.setText(display)
            self.lbl.setStyleSheet("color: #e2e8f0; border: none; background: transparent;")
        else:
            self.lbl.setText("— sin número —")
            self.lbl.setStyleSheet("color: rgba(255,255,255,0.35); border: none; background: transparent;")

    def get_data(self) -> dict:
        return {"cabecera": self._cabecera, "texto": self._texto}

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_selected(not self._is_selected)
            self.toggled.emit()
        super().mousePressEvent(e)


# ---------------------------------------------------------------------------
# Diálogo de edición del número destacado
# ---------------------------------------------------------------------------

class _NumeroEditDialog(QDialog):
    def __init__(self, cabecera: str = "", texto: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Número destacado")
        self.setMinimumWidth(340)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Cabecera:"))
        self._ed_cab = QLineEdit(cabecera)
        self._ed_cab.setPlaceholderText("Ej: 47%")
        lay.addWidget(self._ed_cab)

        lay.addWidget(QLabel("Texto:"))
        self._ed_txt = QPlainTextEdit(texto)
        self._ed_txt.setPlaceholderText("Descripción del número")
        self._ed_txt.setFixedHeight(90)
        lay.addWidget(self._ed_txt)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def get_result(self) -> dict:
        return {
            "cabecera": self._ed_cab.text().strip(),
            "texto": self._ed_txt.toPlainText().strip(),
        }


# ---------------------------------------------------------------------------
# Diálogo de edición del dato destacado
# ---------------------------------------------------------------------------

class _DatoEditDialog(QDialog):
    def __init__(self, text: str = "", limit: int = 120, titulo: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar dato")
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Título:"))
        self._ed_titulo = QLineEdit(titulo)
        self._ed_titulo.setPlaceholderText("Ej: El dato")
        lay.addWidget(self._ed_titulo)

        lay.addWidget(QLabel("Texto del dato destacado:"))
        self._ed = QPlainTextEdit(text)
        self._ed.setFixedHeight(100)
        lay.addWidget(self._ed)

        self._cnt = CharCounter(limit, 50, self._ed)
        self._ed.textChanged.connect(lambda: self._cnt.update_count(self._ed.toPlainText()))
        lay.addWidget(self._cnt)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._cnt.update_count(text)

    def get_result(self) -> dict:
        return {
            "titulo": self._ed_titulo.text().strip(),
            "texto": self._ed.toPlainText().strip(),
        }


# ---------------------------------------------------------------------------
# Overlay flotante de flecha para indicar dirección del texto resaltado
# ---------------------------------------------------------------------------

class _SelectionArrowOverlay(QWidget):
    def __init__(self, parent: QPlainTextEdit, on_click=None):
        super().__init__(parent)
        self._direction = "down"
        self._label = ""
        self._on_click = on_click
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(38, 52)
        self.setCursor(Qt.PointingHandCursor)
        self._opacity = 1.0
        self._anim = None

    @property
    def direction(self):
        return self._direction

    @direction.setter
    def direction(self, val):
        self._direction = val
        self.update()

    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, val):
        self._label = val
        self.update()

    def _reposition(self):
        p = self.parent()
        if p:
            self.move(p.width() - self.width() - 8,
                      p.height() // 2 - self.height() // 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(100, 180, 255, int(200 * self._opacity))
        bg    = QColor(100, 180, 255, int(60 * self._opacity))

        rect = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), 6, 6)
        painter.fillPath(path, bg)
        painter.setPen(color)
        painter.drawPath(path)

        cx = self.width() // 2
        arrow_cy = self.height() // 2 - 6
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        arrow = QPainterPath()
        if self._direction == "up":
            arrow.moveTo(cx, arrow_cy - 8)
            arrow.lineTo(cx - 7, arrow_cy + 6)
            arrow.lineTo(cx + 7, arrow_cy + 6)
        else:
            arrow.moveTo(cx, arrow_cy + 8)
            arrow.lineTo(cx - 7, arrow_cy - 6)
            arrow.lineTo(cx + 7, arrow_cy - 6)
        arrow.closeSubpath()
        painter.drawPath(arrow)

        if self._label:
            f = painter.font()
            f.setPixelSize(9)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(color)
            lbl_rect = self.rect().adjusted(2, self.height() - 18, -2, -2)
            painter.drawText(lbl_rect, Qt.AlignCenter, self._label)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._on_click:
            self._on_click()
        super().mousePressEvent(e)

    def fade_out(self):
        self.hide()


# ---------------------------------------------------------------------------
# Reemplazos de usuario para el corrector ortográfico
# ---------------------------------------------------------------------------

class _UserReplacements:
    """Persiste un dict {palabra_original: [reemplazo1, ...]} en DATA_DIR."""
    try:
        from config.config import config_global as _cfg
        _path = _cfg.DATA_DIR / "user_replacements.json"
    except Exception:
        _path = None

    @classmethod
    def _load(cls) -> dict:
        if cls._path and cls._path.exists():
            try:
                return json.loads(cls._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    @classmethod
    def get(cls, word: str) -> list:
        return cls._load().get(word.lower(), [])

    @classmethod
    def add(cls, word: str, replacement: str):
        if not cls._path:
            return
        data = cls._load()
        key = word.lower()
        lst = data.get(key, [])
        if replacement in lst:
            lst.remove(replacement)
        lst.insert(0, replacement)
        data[key] = lst[:10]
        try:
            cls._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Worker para operaciones bulk de spell en hilo de fondo
# ---------------------------------------------------------------------------

class _SpellBulkWorker(QThread):
    finished = pyqtSignal()

    def __init__(self, highlighters: list, words: set, action: str):
        super().__init__()
        self._hls = highlighters
        self._words = words
        self._action = action  # "add" | "ignore"

    def run(self):
        lower = {w.lower() for w in self._words}
        for hl in self._hls:
            if self._action == "add":
                for w in lower:
                    hl._spell.add_word(w)
                    hl._ignored.discard(w)
            else:
                hl._ignored.update(lower)
            hl._errors = [e for e in hl._errors if e["word"].lower() not in lower]
        self.finished.emit()


# ---------------------------------------------------------------------------
# Notificación flotante (toast)
# ---------------------------------------------------------------------------

class _ToastNotification(QWidget):
    def __init__(self, parent, message: str):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        lbl = QLabel(message, self)
        lbl.setStyleSheet(
            "background: rgba(30,40,55,0.92); color: #e2e8f0;"
            " border: 1px solid rgba(130,180,255,0.30); border-radius: 10px;"
            " padding: 8px 18px; font-size: 13px;"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(lbl)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        QTimer.singleShot(5000, self._fade_out)

    def _reposition(self):
        p = self.parent()
        if p:
            x = (p.width() - self.width()) // 2
            self.move(x, 18)

    def _fade_out(self):
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(400)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()


# ---------------------------------------------------------------------------
# Ventana principal del editor
# ---------------------------------------------------------------------------

class EditorNotaWindow(QMainWindow):
    nota_guardada = pyqtSignal(int)
    nota_guardada_para_armar = pyqtSignal(int)
    nota_guardada_para_armado_bot = pyqtSignal(int)   # 'Guardar para armado automático' (flag armado_bot)
    maqueta_limits_guardados = pyqtSignal()   # límites de maqueta editados → publicar a estaciones

    def __init__(
        self,
        numero: int,
        noticia_index: int,
        controller,
        maqueta_cfg: dict,
        parent=None,
    ):
        super().__init__(parent)
        self.numero = numero
        self.noticia_index = noticia_index
        self.controller = controller
        self._mq = dict(maqueta_cfg)
        self._seccion: str = ""

        self._spell: SpellService | None = None
        self._hl_bajada: SpellHighlighter | None = None
        self._hl_cuerpo: SpellHighlighter | None = None

        self._detector = TextualDetector()
        self._stories: list[StoryPanel] = []
        # Deducción por recursos (textual/dato/número/QR/foto) de la PRINCIPAL, cacheada
        # aparte para poder sumarle el consumo de las secundarias aunque la principal no
        # esté activa (ver _refresh_primary_secondary_deduction).
        self._primary_resource_deduction: int = 0
        self._qr_path: Path | None = None
        self._body_highlight_range: tuple[int, int] | None = None
        self._highlight_source: str = ""  # "textual", "dato", "numero"
        self._arrow_overlay: _SelectionArrowOverlay | None = None

        # Recursos (foto/textual/dato/número/QR) independientes POR NOTICIA: los widgets
        # de la derecha son compartidos (una sola instancia), pero su estado se cachea por
        # índice de noticia y se recarga al cambiar de pestaña (ver _on_story_switch).
        self._active_res_idx = 0
        self._res_cache: dict[int, dict] = {}

        self.setWindowTitle(f"Editor de nota — Página {numero}")
        self._pagina = None
        self.showMaximized()

        self._build_ui()
        self._apply_qss()
        self._load_nota()

        QTimer.singleShot(0, self._init_spell)
        QTimer.singleShot(80, self._init_splitter)

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        mq = self._mq

        # Menú
        mb = QMenuBar(self)
        self.setMenuBar(mb)
        m_config = mb.addMenu("Configuración")
        act_cfg = QAction("Límites de maqueta...", self)
        act_cfg.triggered.connect(self._open_config)
        m_config.addAction(act_cfg)
        act_display = QAction("Visualización...", self)
        act_display.triggered.connect(self._open_display_config)
        m_config.addAction(act_display)

        # Menú IA
        m_ia = mb.addMenu("IA")
        act_ia_cfg = QAction("Configurar IA…", self)
        act_ia_cfg.triggered.connect(self._on_configurar_ia)
        m_ia.addAction(act_ia_cfg)
        self._act_ia_auto = QAction("Reescritura automática al guardar", self)
        self._act_ia_auto.setCheckable(True)
        try:
            from config.config import config_global as _cg
            self._act_ia_auto.setChecked(_cg.ia_auto_enabled)
        except Exception:
            pass
        self._act_ia_auto.toggled.connect(self._on_toggle_ia_auto)
        m_ia.addAction(self._act_ia_auto)

        # Central
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.split = QSplitter(Qt.Horizontal)
        root.addWidget(self.split)

        # ── Panel izquierdo: contenedor con header fijo + scroll ──
        left_panel = QWidget()
        left_panel_lay = QVBoxLayout(left_panel)
        left_panel_lay.setContentsMargins(0, 0, 0, 0)
        left_panel_lay.setSpacing(0)
        self.split.addWidget(left_panel)

        # ── Cabecera fija (siempre visible) ──
        self._left_header = QWidget()
        self._left_header.setObjectName("leftHeader")
        hdr_lay = QVBoxLayout(self._left_header)
        hdr_lay.setContentsMargins(14, 8, 14, 6)
        hdr_lay.setSpacing(6)

        # Fila 1 compacta: título de página + maqueta + noticias (antes eran 2 filas;
        # el espacio ahorrado deja visible el epígrafe en pantallas 1366×768).
        maqueta_row = QHBoxLayout()
        maqueta_row.setSpacing(8)
        self._lbl_page = QLabel(f"Página {self.numero}")
        self._lbl_page.setProperty("pageTitle", True)
        maqueta_row.addWidget(self._lbl_page)
        maqueta_row.addSpacing(10)
        maqueta_row.addWidget(QLabel("Maqueta:"))
        self._cb_maqueta = QComboBox()
        try:
            from services.maqueta_reader_service import get_templates
            self._cb_maqueta.addItems(get_templates())
        except Exception:
            pass
        maqueta_row.addWidget(self._cb_maqueta, 1)
        maqueta_row.addWidget(QLabel("Noticias:"))
        self._sb_noticias = QSpinBox()
        self._sb_noticias.setRange(1, 4)
        self._sb_noticias.setValue(1)
        self._sb_noticias.setFixedWidth(50)
        maqueta_row.addWidget(self._sb_noticias)
        hdr_lay.addLayout(maqueta_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_guardar = QPushButton("Guardar  Ctrl+S")
        self._btn_guardar.setCursor(Qt.PointingHandCursor)
        self._btn_guardar.setProperty("primary", True)
        self._btn_guardar.setProperty("compact", True)   # botones del header 15% más chicos
        self._btn_guardar_armar = QPushButton("Guardar para armar  Ctrl+G")
        self._btn_guardar_armar.setCursor(Qt.PointingHandCursor)
        self._btn_guardar_armar.setProperty("primary", True)
        self._btn_guardar_armar.setProperty("compact", True)
        self._btn_guardar_bot = QPushButton("Guardar para armado automático")
        self._btn_guardar_bot.setCursor(Qt.PointingHandCursor)
        self._btn_guardar_bot.setProperty("primary", True)
        self._btn_guardar_bot.setProperty("compact", True)
        self._btn_ia_todo = QPushButton("✨ Reescribir todo")
        self._btn_ia_todo.setCursor(Qt.PointingHandCursor)
        self._btn_ia_todo.setProperty("compact", True)
        self._btn_ia_todo.setToolTip(
            "Reescribir con IA toda la noticia activa respetando los límites de cada campo"
        )
        self._btn_ia_todo.setStyleSheet(
            "QPushButton { color: #f5c542; background: rgba(245,197,66,0.12);"
            " border: 1px solid rgba(245,197,66,0.35); border-radius: 6px; padding: 4px 10px; }"
            " QPushButton:hover { background: #f5c542; color: #1a2535; }"
            " QPushButton:disabled { color: rgba(245,197,66,0.35); }"
        )
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_ia_todo)
        btn_row.addWidget(self._btn_guardar)
        btn_row.addWidget(self._btn_guardar_armar)
        btn_row.addWidget(self._btn_guardar_bot)
        hdr_lay.addLayout(btn_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { border: none; border-top: 1px solid rgba(255,255,255,0.08); }")
        hdr_lay.addWidget(sep)

        left_panel_lay.addWidget(self._left_header)

        # ── Scroll area (solo las pestañas de noticias) ──
        self._left_scroll = QScrollArea()
        self._left_scroll.setWidgetResizable(True)
        self._left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._left_scroll.setFocusPolicy(Qt.NoFocus)
        self._left_scroll.viewport().setFocusPolicy(Qt.NoFocus)

        left_container = QWidget()
        self._left_lay = QVBoxLayout(left_container)
        self._left_lay.setContentsMargins(14, 8, 14, 14)
        self._left_lay.setSpacing(8)

        self._left_scroll.setWidget(left_container)
        left_panel_lay.addWidget(self._left_scroll, 1)
        # Colapso del bloque superior: la rueda sobre el panel izquierdo lo gobierna.
        self._resist_acc = 0
        self._left_scroll.viewport().installEventFilter(self)

        # ── Pestañas de noticias ──
        self._story_tabs = QTabWidget()
        self._left_lay.addWidget(self._story_tabs, 1)

        # ── Swap button ──
        self._btn_swap = QPushButton("⇄  Intercambiar noticias")
        self._btn_swap.setCursor(Qt.PointingHandCursor)
        self._btn_swap.setVisible(False)
        self._left_lay.addWidget(self._btn_swap)

        # ── Panel derecho (tabs) ──
        from ui.widgets.alert_tab_bar import AlertTabWidget
        self._right_tabs = AlertTabWidget()
        self.split.addWidget(self._right_tabs)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([720, 440])

        # Tab Fotos
        self._tab_fotos = QWidget()
        self._fotos_lay = QVBoxLayout(self._tab_fotos)
        self._fotos_lay.setContentsMargins(4, 4, 4, 4)

        foto_tipo_row = QHBoxLayout()
        foto_tipo_row.addWidget(QLabel("Tipo de foto:"))
        self._cb_foto_tipo = QComboBox()
        self._cb_foto_tipo.addItems(
            ["Sin foto", "2 columnas", "3 columnas", "3 columnas ancha", "4 columnas"])
        self._cb_foto_tipo.setCurrentText("2 columnas")
        foto_tipo_row.addWidget(self._cb_foto_tipo)
        foto_tipo_row.addStretch(1)
        self._btn_agregar_foto = QPushButton("  Agregar foto")
        _icono_foto = Path(__file__).parent / "assets" / "agregar-foto.png"
        if _icono_foto.exists():
            from PyQt5.QtGui import QIcon
            from PyQt5.QtCore import QSize
            self._btn_agregar_foto.setIcon(QIcon(str(_icono_foto)))
            self._btn_agregar_foto.setIconSize(QSize(20, 20))   # ícono 10% más grande
        # Texto 10% más chico (setFont para no pisar el chrome del QSS).
        _f_foto = self._btn_agregar_foto.font()
        _f_foto.setPointSizeF(_f_foto.pointSizeF() * 0.9)
        self._btn_agregar_foto.setFont(_f_foto)
        self._btn_agregar_foto.setCursor(Qt.PointingHandCursor)
        self._btn_agregar_foto.setToolTip("Copiar una imagen del disco a la carpeta de materiales de la página")
        self._btn_agregar_foto.clicked.connect(self._on_agregar_foto)
        foto_tipo_row.addWidget(self._btn_agregar_foto)
        self._fotos_lay.addLayout(foto_tipo_row)

        self._fotos_browser = FotosBrowser(Path("."), parent=self._tab_fotos)
        self._fotos_browser.usar_epigrafe.connect(self._on_usar_epigrafe)
        self._fotos_browser.qr_seleccionada.connect(self._on_qr_seleccionada)
        self._fotos_lay.addWidget(self._fotos_browser)

        # Tab Textuales
        self._tab_textuales = QWidget()
        lay_tx = QVBoxLayout(self._tab_textuales)
        lay_tx.setContentsMargins(4, 4, 4, 4)

        tipo_row = QHBoxLayout()
        tipo_row.addWidget(QLabel("Tipo textual:"))
        self._cb_textual_tipo = QComboBox()
        self._cb_textual_tipo.addItems(["—", "simple", "x2", "con foto", "con foto XL"])
        tipo_row.addWidget(self._cb_textual_tipo)
        tipo_row.addStretch(1)
        lay_tx.addLayout(tipo_row)

        self._textual_cards = TextualCardsView(self._tab_textuales)
        self._textual_cards.set_limits(
            sin_foto=mq.get("textual_sin_foto_limit", 220),
            con_foto=mq.get("textual_con_foto_limit", 320),
            epigrafe=mq.get("textual_epigrafe_limit", 90),
        )
        lay_tx.addWidget(self._textual_cards, 1)
        hint = QLabel("Doble clic para editar. Máximo 3 seleccionados.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px;")
        lay_tx.addWidget(hint)
        self._btn_reanalizar = QPushButton("Re-analizar")
        self._btn_reanalizar.setCursor(Qt.PointingHandCursor)
        lay_tx.addWidget(self._btn_reanalizar)

        self._btn_sel_textual = QPushButton("Selección manual en texto")
        self._btn_sel_textual.setCheckable(True)
        self._btn_sel_textual.setCursor(Qt.PointingHandCursor)
        lay_tx.addWidget(self._btn_sel_textual)

        self._sel_textual_row = QWidget()
        sel_row_lay = QHBoxLayout(self._sel_textual_row)
        sel_row_lay.setContentsMargins(0, 0, 0, 0)
        self._btn_sel_accept = QPushButton("Aceptar")
        self._btn_sel_cancel = QPushButton("Cancelar")
        self._btn_sel_accept.setCursor(Qt.PointingHandCursor)
        self._btn_sel_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_sel_accept.setStyleSheet(
            "QPushButton { background: rgba(90,188,138,0.20); color: #5abc8a;"
            " border: 1px solid rgba(90,188,138,0.5); border-radius: 6px; padding: 4px 10px; }"
            " QPushButton:hover { background: rgba(90,188,138,0.35); }"
        )
        self._btn_sel_cancel.setStyleSheet(
            "QPushButton { background: rgba(230,120,60,0.18); color: #e87844;"
            " border: 1px solid rgba(230,120,60,0.4); border-radius: 6px; padding: 4px 10px; }"
            " QPushButton:hover { background: rgba(230,120,60,0.30); }"
        )
        sel_row_lay.addWidget(self._btn_sel_accept)
        sel_row_lay.addWidget(self._btn_sel_cancel)
        self._sel_textual_row.setVisible(False)
        lay_tx.addWidget(self._sel_textual_row)

        # Tab Dato
        self._tab_dato = QWidget()
        lay_dt = QVBoxLayout(self._tab_dato)
        lay_dt.setContentsMargins(4, 4, 4, 4)
        lay_dt.setSpacing(6)

        lbl_dato_hdr = QLabel("Candidatos detectados:")
        lbl_dato_hdr.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 11px;")
        lay_dt.addWidget(lbl_dato_hdr)

        hint_dato = QLabel("Clic para seleccionar")
        hint_dato.setStyleSheet("color: rgba(255,255,255,0.30); font-size: 10px;")
        lay_dt.addWidget(hint_dato)

        self._btn_agregar_dato = QPushButton("＋ Agregar dato")
        self._btn_agregar_dato.setCursor(Qt.PointingHandCursor)
        self._btn_agregar_dato.clicked.connect(self._on_agregar_dato_manual)
        lay_dt.addWidget(self._btn_agregar_dato)

        self._dato_scroll = QScrollArea()
        self._dato_scroll.setWidgetResizable(True)
        self._dato_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._dato_container = QWidget()
        self._dato_lay_cards = QVBoxLayout(self._dato_container)
        self._dato_lay_cards.setContentsMargins(2, 2, 2, 2)
        self._dato_lay_cards.setSpacing(4)
        self._dato_lay_cards.addStretch(1)
        self._dato_scroll.setWidget(self._dato_container)
        lay_dt.addWidget(self._dato_scroll, 1)
        self._btn_sel_dato, self._sel_dato_row = self._crear_sel_manual_ui(lay_dt, "dato")
        lay_dt.addStretch(0)

        self._dato_cards: list[_DatoCard] = []

        # Tab Número
        self._tab_numero = QWidget()
        lay_num = QVBoxLayout(self._tab_numero)
        lay_num.setContentsMargins(4, 4, 4, 4)
        lay_num.setSpacing(6)

        lbl_num_desc = QLabel("Bloque de número destacado. Doble clic en la card para editar.")
        lbl_num_desc.setWordWrap(True)
        lbl_num_desc.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px;")
        lay_num.addWidget(lbl_num_desc)

        btn_agregar_num = QPushButton("＋ Agregar número")
        btn_agregar_num.setCursor(Qt.PointingHandCursor)
        btn_agregar_num.clicked.connect(self._on_numero_edit)
        lay_num.addWidget(btn_agregar_num)

        self._numero_card = _NumeroCard()
        self._numero_card.edit_requested.connect(self._on_numero_edit)
        self._numero_card.toggled.connect(self._recalcular_deduccion)
        self._numero_card.toggled.connect(self._on_numero_card_toggled)
        lay_num.addWidget(self._numero_card)
        self._btn_sel_numero, self._sel_numero_row = self._crear_sel_manual_ui(lay_num, "numero")
        lay_num.addStretch(1)

        # Tab Contar caracteres — selección acumulativa de fragmentos del cuerpo para
        # saber cuántos caracteres (con espacios) tiene lo seleccionado / lo no seleccionado
        # y compararlos contra el límite de la maqueta (hasta dónde y qué cortar).
        self._tab_fragmentos = QWidget()
        lay_fr = QVBoxLayout(self._tab_fragmentos)
        lay_fr.setContentsMargins(4, 4, 4, 4)
        lay_fr.setSpacing(6)

        lbl_fr_desc = QLabel("Arrastrá una selección en el cuerpo: el conteo se calcula al instante. "
                             "Usá «Agregar selección» para sumar otro tramo no contiguo.")
        lbl_fr_desc.setWordWrap(True)
        lbl_fr_desc.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px;")
        lay_fr.addWidget(lbl_fr_desc)

        self._lbl_frag_sel = QLabel("Seleccionado: 0")
        self._lbl_frag_no_sel = QLabel("No seleccionado: 0")
        self._lbl_frag_limite = QLabel("Límite maqueta: —")
        for _l in (self._lbl_frag_sel, self._lbl_frag_no_sel, self._lbl_frag_limite):
            _l.setStyleSheet("font-size: 13px; color: #e2e8f0;")
            lay_fr.addWidget(_l)

        self._frag_scroll = QScrollArea()
        self._frag_scroll.setWidgetResizable(True)
        self._frag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._frag_container = QWidget()
        self._frag_lay = QVBoxLayout(self._frag_container)
        self._frag_lay.setContentsMargins(2, 2, 2, 2)
        self._frag_lay.setSpacing(4)
        self._frag_lay.addStretch(1)
        self._frag_scroll.setWidget(self._frag_container)
        lay_fr.addWidget(self._frag_scroll, 1)

        # Pinta el cuerpo con un tinte desde el inicio hasta el punto donde se alcanza el
        # límite cce de la maqueta (hasta dónde entra el texto), y el excedente en rojo.
        self._chk_pintar_limite = QCheckBox("Pintar el cuerpo hasta el límite")
        self._chk_pintar_limite.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        self._chk_pintar_limite.toggled.connect(lambda _=False: self._aplicar_extra_selections())
        lay_fr.addWidget(self._chk_pintar_limite)

        self._btn_frag_limpiar = QPushButton("Limpiar todo")
        self._btn_frag_limpiar.setCursor(Qt.PointingHandCursor)
        self._btn_frag_limpiar.clicked.connect(self._on_frag_limpiar)
        lay_fr.addWidget(self._btn_frag_limpiar)

        self._btn_sel_frag, self._sel_frag_row = self._crear_sel_manual_ui(
            lay_fr, "fragmento", toggle_text="Selección de fragmentos",
            ok_text="Agregar selección", cancel_text="Terminar")

        self._frag_ranges: list = []   # rangos (start, end) fusionados del documento

        # Tab Corrección ortográfica
        self._tab_corr = QWidget()
        lay_corr = QVBoxLayout(self._tab_corr)
        lay_corr.setContentsMargins(4, 4, 4, 4)
        lay_corr.setSpacing(4)
        self._lbl_corr_hdr = QLabel("Sin errores detectados")
        self._lbl_corr_hdr.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.55);")
        lay_corr.addWidget(self._lbl_corr_hdr)
        self._corr_scroll = QScrollArea()
        self._corr_scroll.setWidgetResizable(True)
        self._corr_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._corr_container = QWidget()
        self._corr_lay = QVBoxLayout(self._corr_container)
        self._corr_lay.setContentsMargins(2, 2, 2, 2)
        self._corr_lay.setSpacing(3)
        self._corr_lay.addStretch(1)
        self._corr_scroll.setWidget(self._corr_container)
        lay_corr.addWidget(self._corr_scroll, 1)
        self._spell_errors_by_field: dict[str, list] = {}

        corr_btns = QHBoxLayout()
        self._btn_add_all_dict = QPushButton("Agregar todas al diccionario")
        self._btn_ignore_all   = QPushButton("Omitir todas")
        self._btn_add_all_dict.setCursor(Qt.PointingHandCursor)
        self._btn_ignore_all.setCursor(Qt.PointingHandCursor)
        self._btn_add_all_dict.setStyleSheet(
            "QPushButton { background: rgba(90,188,138,0.18); color: #5abc8a;"
            " border: 1px solid rgba(90,188,138,0.4); border-radius: 6px; padding: 4px 8px; }"
            " QPushButton:hover { background: rgba(90,188,138,0.30); }"
        )
        self._btn_ignore_all.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.6);"
            " border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 4px 8px; }"
            " QPushButton:hover { background: rgba(255,255,255,0.12); }"
        )
        corr_btns.addWidget(self._btn_add_all_dict)
        corr_btns.addWidget(self._btn_ignore_all)
        lay_corr.addLayout(corr_btns)

        self._right_tabs.addTab(self._tab_fotos, "Fotos")
        self._right_tabs.addTab(self._tab_textuales, "Textuales")
        self._right_tabs.addTab(self._tab_dato, "Dato")
        self._right_tabs.addTab(self._tab_numero, "Número")
        self._right_tabs.addTab(self._tab_fragmentos, "Contar caracteres")
        self._right_tabs.addTab(self._tab_corr, "Corrección")
        # Si las tabs no entran en el ancho, el QTabBar muestra flechas ‹ › para navegar.
        self._right_tabs.tabBar().setUsesScrollButtons(True)

        # Señales
        self._cb_textual_tipo.currentTextChanged.connect(self._on_textual_tipo_changed)
        self._cb_textual_tipo.currentTextChanged.connect(lambda _: self._recalcular_deduccion())
        self._textual_cards.changed.connect(self._recalcular_deduccion)
        self._textual_cards.changed.connect(self._on_textual_selection_changed)
        self._cb_foto_tipo.currentTextChanged.connect(lambda _: self._recalcular_deduccion())
        self._btn_reanalizar.clicked.connect(self._on_detect_textuales)
        self._btn_guardar.clicked.connect(self._on_guardar)
        self._btn_guardar_armar.clicked.connect(self._on_guardar_para_armar)
        self._btn_guardar_bot.clicked.connect(self._on_guardar_para_armado_bot)
        self._btn_ia_todo.clicked.connect(self._on_reescribir_todo)
        self._cb_maqueta.activated[str].connect(self._on_maqueta_changed)
        self._btn_swap.clicked.connect(self._on_swap)
        self._sb_noticias.valueChanged.connect(self._on_story_count_changed)
        self._btn_add_all_dict.clicked.connect(self._on_add_all_to_dict)
        self._btn_ignore_all.clicked.connect(self._on_ignore_all)
        self._btn_sel_textual.toggled.connect(
            lambda on: self._on_sel_mode_toggled("textual", on))
        self._btn_sel_accept.clicked.connect(
            lambda: self._on_sel_mode_accept("textual"))
        self._btn_sel_cancel.clicked.connect(
            lambda: self._on_sel_mode_cancel("textual"))
        self._right_tabs.currentChanged.connect(self._on_right_tab_changed)
        self._story_tabs.currentChanged.connect(self._on_story_switch)

        sc = QShortcut(QKeySequence("Ctrl+S"), self)
        sc.activated.connect(self._on_guardar)
        sc_g = QShortcut(QKeySequence("Ctrl+G"), self)
        sc_g.activated.connect(self._on_guardar_para_armar)

    def _init_splitter(self):
        total = self.split.width()
        right_w = 420
        if total > right_w + 200:
            self.split.setSizes([total - right_w, right_w])

    # ------------------------------------------------------------------
    # Gestión de pestañas de noticias
    # ------------------------------------------------------------------

    def _active_story(self) -> "StoryPanel":
        """La noticia cuyos recursos (foto/textual/dato/número) muestran/editan los tabs
        de la derecha ahora mismo — sigue a la pestaña de noticia activa (_story_tabs)."""
        idx = self._active_res_idx if self._active_res_idx < len(self._stories) else 0
        return self._stories[idx] if self._stories else None

    def _add_story_panel(self, story_index: int) -> StoryPanel:
        panel = StoryPanel(story_index, self._mq)
        label = "Principal" if story_index == 0 else f"Noticia {story_index + 1}"
        self._story_tabs.addTab(panel, label)
        self._stories.append(panel)
        panel.body_display_changed.connect(self._on_body_display_changed)
        panel.ia_config_needed.connect(self._on_configurar_ia)
        panel.ia_busy_changed.connect(self._on_ia_busy_changed)
        # La rueda dentro del cuerpo también gobierna el colapso del bloque superior.
        panel.ed_cuerpo.viewport().installEventFilter(self)

        # Cuerpo/bajada de TODAS las noticias alimentan la detección de recursos, el
        # conteo de caracteres y el pintado del límite — todo eso sigue a la noticia
        # ACTIVA (self._active_story()), sea cual sea el índice. La corrección ortográfica
        # (_hl_bajada/_hl_cuerpo) queda deliberadamente acotada a la PRINCIPAL (índice 0):
        # no es parte de "recursos por noticia" y evita rehacer el corrector por pestaña.
        panel.ed_bajada.textChanged.connect(lambda p=panel: self._on_bajada_changed(p))
        panel.ed_cuerpo.textChanged.connect(lambda p=panel: self._on_cuerpo_changed(p))
        # "Contar caracteres" en vivo: al arrastrar la selección, recalcular el conteo.
        panel.ed_cuerpo.selectionChanged.connect(lambda p=panel: self._on_frag_live_changed(p))

        if story_index == 0:
            panel.ed_bajada.setContextMenuPolicy(Qt.CustomContextMenu)
            panel.ed_bajada.customContextMenuRequested.connect(
                lambda pos, p=panel: self._show_spell_menu(p.ed_bajada, self._hl_bajada, pos)
            )
            panel.ed_cuerpo.setContextMenuPolicy(Qt.CustomContextMenu)
            panel.ed_cuerpo.customContextMenuRequested.connect(
                lambda pos, p=panel: self._show_spell_menu(p.ed_cuerpo, self._hl_cuerpo, pos)
            )
            self._arrow_overlay = _SelectionArrowOverlay(
                panel.ed_cuerpo, on_click=self._scroll_body_to_highlight
            )
            self._arrow_overlay.hide()
            panel.ed_cuerpo.verticalScrollBar().valueChanged.connect(
                lambda _: self._update_arrow_overlay()
            )
        else:
            panel.story_type_changed.connect(
                lambda t, i=story_index: self._on_story_type_changed(i, t)
            )

        return panel

    def _on_story_count_changed(self, count: int):
        while len(self._stories) < count:
            self._add_story_panel(len(self._stories))
        while len(self._stories) > count:
            self._story_tabs.removeTab(len(self._stories) - 1)
            self._stories.pop()
            self._res_cache.pop(len(self._stories), None)
        self._btn_swap.setVisible(count >= 2)
        self._apply_all_story_limits()
        self._refresh_primary_secondary_deduction()

    def _apply_all_story_limits(self):
        """Aplica los límites del config a todos los paneles de noticia. El panel
        principal (índice 0) usa los límites de la maqueta; los secundarios (breves)
        usan los límites de noticia secundaria según la maqueta resuelta (con pie /
        vacía) y un titulador de una sola línea contando sin espacios."""
        mq = self._mq
        limits = {
            "cuerpo_limit":             mq.get("cuerpo_limit", 0),
            "volanta_limit":            mq.get("volanta_limit", 90),
            "bajada_limit":             mq.get("bajada_limit", 220),
            "titulo_lineas":            mq.get("titulo_lineas", 2),
            "titulo_chars_linea":       mq.get("titulo_chars_linea", 38),
            "epigrafe_principal_limit": mq.get("epigrafe_principal_limit", 120),
        }
        # ¿La maqueta resuelta es "con pie"? (nombre normalizado empieza con "pie")
        es_pie = False
        try:
            from services.maqueta_reader_service import _normalizar
            es_pie = _normalizar(self._cb_maqueta.currentText()).startswith("pie")
        except Exception:
            pass
        cuerpo_breve = (mq.get("cuerpo_secundaria_pie_limit", 630) if es_pie
                        else mq.get("cuerpo_secundaria_vacia_limit", 1050))
        limits_breve = dict(limits)
        limits_breve.update({
            "cuerpo_limit":       cuerpo_breve,
            "titulo_lineas":      mq.get("titulo_breve_lineas", 1),
            "titulo_chars_linea": mq.get("titulo_breve_chars", 44),
            "titulo_sin_espacio": True,
        })
        # Principal con DOS noticias: usa el valor propio de la maqueta (más chico, porque la
        # 2ª noticia ocupa parte del box). Vacío → cae al cuerpo_limit normal (1 noticia).
        limits_principal = limits
        if len(self._stories) > 1:
            dobles = mq.get("cuerpo_principal_dobles_limit")
            if dobles:
                limits_principal = dict(limits)
                limits_principal["cuerpo_limit"] = dobles
        for panel in self._stories:
            es_secundaria = getattr(panel, "_story_index", 0) >= 1
            panel.apply_limits(limits_breve if es_secundaria else limits_principal)

    def _on_story_type_changed(self, story_index: int, story_type: str):
        maqueta = self._cb_maqueta.currentText()
        story_count = self._sb_noticias.value()
        config_global.save_story_type(maqueta, self._seccion, story_count, story_index, story_type)
        self._apply_all_story_limits()

    # ------------------------------------------------------------------
    # Recursos (foto/textual/dato/número/QR) por noticia
    # ------------------------------------------------------------------

    def _snapshot_recursos(self) -> dict:
        """Estado actual de los widgets de recurso COMPARTIDOS (una sola instancia para
        todas las noticias). Se cachea por índice de noticia al cambiar de pestaña/guardar."""
        return {
            "foto_tipo": self._cb_foto_tipo.currentText(),
            "textual_tipo_label": self._cb_textual_tipo.currentText(),
            "textual_state": self._textual_cards.get_state(),
            "dato_cards": [
                {"text": c._text, "edited_text": c._edited_text, "titulo": c._titulo,
                 "selected": c._is_selected}
                for c in self._dato_cards
            ],
            "numero": dict(self._numero_card.get_data(), selected=self._numero_card._is_selected),
            "qr_path": str(self._qr_path) if self._qr_path else None,
        }

    def _load_recursos(self, model: dict) -> None:
        """Puebla los widgets de recurso compartidos desde un dict de _snapshot_recursos."""
        model = model or {}
        tipo_map = {
            "simple": "simple", "x2": "x2", "x3": "x3",
            "con foto": "con_foto", "con foto XL": "con_foto_xl",
        }

        # Foto
        idx_foto = self._cb_foto_tipo.findText(model.get("foto_tipo") or "")
        self._cb_foto_tipo.blockSignals(True)
        self._cb_foto_tipo.setCurrentIndex(idx_foto if idx_foto >= 0 else 0)
        self._cb_foto_tipo.blockSignals(False)

        # Textual
        self._textual_cards.set_state(model.get("textual_state") or [])
        label = model.get("textual_tipo_label") or "—"
        idx_tx = self._cb_textual_tipo.findText(label)
        self._cb_textual_tipo.blockSignals(True)
        self._cb_textual_tipo.setCurrentIndex(idx_tx if idx_tx >= 0 else 0)
        self._cb_textual_tipo.blockSignals(False)
        self._textual_cards.set_tipo(tipo_map.get(label))

        # Dato: se reconstruyen las cards (mismo patrón que _populate_dato_cards).
        while self._dato_lay_cards.count() > 1:
            item = self._dato_lay_cards.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._dato_cards = []
        limit = self._mq.get("dato_limit", 120)
        for cd in (model.get("dato_cards") or []):
            card = _DatoCard(cd.get("text", ""), limit)
            card.set_edited_text(cd.get("edited_text") or cd.get("text", ""))
            card.set_titulo(cd.get("titulo", ""))
            card.selected.connect(lambda t, c=card: self._on_dato_card_selected(t, c))
            card.edit_requested.connect(lambda c=card: self._on_dato_card_dbl_clicked(c))
            self._dato_lay_cards.insertWidget(self._dato_lay_cards.count() - 1, card)
            self._dato_cards.append(card)
            if cd.get("selected"):
                card.set_selected(True)

        # Número
        nd = model.get("numero") or {}
        self._numero_card.set_data(nd.get("cabecera", ""), nd.get("texto", ""))
        self._numero_card.set_selected(bool(nd.get("selected")))

        # QR
        qr = model.get("qr_path")
        self._qr_path = Path(qr) if qr else None

    def _auto_detect_para(self, panel: "StoryPanel") -> None:
        """Detecta candidatos de textual/dato desde el cuerpo de `panel` y puebla los
        widgets compartidos (sin restaurar lo guardado — ver _restore_saved_fields_para)."""
        body = panel.ed_cuerpo.toPlainText()
        cands = self._detector.detect(body) if body.strip() else []
        self._textual_cards.set_candidates([c.text for c in cands])
        datos = self._detect_datos(body) if body.strip() else []
        self._populate_dato_cards(datos)

    def _restore_saved_fields_para(self, panel: "StoryPanel") -> None:
        """Restaura textual/dato/número/QR/foto_tipo del JSON de `panel` sobre los widgets
        compartidos (candidatos ya poblados por _auto_detect_para). Misma lógica que la
        vieja _restore_saved_fields, generalizada a cualquier noticia."""
        if not panel or not panel._txt_path:
            return
        json_path = panel._txt_path.with_suffix(".json")
        if not json_path.exists():
            # Noticia sin guardar todavía: el combo de foto es compartido y hereda lo
            # que quedó puesto por la pestaña anterior. Para una noticia SECUNDARIA
            # recién agregada, el default debe ser "Sin foto" (no "2 columnas").
            es_secundaria = getattr(panel, "_story_index", 0) >= 1
            if es_secundaria:
                idx = self._cb_foto_tipo.findText("Sin foto")
                if idx >= 0:
                    self._cb_foto_tipo.blockSignals(True)
                    self._cb_foto_tipo.setCurrentIndex(idx)
                    self._cb_foto_tipo.blockSignals(False)
            return
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return

        # Textual tipo y selecciones
        textual = data.get("textual")
        if textual and textual.get("tipo"):
            tipo = textual["tipo"]
            label_map = {
                "simple": "simple", "x2": "x2", "x3": "x3",
                "con_foto": "con foto", "con_foto_xl": "con foto XL",
            }
            label = label_map.get(tipo, "—")
            idx = self._cb_textual_tipo.findText(label)
            if idx >= 0:
                self._cb_textual_tipo.blockSignals(True)
                self._cb_textual_tipo.setCurrentIndex(idx)
                self._cb_textual_tipo.blockSignals(False)
                self._textual_cards.set_tipo(tipo)
            self._textual_cards.restore_saved(textual)

        # Dato: dict {titulo, texto} (nuevo) o string plano (legacy → sin título).
        dato_raw = data.get("dato")
        if isinstance(dato_raw, dict):
            dato_titulo = (dato_raw.get("titulo") or "").strip()
            dato_texto = (dato_raw.get("texto") or "").strip()
        elif isinstance(dato_raw, str):
            dato_titulo, dato_texto = "", dato_raw.strip()
        else:
            dato_titulo, dato_texto = "", ""
        if dato_texto:
            limit = self._mq.get("dato_limit", 120)
            matched = False
            for card in self._dato_cards:
                if card._text == dato_texto or card._edited_text == dato_texto:
                    card.set_edited_text(dato_texto)
                    card.set_titulo(dato_titulo)
                    card.set_selected(True)
                    for c in self._dato_cards:
                        if c is not card:
                            c.set_selected(False)
                    matched = True
                    break
            if not matched:
                card = _DatoCard(dato_texto, limit)
                card.set_edited_text(dato_texto)
                card.set_titulo(dato_titulo)
                card.selected.connect(lambda t, c=card: self._on_dato_card_selected(t, c))
                card.edit_requested.connect(lambda c=card: self._on_dato_card_dbl_clicked(c))
                self._dato_lay_cards.insertWidget(0, card)
                self._dato_cards.insert(0, card)
                card.set_selected(True)

        # Número
        numero = data.get("numero")
        if isinstance(numero, dict):
            cab = numero.get("cabecera", "") or ""
            num_txt = numero.get("texto", "") or ""
            self._numero_card.set_data(cab, num_txt)
            if cab or num_txt:
                self._numero_card.set_selected(True)

        # QR
        qr_path_str = data.get("qr_path")
        if qr_path_str:
            qr = Path(qr_path_str)
            if qr.exists():
                self._qr_path = qr
                self._fotos_browser.set_qr_path(qr)

        # Tipo de foto: default "2 columnas" para la principal, "Sin foto" para
        # secundarias (si el JSON guardado no trae foto_tipo).
        es_secundaria = getattr(panel, "_story_index", 0) >= 1
        default_foto = "Sin foto" if es_secundaria else "2 columnas"
        foto_tipo = (data.get("foto_tipo") or default_foto).strip()
        if foto_tipo == "3 columnas wide":   # legacy: renombrado a "3 columnas"
            foto_tipo = "3 columnas"
        idx = self._cb_foto_tipo.findText(foto_tipo)
        if idx >= 0:
            self._cb_foto_tipo.blockSignals(True)
            self._cb_foto_tipo.setCurrentIndex(idx)
            self._cb_foto_tipo.blockSignals(False)

    def _on_story_switch(self, new_idx: int) -> None:
        """Cambio de pestaña de noticia: cachea el estado de recursos de la saliente y
        carga (o detecta por primera vez) el de la entrante. Re-apunta el overlay de
        flecha al cuerpo de la noticia activa."""
        if new_idx < 0 or new_idx >= len(self._stories):
            return
        old_idx = self._active_res_idx
        if old_idx == new_idx and old_idx in self._res_cache:
            return
        if self._stories:
            self._res_cache[old_idx] = self._snapshot_recursos()
        self._active_res_idx = new_idx
        panel = self._active_story()

        if self._arrow_overlay is not None and panel is not None:
            self._arrow_overlay.hide()
            self._arrow_overlay.setParent(panel.ed_cuerpo)

        model = self._res_cache.get(new_idx)
        if model is None:
            # Primera vez que se visita esta noticia en esta sesión del editor: detectar
            # candidatos desde SU cuerpo y restaurar lo guardado en SU propio JSON.
            self._auto_detect_para(panel)
            self._restore_saved_fields_para(panel)
            self._res_cache[new_idx] = self._snapshot_recursos()
        else:
            self._load_recursos(model)

        # Los fragmentos ("Contar caracteres") son transitorios y no viajan entre noticias.
        self._frag_ranges = []
        self._cuerpo_snapshot = panel.ed_cuerpo.toPlainText() if panel else None
        self._refrescar_fragmentos_ui()
        self._recalcular_deduccion()
        self._on_textual_selection_changed()
        self._aplicar_extra_selections()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def closeEvent(self, e):
        self._flush_display_save()   # no perder el último ajuste de visualización
        if self._hl_bajada is not None:
            self._hl_bajada.stop()
        if self._hl_cuerpo is not None:
            self._hl_cuerpo.stop()
        super().closeEvent(e)

    # ------------------------------------------------------------------
    # SpellService diferido
    # ------------------------------------------------------------------

    def _init_spell(self):
        if not self._stories:
            return
        panel = self._stories[0]
        try:
            self._spell = SpellService()
            # Diccionario compartido en la raíz base (sync entre estaciones).
            try:
                base_root = getattr(self.controller.rutas, "base_root", None)
                if base_root:
                    self._spell.set_base_root(base_root)
                    self._spell.merge_shared()
            except Exception:
                pass
            self._hl_bajada = SpellHighlighter(
                panel.ed_bajada.document(), self._spell, "Bajada"
            )
            self._hl_cuerpo = SpellHighlighter(
                panel.ed_cuerpo.document(), self._spell, "Cuerpo"
            )
            self._hl_bajada.errors_updated.connect(
                lambda errs: self._update_spell_tab("Bajada", errs)
            )
            self._hl_cuerpo.errors_updated.connect(
                lambda errs: self._update_spell_tab("Cuerpo", errs)
            )
            self._hl_bajada.schedule_check(panel.ed_bajada.toPlainText())
            self._hl_cuerpo.schedule_check(panel.ed_cuerpo.toPlainText())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Carga de nota(s)
    # ------------------------------------------------------------------

    def _load_nota(self):
        try:
            dirs = self.controller.file_service.get_noticia_dirs(self.numero)
        except Exception:
            dirs = []

        # Intentar leer sección de la página
        try:
            pag = self.controller.gestor_paginas.obtener_pagina(self.numero)
            self._seccion = getattr(pag, "seccion", "") or ""
            self._pagina = pag
        except Exception:
            self._seccion = ""
            self._pagina = None

        # Repoblar combo con maquetas filtradas por sección/aviso
        self._cb_maqueta.blockSignals(True)
        current_maqueta = self._cb_maqueta.currentText()
        self._cb_maqueta.clear()
        try:
            from services.maqueta_reader_service import get_templates_for_page, get_templates
            filtered = (get_templates_for_page(self._pagina)
                        if self._pagina is not None else get_templates())
            self._cb_maqueta.addItems(filtered)
            idx = self._cb_maqueta.findText(current_maqueta)
            if idx >= 0:
                self._cb_maqueta.setCurrentIndex(idx)
        except Exception:
            pass
        self._cb_maqueta.blockSignals(False)

        # story_count = (mayor índice de rol presente) + 1, para dejar slots vacíos en huecos.
        # Cada carpeta cae en su slot por sufijo (02a→0/principal, 02b→1/secundaria, 02c→2…).
        if dirs:
            story_count = max(ord(d.name[-1]) - ord("a") for d in dirs) + 1
        else:
            story_count = 1
        _log.info("Editor P%02d _load_nota: dirs=%s (slots=%d)",
                  self.numero, [d.name for d in dirs], story_count)

        # Crear paneles sin disparar valueChanged todavía
        self._sb_noticias.blockSignals(True)
        self._sb_noticias.setValue(story_count)
        self._sb_noticias.blockSignals(False)
        self._on_story_count_changed(story_count)

        # Avisar si la página trae más de una noticia (tras mostrarse la ventana).
        if story_count > 1:
            QTimer.singleShot(0, lambda n=story_count: QMessageBox.information(
                self, "Noticias asignadas",
                f"Esta página tiene {n} noticias asignadas"))

        # Cargar cada carpeta en el panel = índice de su sufijo (rol)
        loaded_any = False
        for d in dirs:
            idx = ord(d.name[-1]) - ord("a")
            if 0 <= idx < len(self._stories):
                if self._stories[idx].load_from_dir(d):
                    loaded_any = True
            _log.debug("Editor P%02d: %s → panel[%d]", self.numero, d.name, idx)

        if not loaded_any:
            self._show_no_content()
            return

        # Maqueta: priorizar la RESUELTA por sección/aviso (regla determinística) sobre la
        # guardada en el JSON (que suele ser genérica). Sincroniza nota.json de paso.
        self._textuales_auto: list = []
        # Campo DEDICADO de las secciones especiales (bloque "Textuales"), separado de
        # _textuales_auto (mecanismo general de sugerencia de textuales estructurados) --
        # ver Bug 4d: no deben mezclarse.
        self._textuales_especiales: list = []
        saved_maqueta = ""
        if dirs:
            first_json = dirs[0] / f"{dirs[0].name}.json"
            if first_json.exists():
                try:
                    nota_data = json.loads(first_json.read_text(encoding="utf-8"))
                    saved_maqueta = nota_data.get("maqueta", "")
                    self._textuales_auto = nota_data.get("textuales_auto", []) or []
                    self._textuales_especiales = nota_data.get("textuales_especiales", []) or []
                except Exception:
                    pass

        try:
            resolved_maqueta = self.controller.file_service.sincronizar_maqueta_pagina(self.numero)
        except Exception:
            resolved_maqueta = None

        for cand in (resolved_maqueta, saved_maqueta):
            if not cand:
                continue
            idx = self._cb_maqueta.findText(cand)
            if idx >= 0:
                self._cb_maqueta.blockSignals(True)
                self._cb_maqueta.setCurrentIndex(idx)
                self._cb_maqueta.blockSignals(False)
                break

        # Cargar la calibración de la maqueta resuelta (hereda del global si no existe)
        maqueta_actual = self._cb_maqueta.currentText()
        if maqueta_actual:
            self._mq.update(config_global.maqueta_config_for(maqueta_actual))
            self._merge_cache_limits(maqueta_actual)
            self._apply_new_limits()

        # Fotos del primer subdirectorio
        if dirs:
            self._fotos_browser.reload(dirs[0])
            self._cargar_epigrafes_fotos(dirs[0])
            mat = self.controller.file_service.material
            if mat:
                self._fotos_browser.set_fps(
                    self.controller.foto_pagina_service,
                    self.numero,
                    dirs[0].name,
                    mat,
                )

        # Título de ventana
        if self._stories and self._stories[0]._txt_path:
            self.setWindowTitle(
                f"Editor — P{self.numero:02d} · {self._stories[0]._txt_path.stem}"
            )

        QTimer.singleShot(200, self._auto_detect)
        # Reescritura automática por IA AL ABRIR la nota (si el toggle está activo).
        # Diferida para que la ventana ya esté visible; solo sobre noticias no reescritas.
        QTimer.singleShot(350, self._ia_auto_on_load)

    def _ia_auto_on_load(self):
        try:
            from config.config import config_global as _cg
            if not _cg.ia_auto_enabled:
                return
        except Exception:
            return
        # restore_ia_state ya pobló _ia_original en las notas ya reescritas → no repetir.
        targets = [p for p in self._stories if p.has_content() and not p._ia_original]
        if targets:
            self._ia_full_rewrite(targets, auto=True)

    def _show_no_content(self):
        QMessageBox.warning(
            self, "Sin contenido",
            f"No se encontró archivo de texto para la página {self.numero}.\n"
            "Asegurate de que la nota esté correctamente asignada."
        )

    def _cargar_epigrafes_fotos(self, nota_dir: Path) -> None:
        json_path = nota_dir / f"{nota_dir.name}.json"
        if not json_path.exists():
            return
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return
        # Matchear por stem: el JSON guarda .jpeg pero en disco quedan .jpg (conversión).
        from services.foto_pagina_service import epigrafes_por_archivo_real
        epigrafes = epigrafes_por_archivo_real(nota_dir, data.get("imagenes", []))
        self._fotos_browser.set_epigrafes(epigrafes)

    def _on_usar_epigrafe(self, texto: str) -> None:
        panel = self._active_story()
        if panel is None:
            return
        panel.ed_epigrafe.setText(texto)
        panel.ed_epigrafe.setCursorPosition(0)   # leer el epígrafe desde el inicio

    # ------------------------------------------------------------------
    # Slots de campos — cuerpo/bajada de CUALQUIER noticia (cablea _add_story_panel);
    # la corrección ortográfica queda acotada a la PRINCIPAL (índice 0).
    # ------------------------------------------------------------------

    def _on_bajada_changed(self, panel: "StoryPanel" = None):
        if not self._stories:
            return
        panel = panel or self._active_story()
        if panel is self._stories[0] and self._hl_bajada is not None:
            self._hl_bajada.schedule_check(panel.ed_bajada.toPlainText())

    def _on_cuerpo_changed(self, panel: "StoryPanel" = None):
        if not self._stories:
            return
        panel = panel or self._active_story()
        if panel is not self._stories[0]:
            # El cupo de la principal depende de cuánto usan las secundarias en su
            # cuerpo — recalcular sin importar si la principal está activa ahora mismo.
            self._refresh_primary_secondary_deduction()
        txt = panel.ed_cuerpo.toPlainText()
        if panel is self._stories[0] and self._hl_cuerpo is not None:
            self._hl_cuerpo.schedule_check(txt)
        if panel is not self._active_story():
            # Cambios programáticos en una noticia no activa (p. ej. carga inicial) no
            # deben mover el conteo de caracteres/pintado de la que se está mostrando.
            return
        # Solo una edición REAL del texto reinicia los fragmentos. El interlineado
        # (apply_line_spacing → mergeBlockFormat) emite textChanged SIN cambiar el texto:
        # comparar el texto plano evita borrar los fragmentos por ese reformateo.
        prev = getattr(self, "_cuerpo_snapshot", None)
        self._cuerpo_snapshot = txt
        if prev is not None and txt != prev and getattr(self, "_frag_ranges", None):
            self._frag_ranges = []
            self._refrescar_fragmentos_ui()
            self._lbl_frag_limite.setText(
                "Las selecciones se reinician al editar el cuerpo.")
        # Refrescar el tinte "hasta el límite" (el corte se corre al editar).
        self._aplicar_extra_selections()

    # ------------------------------------------------------------------
    # Swap
    # ------------------------------------------------------------------

    def _on_swap(self):
        if len(self._stories) < 2:
            return
        data0 = self._stories[0].get_data()
        data1 = self._stories[1].get_data()
        self._stories[0].set_data(data1)
        self._stories[1].set_data(data0)

    def _on_textual_tipo_changed(self, label: str):
        tipo_map = {
            "simple": "simple", "x2": "x2", "x3": "x3",
            "con foto": "con_foto", "con foto XL": "con_foto_xl",
        }
        self._textual_cards.set_tipo(tipo_map.get(label))
        self._refrescar_alerta_textuales()

    def _on_qr_seleccionada(self, path) -> None:
        self._qr_path = path
        self._recalcular_deduccion()

    def _secondary_stories_char_usage(self) -> int:
        """Caracteres de cuerpo que usan las noticias secundarias (índice 1+) — es lo
        único que le resta a la principal: las secundarias no tienen firma/epígrafe/foto
        ni bajada propios."""
        total = 0
        for p in self._stories[1:]:
            total += len(p.ed_cuerpo.toPlainText().replace('\n', ''))
        return total

    def _refresh_primary_secondary_deduction(self) -> None:
        """Recompone el cupo de la principal (deducción por sus propios recursos +
        consumo de las secundarias) sin necesitar que la principal esté activa."""
        if not self._stories or len(self._stories) <= 1:
            return
        primary = self._stories[0]
        base = self._primary_resource_deduction
        primary.set_external_deduction(base + self._secondary_stories_char_usage())

    def _recalcular_deduccion(self) -> None:
        total = self._calc_active_resource_deduction()

        panel = self._active_story()
        if panel is not None:
            extra = total
            if panel is self._stories[0]:
                self._primary_resource_deduction = total
                if len(self._stories) > 1:
                    extra += self._secondary_stories_char_usage()
            panel.set_external_deduction(extra)
        # El límite efectivo cambió → refrescar el tinte "hasta el límite".
        self._aplicar_extra_selections()

    def _textuales_especiales_para_deduccion(self) -> list:
        """Los textuales reales de la sección especial (bloque "Textuales"), en el mismo
        campo dedicado que usa PegarNota v6.js para pegarlos en Quark (ver Bug 4d)."""
        esp = [e for e in getattr(self, "_textuales_especiales", []) if e]
        if len(esp) >= 2:
            return [esp[-2], esp[-1]]
        if len(esp) == 1:
            return [esp[0]]
        return []

    def _calc_active_resource_deduction(self) -> int:
        total = 0

        # Textual: las secciones especiales (Café) tienen su propia fórmula de deducción
        # (config por sección, no por "tipo de textual" — ver es_seccion_textual), y no
        # requieren elegir tipo en el combo.
        if self.controller.es_seccion_textual(self._seccion):
            textos_especiales = self._textuales_especiales_para_deduccion()
            if textos_especiales:
                base, umbral = self.controller.deduccion_textual_seccion(self._seccion)
                total += _calc_deduction_seccion_especial(base, umbral, textos_especiales)
        else:
            tipo_label = self._cb_textual_tipo.currentText()
            tipo_map = {
                "simple": "simple", "x2": "x2", "x3": "x3",
                "con foto": "con_foto", "con foto XL": "con_foto_xl",
            }
            tipo = tipo_map.get(tipo_label)
            if tipo:
                sel = self._textual_cards.selected_items()
                if sel:
                    textos = [item.get("text", "") for item in sel]
                    total += _calc_deduction(tipo, textos, self._mq)

        # Dato
        for card in self._dato_cards:
            if card._is_selected:
                total += _calc_dato_deduction(card._edited_text, self._mq)
                break

        # Número
        if self._numero_card._is_selected:
            nd = self._numero_card.get_data()
            total += _calc_numero_deduction(nd.get("cabecera", ""), nd.get("texto", ""), self._mq)

        # QR
        if self._qr_path:
            total += self._mq.get("qr_deduccion", 170)

        # Tipo de foto. "4 columnas" es un costo unificado (incluye el epígrafe más grande);
        # "Sin foto" BONIFICA: libera los caracteres de la foto 2 col + epígrafe.
        foto_tipo = self._cb_foto_tipo.currentText()
        if foto_tipo == "3 columnas":
            total += self._mq.get("foto_3wide_deduccion", 450)
        elif foto_tipo == "3 columnas ancha":
            total += self._mq.get("foto_3ancha_deduccion", 625)
        elif foto_tipo == "4 columnas":
            total += self._mq.get("foto_4col_deduccion", 1600)
        elif foto_tipo == "Sin foto":
            total -= self._mq.get("sin_foto_bonus", 945)
        self._aplicar_sin_foto_ui(foto_tipo == "Sin foto")

        return total

    def _aplicar_sin_foto_ui(self, sin_foto: bool):
        """'Sin foto' deshabilita el epígrafe de la noticia ACTIVA (la foto es por noticia)
        y la carga de fotos de página."""
        self._btn_agregar_foto.setEnabled(not sin_foto)
        panel = self._active_story()
        ed = getattr(panel, "ed_epigrafe", None) if panel is not None else None
        if ed is not None:
            ed.setEnabled(not sin_foto)
            ed.setToolTip("Sin foto: el epígrafe no aplica" if sin_foto else "")

    def _on_numero_edit(self):
        d = self._numero_card.get_data()
        dlg = _NumeroEditDialog(d["cabecera"], d["texto"], parent=self)
        if dlg.exec_() == dlg.Accepted:
            r = dlg.get_result()
            self._numero_card.set_data(r["cabecera"], r["texto"])
            if r["cabecera"] or r["texto"]:
                self._numero_card.set_selected(True)
            self._recalcular_deduccion()

    def _on_agregar_dato_manual(self):
        limit = self._mq.get("dato_limit", 120)
        dlg = _DatoEditDialog("", limit, parent=self)
        if dlg.exec_() == dlg.Accepted:
            r = dlg.get_result()
            if r["texto"]:
                card = _DatoCard(r["texto"], limit)
                card.set_edited_text(r["texto"])
                card.set_titulo(r["titulo"])
                card.selected.connect(lambda t, c=card: self._on_dato_card_selected(t, c))
                card.edit_requested.connect(lambda c=card: self._on_dato_card_dbl_clicked(c))
                self._dato_lay_cards.insertWidget(0, card)
                self._dato_cards.insert(0, card)
                card.set_selected(True)
                self._recalcular_deduccion()

    def _on_dato_card_dbl_clicked(self, card: "_DatoCard"):
        dlg = _DatoEditDialog(card._edited_text, self._mq.get("dato_limit", 120),
                              titulo=card._titulo, parent=self)
        if dlg.exec_() == dlg.Accepted:
            r = dlg.get_result()
            if r["texto"]:
                card.set_edited_text(r["texto"])
                card.set_titulo(r["titulo"])
                for c in self._dato_cards:
                    if c is not card:
                        c.set_selected(False)
                card.set_selected(True)
                self._recalcular_deduccion()

    # ------------------------------------------------------------------
    # Guardar
    # ------------------------------------------------------------------

    def _do_save(self) -> bool:
        fs = self.controller.file_service

        def _rol_de_indice(i: int) -> str:
            return "principal" if i == 0 else "secundaria" if i == 1 else f"noticia_{i + 1}"

        def _tiene_contenido(p) -> bool:
            return bool(p.ed_cuerpo.toPlainText().strip()
                        or p.title_grid.text().strip())

        # Paneles a guardar: con path existente, o nuevos (spinner) con contenido.
        # A los nuevos se les crea la carpeta del rol que les corresponde (02a/02b/02c…).
        panels = []
        for i, p in enumerate(self._stories):
            if p._txt_path:
                panels.append(p)
            elif _tiene_contenido(p):
                rol = _rol_de_indice(i)
                dest = fs.noticia_dir_de_rol(self.numero, rol)
                p._txt_path = dest / f"{self.numero:02d}{fs.rol_a_sufijo(rol)}.txt"
                panels.append(p)

        if not panels:
            QMessageBox.warning(self, "Error", "No hay archivo de texto cargado.")
            return False
        sel_tx = self._textual_cards.selected_items()
        es_especial = False
        try:
            es_especial = self.controller.es_seccion_textual(self._seccion)
        except Exception:
            pass
        if sel_tx and not es_especial and self._cb_textual_tipo.currentText() == "—":
            resp = QMessageBox.question(
                self, "Textual sin tipo",
                f"Hay {len(sel_tx)} textual(es) seleccionado(s) pero no elegiste tipo.\n"
                "El textual no se pegará en Quark. ¿Guardás igual?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp == QMessageBox.No:
                self._right_tabs.setCurrentWidget(self._tab_textuales)
                return False
        maqueta_sel = self._cb_maqueta.currentText()
        _log.info("Editor P%02d guardar: %s", self.numero,
                  [(_rol_de_indice(self._stories.index(p)), p._txt_path.name) for p in panels])

        # Recursos independientes por noticia: guardar el estado de la pestaña activa antes
        # de tocar los widgets compartidos, y recargar el de CADA panel antes de escribir su
        # propio JSON (si no, todos los paneles se guardarían con los recursos de la activa).
        activo_idx = self._active_res_idx
        if self._stories:
            self._res_cache[activo_idx] = self._snapshot_recursos()

        for panel in panels:
            try:
                panel.save_to_path(panel._txt_path)
                idx = self._stories.index(panel)
                self._load_recursos(self._res_cache.get(idx) or {})
                self._actualizar_nota_json(panel._txt_path, panel, maqueta_sel)
            except Exception as e:
                QMessageBox.critical(self, "Error al guardar", str(e))
                return False

        # Dejar los widgets mostrando otra vez la pestaña que el usuario tenía abierta.
        if self._stories:
            self._load_recursos(self._res_cache.get(activo_idx) or {})
            self._recalcular_deduccion()
            self._on_textual_selection_changed()

        self.nota_guardada.emit(self.numero)
        return True

    def _on_guardar(self):
        if self._do_save():
            names = ", ".join(p._txt_path.stem for p in self._stories if p._txt_path)
            QMessageBox.information(self, "Guardado", f"Nota(s) guardada(s):\n{names}")

    def _on_guardar_para_armar(self):
        if self._bloqueo_textuales():   # coercitivo: textual incompleto no se arma
            return
        if self._do_save():
            self.nota_guardada_para_armar.emit(self.numero)
            self.close()

    def _on_guardar_para_armado_bot(self):
        if self._bloqueo_textuales():   # coercitivo: textual incompleto no se arma
            return
        if self._do_save():
            self.nota_guardada_para_armado_bot.emit(self.numero)
            self.close()

    # ------------------------------------------------------------------
    # Reescritura por IA — configuración, botón "Reescribir todo", auto
    # ------------------------------------------------------------------

    def _on_configurar_ia(self):
        from ui.ia_config_dialog import IAConfigDialog
        dlg = IAConfigDialog(self)
        if dlg.exec_():
            try:
                from config.config import config_global as _cg
                self._act_ia_auto.blockSignals(True)
                self._act_ia_auto.setChecked(_cg.ia_auto_enabled)
                self._act_ia_auto.blockSignals(False)
            except Exception:
                pass

    def _on_toggle_ia_auto(self, checked: bool):
        try:
            from config.config import config_global as _cg
            _cg.save_ia_auto_enabled(bool(checked))
        except Exception as e:
            _log.warning("[EDITOR] no se pudo guardar ia_auto_enabled: %s", e)

    def _on_ia_busy_changed(self, busy: bool):
        try:
            self._btn_ia_todo.setEnabled(not busy)
        except Exception:
            pass

    def _on_reescribir_todo(self):
        """Reescribe con IA la noticia activa (pestaña actual)."""
        panel = self._story_tabs.currentWidget()
        if panel is None:
            return
        if not panel.has_content():
            QMessageBox.information(self, "IA", "La noticia no tiene contenido para reescribir.")
            return
        self._ia_full_rewrite([panel], auto=False)

    def _ia_full_rewrite(self, panels: list, auto: bool = False) -> bool:
        """Reescribe la nota completa de cada panel con contenido, con diálogo de
        progreso cancelable. Corre la llamada en un worker (no congela la UI).
        Preserva el original y resalta el diff (lo hace StoryPanel.apply_ia_full)."""
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import QEventLoop
        try:
            from services.ia_service import AIRewriter
            rewriter = AIRewriter()
        except Exception as e:
            if not auto:
                self._on_ia_config_error_dialog(e)
            else:
                _log.warning("[EDITOR] IA auto: sin API key (%s)", e)
            return False

        targets = [p for p in panels if p.has_content()]
        if not targets:
            return True

        from ui.ia_worker import IAWorker
        dlg = QProgressDialog("Reescribiendo con IA…", "Cancelar", 0, len(targets), self)
        dlg.setWindowTitle("IA")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        estado = {"cancel": False}
        dlg.canceled.connect(lambda: estado.__setitem__("cancel", True))

        for i, panel in enumerate(targets):
            if estado["cancel"]:
                break
            dlg.setValue(i)
            datos, limites = panel.ia_datos_y_limites()
            if not datos:
                continue
            caja: dict = {}
            loop = QEventLoop()
            worker = IAWorker(rewriter.reescribir_nota_completa, datos, limites, parent=self)
            worker.done.connect(lambda r, b=caja, lp=loop: (b.update({"r": r}), lp.quit()))
            worker.failed.connect(lambda m, b=caja, lp=loop: (b.update({"e": m}), lp.quit()))
            worker.start()
            loop.exec_()
            if "r" in caja and isinstance(caja["r"], dict):
                panel.apply_ia_full(caja["r"])
            elif "e" in caja and not auto:
                QMessageBox.warning(self, "Error IA", caja["e"])
        dlg.setValue(len(targets))
        return True

    def _on_ia_config_error_dialog(self, err: Exception):
        resp = QMessageBox.question(
            self, "IA no configurada",
            f"{err}\n\n¿Querés configurar la API key de OpenAI ahora?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if resp == QMessageBox.Yes:
            self._on_configurar_ia()

    def _actualizar_nota_json(self, txt_path: Path, panel: "StoryPanel", maqueta: str):
        """Actualiza el JSON de la nota con los campos del editor y la maqueta seleccionada."""
        json_path = txt_path.with_suffix(".json")
        data: dict = {}
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        # Título desde el texto plano: los cortes por columna NO son caracteres en el texto
        # (van pegados), y solo los saltos reales (Enter) separan con espacio. Así un corte
        # mid-word ("ejempl|o") no inyecta un espacio ("ejempl o").
        titulo = " ".join(seg.strip() for seg in panel.title_grid.text().split("\n") if seg.strip())

        # Textual
        tipo_label = self._cb_textual_tipo.currentText()
        tipo_map = {
            "simple": "simple", "x2": "x2", "x3": "x3",
            "con foto": "con_foto", "con foto XL": "con_foto_xl",
        }
        tipo = tipo_map.get(tipo_label)
        textual = None
        if tipo:
            # Solo slots con texto real: un tipo elegido SIN textuales seleccionados NO se
            # propaga (el script pegaría "" y dejaría los boxes de Quark editados y EN BLANCO
            # — bug reportado). Ver también la alerta bloqueante en _estado_alerta_textuales.
            selected = [it for it in self._textual_cards.selected_items()
                        if (it.get("text") or "").strip()]
            if selected:
                textual = {"tipo": tipo}
                for i, item in enumerate(selected[:3], 1):
                    textual[f"texto{i}"] = item.get("text", "")
                    textual[f"nombre{i}"] = item.get("orador_nombre", "")
                    raw_cargo = item.get("orador_cargo", "").strip()
                    textual[f"cargo{i}"] = (" " + raw_cargo) if raw_cargo else ""
                if tipo in ("con_foto", "con_foto_xl"):
                    foto_info = selected[0].get("foto") or {}
                    foto_src = foto_info.get("path", "")
                    textual["foto"] = self._copy_foto_textual(foto_src, txt_path) if foto_src else None
                else:
                    textual["foto"] = None
            else:
                _log.warning("[EDITOR] P%02d: tipo de textual '%s' sin textuales seleccionados"
                             " → no se propaga al JSON.", self.numero, tipo)

        # Dato: {titulo, texto} (título → Box1125, texto → Box1126). Solo si hay texto.
        dato = None
        for c in self._dato_cards:
            if c._is_selected:
                nd = c.get_data()
                if nd["texto"]:
                    dato = {"titulo": nd["titulo"], "texto": nd["texto"]}
                break

        # Número
        numero = None
        if self._numero_card._is_selected:
            nd = self._numero_card.get_data()
            if nd["cabecera"] or nd["texto"]:
                numero = nd

        _si = getattr(panel, "_story_index", 0)
        rol = "principal" if _si == 0 else "secundaria" if _si == 1 else f"noticia_{_si + 1}"
        data.update({
            "tipo": rol,
            "rol": rol,
            "volanta": panel.ed_volanta.toPlainText().strip(),
            "titulo": titulo,
            "bajada": panel.ed_bajada.toPlainText().strip(),
            "firma": panel.ed_firma.text().strip(),
            "firma_habilitada": panel.chk_firma.isChecked(),
            "epigrafe": panel.ed_epigrafe.text().strip(),
            "cuerpo": panel.ed_cuerpo.toPlainText().strip(),
            "maqueta": maqueta,
            "fecha_modificacion": datetime.now().isoformat(),
            "textual": textual,
            "dato": dato,
            "numero": numero,
            "qr_path": str(self._qr_path) if self._qr_path else None,
            "foto_tipo": self._cb_foto_tipo.currentText(),
            # Texto original previo a la reescritura por IA (para deshacer/resaltar al reabrir)
            "ia_original": dict(getattr(panel, "_ia_original", {}) or {}),
            # Marca de nota editada por el usuario: el chrome_watcher NO debe sobrescribir
            # una nota con editado=true (si no, se perdería la config al re-bajar/re-empujar).
            "editado": True,
        })
        try:
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            _log.warning(f"[EDITOR] WARNING: no se pudo actualizar JSON {json_path.name}: {e}")

    def _on_agregar_foto(self):
        """Copia una o más imágenes del disco a la carpeta de materiales de la
        página (materiales/Pnn) y refresca el visor de fotos."""
        from PyQt5.QtWidgets import QFileDialog
        import shutil

        # Destino: la carpeta que muestra el visor (subcarpeta bajo materiales/Pnn)
        # o, si no hay, la raíz materiales/Pnn de la página.
        dest_dir = None
        d = getattr(self._fotos_browser, "_dir", None)
        if d and Path(d).is_absolute() and Path(d).exists():
            dest_dir = Path(d)
        else:
            mat = self.controller.file_service.material
            if mat:
                dest_dir = Path(mat) / f"P{self.numero:02d}"
        if dest_dir is None:
            QMessageBox.warning(self, "Sin carpeta",
                                "No hay carpeta de materiales para esta página.")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Agregar foto a la página", str(dest_dir),
            "Imágenes (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp)")
        if not paths:
            return

        dest_dir.mkdir(parents=True, exist_ok=True)
        copiadas = 0
        for p in paths:
            src = Path(p)
            try:
                dest = dest_dir / src.name
                i = 1
                while dest.exists():     # no pisar: sufijo incremental
                    dest = dest_dir / f"{src.stem}_{i}{src.suffix}"
                    i += 1
                shutil.copy2(str(src), str(dest))
                copiadas += 1
            except Exception as e:
                _log.warning("No se pudo copiar foto %s: %s", src, e)
        if copiadas:
            self._fotos_browser.reload(dest_dir)

    def _copy_foto_textual(self, src_path: str, txt_path: Path) -> str | None:
        import shutil
        src = Path(src_path)
        if not src.exists():
            return None
        dest_name = f"fototextual_{self.numero}{src.suffix.lower()}"
        dest = txt_path.parent / dest_name
        try:
            shutil.copy2(str(src), str(dest))
            return str(dest)
        except Exception as e:
            _log.warning(f"[EDITOR] WARNING: no se pudo copiar foto textual: {e}")
            return None

    # ------------------------------------------------------------------
    # Detección de textuales y datos
    # ------------------------------------------------------------------

    def _auto_detect(self):
        """Carga inicial: detecta y restaura recursos para TODAS las noticias de la página
        (cada una contra su propio JSON), cachea el resultado por índice y deja los widgets
        mostrando la PRINCIPAL (índice 0) — recursos independientes por noticia."""
        if not self._stories:
            return
        for idx, panel in enumerate(self._stories):
            self._active_res_idx = idx
            self._auto_detect_para(panel)
            if idx == 0:
                textuales_auto = getattr(self, "_textuales_auto", [])
                if textuales_auto:
                    self._textual_cards.add_preselected(textuales_auto)
            self._restore_saved_fields_para(panel)
            # Fijar la deducción de ESTE panel ahora (no solo cuando el usuario lo visite),
            # así limite_efectivo_cuerpo() es correcto desde la carga para todas las noticias.
            self._recalcular_deduccion()
            self._res_cache[idx] = self._snapshot_recursos()
        self._active_res_idx = 0
        self._load_recursos(self._res_cache[0])
        self._recalcular_deduccion()

    def _populate_dato_cards(self, datos: list[str]):
        while self._dato_lay_cards.count() > 1:
            item = self._dato_lay_cards.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._dato_cards = []
        limit = self._mq.get("dato_limit", 120)
        for txt in datos[:6]:
            card = _DatoCard(txt, limit)
            card.selected.connect(lambda t, c=card: self._on_dato_card_selected(t, c))
            card.edit_requested.connect(lambda c=card: self._on_dato_card_dbl_clicked(c))
            self._dato_lay_cards.insertWidget(self._dato_lay_cards.count() - 1, card)
            self._dato_cards.append(card)

    def _on_dato_card_selected(self, text: str, card: _DatoCard):
        for c in self._dato_cards:
            if c is not card:
                c.set_selected(False)
        self._recalcular_deduccion()
        self._highlight_body_text(text if card._is_selected else "", source="dato")

    # ------------------------------------------------------------------
    # Resaltado en cuerpo y overlay de flecha
    # ------------------------------------------------------------------

    # Normalización 1:1 (misma longitud) para tolerar comillas tipográficas y el separador
    # de párrafo de QTextEdit: los índices del match siguen valiendo sobre el texto original.
    _TRANS_HIGHLIGHT = str.maketrans({
        "“": '"', "”": '"', "«": '"', "»": '"',
        "‘": "'", "’": "'",
        " ": "\n",
    })

    def _buscar_en_cuerpo(self, body: str, text: str) -> int:
        """find exacto; si falla, reintenta con ambos strings normalizados (comillas/saltos,
        sustituciones 1:1 → el índice devuelto es válido sobre `body` original)."""
        idx = body.find(text)
        if idx >= 0:
            return idx
        return body.translate(self._TRANS_HIGHLIGHT).find(text.translate(self._TRANS_HIGHLIGHT))

    def _highlight_body_text(self, text: str, source: str = ""):
        self._highlight_body_texts([text] if text else [], source)

    def _highlight_body_texts(self, texts: list, source: str = ""):
        """Resalta en el cuerpo TODOS los textos hallados (celeste). La flecha del overlay
        apunta al primero. Los fallos de búsqueda son tolerantes a comillas tipográficas."""
        self._body_highlight_range = None
        self._highlight_source = source
        if not self._stories:
            return
        editor = self._active_story().ed_cuerpo
        body = editor.toPlainText()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(100, 180, 255, 55))
        fmt.setProperty(QTextCharFormat.OutlinePen, QColor(100, 180, 255, 200))
        from PyQt5.QtWidgets import QTextEdit
        selections = []
        for text in texts:
            if not text:
                continue
            idx = self._buscar_en_cuerpo(body, text)
            if idx < 0:
                continue
            if self._body_highlight_range is None:
                self._body_highlight_range = (idx, idx + len(text))
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            c = QTextCursor(editor.document())
            c.setPosition(idx)
            c.setPosition(idx + len(text), QTextCursor.KeepAnchor)
            sel.cursor = c
            selections.append(sel)
        self._resource_extra_sels = selections
        self._aplicar_extra_selections()   # compone con el resaltado naranja de fragmentos
        self._update_arrow_overlay()

    def _update_arrow_overlay(self):
        if not self._arrow_overlay or not self._stories:
            return
        editor = self._active_story().ed_cuerpo
        if not self._body_highlight_range:
            self._arrow_overlay.hide()
            return
        # Only show when the corresponding tab is active
        _source_tab = {
            "textual": self._tab_textuales,
            "dato":    self._tab_dato,
            "numero":  self._tab_numero,
        }
        expected_tab = _source_tab.get(self._highlight_source)
        if expected_tab and self._right_tabs.currentWidget() is not expected_tab:
            self._arrow_overlay.hide()
            return
        _source_label = {"textual": "Aa", "dato": "D", "numero": "Nº"}
        self._arrow_overlay.label = _source_label.get(self._highlight_source, "")
        start = self._body_highlight_range[0]
        doc = editor.document()
        block = doc.findBlock(start)
        if not block.isValid():
            self._arrow_overlay.hide()
            return
        try:
            # cursorRect funciona en QTextEdit (blockBoundingGeometry es solo de QPlainTextEdit).
            cur = QTextCursor(doc)
            cur.setPosition(start)
            crect = editor.cursorRect(cur)
        except Exception:
            self._arrow_overlay.hide()
            return
        viewport_h = editor.viewport().rect().height()
        top_y = crect.top()
        bottom_y = crect.bottom()
        if bottom_y < 0:
            self._arrow_overlay.direction = "up"
            self._arrow_overlay._reposition()
            self._arrow_overlay.show()
            self._arrow_overlay.raise_()
        elif top_y > viewport_h:
            self._arrow_overlay.direction = "down"
            self._arrow_overlay._reposition()
            self._arrow_overlay.show()
            self._arrow_overlay.raise_()
        else:
            self._arrow_overlay.hide()

    def _scroll_body_to_highlight(self):
        if not self._body_highlight_range or not self._stories:
            return
        editor = self._active_story().ed_cuerpo
        c = QTextCursor(editor.document())
        c.setPosition(self._body_highlight_range[0])
        editor.setTextCursor(c)
        editor.ensureCursorVisible()

    def _on_textual_selection_changed(self):
        sel = self._textual_cards.selected_items()
        self._highlight_body_texts([c.get("text", "") for c in sel], source="textual")
        self._refrescar_alerta_textuales()

    # ------------------------------------------------------------------
    # Alerta de la pestaña Textuales (ícono + borde naranja + tooltip + shake)
    # ------------------------------------------------------------------

    def _idx_tab_textuales(self) -> int:
        return self._right_tabs.indexOf(self._tab_textuales)

    def _estado_alerta_textuales(self):
        """None si está todo completo; si no, ('bloqueante'|'aviso', mensaje).
        Los bloqueantes impiden 'Guardar para armar' y 'armado automático' (no el guardado)."""
        # Secciones especiales (Café): los textuales van por la vía dedicada (bloque "Textuales"),
        # no por el textual estructurado con tipo/orador → sin advertencia ni bloqueo.
        try:
            if self.controller.es_seccion_textual(self._seccion):
                return None
        except Exception:
            pass
        sel = self._textual_cards.selected_items()
        label = self._cb_textual_tipo.currentText()
        if not sel:
            # Espejo del caso "seleccionados sin tipo": un tipo elegido SIN textuales no se
            # propaga al pegado (quedarían boxes en blanco) → alertar y bloquear el armado.
            if label != "—":
                return ("bloqueante", "Selecciona los textuales para el tipo elegido")
            return None
        if label == "—":
            return ("bloqueante", "Selecciona el tipo de textual")
        if any(not (c.get("orador_nombre") or "").strip()
               or not (c.get("orador_cargo") or "").strip() for c in sel):
            return ("bloqueante", "Selecciona nombre y cargo del textual")
        tipo = {"simple": "simple", "x2": "x2",
                "con foto": "con_foto", "con foto XL": "con_foto_xl"}.get(label)
        if tipo in ("con_foto", "con_foto_xl"):
            foto = sel[0].get("foto") or {}
            if not (foto.get("path") or "").strip():
                return ("aviso", "Selecciona una foto para el textual")
        return None

    def _refrescar_alerta_textuales(self):
        est = self._estado_alerta_textuales()
        bar = self._right_tabs.alert_bar
        idx = self._idx_tab_textuales()
        if est:
            icono = str(Path(__file__).parent / "assets" / "alerta.png")
            bar.set_alert(idx, est[1], icono)
        else:
            bar.set_alert(idx, None)

    def _on_right_tab_changed(self, nuevo: int):
        self._update_arrow_overlay()
        idx = self._idx_tab_textuales()
        if nuevo != idx and self._right_tabs.alert_bar.has_alert(idx):
            self._right_tabs.alert_bar.shake(idx)
        # Al entrar a "Contar caracteres", refrescar conteos (el límite pudo cambiar).
        if self._right_tabs.widget(nuevo) is getattr(self, "_tab_fragmentos", None):
            self._actualizar_conteo_fragmentos()
            self._aplicar_extra_selections()

    def _bloqueo_textuales(self) -> bool:
        """True si hay alerta bloqueante: enfoca la pestaña, sacude y avisa."""
        est = self._estado_alerta_textuales()
        if est and est[0] == "bloqueante":
            idx = self._idx_tab_textuales()
            self._refrescar_alerta_textuales()
            self._right_tabs.setCurrentIndex(idx)
            self._right_tabs.alert_bar.shake(idx)
            QMessageBox.warning(self, "Textuales", est[1])
            return True
        return False

    def _on_numero_card_toggled(self):
        if self._numero_card._is_selected:
            data = self._numero_card.get_data()
            text = data.get("texto", "") or data.get("cabecera", "")
            self._highlight_body_text(text, source="numero")
        else:
            self._highlight_body_text("", source="numero")

    # ------------------------------------------------------------------
    # Selección manual de textual desde el cuerpo
    # ------------------------------------------------------------------

    def eventFilter(self, obj, ev):
        """Colapso tipo app-bar: rueda abajo oculta volanta/título/bajada/firma/epígrafe
        (el cuerpo llena el panel); rueda arriba con el scroll en tope debe VENCER una
        resistencia (~3 muescas acumuladas) para volver a mostrarlos."""
        if ev.type() == QEvent.Wheel and self._stories:
            panel = self._story_tabs.currentWidget()
            if isinstance(panel, StoryPanel):
                dy = ev.angleDelta().y()
                if dy < 0:
                    # Rueda abajo: colapsar el bloque superior (el epígrafe queda fuera
                    # del colapso, así que sigue visible junto al cuerpo).
                    if not panel.upper_collapsed():
                        panel.set_upper_collapsed(True)
                    self._resist_acc = 0
                elif dy > 0 and panel.upper_collapsed():
                    sb = (self._left_scroll.verticalScrollBar()
                          if obj is self._left_scroll.viewport()
                          else panel.ed_cuerpo.verticalScrollBar())
                    if sb.value() <= 0:
                        self._resist_acc += dy
                        if self._resist_acc >= 360:
                            panel.set_upper_collapsed(False)
                            self._resist_acc = 0
                    else:
                        self._resist_acc = 0
        return super().eventFilter(obj, ev)

    def _crear_sel_manual_ui(self, lay, mode: str, toggle_text: str = "Selección manual en texto",
                             ok_text: str = "Aceptar", cancel_text: str = "Cancelar"):
        """Botón toggle + fila Aceptar/Cancelar (mismo patrón que Textuales) para las
        pestañas Dato, Número y Contar caracteres. Devuelve (btn_toggle, row)."""
        btn = QPushButton(toggle_text)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        lay.addWidget(btn)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        ok = QPushButton(ok_text)
        ko = QPushButton(cancel_text)
        ok.setCursor(Qt.PointingHandCursor)
        ko.setCursor(Qt.PointingHandCursor)
        ok.setStyleSheet(
            "QPushButton { background: rgba(90,188,138,0.20); color: #5abc8a;"
            " border: 1px solid rgba(90,188,138,0.5); border-radius: 6px; padding: 4px 10px; }"
            " QPushButton:hover { background: rgba(90,188,138,0.35); }"
        )
        ko.setStyleSheet(
            "QPushButton { background: rgba(230,120,60,0.18); color: #e87844;"
            " border: 1px solid rgba(230,120,60,0.4); border-radius: 6px; padding: 4px 10px; }"
            " QPushButton:hover { background: rgba(230,120,60,0.30); }"
        )
        rl.addWidget(ok)
        rl.addWidget(ko)
        row.setVisible(False)
        lay.addWidget(row)
        btn.toggled.connect(lambda on, m=mode: self._on_sel_mode_toggled(m, on))
        ok.clicked.connect(lambda _=False, m=mode: self._on_sel_mode_accept(m))
        ko.clicked.connect(lambda _=False, m=mode: self._on_sel_mode_cancel(m))
        return btn, row

    def _sel_manual_ctrl(self) -> dict:
        """mode -> (botón toggle, fila aceptar/cancelar) de los 4 modos de selección manual."""
        return {
            "textual": (self._btn_sel_textual, self._sel_textual_row),
            "dato": (self._btn_sel_dato, self._sel_dato_row),
            "numero": (self._btn_sel_numero, self._sel_numero_row),
            "fragmento": (self._btn_sel_frag, self._sel_frag_row),
        }

    def _on_sel_mode_toggled(self, mode: str, on: bool):
        _btn, row = self._sel_manual_ctrl()[mode]
        row.setVisible(on)
        if on:
            # Los tres modos son mutuamente excluyentes.
            for m, (b, r) in self._sel_manual_ctrl().items():
                if m != mode and b.isChecked():
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
                    r.setVisible(False)
        activo = any(b.isChecked() for b, _ in self._sel_manual_ctrl().values())
        self._aplicar_borde_seleccion(activo)

    def _aplicar_borde_seleccion(self, on: bool):
        if not self._stories:
            return
        panel = self._active_story()
        if on:
            # Mantener el tema de lectura y solo cambiar el borde a azul de selección.
            import re as _re
            from ui.widgets.body_display import body_qss
            styled = _re.sub(
                r"border: 2px solid [^;]+;",
                "border: 2px solid rgba(100,180,255,0.9);",
                body_qss(panel._body_display),
            )
            panel.ed_cuerpo.setStyleSheet(styled)
        else:
            # Restaurar el tema de lectura del cuerpo (no vaciar el stylesheet).
            panel._refresh_cuerpo_style(getattr(panel.cnt_cuerpo, "state", None))

    def _on_sel_mode_accept(self, mode: str):
        if not self._stories:
            return
        _editor_sel = self._active_story().ed_cuerpo
        cursor = _editor_sel.textCursor()
        text = cursor.selectedText().strip()
        text = text.replace("\u2029", "\n")   # separador de párrafo de QTextEdit
        btn, _row = self._sel_manual_ctrl()[mode]
        if mode == "fragmento":
            # Acumulativo: agrega el rango y MANTIENE el modo activo para seguir sumando.
            if cursor.hasSelection():
                self._agregar_fragmento(cursor.selectionStart(), cursor.selectionEnd())
                cursor.clearSelection()
                _editor_sel.setTextCursor(cursor)
            return
        if text:
            if mode == "textual":
                self._textual_cards.add_preselected([text])
            elif mode == "dato":
                self._agregar_dato_desde_texto(text)
            else:
                self._agregar_numero_desde_texto(text)
        btn.setChecked(False)

    def _on_sel_mode_cancel(self, mode: str):
        if self._stories:
            editor = self._active_story().ed_cuerpo
            c = editor.textCursor()
            c.clearSelection()
            editor.setTextCursor(c)
        btn, _row = self._sel_manual_ctrl()[mode]
        btn.setChecked(False)

    def _agregar_dato_desde_texto(self, text: str):
        """Crea una card de Dato ya seleccionada con el texto elegido del cuerpo."""
        limit = self._mq.get("dato_limit", 120)
        card = _DatoCard(text, limit)
        card.set_edited_text(text)
        card.selected.connect(lambda t, c=card: self._on_dato_card_selected(t, c))
        card.edit_requested.connect(lambda c=card: self._on_dato_card_dbl_clicked(c))
        self._dato_lay_cards.insertWidget(0, card)
        self._dato_cards.insert(0, card)
        card.set_selected(True)
        self._on_dato_card_selected(text, card)   # deselecciona otras + recalcula + resalta

    def _agregar_numero_desde_texto(self, text: str):
        """Abre el diálogo de Número con el texto elegido precargado (falta la cabecera)."""
        d = self._numero_card.get_data()
        dlg = _NumeroEditDialog(d["cabecera"], text, parent=self)
        if dlg.exec_() == dlg.Accepted:
            r = dlg.get_result()
            self._numero_card.set_data(r["cabecera"], r["texto"])
            if r["cabecera"] or r["texto"]:
                self._numero_card.set_selected(True)
                self._on_numero_card_toggled()
            self._recalcular_deduccion()

    # ------------------------------------------------------------------
    # Contar caracteres: fragmentos acumulativos del cuerpo
    # ------------------------------------------------------------------

    @staticmethod
    def _fusionar_rangos(ranges: list) -> list:
        """Fusiona rangos (start, end) solapados o adyacentes — no se cuenta dos veces."""
        out: list = []
        for s, e in sorted(ranges):
            if out and s <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], e))
            else:
                out.append((s, e))
        return out

    @staticmethod
    def _contar_chars(texto: str) -> int:
        """Criterio del contador del cuerpo: caracteres CON espacios, sin saltos de línea."""
        return len(texto.replace("\u2029", "").replace("\n", "").strip())

    def _frag_rangos_efectivos(self) -> list:
        """Fragmentos acumulados + la selección viva actual del cuerpo (para el conteo en vivo)."""
        rangos = list(self._frag_ranges)
        if self._stories:
            cur = self._active_story().ed_cuerpo.textCursor()
            if cur.hasSelection():
                rangos = rangos + [(cur.selectionStart(), cur.selectionEnd())]
        return self._fusionar_rangos(rangos)

    def _on_frag_live_changed(self, panel: "StoryPanel" = None):
        """Conteo en vivo mientras se arrastra la selección: solo activo en la pestaña
        'Contar caracteres' Y en el cuerpo de la noticia ACTIVA (los fragmentos acumulados +
        la selección actual se cuentan juntos)."""
        if not self._stories:
            return
        if panel is not None and panel is not self._active_story():
            return
        if self._right_tabs.widget(self._right_tabs.currentIndex()) is not getattr(
                self, "_tab_fragmentos", None):
            return
        self._actualizar_conteo_fragmentos()

    def _agregar_fragmento(self, start: int, end: int):
        if end <= start:
            return
        self._frag_ranges = self._fusionar_rangos(self._frag_ranges + [(start, end)])
        self._refrescar_fragmentos_ui()

    def _on_frag_quitar(self, idx: int):
        if 0 <= idx < len(self._frag_ranges):
            del self._frag_ranges[idx]
            self._refrescar_fragmentos_ui()

    def _on_frag_limpiar(self):
        if self._frag_ranges:
            self._frag_ranges = []
            self._refrescar_fragmentos_ui()

    def _refrescar_fragmentos_ui(self):
        """Reconstruye las cards de fragmentos, los contadores y el resaltado naranja."""
        # Cards
        while self._frag_lay.count() > 1:
            item = self._frag_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        body = self._active_story().ed_cuerpo.toPlainText() if self._stories else ""
        for i, (s, e) in enumerate(self._frag_ranges):
            frag = body[s:e]
            preview = frag.strip().replace("\u2029", " ").replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "…"
            fila = QWidget()
            fl = QHBoxLayout(fila)
            fl.setContentsMargins(4, 2, 4, 2)
            lbl = QLabel(f"{self._contar_chars(frag)} — {preview}")
            lbl.setStyleSheet("color: rgba(255,255,255,0.75); font-size: 11px;")
            lbl.setWordWrap(True)
            fl.addWidget(lbl, 1)
            btn_x = QPushButton("✕")
            btn_x.setFixedSize(20, 20)
            btn_x.setCursor(Qt.PointingHandCursor)
            btn_x.setStyleSheet(
                "QPushButton { background: rgba(230,120,60,0.18); color: #e87844;"
                " border: 1px solid rgba(230,120,60,0.4); border-radius: 4px; font-size: 10px; }"
                " QPushButton:hover { background: rgba(230,120,60,0.35); }")
            btn_x.clicked.connect(lambda _=False, i=i: self._on_frag_quitar(i))
            fl.addWidget(btn_x)
            self._frag_lay.insertWidget(self._frag_lay.count() - 1, fila)

        self._actualizar_conteo_fragmentos()
        self._aplicar_extra_selections()

    def _actualizar_conteo_fragmentos(self):
        """(a) chars de la selección, (b) chars de lo no seleccionado, (c) vs límite maqueta."""
        if not self._stories:
            return
        panel = self._active_story()
        body = panel.ed_cuerpo.toPlainText()
        total = self._contar_chars(body)
        seleccionado = sum(self._contar_chars(body[s:e]) for s, e in self._frag_rangos_efectivos())
        no_seleccionado = max(0, total - seleccionado)
        limite = panel.limite_efectivo_cuerpo()

        def _pintar(lbl, texto, n):
            if limite > 0:
                color = "#5abc8a" if n <= limite else "#ff6b6b"
            else:
                color = "#e2e8f0"
            lbl.setText(texto)
            lbl.setStyleSheet(f"font-size: 13px; color: {color};")

        _pintar(self._lbl_frag_sel, f"Seleccionado: {seleccionado}", seleccionado)
        _pintar(self._lbl_frag_no_sel, f"No seleccionado: {no_seleccionado}", no_seleccionado)
        self._lbl_frag_limite.setText(
            f"Límite maqueta: {limite}" if limite > 0 else "Límite maqueta: sin límite")
        self._lbl_frag_limite.setStyleSheet("font-size: 13px; color: #e2e8f0;")

    def _frag_extra_selections(self, editor):
        """ExtraSelections NARANJAS de los fragmentos acumulados."""
        from PyQt5.QtWidgets import QTextEdit
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(235, 140, 60, 70))
        fmt.setProperty(QTextCharFormat.OutlinePen, QColor(235, 140, 60, 200))
        sels = []
        for s, e in self._frag_ranges:
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            c = QTextCursor(editor.document())
            c.setPosition(s)
            c.setPosition(e, QTextCursor.KeepAnchor)
            sel.cursor = c
            sels.append(sel)
        return sels

    @staticmethod
    def _pos_para_limite_cce(body: str, limite: int) -> int:
        """Índice de documento donde el conteo cce (con espacios, sin saltos, sin whitespace
        inicial — criterio de _contar_chars) alcanza `limite`. Devuelve len(body) si no llega."""
        count = 0
        started = False
        for i, ch in enumerate(body):
            if ch in ("\n", " "):
                continue
            if not started:
                if ch.isspace():
                    continue
                started = True
            count += 1
            if count >= limite:
                return i + 1
        return len(body)

    def _limit_paint_extra_selections(self, panel):
        """Tinte del cuerpo: verde tenue desde el inicio hasta el punto de corte del límite cce
        de la maqueta, y rojo tenue el excedente. Activado por el checkbox 'Pintar hasta el límite'."""
        if not getattr(self, "_chk_pintar_limite", None) or not self._chk_pintar_limite.isChecked():
            return []
        limite = panel.limite_efectivo_cuerpo()
        if limite <= 0:
            return []
        from PyQt5.QtWidgets import QTextEdit
        editor = panel.ed_cuerpo
        body = editor.toPlainText()
        pos = self._pos_para_limite_cce(body, limite)
        sels = []
        fmt_ok = QTextCharFormat()
        fmt_ok.setBackground(QColor(90, 188, 138, 45))
        c = QTextCursor(editor.document())
        c.setPosition(0)
        c.setPosition(pos, QTextCursor.KeepAnchor)
        s = QTextEdit.ExtraSelection()
        s.format = fmt_ok
        s.cursor = c
        sels.append(s)
        if pos < len(body):
            fmt_over = QTextCharFormat()
            fmt_over.setBackground(QColor(255, 107, 107, 55))
            c2 = QTextCursor(editor.document())
            c2.setPosition(pos)
            c2.setPosition(len(body), QTextCursor.KeepAnchor)
            s2 = QTextEdit.ExtraSelection()
            s2.format = fmt_over
            s2.cursor = c2
            sels.append(s2)
        return sels

    def _aplicar_extra_selections(self):
        """Compone: tinte de límite (fondo) + highlight celeste de recursos + naranja de fragmentos."""
        if not self._stories:
            return
        panel = self._active_story()
        editor = panel.ed_cuerpo
        recursos = list(getattr(self, "_resource_extra_sels", []) or [])
        editor.setExtraSelections(
            self._limit_paint_extra_selections(panel) + recursos + self._frag_extra_selections(editor))

    # ------------------------------------------------------------------
    # Corrección: acciones globales
    # ------------------------------------------------------------------

    def _on_add_all_to_dict(self):
        words = {e["word"] for errs in self._spell_errors_by_field.values()
                 for e in errs if e.get("type") == "spell"}
        if not words:
            return
        hls = [hl for hl in (self._hl_bajada, self._hl_cuerpo) if hl]
        _ToastNotification(self.centralWidget(), f"Agregando {len(words)} palabra(s) al diccionario…")
        self._spell_bulk_worker = _SpellBulkWorker(hls, words, "add")
        self._spell_bulk_worker.finished.connect(lambda: self._on_bulk_done(hls))
        self._spell_bulk_worker.start()

    def _on_ignore_all(self):
        words = {e["word"] for errs in self._spell_errors_by_field.values()
                 for e in errs}
        if not words:
            return
        hls = [hl for hl in (self._hl_bajada, self._hl_cuerpo) if hl]
        _ToastNotification(self.centralWidget(), f"Omitiendo {len(words)} palabra(s)…")
        self._spell_bulk_worker = _SpellBulkWorker(hls, words, "ignore")
        self._spell_bulk_worker.finished.connect(lambda: self._on_bulk_done(hls))
        self._spell_bulk_worker.start()

    def _on_bulk_done(self, hls):
        for hl in hls:
            hl.rehighlight()
            hl.errors_updated.emit(hl._errors)

    def _detect_datos(self, text: str) -> list[str]:
        import re
        min_len = 20
        max_len = self._mq.get("dato_limit", 120) * 2
        sentences = re.split(r"(?<=[.!?])\s+", text)
        result = []
        for s in sentences:
            s = s.strip()
            if min_len <= len(s) <= max_len and len(re.findall(r"\d", s)) >= 2:
                result.append(s)
        return result

    def _update_spell_tab(self, field: str, errors: list):
        self._spell_errors_by_field[field] = errors
        while self._corr_lay.count() > 1:
            item = self._corr_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        total = 0
        for fname, errs in self._spell_errors_by_field.items():
            for err in errs:
                item = _SpellErrorItem(err, fname)
                item.clicked_item.connect(
                    lambda e, f, w=item: self._on_error_item_clicked(e, f, w)
                )
                item.navigate_item.connect(self._navigate_to_error)
                self._corr_lay.insertWidget(self._corr_lay.count() - 1, item)
                total += 1

        spell_n = sum(1 for errs in self._spell_errors_by_field.values()
                      for e in errs if e["type"] == "spell")
        rep_n   = sum(1 for errs in self._spell_errors_by_field.values()
                      for e in errs if e["type"] in ("repeat", "proximity"))
        if total == 0:
            self._lbl_corr_hdr.setText("Sin errores detectados")
        else:
            parts = []
            if spell_n:  parts.append(f"{spell_n} ortográfico{'s' if spell_n>1 else ''}")
            if rep_n:    parts.append(f"{rep_n} repetición{'es' if rep_n>1 else ''}")
            self._lbl_corr_hdr.setText("  ·  ".join(parts))

    def _on_error_item_clicked(self, err: dict, field: str, item_widget: _SpellErrorItem):
        hl = self._hl_bajada if field == "Bajada" else self._hl_cuerpo
        if hl is None:
            return
        suggestions = err.get("suggestions")
        if suggestions is None:
            suggestions = hl._spell.get_suggestions(err["word"])
            err["suggestions"] = suggestions

        user_sug = _UserReplacements.get(err["word"])
        all_sug = user_sug + [s for s in (suggestions or []) if s not in user_sug]
        popup = _SuggestionPopup(err["word"], all_sug, err["type"], self)
        popup.suggestion_chosen.connect(
            lambda s, e=err, f=field: self._apply_suggestion(f, e, s)
        )
        popup.add_to_dict_req.connect(lambda w=err["word"], h=hl: h.add_word_to_dict(w))
        popup.ignore_req.connect(lambda w=err["word"], h=hl: h.ignore_word(w))
        popup.replace_requested.connect(
            lambda repl, e=err, f=field, w=err["word"]: (
                self._apply_suggestion(f, e, repl),
                _UserReplacements.add(w, repl),
            )
        )
        global_pos = item_widget.mapToGlobal(QPoint(0, item_widget.height()))
        popup.move(global_pos)
        popup.show()

    def _navigate_to_error(self, err: dict, field: str):
        """Doble clic en error: cambia al editor correspondiente, hace scroll y selecciona."""
        if not self._stories:
            return
        editor = (
            self._stories[0].ed_bajada if field == "Bajada"
            else self._stories[0].ed_cuerpo
        )
        # Switch to the first story tab
        self._story_tabs.setCurrentIndex(0)
        # Switch to the right correction tab (it's already there, but also show the editor)
        editor.setFocus(Qt.OtherFocusReason)
        # Select the error range
        c = QTextCursor(editor.document())
        c.setPosition(err["start"])
        c.setPosition(err["end"], QTextCursor.KeepAnchor)
        editor.setTextCursor(c)
        editor.ensureCursorVisible()

    def _apply_suggestion(self, field: str, err: dict, new_word: str):
        if not self._stories:
            return
        editor = (
            self._stories[0].ed_bajada if field == "Bajada"
            else self._stories[0].ed_cuerpo
        )
        c = QTextCursor(editor.document())
        c.setPosition(err["start"])
        c.setPosition(err["end"], QTextCursor.KeepAnchor)
        c.insertText(new_word)

    def _on_detect_textuales(self):
        """Re-analizar: re-detecta candidatos PRESERVANDO la selección y los datos ya
        cargados (nombre/cargo/foto). Antes `set_candidates` borraba todo en silencio →
        el usuario guardaba con el tipo elegido y 0 seleccionados → los boxes de Quark
        se editaban con texto vacío (bug 'textual en blanco')."""
        if not self._stories:
            return
        body = self._active_story().ed_cuerpo.toPlainText()
        cands = self._detector.detect(body)
        self._textual_cards.reanalizar_preservando([c.text for c in cands])
        self._right_tabs.setCurrentWidget(self._tab_textuales)

    def _show_spell_menu(self, editor, highlighter, pos):
        if highlighter is None:
            menu = editor.createStandardContextMenu()
            menu.exec_(editor.mapToGlobal(pos))
            return
        cursor = editor.cursorForPosition(pos)
        position = cursor.position()
        result = highlighter.get_suggestions_at(position)
        if not result:
            menu = editor.createStandardContextMenu()
            menu.exec_(editor.mapToGlobal(pos))
            return

        word, suggestions = result
        err_type = next(
            (e["type"] for e in highlighter._errors if e["start"] <= position <= e["end"]),
            "spell"
        )
        err_obj = next(
            (e for e in highlighter._errors if e["start"] <= position <= e["end"]),
            None
        )
        field = "Bajada" if highlighter is self._hl_bajada else "Cuerpo"
        user_sug = _UserReplacements.get(word)
        all_sug = user_sug + [s for s in (suggestions or []) if s not in user_sug]
        menu = editor.createStandardContextMenu()
        menu.addSeparator()
        if all_sug:
            for sug in all_sug[:5]:
                act = QAction(f'Reemplazar con: "{sug}"', menu)
                if err_obj is not None:
                    act.triggered.connect(
                        lambda _, s=sug, e=err_obj, f=field: self._apply_suggestion(f, e, s)
                    )
                menu.addAction(act)
        else:
            act_no_sug = QAction(f'"{word}" — sin sugerencias', menu)
            act_no_sug.setEnabled(False)
            menu.addAction(act_no_sug)
        if err_type == "spell":
            menu.addSeparator()
            act_dict = QAction(f'Agregar "{word}" al diccionario', menu)
            act_dict.triggered.connect(lambda _, w=word, hl=highlighter: hl.add_word_to_dict(w))
            menu.addAction(act_dict)
        act_ignore = QAction(f'Omitir "{word}"', menu)
        act_ignore.triggered.connect(lambda _, w=word, hl=highlighter: hl.ignore_word(w))
        menu.addAction(act_ignore)
        menu.exec_(editor.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Configuración de maqueta
    # ------------------------------------------------------------------

    def _open_config(self):
        nombre = self._cb_maqueta.currentText()
        dlg = MaquetaConfigDialog(self._mq, parent=self, nombre=nombre)
        if dlg.exec_() == dlg.Accepted:
            new_cfg = dlg.get_result()
            config_global.save_maqueta_config_for(nombre, new_cfg)
            self._mq.update(new_cfg)
            self._apply_new_limits()
            # Compartir los límites editados con las demás estaciones.
            self.maqueta_limits_guardados.emit()

    def _on_maqueta_changed(self, nombre: str):
        if not nombre:
            return
        self._mq.update(config_global.maqueta_config_for(nombre))
        self._merge_cache_limits(nombre)
        self._apply_new_limits()

    def _merge_cache_limits(self, maqueta: str) -> None:
        """Aplica sobre self._mq los límites derivados de la CACHÉ de lectura de
        maquetas (capacidades reales medidas por CDP). La lectura real es la fuente
        preferida para volanta/cuerpo/epígrafe; el resto viene de config."""
        try:
            from services.maqueta_reader_service import limits_from_cache
            cache_lim = limits_from_cache(maqueta, getattr(self, "_seccion", "") or "")
            if cache_lim:
                # picture_count no es un límite de campo; no ensuciar _mq con él.
                cache_lim.pop("picture_count", None)
                self._mq.update(cache_lim)
                _log.info("[EDITOR] Límites de caché aplicados para '%s': %s",
                          maqueta, sorted(cache_lim.keys()))
        except Exception as e:
            _log.debug("[EDITOR] _merge_cache_limits: %s", e)

    def refrescar_limites_maqueta(self):
        """Re-aplica los límites de la maqueta actual (p.ej. tras adoptar cambios de
        otra estación). No toca el tema de visualización local."""
        self._on_maqueta_changed(self._cb_maqueta.currentText())

    def _open_display_config(self):
        from ui.display_config_dialog import DisplayConfigDialog
        dlg = DisplayConfigDialog(self._mq, parent=self)
        if dlg.exec_() == dlg.Accepted:
            new_cfg = dlg.get_result()
            config_global.save_maqueta_config(new_cfg)
            self._mq.update(new_cfg)
            self._apply_qss()
            for panel in self._stories:
                panel._apply_field_fonts(self._mq)

    def _on_body_display_changed(self, settings: dict):
        """La barra de visualización del cuerpo cambió: sincronizar el resto de
        las noticias (en memoria) y persistir con debounce.

        El apply visual ya ocurrió en el panel emisor; escribir el INI en cada
        paso del spin trababa el repaint (se sentía con retardo). Se difiere."""
        self._mq.update(settings)
        sender = self.sender()
        for panel in self._stories:
            if panel is not sender:
                panel.set_body_display(settings)

        self._pending_display = dict(settings)
        t = getattr(self, "_display_save_timer", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(500)
            t.timeout.connect(self._flush_display_save)
            self._display_save_timer = t
        t.start()

    def _flush_display_save(self):
        """Escribe a disco los últimos ajustes de visualización (debounced)."""
        pending = getattr(self, "_pending_display", None)
        if not pending:
            return
        try:
            config_global.save_maqueta_config(pending)
        except Exception as e:
            _log.warning("No se pudo guardar la visualización del cuerpo: %s", e)
        self._pending_display = None

    def _apply_new_limits(self):
        mq = self._mq
        self._apply_qss()
        for panel in self._stories:
            panel._firma_deduccion = mq.get("firma_deduccion", 275)
            panel.cnt_volanta.set_limit(mq.get("volanta_limit", 90))
            panel.cnt_bajada.set_limit(mq.get("bajada_limit", 220))
            panel.cnt_epigrafe.set_limit(mq.get("epigrafe_principal_limit", 120))
            panel.cnt_volanta.update_count(panel.ed_volanta.toPlainText())
            panel.cnt_bajada.update_count(panel.ed_bajada.toPlainText())
            panel.cnt_epigrafe.update_count(panel.ed_epigrafe.text())
        self._textual_cards.set_limits(
            sin_foto=mq.get("textual_sin_foto_limit", 220),
            con_foto=mq.get("textual_con_foto_limit", 320),
            epigrafe=mq.get("textual_epigrafe_limit", 90),
        )
        self._apply_all_story_limits()

    # ------------------------------------------------------------------
    # Estilos
    # ------------------------------------------------------------------

    def _apply_qss(self):
        fs = self._mq.get("editor_font_size", 13)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: #101820;
                color: #e2e8f0;
                font-size: {fs}px;
            }}
            QLabel[pageTitle="true"] {{
                font-size: 18px;
                font-weight: 700;
                color: #e7885f;
                padding-bottom: 4px;
            }}
            QLabel[fieldTitle="true"] {{
                font-size: 13px;
                font-weight: 600;
                color: rgba(255,255,255,0.85);
            }}
            QPlainTextEdit, QLineEdit {{
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 8px;
                padding: 8px;
                color: #e2e8f0;
            }}
            QPlainTextEdit:focus, QLineEdit:focus {{
                border: 1px solid rgba(130,180,255,0.55);
                background: rgba(255,255,255,0.08);
            }}
            QComboBox {{
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 8px;
                padding: 4px 10px;
                color: #e2e8f0;
            }}
            QComboBox::drop-down {{ border: none; }}
            QPushButton {{
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 7px;
                padding: 6px 12px;
                color: #e2e8f0;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
            QPushButton[primary="true"] {{
                background: rgba(231,136,95,0.25);
                border-color: rgba(231,136,95,0.55);
                color: #f0c0a0;
            }}
            QPushButton[primary="true"]:hover {{
                background: rgba(231,136,95,0.38);
            }}
            QPushButton[compact="true"] {{
                padding: 4px 10px;
                font-size: 11px;
            }}
            QScrollBar:vertical {{
                border: none;
                background: rgba(255,255,255,0.04);
                width: 8px;
                margin: 0;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.18);
                min-height: 24px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.28); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QTabWidget::pane {{
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 6px;
            }}
            QTabBar {{
                background: transparent;
                border: none;
            }}
            QTabBar::tab {{
                padding: 6px 14px;
                border-radius: 6px 6px 0 0;
                color: rgba(255,255,255,0.6);
            }}
            QTabBar::tab:selected {{
                background: rgba(231,136,95,0.20);
                color: #e7885f;
            }}
            /* Flechas ‹ › del tab bar cuando las pestañas no entran en el ancho.
               Fondo opaco + tamaño explícito para que la flecha (dibujada por Qt) se
               vea y no queden botones casi transparentes y apelotonados. */
            QTabBar::scroller {{ width: 44px; }}
            QTabBar QToolButton {{
                background: #2b3a4f;
                border: 1px solid rgba(255,255,255,0.30);
                border-radius: 4px;
                min-width: 20px;
                margin: 1px;
            }}
            QTabBar QToolButton:hover {{ background: #e7885f; border-color: #e7885f; }}
            QTabBar QToolButton:pressed {{ background: #c96a41; }}
            QTabBar QToolButton:disabled {{ background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.10); }}
            QFrame {{
                border: 1px solid rgba(255,255,255,0.10);
                background: rgba(255,255,255,0.04);
                border-radius: 10px;
            }}
            QFrame[over="true"] {{
                border: 1px solid rgba(255,100,100,0.55);
                background: rgba(255,100,100,0.06);
            }}
            QFrame[selected="true"] {{
                border: 2px solid rgba(100,180,255,0.85);
                background: rgba(100,180,255,0.16);
            }}
            QMenuBar {{
                background: #101820;
                color: #e2e8f0;
                border-bottom: 1px solid rgba(255,255,255,0.08);
            }}
            QMenuBar::item:selected {{ background: rgba(255,255,255,0.10); }}
            QMenu {{
                background: #1e293b;
                color: #e2e8f0;
                border: 1px solid rgba(255,255,255,0.12);
            }}
            QMenu::item:selected {{ background: rgba(255,255,255,0.12); }}
        """)
