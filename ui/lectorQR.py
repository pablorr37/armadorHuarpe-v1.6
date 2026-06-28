from __future__ import annotations

import webbrowser
import cv2
import numpy as np
import pyautogui
from typing import Optional
from pyzbar import pyzbar

from PyQt5.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QCursor, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import QWidget, QApplication, QPushButton, QLabel
import logging
_log = logging.getLogger(__name__)

try:
    from utils.resources import resource_path
except Exception:  # fallback dev
    from pathlib import Path as _P
    def resource_path(rel: str) -> str:
        return str(_P(__file__).resolve().parent.parent / rel)



CAP_SIZE = 150  # lado del recuadro de captura


# ==============================================================
# 🔹 Auxiliares
# ==============================================================

def _capturar_region_around(pos: QPoint, size: int = CAP_SIZE) -> np.ndarray:
    """Captura una región cuadrada alrededor de 'pos' (coordenadas de pantalla)."""
    half = size // 2
    x = max(0, pos.x() - half)
    y = max(0, pos.y() - half)
    w = h = size
    img = pyautogui.screenshot(region=(x, y, w, h))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _leer_qr(imagen_bgr: np.ndarray) -> str | None:
    """Lee códigos QR en la imagen y devuelve el primero válido."""
    codigos = pyzbar.decode(imagen_bgr)
    for c in codigos:
        try:
            data = c.data.decode("utf-8", errors="ignore").strip()
            if data:
                return data
        except Exception:
            pass
    return None


# ==============================================================
# 🔹 Overlay con botón flotante
# ==============================================================

class QROverlay(QWidget):
    """
    Ventana transparente, siempre encima, que muestra una mira verde controlada
    por un botón flotante "QR" (abajo a la derecha, sobre la barra de tareas).
    - Clic izquierdo sobre la mira: intenta leer QR.
    - Clic derecho: apaga temporalmente la mira.
    - Clic izquierdo en botón "QR": alterna entre encendido y apagado de la mira.
    - Clic derecho en botón "QR": cierra completamente el overlay.
    """
    qr_detected = pyqtSignal(str)
    overlay_closed = pyqtSignal()

    def __init__(self, parent=None, capture_size: int = CAP_SIZE, info: dict = None,
                 auto_info: bool = False):
        super().__init__(parent)
        self.capture_size = capture_size
        self._visible = False  # mira inicialmente apagada
        self._info = info or {}
        self._info_visible = bool(auto_info)  # si True, cápsulas visibles de entrada
        self._info_labels = []

        # Ventana transparente y siempre encima
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        # Cobertura pantalla completa
        geo = QApplication.desktop().screenGeometry()
        self.setGeometry(geo)

        # Posición inicial del cursor y repintado continuo
        self._cursor_pos = QCursor.pos()
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(16)  # ~60 FPS
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        # Crear botón flotante “QR” + botón "información" (arriba del QR) y cápsulas
        self._create_qr_button(geo)
        self._create_info_button(geo)
        self._create_info_capsules(geo)

        self.show()
        _log.info("[QR] Overlay activo. Usa el botón QR para encender o apagar la mira.")

    # ----------------------------------------------------------
    # Botón flotante
    # ----------------------------------------------------------

    def _create_qr_button(self, geo):
        """Crea el botón redondo 'QR' abajo a la derecha."""
        self.qr_button = QPushButton("QR", self)
        self.qr_button.setFixedSize(60, 60)
        self.qr_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.qr_button.setStyleSheet("""
            QPushButton {
                border-radius: 30px;
                background-color: #2ecc71;
                color: white;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
        """)
        # Posición: 20 px arriba y a la izquierda del borde inferior derecho
        bx = geo.width() - 80
        by = geo.height() - 200
        self._qr_bx, self._qr_by = bx, by
        self.qr_button.move(bx, by)

        # Eventos: clic izquierdo para alternar, derecho para cerrar
        self.qr_button.mousePressEvent = self._on_qr_button_click

    # ----------------------------------------------------------
    # Botón "información" + cápsulas (#9)
    # ----------------------------------------------------------
    def _create_info_button(self, geo):
        """Botón redondo 'información' justo arriba del botón QR."""
        self.info_button = QPushButton(self)
        self.info_button.setFixedSize(60, 60)
        self.info_button.setIcon(QIcon(QPixmap(resource_path("ui/assets/informacion.png"))))
        from PyQt5.QtCore import QSize
        # Ícono ~10% más grande (34→37) → anillo naranja más fino, mismo botón 60px.
        self.info_button.setIconSize(QSize(37, 37))
        self.info_button.setStyleSheet(
            "QPushButton{border-radius:30px;background-color:#e7885f;}"
            "QPushButton:hover{background-color:#d9534f;}"
        )
        self.info_button.move(self._qr_bx, self._qr_by - 80)
        self.info_button.mousePressEvent = self._on_info_button_click

    def _create_info_capsules(self, geo):
        """Cápsulas estilizadas (naranja→rojo) con las filas de info (título: valor).
        Las filas vienen en info['filas'] = [(titulo, valor), …] (contexto PDF o pegado).
        Centradas sobre el botón de info y apiladas hacia arriba; más chicas."""
        filas = self._info.get("filas") or []
        cap_w, cap_h, gap = 230, 26, 6
        cx = self._qr_bx + 30                  # centro horizontal del botón de info (60px)
        # Clampear dentro del viewport: el botón está pegado al borde derecho, así que
        # centrar la cápsula la sacaba de pantalla por la derecha.
        x = max(8, min(cx - cap_w // 2, geo.width() - cap_w - 8))
        info_top = self._qr_by - 80
        for i, (titulo, valor) in enumerate(filas):
            lbl = QLabel(f"  {titulo}: {valor if (valor not in (None, '')) else '—'}", self)
            lbl.setFixedSize(cap_w, cap_h)
            lbl.setFont(QFont("Arial", 9, QFont.Bold))
            lbl.setStyleSheet(
                "QLabel{color:white;border-radius:13px;padding:0 8px;"
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #e7885f, stop:1 #d9534f);}"
            )
            # i=0 inmediatamente arriba del botón; crecen hacia arriba (clampeadas).
            y = max(8, info_top - (i + 1) * (cap_h + gap))
            lbl.move(x, y)
            lbl.setVisible(self._info_visible)   # respeta auto_info
            self._info_labels.append(lbl)

    def _on_info_button_click(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_info()
        elif event.button() == Qt.RightButton:
            # Mismo gesto que el QR: clic derecho cierra el overlay.
            self.close()
        event.accept()

    def _toggle_info(self):
        self._info_visible = not self._info_visible
        for lbl in self._info_labels:
            lbl.setVisible(self._info_visible)

    def _on_qr_button_click(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_mira()
        elif event.button() == Qt.RightButton:
            _log.info("[QR] Overlay cerrado (clic derecho en botón QR).")
            self.close()
        event.accept()

    def _toggle_mira(self):
        """Activa o apaga la mira manualmente."""
        self._visible = not self._visible
        state = "ON" if self._visible else "OFF"
        color = "#2ecc71" if self._visible else "#e74c3c"
        self.qr_button.setStyleSheet(f"""
            QPushButton {{
                border-radius: 30px;
                background-color: {color};
                color: white;
            }}
        """)
        self.update()
        _log.info(f"[QR] Mira {state} (botón).")

    # ----------------------------------------------------------
    # Eventos y dibujo
    # ----------------------------------------------------------

    def _tick(self):
        pos = QCursor.pos()
        if pos != self._cursor_pos:
            self._cursor_pos = pos
            self.update()

    def _rect_at_cursor(self) -> QRect:
        half = self.capture_size // 2
        p = self._cursor_pos
        return QRect(p.x() - half, p.y() - half, self.capture_size, self.capture_size)

    def paintEvent(self, _):
        if not self._visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), Qt.transparent)

        r = self._rect_at_cursor()
        pen = QPen(QColor(0, 255, 0), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)

        cx, cy = self._cursor_pos.x(), self._cursor_pos.y()
        painter.drawLine(cx - 10, cy, cx + 10, cy)
        painter.drawLine(cx, cy - 10, cx, cy + 10)

    # ----------------------------------------------------------
    # Captura del QR y control de mira
    # ----------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Intentar leer QR (aunque la mira esté apagada)
            try:
                img = _capturar_region_around(self._cursor_pos, self.capture_size)
                enlace = _leer_qr(img)
                if enlace:
                    webbrowser.open(enlace)
                    self.qr_detected.emit(enlace)
                    self.close()
                else:
                    self._blink()
            except Exception as e:
                _log.info(f"[QR] Error de lectura: {e}")
                self._blink()
            event.accept()

        elif event.button() == Qt.RightButton:
            # Apagar la mira manualmente (sin cerrar overlay)
            if self._visible:
                self._visible = False
                self.update()
                self._update_button_color()
                _log.info("[QR] Mira OFF (clic derecho en mira)")
            event.accept()

        else:
            super().mousePressEvent(event)

    def closeEvent(self, event):
        self.overlay_closed.emit()
        super().closeEvent(event)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _update_button_color(self):
        color = "#2ecc71" if self._visible else "#e74c3c"
        self.qr_button.setStyleSheet(f"""
            QPushButton {{
                border-radius: 30px;
                background-color: {color};
                color: white;
            }}
        """)

    def _blink(self):
        """Efecto rápido al no detectar QR."""
        old = self.capture_size
        self.capture_size = max(120, old - 20)
        self.update()
        QTimer.singleShot(120, lambda: (setattr(self, "capture_size", old), self.update()))



# ==============================================================
# 🔹 API para MainWindow
# ==============================================================

_overlay_ref: Optional[QROverlay] = None


def start_overlay(parent=None, info: dict = None, auto_info: bool = False):
    """Crea (o reinicia) el overlay. Arranca con mira apagada y botón QR visible.
    Si auto_info=True, las cápsulas de información arrancan visibles."""
    global _overlay_ref
    if _overlay_ref is None or not _overlay_ref.isVisible():
        _overlay_ref = QROverlay(parent, info=info, auto_info=auto_info)
        return _overlay_ref
    else:
        try:
            _overlay_ref.close()
        except Exception:
            pass
        _overlay_ref = QROverlay(parent, info=info, auto_info=auto_info)
        return _overlay_ref


def stop_overlay():
    """Cierra el overlay si está activo."""
    global _overlay_ref
    if _overlay_ref and _overlay_ref.isVisible():
        _overlay_ref.close()
    _overlay_ref = None
