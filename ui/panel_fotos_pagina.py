# ui/panel_fotos_pagina.py
"""
PanelFotosPagina — panel colapsable que muestra la lista ordenada de fotos
seleccionadas para la página/subnoticia activa.

Solo emite señales; nunca toca disco ni llama al controller directamente.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from utils.app_logger import get_logger

_log = get_logger(__name__)


class PanelFotosPagina(QWidget):
    """
    Panel colapsable (QGroupBox) que lista las fotos seleccionadas para la
    página activa, con controles de reordenamiento y eliminación.

    Señales:
        mover_arriba(Path)  — pedir mover la foto un slot arriba.
        mover_abajo(Path)   — pedir mover la foto un slot abajo.
        quitar(Path)        — pedir quitar la foto de la selección.
    """

    mover_arriba = pyqtSignal(Path)
    mover_abajo  = pyqtSignal(Path)
    quitar       = pyqtSignal(Path)

    _STYLE_BTN = """
        QPushButton {
            background: #1e293b; color: #e2e8f0;
            border: 1px solid #334155; border-radius: 4px;
            padding: 2px 5px; font-size: 11px;
        }
        QPushButton:hover   { background: #334155; }
        QPushButton:pressed { background: #475569; }
        QPushButton:disabled { color: #4a5568; border-color: #2d3748; }
    """
    _STYLE_BTN_REMOVE = _STYLE_BTN + "QPushButton { color: #f87171; }"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._fotos: list[dict] = []
        self._last_foto_count: int = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.setSpacing(0)

        # QGroupBox colapsable: cuando está desmarcado oculta el contenido
        self.group = QGroupBox("Fotos de la página")
        self.group.setCheckable(True)
        self.group.setChecked(False)   # colapsado por defecto
        self.group.setStyleSheet("""
            QGroupBox {
                font-size: 11px; font-weight: bold;
                color: #94a3b8;
                border: 1px solid #334155; border-radius: 4px;
                margin-top: 6px; padding-top: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
            }
        """)
        self.group.toggled.connect(self._on_toggle)

        self._inner = QWidget()
        self._inner.setVisible(False)
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(4, 4, 4, 4)
        self._inner_layout.setSpacing(2)

        gl = QVBoxLayout(self.group)
        gl.setContentsMargins(4, 4, 4, 4)
        gl.addWidget(self._inner)

        outer.addWidget(self.group)

    # ── API pública ───────────────────────────────────────────────────────────

    def actualizar(self, fotos: list[dict]) -> None:
        """
        Reconstruye la lista visual a partir del estado actual.

        fotos: lista de dicts con claves {path, nombre, orden, rol}.
        """
        self._fotos = list(fotos)
        self._reconstruir_filas()
        n = len(fotos)
        titulo = f"Fotos de la página  ({n})" if n else "Fotos de la página"
        self.group.setTitle(titulo)
        if n != self._last_foto_count:
            _log.debug("PanelFotosPagina actualizado con %d foto(s).", n)
            self._last_foto_count = n

    def limpiar(self) -> None:
        """Vacía el panel."""
        self._fotos = []
        self._reconstruir_filas()
        self.group.setTitle("Fotos de la página")

    # ── Slots privados ────────────────────────────────────────────────────────

    def _on_toggle(self, checked: bool) -> None:
        self._inner.setVisible(checked)

    def _reconstruir_filas(self) -> None:
        # Eliminar widgets anteriores
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._fotos:
            lbl = QLabel("No hay fotos seleccionadas.")
            lbl.setStyleSheet("color: #64748b; font-size: 11px; padding: 4px;")
            self._inner_layout.addWidget(lbl)
            return

        for f in self._fotos:
            fila = self._crear_fila(f)
            self._inner_layout.addWidget(fila)
            # Separador fino entre filas
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #1e293b;")
            self._inner_layout.addWidget(sep)

    def _crear_fila(self, f: dict) -> QWidget:
        row = QWidget()
        outer_lay = QVBoxLayout(row)
        outer_lay.setContentsMargins(0, 2, 0, 2)
        outer_lay.setSpacing(2)

        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)

        # Número de orden (1-based) y rol
        rol_icon = "★" if f.get("rol") == "principal" else "·"
        lbl_orden = QLabel(f"[{f['orden'] + 1}] {rol_icon}")
        lbl_orden.setFixedWidth(38)
        lbl_orden.setStyleSheet("color: #94a3b8; font-size: 11px;")
        h.addWidget(lbl_orden)

        # Nombre (expandible, muestra path como tooltip)
        lbl_nombre = QLabel(f.get("nombre", ""))
        lbl_nombre.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lbl_nombre.setStyleSheet("font-size: 11px; color: #e2e8f0;")
        lbl_nombre.setToolTip(f.get("path", ""))
        lbl_nombre.setMaximumWidth(200)
        lbl_nombre.setWordWrap(False)
        h.addWidget(lbl_nombre)

        outer_lay.addLayout(h)

        total = len(self._fotos)
        path_obj = Path(f["path"])
        orden    = f["orden"]

        # Botón ↑ (subir)
        btn_up = QPushButton("↑")
        btn_up.setFixedSize(22, 22)
        btn_up.setStyleSheet(self._STYLE_BTN)
        btn_up.setEnabled(orden > 0)
        btn_up.setToolTip("Subir foto en el orden")
        btn_up.clicked.connect(lambda _, p=path_obj: self.mover_arriba.emit(p))
        h.addWidget(btn_up)

        # Botón ↓ (bajar)
        btn_dn = QPushButton("↓")
        btn_dn.setFixedSize(22, 22)
        btn_dn.setStyleSheet(self._STYLE_BTN)
        btn_dn.setEnabled(orden < total - 1)
        btn_dn.setToolTip("Bajar foto en el orden")
        btn_dn.clicked.connect(lambda _, p=path_obj: self.mover_abajo.emit(p))
        h.addWidget(btn_dn)

        # Botón ✕ (quitar)
        btn_rm = QPushButton("✕")
        btn_rm.setFixedSize(22, 22)
        btn_rm.setStyleSheet(self._STYLE_BTN_REMOVE)
        btn_rm.setToolTip("Quitar foto de la selección")
        btn_rm.clicked.connect(lambda _, p=path_obj: self.quitar.emit(p))
        h.addWidget(btn_rm)

        epi = f.get("epigrafe", "").strip()
        if epi:
            lbl_epi = QLabel(epi if len(epi) <= 80 else epi[:77] + "…")
            lbl_epi.setStyleSheet("color: rgba(255,255,255,0.40); font-size: 10px; padding-left: 38px;")
            lbl_epi.setToolTip(epi)
            lbl_epi.setWordWrap(False)
            outer_lay.addWidget(lbl_epi)

        return row
