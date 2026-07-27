from __future__ import annotations
import json
import re
from pathlib import Path
from PyQt5.QtCore import Qt, QObject, QEvent, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit,
    QComboBox, QCheckBox, QDialog, QDialogButtonBox, QPushButton, QMessageBox,
)
from PyQt5.QtGui import QFont

from ui.widgets.field_block import FieldBlock
from ui.widgets.title_grid_editor import TitleGridEditor
from ui.widgets.body_display import (
    BodyDisplayToolbar, apply_body_display, body_qss, extract_settings,
)

def _normalizar_cuerpo(texto: str) -> str:
    """Colapsa \n\n+ a \n; conserva \n\n antes de intertítulos ##."""
    partes = re.split(r'(\n{2,})', texto)
    resultado = []
    for i, parte in enumerate(partes):
        if re.match(r'\n{2,}', parte):
            siguiente = partes[i + 1] if i + 1 < len(partes) else ""
            if siguiente.lstrip().startswith("##"):
                resultado.append("\n\n")
            else:
                resultado.append("\n")
        else:
            resultado.append(parte)
    return "".join(resultado).strip()


_QUOTE_MAP = str.maketrans({
    '«': '“', '»': '”',  # « » → " "
    '‘': "'",      '’': "'",        # ' ' → ' (rectas)
})

def _normalizar_comillas(text: str) -> str:
    """Convierte comillas rectas ASCII dobles a tipográficas " " y normaliza « »."""
    text = text.translate(_QUOTE_MAP)
    text = re.sub(r'(?<!\w)"(?=\S)', '“', text)
    text = re.sub(r'(?<=\S)"(?!\w)', '”', text)
    text = re.sub(r'"(?=\S)', '“', text)
    return text


_COUNTER_CLR = {
    "short":  "#e87844",  # naranja (pocos chars = campo desaprovechado)
    "medium": "#d4a830",  # naranja-amarillo
    "near":   "#c8c040",  # amarillo
    "good":   "#5abc8a",  # verde
    "over":   "#ff6060",  # rojo
}
_EDIT_BG = {
    "short":  "rgba(232,120,68,0.08)",
    "medium": "rgba(212,168,48,0.07)",
    "near":   "rgba(200,192,64,0.07)",
    "good":   "rgba(80,195,130,0.08)",
    "over":   "rgba(255,80,80,0.08)",
}
_EDIT_BD = {
    "short":  "rgba(232,120,68,0.30)",
    "medium": "rgba(212,168,48,0.26)",
    "near":   "rgba(200,192,64,0.28)",
    "good":   "rgba(80,195,130,0.32)",
    "over":   "rgba(255,80,80,0.35)",
}


_COUNTER_BG = {
    "short":  "rgba(232,120,68,0.12)",
    "medium": "rgba(212,168,48,0.10)",
    "near":   "rgba(200,192,64,0.10)",
    "good":   "rgba(90,188,138,0.12)",
    "over":   "rgba(255,96,96,0.15)",
}


class CharCounter(QLabel):
    def __init__(self, limit: int, warning_margin: int = 50, linked_widget=None,
                 parent=None, manage_style: bool = True):
        super().__init__(parent)
        self._limit = limit
        self._linked = linked_widget
        self._manage_style = manage_style   # False → no reescribe el estilo del editor
        self._current = 0
        self._font_size = 11
        self._linked_font_size = 0  # 0 = heredar del padre
        self.state: str | None = None       # último nivel de llenado calculado
        self._update_display()

    def set_font_size(self, size: int):
        self._font_size = size
        self._update_display()

    def set_linked_font_size(self, size: int):
        self._linked_font_size = size
        self._update_display()

    def update_count(self, text: str):
        self._current = len(text.strip()) if text else 0
        self._update_display()

    def set_limit(self, limit: int):
        self._limit = limit
        self._update_display()

    def _update_display(self):
        n = self._current
        m = self._limit
        self.setText(f"{n}/{m}")
        fs = self._font_size
        if m <= 0:
            self.state = None
            self.setStyleSheet(
                f"color: rgba(255,255,255,0.45); font-size: {fs}px;"
                " border: 1.5px solid rgba(255,255,255,0.12); border-radius: 6px;"
                " background: rgba(255,255,255,0.04); padding: 4px;"
            )
            return
        ratio = n / m
        if n > m:           state = "over"
        elif ratio >= 0.95: state = "good"
        elif ratio >= 0.70: state = "near"
        elif ratio >= 0.35: state = "medium"
        else:               state = "short"
        self.state = state
        clr = _COUNTER_CLR[state]
        bg  = _COUNTER_BG[state]
        self.setStyleSheet(
            f"color: {clr}; font-size: {fs}px; font-weight: 600;"
            f" border: 1.5px solid {clr}; border-radius: 6px;"
            f" background: {bg}; padding: 4px;"
        )
        if self._manage_style and self._linked is not None:
            wn = type(self._linked).__name__
            font_rule = f" font-size: {self._linked_font_size}px;" if self._linked_font_size else ""
            self._linked.setStyleSheet(
                f"{wn} {{"
                f" background: {_EDIT_BG[state]};"
                f" border: 1px solid {_EDIT_BD[state]};"
                f" border-radius: 8px; padding: 8px; color: #e2e8f0;{font_rule}"
                f"}}"
            )


class NextFilter(QObject):
    def __init__(self, on_next):
        super().__init__()
        self._on_next = on_next

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress:
            key = ev.key()
            mod = ev.modifiers()
            no_mod = not (mod & (Qt.ControlModifier | Qt.AltModifier))
            if key == Qt.Key_Tab and no_mod:
                if isinstance(obj, (QLineEdit, QPlainTextEdit, QTextEdit)):
                    self._on_next(obj)
                    return True
            # Enter/Return salta campo solo en QLineEdit (una línea); en QPlainTextEdit inserta salto
            if key in (Qt.Key_Return, Qt.Key_Enter) and no_mod:
                if isinstance(obj, QLineEdit):
                    self._on_next(obj)
                    return True
        return False


def _wrap(editor: QWidget, counter: QWidget) -> QWidget:
    counter.setMinimumWidth(80)
    counter.setMaximumWidth(200)
    counter.setMinimumHeight(44)
    counter.setWordWrap(True)
    counter.setAlignment(Qt.AlignCenter)
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(editor, 1)
    lay.addWidget(counter)
    return w


class StoryPanel(QWidget):
    """Agrupa todos los campos de edición de una noticia."""

    textChanged = pyqtSignal()
    story_type_changed = pyqtSignal(str)   # emitido cuando el usuario cambia el tipo
    body_display_changed = pyqtSignal(dict)  # ajustes de visualización del cuerpo
    ia_config_needed = pyqtSignal()        # falta API key → abrir configuración de IA
    ia_busy_changed = pyqtSignal(bool)     # True mientras corre una reescritura por IA

    def __init__(self, story_index: int, mq: dict, parent=None):
        super().__init__(parent)
        self._story_index = story_index
        self._mq = dict(mq)
        self._body_display = extract_settings(mq)   # tema de lectura del cuerpo
        self._txt_path: Path | None = None
        self._cuerpo_box_limit: int = 0
        self._deduction_external: int = 0
        self._firma_deduccion: int = mq.get("firma_deduccion", 275)
        # #7 — cada intertítulo (línea que empieza con ##) ocupa ~1 línea extra.
        self._intertitulo_deduccion: int = mq.get("intertitulo_deduccion", 35)
        self._story_type: str = ""

        # ── Estado de reescritura por IA ──
        self._ia_workers: list = []                 # workers vivos (evita GC)
        self._ia_original: dict[str, str] = {}      # campo → texto previo a la IA
        self._ia_suppress_clear: bool = False       # no limpiar highlight en set programático
        self._ia_btn: dict[str, QPushButton] = {}
        self._ia_undo_btn: dict[str, QPushButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # Contenedor superior colapsable (volanta/título/bajada/firma/epígrafe): al hacer
        # scroll hacia abajo se oculta animado y el cuerpo ocupa todo el panel.
        self._upper = QWidget()
        lay = QVBoxLayout(self._upper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        outer.addWidget(self._upper)
        self._upper_collapsed = False
        self._upper_anim = None

        # ── Volanta ──
        self.ed_volanta = QPlainTextEdit()
        self.ed_volanta.setFixedHeight(60)
        self.ed_volanta.setPlaceholderText("Volanta...")
        self.cnt_volanta = CharCounter(mq.get("volanta_limit", 90), 50, self.ed_volanta)
        self._block_volanta = FieldBlock(
            "Volanta", _wrap(self.ed_volanta, self.cnt_volanta),
            header_widgets=self._make_ia_buttons("volanta"),
        )
        lay.addWidget(self._block_volanta)

        # ── Título ──
        cols = mq.get("titulo_chars_linea", 33)
        rows = mq.get("titulo_lineas", 2)
        self.title_grid = TitleGridEditor(cols_per_line=cols, rows=rows)
        self.cnt_titulo = QLabel("")
        self._cnt_titulo_fs: int = 11
        self._titulo_over: bool = False
        titulo_wrap = _wrap(self.title_grid, self.cnt_titulo)
        titulo_wrap.setFocusProxy(self.title_grid)

        # Header del título: [Tipo: ▼]  Título (N líneas × M chars)
        titulo_hdr = QWidget()
        titulo_hdr_lay = QHBoxLayout(titulo_hdr)
        titulo_hdr_lay.setContentsMargins(0, 0, 0, 0)
        titulo_hdr_lay.setSpacing(8)

        self._type_lbl: QLabel | None = None
        self._type_cb: QComboBox | None = None
        if story_index > 0:
            self._type_lbl = QLabel("Tipo:")
            self._type_lbl.setVisible(False)
            self._type_cb = QComboBox()
            self._type_cb.setFixedWidth(130)
            self._type_cb.setVisible(False)
            self._type_cb.currentTextChanged.connect(self._on_type_changed)
            titulo_hdr_lay.addWidget(self._type_lbl)
            titulo_hdr_lay.addWidget(self._type_cb)

        self._titulo_sin_espacio = False   # breves: contar el título sin espacios
        self._titulo_lbl = QLabel(
            f"Título ({rows} línea{'s' if rows > 1 else ''} × {cols} chars)"
        )
        self._titulo_lbl.setProperty("fieldTitle", True)
        titulo_hdr_lay.addWidget(self._titulo_lbl)
        for _b in self._make_ia_buttons("titulo"):
            titulo_hdr_lay.addWidget(_b)
        titulo_hdr_lay.addStretch(1)

        titulo_section = QWidget()
        titulo_sec_lay = QVBoxLayout(titulo_section)
        titulo_sec_lay.setContentsMargins(0, 0, 0, 0)
        titulo_sec_lay.setSpacing(4)
        titulo_sec_lay.addWidget(titulo_hdr)
        titulo_sec_lay.addWidget(titulo_wrap)
        titulo_section.setFocusProxy(self.title_grid)
        self._block_titulo = titulo_section   # mantiene compatibilidad con setVisible
        lay.addWidget(titulo_section)

        # ── Bajada ──
        self.ed_bajada = QPlainTextEdit()
        self.ed_bajada.setFixedHeight(80)
        self.ed_bajada.setPlaceholderText("Bajada...")
        self.cnt_bajada = CharCounter(mq.get("bajada_limit", 220), 50, self.ed_bajada)
        self._block_bajada = FieldBlock(
            "Bajada", _wrap(self.ed_bajada, self.cnt_bajada),
            header_widgets=self._make_ia_buttons("bajada"),
        )
        lay.addWidget(self._block_bajada)

        # ── Firma ──
        firma_row = QWidget()
        firma_lay = QHBoxLayout(firma_row)
        firma_lay.setContentsMargins(0, 0, 0, 0)
        firma_lay.setSpacing(8)
        self.chk_firma = QCheckBox("Incluir firma")
        self.chk_firma.setCursor(Qt.PointingHandCursor)
        self.ed_firma = QLineEdit()
        self.ed_firma.setPlaceholderText("Nombre del periodista...")
        firma_lay.addWidget(self.chk_firma)
        firma_lay.addWidget(self.ed_firma, 1)
        self._block_firma = FieldBlock("Firma", firma_row)
        lay.addWidget(self._block_firma)

        # ── Epígrafe (se oculta para noticias secundarias sin foto) ──
        self.ed_epigrafe = QLineEdit()
        self.ed_epigrafe.setPlaceholderText("Epígrafe de la foto principal...")
        self.cnt_epigrafe = CharCounter(mq.get("epigrafe_principal_limit", 120), 50, self.ed_epigrafe)
        # QLineEdit no permite resaltar sub-rangos → badge de campo completo.
        self._ia_epigrafe_badge = QLabel("✨ reescrito por IA")
        self._ia_epigrafe_badge.setVisible(False)
        self._ia_epigrafe_badge.setStyleSheet(
            "color: #7a6a00; background: rgba(255,220,0,0.28);"
            " border-radius: 6px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        self._block_epigrafe = FieldBlock(
            "Epígrafe", _wrap(self.ed_epigrafe, self.cnt_epigrafe),
            header_widgets=[*self._make_ia_buttons("epigrafe"), self._ia_epigrafe_badge],
        )
        # El epígrafe va FUERA del bloque colapsable: debe seguir visible cuando el
        # colapso oculta volanta/título/bajada/firma (pantallas chicas, 1366×768).
        outer.addWidget(self._block_epigrafe)

        # ── Cuerpo ──
        # QTextEdit (no QPlainTextEdit): QPlainTextEdit ignora el interlineado
        # (QPlainTextDocumentLayout no aplica QTextBlockFormat line-height).
        self.ed_cuerpo = QTextEdit()
        self.ed_cuerpo.setAcceptRichText(False)   # pegar como texto plano
        self.ed_cuerpo.setMinimumHeight(360)
        self.ed_cuerpo.setPlaceholderText("Cuerpo de la nota...")
        # manage_style=False: el tema de lectura (claro) lo controla _refresh_cuerpo_style,
        # no el contador (que dejaría el cuerpo en tema oscuro).
        self.cnt_cuerpo = CharCounter(0, 50, self.ed_cuerpo, manage_style=False)

        cuerpo_section = QWidget()
        cuerpo_sec_lay = QVBoxLayout(cuerpo_section)
        cuerpo_sec_lay.setContentsMargins(0, 0, 0, 0)
        cuerpo_sec_lay.setSpacing(4)
        cuerpo_hdr = QHBoxLayout()
        lbl_cuerpo = QLabel("Cuerpo")
        lbl_cuerpo.setProperty("fieldTitle", True)
        cuerpo_hdr.addWidget(lbl_cuerpo)
        for _b in self._make_ia_buttons("cuerpo"):
            cuerpo_hdr.addWidget(_b)
        cuerpo_hdr.addStretch(1)
        btn_expand = QPushButton("⊞")
        btn_expand.setFixedSize(56, 28)   # ⊞ más ancho (antes 28×28 quedaba angosto)
        btn_expand.setCursor(Qt.PointingHandCursor)
        btn_expand.setToolTip("Ver cuerpo ampliado")
        btn_expand.setStyleSheet(
            "QPushButton { font-size: 16px; color: #e2e8f0;"
            " background: rgba(255,255,255,0.08);"
            " border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; }"
            " QPushButton:hover { background: #e7885f; color: #ffffff; }"
        )
        btn_expand.clicked.connect(self._abrir_cuerpo_ampliado)
        cuerpo_hdr.addWidget(btn_expand)
        cuerpo_hdr.addWidget(self.cnt_cuerpo)
        cuerpo_sec_lay.addLayout(cuerpo_hdr)

        # Barra de visualización (tema de lectura: fuente, tamaño, colores, interlineado)
        self._body_toolbar = BodyDisplayToolbar(self._body_display)
        self._body_toolbar.changed.connect(self._on_body_toolbar_changed)
        cuerpo_sec_lay.addWidget(self._body_toolbar)

        cuerpo_sec_lay.addWidget(self.ed_cuerpo, 1)
        self._block_cuerpo = cuerpo_section
        outer.addWidget(self._block_cuerpo, 1)

        outer.addStretch(0)

        # Apply per-field font sizes from maqueta config
        self._apply_field_fonts(mq)

        # Tab navigation
        self._next_filter = NextFilter(self._go_next_field)
        for ed in (self.ed_volanta, self.ed_bajada, self.ed_epigrafe, self.ed_cuerpo):
            ed.installEventFilter(self._next_filter)
        self.title_grid.tab_pressed.connect(lambda: self._go_next_field(self.title_grid))

        # Internal signals
        self.ed_volanta.textChanged.connect(self._on_volanta_changed)
        self.title_grid.textChanged.connect(self._on_titulo_changed)
        self.ed_bajada.textChanged.connect(self._on_bajada_changed)
        self.chk_firma.toggled.connect(self._update_cuerpo_counter)
        self.ed_epigrafe.textChanged.connect(self._on_epigrafe_changed)
        self.ed_cuerpo.textChanged.connect(self._on_cuerpo_changed)

    # ── Colapso animado del bloque superior (estilo app-bar) ──

    def upper_collapsed(self) -> bool:
        return self._upper_collapsed

    def set_upper_collapsed(self, collapsed: bool):
        """Oculta/muestra animado (InOutCubic, ~260 ms) volanta/título/bajada/firma/epígrafe
        para que el cuerpo ocupe todo el panel."""
        if collapsed == self._upper_collapsed:
            return
        self._upper_collapsed = collapsed
        if self._upper_anim is not None:
            self._upper_anim.stop()
        inicio = self._upper.height()
        fin = 0 if collapsed else self._upper.sizeHint().height()
        anim = QPropertyAnimation(self._upper, b"maximumHeight", self)
        anim.setDuration(260)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.setStartValue(inicio)
        anim.setEndValue(fin)
        if not collapsed:
            # Al terminar de expandir, soltar el tope para que el layout respire normal.
            anim.finished.connect(lambda: self._upper.setMaximumHeight(16777215))
        anim.start()
        self._upper_anim = anim

    # ── Font application ──

    def _apply_field_fonts(self, mq: dict):
        pairs = [
            (self.cnt_volanta,  "volanta_font_size",  16),
            (self.cnt_bajada,   "bajada_font_size",   16),
            (self.cnt_epigrafe, "epigrafe_font_size", 16),
            (self.cnt_cuerpo,   "cuerpo_font_size",   16),
        ]
        for cnt, key, default in pairs:
            cnt.set_linked_font_size(int(mq.get(key, default)))

        title_size = int(mq.get("titulo_font_size", 16))
        self.title_grid.setStyleSheet(f"font-size: {title_size}px;")

        cfs = int(mq.get("counter_font_size", 11))
        self._cnt_titulo_fs = cfs
        self.cnt_volanta.set_font_size(cfs)
        self.cnt_bajada.set_font_size(cfs)
        self.cnt_epigrafe.set_font_size(cfs)
        self.cnt_cuerpo.set_font_size(cfs + 2)
        self._refresh_titulo_counter()

        # Sincroniza el tema de lectura del cuerpo con la maqueta (incluye el
        # tamaño que ajusta el diálogo "Visualización...").
        self._body_display = extract_settings(mq)
        if getattr(self, "_body_toolbar", None) is not None:
            self._body_toolbar.set_settings(self._body_display)
        self._apply_body_display()

    def _refresh_titulo_counter(self):
        fs = self._cnt_titulo_fs
        over = self._titulo_over
        if over:
            clr, bg, brd = "#ff6b6b", "rgba(255,100,100,0.12)", "#ff6b6b"
        else:
            clr, bg, brd = "rgba(255,255,255,0.45)", "rgba(255,255,255,0.04)", "rgba(255,255,255,0.20)"
        self.cnt_titulo.setStyleSheet(
            f"color: {clr}; font-size: {fs}px; font-weight: 600;"
            f" border: 1.5px solid {brd}; border-radius: 6px;"
            f" background: {bg}; padding: 4px;"
        )

    # ── Navigation ──

    def _go_next_field(self, current):
        order = [self.ed_volanta, self.title_grid]
        if self._block_bajada.isVisible():
            order.append(self.ed_bajada)
        if self._block_epigrafe.isVisible():
            order.append(self.ed_epigrafe)
        order.append(self.ed_cuerpo)
        try:
            idx = order.index(current)
        except ValueError:
            idx = 0
        order[(idx + 1) % len(order)].setFocus(Qt.TabFocusReason)

    # ── Slot handlers ──

    def _on_volanta_changed(self):
        self._maybe_clear_ia("volanta")
        self.cnt_volanta.update_count(self.ed_volanta.toPlainText())
        self.textChanged.emit()

    def _on_titulo_changed(self):
        cols = self.title_grid.cols
        lines = self.title_grid.get_lines()
        # Breves: el límite del título se cuenta SIN espacios (caracteres totales).
        _n = (lambda l: len(l.replace(" ", ""))) if self._titulo_sin_espacio else len
        parts = [
            f"L{i+1}: {_n(l)}/{cols}" + (" ⚠" if _n(l) > cols else "")
            for i, l in enumerate(lines)
            if i < self.title_grid.rows
        ]
        self._titulo_over = any(_n(l) > cols for l in lines[:self.title_grid.rows])
        self.cnt_titulo.setText("\n".join(parts))
        self._refresh_titulo_counter()
        self._maybe_clear_ia("titulo")
        self.textChanged.emit()

    def _on_bajada_changed(self):
        self._maybe_clear_ia("bajada")
        self.cnt_bajada.update_count(self.ed_bajada.toPlainText())
        self._update_cuerpo_counter()
        self.textChanged.emit()

    def _on_epigrafe_changed(self):
        self._maybe_clear_ia("epigrafe")
        self.cnt_epigrafe.update_count(self.ed_epigrafe.text())
        self.textChanged.emit()

    def _on_cuerpo_changed(self):
        self._maybe_clear_ia("cuerpo")
        self._update_cuerpo_counter()
        self.textChanged.emit()

    def limite_efectivo_cuerpo(self) -> int:
        """Límite efectivo del cuerpo (0 = sin límite): cuerpo_limit − bajada − firma −
        deducción externa − intertítulos (## → una línea extra cada uno). Fuente única de
        la fórmula: la usan el contador del cuerpo y el tab 'Contar caracteres'."""
        if self._cuerpo_box_limit <= 0:
            return 0
        raw = self.ed_cuerpo.toPlainText()
        n_inter = sum(1 for ln in raw.splitlines() if ln.strip().startswith("##"))
        bajada_len = len(self.ed_bajada.toPlainText().strip())
        firma_ded = self._firma_deduccion if self.chk_firma.isChecked() else 0
        return max(0, self._cuerpo_box_limit - bajada_len - firma_ded
                   - self._deduction_external - n_inter * self._intertitulo_deduccion)

    def _update_cuerpo_counter(self):
        """Recalcula el límite disponible para el cuerpo (ver limite_efectivo_cuerpo)."""
        raw = self.ed_cuerpo.toPlainText()
        cuerpo_text = raw.replace('\n', '')
        self.cnt_cuerpo.set_limit(self.limite_efectivo_cuerpo())
        self.cnt_cuerpo.update_count(cuerpo_text)
        self._refresh_cuerpo_style(self.cnt_cuerpo.state)

    # ── Visualización del cuerpo (tema de lectura) ──

    def _apply_body_display(self, state: str | None = None):
        """Aplica fuente, colores e interlineado al cuerpo integrado."""
        if state is None:
            state = getattr(self.cnt_cuerpo, "state", None)
        apply_body_display(self.ed_cuerpo, self._body_display, state)

    def _refresh_cuerpo_style(self, state: str | None):
        """Refresca solo el QSS del cuerpo (borde según llenado) sin tocar el documento."""
        self.ed_cuerpo.setStyleSheet(body_qss(self._body_display, state))

    def _on_body_toolbar_changed(self, settings: dict):
        """Cambio hecho en la barra de visualización integrada."""
        self._body_display = dict(settings)
        self._apply_body_display()
        self.body_display_changed.emit(dict(settings))

    def set_body_display(self, settings: dict):
        """Sincroniza ajustes de visualización venidos de afuera (otra noticia/diálogo)."""
        self._body_display = extract_settings(settings)
        if getattr(self, "_body_toolbar", None) is not None:
            self._body_toolbar.set_settings(self._body_display)
        self._apply_body_display()

    def set_external_deduction(self, amount: int) -> None:
        self._deduction_external = amount
        self._update_cuerpo_counter()

    # ── Public API ──

    def apply_limits(self, limits: dict):
        """Aplica límites de caracteres leídos de la maqueta."""
        if "volanta_limit" in limits:
            self.cnt_volanta.set_limit(limits["volanta_limit"])
            self.cnt_volanta.update_count(self.ed_volanta.toPlainText())
        if "epigrafe_principal_limit" in limits:
            self.cnt_epigrafe.set_limit(limits["epigrafe_principal_limit"])
            self.cnt_epigrafe.update_count(self.ed_epigrafe.text())

        tiene_epi = limits.get("tiene_epigrafe", True)
        self._block_epigrafe.setVisible(tiene_epi)

        tiene_baj = not limits.get("sin_bajada", False)
        self._block_bajada.setVisible(tiene_baj)

        if "cuerpo_limit" in limits:
            self._cuerpo_box_limit = limits["cuerpo_limit"]
            self._update_cuerpo_counter()

        self._titulo_sin_espacio = bool(limits.get("titulo_sin_espacio", False))
        titulo_lineas = limits.get("titulo_lineas", self.title_grid.rows)
        titulo_chars = limits.get("titulo_chars_linea", self.title_grid.cols)
        prev_cols, prev_rows = self.title_grid.cols, self.title_grid.rows
        self.title_grid.update_dims(titulo_chars, titulo_lineas)
        if titulo_chars != prev_cols or titulo_lineas != prev_rows:
            # .text() crudo (no get_lines(), que parte palabras por el corte duro de
            # columna) — set_text() ya normaliza saltos reales a espacio correctamente.
            self.title_grid.set_text(self.title_grid.text())
        self._titulo_lbl.setText(
            f"Título ({titulo_lineas} línea{'s' if titulo_lineas > 1 else ''} × {titulo_chars} chars)"
        )
        self._on_titulo_changed()

    # ── Tipo de noticia (secundaria / breve / etc.) ──

    @property
    def story_type(self) -> str:
        return self._story_type

    def set_story_types(self, types: list[str], current: str) -> None:
        """Configura el selector de tipo; muestra u oculta según cuántos tipos haya."""
        if self._type_cb is None:
            return
        has_choice = len(types) > 1
        self._type_lbl.setVisible(has_choice)
        self._type_cb.setVisible(has_choice)
        if has_choice:
            self._type_cb.blockSignals(True)
            self._type_cb.clear()
            self._type_cb.addItems(types)
            idx = self._type_cb.findText(current)
            self._type_cb.setCurrentIndex(max(0, idx))
            self._story_type = self._type_cb.currentText()
            self._type_cb.blockSignals(False)
        elif types:
            self._story_type = types[0]

    def _on_type_changed(self, new_type: str) -> None:
        if new_type and new_type != self._story_type:
            self._story_type = new_type
            self.story_type_changed.emit(new_type)

    # ==================================================================
    # Reescritura por IA (por campo) + preservación del original + diff
    # ==================================================================

    _IA_BTN_QSS = (
        "QPushButton { font-size: 13px; color: #f5c542;"
        " background: rgba(245,197,66,0.12);"
        " border: 1px solid rgba(245,197,66,0.35); border-radius: 6px; }"
        " QPushButton:hover { background: #f5c542; color: #1a2535; }"
        " QPushButton:disabled { color: rgba(245,197,66,0.35);"
        " border-color: rgba(245,197,66,0.15); }"
    )
    _IA_UNDO_QSS = (
        "QPushButton { font-size: 13px; color: #e2e8f0;"
        " background: rgba(255,255,255,0.08);"
        " border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; }"
        " QPushButton:hover { background: #e7885f; color: #ffffff; }"
    )

    def _make_ia_buttons(self, campo: str) -> list:
        """Crea (y registra) el botón ✨ (reescribir) y ↩ (deshacer IA) de un campo."""
        btn = QPushButton("✨")
        btn.setFixedSize(30, 26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(f"Reescribir {campo} con IA")
        btn.setStyleSheet(self._IA_BTN_QSS)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(lambda _=False, c=campo: self._reescribir_campo_ia(c))
        self._ia_btn[campo] = btn

        undo = QPushButton("↩")
        undo.setFixedSize(28, 26)
        undo.setCursor(Qt.PointingHandCursor)
        undo.setToolTip("Deshacer reescritura de IA (volver al original)")
        undo.setStyleSheet(self._IA_UNDO_QSS)
        undo.setFocusPolicy(Qt.NoFocus)
        undo.setVisible(False)
        undo.clicked.connect(lambda _=False, c=campo: self._deshacer_ia(c))
        self._ia_undo_btn[campo] = undo
        return [btn, undo]

    # ── mapeo campo → widget/texto/límite ──

    def _get_campo_text(self, campo: str) -> str:
        return {
            "volanta":  self.ed_volanta.toPlainText(),
            "titulo":   self.title_grid.text(),
            "bajada":   self.ed_bajada.toPlainText(),
            "epigrafe": self.ed_epigrafe.text(),
            "cuerpo":   self.ed_cuerpo.toPlainText(),
        }.get(campo, "")

    def _set_campo_text(self, campo: str, txt: str) -> None:
        if campo == "volanta":
            self.ed_volanta.setPlainText(txt)
        elif campo == "titulo":
            self.title_grid.set_text(txt)
        elif campo == "bajada":
            self.ed_bajada.setPlainText(txt)
        elif campo == "epigrafe":
            self.ed_epigrafe.setText(txt)
            self.ed_epigrafe.setCursorPosition(0)
        elif campo == "cuerpo":
            self.ed_cuerpo.setPlainText(_normalizar_cuerpo(txt))
            self._apply_body_display()

    def _get_campo_widget(self, campo: str):
        return {
            "volanta":  self.ed_volanta,
            "bajada":   self.ed_bajada,
            "cuerpo":   self.ed_cuerpo,
        }.get(campo)

    def _get_campo_limite(self, campo: str) -> int:
        if campo == "volanta":
            return self.cnt_volanta._limit
        if campo == "bajada":
            return self.cnt_bajada._limit
        if campo == "epigrafe":
            return self.cnt_epigrafe._limit
        if campo == "cuerpo":
            return self.limite_efectivo_cuerpo()
        if campo == "titulo":
            return self.title_grid.cols * self.title_grid.rows
        return 0

    def _build_ia_context(self) -> str:
        titulo = self.title_grid.text().strip()
        cuerpo = self.ed_cuerpo.toPlainText().strip()
        partes = []
        if titulo:
            partes.append(f"Título: {titulo}")
        if cuerpo:
            partes.append(f"Cuerpo: {cuerpo}")
        return "\n\n".join(partes)

    # ── ejecución de la reescritura ──

    def _reescribir_campo_ia(self, campo: str) -> None:
        texto = (self._get_campo_text(campo) or "").strip()
        if not texto:
            return
        try:
            from services.ia_service import AIRewriter
            rewriter = AIRewriter()
        except Exception as e:  # IAConfigError u otro
            self._ia_config_error(e)
            return

        limite = self._get_campo_limite(campo)
        contexto = self._build_ia_context() if campo != "cuerpo" else ""
        original = self._get_campo_text(campo)

        btn = self._ia_btn.get(campo)
        if btn:
            btn.setEnabled(False)
            btn.setText("…")
        self.ia_busy_changed.emit(True)

        from ui.ia_worker import IAWorker
        worker = IAWorker(rewriter.reescribir_campo, campo, texto, limite, contexto, parent=self)

        def _ok(nuevo, c=campo, orig=original, w=worker):
            self._aplicar_reescritura_campo(c, orig, nuevo)
            self._ia_finish(c, w)

        def _err(msg, c=campo, w=worker):
            QMessageBox.warning(self, "Error IA", f"No se pudo reescribir {c}:\n{msg}")
            self._ia_finish(c, w)

        worker.done.connect(_ok)
        worker.failed.connect(_err)
        self._ia_workers.append(worker)
        worker.start()

    def _ia_finish(self, campo: str, worker) -> None:
        btn = self._ia_btn.get(campo)
        if btn:
            btn.setEnabled(True)
            btn.setText("✨")
        try:
            self._ia_workers.remove(worker)
        except ValueError:
            pass
        self.ia_busy_changed.emit(bool(self._ia_workers))

    def _ia_config_error(self, err: Exception) -> None:
        resp = QMessageBox.question(
            self, "IA no configurada",
            f"{err}\n\n¿Querés configurar la API key de OpenAI ahora?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if resp == QMessageBox.Yes:
            self.ia_config_needed.emit()

    def _aplicar_reescritura_campo(self, campo: str, original: str, nuevo: str) -> None:
        nuevo = (nuevo or "").strip()
        if not nuevo or nuevo == original:
            return
        self._ia_original[campo] = original
        self._ia_suppress_clear = True
        try:
            self._set_campo_text(campo, nuevo)
        finally:
            self._ia_suppress_clear = False
        self._set_ia_highlight(campo, original)
        undo = self._ia_undo_btn.get(campo)
        if undo:
            undo.setVisible(True)
        self.textChanged.emit()

    def _set_ia_highlight(self, campo: str, original: str) -> None:
        from ui.widgets.ia_diff import diff_ranges, apply_text_edit_highlight
        if campo == "titulo":
            self.title_grid.set_ia_highlight(original)
        elif campo == "epigrafe":
            self._ia_epigrafe_badge.setVisible(True)
        else:
            widget = self._get_campo_widget(campo)
            if widget is not None:
                nuevo = self._get_campo_text(campo)
                apply_text_edit_highlight(widget, diff_ranges(original, nuevo))

    def _clear_ia_highlight(self, campo: str) -> None:
        from ui.widgets.ia_diff import clear_text_edit_highlight
        if campo == "titulo":
            self.title_grid.clear_ia_highlight()
        elif campo == "epigrafe":
            self._ia_epigrafe_badge.setVisible(False)
        else:
            widget = self._get_campo_widget(campo)
            if widget is not None:
                clear_text_edit_highlight(widget)

    def _maybe_clear_ia(self, campo: str) -> None:
        """Al editar a mano un campo reescrito, quita el resaltado y el botón deshacer."""
        if self._ia_suppress_clear:
            return
        if campo not in self._ia_original:
            # Aún así, el título podría tener highlight residual sin original registrado.
            if campo == "titulo" and self.title_grid.has_ia_highlight():
                self.title_grid.clear_ia_highlight()
            return
        self._clear_ia_highlight(campo)
        self._ia_original.pop(campo, None)
        undo = self._ia_undo_btn.get(campo)
        if undo:
            undo.setVisible(False)

    def _deshacer_ia(self, campo: str) -> None:
        original = self._ia_original.get(campo)
        if original is None:
            return
        self._ia_suppress_clear = True
        try:
            self._set_campo_text(campo, original)
            self._clear_ia_highlight(campo)
        finally:
            self._ia_suppress_clear = False
        self._ia_original.pop(campo, None)
        undo = self._ia_undo_btn.get(campo)
        if undo:
            undo.setVisible(False)
        self.textChanged.emit()

    # ── API para la reescritura de la NOTA COMPLETA (usada por el editor) ──

    def ia_datos_y_limites(self) -> tuple[dict, dict]:
        """Devuelve (datos, limites) de los campos con contenido, para
        reescribir_nota_completa()."""
        datos, limites = {}, {}
        for campo in ("volanta", "titulo", "bajada", "epigrafe", "cuerpo"):
            txt = (self._get_campo_text(campo) or "").strip()
            if not txt:
                continue
            # epígrafe/bajada ocultos por la maqueta no se reescriben
            if campo == "epigrafe" and not self._block_epigrafe.isVisibleTo(self):
                continue
            if campo == "bajada" and not self._block_bajada.isVisibleTo(self):
                continue
            datos[campo] = txt
            limites[campo] = self._get_campo_limite(campo)
        return datos, limites

    def apply_ia_full(self, result: dict) -> None:
        """Aplica el resultado de reescribir_nota_completa() a todos los campos,
        preservando el original y resaltando el diff en cada uno."""
        for campo, nuevo in (result or {}).items():
            original = self._get_campo_text(campo)
            self._aplicar_reescritura_campo(campo, original, nuevo)

    def has_content(self) -> bool:
        return bool((self._get_campo_text("cuerpo") or "").strip()
                    or (self.title_grid.text() or "").strip())

    def restore_ia_state(self, ia_original: dict) -> None:
        """Re-muestra el resaltado amarillo y el botón deshacer de los campos
        reescritos por IA al reabrir la nota (compara original vs texto actual)."""
        if not ia_original:
            return
        for campo, original in ia_original.items():
            if campo not in ("volanta", "titulo", "bajada", "epigrafe", "cuerpo"):
                continue
            actual = self._get_campo_text(campo)
            if not original or actual == original:
                continue
            self._ia_original[campo] = original
            self._set_ia_highlight(campo, original)
            undo = self._ia_undo_btn.get(campo)
            if undo:
                undo.setVisible(True)

    def load_from_dir(self, subdir: Path) -> bool:
        """Carga la nota desde el subdirectorio. JSON primero, TXT como fallback."""
        txt_files = [
            f for f in subdir.glob("*.txt")
            if not f.stem.startswith("original_")
        ] if subdir.exists() else []

        if not txt_files:
            return False

        self._txt_path = txt_files[0]
        base_name = self._txt_path.stem
        json_path = subdir / f"{base_name}.json"

        if json_path.exists():
            try:
                nota = json.loads(json_path.read_text(encoding="utf-8"))
                firma = nota.get("firma", "")
                self.ed_firma.setText(firma)
                self.chk_firma.setChecked(nota.get("firma_habilitada", bool(firma)))
                self.ed_volanta.setPlainText(nota.get("volanta", ""))
                self.title_grid.set_text(nota.get("titulo", ""))
                self.ed_bajada.setPlainText(nota.get("bajada", ""))
                self.ed_epigrafe.setText(nota.get("epigrafe", ""))
                self.ed_epigrafe.setCursorPosition(0)   # leer el epígrafe desde el inicio
                self.ed_cuerpo.setPlainText(_normalizar_cuerpo(nota.get("cuerpo", "")))
                self._apply_body_display()   # reaplica interlineado tras cargar texto
                self._update_cuerpo_counter()
                self.restore_ia_state(nota.get("ia_original") or {})
                return True
            except Exception:
                pass  # fallback a TXT

        # Fallback: TXT
        raw = self._txt_path.read_text(encoding="utf-8", errors="replace")
        parts = [p.strip() for p in raw.split("///")]
        while len(parts) < 6:
            parts.append("")
        volanta, titulo, bajada, firma, epigrafe, *resto = parts
        self.ed_firma.setText(firma)
        self.chk_firma.setChecked(bool(firma))
        self.ed_volanta.setPlainText(volanta)
        self.title_grid.set_text(titulo)
        self.ed_bajada.setPlainText(bajada)
        self.ed_epigrafe.setText(epigrafe)
        self.ed_epigrafe.setCursorPosition(0)   # leer el epígrafe desde el inicio
        self.ed_cuerpo.setPlainText(" /// ".join(resto))
        self._apply_body_display()   # reaplica interlineado tras cargar texto
        self._update_cuerpo_counter()
        return True

    def save_to_path(self, txt_path: Path):
        """Guarda al path dado, creando backup automáticamente."""
        original = txt_path.parent / f"original_{txt_path.name}"
        if not original.exists():
            try:
                original.write_text(
                    txt_path.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
            except Exception:
                pass

        # Texto crudo + split SOLO por Enters reales (no por el corte duro de columna
        # de get_lines(), que partía palabras a la mitad del salto y las volvía a unir
        # con un espacio espurio — ej. "llegar a" con la "a" cayendo en la fila
        # siguiente terminaba en "llegara"). Mismo patrón que editor_nota_window.py.
        titulo = " ".join(seg.strip() for seg in self.title_grid.text().split("\n") if seg.strip())
        contenido = " /// ".join([
            _normalizar_comillas(self.ed_volanta.toPlainText().strip()),
            _normalizar_comillas(titulo),
            _normalizar_comillas(self.ed_bajada.toPlainText().strip()),
            self.ed_firma.text().strip(),
            self.ed_epigrafe.text().strip(),
            _normalizar_comillas(self.ed_cuerpo.toPlainText().strip()),
        ])
        txt_path.write_text(contenido, encoding="utf-8")

    def _abrir_cuerpo_ampliado(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Cuerpo de la nota")
        dlg.resize(900, 680)
        dlg.setSizeGripEnabled(True)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(12, 12, 12, 8)

        toolbar = BodyDisplayToolbar(self._body_display, dlg)
        lay.addWidget(toolbar)

        ed = QTextEdit(dlg)
        ed.setAcceptRichText(False)
        ed.setPlainText(self.ed_cuerpo.toPlainText())
        lay.addWidget(ed)
        apply_body_display(ed, self._body_display)

        def _on_disp(settings):
            self._body_display = dict(settings)
            self._body_toolbar.set_settings(settings)   # mantiene en sync la barra integrada
            apply_body_display(ed, settings)
            self.body_display_changed.emit(dict(settings))
        toolbar.changed.connect(_on_disp)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec_() == QDialog.Accepted:
            self.ed_cuerpo.setPlainText(ed.toPlainText())
        # Refleja en el cuerpo integrado cualquier cambio de visualización del diálogo.
        self._apply_body_display()

    def get_data(self) -> dict:
        return {
            "volanta":          self.ed_volanta.toPlainText(),
            "titulo":           self.title_grid.text(),
            "bajada":           self.ed_bajada.toPlainText(),
            "epigrafe":         self.ed_epigrafe.text(),
            "cuerpo":           self.ed_cuerpo.toPlainText(),
            "firma":            self.ed_firma.text(),
            "firma_habilitada": self.chk_firma.isChecked(),
            "txt_path":         self._txt_path,
        }

    def set_data(self, data: dict):
        self.ed_volanta.setPlainText(data.get("volanta", ""))
        self.title_grid.set_text(data.get("titulo", ""))
        self.ed_bajada.setPlainText(data.get("bajada", ""))
        self.ed_epigrafe.setText(data.get("epigrafe", ""))
        self.ed_epigrafe.setCursorPosition(0)   # leer el epígrafe desde el inicio
        self.ed_cuerpo.setPlainText(_normalizar_cuerpo(data.get("cuerpo", "")))
        self.ed_firma.setText(data.get("firma", ""))
        self.chk_firma.setChecked(data.get("firma_habilitada", bool(data.get("firma", ""))))
        self._txt_path = data.get("txt_path")
        self._apply_body_display()   # reaplica interlineado tras cargar texto
        self._update_cuerpo_counter()
