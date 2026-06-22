from __future__ import annotations
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QPushButton, QGroupBox, QTabWidget, QWidget,
    QScrollArea, QSizePolicy,
)


# ── Pestaña 1: Campos de texto ────────────────────────────────────────────────
_CAMPOS_TEXTO = [
    ("cuerpo_limit",             "Cuerpo — capacidad (chars)",        0, 9999),
    ("volanta_limit",            "Volanta (chars)",                   1,  999),
    ("bajada_limit",             "Bajada (chars)",                    1,  999),
    ("titulo_lineas",            "Título — líneas",                   1,    4),
    ("titulo_chars_linea",       "Título — chars por línea",         10,   99),
    ("epigrafe_principal_limit", "Epígrafe principal (chars)",        1,  999),
    ("cuerpo_warning_margin",    "Cuerpo — margen de aviso (chars)",  0,  999),
]

# ── Pestaña 2: Textuales ──────────────────────────────────────────────────────
_LIMITES_TEXTUAL = [
    ("textual_sin_foto_limit", "Textual sin foto (chars)",    1, 999),
    ("textual_con_foto_limit", "Textual con foto (chars)",    1, 999),
    ("textual_epigrafe_limit", "Textual — epígrafe (chars)",  1, 999),
    ("dato_limit",             "Dato destacado (chars)",       1, 999),
]

_DESCUENTOS_TEXTUAL = [
    ("textual_simple_base",        "Simple — base (chars fijos)",          0, 9999),
    ("textual_simple_umbral",      "Simple — penaliza a partir de",        0,  999),
    ("textual_x2_base",            "x2 — base (chars fijos)",              0, 9999),
    ("textual_x2_umbral",          "x2 — penaliza a partir de",            0,  999),
    ("textual_x3_base",            "x3 — base (chars fijos)",              0, 9999),
    ("textual_x3_umbral",          "x3 — penaliza a partir de",            0,  999),
    ("textual_con_foto_base",      "Con foto — base (chars fijos)",        0, 9999),
    ("textual_con_foto_umbral",    "Con foto — penaliza a partir de",      0,  999),
    ("textual_con_foto_xl_base",   "Con foto XL — base (chars fijos)",     0, 9999),
    ("textual_con_foto_xl_umbral", "Con foto XL — penaliza a partir de",   0,  999),
]

# ── Pestaña 3: Recursos ───────────────────────────────────────────────────────
_DESCUENTOS_FIJOS = [
    ("firma_deduccion",      "Firma (si está habilitada)",  0, 999),
    ("qr_deduccion",         "QR",                          0, 999),
    ("foto_3wide_deduccion", "Foto 3 col. wide",            0, 999),
    ("foto_3ancha_deduccion","Foto 3 col. ancha",           0, 999),
]

_DESCUENTOS_DATO = [
    ("dato_base",   "Base (chars fijos)",       0, 999),
    ("dato_umbral", "Penaliza a partir de",     0, 999),
]

_DESCUENTOS_NUMERO = [
    ("numero_base",   "Base (chars fijos)",     0, 999),
    ("numero_umbral", "Penaliza a partir de",   0, 999),
]


def _make_form(fields: list, current: dict, spinboxes: dict) -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight)
    form.setSpacing(8)
    for key, label, mn, mx in fields:
        sb = QSpinBox()
        sb.setMinimum(mn)
        sb.setMaximum(mx)
        sb.setValue(int(current.get(key, mn)))
        form.addRow(label + ":", sb)
        spinboxes[key] = sb
    return form


def _scrollable_tab(inner: QWidget) -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(inner)
    wrapper = QWidget()
    lay = QVBoxLayout(wrapper)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(scroll)
    return wrapper


class MaquetaConfigDialog(QDialog):
    """Diálogo para calibrar manualmente todos los límites y descuentos de la maqueta."""

    def __init__(self, current: dict, parent=None, nombre: str = ""):
        super().__init__(parent)
        self.setWindowTitle(
            f"Límites de maqueta — {nombre}" if nombre else "Configuración de maqueta"
        )
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setMinimumHeight(500)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(QLabel(
            "Calibrá manualmente los límites de caracteres y los descuentos por recurso.\n"
            "Los valores se guardan en config.ini y se aplican en el editor."
        ))

        self._spinboxes: dict[str, QSpinBox] = {}
        tabs = QTabWidget()

        # ── Tab 1: Campos de texto ────────────────────────────────────────────
        tab1_inner = QWidget()
        t1_lay = QVBoxLayout(tab1_inner)
        t1_lay.setContentsMargins(8, 8, 8, 8)
        t1_lay.setSpacing(8)
        note1 = QLabel(
            "Capacidad máxima de cada campo de texto.\n"
            "Cuerpo en 0 = sin límite (el contador muestra solo el total, sin color de advertencia)."
        )
        note1.setWordWrap(True)
        note1.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 11px;")
        t1_lay.addWidget(note1)
        grp1 = QGroupBox()
        grp1.setLayout(_make_form(_CAMPOS_TEXTO, current, self._spinboxes))
        t1_lay.addWidget(grp1)
        t1_lay.addStretch(1)
        tabs.addTab(_scrollable_tab(tab1_inner), "Campos de texto")

        # ── Tab 2: Textuales ──────────────────────────────────────────────────
        tab2_inner = QWidget()
        t2_lay = QVBoxLayout(tab2_inner)
        t2_lay.setContentsMargins(8, 8, 8, 8)
        t2_lay.setSpacing(8)
        note2 = QLabel(
            "Límites de extensión de cada textual/dato.\n"
            "Descuento al cuerpo = Base + 1 char extra por cada char que supere el punto de corte."
        )
        note2.setWordWrap(True)
        note2.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 11px;")
        t2_lay.addWidget(note2)
        grp2a = QGroupBox("Límites de extensión")
        grp2a.setLayout(_make_form(_LIMITES_TEXTUAL, current, self._spinboxes))
        t2_lay.addWidget(grp2a)
        grp2b = QGroupBox("Descuentos al cuerpo por tipo de textual")
        grp2b.setLayout(_make_form(_DESCUENTOS_TEXTUAL, current, self._spinboxes))
        t2_lay.addWidget(grp2b)
        t2_lay.addStretch(1)
        tabs.addTab(_scrollable_tab(tab2_inner), "Textuales")

        # ── Tab 3: Recursos ───────────────────────────────────────────────────
        tab3_inner = QWidget()
        t3_lay = QVBoxLayout(tab3_inner)
        t3_lay.setContentsMargins(8, 8, 8, 8)
        t3_lay.setSpacing(8)
        grp3a = QGroupBox("Descuentos fijos al cuerpo")
        grp3a.setLayout(_make_form(_DESCUENTOS_FIJOS, current, self._spinboxes))
        t3_lay.addWidget(grp3a)
        grp3b = QGroupBox("Dato destacado")
        grp3b.setLayout(_make_form(_DESCUENTOS_DATO, current, self._spinboxes))
        t3_lay.addWidget(grp3b)
        grp3c = QGroupBox("Número destacado")
        grp3c.setLayout(_make_form(_DESCUENTOS_NUMERO, current, self._spinboxes))
        t3_lay.addWidget(grp3c)
        grp3d = QGroupBox("Cajas de imagen (nombre exacto en Quark)")
        form3d = QFormLayout()
        form3d.setLabelAlignment(Qt.AlignRight)
        form3d.setSpacing(8)
        self._le_foto_box = QLineEdit(str(current.get("foto_box_principal", "Box369")))
        form3d.addRow("Foto principal:", self._le_foto_box)
        grp3d.setLayout(form3d)
        t3_lay.addWidget(grp3d)
        t3_lay.addStretch(1)
        tabs.addTab(_scrollable_tab(tab3_inner), "Recursos")

        root.addWidget(tabs, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_ok = QPushButton("Guardar")
        btn_ok.setDefault(True)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_ok.setCursor(Qt.PointingHandCursor)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self.accept)

    def get_result(self) -> dict:
        result = {key: sb.value() for key, sb in self._spinboxes.items()}
        result["foto_box_principal"] = self._le_foto_box.text().strip() or "Box369"
        return result
