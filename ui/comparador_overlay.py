"""ComparadorOverlay — superpone la captura del origen (A) semitransparente sobre la
pantalla para verificar/afinar manualmente dónde quedó el recurso (posición B).

Se usa en la pasada de calibración de agarre: cv2 propone B automáticamente; este overlay
muestra el recorte de A encima de esa posición y el usuario lo arrastra hasta que calce
exactamente con el recurso real. Al confirmar devuelve el CENTRO (x, y) en coords globales.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QDialog, QLabel, QPushButton, QHBoxLayout, QApplication, QGraphicsOpacityEffect,
)

_log = logging.getLogger(__name__)

_ACENTO = "#e7885f"
_PANEL_BG = "#1e293b"


def bgr_a_qpixmap(bgr: np.ndarray) -> QPixmap:
    """Convierte una imagen OpenCV BGR a QPixmap."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())


class _Arrastrable(QLabel):
    """Recorte de A, semitransparente y arrastrable con el mouse."""

    def __init__(self, pixmap: QPixmap, parent):
        super().__init__(parent)
        self.setPixmap(pixmap)
        self.resize(pixmap.size())
        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(0.55)
        self.setGraphicsEffect(eff)
        self.setCursor(Qt.OpenHandCursor)
        self._arrastrando = False
        self._off = QPoint()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._arrastrando = True
            self._off = ev.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._arrastrando:
            self.move(self.mapToParent(ev.pos()) - self._off)

    def mouseReleaseEvent(self, ev):
        self._arrastrando = False
        self.setCursor(Qt.OpenHandCursor)


class ComparadorOverlay(QDialog):
    """Overlay modal a pantalla completa. `exec_()` → Accepted si el usuario confirma
    (usar `resultado()` para el centro global), o Rejected si salta/cancela."""

    def __init__(self, template_bgr: np.ndarray, centro_inicial, parent=None,
                 titulo: str = "Verificar posición"):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self._geo = QApplication.desktop().screenGeometry()
        self.setGeometry(self._geo)
        self._resultado = None

        pix = bgr_a_qpixmap(template_bgr)
        self._img = _Arrastrable(pix, self)
        # Posicionar el centro del recorte en `centro_inicial` (global → local).
        cx, cy = int(centro_inicial[0]), int(centro_inicial[1])
        lx = cx - self._geo.x() - pix.width() // 2
        ly = cy - self._geo.y() - pix.height() // 2
        self._img.move(lx, ly)

        # Panel de control (arriba-izquierda) con instrucción + botones.
        self._panel = QLabel(
            f"<b>{titulo}</b><br>Arrastrá la imagen naranja hasta que calce con el recurso "
            "real en Quark, luego Confirmar.", self)
        self._panel.setStyleSheet(
            f"QLabel{{background:{_PANEL_BG};color:#e2e8f0;border:1px solid {_ACENTO};"
            "border-radius:10px;padding:10px 14px;font-size:13px;}")
        self._panel.setWordWrap(True)
        self._panel.setFixedWidth(420)
        self._panel.adjustSize()
        self._panel.move(self._geo.width() // 2 - 210, 24)

        self._btn_ok = QPushButton("Confirmar", self)
        self._btn_skip = QPushButton("Saltar (no se detecta)", self)
        for b, base in ((self._btn_ok, _ACENTO), (self._btn_skip, "#334155")):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{base};color:#f8fafc;border:none;border-radius:8px;"
                "padding:8px 16px;font-size:13px;}QPushButton:hover{background:#475569;}")
        self._btn_ok.clicked.connect(self._confirmar)
        self._btn_skip.clicked.connect(self._saltar)

        fila = QLabel(self)  # contenedor para la fila de botones
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self._btn_ok)
        lay.addWidget(self._btn_skip)
        fila.adjustSize()
        fila.move(self._geo.width() // 2 - fila.width() // 2,
                  self._panel.y() + self._panel.height() + 10)

        self._img.raise_()
        self._panel.raise_()
        fila.raise_()

    def _confirmar(self):
        c_local = self._img.geometry().center()
        self._resultado = (c_local.x() + self._geo.x(), c_local.y() + self._geo.y())
        self.accept()

    def _saltar(self):
        self._resultado = None
        self.reject()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self._saltar()
        else:
            super().keyPressEvent(ev)

    def resultado(self):
        """(x, y) global del centro confirmado, o None si se saltó/canceló."""
        return self._resultado
