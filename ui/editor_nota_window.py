from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPoint, QThread, QPropertyAnimation
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QScrollArea, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QMessageBox, QAction, QMenuBar, QShortcut,
    QTabWidget, QComboBox, QFrame, QSizePolicy, QSpinBox,
    QDialog, QDialogButtonBox,
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
        self.lbl.setText(t if len(t) <= 110 else t[:107] + "…")
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
    def __init__(self, text: str = "", limit: int = 120, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar dato")
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

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

    def get_result(self) -> str:
        return self._ed.toPlainText().strip()


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
        self._qr_path: Path | None = None
        self._body_highlight_range: tuple[int, int] | None = None
        self._highlight_source: str = ""  # "textual", "dato", "numero"
        self._arrow_overlay: _SelectionArrowOverlay | None = None

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
        hdr_lay.setContentsMargins(14, 14, 14, 8)
        hdr_lay.setSpacing(8)

        self._lbl_page = QLabel(f"Página {self.numero}")
        self._lbl_page.setProperty("pageTitle", True)
        hdr_lay.addWidget(self._lbl_page)

        maqueta_row = QHBoxLayout()
        maqueta_row.setSpacing(8)
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
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_guardar)
        btn_row.addWidget(self._btn_guardar_armar)
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

        # ── Pestañas de noticias ──
        self._story_tabs = QTabWidget()
        self._left_lay.addWidget(self._story_tabs, 1)

        # ── Swap button ──
        self._btn_swap = QPushButton("⇄  Intercambiar noticias")
        self._btn_swap.setCursor(Qt.PointingHandCursor)
        self._btn_swap.setVisible(False)
        self._left_lay.addWidget(self._btn_swap)

        # ── Panel derecho (tabs) ──
        self._right_tabs = QTabWidget()
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
        self._cb_foto_tipo.addItems(["2 columnas", "3 columnas wide", "3 columnas ancha"])
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
        self._cb_textual_tipo.addItems(["—", "simple", "x2", "x3", "con foto", "con foto XL"])
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

        self._btn_sel_textual = QPushButton("Seleccionar textual")
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
        lay_num.addStretch(1)

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
        self._right_tabs.addTab(self._tab_corr, "Corrección")

        # Señales
        self._cb_textual_tipo.currentTextChanged.connect(self._on_textual_tipo_changed)
        self._cb_textual_tipo.currentTextChanged.connect(lambda _: self._recalcular_deduccion())
        self._textual_cards.changed.connect(self._recalcular_deduccion)
        self._textual_cards.changed.connect(self._on_textual_selection_changed)
        self._cb_foto_tipo.currentTextChanged.connect(lambda _: self._recalcular_deduccion())
        self._btn_reanalizar.clicked.connect(self._on_detect_textuales)
        self._btn_guardar.clicked.connect(self._on_guardar)
        self._btn_guardar_armar.clicked.connect(self._on_guardar_para_armar)
        self._cb_maqueta.activated[str].connect(self._on_maqueta_changed)
        self._btn_swap.clicked.connect(self._on_swap)
        self._sb_noticias.valueChanged.connect(self._on_story_count_changed)
        self._btn_add_all_dict.clicked.connect(self._on_add_all_to_dict)
        self._btn_ignore_all.clicked.connect(self._on_ignore_all)
        self._btn_sel_textual.toggled.connect(self._on_sel_textual_toggled)
        self._btn_sel_accept.clicked.connect(self._on_sel_textual_accept)
        self._btn_sel_cancel.clicked.connect(self._on_sel_textual_cancel)
        self._right_tabs.currentChanged.connect(lambda _: self._update_arrow_overlay())

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

    def _add_story_panel(self, story_index: int) -> StoryPanel:
        panel = StoryPanel(story_index, self._mq)
        label = "Principal" if story_index == 0 else f"Noticia {story_index + 1}"
        self._story_tabs.addTab(panel, label)
        self._stories.append(panel)
        panel.body_display_changed.connect(self._on_body_display_changed)

        if story_index == 0:
            panel.ed_bajada.setContextMenuPolicy(Qt.CustomContextMenu)
            panel.ed_bajada.customContextMenuRequested.connect(
                lambda pos, p=panel: self._show_spell_menu(p.ed_bajada, self._hl_bajada, pos)
            )
            panel.ed_cuerpo.setContextMenuPolicy(Qt.CustomContextMenu)
            panel.ed_cuerpo.customContextMenuRequested.connect(
                lambda pos, p=panel: self._show_spell_menu(p.ed_cuerpo, self._hl_cuerpo, pos)
            )
            panel.ed_bajada.textChanged.connect(self._on_bajada_changed)
            panel.ed_cuerpo.textChanged.connect(self._on_cuerpo_changed)
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
        self._btn_swap.setVisible(count >= 2)
        self._apply_all_story_limits()

    def _apply_all_story_limits(self):
        """Aplica los límites del config a todos los paneles de noticia."""
        mq = self._mq
        limits = {
            "cuerpo_limit":             mq.get("cuerpo_limit", 0),
            "volanta_limit":            mq.get("volanta_limit", 90),
            "bajada_limit":             mq.get("bajada_limit", 220),
            "titulo_lineas":            mq.get("titulo_lineas", 2),
            "titulo_chars_linea":       mq.get("titulo_chars_linea", 38),
            "epigrafe_principal_limit": mq.get("epigrafe_principal_limit", 120),
        }
        for panel in self._stories:
            panel.apply_limits(limits)

    def _on_story_type_changed(self, story_index: int, story_type: str):
        maqueta = self._cb_maqueta.currentText()
        story_count = self._sb_noticias.value()
        config_global.save_story_type(maqueta, self._seccion, story_count, story_index, story_type)
        self._apply_all_story_limits()

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
        saved_maqueta = ""
        if dirs:
            first_json = dirs[0] / f"{dirs[0].name}.json"
            if first_json.exists():
                try:
                    nota_data = json.loads(first_json.read_text(encoding="utf-8"))
                    saved_maqueta = nota_data.get("maqueta", "")
                    self._textuales_auto = nota_data.get("textuales_auto", []) or []
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
        if not self._stories:
            return
        panel = self._stories[0]
        panel.ed_epigrafe.setText(texto)
        panel.ed_epigrafe.setCursorPosition(0)   # leer el epígrafe desde el inicio

    # ------------------------------------------------------------------
    # Slots de campos (principal story)
    # ------------------------------------------------------------------

    def _on_bajada_changed(self):
        if not self._stories:
            return
        txt = self._stories[0].ed_bajada.toPlainText()
        if self._hl_bajada is not None:
            self._hl_bajada.schedule_check(txt)

    def _on_cuerpo_changed(self):
        if not self._stories:
            return
        txt = self._stories[0].ed_cuerpo.toPlainText()
        if self._hl_cuerpo is not None:
            self._hl_cuerpo.schedule_check(txt)

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

    def _on_qr_seleccionada(self, path) -> None:
        self._qr_path = path
        self._recalcular_deduccion()

    def _recalcular_deduccion(self) -> None:
        total = 0

        # Textual
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

        # Tipo de foto
        foto_tipo = self._cb_foto_tipo.currentText()
        if foto_tipo == "3 columnas wide":
            total += self._mq.get("foto_3wide_deduccion", 450)
        elif foto_tipo == "3 columnas ancha":
            total += self._mq.get("foto_3ancha_deduccion", 625)

        for panel in self._stories:
            panel.set_external_deduction(total)

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
            new_text = dlg.get_result()
            if new_text:
                card = _DatoCard(new_text, limit)
                card.set_edited_text(new_text)
                card.selected.connect(lambda t, c=card: self._on_dato_card_selected(t, c))
                card.edit_requested.connect(lambda c=card: self._on_dato_card_dbl_clicked(c))
                self._dato_lay_cards.insertWidget(0, card)
                self._dato_cards.insert(0, card)
                card.set_selected(True)
                self._recalcular_deduccion()

    def _on_dato_card_dbl_clicked(self, card: "_DatoCard"):
        dlg = _DatoEditDialog(card._edited_text, self._mq.get("dato_limit", 120), parent=self)
        if dlg.exec_() == dlg.Accepted:
            new_text = dlg.get_result()
            if new_text:
                card.set_edited_text(new_text)
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
                        or " ".join(p.title_grid.get_lines()).strip())

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
        if sel_tx and self._cb_textual_tipo.currentText() == "—":
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
        for panel in panels:
            try:
                panel.save_to_path(panel._txt_path)
                self._actualizar_nota_json(panel._txt_path, panel, maqueta_sel)
            except Exception as e:
                QMessageBox.critical(self, "Error al guardar", str(e))
                return False
        self.nota_guardada.emit(self.numero)
        return True

    def _on_guardar(self):
        if self._do_save():
            names = ", ".join(p._txt_path.stem for p in self._stories if p._txt_path)
            QMessageBox.information(self, "Guardado", f"Nota(s) guardada(s):\n{names}")

    def _on_guardar_para_armar(self):
        if self._do_save():
            self.nota_guardada_para_armar.emit(self.numero)
            self.close()

    def _actualizar_nota_json(self, txt_path: Path, panel: "StoryPanel", maqueta: str):
        """Actualiza el JSON de la nota con los campos del editor y la maqueta seleccionada."""
        json_path = txt_path.with_suffix(".json")
        data: dict = {}
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        titulo = " ".join(ln.strip() for ln in panel.title_grid.get_lines() if ln.strip())

        # Textual
        tipo_label = self._cb_textual_tipo.currentText()
        tipo_map = {
            "simple": "simple", "x2": "x2", "x3": "x3",
            "con foto": "con_foto", "con foto XL": "con_foto_xl",
        }
        tipo = tipo_map.get(tipo_label)
        textual = None
        if tipo:
            selected = self._textual_cards.selected_items()
            textual = {"tipo": tipo}
            for i, item in enumerate(selected[:3], 1):
                textual[f"texto{i}"] = item.get("text", "")
                textual[f"nombre{i}"] = item.get("orador_nombre", "")
                raw_cargo = item.get("orador_cargo", "").strip()
                textual[f"cargo{i}"] = (" " + raw_cargo) if raw_cargo else ""
            if tipo in ("con_foto", "con_foto_xl") and selected:
                foto_info = selected[0].get("foto") or {}
                foto_src = foto_info.get("path", "")
                textual["foto"] = self._copy_foto_textual(foto_src, txt_path) if foto_src else None
            else:
                textual["foto"] = None

        # Dato
        dato = None
        for c in self._dato_cards:
            if c._is_selected:
                dato = c._edited_text.strip() or None
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
        if not self._stories:
            return
        body = self._stories[0].ed_cuerpo.toPlainText()
        if not body.strip():
            return
        cands = self._detector.detect(body)
        self._textual_cards.set_candidates([c.text for c in cands])
        textuales_auto = getattr(self, "_textuales_auto", [])
        if textuales_auto:
            self._textual_cards.add_preselected(textuales_auto)
        datos = self._detect_datos(body)
        self._populate_dato_cards(datos)
        self._restore_saved_fields()

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

    def _restore_saved_fields(self):
        if not self._stories or not self._stories[0]._txt_path:
            return
        json_path = self._stories[0]._txt_path.with_suffix(".json")
        if not json_path.exists():
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

        # Dato
        dato = data.get("dato") or ""
        if dato:
            limit = self._mq.get("dato_limit", 120)
            matched = False
            for card in self._dato_cards:
                if card._text == dato or card._edited_text == dato:
                    card.set_edited_text(dato)
                    card.set_selected(True)
                    for c in self._dato_cards:
                        if c is not card:
                            c.set_selected(False)
                    matched = True
                    break
            if not matched:
                card = _DatoCard(dato, limit)
                card.set_edited_text(dato)
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

        # Tipo de foto
        foto_tipo = data.get("foto_tipo", "2 columnas")
        idx = self._cb_foto_tipo.findText(foto_tipo)
        if idx >= 0:
            self._cb_foto_tipo.blockSignals(True)
            self._cb_foto_tipo.setCurrentIndex(idx)
            self._cb_foto_tipo.blockSignals(False)

        self._recalcular_deduccion()

    def _on_dato_card_selected(self, text: str, card: _DatoCard):
        for c in self._dato_cards:
            if c is not card:
                c.set_selected(False)
        self._recalcular_deduccion()
        self._highlight_body_text(text if card._is_selected else "", source="dato")

    # ------------------------------------------------------------------
    # Resaltado en cuerpo y overlay de flecha
    # ------------------------------------------------------------------

    def _highlight_body_text(self, text: str, source: str = ""):
        self._body_highlight_range = None
        self._highlight_source = source
        if not self._stories:
            return
        editor = self._stories[0].ed_cuerpo
        if not text:
            editor.setExtraSelections([])
            self._update_arrow_overlay()
            return
        body = editor.toPlainText()
        idx = body.find(text)
        if idx < 0:
            editor.setExtraSelections([])
            self._update_arrow_overlay()
            return
        self._body_highlight_range = (idx, idx + len(text))
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(100, 180, 255, 55))
        fmt.setProperty(QTextCharFormat.OutlinePen, QColor(100, 180, 255, 200))
        from PyQt5.QtWidgets import QTextEdit
        sel = QTextEdit.ExtraSelection()
        sel.format = fmt
        c = QTextCursor(editor.document())
        c.setPosition(idx)
        c.setPosition(idx + len(text), QTextCursor.KeepAnchor)
        sel.cursor = c
        editor.setExtraSelections([sel])
        self._update_arrow_overlay()

    def _update_arrow_overlay(self):
        if not self._arrow_overlay or not self._stories:
            return
        editor = self._stories[0].ed_cuerpo
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
        editor = self._stories[0].ed_cuerpo
        c = QTextCursor(editor.document())
        c.setPosition(self._body_highlight_range[0])
        editor.setTextCursor(c)
        editor.ensureCursorVisible()

    def _on_textual_selection_changed(self):
        sel = self._textual_cards.selected_items()
        if sel:
            self._highlight_body_text(sel[0].get("text", ""), source="textual")
        else:
            self._highlight_body_text("", source="textual")

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

    def _on_sel_textual_toggled(self, on: bool):
        self._sel_textual_row.setVisible(on)
        if not self._stories:
            return
        panel = self._stories[0]
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

    def _on_sel_textual_accept(self):
        if not self._stories:
            return
        text = self._stories[0].ed_cuerpo.textCursor().selectedText().strip()
        if text:
            self._textual_cards.add_preselected([text])
        self._btn_sel_textual.setChecked(False)

    def _on_sel_textual_cancel(self):
        if self._stories:
            c = self._stories[0].ed_cuerpo.textCursor()
            c.clearSelection()
            self._stories[0].ed_cuerpo.setTextCursor(c)
        self._btn_sel_textual.setChecked(False)

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
        if not self._stories:
            return
        body = self._stories[0].ed_cuerpo.toPlainText()
        cands = self._detector.detect(body)
        self._textual_cards.set_candidates([c.text for c in cands])
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
        self._apply_new_limits()

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
                border-radius: 8px;
                padding: 8px 14px;
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
                padding: 6px 11px;
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
            QTabBar::tab {{
                padding: 6px 14px;
                border-radius: 6px 6px 0 0;
                color: rgba(255,255,255,0.6);
            }}
            QTabBar::tab:selected {{
                background: rgba(231,136,95,0.20);
                color: #e7885f;
            }}
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
