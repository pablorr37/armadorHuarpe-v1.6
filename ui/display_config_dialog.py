from __future__ import annotations
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QSpinBox, QPushButton, QGroupBox,
)


class DisplayConfigDialog(QDialog):
    """
    Configuración de visualización del editor de noticias.
    Agrupa preferencias de apariencia que no dependen de la maqueta.
    """

    def __init__(self, current: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Visualización del editor")
        self.setModal(True)
        self.setMinimumWidth(400)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(QLabel(
            "Preferencias de apariencia del editor.\n"
            "Los cambios se aplican inmediatamente al guardar."
        ))

        def _sb(key, default, parent_form):
            sb = QSpinBox()
            sb.setMinimum(8)
            sb.setMaximum(36)
            sb.setSuffix(" px")
            sb.setValue(int(current.get(key, default)))
            return sb

        group = QGroupBox("Tamaño de fuente por campo")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        self._sb_font        = _sb("editor_font_size",   13, form)
        self._sb_cuerpo      = _sb("cuerpo_font_size",   16, form)
        self._sb_volanta     = _sb("volanta_font_size",  16, form)
        self._sb_bajada      = _sb("bajada_font_size",   16, form)
        self._sb_epigrafe    = _sb("epigrafe_font_size", 16, form)
        self._sb_titulo      = _sb("titulo_font_size",   16, form)
        self._sb_counter     = _sb("counter_font_size",  11, form)

        form.addRow("Fuente general (UI):", self._sb_font)
        form.addRow("Cuerpo:", self._sb_cuerpo)
        form.addRow("Volanta:", self._sb_volanta)
        form.addRow("Bajada:", self._sb_bajada)
        form.addRow("Epígrafe:", self._sb_epigrafe)
        form.addRow("Editor de título:", self._sb_titulo)
        form.addRow("Contadores de caracteres:", self._sb_counter)

        root.addWidget(group)

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
        return {
            "editor_font_size":   self._sb_font.value(),
            "cuerpo_font_size":   self._sb_cuerpo.value(),
            "volanta_font_size":  self._sb_volanta.value(),
            "bajada_font_size":   self._sb_bajada.value(),
            "epigrafe_font_size": self._sb_epigrafe.value(),
            "titulo_font_size":   self._sb_titulo.value(),
            "counter_font_size":  self._sb_counter.value(),
        }
