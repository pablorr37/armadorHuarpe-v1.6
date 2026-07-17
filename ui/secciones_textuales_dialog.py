from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QLabel,
    QPushButton, QInputDialog, QDialogButtonBox,
)
from PyQt5.QtCore import pyqtSignal

from config.config import config_global


class SeccionesTextualesDialog(QDialog):
    """Secciones ESPECIALES: aquellas cuyos textuales se extraen del bloque 'Textuales' de la
    nota del manager (hoy Café de la Política), en vez de tomar todos los blockquotes.
    Escalable: agregar el nombre de la sección tal cual aparece en el manager."""

    secciones_guardadas = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Secciones especiales (textuales)")
        self.setMinimumWidth(360)
        self._build_ui()
        self._cargar(config_global.secciones_textuales)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Secciones cuyos textuales se toman del bloque «Textuales» de la nota\n"
            "(el resto usa la detección general de citas)."))

        self._lista = QListWidget()
        lay.addWidget(self._lista)

        btns = QHBoxLayout()
        for label, slot in [("Agregar", self._agregar), ("Eliminar", self._eliminar)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        lay.addLayout(btns)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._guardar)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _cargar(self, items: list):
        self._lista.clear()
        self._lista.addItems(sorted(items, key=str.casefold))

    def _agregar(self):
        txt, ok = QInputDialog.getText(self, "Nueva sección especial", "Nombre (como en el manager):")
        if ok and txt.strip():
            existing = [self._lista.item(i).text() for i in range(self._lista.count())]
            if txt.strip() not in existing:
                existing.append(txt.strip())
                self._cargar(existing)

    def _eliminar(self):
        for item in self._lista.selectedItems():
            self._lista.takeItem(self._lista.row(item))

    def _guardar(self):
        lista = sorted(
            (self._lista.item(i).text() for i in range(self._lista.count())),
            key=str.casefold,
        )
        config_global.save_secciones_textuales(lista)
        self.secciones_guardadas.emit(lista)
        self.accept()
