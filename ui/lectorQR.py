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
        self._checklist_labels = []
        self._checklist_visible = True        # visible por defecto; ocultable aparte
        self._geo = None
        self._drag = None

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

        # Crear botón flotante “QR” + botón "información" (arriba del QR) + cápsulas + checklist
        self._geo = geo
        self._create_qr_button(geo)
        self._create_info_button(geo)
        self._create_info_capsules(geo)
        self._create_checklist_capsules(geo)

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
        # Posición inicial: guardada en config, o por defecto abajo-derecha.
        bx, by = geo.width() - 80, geo.height() - 200
        try:
            from config.config import config_global
            saved = config_global.qr_overlay_pos
            if saved:
                bx, by = saved
        except Exception:
            pass
        bx = max(8, min(int(bx), geo.width() - 68))
        by = max(88, min(int(by), geo.height() - 68))
        self._qr_bx, self._qr_by = bx, by
        self.qr_button.move(bx, by)
        # Arrastrable por el ícono; clic izq (sin arrastre) = alternar mira; der = cerrar.
        self._instalar_drag(self.qr_button, self._toggle_mira)

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
        # Arrastrable; clic izq = info; clic medio = checklist; der = cerrar.
        self._instalar_drag(self.info_button, self._toggle_info, on_middle=self._toggle_checklist)

    def _create_info_capsules(self, geo):
        """Cápsulas de info (título: valor) desde info['filas']."""
        self._cap_w, self._cap_h, self._gap = 230, 29, 6   # 10% más altas (26→29)
        for (titulo, valor) in (self._info.get("filas") or []):
            if titulo and (valor not in (None, "")):
                txt = f"  {titulo}: {valor}"
            elif titulo:
                txt = f"  {titulo}"
            else:
                txt = f"  {valor}"
            lbl = QLabel(txt, self)
            lbl.setFont(QFont("Arial", 9, QFont.Bold))
            lbl.setWordWrap(True)
            lbl.setFixedWidth(self._cap_w)
            lbl.setStyleSheet(
                "QLabel{color:white;border-radius:14px;padding:0 8px;"
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #e7885f, stop:1 #d9534f);}"
            )
            lbl.setFixedHeight(max(self._cap_h, lbl.heightForWidth(self._cap_w)))
            lbl.setVisible(self._info_visible)
            self._info_labels.append(lbl)
        self._posicionar_capsulas()

    def _create_checklist_capsules(self, geo):
        """Checklist (recordatorios) por encima de las cápsulas de info; ocultable aparte
        (clic medio en el botón de info, o clic sobre una cápsula del checklist)."""
        items = [
            "Poner en negrita todos los DIARIO HUARPE",
            "Buscar intertítulos (comienzan con ## )",
            "Borrar firma y correo si la nota no va firmada",
        ]
        for txt in items:
            lbl = QLabel(f"  ☐  {txt}", self)
            lbl.setFont(QFont("Arial", 9, QFont.Bold))
            lbl.setWordWrap(True)
            lbl.setFixedWidth(self._cap_w)
            lbl.setStyleSheet(
                "QLabel{color:#0f172a;border-radius:14px;padding:5px 8px;"
                "background:#cfe8d8;border:1px solid #2ecc71;}"
            )
            # +10px (5 arriba + 5 abajo) por el padding vertical del checklist.
            lbl.setFixedHeight(max(self._cap_h, lbl.heightForWidth(self._cap_w - 16) + 10))
            lbl.setVisible(self._checklist_visible)
            lbl.mousePressEvent = lambda ev: self._toggle_checklist()
            self._checklist_labels.append(lbl)
        self._posicionar_capsulas()

    def _posicionar_capsulas(self):
        """Posiciona info + checklist relativo a (_qr_bx, _qr_by)."""
        if not self._geo:
            return
        cap_w, gap = self._cap_w, self._gap
        cx = self._qr_bx + 30
        x = max(8, min(cx - cap_w // 2, self._geo.width() - cap_w - 8))
        # Apilar hacia arriba usando el alto real de cada cápsula (wordWrap → variable).
        y = self._qr_by - 80
        for lbl in self._info_labels:
            y -= (lbl.height() + gap)
            lbl.move(x, max(8, y))
        y -= gap
        for lbl in self._checklist_labels:
            y -= (lbl.height() + gap)
            lbl.move(x, max(8, y))

    def _instalar_drag(self, button, on_click, on_middle=None):
        """Arrastra la columna desde 'button'. Clic izq sin arrastre = on_click;
        clic medio = on_middle; clic der = cerrar el overlay."""
        def press(ev):
            if ev.button() == Qt.LeftButton:
                self._drag = {"moved": False, "g0": ev.globalPos(),
                              "bx0": self._qr_bx, "by0": self._qr_by}
            elif ev.button() == Qt.MiddleButton and on_middle:
                on_middle()
            elif ev.button() == Qt.RightButton:
                self.close()
            ev.accept()
        def move(ev):
            d = self._drag
            if d and (ev.buttons() & Qt.LeftButton):
                delta = ev.globalPos() - d["g0"]
                if delta.manhattanLength() > 4:
                    d["moved"] = True
                self._reposicionar_columna(d["bx0"] + delta.x(), d["by0"] + delta.y())
            ev.accept()
        def release(ev):
            d = self._drag
            if ev.button() == Qt.LeftButton and d:
                self._drag = None
                if d["moved"]:
                    self._guardar_posicion()
                else:
                    on_click()
            ev.accept()
        button.mousePressEvent = press
        button.mouseMoveEvent = move
        button.mouseReleaseEvent = release

    def _reposicionar_columna(self, bx, by):
        if self._geo:
            bx = max(8, min(int(bx), self._geo.width() - 68))
            by = max(88, min(int(by), self._geo.height() - 68))
        self._qr_bx, self._qr_by = int(bx), int(by)
        self.qr_button.move(self._qr_bx, self._qr_by)
        self.info_button.move(self._qr_bx, self._qr_by - 80)
        self._posicionar_capsulas()

    def _guardar_posicion(self):
        try:
            from config.config import config_global
            config_global.save_qr_overlay_pos(self._qr_bx, self._qr_by)
        except Exception:
            pass

    def _toggle_info(self):
        self._info_visible = not self._info_visible
        for lbl in self._info_labels:
            lbl.setVisible(self._info_visible)
        # El toggle de info arrastra al checklist: si oculta info, oculta el checklist;
        # si muestra info, lo vuelve a mostrar. (El clic medio lo alterna por separado.)
        self._checklist_visible = self._info_visible
        for lbl in self._checklist_labels:
            lbl.setVisible(self._checklist_visible)

    def _toggle_checklist(self):
        self._checklist_visible = not self._checklist_visible
        for lbl in self._checklist_labels:
            lbl.setVisible(self._checklist_visible)

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
