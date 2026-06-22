from __future__ import annotations
from PyQt5.QtCore import QObject, QPropertyAnimation, QEasingCurve


class SmoothScroll(QObject):
    def __init__(self, scrollbar, parent=None):
        super().__init__(parent)
        self.scrollbar = scrollbar
        self.anim = QPropertyAnimation(self.scrollbar, b"value", self)
        self.anim.setDuration(200)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)

    def scroll_to(self, value: int):
        self.anim.stop()
        self.anim.setStartValue(self.scrollbar.value())
        self.anim.setEndValue(value)
        self.anim.start()
