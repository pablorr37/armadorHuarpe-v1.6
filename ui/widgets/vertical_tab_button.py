"""
VerticalTabButton — solapa angosta con texto vertical (de abajo hacia arriba),
estilo del menú radial (hover naranja). Usada para plegar/desplegar paneles.
"""
from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import QPainter, QColor, QFont
from PyQt5.QtCore import Qt, pyqtSignal, QSize


class VerticalTabButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, texto: str = "Info de noticia", ancho: int = 26, parent=None):
        super().__init__(parent)
        self._texto = texto
        self._ancho = int(ancho)
        self._hover = False
        self._expandido = False
        self.setFixedWidth(self._ancho)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QSize(self._ancho, 120)

    def set_expandido(self, expandido: bool):
        self._expandido = bool(expandido)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Fondo (hover naranja, estilo radial)
        bg = QColor("#e7885f") if self._hover else QColor(30, 41, 59)
        p.setBrush(bg)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, w, h, 6, 6)

        # Texto vertical de abajo hacia arriba
        flecha = "«" if self._expandido else "»"
        texto = f"{flecha}  {self._texto}"
        p.setPen(QColor("#ffffff") if self._hover else QColor("#e2e8f0"))
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.save()
        # Origen abajo-centro, rotar -90 → el texto sube
        p.translate(w / 2 + 4, h - 8)
        p.rotate(-90)
        p.drawText(0, 0, texto)
        p.restore()
        p.end()
