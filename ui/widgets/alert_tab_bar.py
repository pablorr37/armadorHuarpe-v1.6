"""AlertTabBar — QTabBar con estado de alerta por pestaña.

Una pestaña "alertada" muestra el ícono alerta.png, texto y borde naranja acentuado
con fondo naranja translúcido, y un tooltip explicativo. `shake()` la sacude
levemente de izquierda a derecha (efecto de atención, amortiguado).

AlertTabWidget es un QTabWidget que instala este tab bar (setTabBar es protected:
solo accesible desde una subclase).
"""
from __future__ import annotations

import math

from PyQt5.QtCore import QSize, QVariantAnimation
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen
from PyQt5.QtWidgets import QTabBar, QTabWidget

_NARANJA_TEXTO = QColor("#ff8c42")
_NARANJA_BORDE = QColor("#ff7a26")   # más acentuado
_NARANJA_FONDO = QColor(255, 140, 66, 36)


class AlertTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Sin la línea "base" que el estilo nativo dibuja bajo las pestañas
        # (se ve como una línea blanca molesta sobre el tema oscuro).
        self.setDrawBase(False)
        self._alerts: dict[int, str] = {}   # idx -> tooltip
        self._shake_dx = 0.0
        self._shake_anim = None
        self._icon_alerta: QIcon | None = None
        self._color_texto_default = None    # se captura al setear la primera alerta

    def set_alert(self, idx: int, tooltip: str | None, icon_path: str = ""):
        """Activa (tooltip no vacío) o limpia (None/"") la alerta de la pestaña `idx`."""
        if tooltip:
            if self._color_texto_default is None:
                self._color_texto_default = self.tabTextColor(idx)
            if self._icon_alerta is None and icon_path:
                self._icon_alerta = QIcon(icon_path)
            if self._icon_alerta is not None:
                # Chico para no estirar la pestaña.
                self.setIconSize(QSize(14, 14))
                self.setTabIcon(idx, self._icon_alerta)
            self.setTabTextColor(idx, _NARANJA_TEXTO)
            self.setTabToolTip(idx, tooltip)
            self._alerts[idx] = tooltip
        else:
            self.setTabIcon(idx, QIcon())
            if self._color_texto_default is not None:
                self.setTabTextColor(idx, self._color_texto_default)
            self.setTabToolTip(idx, "")
            self._alerts.pop(idx, None)
        self.update()

    def has_alert(self, idx: int) -> bool:
        return idx in self._alerts

    def shake(self, idx: int):
        """Sacudida horizontal leve (±4 px, 3 ciclos amortiguados, ~320 ms)."""
        if idx not in self._alerts:
            return
        if self._shake_anim is not None:
            self._shake_anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(320)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _tick(t):
            self._shake_dx = 4.0 * math.sin(t * 3 * 2 * math.pi) * (1.0 - t)
            self.update()

        def _fin():
            self._shake_dx = 0.0
            self.update()

        anim.valueChanged.connect(_tick)
        anim.finished.connect(_fin)
        self._shake_anim = anim
        anim.start()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self._alerts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        for idx in self._alerts:
            r = self.tabRect(idx).adjusted(1, 2, -2, -2)
            if self._shake_dx:
                r.translate(int(round(self._shake_dx)), 0)
            p.setBrush(_NARANJA_FONDO)
            p.setPen(QPen(_NARANJA_BORDE, 2))
            p.drawRoundedRect(r, 5, 5)
        p.end()


class AlertTabWidget(QTabWidget):
    """QTabWidget con AlertTabBar instalado. Exponer `alert_bar` para set_alert/shake."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.alert_bar = AlertTabBar(self)
        self.setTabBar(self.alert_bar)
