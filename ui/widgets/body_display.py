"""
Visualización del cuerpo de la nota (tema de lectura).

Estos helpers cambian SOLO cómo se ve el editor del cuerpo (fondo hueso, texto
gris oscuro, fuente tipo Roboto Slab / Cambria, interlineado). No alteran el
texto guardado: el .txt sigue siendo texto plano.

`BodyDisplayToolbar` es la "barra de visualización" reutilizable que se inserta
sobre el cuerpo integrado y en el cuerpo ampliado.
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QTextBlockFormat
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSpinBox, QDoubleSpinBox,
)

# Realce de llenado del cuerpo en tema claro: en vez de teñir el fondo (que
# rompería la lectura) usamos un borde de color según el nivel de ocupación.
_STATE_BORDER = {
    "short":  "#e08a4e",
    "medium": "#d0a838",
    "near":   "#c2b840",
    "good":   "#5aa878",
    "over":   "#e25656",
}
_NEUTRAL_BORDER = "#cdc3ad"

# Defaults del tema de lectura (coinciden con los de config.maqueta_config).
DEFAULTS = {
    "cuerpo_font_family":  "Cambria",
    "cuerpo_font_size":    16,
    "cuerpo_text_color":   "#2b2b2b",
    "cuerpo_bg_color":     "#f4efe4",
    "cuerpo_line_spacing": 118,
}

DISPLAY_KEYS = tuple(DEFAULTS.keys())


def extract_settings(mq: dict) -> dict:
    """Toma del dict de maqueta solo las claves de visualización del cuerpo."""
    out = dict(DEFAULTS)
    for k in DISPLAY_KEYS:
        if k in mq and mq[k] not in (None, ""):
            out[k] = mq[k]
    out["cuerpo_font_size"] = int(out["cuerpo_font_size"])
    out["cuerpo_line_spacing"] = int(out["cuerpo_line_spacing"])
    return out


def body_qss(settings: dict, state: str | None = None) -> str:
    # La fuente (familia/tamaño) la fija setFont en apply_body_display (fuente
    # única de verdad, así fontMetrics queda correcto). Acá solo color/borde.
    bg = settings.get("cuerpo_bg_color", DEFAULTS["cuerpo_bg_color"])
    fg = settings.get("cuerpo_text_color", DEFAULTS["cuerpo_text_color"])
    border = _STATE_BORDER.get(state, _NEUTRAL_BORDER)
    return (
        "QPlainTextEdit {"
        f" background: {bg};"
        f" color: {fg};"
        f" border: 2px solid {border};"
        " border-radius: 8px;"
        " padding: 10px;"
        " selection-background-color: #b9d6f2;"
        " selection-color: #1a1a1a;"
        "}"
    )


def apply_line_spacing(editor, percent: int) -> None:
    """Aplica interlineado proporcional a todo el documento.

    NO bloquea las señales del documento: el QPlainTextDocumentLayout necesita la
    notificación del cambio para recalcular y repintar en vivo (fuente + interlineado).
    Un guard de re-entrancia evita un eventual bucle (hoy el camino por tecla no
    reentra acá: _on_cuerpo_changed → _update_cuerpo_counter → _refresh_cuerpo_style)."""
    if getattr(editor, "_armh_applying_ls", False):
        return
    editor._armh_applying_ls = True
    try:
        doc = editor.document()
        cur = QTextCursor(doc)
        cur.select(QTextCursor.Document)
        bf = QTextBlockFormat()
        bf.setLineHeight(float(percent), QTextBlockFormat.ProportionalHeight)
        cur.mergeBlockFormat(bf)
    finally:
        editor._armh_applying_ls = False


def apply_body_display(editor, settings: dict, state: str | None = None) -> None:
    """Aplica fuente + estilo + interlineado al editor del cuerpo."""
    fam = settings.get("cuerpo_font_family", DEFAULTS["cuerpo_font_family"])
    size = int(settings.get("cuerpo_font_size", DEFAULTS["cuerpo_font_size"]))
    f = QFont(fam)
    f.setPixelSize(size)
    editor.setFont(f)
    editor.setStyleSheet(body_qss(settings, state))
    apply_line_spacing(editor, int(settings.get("cuerpo_line_spacing", DEFAULTS["cuerpo_line_spacing"])))


class BodyDisplayToolbar(QWidget):
    """Barra compacta del cuerpo: tamaño de fuente · interlineado.

    Emite `changed(dict)` con el set completo de ajustes en cada edición.
    La familia y los colores quedan fijos en los valores persistidos.
    """
    changed = pyqtSignal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = extract_settings(settings)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lbl_size = QLabel("Tamaño de fuente:")
        lbl_size.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 11px;")
        lay.addWidget(lbl_size)

        self._sb_size = QSpinBox()
        self._sb_size.setRange(8, 48)
        self._sb_size.setToolTip("Tamaño de fuente del cuerpo")
        self._sb_size.setValue(int(self._settings["cuerpo_font_size"]))
        self._sb_size.valueChanged.connect(lambda _: self._emit())
        lay.addWidget(self._sb_size)

        lay.addSpacing(14)

        lbl_ls = QLabel("Interlineado")
        lbl_ls.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 11px;")
        lay.addWidget(lbl_ls)

        self._sb_ls = QDoubleSpinBox()
        self._sb_ls.setRange(1.0, 3.0)
        self._sb_ls.setSingleStep(0.05)
        self._sb_ls.setDecimals(2)
        self._sb_ls.setToolTip("Interlineado del cuerpo")
        self._sb_ls.setValue(int(self._settings["cuerpo_line_spacing"]) / 100.0)
        self._sb_ls.valueChanged.connect(lambda _: self._emit())
        lay.addWidget(self._sb_ls)

        lay.addStretch(1)

    def _emit(self) -> None:
        # Solo tamaño e interlineado; familia/colores se conservan de self._settings.
        self._settings["cuerpo_font_size"] = self._sb_size.value()
        self._settings["cuerpo_line_spacing"] = int(round(self._sb_ls.value() * 100))
        self.changed.emit(dict(self._settings))

    # ── API ───────────────────────────────────────────────────
    def current(self) -> dict:
        return dict(self._settings)

    def set_settings(self, settings: dict) -> None:
        """Refleja ajustes externos en los controles sin re-emitir."""
        s = extract_settings(settings)
        self._settings = s
        for w in (self._sb_size, self._sb_ls):
            w.blockSignals(True)
        self._sb_size.setValue(int(s["cuerpo_font_size"]))
        self._sb_ls.setValue(int(s["cuerpo_line_spacing"]) / 100.0)
        for w in (self._sb_size, self._sb_ls):
            w.blockSignals(False)
