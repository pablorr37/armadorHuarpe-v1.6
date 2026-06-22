from __future__ import annotations
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel


class FieldBlock(QWidget):
    focus_next_requested = pyqtSignal()

    def __init__(self, title: str, editor: QWidget, parent=None):
        super().__init__(parent)
        self._editor = editor

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.lbl_title = QLabel(title)
        self.lbl_title.setProperty("fieldTitle", True)

        lay.addWidget(self.lbl_title)
        lay.addWidget(editor)

        self.setFocusProxy(editor)

    @property
    def editor(self) -> QWidget:
        return self._editor
