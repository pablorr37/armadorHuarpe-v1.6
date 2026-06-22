from __future__ import annotations
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QTabWidget


class RightPanel(QWidget):
    def __init__(self, parent=None, expanded_width: int = 420):
        super().__init__(parent)
        self._expanded_width = expanded_width
        self._collapsed = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Rail fijo
        self.rail = QWidget(self)
        self.rail.setFixedWidth(32)
        rail_lay = QVBoxLayout(self.rail)
        rail_lay.setContentsMargins(4, 8, 4, 8)
        rail_lay.setSpacing(0)

        self.btn_toggle = QPushButton("‹", self.rail)
        self.btn_toggle.setFixedSize(24, 36)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle)
        rail_lay.addWidget(self.btn_toggle, alignment=Qt.AlignTop)
        rail_lay.addStretch(1)

        # Contenido animable
        self.content = QWidget(self)
        self.content.setMaximumWidth(self._expanded_width)
        self.content.setMinimumWidth(0)

        content_lay = QVBoxLayout(self.content)
        content_lay.setContentsMargins(8, 8, 8, 8)

        self.tabs = QTabWidget(self.content)
        content_lay.addWidget(self.tabs)

        root.addWidget(self.rail)
        root.addWidget(self.content)

        self.anim = QPropertyAnimation(self.content, b"maximumWidth", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)

    def toggle(self):
        self.anim.stop()
        if self._collapsed:
            self.btn_toggle.setText("‹")
            self.anim.setStartValue(self.content.maximumWidth())
            self.anim.setEndValue(self._expanded_width)
            self._collapsed = False
        else:
            self.btn_toggle.setText("›")
            self.anim.setStartValue(self.content.maximumWidth())
            self.anim.setEndValue(0)
            self._collapsed = True
        self.anim.start()

    def is_collapsed(self) -> bool:
        return self._collapsed
