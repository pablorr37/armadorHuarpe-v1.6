from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QInputDialog, QDialogButtonBox,
)
from PyQt5.QtCore import pyqtSignal

from config.config import config_global


class SeccionesConfigDialog(QDialog):
    secciones_guardadas = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar secciones")
        self.setMinimumWidth(340)
        self._build_ui()
        self._cargar(config_global.secciones)

    def _build_ui(self):
        lay = QVBoxLayout(self)

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
        txt, ok = QInputDialog.getText(self, "Nueva sección", "Nombre:")
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
        config_global.save_secciones(lista)
        self.secciones_guardadas.emit(lista)
        self.accept()
