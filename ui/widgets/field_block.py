from __future__ import annotations
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel


class FieldBlock(QWidget):
    focus_next_requested = pyqtSignal()

    def __init__(self, title: str, editor: QWidget, parent=None, header_widgets=None):
        """
        header_widgets: lista opcional de QWidget que se ubican en la fila del
        título, arriba-a-la-izquierda del editor (p. ej. el botón de IA).
        """
        super().__init__(parent)
        self._editor = editor

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.lbl_title = QLabel(title)
        self.lbl_title.setProperty("fieldTitle", True)

        if header_widgets:
            hdr = QHBoxLayout()
            hdr.setContentsMargins(0, 0, 0, 0)
            hdr.setSpacing(6)
            hdr.addWidget(self.lbl_title)
            for w in header_widgets:
                hdr.addWidget(w)
            hdr.addStretch(1)
            lay.addLayout(hdr)
        else:
            lay.addWidget(self.lbl_title)
        lay.addWidget(editor)

        self.setFocusProxy(editor)

    @property
    def editor(self) -> QWidget:
        return self._editor
