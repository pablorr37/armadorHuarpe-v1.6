"""
CircleIconButton — botón redondo con ícono + texto debajo (y valor opcional),
con el mismo estilo del menú radial: naranja al hover, gris/deshabilitado, y un
estado "activo" (realce naranja persistente). Reutilizable en el selector de
fotos y en la fila de estado de página.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtGui import QIcon, QPixmap, QImage, qGray
from PyQt5.QtCore import Qt, QSize, pyqtSignal


def grayscale_pixmap(pm: QPixmap) -> QPixmap:
    """Copia en escala de grises del pixmap, preservando el alpha."""
    if pm is None or pm.isNull():
        return pm
    src = pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation) \
        if max(pm.width(), pm.height()) > 64 else pm
    img = src.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            g = qGray(c.red(), c.green(), c.blue())
            c.setRgb(g, g, g, c.alpha())
            img.setPixelColor(x, y, c)
    return QPixmap.fromImage(img)


class CircleIconButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, pixmap: QPixmap, titulo: str, valor: str = None,
                 icon_px: int = 30, reservar_valor: bool = False,
                 label_w: int = None, parent=None):
        super().__init__(parent)
        self._pm = pixmap
        self._icon_px = max(16, int(icon_px))
        self._enabled = True
        self._activo = False
        self._reservar_valor = bool(reservar_valor)
        self._btn_px = self._icon_px + 12
        # Escalado del TEXTO (no del ícono): tamaño de fuente base y ancho de label base.
        self._base_font_px = 10
        self._font_px = 10
        self._base_label_w = label_w

        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(2)

        # parent=self desde la creación: evita que setVisible(True) muestre un
        # QLabel parentless como ventana top-level (artefacto de "ventana chica").
        self._btn = QPushButton(self)
        self._btn.setIcon(QIcon(pixmap))
        self._btn.setIconSize(QSize(self._icon_px, self._icon_px))
        self._btn.setFixedSize(self._btn_px, self._btn_px)
        self._btn.clicked.connect(self.clicked)

        self._lbl = QLabel(titulo, self)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setWordWrap(True)
        if label_w:
            # Ancho fijo → todos los íconos quedan del mismo ancho y el word-wrap
            # reparte el texto en líneas, dejándolos alineados/equidistantes.
            self._lbl.setFixedWidth(int(label_w))

        self._val = QLabel(valor or "", self)
        self._val.setAlignment(Qt.AlignCenter)
        self._val.setWordWrap(True)
        self._val.setVisible(self._reservar_valor or bool(valor))

        v.addWidget(self._btn, 0, Qt.AlignHCenter)
        v.addWidget(self._lbl, 0, Qt.AlignHCenter)
        v.addWidget(self._val, 0, Qt.AlignHCenter)

        self._aplicar_estilos()

    # ── estilos ───────────────────────────────────────────────
    def _aplicar_estilos(self):
        # Mismo diseño que el menú radial: sin borde; hover/seleccionado = RELLENO
        # naranja (#e7885f). Seleccionado = relleno naranja persistente.
        r = self._btn_px // 2
        if not self._enabled:
            self._btn.setStyleSheet(
                "QPushButton{border:none;border-radius:%dpx;"
                "background:rgba(30,41,59,0.55);}" % r)
            self._btn.setCursor(Qt.ArrowCursor)
        elif self._activo:
            self._btn.setStyleSheet(
                "QPushButton{border:none;border-radius:%dpx;background:#e7885f;}"
                "QPushButton:hover{background:#e7885f;}" % r)
            self._btn.setCursor(Qt.PointingHandCursor)
        else:
            self._btn.setStyleSheet(
                "QPushButton{border:none;border-radius:%dpx;"
                "background:rgba(30,41,59,0.96);}"
                "QPushButton:hover{background:#e7885f;}" % r)
            self._btn.setCursor(Qt.PointingHandCursor)
        self._lbl.setStyleSheet(
            "color:%s; font-size:%dpx; font-weight:bold; background:transparent;"
            % (("#e2e8f0" if self._enabled else "#7b8694"), self._font_px))
        self._val.setStyleSheet(
            "color:#9fb0c3; font-size:%dpx; background:transparent;" % self._font_px)

    # ── API ───────────────────────────────────────────────────
    def escalar_label(self, scale: float):
        """Escala SOLO el texto (título + valor) y, si tenía, el ancho del label,
        proporcional al tamaño de pantalla. El ícono/botón no cambian de tamaño."""
        s = max(0.6, float(scale))
        self._font_px = max(9, round(self._base_font_px * s))
        if self._base_label_w:
            self._lbl.setFixedWidth(int(self._base_label_w * s))
        self._aplicar_estilos()

    def set_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._btn.setEnabled(enabled)
        self._btn.setIcon(QIcon(self._pm if enabled else grayscale_pixmap(self._pm)))
        self._aplicar_estilos()

    def set_activo(self, activo: bool):
        activo = bool(activo)
        if activo == self._activo:
            return
        self._activo = activo
        self._aplicar_estilos()
        self.update()

    def set_titulo(self, titulo: str):
        self._lbl.setText(titulo or "")

    def titulo(self) -> str:
        return self._lbl.text()

    def set_valor(self, valor: str):
        self._val.setText(valor or "")
        self._val.setVisible(self._reservar_valor or bool(valor))

    def set_pixmap(self, pm: QPixmap):
        self._pm = pm
        self._btn.setIcon(QIcon(pm if self._enabled else grayscale_pixmap(pm)))
