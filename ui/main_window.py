# ui/main_window.py

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QTextEdit, QGridLayout, 
    QFileDialog, QMessageBox, QListWidget, QInputDialog, QMenu, QAction, QSizePolicy, QScrollArea,
    QDialog, QLabel, QLineEdit, QDialogButtonBox, QApplication, QShortcut
)
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QHeaderView
from PyQt5.QtWidgets import QStackedWidget, QGraphicsOpacityEffect
from ui.widgets.circle_icon_button import CircleIconButton
from ui.widgets.vertical_tab_button import VerticalTabButton
from PyQt5.QtGui import QMovie
from ui.dialogo_pool_editor import PoolEditorDialog
from ui.visor_img import VisorPanelWidget
from ui.panel_fotos_pagina import PanelFotosPagina
import json
from ui.maqueta_widget import MaquetaWidget
from PyQt5.QtGui import QPainter, QPixmap, QKeySequence, QColor, QIcon, QImage, qGray, QPainterPath
import subprocess
import configparser
from ui.lectorQR import start_overlay
from urllib.parse import urlparse
from ui.workers import PoolScrapeWorker
import os
import ctypes
from ctypes import wintypes
import time


import re
from typing import Optional
from PyQt5 import QtWidgets, QtCore, QtGui
from ui.shortcut_config_dialog import ShortcutConfigDialog
from ui.secciones_config_dialog import SeccionesConfigDialog
from utils.resources import resource_path
from PyQt5.QtGui import QDesktopServices, QFont, QFontMetrics, QPen, QIcon
from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal, QThread, QObject, QEvent, QRectF, QSize, QPoint, QRect, QPropertyAnimation, QEasingCurve, QVariantAnimation, QParallelAnimationGroup
from controller.controller import ArmadorController
from pathlib import Path
from ui.dialogo_mono import DialogoMono
from services.shortcut_manager import ShortcutManager
from services.chrome_watcher import ChromeWatcher
from config.config import Config
from utils.app_logger import get_logger

from datetime import datetime

_log = get_logger(__name__)


def _pixmap_grayscale(pm: QPixmap) -> QPixmap:
    """Devuelve una copia en escala de grises del pixmap, preservando el alpha."""
    if pm is None or pm.isNull():
        return pm
    src = pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation) if max(pm.width(), pm.height()) > 64 else pm
    img = src.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            g = qGray(c.red(), c.green(), c.blue())
            c.setRgb(g, g, g, c.alpha())
            img.setPixelColor(x, y, c)
    return QPixmap.fromImage(img)


_AJUSTES_MENU_QSS = (
    "QMenu { background: #1e293b; color: #e2e8f0;"
    " border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; padding: 4px; }"
    " QMenu::item { padding: 5px 18px; border-radius: 5px; }"
    " QMenu::item:selected { background: #e7885f; color: #fff; }"
    " QMenu::separator { height: 1px; background: rgba(255,255,255,0.10); margin: 4px 8px; }"
)


class PageButton(QPushButton):
    doubleClicked = pyqtSignal(int)
    ajustesClicked = pyqtSignal(int)
    foto_icon = None
    titulo_icon = None
    activo_icon = None
    editando_icon = None
    ajustes_icon = None

    def __init__(self, numero: int, *args, **kwargs):
        super().__init__(str(numero), *args, **kwargs)
        self.numero = numero
        self.tapa_foto = False
        self.tapa_titulo = False
        self.listo_para_armar = False
        self.editando = False
        self.setAcceptDrops(True)
        self._drop_hover = False
        self._hover_scale = 1.06   # 6% más grande
        self._ajustes_rect = None  # zona clickeable del ícono de ajustes (se setea en paintEvent)
        self._is_active = False        # ¿es la página seleccionada?
        self._ajustes_visible = False  # ¿se está mostrando el ícono de ajustes?
        self.setMouseTracking(True)
        self._ajustes_timer = QTimer(self)
        self._ajustes_timer.setSingleShot(True)
        self._ajustes_timer.timeout.connect(self._ocultar_ajustes)
        # Fade-in del ícono de ajustes
        self._ajustes_opacity = 0.0
        self._ajustes_fade = QVariantAnimation(self)
        self._ajustes_fade.setStartValue(0.0)
        self._ajustes_fade.setEndValue(1.0)
        self._ajustes_fade.setDuration(280)
        self._ajustes_fade.setEasingCurve(QEasingCurve.OutCubic)
        self._ajustes_fade.valueChanged.connect(self._on_ajustes_fade)

        # Carga diferida (lazy) de img
        if PageButton.foto_icon is None:
            PageButton.foto_icon = QPixmap(resource_path("ui/assets/foto_tapa.png"))
        if PageButton.titulo_icon is None:
            PageButton.titulo_icon = QPixmap(resource_path("ui/assets/titulo_tapa.png"))
        if PageButton.activo_icon is None:
            PageButton.activo_icon = QPixmap(resource_path("ui/assets/activo.png"))
        if PageButton.editando_icon is None:
            PageButton.editando_icon = QPixmap(resource_path("ui/assets/editar.png"))
        if PageButton.ajustes_icon is None:
            PageButton.ajustes_icon = QPixmap(resource_path("ui/assets/ajustes.png"))

    def _dibujar_ajustes(self, painter, size, margin):
        """Dibuja el ícono de ajustes (esquina inferior izquierda) solo cuando está
        visible, y guarda su rect clickeable. Se llama desde ambos modos del paintEvent.
        Es 10% más chico que el resto, con fade-in y borde naranja."""
        if not self._ajustes_visible:
            self._ajustes_rect = None
            return
        from PyQt5.QtCore import QRect as _QRect
        aj = max(14, int(size * 0.9))          # 10% más chico que los otros íconos
        ax = margin
        ay = self.height() - aj - margin
        rect = _QRect(ax, ay, aj, aj)
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, self._ajustes_opacity)))
        if PageButton.ajustes_icon and not PageButton.ajustes_icon.isNull():
            painter.drawPixmap(ax, ay, aj, aj, PageButton.ajustes_icon)
        # Borde naranja (mismo realce que el hover de los íconos radiales)
        pen = QPen(QColor("#e7885f"), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)
        painter.restore()
        self._ajustes_rect = rect

    # ── Visibilidad temporal del ícono de ajustes ────────────────────
    def _on_ajustes_fade(self, val):
        self._ajustes_opacity = float(val)
        self.update()

    def mostrar_ajustes_temporal(self):
        if not self._ajustes_visible:
            self._ajustes_visible = True
            self._ajustes_opacity = 0.0   # arrancar transparente (evita 1er frame opaco)
            self._ajustes_fade.stop()
            self._ajustes_fade.start()    # fade-in al aparecer
        self.update()
        self._ajustes_timer.start(2000)

    def _ocultar_ajustes(self):
        self._ajustes_timer.stop()
        if self._ajustes_visible:
            self._ajustes_visible = False
            self.update()

    def set_activa(self, v):
        v = bool(v)
        if v == self._is_active:
            return
        self._is_active = v
        if v:
            self.mostrar_ajustes_temporal()   # al seleccionar → 5s visible
        else:
            self._ocultar_ajustes()           # al deseleccionar → oculto
        self.update()                         # repintar el borde de selección al cambiar

    def mouseMoveEvent(self, event):
        if self._is_active:
            self.mostrar_ajustes_temporal()   # fade-in si aparece + reinicia los 2s
        super().mouseMoveEvent(event)
    
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasFormat("application/x-armador-pool-nota"):
            event.acceptProposedAction()
            self._drop_hover = True
            self.update()
        else:
            event.ignore()


    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        mime = event.mimeData()
        if mime.hasFormat("application/x-armador-pool-nota"):
            event.setDropAction(QtCore.Qt.CopyAction)
            event.accept()
        else:
            event.ignore()


    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent):
        self._drop_hover = False
        self.update()
        super().dragLeaveEvent(event)


    def dropEvent(self, event: QtGui.QDropEvent):
        mime = event.mimeData()

        if not mime.hasFormat("application/x-armador-pool-nota"):
            event.ignore()
            self._drop_hover = False
            self.update()
            return

        # ---- BLOQUEO POR EDICIÓN PENDIENTE ----
        mw = self.window()
        if hasattr(mw, "pool_editor") and mw.pool_editor.isVisible():
            if mw.pool_editor.hay_cambios_pendientes():
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(
                    mw,
                    "Edición en curso",
                    "Hay cambios sin guardar en la noticia abierta. Guardalos o cancelá antes de arrastrar."
                )
                event.ignore()
                self._drop_hover = False
                self.update()
                return
        # ----------------------------------------
        
        data_bytes = mime.data("application/x-armador-pool-nota")

        try:
            raw = bytes(data_bytes).decode("utf-8")
            payload = json.loads(raw)        # ← JSON REAL
            dir_str = payload.get("dir")     # ← path real
            if not dir_str:
                raise ValueError("dir vacío")
        except Exception:
            event.ignore()
            self._drop_hover = False
            self.update()
            return


        event.acceptProposedAction()
        self._drop_hover = False
        self.update()

        # Delegar al MainWindow
        mw = self.window()
        if hasattr(mw, "on_drop_pool_nota"):
            mw.on_drop_pool_nota(self.numero, Path(dir_str))




    def set_tapa_flags(self, foto: bool, titulo: bool):
        """Actualiza los flags de tapa sin repintar de inmediato."""
        changed = (self.tapa_foto != foto) or (self.tapa_titulo != titulo)
        self.tapa_foto = foto
        self.tapa_titulo = titulo
        if changed:
            # Evitar repaint inmediato dentro de un ciclo de dibujo
            QTimer.singleShot(0, self.update)

    def set_listo_flag(self, listo: bool):
        if self.listo_para_armar != listo:
            self.listo_para_armar = listo
            QTimer.singleShot(0, self.update)

    def set_editando_flag(self, v: bool):
        if self.editando != v:
            self.editando = v
            QTimer.singleShot(0, self.update)


    def paintEvent(self, event):
        # Evitar repintados invisibles
        if not self.isVisible():
            return

        # === Sin página asignada → dibujo estándar ===
        if not hasattr(self, "pagina") or self.pagina is None:
            super().paintEvent(event)
            return

        pagina = self.pagina
        rect = QRectF(0, 0, self.width(), self.height())

        # Si está en hover por drag, expandir el botón suavemente
        if self._drop_hover:
            factor = self._hover_scale
            w = rect.width() * factor
            h = rect.height() * factor
            dx = (w - rect.width()) / 2
            dy = (h - rect.height()) / 2
            rect = QRectF(-dx, -dy, w, h)

        color_estado = getattr(self, "_estado_color", QColor("#cccccc"))

        # ==========================================================
        # 🟣 MODO MAQUETACIÓN
        # ==========================================================
        if getattr(self, "modo_maquetacion", False):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            # Fondo y maqueta
            painter.fillRect(rect, QColor(color_estado))
            try:
                parent = self.parent()
                while parent and not hasattr(parent, "controller"):
                    parent = parent.parent() if hasattr(parent, "parent") else None
                controller = getattr(parent, "controller", None)
                MaquetaWidget.draw_static(
                    painter, pagina, rect.adjusted(4, 4, -4, -4), controller
                )
            except Exception as e:
                _log.warning(f"[WARN] draw_static en PageButton: {e}")

            # Número con sombra
            font = painter.font()
            font.setBold(True)
            font.setPointSize(13)
            painter.setFont(font)
            text = f"P{self.numero:02d}"
            painter.setPen(QColor("black"))
            for dx in (-1, 1):
                for dy in (-1, 1):
                    painter.drawText(8 + dx, 20 + dy, text)
            painter.setPen(QColor("white"))
            painter.drawText(8, 20, text)



            # Borde general
            pen = QPen(Qt.black, 0.10)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0.10, 0.10, -0.10, -0.10))

            # Borde si está seleccionada
            if self.hasFocus():
                pen = QPen(QColor("#4043EB"), 5)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect.adjusted(3, 3, -3, -3))

            # Ícono de ajustes (esquina inferior izquierda, también en maquetación)
            _aj_size = max(22, int(min(self.width(), self.height()) * 0.25))
            self._dibujar_ajustes(painter, _aj_size, 4)

            painter.end()
            return

        # ==========================================================
        # 🔵 MODO ARMADO — aspecto tipo Maquetación (aviso real) + sección + borde redondeado
        # ==========================================================
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        radio = 8.0
        # Fondo + aviso real, recortados a esquinas redondeadas
        path = QPainterPath()
        path.addRoundedRect(rect, radio, radio)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, QColor(color_estado))
        try:
            parent = self.parent()
            while parent and not hasattr(parent, "controller"):
                parent = parent.parent() if hasattr(parent, "parent") else None
            controller = getattr(parent, "controller", None)
            MaquetaWidget.draw_static(painter, pagina, rect.adjusted(4, 4, -4, -4), controller)
        except Exception as e:
            _log.warning(f"[WARN] draw_static en PageButton (armado): {e}")
        painter.restore()

        # Número de página + sección (con sombra, como en Maquetación)
        def _texto_sombra(px, py, txt, ptsize):
            f = painter.font(); f.setBold(True); f.setPointSize(ptsize); painter.setFont(f)
            painter.setPen(QColor("black"))
            for dx in (-1, 1):
                for dy in (-1, 1):
                    painter.drawText(px + dx, py + dy, txt)
            painter.setPen(QColor("white"))
            painter.drawText(px, py, txt)

        _texto_sombra(8, 20, f"P{self.numero:02d}", 13)
        seccion = (getattr(pagina, "seccion", "") or "").strip()
        if seccion:
            _texto_sombra(8, 36, seccion, 10)

        # Borde redondeado (conserva el aspecto actual) + foco
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radio, radio)
        if getattr(self, "_is_active", False):
            # Borde de 5px pegado al borde (cubre el sangrado del fondo redondeado).
            # Va por _is_active (página seleccionada) → sigue a la navegación con flechas.
            painter.setPen(QPen(QColor("#4043EB"), 5))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radio, radio)

        # --- Íconos de estado (se mantienen) ---
        size = max(22, int(min(self.width(), self.height()) * 0.25))
        margin = 4
        x = self.width() - size - margin
        y = self.height() - size - margin
        if self.tapa_foto and PageButton.foto_icon and not PageButton.foto_icon.isNull():
            painter.drawPixmap(x, y, size, size, PageButton.foto_icon)
        if self.tapa_titulo and PageButton.titulo_icon and not PageButton.titulo_icon.isNull():
            painter.drawPixmap(x, y - size - 2 if self.tapa_foto else y, size, size, PageButton.titulo_icon)
        if self.listo_para_armar and PageButton.activo_icon and not PageButton.activo_icon.isNull():
            painter.drawPixmap(margin, margin, size, size, PageButton.activo_icon)
        if self.editando and PageButton.editando_icon and not PageButton.editando_icon.isNull():
            painter.drawPixmap(self.width() - size - margin, margin, size, size, PageButton.editando_icon)

        # Ícono de ajustes (esquina inferior izquierda)
        self._dibujar_ajustes(painter, size, margin)

        painter.end()





    def mousePressEvent(self, event):
        # Click sobre el ícono de ajustes → abrir menú radial (no activa la página)
        if (event.button() == Qt.LeftButton and self._ajustes_rect is not None
                and self._ajustes_rect.contains(event.pos())):
            self.ajustesClicked.emit(self.numero)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.editando:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(
                    self.window(), "Noticia en edición",
                    "Esta noticia está siendo editada por otro usuario."
                )
                event.accept()
                return
            self.doubleClicked.emit(self.numero)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class _AjustesRadialMenu(QWidget):
    """
    Menú radial flotante de íconos alrededor de un botón de página.
    Cierra con ✕, tecla Esc o click afuera. Al elegir una opción que abre un
    submenú, los demás íconos se ocultan y queda solo el elegido (para que el
    usuario sepa qué seleccionó); por eso es ventana Qt.Tool (no Qt.Popup), que
    sobrevive a la apertura de un QMenu.
    `items`: lista de (QPixmap, texto, callable).
    """

    def __init__(self, anchor_btn, items, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._submenu_open = False
        self._item_widgets = []

        import math
        bw, bh = anchor_btn.width(), anchor_btn.height()
        page_icon = max(22, int(min(bw, bh) * 0.25))
        icon = max(16, int(page_icon * 0.9 * 1.1))     # base (10% más chico) + 10% extra
        ring = int((max(bw, bh) // 2 + int(icon * 0.8) + 6) * 1.3225)  # radio del anillo (+15% sobre el +15%)

        btn_px = icon + 10
        label_h = 20
        cont_w = max(btn_px, 96)                         # ancho para que entre el texto
        cont_h = btn_px + 2 + label_h
        center_global = anchor_btn.mapToGlobal(QPoint(bw // 2, bh // 2))
        half = ring + max(cont_w, cont_h) // 2 + 8       # margen del popup (incluye labels)
        side = half * 2
        left = center_global.x() - half
        top = center_global.y() - half
        # Mantener el popup completo dentro del área disponible de la pantalla: en
        # las páginas de la fila inferior, sin esto la mitad de abajo del anillo
        # cae bajo la barra de tareas y los ítems quedan fuera del viewport.
        try:
            avail = QApplication.desktop().availableGeometry(center_global)
            if side <= avail.width():
                left = max(avail.left(), min(left, avail.right() - side + 1))
            else:
                left = avail.left()
            if side <= avail.height():
                top = max(avail.top(), min(top, avail.bottom() - side + 1))
            else:
                top = avail.top()
        except Exception:
            pass
        self.setGeometry(left, top, side, side)
        cx, cy = half, half                             # centro en coords locales

        self._cont_w = cont_w
        self._btn_px = btn_px
        self._closing = False
        self._anims = []                                 # refs para que no las recoja el GC
        center_pos = QPoint(int(cx - cont_w / 2), int(cy - cont_h / 2))

        n = max(1, len(items))
        for i, item in enumerate(items):
            pm, tip, cb = item[0], item[1], item[2]
            enabled = item[3] if len(item) > 3 else True
            ang = math.radians(-90 + i * (360.0 / n))   # empieza arriba, en sentido horario
            bx = cx + ring * math.cos(ang)
            by = cy + ring * math.sin(ang)

            cont = QWidget(self)
            cont.setFixedSize(cont_w, cont_h)
            v = QVBoxLayout(cont)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)

            b = QPushButton(cont)
            b.setIcon(QIcon(_pixmap_grayscale(pm) if not enabled else pm))
            b.setIconSize(QSize(icon, icon))
            b.setFixedSize(btn_px, btn_px)
            if enabled:
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet(
                    "QPushButton { border: none; border-radius: %dpx;"
                    " background: rgba(30,41,59,0.96); }"
                    " QPushButton:hover { background: #e7885f; }" % (btn_px // 2)
                )
                b.clicked.connect(lambda _, f=cb, w=cont: self._run(f, w))
            else:
                b.setEnabled(False)
                b.setStyleSheet(
                    "QPushButton { border: none; border-radius: %dpx;"
                    " background: rgba(30,41,59,0.55); }" % (btn_px // 2)
                )

            lab = QLabel(tip, cont)
            lab.setAlignment(Qt.AlignCenter)
            lab.setWordWrap(True)
            lab.setStyleSheet(
                "color: %s; font-size: 11px; font-weight: bold;"
                " background: rgba(30,41,59,0.92); border-radius: 6px; padding: 1px 5px;"
                % ("#e2e8f0" if enabled else "#7b8694")
            )

            v.addWidget(b, 0, Qt.AlignHCenter)
            v.addWidget(lab, 0, Qt.AlignHCenter)

            cont._final_pos = QPoint(int(bx - cont_w / 2), int(by - cont_h / 2))
            cont._center_pos = center_pos
            eff = QGraphicsOpacityEffect(cont)
            eff.setOpacity(0.0)
            cont.setGraphicsEffect(eff)
            cont.move(center_pos)                        # arrancan en el centro (animan hacia afuera)
            self._item_widgets.append(cont)

        # Botón cerrar (✕) en el centro, sobre el botón de la página
        self._close_btn = QPushButton("✕", self)
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 12px;"
            " background: rgba(30,41,59,0.96); color: rgba(255,255,255,0.75);"
            " font-weight: bold; }"
            " QPushButton:hover { background: #ef4444; color: #fff; }"
        )
        self._close_btn.move(int(cx - 12), int(cy - 12))
        eff_c = QGraphicsOpacityEffect(self._close_btn)
        eff_c.setOpacity(0.0)
        self._close_btn.setGraphicsEffect(eff_c)
        self._close_btn.clicked.connect(self._dismiss)

    # ── Animaciones ───────────────────────────────────────────────────
    def _animate_in(self):
        grp = QParallelAnimationGroup(self)
        for cont in self._item_widgets:
            cont.move(cont._center_pos)
            cont.graphicsEffect().setOpacity(0.0)
            ap = QPropertyAnimation(cont, b"pos", self)
            ap.setDuration(260)
            ap.setStartValue(cont._center_pos)
            ap.setEndValue(cont._final_pos)
            ap.setEasingCurve(QEasingCurve.OutBack)      # mini-rebote
            ao = QPropertyAnimation(cont.graphicsEffect(), b"opacity", self)
            ao.setDuration(200); ao.setStartValue(0.0); ao.setEndValue(1.0)
            grp.addAnimation(ap); grp.addAnimation(ao)
        aoc = QPropertyAnimation(self._close_btn.graphicsEffect(), b"opacity", self)
        aoc.setDuration(200); aoc.setStartValue(0.0); aoc.setEndValue(1.0)
        grp.addAnimation(aoc)
        self._anims.append(grp)
        grp.start()

    def _make_retract(self, widgets) -> QParallelAnimationGroup:
        grp = QParallelAnimationGroup(self)
        for w in widgets:
            cp = getattr(w, "_center_pos", None)
            if cp is not None:
                ap = QPropertyAnimation(w, b"pos", self)
                ap.setDuration(170)
                ap.setStartValue(w.pos())
                ap.setEndValue(cp)
                ap.setEasingCurve(QEasingCurve.InBack)
                grp.addAnimation(ap)
            eff = w.graphicsEffect()
            if eff is not None:
                ao = QPropertyAnimation(eff, b"opacity", self)
                ao.setDuration(150)
                ao.setStartValue(eff.opacity())
                ao.setEndValue(0.0)
                grp.addAnimation(ao)
        return grp

    def _dismiss(self):
        if self._closing:
            return
        self._closing = True
        grp = self._make_retract(self._item_widgets + [self._close_btn])
        grp.finished.connect(self.close)
        self._anims.append(grp)
        if grp.animationCount() == 0:
            self.close()
        else:
            grp.start()

    # ── Eventos ──────────────────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)
        self.activateWindow()
        self.setFocus()
        self._animate_in()

    def closeEvent(self, event):
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        # Click afuera del radial → cerrar (salvo que haya un submenú abierto).
        if event.type() == QEvent.MouseButtonPress and not self._submenu_open and not self._closing:
            try:
                if not self.geometry().contains(event.globalPos()):
                    self._dismiss()
            except Exception:
                pass
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._dismiss()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        # No pintar fondo: el contenedor es 100% transparente; solo se ven los botones.
        pass

    def _run(self, cb, chosen):
        # Punto de anclaje: centro-inferior del ícono elegido (para abrir el submenú debajo)
        anchor = chosen.mapToGlobal(QPoint(self._cont_w // 2, self._btn_px))
        # Retraer hacia el centro los demás íconos y la ✕; queda visible solo el elegido.
        grp = self._make_retract([w for w in self._item_widgets if w is not chosen] + [self._close_btn])
        self._anims.append(grp)
        grp.start()
        self._submenu_open = True
        try:
            cb(anchor)
        finally:
            self._submenu_open = False
        self._dismiss()


#ACTUALIZADOR DE ESTADOS, QXP, PDF, ETC. EN HILO SEPARADO
class PollWorker(QObject):
    finished = pyqtSignal()
    done = pyqtSignal(bool)     # True si hubo cambios en verificar_qxp_pdf()
    error = pyqtSignal(str)

    def __init__(self, controller: ArmadorController):
        super().__init__()
        self.controller = controller

    def run(self):
        try:
            # Trabajo pesado fuera del hilo de la GUI:
            hubo_cambios = self.controller.verificar_qxp_pdf()
            
            self.done.emit(bool(hubo_cambios))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class AvisoCacheWorker(QObject):
    """Genera en disco los PNG de caché de los avisos (GhostScript/fitz) en un hilo
    aparte. NO crea QPixmap (eso queda para el hilo GUI). Emite {numero: (png_path, mtime)}."""
    done = pyqtSignal(dict)
    finished = pyqtSignal()

    def __init__(self, tareas):
        super().__init__()
        self.tareas = tareas   # list[(numero:int, path_str:str, mtime:float)]

    def run(self):
        from ui.maqueta_widget import _eps_to_png, pdf_to_png
        out = {}
        for numero, path_str, mtime in self.tareas:
            try:
                p = Path(path_str)
                ext = p.suffix.lower()
                if ext == ".eps":
                    png = _eps_to_png(p, Path("cache_eps"))
                    if png and png.exists():
                        out[numero] = (str(png), mtime)
                elif ext == ".pdf":
                    png = pdf_to_png(p, Path("cache_pdf"))
                    if png and png.exists():
                        out[numero] = (str(png), mtime)
                elif p.exists():
                    out[numero] = (str(p), mtime)
            except Exception as e:
                _log.warning("AvisoCacheWorker P%02d: %s", numero, e)
        self.done.emit(out)
        self.finished.emit()



# === Colores por estado de página ===
COLOR_ESTADOS = {
    "impreso":   "#6beb5f",
    "revisado":  "#2a8818",
    "apdf":      "#b700ff", 
    "corregido": "#fceb06", #PARA PERFIL Maquetación Y AVISOS
    "fotocromia":"#db3431",
    "armado":    "#db3431", #PARA PERFIL Maquetación Y AVISOS
    "azul":       "#0080ff", #PARA PERFIL Maquetación Y AVISOS
    "asignado":  "#80d4ff",
    "asignado_remoto":"#ffffff" ,
    "vacío":     "#2d2f30",
    "txt": "#a8a8a8"
    
}

       # Estilo visual tipo toggle

style_btn = """
    QPushButton {
        background-color: #1e293b;        /* azul gris oscuro base */
        color: #f1f5f9;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 6px 12px;
        font-size: 13px;
    }
    QPushButton:hover {
        background-color: #334155;        /* un poco más claro al pasar */
    }
    QPushButton:pressed {
        background-color: #475569;        /* tono presionado */
    }
    QPushButton:checked {
        background-color: #e7885f;        /* 🔶 tu naranja original */
        color: white;
        font-weight: bold;
        border: 1px solid #b6410f;        /* borde oscuro naranja */
    }
    QPushButton:disabled {
        background-color: #0f172a;
        color: #64748b;
        border: 1px solid #1e293b;
    }
"""
# --- Imágenes permitidas (sin WEBP) ---
IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".psd", ".eps", ".pdf", ".bmp", ".gif"}
# ----
class PoolTreeWidget(QtWidgets.QTreeWidget):
    """
    QTreeWidget que emite drags con información de la nota del pool.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            item = self.currentItem()
            if item is not None:
                mw = self.window()
                if hasattr(mw, "on_pool_item_double_clicked"):
                    mw.on_pool_item_double_clicked(item, 0)
                    return
        super().keyPressEvent(event)

    
    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return

        data = item.data(0, QtCore.Qt.UserRole)
        if not data:
            return  # es un nodo de sección

        # ---- BLOQUEO POR EDICIÓN PENDIENTE ----
        mw = self.window()
        if hasattr(mw, "pool_editor") and mw.pool_editor.isVisible():
            # extraemos ruta de esta nota
            dir_str = data.get("dir_path") or data.get("dir") or None
            if dir_str:
                from pathlib import Path
                nota_dir = Path(dir_str)
                # Comparamos con nota actualmente abierta
                if mw.pool_editor.hay_cambios_pendientes():
                    if mw.pool_editor._dir_pool_actual == nota_dir:
                        # bloqueamos solo esa nota
                        return
    # ----------------------------------------
        
        mime = QtCore.QMimeData()
        # usamos un formato propio para identificar el drop
        payload = {"dir": data.get("dir_path") or data.get("dir")}
        mime.setData(
            "application/x-armador-pool-nota",
            QtCore.QByteArray(json.dumps(payload).encode("utf-8"))
        )

        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(QtCore.Qt.CopyAction)

class MainWindow(QMainWindow):
    def __init__(self, controller: ArmadorController):
        super().__init__()
        self.controller = controller
        self.controller.on_scrape_error = self._on_queue_scrape_error
        self.setWindowTitle("Armador Huarpe")
        self.setWindowIcon(QIcon(resource_path("ui/assets/guanaco.png")))

        self.setMinimumSize(900, 600)

        # Widget principal y layout general
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_widget.setStyleSheet("""
            QWidget {
                background-color: #101820;  /* azul grisáceo oscuro moderno */
                color: #e0e0e0;             /* texto claro */
            }
            QLabel {
                color: #e0e0e0;
            }
            QTextEdit, QListWidget, QScrollArea {
                background-color: #1e293b;
                border: 1px solid #334155;
                color: #f1f5f9;
            }
        """)
        # === Menú superior === #
        # Menú de acciones
        menubar = self.menuBar()

        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #1e293b;
                color: #e2e8f0;
                border-bottom: 1px solid #334155;
            }
            QMenuBar::item:selected {
                background-color: #334155;
                color: #ffffff;
            }
            QMenu {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
            }
            QMenu::item:selected {
                background-color: #e7885f;  /* usa tu naranja también al seleccionar */
                color: #ffffff;
            }
        """)

        acciones_menu = menubar.addMenu("Acciones")

        # Acción: actualizar base
        crear_base_action = QAction("Conectar base", self)
        crear_base_action.triggered.connect(self.on_crear_base)
        acciones_menu.addAction(crear_base_action)

        acciones_menu.addSeparator()
        # Acción: Actualizar páginas (limpia caché y fuerza poll)
        act_actualizar_paginas = QAction("Actualizar páginas", self)
        act_actualizar_paginas.triggered.connect(self.on_actualizar_paginas)
        acciones_menu.addAction(act_actualizar_paginas)

        acciones_menu.addSeparator()

        # Menú Acciones: Lanzar Chrome (debug) 
        self.act_launch_chrome = QAction("Abrir Chrome automatizado", self)
        self.act_launch_chrome.triggered.connect(self.on_launch_chrome_debug)
        acciones_menu.addAction(self.act_launch_chrome)

        layout = QHBoxLayout()
        main_widget.setLayout(layout)
        acciones_menu.addSeparator()
        
        # Cargar mono   
        cargar_mono_action = QAction("Cargar mono", self)
        cargar_mono_action.triggered.connect(self.abrir_dialogo_mono)
        acciones_menu.addAction(cargar_mono_action)

        # Cargar avisos
        cargar_avisos_excel_action = QAction("Cargar avisos", self)
        cargar_avisos_excel_action.triggered.connect(self.on_cargar_avisos_excel)
        acciones_menu.addAction(cargar_avisos_excel_action)

        # Módulo "Armar mono" (lista de notas del día)
        self.action_armar_mono = QAction("Armar mono (lista de notas)", self)
        self.action_armar_mono.setCheckable(True)
        self.action_armar_mono.setChecked(False)
        self.action_armar_mono.triggered.connect(self.on_toggle_armar_mono)
        acciones_menu.addAction(self.action_armar_mono)



        # ------------------------------------------------------------
        # NUEVO MENÚ CONFIGURACIÓN
        # ------------------------------------------------------------
        menu_config = menubar.addMenu("Configuración")

        # Atajos de teclado
        action_shortcuts = QAction("Atajos de teclado", self)
        action_shortcuts.triggered.connect(self.abrir_configuracion_atajos)
        menu_config.addAction(action_shortcuts)

        menu_config.addSeparator()

        # Configurar usuario
        action_usuario = QAction("Usuario", self)
        action_usuario.triggered.connect(self.on_configurar_usuario)
        menu_config.addAction(action_usuario)

        # Configurar rutas
        action_rutas = QAction("Rutas", self)
        action_rutas.triggered.connect(self.on_configurar_rutas)
        menu_config.addAction(action_rutas)

        # Configurar carpeta de maquetas
        action_maquetas = QAction("Carpeta de maquetas", self)
        action_maquetas.triggered.connect(self.on_configurar_maquetas)
        menu_config.addAction(action_maquetas)

        # Secciones
        action_secciones = QAction("Secciones...", self)
        action_secciones.triggered.connect(self._abrir_config_secciones)
        menu_config.addAction(action_secciones)

        menu_config.addSeparator()

        # === Submenú Seleccionar Quark ===
        menu_quark = QMenu("Seleccionar Quark", self)

        # Crear acciones tipo radio (solo una puede estar tildada)
        accion_quark8 = QAction("Quark 8", self, checkable=True)
        accion_quark2018 = QAction("Quark 2018", self, checkable=True)

        # Cargar selección actual desde config.ini
        cfg = configparser.ConfigParser()
        cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
        seleccion_actual = cfg.get("quark", "quark_seleccionado", fallback="Quark 2018")
        self.tipo_quark = seleccion_actual
        accion_quark8.setChecked(seleccion_actual == "Quark 8")
        accion_quark2018.setChecked(seleccion_actual == "Quark 2018")
        

        # Conectar señales
        accion_quark8.triggered.connect(lambda: self.seleccionar_quark("Quark 8"))
        accion_quark2018.triggered.connect(lambda: self.seleccionar_quark("Quark 2018"))

        # Agrupar acciones para comportamiento tipo radio
        from PyQt5.QtWidgets import QActionGroup
        grupo_quark = QActionGroup(self)
        grupo_quark.addAction(accion_quark8)
        grupo_quark.addAction(accion_quark2018)
        grupo_quark.setExclusive(True)

        # Agregar acciones al submenú
        menu_quark.addAction(accion_quark8)
        menu_quark.addAction(accion_quark2018)

        # Insertar submenú en el menú Configuración existente
        menu_config.addMenu(menu_quark)



        # ------------------------------------------------------------
        # === PANEL IZQUIERDO ===
                # ------------------------------------------------------------
        # === PANEL IZQUIERDO (perfiles + stack Armado/Maquetación vs Armar mono) ===
        # ------------------------------------------------------------
        self.panel_izquierdo = QWidget()
        panel_izq_layout = QVBoxLayout(self.panel_izquierdo)
        self.panel_izquierdo.setLayout(panel_izq_layout)
        self.panel_izquierdo.setFixedWidth(400)

        # --- NUEVO SELECTOR DE PERFIL (switch con íconos) ---
        panel_izq_layout.addWidget(QLabel("Seleccione perfil de usuario:"))

        perfil_layout = QHBoxLayout()
        perfil_layout.setSpacing(10)

        # Botón: Armado y corrección
        self.btn_armado = QPushButton("Armado")
        self.btn_armado.setIcon(QIcon(resource_path("ui/assets/texto.png")))
        self.btn_armado.setIconSize(QSize(30, 30))
        self.btn_armado.setCheckable(True)

        # Botón: Maquetación y avisos
        self.btn_maquetacion = QPushButton("Maquetación")
        self.btn_maquetacion.setIcon(QIcon(resource_path("ui/assets/cmyk.png")))
        self.btn_maquetacion.setIconSize(QSize(30, 30))
        self.btn_maquetacion.setCheckable(True)

        self.btn_armado.setStyleSheet(style_btn)
        self.btn_maquetacion.setStyleSheet(style_btn)

        perfil_layout.addWidget(self.btn_armado)
        perfil_layout.addWidget(self.btn_maquetacion)
        panel_izq_layout.addLayout(perfil_layout)

        # Estado inicial
        self.btn_armado.setChecked(True)

        # Conexiones de perfil
        self.btn_armado.clicked.connect(lambda: self._set_perfil("Armado y corrección"))
        self.btn_maquetacion.clicked.connect(lambda: self._set_perfil("Maquetación y avisos"))

        # Label página activa (siempre arriba, compartida)
        self.label_pagina_activa = QLabel("Página activa: -")
        self.label_pagina_activa.setStyleSheet("font-weight: bold; font-size: 14px;")
        panel_izq_layout.addWidget(self.label_pagina_activa)

        # ----------------------------------------------------
        # STACK IZQUIERDO: [0] Armado/Maquetación  [1] Armar mono
        # ----------------------------------------------------
        self.stack_left = QStackedWidget()
        panel_izq_layout.addWidget(self.stack_left, 1)

        # ----------------------------------------------------
        # [0] PANEL ARMADO / MAQUETACIÓN (layout actual)
        # ----------------------------------------------------
        self.panel_armado_maquetacion = QWidget()
        arm_layout = QVBoxLayout(self.panel_armado_maquetacion)
        arm_layout.setContentsMargins(0, 0, 0, 0)
        arm_layout.setSpacing(6)

        # --- Info de asignación ---
        # Indicador de estado de página: fila de íconos circulares (Estado / Link / Información)
        _ax = lambda name: QPixmap(resource_path(f"ui/assets/{name}"))
        self.info_estado = CircleIconButton(_ax("estado.png"), "Estado de la página", "",
                                            icon_px=33, reservar_valor=True)
        self.info_link = CircleIconButton(_ax("link.png"), "Link",
                                          icon_px=33, reservar_valor=True)
        self.info_usuario = CircleIconButton(_ax("usuario.png"), "Información", "",
                                             icon_px=33, reservar_valor=True)
        self.info_link.clicked.connect(lambda: self._on_info_link_clicked())
        self.info_usuario.clicked.connect(lambda: self._on_info_usuario_clicked())

        self.info_scroll = QWidget()
        _info_row = QHBoxLayout(self.info_scroll)
        _info_row.setContentsMargins(6, 4, 6, 4)
        _info_row.setSpacing(0)
        _info_row.setAlignment(Qt.AlignTop)
        _info_row.addStretch()
        _info_row.addWidget(self.info_estado)
        _info_row.addStretch()
        _info_row.addWidget(self.info_link)
        _info_row.addStretch()
        _info_row.addWidget(self.info_usuario)
        _info_row.addStretch()

        arm_layout.addWidget(self.info_scroll)

        # --- Navegación entre noticias (02a, 02b...) ---
        nav_noticia_layout = QHBoxLayout()
        self.btn_prev_noticia = QPushButton("«")
        self.btn_next_noticia = QPushButton("»")
        for b in (self.btn_prev_noticia, self.btn_next_noticia):
            b.setStyleSheet(style_btn)
            b.setFixedWidth(40)

        self.label_noticia_titulo = QLabel("Noticia A")
        self.label_noticia_titulo.setAlignment(Qt.AlignCenter)
        self.label_noticia_titulo.setStyleSheet("""
            font-size: 15px;
            font-weight: bold;
            color: #ccc;
            padding: 3px 6px;
        """)
        self.label_noticia_titulo.setVisible(False)

        nav_noticia_layout.addWidget(self.btn_prev_noticia)
        nav_noticia_layout.addWidget(self.label_noticia_titulo, 1)
        nav_noticia_layout.addWidget(self.btn_next_noticia)

        self.btn_prev_noticia.clicked.connect(self._nav_prev_noticia)
        self.btn_next_noticia.clicked.connect(self._nav_next_noticia)

        self.btn_prev_noticia.setEnabled(False)
        self.btn_next_noticia.setEnabled(False)

        arm_layout.addLayout(nav_noticia_layout)

        # --- Visor de imagen (VisorPanelWidget) ---
        self.visor_panel = VisorPanelWidget(self)
        self.visor_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Señales del visor → slots de MainWindow
        self.visor_panel.foto_tapa_marcar.connect(self._on_visor_foto_tapa_marcar)
        self.visor_panel.foto_tapa_desmarcar.connect(self._on_visor_foto_tapa_desmarcar)
        self.visor_panel.imagen_eliminada.connect(self._on_visor_imagen_eliminada)
        self.visor_panel.imagen_renombrada.connect(self._on_visor_imagen_renombrada)
        self.visor_panel.abrir_en_editor_solicitado.connect(self._on_visor_abrir_en_editor)
        # Nuevas señales de selección de fotos de página
        self.visor_panel.foto_seleccionar.connect(self._on_visor_foto_seleccionar)
        self.visor_panel.foto_deseleccionar.connect(self._on_visor_foto_deseleccionar)
        self.visor_panel.usar_epigrafe.connect(self._on_visor_usar_epigrafe)
        self.visor_panel.imagen_navegada.connect(lambda _: self._refrescar_visor_seleccion())

        # Panel de fotos seleccionadas — oculto; el estado visual está en el pin del visor
        self.panel_fotos = PanelFotosPagina(self)
        self.panel_fotos.mover_arriba.connect(self._on_fotos_mover_arriba)
        self.panel_fotos.mover_abajo.connect(self._on_fotos_mover_abajo)
        self.panel_fotos.quitar.connect(self._on_fotos_quitar)
        self.panel_fotos.setVisible(False)

        # Compat: exponer atributos que otros métodos todavía referencian directamente
        self.img_scroll       = self.visor_panel.img_scroll
        self.image_label      = self.visor_panel.image_label
        self.label_nombre_img = self.visor_panel.label_nombre_img
        self.btn_prev         = self.visor_panel.btn_prev
        self.btn_next         = self.visor_panel.btn_next

        # --- Editor de texto ---
        self.texto_noticia = QTextEdit()
        self.texto_noticia.setReadOnly(True)
        self.texto_noticia.setStyleSheet("font-size: 16px;")
        self.texto_noticia.setMinimumHeight(80)
        self.DEFAULT_PLACEHOLDER = (
            "Aquí se mostrará el contenido de la noticia para editar y corregir"
        )
        try:
            self.texto_noticia.setPlaceholderText(self.DEFAULT_PLACEHOLDER)
        except Exception:
            pass

        # --- Lista de fragmentos ---
        self.lista_fragmentos = QListWidget()
        self.lista_fragmentos.setMaximumHeight(120)
        self.lista_fragmentos.setToolTip("Fragmentos de la noticia para pegar en Quark")
        self.lista_fragmentos.currentRowChanged.connect(self.on_fragment_selected)

        # Contenedor de fragmentos (lista + editor), va en la página 1 del stack.
        # parent=self evita que sea un top-level suelto antes de entrar al layout
        # (un contenedor sin parent con un widget pesado parpadea como ventana nativa).
        self._fragments_container = QWidget(self)
        _frag_v = QVBoxLayout(self._fragments_container)
        _frag_v.setContentsMargins(0, 0, 0, 0)
        _frag_v.setSpacing(4)
        _frag_v.addWidget(self.lista_fragmentos)
        _frag_v.addWidget(self.texto_noticia, stretch=1)

        # --- Panel de aviso (maqueta) — página 2 del stack ---
        self.maqueta_widget = MaquetaWidget(self.controller, parent=self)
        self.maqueta_widget.setMinimumHeight(150)
        self.maqueta_widget.setStyleSheet("background: #1e293b; border: 1px solid #333;")

        # Stack: 0 = fotos (visor), 1 = fragmentos, 2 = panel de aviso (maqueta)
        self.stack_info = QStackedWidget(self)
        self.stack_info.addWidget(self.visor_panel)
        self.stack_info.addWidget(self._fragments_container)
        self.stack_info.addWidget(self.maqueta_widget)
        self.stack_info.setCurrentIndex(0)

        # Solapas verticales: "Info de noticia" (arriba) y "Panel de aviso" (abajo).
        # Abrir una cierra la otra (estado mutuamente excluyente _panel_modo).
        self.tab_info_noticia = VerticalTabButton("Info de noticia", parent=self)
        self.tab_info_noticia.clicked.connect(self._toggle_info_noticia)
        self.tab_panel_aviso = VerticalTabButton("Panel de aviso", parent=self)
        self.tab_panel_aviso.clicked.connect(self._toggle_panel_aviso)
        self._panel_modo = 0            # 0=fotos, 1=fragmentos, 2=aviso
        self._info_noticia_expandido = False

        _tabs_col = QVBoxLayout()
        _tabs_col.setContentsMargins(0, 0, 0, 0)
        _tabs_col.setSpacing(4)
        _tabs_col.addWidget(self.tab_info_noticia, 1)
        _tabs_col.addWidget(self.tab_panel_aviso, 1)

        content_row = QHBoxLayout()
        content_row.setSpacing(4)
        content_row.addLayout(_tabs_col)
        content_row.addWidget(self.stack_info, stretch=1)
        arm_layout.addLayout(content_row, stretch=2)

        self.label_aviso_nombre = QLabel("Aviso: —")
        self.label_aviso_nombre.setStyleSheet(
            "font-size: 16px; color: #cccaca; font-weight: bold;"
        )
        self.label_aviso_nombre.setVisible(False)
        arm_layout.addWidget(self.label_aviso_nombre)

        # Estado de navegación
        self._noticias = []
        self._noticia_index = 0
        self._fotos_estado: dict = {}   # snapshot de fotos_seleccionadas.json de la noticia activa
        self.stack_left.addWidget(self.panel_armado_maquetacion)

        # ----------------------------------------------------
        # [1] PANEL "ARMAR MONO" (lista de notas del día)
        # ----------------------------------------------------
        self.panel_mono = QWidget()
        mono_layout = QVBoxLayout(self.panel_mono)
        mono_layout.setContentsMargins(0, 8, 0, 8)
        mono_layout.setSpacing(4)

        self.label_mono_titulo = QLabel("Armar mono – notas del día")
        self.label_mono_titulo.setStyleSheet("font-weight: bold; font-size: 13px;")
        mono_layout.addWidget(self.label_mono_titulo)

        self.pool_spinner = QtWidgets.QLabel(self.panel_mono)
        self.pool_spinner.setAlignment(Qt.AlignCenter)
        self.pool_spinner.setVisible(False)

        # Permitir transparencia real
        self.pool_spinner.setAttribute(Qt.WA_TranslucentBackground, True)
        self.pool_spinner.setStyleSheet("""
            background: transparent;
        """)

        # Cargar GIF transparente
        gif_path = resource_path("ui/assets/actualizando.gif")
        self.pool_spinner_movie = QMovie(gif_path)
        self.pool_spinner.setMovie(self.pool_spinner_movie)
        #self.pool_spinner_movie.setScaledSize(QSize(55, 55))

        # Cuando el GIF carga el primer frame, ajustar el tamaño
        def ajustar_tamaño():
            size = self.pool_spinner_movie.currentPixmap().size()
            if not size.isEmpty():
                self.pool_spinner.setFixedSize(size)

        self.pool_spinner_movie.frameChanged.connect(lambda _: ajustar_tamaño())


        # Lo colocamos arriba de la lista del pool (mono_lista)
        self.pool_spinner.raise_()


        barra_busqueda_layout = QHBoxLayout()
        self.mono_busqueda = QLineEdit()
        self.mono_busqueda.setPlaceholderText("Buscar por título o sección...")
        barra_busqueda_layout.addWidget(self.mono_busqueda)

        self.mono_orden = QComboBox()
        self.mono_orden.addItems([
            "Por sección",
            "Por título",
            "Por caracteres",
            "Por fecha",
            "Por hora ↑",
            "Por hora ↓",
            "Por palabras ↓",
            "Por palabras ↑",
            "Por texto ↓",
            "Por texto ↑",
        ])

        barra_busqueda_layout.addWidget(self.mono_orden)

        mono_layout.addLayout(barra_busqueda_layout)

        self.mono_busqueda.textChanged.connect(self._filtrar_y_ordenar_pool)
        self.mono_orden.currentIndexChanged.connect(self._filtrar_y_ordenar_pool)



        self.mono_lista = PoolTreeWidget()
        self.mono_lista.viewport().installEventFilter(self)

        self.mono_lista.setHeaderLabels(
            ["Estado", "Título", "Sección", "Caracteres", "Fecha"]
        )
        self.mono_lista.setRootIsDecorated(False)
        self.mono_lista.setIndentation(0)
        self.mono_lista.setUniformRowHeights(True)
        self.mono_lista.setAlternatingRowColors(True)
        self.mono_lista.setSelectionMode(QTreeWidget.SingleSelection)
        self.mono_lista.setMinimumHeight(120)
        self.mono_lista.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.mono_lista.setDragEnabled(True)
        self.mono_lista.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

        header = self.mono_lista.header()
        header.setStretchLastSection(False)
        self.mono_lista.setFocusPolicy(Qt.StrongFocus)

        # Estado
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.resizeSection(0, 40)  

        # Título (principal, amplio y redimensionable)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.resizeSection(1, 250)
        #header.setStretchLastSection(True)   # el stretch ahora va en "Título"

        # Sección (más chica)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.resizeSection(2, 70)

        # Caracteres
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.resizeSection(3, 60)

        # Fecha
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.resizeSection(4, 40)



        self.mono_lista.itemSelectionChanged.connect(self.on_pool_selection_changed)
        self.mono_lista.itemDoubleClicked.connect(self.on_pool_item_double_clicked)
        mono_layout.addWidget(self.mono_lista, stretch=1)

        # ── Botón Iniciar / Actualizar / Detener ──────────────────
        self.btn_pool_scan = QPushButton("Iniciar")
        self.btn_pool_scan.setFixedHeight(30)
        self.btn_pool_scan.setStyleSheet("""
            QPushButton { background:#1e293b; color:#e2e8f0;
                          border-radius:5px; padding:4px 12px; }
            QPushButton:hover   { background:#334155; }
            QPushButton:pressed { background:#475569; }
            QPushButton[detener=true] { background:#7f1d1d; color:#fca5a5; }
            QPushButton[detener=true]:hover { background:#991b1b; }
        """)
        self.btn_pool_scan.clicked.connect(self._on_btn_pool_scan_clicked)
        mono_layout.addWidget(self.btn_pool_scan)

        # Estado del hilo de scraping
        # Valores: "idle" | "iniciando" | "corriendo" | "deteniendo"
        # _pool_estado es la única fuente de verdad para el botón.
        # _pool_thread/_pool_worker solo se usan para ciclo de vida Qt.
        self._pool_thread = None
        self._pool_worker = None
        self._pool_estado = "idle"
        



        
        
        # Apenas se arma el panel MONO
        self.cargar_pool_hoy()

        self.stack_left.addWidget(self.panel_mono)

        # De inicio mostramos el panel normal, no el de mono
        self.stack_left.setCurrentWidget(self.panel_armado_maquetacion)

        # Finalmente añadir el panel izquierdo completo al layout principal
        layout.addWidget(self.panel_izquierdo)

        ### VISOR DE NOTICIAS DEL POOL ###
        self.pool_editor = PoolEditorDialog(self.controller, self)
        self.pool_editor.guardar_cambios.connect(self._on_pool_guardar_cambios)
        


        # bloquear DnD si el editor tiene cambios sin guardar
        self._pool_editor_activo = False

        

        # === PANEL DERECHO (toolbar + grilla) ===
        self.panel_derecho = QWidget()
        right_v = QVBoxLayout()
        self.panel_derecho.setLayout(right_v)

        # ----- Botonera horizontal (arriba de la grilla) -----
        toolbar = QHBoxLayout()
        
        self.boton_pegar = QPushButton("Pegar en Quark")
        # íconos mutables se asignan en los condicionales que los mutan
        self.boton_pegar.setIconSize(QSize(16,16))
        self.boton_pegar.setStyleSheet(style_btn + """
            border-top-right-radius: 0;
            border-bottom-right-radius: 0;
        """)
        self.boton_pegar.clicked.connect(self.on_pegar)
        self.boton_pegar.setEnabled(False)
        toolbar.addWidget(self.boton_pegar)

        # Abrir Quark: siempre creado, pero visible solo en Maquetación
        self.boton_abrir_quark = QPushButton("Abrir Quark")
        # íconos mutables se asignan en los condicionales que los mutan
        self.boton_abrir_quark.setIconSize(QSize(16,16))
        self.boton_abrir_quark.setStyleSheet(style_btn)
        self.boton_abrir_quark.clicked.connect(self.on_abrir_quark)
        self.boton_abrir_quark.setVisible(False)
        toolbar.addWidget(self.boton_abrir_quark)

        self.boton_quitar = QPushButton("Quitar asignación")
        # íconos mutables se asignan en los condicionales que los mutan
        self.boton_quitar.setIconSize(QSize(16,16))
        self.boton_quitar.setStyleSheet(style_btn)
        self.boton_quitar.clicked.connect(self.on_quitar)
        self.boton_quitar.setEnabled(False)
        toolbar.addWidget(self.boton_quitar)

        # --- Botón "+" para agregar otra noticia ---
        self.boton_agregar_nota = QPushButton("+")
        self.boton_agregar_nota.setToolTip("Agregar otra noticia a esta página")
        self.boton_agregar_nota.setFixedWidth(32)
        self.boton_agregar_nota.setIconSize(QSize(14, 14))
        self.boton_agregar_nota.setStyleSheet(style_btn + """
            border-top-left-radius: 0;
            border-bottom-left-radius: 0;
            font-size: 18px;
            padding: 2px;
        """)
        self.boton_agregar_nota.setEnabled(False)
        self.boton_agregar_nota.clicked.connect(self.on_agregar_nota)
        toolbar.addWidget(self.boton_agregar_nota)

        self.boton_mover = QPushButton("Mover")
        #self.boton_mover.setIcon(QIcon(resource_path("ui/assets/adelante.png")))
        self.boton_mover.setIconSize(QSize(16,16))
        self.boton_mover.setStyleSheet(style_btn)
        self.boton_mover.clicked.connect(self.on_mover)
        self.boton_mover.setEnabled(False)
        toolbar.addWidget(self.boton_mover)

        self.boton_devolver = QPushButton("Devolver")
        #self.boton_devolver.setIcon(QIcon(resource_path("ui/assets/atras.png")))
        self.boton_devolver.setIconSize(QSize(16,16))
        self.boton_devolver.setStyleSheet(style_btn)
        self.boton_devolver.clicked.connect(self.on_devolver)
        self.boton_devolver.setEnabled(False)
        toolbar.addWidget(self.boton_devolver)



        right_v.addLayout(toolbar)
        
        # === GRILLA DE PÁGINAS (debajo de la botonera) ===
        self.panel_paginas = QWidget()
        self.grid_layout = QGridLayout()
        self.panel_paginas.setLayout(self.grid_layout)

        # Llamada inicial para crear los botones según la pantalla
        self._crear_botones_grilla()

        # Ajustar tamaño de botones al redimensionar ventana
        right_v.addWidget(self.panel_paginas, stretch=1)
        layout.addWidget(self.panel_derecho, stretch=1)

        

        self.on_cambiar_perfil("Armado y corrección")


        # Avisos reales en falso al inicio
        self._avisos_real_cargando = False

        self.pagina_activa = None
        # --- Refrescar botones después de cargar ---
        self.colorear_paginas()
        # === Timer de polling (15s) ===
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.on_poll)

        # === Timer de pool de noticias === #
        self.pool_timer = QTimer(self)
        self.pool_timer.timeout.connect(self.on_pool_timer)
        self.pool_timer.setSingleShot(False)
        #self.pool_timer.start(600000)


        
        
        # --- Estado del poll asíncrono ---
        self._poll_thread = None
        self._poll_worker = None
        self._poll_running = False


        # Estado de sesión: arrancamos en reposo
        self.base_activa = False
        self._editor_windows: dict = {}
        



        # === Atajos de teclado (ShortcutManager) === funciones al final del archivo
        self.shortcut_mgr = ShortcutManager()
        self._setup_shortcuts()

    # === NAVEGACIÓN CON FLECHAS Y ENTER ===
        self._cols = 4
        self._total_pages = len(self.boton_paginas)
        # El filtro debe instalarse a nivel de aplicación para recibir eventos
        # aunque el foco esté en otros widgets (botones, listas, etc.)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.statusBar().setStyleSheet("""
        QStatusBar {
            background-color: #0f172a;
            color: #e2e8f0;
            border-top: 1px solid #334155;
        }
    """)
        
    
        # Cambiar color de barra superior (Windows 10/11)
        dwmapi = ctypes.WinDLL("dwmapi")
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36

        hwnd = self.winId().__int__()
        
        color = 0x002E1F16      # formato 0x00BBGGRR → #161f2e (más oscuro)



        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                             ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int(1)))

        # Color de fondo (oscuro)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR,
                             ctypes.byref(ctypes.c_int(color)), ctypes.sizeof(ctypes.c_int(color)))

        # Color del texto (blanco)
        text_color = 0x00F0F0F0
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR,
                             ctypes.byref(ctypes.c_int(text_color)), ctypes.sizeof(ctypes.c_int(text_color)))
        

        

        
    def _crear_botones_grilla(self):
        """Crea o reajusta los botones de página según el tamaño de la pantalla."""
        screen = QApplication.primaryScreen().availableGeometry()
        screen_w, screen_h = screen.width(), screen.height()

        # Base: 1366x768 → 120x120
        scale_w = screen_w / 1366
        scale_h = screen_h / 768
        scale = min(scale_w, scale_h)

        btn_size = int(120 * scale)
        spacing = int(15 * scale)

        self.grid_layout.setSpacing(spacing)
        self.grid_layout.setContentsMargins(spacing, spacing, spacing, spacing)

        # Si ya existen, solo actualizamos tamaño
        if hasattr(self, "boton_paginas") and self.boton_paginas:
            for boton in self.boton_paginas.values():
                boton.setFixedSize(btn_size, btn_size)
            return

        # Si no existen, los creamos
        self.boton_paginas = {}
        for i in range(1, 17):
            boton = PageButton(i)
            boton.setFixedSize(btn_size, btn_size)
            boton.setStyleSheet("background-color: lightgray; font-size: 18px; border-radius:8px;")
            boton.clicked.connect(lambda _, n=i: self.on_click_pagina(n))
            boton.doubleClicked.connect(self.on_doble_click_pagina)
            boton.ajustesClicked.connect(self.on_ajustes_menu_requested)
            boton.setContextMenuPolicy(Qt.CustomContextMenu)
            boton.customContextMenuRequested.connect(
                lambda pos, n=i, b=boton: self.on_context_menu_requested(n, b.mapToGlobal(pos))
            )
            fila = (i - 1) // 4
            col = (i - 1) % 4
            self.grid_layout.addWidget(boton, fila, col)
            self.boton_paginas[i] = boton


        
    def eventFilter(self, obj, event):
        """Captura teclas globales para navegación de páginas (solo cuando MainWindow está activa)."""
        from PyQt5.QtGui import QKeyEvent
        if not (event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent)):
            return super().eventFilter(obj, event)

        # Solo cuando MainWindow es la ventana activa
        if QApplication.activeWindow() is not self:
            return super().eventFilter(obj, event)

        # No interferir si hay modal/popup (diálogos, menús contextuales)
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return super().eventFilter(obj, event)

        # No interceptar si el pool editor está visible
        if self.pool_editor.isVisible():
            return super().eventFilter(obj, event)

        key = event.key()

        # No interceptar si el foco está en un editor de texto dentro de esta ventana
        widget = self.focusWidget()
        from PyQt5.QtWidgets import (
            QLineEdit, QTextEdit, QPlainTextEdit,
            QComboBox, QListWidget, QTreeWidget, QTreeView,
        )
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit,
                               QComboBox, QListWidget, QTreeWidget, QTreeView)):
            return super().eventFilter(obj, event)

        if not getattr(self, "base_activa", False):
            return super().eventFilter(obj, event)

        if key in (Qt.Key_Right, Qt.Key_Left, Qt.Key_Up, Qt.Key_Down):
            self._move_focus(key)
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._activate_current_page()
            return True

        return super().eventFilter(obj, event)

    def _move_focus(self, key):
        """Mueve la selección en la grilla respetando filas/columnas."""
        if not getattr(self, "base_activa", False):
            return

        # Si no hay activa, arrancamos desde la primera
        current_idx = 0 if not self.pagina_activa else self.pagina_activa - 1

        cols = self._cols
        total = self._total_pages
        rows = (total + cols - 1) // cols

        row, col = divmod(current_idx, cols)

        if key == Qt.Key_Right:
            col += 1
        elif key == Qt.Key_Left:
            col -= 1
        elif key == Qt.Key_Down:
            row += 1
        elif key == Qt.Key_Up:
            row -= 1

        # wrap vertical
        row %= rows

        # última columna válida en esa fila (maneja filas incompletas)
        last_col_in_row = min(cols - 1, (total - 1) - row * cols)

        # wrap horizontal dentro de la fila real
        if col < 0:
            col = last_col_in_row
        elif col > last_col_in_row:
            col = 0

        new_idx = row * cols + col
        if new_idx >= total:
            new_idx = total - 1

        numero = new_idx + 1
        self.on_click_pagina(numero)


    def _activate_current_page(self):
        """Simula doble clic en la página activa"""
        if not self.pagina_activa:
            return
        boton = self.boton_paginas.get(self.pagina_activa)
        if boton:
            boton.doubleClicked.emit(self.pagina_activa)


    # === EVENTOS ===
    def _wrap_lines(self, text: str, font_px: int, max_width: int, max_lines: int = 2) -> list[str]:
        """
        Devuelve una lista de líneas envueltas para que quepan en max_width.
        - Rompe por palabras; si una palabra sola no entra, corta dentro de la palabra.
        - Limita a max_lines y agrega '…' si recorta.   
        """
        text = (text or "").strip()
        if not text:
            return []

        # Medición con el mismo tamaño que usaremos en el botón
        f = QFont(self.font())
        f.setPixelSize(font_px)
        fm = QFontMetrics(f)

        words = text.split()
        lines: list[str] = []
        current = ""

        def push_line(line):
            nonlocal lines
            if line:
                lines.append(line)

        i = 0
        while i < len(words):
            w = words[i]
            tentative = (current + " " + w).strip()
            if fm.horizontalAdvance(tentative) <= max_width or not current:
                current = tentative
                i += 1
            else:
                # si la palabra sola no entra, partirla
                if not current and fm.horizontalAdvance(w) > max_width:
                    cut = len(w)
                    while cut > 1 and fm.horizontalAdvance(w[:cut]) > max_width:
                        cut -= 1
                    push_line(w[:cut])
                    words[i] = w[cut:]
                else:
                    push_line(current)
                    current = ""
            if max_lines and len(lines) >= max_lines:
                break

        if current and (not max_lines or len(lines) < max_lines):
            push_line(current)

        # Si sobraron palabras y ya estamos al límite, elidir con …
        if max_lines and (i < len(words) or (current and len(lines) >= max_lines)):
            last = lines[-1] if lines else ""
            ell = "…"
            while last and fm.horizontalAdvance(last + ell) > max_width:
                last = last[:-1]
            if last:
                lines[-1] = last + ell

        return lines

    # === Handlers: lanzar Chrome y actualizar estado ===
    def on_launch_chrome_debug(self):
        """
        Lanza Chrome con --remote-debugging-port en el perfil dedicado.
        La configuración se completa automáticamente si faltan claves.
        """
        ok, msg = self.controller.launch_chrome_debug()
        #if ok:
        #    QMessageBox.information(self, "Chrome (debug)",
        #                            "Se lanzó Chrome en modo depuración.\n"
        #                            "Usá esa ventana para loguearte una vez con 2FA.")
            
        if not ok:
            QMessageBox.warning(self, "Chrome (debug)", msg)
            





    def closeEvent(self, event):
        # Parar watchers/timers para que el proceso realmente termine (evita zombie:
        # un proceso cuyo ChromeWatcher sigue escaneando Downloads tras cerrar la ventana).
        for attr in ("_chrome_watcher", "_pdf_watcher", "timer"):
            w = getattr(self, attr, None)
            try:
                if w is not None:
                    w.stop()
            except Exception as e:
                _log.warning("[WARN] Al detener %s: %s", attr, e)

        # Joinear el thread de poll si sigue vivo
        th = getattr(self, "_poll_thread", None)
        try:
            if th is not None and th.isRunning():
                th.quit()
                th.wait(3000)
        except Exception as e:
            _log.warning("[WARN] Al cerrar poll thread: %s", e)

        try:
            # Apagar cola de scraping (si existe)
            if hasattr(self, "controller") and self.controller:
                self.controller.stop_queue()
        except Exception as e:
            _log.warning(f"[WARN] Al cerrar: {e}")

        _log.info("MainWindow.closeEvent: watcher/threads detenidos, cerrando PID=%d", os.getpid())
        super().closeEvent(event)


    def on_configurar_usuario(self):
        """
        Abre un diálogo para configurar el nombre de usuario y lo persiste en config.ini (raíz).
        No toca estados; solo guarda y actualiza self.controller.usuario si corresponde.
        """
        ini_path = Config.CONFIG_FILE
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        cfg = configparser.ConfigParser()
        if ini_path.exists():
            cfg.read(str(ini_path), encoding="utf-8")

        actual = ""
        if cfg.has_section("USUARIO"):
            actual = (cfg.get("USUARIO", "user", fallback="") or "").strip()

        nuevo, ok = QInputDialog.getText(self, "Configurar usuario", "Nombre de usuario:", text=actual)
        nuevo = (nuevo or "").strip()
        if not ok:
            return
        if not cfg.has_section("USUARIO"):
            cfg.add_section("USUARIO")
        cfg.set("USUARIO", "user", nuevo)

        with open(ini_path, "w", encoding="utf-8") as f:
            cfg.write(f)

        # Si la base ya está activa, podés actualizar el controller en caliente
        if getattr(self, "base_activa", False) and nuevo:
            self.controller.usuario = nuevo

            # Evitar crash si el INI de páginas aún no existe
            ini = self.controller.file_service._shared_ini_path()
            if ini and ini.exists():
                self.controller.refrescar_avisos_desde_ini()

            self.colorear_paginas()
            if getattr(self, "pagina_activa", None):
                self._update_label_asignacion(self.pagina_activa)



    def abrir_dialogo_mono(self):
        r = self.controller.rutas
        
        # Debe existir una base activa
        if not getattr(self, "base_activa", False):
            QMessageBox.warning(
                self,
                "Falta inicializar",
                "Primero conectate a la Base con Ctrl + B para generar la estructura de páginas."
            )
            return

        # Detectar carpeta "materiales"
        if not r.quark_output_dir:
            QMessageBox.warning(self, "Error", "No se detectó la carpeta base de edición.")
            return

        materiales = r.quark_output_dir / "materiales"
        if not materiales.exists():
            QMessageBox.warning(
                self,
                "Base incompleta",
                "No se encontró la carpeta 'materiales'. Volvé a crear la Base."
            )
            return

        # OK → abrir diálogo
        dlg = DialogoMono(self.controller, parent=self)
        dlg.exec_()


    def on_doble_click_pagina(self, numero: int):
        """Abre el archivo asociado a la página.
        Abre Quark 8 o 2018 según lo seleccionado en config.ini.
        """
        if not getattr(self, "base_activa", False):
            return

        pagina = self.controller.gestor_paginas.obtener_pagina(numero)

        # 1) Buscar QXP o PDF en destinos conocidos (base/mandar/final/apdf/pdf)
        resultado = self.controller.archivo_asociado_a_estado(numero)

        # archivo_asociado_a_estado puede devolver TXT — descartarlo aquí
        if resultado and resultado.suffix.lower() not in (".pdf", ".qxp"):
            resultado = None

        # 2) Si no hay QXP/PDF en destinos, buscar en materiales (estado "proceso")
        if not resultado:
            resultado = self.controller.file_service.find_qxp_en_materiales(numero)

        # 3) Fallback: si no hay QXP ni PDF y la página tiene texto → abrir editor
        if not resultado or not resultado.exists():
            if pagina and (pagina.asignado or getattr(pagina, "asignada_por_ini", False)):
                self._abrir_editor_nota(numero)
                return

        
        # ✅ Unificado: siempre un Path o None
        if resultado and resultado.exists():
            archivos = [resultado]
        else:
            archivos = []

        if not archivos:
            QMessageBox.information(
                self,
                "Archivo no encontrado",
                f"No se encontró ningún archivo para abrir en la página {numero} según su estado."
            )
            return

        # Leer configuración de Quark seleccionado
        config = configparser.ConfigParser()
        config.read(str(Config.CONFIG_FILE), encoding="utf-8")
        

        quark_sel = config.get("quark", "quark_seleccionado", fallback="Quark 8").strip().lower()
        if "quark 8" in quark_sel:
            quark_exe = config.get("apps", "quark8", fallback=None)
        else:
            quark_exe = config.get("apps", "quark2018", fallback=None)

        if not quark_exe or not Path(quark_exe).exists():
            QMessageBox.warning(
                self,
                "Error",
                f"No se encontró la ruta al ejecutable de {quark_sel}.\nVerificá la sección [apps] en config.ini."
            )
            return

        # Abrir archivos según tipo
        abrio_pdf = False
        for archivo in archivos:
            if archivo.suffix.lower() == ".pdf":
                abrio_pdf = True
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(archivo)))
            elif archivo.suffix.lower() == ".qxp":
                try:
                    # Detectar si se usa Quark 8 → abrir mediante asociación del sistema
                    if "quark 8" in quark_sel:
                        os.startfile(str(archivo))
                    else:
                        subprocess.Popen([quark_exe, str(archivo)])
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "Error al abrir Quark",
                        f"No se pudo abrir {archivo}:\n{e}"
                    )

        # Si se abrió algún QXP, ejecutar la maximización de Quark
        if any(a.suffix.lower() == ".qxp" for a in archivos):
            QTimer.singleShot(1200, self._maximizar_quark)


        # Si se abrió al menos un PDF, activar overlay lector de QR (no bloquea la UI)
        try:
            if abrio_pdf:
                self._activate_qr_mode()

        except Exception as e:
            _log.warning(f"[QR] No se pudo iniciar overlay: {e}")



    def _abrir_editor_nota(self, numero: int, noticia_index: int = 0):
        existing = self._editor_windows.get(numero)
        if existing is not None and existing.isVisible():
            existing.activateWindow()
            existing.raise_()
            return
        from ui.editor_nota_window import EditorNotaWindow
        from config.config import Config
        mq_cfg = Config().maqueta_config
        win = EditorNotaWindow(numero, noticia_index, self.controller, mq_cfg, parent=self)
        win.nota_guardada.connect(self._on_nota_editada)
        win.nota_guardada_para_armar.connect(self._on_nota_guardada_para_armar)
        win.setAttribute(Qt.WA_DeleteOnClose, True)

        # Marcar "en edición" al abrir
        self._set_editando(numero, True)

        def _on_editor_closed():
            self._set_editando(numero, False)
            self._editor_windows.pop(numero, None)

        win.destroyed.connect(_on_editor_closed)
        win.show()
        self._editor_windows[numero] = win

    def _set_editando(self, numero: int, valor: bool):
        try:
            self.controller.file_service.write_page_entry(numero, editando="true" if valor else "false")
            pag = self.controller.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.editando = valor
            boton = self.boton_paginas.get(numero)
            if isinstance(boton, PageButton):
                boton.set_editando_flag(valor)
        except Exception:
            pass

    def _accion_descartar_editando(self, numero: int):
        self._set_editando(numero, False)
        self.statusBar().showMessage(f"Página {numero}: notificación de edición descartada", 3000)

    def _on_nota_editada(self, numero: int):
        self.mostrar_fragmentos(numero)
        self.colorear_paginas()

    def _accion_descartar_para_armar(self, numero: int):
        try:
            self.controller.file_service.write_page_entry(numero, listo_para_armar="false")
            pag = self.controller.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.listo_para_armar = False
            boton = self.boton_paginas.get(numero)
            if isinstance(boton, PageButton):
                boton.set_listo_flag(False)
            self.statusBar().showMessage(f"Página {numero}: descartado para armar", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def _on_nota_guardada_para_armar(self, numero: int):
        self._on_nota_editada(numero)
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        if pag:
            pag.listo_para_armar = True
        try:
            self.controller.file_service.write_page_entry(numero, listo_para_armar="true")
        except Exception:
            pass
        boton = self.boton_paginas.get(numero)
        if isinstance(boton, PageButton):
            boton.set_listo_flag(True)

    # === Menú contextual (botón derecho) ===

    # Carga las secciones desde config.ini
    def _get_secciones_config(self) -> list[str]:
        ini_path = Config.CONFIG_FILE
        cfg = configparser.ConfigParser()
        if ini_path.exists():
            cfg.read(str(ini_path), encoding="utf-8")
        raw = cfg.get("SECCIONES", "secciones", fallback="")
        return [s.strip() for s in raw.split(",") if s.strip()]


    def on_context_menu_requested(self, numero: int, global_pos):
        """
        Construye y muestra el menú contextual para la página `numero`.
        Selecciona la página como activa sin disparar diálogos.
        Etiquetas dinámicas: Abrir (PDF/Quark), Mover/Devolver (→ destino).
        """
        if not getattr(self, "base_activa", False):
            return

        self._refresh_after_action(numero)

        # 2) Estado actual y decisiones
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        archivo = self.controller.archivo_asociado_a_estado(numero)
        # Si devolvió TXT (no QXP/PDF), verificar también materiales (estado "proceso")
        if archivo and archivo.suffix.lower() not in (".pdf", ".qxp"):
            qxp_mat = self.controller.file_service.find_qxp_en_materiales(numero)
            if qxp_mat:
                archivo = qxp_mat
        decision = self.controller.decidir_botones(numero)

        tiene_txt = bool(pag.asignado)
        tiene_aviso_full = bool(getattr(pag, "aviso_full", False))
        tiene_aviso_half = bool(getattr(pag, "aviso_half", False))
        tiene_aviso_footer = bool(getattr(pag, "aviso_footer", False))
        #hay_algo = bool(
        #    tiene_txt
        #    or getattr(pag, "asignada_por_ini", False)
        #    or tiene_aviso_full or tiene_aviso_half or tiene_aviso_footer
        #)

        indice = getattr(self, "_noticia_index", 0)
        frags = self.controller.obtener_fragmentos(numero, indice)
        puede_pegar = bool(tiene_txt and frags)

        # Etiqueta dinámica para "Abrir"
        abrir_label = "Abrir (Quark/PDF según el caso)"
        if isinstance(archivo, list) and archivo:
            archivo = archivo[0]

        if archivo and archivo.exists():
            suf = archivo.suffix.lower()
            if suf == ".pdf":
                abrir_label = "Abrir PDF"
            elif suf == ".qxp":
                abrir_label = "Abrir en Quark"


        mover_info = decision.get("mover", {})
        devolver_info = decision.get("devolver", {})

        def _friendly_dest_label(pathlike):
            try:
                p = Path(pathlike) if pathlike else None
            except Exception:
                p = None
            if not p:
                return ""
            name = p.name
            parent = p.parent.name if p.parent else ""
            if p.suffix:
                name = p.parent.name
                parent = p.parent.parent.name if p.parent and p.parent.parent else ""
            m = {
                "OK": "OK",
                "mandar": "Mandar",
                "final": "Final",
                "VAULT": "VAULT",
                "En proceso": "En proceso"
            }
            if name in m:
                return m[name]
            if parent.lower() in ("final", "mandar"):
                return parent.capitalize()
            return name

        mover_label = mover_info.get("label", "Mover")
        if mover_info.get("dest"):
            mover_dest = _friendly_dest_label(mover_info.get("dest"))
            if mover_dest:
                mover_label = f"{mover_label} → {mover_dest}"

        devolver_label = devolver_info.get("label", "Devolver")
        if devolver_info.get("dest"):
            devolver_dest = _friendly_dest_label(devolver_info.get("dest"))
            if devolver_dest:
                devolver_label = f"{devolver_label} → {devolver_dest}"

        menu = QMenu(self)

        abrir_act = QAction(abrir_label, self)
        abrir_act.setEnabled(bool(archivo and archivo.exists()))
        abrir_act.triggered.connect(lambda: self._accion_abrir_asociado(numero))
        menu.addAction(abrir_act)


        # ---- Descartar PDF (según estado) ----
        try:
            pdf_path_desc = self.controller.pdf_path_para_descartar(numero)
        except Exception:
            pdf_path_desc = None

        descartar_pdf_act = QAction("Descartar PDF", self)
        descartar_pdf_act.setEnabled(bool(pdf_path_desc))
        descartar_pdf_act.triggered.connect(lambda: self._accion_descartar_pdf(numero))
        menu.addAction(descartar_pdf_act)

        _qxps = self.controller.file_service.listar_qxp_todas_ubicaciones(numero)
        descartar_qxp_act = QAction("Descartar QXP", self)
        descartar_qxp_act.setEnabled(bool(_qxps))
        descartar_qxp_act.triggered.connect(lambda: self._accion_descartar_qxp(numero))
        menu.addAction(descartar_qxp_act)

        menu.addSeparator()
        # --- Pegar en Quark (solo si asignación local + hay fragmentos) ---
        asignacion_local = bool(getattr(pag, "asignada_por_ini", False))
        puede_pegar = bool(asignacion_local and frags)

        # --- Pegar en Quark  /  Abrir imagen (según perfil) ---
        if self.controller.perfil == "Maquetación y avisos":
            pegar_act = QAction("Abrir imagen", self)
            pegar_act.setEnabled(bool(self.controller.file_service.find_material_image_for_page(numero)))
            pegar_act.triggered.connect(lambda: self._accion_abrir_imagen(numero))
        else:
            # Armado: como antes
            asignacion_local = bool(getattr(pag, "asignada_por_ini", False))
            puede_pegar = bool(asignacion_local and frags)
            pegar_act = QAction("Pegar en Quark", self)
            pegar_act.setEnabled(puede_pegar)
            pegar_act.triggered.connect(lambda: self._accion_pegar_quark(numero))
        menu.addAction(pegar_act)

        if self.controller.perfil == "Armado y corrección":
            pagina_cm = self.controller.gestor_paginas.obtener_pagina(numero)
            if pagina_cm and pagina_cm.asignado:
                act_editor = menu.addAction("Abrir editor de nota")
                act_editor.triggered.connect(lambda: self._abrir_editor_nota(numero))

        menu.addSeparator()
        if self.controller.perfil != "Maquetación y avisos":
            submenu = QMenu("Asignación / avisos", self)

            tiene_txt = bool(pag.asignado)
            asignada_cualquiera = bool(getattr(pag, "asignada_por_ini", False))
            completa = bool(tiene_aviso_full)
            
                
            if not tiene_txt and not completa:
                act_cargar = QAction("Cargar link…", self)
                if self._pool_estado != "idle":
                    act_cargar.setEnabled(False)
                    act_cargar.setToolTip("El bot está en uso con la lista de noticias. Esperá a que termine.")
                else:
                    act_cargar.triggered.connect(lambda n=numero: self._accion_asignar_texto(n))
                submenu.addAction(act_cargar)

                def _asignar_manual():
                    try:
                        fs = self.controller.file_service
                        txt_path = fs.crear_txt_manual(numero)
                        fs.write_page_entry(
                            numero,
                            txt_name=txt_path.name,
                            assigned=True,
                            estado="proceso",
                            by=self.controller.usuario
                        )
                        pag2 = self.controller.gestor_paginas.obtener_pagina(numero)
                        if pag2:
                            pag2.asignado = True
                            pag2.asignada_por_ini = True

                        self._despues_de_cambio_estado(numero)
                        self.actualizar_info_pagina(pag2)
                    except Exception as e:
                        QMessageBox.critical(self, "Asignar sin material", str(e))

                act_manual = QAction("Asignar sin material", self)
                act_manual.triggered.connect(_asignar_manual)
                submenu.addAction(act_manual)

            else:
                if asignada_cualquiera:
                    act_quitar = QAction("Quitar asignación", self)
                    act_quitar.triggered.connect(lambda: self._accion_quitar_asignacion(numero))
                    submenu.addAction(act_quitar)
                else:
                    act_asignar = QAction("Asignar", self)
                    act_asignar.triggered.connect(lambda: self.on_quitar())
                    submenu.addAction(act_asignar)

                 # --- Submenú dinámico para borrar noticias ---
                fs = self.controller.file_service
                subnotas = []
                try:
                    # Carpeta de materiales de la página (ej. materiales/P06)
                    folder = fs.material / f"P{numero:02d}"
                    subnotas = []
                    if folder.exists():
                        # Buscar subnotas dentro de Pxx/ (ej. P06/06a/06a.txt, P06/06b/06b.txt)
                        subnotas = sorted(
                            p for p in folder.glob("*/*.txt")
                            if not p.stem.startswith("original_")
                        )

                except Exception:
                    pass

                if len(subnotas) <= 1:
                    # Solo una noticia → acción directa
                    act_quitar_txt = QAction("Borrar noticia", self)
                    act_quitar_txt.triggered.connect(lambda: self._accion_borrar_noticia(numero, 0))
                    submenu.addAction(act_quitar_txt)
                else:
                    # Varias noticias → submenú etiquetado por sufijo+rol real
                    sub_borrar = QMenu("Borrar noticia", self)
                    for idx, txt_path in enumerate(subnotas):
                        suf = txt_path.parent.name[-1]
                        rol = fs.sufijo_a_rol(suf)
                        act = QAction(f"Noticia {suf.upper()} ({rol})", self)
                        act.triggered.connect(lambda _, i=idx: self._accion_borrar_noticia(numero, i))
                        sub_borrar.addAction(act)
                    submenu.addMenu(sub_borrar)

        else:
            # En Maquetación solo mostramos avisos
            submenu = QMenu("Avisos", self)
            act_limpiar = QAction("Limpiar aviso", self)
            act_limpiar.triggered.connect(lambda: self._accion_limpiar_aviso(numero))
            submenu.addAction(act_limpiar)
            submenu.addSeparator()


        # Opciones de avisos (comunes a ambos perfiles)
        submenu.addSeparator()
        # Asignar aviso manual — disponible en ambos perfiles
        act_asignar_aviso = QAction("Asignar aviso…", self)
        act_asignar_aviso.triggered.connect(lambda: self._accion_asignar_aviso_archivo(numero))
        submenu.addAction(act_asignar_aviso)

        act_full = QAction("Página completa", self)
        act_full.triggered.connect(lambda: self._accion_asignar_aviso_full(numero))
        submenu.addAction(act_full)

        act_half = QAction("Media página", self)
        act_half.triggered.connect(lambda: self._accion_asignar_aviso_half(numero))
        submenu.addAction(act_half)

        act_robapagina = QAction("Robapágina", self)
        act_robapagina.triggered.connect(lambda: self._accion_asignar_aviso_robapagina(numero))
        submenu.addAction(act_robapagina)


        act_footer = QAction("Pie de página", self)
        act_footer.triggered.connect(lambda: self._accion_asignar_aviso_footer(numero))
        submenu.addAction(act_footer)

        submenu.addSeparator()
        act_clear = QAction("Quitar avisos", self)
        act_clear.triggered.connect(lambda: self._accion_quitar_avisos(numero))
        submenu.addAction(act_clear)

        submenu.addSeparator()
        
        act_quitar_link = QAction("Quitar link", self)
        act_quitar_link.triggered.connect(
            lambda n=numero: self._accion_quitar_link(n)
            )
        submenu.addAction(act_quitar_link)
        
        # --- Submenú Sección ---
        submenu_seccion = QMenu("Sección", self)
        seccion_actual = (pag.seccion or "").strip()
        opciones = self._get_secciones_config()

        for opcion in opciones:
            act = QAction(opcion, self)
            if seccion_actual and opcion.lower() == seccion_actual.lower():
                act.setCheckable(True)
                act.setChecked(True)
            act.triggered.connect(lambda _, o=opcion: self._accion_set_seccion(numero, o))
            submenu_seccion.addAction(act)

        if seccion_actual:
            submenu_seccion.addSeparator()
            act_clear = QAction("Limpiar sección", self)
            act_clear.triggered.connect(lambda: self._accion_clear_seccion(numero))
            submenu_seccion.addAction(act_clear)

        menu.addMenu(submenu_seccion)



        menu.addMenu(submenu)
        menu.addSeparator()

        # --- Enrocar páginas (intercambio de contenido) ---
        sub_enroque = QMenu("Enrocar páginas", self)
        act_enroque_av = QAction("Con aviso", self)
        act_enroque_av.triggered.connect(lambda: self._iniciar_enroque(numero, True))
        sub_enroque.addAction(act_enroque_av)
        act_enroque_sin = QAction("Sin aviso", self)
        act_enroque_sin.triggered.connect(lambda: self._iniciar_enroque(numero, False))
        sub_enroque.addAction(act_enroque_sin)
        menu.addMenu(sub_enroque)
        menu.addSeparator()

        mover_dest = mover_info.get("dest")
        devolver_dest = devolver_info.get("dest")

        mover_act = QAction(f"Mover → { _friendly_dest_label(mover_dest) }" if mover_dest else "Mover", self)
        mover_act.setEnabled(bool(mover_dest))
        mover_act.triggered.connect(lambda: self._accion_mover(numero))
        menu.addAction(mover_act)

        devolver_act = QAction(f"Devolver → { _friendly_dest_label(devolver_dest) }" if devolver_dest else "Devolver", self)
        devolver_act.setEnabled(bool(devolver_dest))
        devolver_act.triggered.connect(lambda: self._accion_devolver(numero))
        menu.addAction(devolver_act)

        if self.controller.perfil == "Maquetación y avisos":
            abrir_qxp_act = QAction("Abrir Quark", self)
            can_qxp = bool(self.controller.file_service.find_qxp_final(numero)
                           or self.controller.file_service.find_qxp_base(numero))
            abrir_qxp_act.setEnabled(can_qxp)
            abrir_qxp_act.triggered.connect(lambda: self._accion_abrir_quark(numero))
            menu.addAction(abrir_qxp_act)

        menu.addSeparator()

        act_tapa_foto = QAction("Marcar foto de tapa", self)
        act_tapa_foto.triggered.connect(lambda: self._accion_marcar_tapa_foto(numero))
        menu.addAction(act_tapa_foto)

        act_tapa_titulo = QAction("Marcar título de tapa", self)
        act_tapa_titulo.triggered.connect(lambda: self._accion_marcar_tapa_titulo(numero))
        menu.addAction(act_tapa_titulo)

        act_tapa_clear = QAction("Quitar título/foto de tapa", self)
        act_tapa_clear.triggered.connect(lambda: self._accion_limpiar_tapa(numero))
        menu.addAction(act_tapa_clear)


        # --- Descartar para armar (solo cuando el flag está activo) ---
        if getattr(pag, "listo_para_armar", False) or getattr(pag, "editando", False):
            menu.addSeparator()
        if getattr(pag, "listo_para_armar", False):
            act_descartar_armar = QAction("Descartar para armar", self)
            act_descartar_armar.triggered.connect(
                lambda: self._accion_descartar_para_armar(numero)
            )
            menu.addAction(act_descartar_armar)
        if getattr(pag, "editando", False):
            act_descartar_edit = QAction("Descartar notificación de edición", self)
            act_descartar_edit.triggered.connect(
                lambda: self._accion_descartar_editando(numero)
            )
            menu.addAction(act_descartar_edit)

        menu.exec_(global_pos)

    # ══════════════════════════════════════════════════════════════════
    # Menú radial de ajustes (ícono en el botón de página)
    # ══════════════════════════════════════════════════════════════════

    def _subnotas_de(self, numero: int):
        fs = self.controller.file_service
        folder = fs.material / f"P{numero:02d}"
        if not folder.exists():
            return []
        return sorted(p for p in folder.glob("*/*.txt")
                      if not p.stem.startswith("original_"))

    def _menu_seccion(self, numero: int) -> QMenu:
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)
        seccion_actual = (getattr(pag, "seccion", "") or "").strip()
        for opcion in self._get_secciones_config():
            act = QAction(opcion, self)
            if seccion_actual and opcion.lower() == seccion_actual.lower():
                act.setCheckable(True); act.setChecked(True)
            act.triggered.connect(lambda _, o=opcion: self._accion_set_seccion(numero, o))
            m.addAction(act)
        if seccion_actual:
            m.addSeparator()
            act_clear = QAction("Limpiar sección", self)
            act_clear.triggered.connect(lambda: self._accion_clear_seccion(numero))
            m.addAction(act_clear)
        return m

    def _menu_avisos(self, numero: int) -> QMenu:
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)
        for label, slot in (
            ("Página completa", self._accion_asignar_aviso_full),
            ("Media página", self._accion_asignar_aviso_half),
            ("Robapágina", self._accion_asignar_aviso_robapagina),
            ("Pie de página", self._accion_asignar_aviso_footer),
        ):
            act = QAction(label, self)
            act.triggered.connect(lambda _, s=slot: s(numero))
            m.addAction(act)
        m.addSeparator()
        act_clear = QAction("Quitar avisos", self)
        act_clear.triggered.connect(lambda: self._accion_quitar_avisos(numero))
        m.addAction(act_clear)
        return m

    def _menu_enrocar(self, numero: int) -> QMenu:
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)
        a1 = QAction("Con aviso", self)
        a1.triggered.connect(lambda: self._iniciar_enroque(numero, True))
        m.addAction(a1)
        a2 = QAction("Sin aviso", self)
        a2.triggered.connect(lambda: self._iniciar_enroque(numero, False))
        m.addAction(a2)
        return m

    def _menu_borrar(self, numero: int) -> QMenu:
        fs = self.controller.file_service
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)
        for idx, txt_path in enumerate(self._subnotas_de(numero)):
            suf = txt_path.parent.name[-1]
            rol = fs.sufijo_a_rol(suf)
            act = QAction(f"Noticia {suf.upper()} ({rol})", self)
            act.triggered.connect(lambda _, i=idx: self._accion_borrar_noticia(numero, i))
            m.addAction(act)
        return m

    def _menu_eliminar(self, numero: int) -> QMenu:
        """Submenú 'Eliminar': noticia / Quark / PDF (cada opción gris si no aplica)."""
        fs = self.controller.file_service
        ic = lambda name: QIcon(QPixmap(resource_path(f"ui/assets/{name}")))
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)

        subnotas = self._subnotas_de(numero)
        if len(subnotas) >= 2:
            sub = QMenu("Eliminar noticia", self); sub.setStyleSheet(_AJUSTES_MENU_QSS)
            sub.setIcon(ic("noticia.png"))
            for idx, txt_path in enumerate(subnotas):
                suf = txt_path.parent.name[-1]
                rol = fs.sufijo_a_rol(suf)
                act = QAction(f"Noticia {suf.upper()} ({rol})", self)
                act.triggered.connect(lambda _, i=idx: self._accion_borrar_noticia(numero, i))
                sub.addAction(act)
            m.addMenu(sub)
        else:
            act_n = QAction(ic("noticia.png"), "Eliminar noticia", self)
            act_n.setEnabled(len(subnotas) == 1)
            act_n.triggered.connect(lambda: self._accion_borrar_noticia(numero, 0))
            m.addAction(act_n)

        try:
            hay_qxp = bool(fs.listar_qxp_todas_ubicaciones(numero))
        except Exception:
            hay_qxp = False
        try:
            hay_pdf = bool(self.controller.pdf_path_para_descartar(numero))
        except Exception:
            hay_pdf = False

        m.addSeparator()
        act_q = QAction(ic("quark.png"), "Eliminar Quark", self)
        act_q.setEnabled(hay_qxp)
        act_q.triggered.connect(lambda: self._accion_descartar_qxp(numero))
        m.addAction(act_q)
        act_p = QAction(ic("pdf.png"), "Eliminar PDF", self)
        act_p.setEnabled(hay_pdf)
        act_p.triggered.connect(lambda: self._accion_descartar_pdf(numero))
        m.addAction(act_p)
        return m

    def _accion_asignar_directo(self, numero: int):
        """Asigna la página (rama 'asignar' de on_quitar) sin depender del texto del botón."""
        try:
            fs = self.controller.file_service
            entry = fs.read_page_entry(numero)
            usuario = (self.controller.usuario or "desconocido")
            if entry.get("aviso_full", False):
                fs.mark_assigned(numero, txt_name="", by=usuario, apagar_aviso_full=False)
            else:
                txt_path = fs.obtener_txt(numero)
                if txt_path is None or not txt_path.exists():
                    QMessageBox.warning(self, "Asignar", "No hay TXT en materiales para asignar.")
                    return
                fs.mark_assigned(numero, txt_path.name, by=usuario)
            pag = self.controller.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.asignada_por_ini = True
            self._despues_de_cambio_estado(numero)
            self.colorear_paginas()
        except Exception as e:
            QMessageBox.critical(self, "Asignar", str(e))

    def _menu_nueva_noticia(self, numero: int) -> QMenu:
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)
        a1 = QAction("Principal", self)
        a1.triggered.connect(lambda: self._accion_nueva_noticia(numero, "principal"))
        m.addAction(a1)
        a2 = QAction("Secundaria", self)
        a2.triggered.connect(lambda: self._accion_nueva_noticia(numero, "secundaria"))
        m.addAction(a2)
        m.addSeparator()
        a3 = QAction("Otra…", self)
        a3.triggered.connect(lambda: self._accion_nueva_noticia(numero, "otra"))
        m.addAction(a3)
        return m

    def _accion_nueva_noticia(self, numero: int, rol: str):
        """Crea una noticia en blanco en el rol elegido y abre el editor en ese índice."""
        fs = self.controller.file_service
        if rol == "otra":
            n, ok = QInputDialog.getInt(
                self, "Nueva noticia",
                "Elija el orden que tendrá la nueva noticia",
                3, 3, 26)        # min 3 → 1 (principal) y 2 (secundaria) no elegibles acá
            if not ok:
                return
            rol = f"noticia_{n}"
        suf = fs.rol_a_sufijo(rol)
        idx = ord(suf) - ord("a")
        txt = fs.material / f"P{numero:02d}" / f"{numero:02d}{suf}" / f"{numero:02d}{suf}.txt"
        if txt.exists() and txt.stat().st_size > 0:
            QMessageBox.information(
                self, "Nueva noticia",
                f"Ya existe la noticia {suf.upper()} ({fs.sufijo_a_rol(suf)}). Se abrirá para editarla.")
        else:
            try:
                fs.crear_txt_manual(numero, idx)
            except Exception as e:
                QMessageBox.critical(self, "Nueva noticia", str(e))
                return
            pag = self.controller.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.asignado = True
            self._despues_de_cambio_estado(numero)
        self._abrir_editor_nota(numero, idx)

    def on_ajustes_menu_requested(self, numero: int):
        if not getattr(self, "base_activa", False):
            return
        btn = self.boton_paginas.get(numero)
        if btn is None:
            return

        def _exec_centrado(menu, anchor):
            # Abre el menú centrado horizontalmente y justo debajo del ícono elegido
            w = menu.sizeHint().width()
            menu.exec_(QPoint(anchor.x() - w // 2, anchor.y() + 4))

        def _show(menu_builder, anchor):
            _exec_centrado(menu_builder(numero), anchor)

        def _toggle_tapa(attr, marcar, anchor=None):
            pag = self.controller.gestor_paginas.obtener_pagina(numero)
            if getattr(pag, attr, False):
                usuario = (self.controller.usuario or "").strip()
                self.controller.file_service.write_page_entry(numero, **{attr: False}, by=usuario)
                if pag:
                    setattr(pag, attr, False)
                self._despues_de_cambio_estado(numero)
            else:
                marcar(numero)

        # --- Disponibilidad para habilitar/deshabilitar (grises) ---
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        fs = self.controller.file_service
        try:
            hay_pdf = bool(self.controller.pdf_path_para_descartar(numero))
        except Exception:
            hay_pdf = False
        try:
            hay_qxp = bool(fs.listar_qxp_todas_ubicaciones(numero))
        except Exception:
            hay_qxp = False
        tiene_txt = bool(getattr(pag, "asignado", False))
        asignada = bool(getattr(pag, "asignada_por_ini", False))
        aviso_full = bool(getattr(pag, "aviso_full", False))
        # "Asignar aviso" solo si hay un tipo de aviso configurado en la página
        tiene_aviso_tipo = bool(
            aviso_full
            or getattr(pag, "aviso_half", False)
            or getattr(pag, "aviso_footer", False)
            or getattr(pag, "aviso_robapagina", False)
        )
        try:
            tiene_frags = bool(self.controller.obtener_fragmentos(numero, 0))
        except Exception:
            tiene_frags = False
        puede_pegar = bool(asignada and (tiene_frags or aviso_full))
        puede_eliminar = bool(tiene_txt or hay_qxp or hay_pdf)
        # Toggle Asignar / Quitar asignación
        if asignada:
            asignar_icon, asignar_txt = "asignar-no.png", "Quitar asignación"
            asignar_cb = lambda a: self._accion_quitar_asignacion(numero)
            asignar_enabled = True
        else:
            asignar_icon, asignar_txt = "asignar.png", "Asignar"
            asignar_cb = lambda a: self._accion_asignar_directo(numero)
            asignar_enabled = bool(tiene_txt or aviso_full)

        px = lambda name: QPixmap(resource_path(f"ui/assets/{name}"))
        items = [
            (px("nueva.png"),       "Nueva noticia",   lambda a: _show(self._menu_nueva_noticia, a)),
            (px("seccion.png"),     "Sección",         lambda a: _show(self._menu_seccion, a)),
            (px("aviso.png"),       "Configurar aviso", lambda a: _show(self._menu_avisos, a)),
            (px("asignar-aviso.png"), "Asignar aviso", lambda a: self._accion_asignar_aviso_archivo(numero), tiene_aviso_tipo),
            (px("enroque.png"),     "Enrocar páginas", lambda a: _show(self._menu_enrocar, a)),
            (px("foto_tapa.png"),   "Foto de tapa",    lambda a: _toggle_tapa("tapa_foto", self._accion_marcar_tapa_foto)),
            (px("titulo_tapa.png"), "Título de tapa",  lambda a: _toggle_tapa("tapa_titulo", self._accion_marcar_tapa_titulo)),
            (px("pegar.png"),       "Pegar en Quark",  lambda a: self._accion_pegar_quark(numero), puede_pegar),
            (px(asignar_icon),      asignar_txt,       asignar_cb, asignar_enabled),
            (px("borrar.png"),      "Eliminar",        lambda a: _show(self._menu_eliminar, a), puede_eliminar),
        ]
        self._ajustes_menu = _AjustesRadialMenu(btn, items, self)
        self._ajustes_menu.show()

    # ══════════════════════════════════════════════════════════════════
    # Enrocar páginas — panel overlay + modo de selección
    # ══════════════════════════════════════════════════════════════════

    _ENROQUE_PANEL_H = 64

    def _enroque_texto(self) -> str:
        x = getattr(self, "_enroque_x", None)
        y = getattr(self, "_enroque_y", None)
        modo = "con aviso" if getattr(self, "_enroque_con_aviso", False) else "sin aviso"
        if y:
            return f"Enrocar P{x:02d} con P{y:02d}   ({modo})"
        return f"Enrocar P{x:02d} con P__   ({modo}) — elegí la otra página en la grilla"

    def _ensure_enroque_panel(self):
        if getattr(self, "_enroque_panel", None) is not None:
            return
        panel = QWidget(self.panel_derecho)
        panel.setObjectName("enroquePanel")
        panel.setStyleSheet(
            "#enroquePanel { background-color: #1e293b; border-top: 2px solid #e7885f; }"
            "QLabel { color: #e2e8f0; font-size: 14px; font-weight: bold; }"
        )
        lay = QHBoxLayout(panel)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        self._enroque_label = QLabel("Enrocar…")
        btn_aceptar = QPushButton("Aceptar")
        btn_aceptar.clicked.connect(self._confirmar_enroque)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self._cancelar_enroque)

        lay.addWidget(self._enroque_label, 1)
        lay.addWidget(btn_aceptar)
        lay.addWidget(btn_cancelar)

        self._enroque_btn_aceptar = btn_aceptar
        panel.hide()
        self._enroque_panel = panel
        self._enroque_anim = QPropertyAnimation(panel, b"geometry", self)
        self._enroque_anim.setDuration(180)
        self._enroque_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _enroque_geom(self, visible: bool) -> QRect:
        pd = self.panel_derecho
        h = min(self._ENROQUE_PANEL_H, 200)
        w = pd.width()
        y = (pd.height() - h) if visible else pd.height()
        return QRect(0, y, w, h)

    def _mostrar_enroque_panel(self):
        panel = self._enroque_panel
        try:
            self._enroque_anim.finished.disconnect()
        except Exception:
            pass
        panel.setGeometry(self._enroque_geom(False))
        panel.show()
        panel.raise_()
        self._enroque_anim.stop()
        self._enroque_anim.setStartValue(self._enroque_geom(False))
        self._enroque_anim.setEndValue(self._enroque_geom(True))
        self._enroque_anim.start()

    def _ocultar_enroque_panel(self):
        panel = getattr(self, "_enroque_panel", None)
        if not panel:
            return
        self._enroque_anim.stop()
        try:
            self._enroque_anim.finished.disconnect()
        except Exception:
            pass
        self._enroque_anim.setStartValue(self._enroque_geom(True))
        self._enroque_anim.setEndValue(self._enroque_geom(False))
        self._enroque_anim.finished.connect(panel.hide)
        self._enroque_anim.start()

    def _reposicionar_enroque_panel(self):
        panel = getattr(self, "_enroque_panel", None)
        if panel and panel.isVisible():
            panel.setGeometry(self._enroque_geom(True))

    def _iniciar_enroque(self, numero: int, con_aviso: bool):
        if not getattr(self, "base_activa", False):
            return
        self._enroque_mode = True
        self._enroque_x = numero
        self._enroque_y = None
        self._enroque_con_aviso = con_aviso
        self._ensure_enroque_panel()
        self._enroque_label.setText(self._enroque_texto())
        self._enroque_btn_aceptar.setEnabled(False)
        self._mostrar_enroque_panel()
        self.colorear_paginas()
        self.statusBar().showMessage(
            f"Enroque: elegí la otra página para intercambiar con P{numero:02d}.", 6000)

    def _confirmar_enroque(self):
        x = getattr(self, "_enroque_x", None)
        y = getattr(self, "_enroque_y", None)
        if not x or not y:
            return
        con_aviso = bool(getattr(self, "_enroque_con_aviso", False))

        hay_qxp = False
        try:
            hay_qxp = self.controller.hay_qxp(x) or self.controller.hay_qxp(y)
        except Exception:
            hay_qxp = False

        qxp_mode = "ninguno"
        if hay_qxp:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle("Enrocar páginas")
            box.setText(
                "Una o más páginas ya están asignadas y con archivos de Quark. "
                "¿Desea quitar la asignación y eliminar los archivos de Quark o "
                "intercambiarlos también? (esto último cambiará el nombre del archivo "
                "pero deberán editarse los folios a mano)"
            )
            btn_elim = box.addButton("Eliminar archivos de Quark", QMessageBox.AcceptRole)
            btn_enro = box.addButton("Enrocar también archivos de Quark", QMessageBox.ActionRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is btn_elim:
                qxp_mode = "eliminar"
            elif clicked is btn_enro:
                qxp_mode = "enrocar"
            else:
                return  # Cancelar: no cierra el modo

        try:
            self.controller.enrocar_paginas(x, y, con_aviso, qxp_mode)
        except Exception as e:
            QMessageBox.critical(self, "Enrocar páginas", str(e))
            return

        self._salir_enroque()
        self.colorear_paginas()
        self._refresh_after_action(x)
        self.statusBar().showMessage(f"Páginas P{x:02d} y P{y:02d} enrocadas.", 4000)

    def _cancelar_enroque(self):
        self._salir_enroque()

    def _salir_enroque(self):
        self._enroque_mode = False
        self._enroque_x = None
        self._enroque_y = None
        self._ocultar_enroque_panel()
        self.colorear_paginas()

    def _on_chrome_nota_descargada(self, numero: int):
        self._refresh_after_action(numero)
        self.on_poll()
        self.statusBar().showMessage(f"Página {numero} copiada desde Chrome Extension", 4000)

    def _refresh_after_action(self, numero: int):
        """
        Refresca UI dejando la página `numero` como activa,
        sin disparar los diálogos de on_click_pagina.
        """
        if self.pagina_activa and self.pagina_activa in self.boton_paginas:
            pag_ant = self.controller.gestor_paginas.obtener_pagina(self.pagina_activa)
            self._apply_button_style_for_page(self.boton_paginas[self.pagina_activa], pag_ant)

        self.pagina_activa = numero
        self.label_pagina_activa.setText(f"Página activa: {numero}")
        self._load_images_for_page(numero)
        pagina = self.controller.seleccionar_pagina(numero)
        self.colorear_paginas()
        self.actualizar_info_pagina(pagina)
        self.mostrar_fragmentos(numero)
        self.actualizar_botonera_mover_devolver()
        self._update_aviso_nombre(pagina)
        estilos = self.boton_paginas[numero].styleSheet()
        self.boton_paginas[numero].setStyleSheet(f"{estilos} border: 6px solid #4043EB;")
        # Mostrar widget de maqueta si corresponde
        if self.controller.perfil == "Maquetación y avisos":
            self.maqueta_widget.set_pagina(pagina)

    #acciones del menú contextual
    def _accion_borrar_noticia(self, numero: int, idx: int):
        """
        Borra la subnoticia indicada (idx → 0=a, 1=b, etc.).
        Limpia el INI y actualiza interfaz.
        """
        fs = self.controller.file_service
        folder = fs.material / f"P{numero:02d}"
        subnotas = sorted(folder.glob("*/*.txt")) if folder.exists() else []

        if idx >= len(subnotas):
            return

        txt_path = subnotas[idx]
        nombre = txt_path.name

        resp = QMessageBox.question(
            self, "Borrar noticia",
            f"¿Seguro que querés borrar {nombre}? (También quitará las imágenes).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if resp != QMessageBox.Yes:
            return

        try:
            fs.eliminar_txt_asignado(numero, idx)
            fs.write_page_entry(numero, assigned=False, listo_para_armar="false", by="")
            pag2 = self.controller.gestor_paginas.obtener_pagina(numero)
            if pag2:
                pag2.asignado = False
                pag2.asignada_por_ini = False
                pag2.listo_para_armar = False
            boton = self.boton_paginas.get(numero)
            if isinstance(boton, PageButton):
                boton.set_listo_flag(False)
            self._despues_de_cambio_estado(numero)
            self.actualizar_info_pagina(pag2)
        except Exception as e:
            QMessageBox.critical(self, "Borrar noticia", str(e))


    
    def _accion_marcar_tapa_foto(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.marcar_tapa_foto(numero, by=usuario)
        self._despues_de_cambio_estado(numero)

    def _accion_marcar_tapa_titulo(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.marcar_tapa_titulo(numero, by=usuario)
        self._despues_de_cambio_estado(numero)

    def _accion_limpiar_tapa(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.limpiar_tapa_flags(numero, by=usuario)
        self._despues_de_cambio_estado(numero)

    def _accion_descartar_pdf(self, numero: int):
        """
        Confirma y descarta el PDF:
        - verde claro: borra en OK
        - verde oscuro: borra en carpeta diaria
        """
        try:
            self.controller.descartar_pdf(numero)
            # refrescar UI
            self._despues_de_cambio_estado(numero)
            self.statusBar().showMessage(f"P{numero:02d}: PDF enviado a la papelera.", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Descartar PDF", str(e))

    def _accion_descartar_qxp(self, numero: int):
        fs = self.controller.file_service
        try:
            locs = fs.listar_qxp_todas_ubicaciones(numero)
        except Exception:
            locs = []
        if not locs:
            self.statusBar().showMessage(f"P{numero:02d}: no hay QXP para borrar.", 3000)
            return

        mat = fs.find_qxp_en_materiales(numero)
        mat_key = None
        if mat:
            try:
                mat_key = mat.resolve()
            except Exception:
                mat_key = mat

        def _key(p):
            try:
                return p.resolve()
            except Exception:
                return p

        solo_materiales = bool(mat) and all(_key(q) == mat_key for q in locs)

        try:
            if solo_materiales:
                try:
                    rel = mat.relative_to(Path(fs.rutas.get("material") or ""))
                except Exception:
                    rel = mat.name
                resp = QMessageBox.question(
                    self, "Borrar QXP",
                    f"El archivo {mat.name} solo está en materiales/{rel}, "
                    "eliminarlo también quitará la asignación (los materiales como texto y "
                    "fotos permanecen). ¿Desea continuar?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if resp != QMessageBox.Yes:
                    return
                self.controller.quitar_asignacion(numero, borrar_qxp=True)
                self.statusBar().showMessage(
                    f"P{numero:02d}: QXP borrado y asignación quitada.", 3000)
            else:
                n = fs.eliminar_qxp_fuera_de_materiales(numero)
                self.statusBar().showMessage(
                    f"P{numero:02d}: {n} QXP enviado(s) a la papelera.", 3000)
            self._despues_de_cambio_estado(numero)
            self.colorear_paginas()
        except Exception as e:
            QMessageBox.warning(self, "Borrar QXP", str(e))



    # ══════════════════════════════════════════════════════════════════
    # Señales del VisorPanelWidget → lógica de negocio
    # ══════════════════════════════════════════════════════════════════

    def on_abrir_imagen(self):
        """Abre la imagen activa del visor en el editor externo (Photoshop, etc.)."""
        if not getattr(self, "base_activa", False) or self.pagina_activa is None:
            return
        p = self.visor_panel.imagen_actual()
        if not p:
            QMessageBox.information(self, "Abrir imagen",
                                    "No hay imagen seleccionada para esta página.")
            return
        self._on_visor_abrir_en_editor(p)

    def _on_visor_abrir_en_editor(self, p: Path) -> None:
        """Abre `p` en el editor externo configurado (Photoshop / fallback diálogo)."""
        if not p or not p.exists():
            QMessageBox.information(self, "Abrir imagen",
                                    "No encontré la imagen seleccionada en disco.")
            return
        try:
            cfg     = configparser.ConfigParser()
            cfg_path = Config.CONFIG_FILE
            if cfg_path.exists():
                cfg.read(cfg_path, encoding="utf-8")

            photoshop_path = ""
            for sec in ("APPS", "apps"):
                if cfg.has_section(sec):
                    photoshop_path = cfg.get(sec, "photoshop", fallback="").strip()
                    if photoshop_path:
                        break

            if not photoshop_path:
                photoshop_path = r"C:\Program Files\Adobe\Adobe Photoshop CC 2019\Photoshop.exe"

            if not Path(photoshop_path).exists():
                exe_path, _ = QFileDialog.getOpenFileName(
                    self, "Seleccionar aplicación para abrir la imagen",
                    "C:\\Program Files", "Ejecutables (*.exe)"
                )
                if not exe_path:
                    QMessageBox.information(self, "Abrir imagen",
                                            "No se seleccionó ninguna aplicación.")
                    return
                photoshop_path = exe_path
                sec = "APPS"
                if not cfg.has_section(sec):
                    cfg.add_section(sec)
                cfg.set(sec, "photoshop", photoshop_path)
                with open(cfg_path, "w", encoding="utf-8") as f:
                    cfg.write(f)

            subprocess.Popen([photoshop_path, str(p)])
            _log.info(f"[OK] Imagen abierta con {photoshop_path}")
        except Exception as e:
            QMessageBox.warning(self, "Abrir imagen", f"No pude abrir la imagen:\n{e}")

    def _on_visor_foto_tapa_marcar(self, src: Path) -> None:
        """Copia `src` a materiales/P01 como foto de tapa."""
        # ── Verificar si ya hay una foto de tapa de otra página ──
        pagina_origen = self.controller.foto_tapa_pagina_origen()
        pagina_actual = self.pagina_activa

        if (
            self.controller.foto_tapa_en_p01() is not None
            and pagina_origen is not None
            and pagina_origen != pagina_actual
        ):
            resp = QMessageBox.question(
                self,
                "Foto de tapa ya seleccionada",
                f"La foto de tapa ya se seleccionó de página {pagina_origen}.\n"
                f"¿Desea reemplazarla con una imagen de la página {pagina_actual}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                # Revertir estrella en el visor (fue activada optimistamente)
                self.visor_panel.set_foto_tapa_activa(False)
                return

        try:
            self.controller.copiar_foto_tapa_a_p01(src, pagina=pagina_actual)
            self.visor_panel.set_foto_tapa_activa(True)
            _log.info(f"[FOTO TAPA] Marcada desde panel: {src.name}")
        except Exception as e:
            self.visor_panel.set_foto_tapa_activa(False)
            QMessageBox.critical(self, "Error al marcar foto de tapa",
                                 f"No se pudo copiar la imagen a P01:\n\n{e}")

    def _on_visor_foto_tapa_desmarcar(self) -> None:
        """Borra la foto de tapa de materiales/P01."""
        try:
            self.controller.borrar_foto_tapa_de_p01()
            self.visor_panel.set_foto_tapa_activa(False)
            _log.info("[FOTO TAPA] Desmarcada desde panel.")
        except Exception as e:
            self.visor_panel.set_foto_tapa_activa(True)
            QMessageBox.warning(self, "Error al desmarcar foto de tapa",
                                f"No se pudo borrar el archivo en P01:\n\n{e}")

    def _on_visor_imagen_eliminada(self, path: Path) -> None:
        """Recarga las imágenes tras eliminar una."""
        n = self.pagina_activa
        if n is None:
            return
        imgs = self._gather_images_for_page_via_visor(n)
        self.visor_panel.actualizar_imagenes(imgs)

    def _on_visor_imagen_renombrada(self, src: Path, nuevo_stem: str) -> None:
        """Renombra `src` en disco, actualiza selección y refresca el visor."""
        n = self.pagina_activa
        if n is None:
            return
        try:
            dest = self.controller.file_service.rename_material_image(n, src, nuevo_stem)
            imgs = self._gather_images_for_page_via_visor(n)
            self.visor_panel.actualizar_imagenes(imgs)
            # Posicionar en la imagen renombrada
            for i, p in enumerate(imgs):
                if p.name == dest.name:
                    self.visor_panel._image_index = i
                    self.visor_panel._show_current()
                    break
            _log.info("Imagen renombrada: %s → %s", src.stem, nuevo_stem)
            # Actualizar path en selección de fotos si corresponde
            subfolder = self._subfolder_activo()
            self._fotos_estado = self.controller.actualizar_path_foto_renombrada(
                n, subfolder, src, dest
            )
            self._refrescar_panel_fotos()
            self._refrescar_visor_seleccion()
            if self.pagina_activa:
                self._refresh_after_action(self.pagina_activa)
        except Exception as e:
            QMessageBox.critical(self, "Renombrar imagen", str(e))

    # ── Selección de fotos de página ─────────────────────────────────────────

    def _subfolder_activo(self) -> "Optional[str]":
        """Devuelve el nombre del subfolder activo (p.ej. '06a') o None."""
        if self._noticias and 0 <= self._noticia_index < len(self._noticias):
            return self._noticias[self._noticia_index].name
        return None

    def _refrescar_panel_fotos(self) -> None:
        """Sincroniza el PanelFotosPagina con el estado en memoria."""
        self.panel_fotos.actualizar(self._fotos_estado.get("fotos", []))

    def _refrescar_visor_seleccion(self) -> None:
        """Actualiza el botón 📌 y el label según la imagen visible actualmente."""
        img = self.visor_panel.imagen_actual()
        if img is None:
            self.visor_panel.set_foto_seleccionada(False)
            return
        svc     = self.controller.foto_pagina_service
        estado  = self._fotos_estado
        sel     = svc.esta_seleccionada(estado, img)
        orden   = svc.orden_de(estado, img) if sel else None
        self.visor_panel.set_foto_seleccionada(sel, orden)

    def _cargar_fotos_estado(self) -> None:
        """Carga fotos_seleccionadas.json para la página/subfolder activa."""
        pagina = self.pagina_activa
        if pagina is None:
            self._fotos_estado = {}
            return
        subfolder = self._subfolder_activo()
        self._fotos_estado = self.controller.cargar_estado_fotos_pagina(
            pagina, subfolder
        )

    def _cargar_epigrafes_visor(self, noticia_dir) -> None:
        """Lee los epígrafes del JSON de la nota y los pasa al visor."""
        try:
            json_path = noticia_dir / f"{noticia_dir.name}.json"
            if not json_path.exists():
                self.visor_panel.set_epigrafes({})
                return
            import json as _json
            data = _json.loads(json_path.read_text(encoding="utf-8"))
            epigrafes: dict = {}
            for img in data.get("imagenes", []):
                archivo = img.get("archivo", "")
                epi = img.get("epigrafe", "").strip()
                if epi and archivo and epi != "NO HAY EPÍGRAFE":
                    epigrafes[archivo] = epi
            self.visor_panel.set_epigrafes(epigrafes)
        except Exception:
            self.visor_panel.set_epigrafes({})

    def _on_visor_usar_epigrafe(self, texto: str) -> None:
        """Guarda el epígrafe elegido en fotos_seleccionadas.json para la foto actual."""
        pagina = self.pagina_activa
        if pagina is None:
            return
        img = self.visor_panel.imagen_actual()
        if img is None:
            return
        subfolder = self._subfolder_activo()
        svc = self.controller.foto_pagina_service
        mat = self.controller.file_service.material
        if mat is None:
            return
        self._fotos_estado = svc.set_epigrafe(self._fotos_estado, img, texto)
        svc.guardar(self._fotos_estado, pagina, subfolder, mat)
        self._refrescar_panel_fotos()

    def _on_visor_foto_seleccionar(self, path: Path) -> None:
        """El visor pide seleccionar `path` para la página."""
        pagina = self.pagina_activa
        if pagina is None:
            return
        subfolder = self._subfolder_activo()
        svc   = self.controller.foto_pagina_service
        orden = len(self._fotos_estado.get("fotos", []))
        nombre = svc.auto_nombre(orden, pagina)
        self._fotos_estado = self.controller.seleccionar_foto_pagina(
            pagina, subfolder, path, nombre
        )
        self._refrescar_panel_fotos()
        self._refrescar_visor_seleccion()

    def _on_visor_foto_deseleccionar(self, path: Path) -> None:
        """El visor pide deseleccionar `path`."""
        pagina = self.pagina_activa
        if pagina is None:
            return
        subfolder = self._subfolder_activo()
        self._fotos_estado = self.controller.deseleccionar_foto_pagina(
            pagina, subfolder, path
        )
        self._refrescar_panel_fotos()
        self._refrescar_visor_seleccion()

    def _on_fotos_mover_arriba(self, path: Path) -> None:
        pagina = self.pagina_activa
        if pagina is None:
            return
        subfolder = self._subfolder_activo()
        self._fotos_estado = self.controller.mover_foto_arriba(pagina, subfolder, path)
        self._refrescar_panel_fotos()
        self._refrescar_visor_seleccion()

    def _on_fotos_mover_abajo(self, path: Path) -> None:
        pagina = self.pagina_activa
        if pagina is None:
            return
        subfolder = self._subfolder_activo()
        self._fotos_estado = self.controller.mover_foto_abajo(pagina, subfolder, path)
        self._refrescar_panel_fotos()
        self._refrescar_visor_seleccion()

    def _on_fotos_quitar(self, path: Path) -> None:
        pagina = self.pagina_activa
        if pagina is None:
            return
        subfolder = self._subfolder_activo()
        self._fotos_estado = self.controller.deseleccionar_foto_pagina(
            pagina, subfolder, path
        )
        self._refrescar_panel_fotos()
        self._refrescar_visor_seleccion()

    def _gather_images_for_page_via_visor(self, n: int):
        """Reúne imágenes para la página n con el orden de prioridad estándar."""
        from pathlib import Path as _Path
        import re as _re
        folder = self.controller.file_service.material / f"P{n:02d}"
        if not folder.exists():
            return []
        exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]

        def sort_key(p):
            name = p.name.lower()
            if _re.search(rf"para[\s_-]*la[\s_-]*0*{n}\b", name): return (0, 0, name)
            if _re.match(rf"^principal[_\s-]*{n:02d}\.", name):      return (1, 0, name)
            m = _re.match(rf"^extra(\d*)[_\s-]*{n:02d}\.", name)
            if m: return (2, int(m.group(1) or 0), name)
            return (3, 0, name)

        return sorted(files, key=sort_key)

    def _accion_abrir_imagen(self, numero: int):
        self.pagina_activa = numero
        self.on_abrir_imagen()

    def _accion_abrir_quark(self, numero: int):
        self.pagina_activa = numero
        self.on_abrir_quark()

    def _accion_set_seccion(self, numero: int, nueva: str):
        usuario = (self.controller.usuario or "").strip()
        self.controller.file_service.set_seccion(numero, nueva.strip(), by=usuario)
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        if pag:
            pag.seccion = nueva.strip()
        self._despues_de_cambio_estado(numero)


    def _accion_clear_seccion(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.file_service.clear_seccion(numero, by=usuario)
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        if pag:
            pag.seccion = ""
        self._despues_de_cambio_estado(numero)



    def _accion_quitar_avisos(self, numero: int):
        """
        Limpia completamente cualquier aviso asignado a la página:
        - Borra flags y nombre en el INI
        - Elimina los campos temporales en memoria (pixmap, mtime, path)
        - Refresca la maqueta y los labels
        """
        usuario = (self.controller.usuario or "").strip()

        try:
            # 1. Limpiar en el INI
            self.controller.file_service.clear_avisos(numero, by=usuario)
            self.controller.file_service.set_aviso_nombre(numero, "", by=usuario)

            # 2. Limpiar en el objeto de página
            pag = self.controller.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.aviso_full = False
                pag.aviso_half = False
                pag.aviso_footer = False
                pag.aviso_robapagina = False
                pag.aviso_nombre = ""
                pag.aviso_path = None
                pag.aviso_pixmap = None
                pag.aviso_mtime = None

            # 3. Refrescar la UI y maqueta
            self._despues_de_cambio_estado(numero)

            if self.controller.perfil == "Maquetación y avisos":
                self.maqueta_widget.set_pagina(pag)
                self.maqueta_widget.update()

            # 4. Actualizar etiqueta de nombre del aviso
            self._update_aviso_nombre(pag)

            # 5. Forzar repintado del botón
            if numero in self.boton_paginas:
                self.boton_paginas[numero].update()

            

        except Exception as e:
            QMessageBox.critical(self, "Quitar avisos", f"Error al quitar aviso:\n{e}")


    def _accion_quitar_link(self, _numero: int):
        try:
            numero = self.pagina_activa
            self.controller.quitar_link_pagina(numero)
            self._despues_de_cambio_estado(numero)
        except Exception as e:
            QMessageBox.critical(self, "Quitar link", str(e))

        
    
    def _accion_asignar_texto(self, numero: int):
        link, ok = QInputDialog.getText(self, "Cargar link", "Pegá el link de la nota:")
        if not ok or not link.strip():
            return
        try:
            # 🚀 Encolamos como en el cargador automático
            self.controller.enqueue_scrape(numero, link.strip())
            #self.statusBar().showMessage(f"P{numero:02d}: encolado scrape…", 3000)

            # refrescar estado visual
            self._despues_de_cambio_estado(numero)
            pagina = self.controller.gestor_paginas.obtener_pagina(numero)
            self.actualizar_info_pagina(pagina)

        except Exception as e:
            QMessageBox.critical(self, "Cargar link", str(e))

    def on_seleccionar_carpeta_avisos(self):
        """
        Permite elegir la carpeta raíz 'Comercial' (que contiene 'Avisos YYYY').
        Persiste en config.ini como [RUTAS].carpeta_avisos y recalcula el día.
        """
        carpeta = QFileDialog.getExistingDirectory(self, "Seleccionar raíz de avisos (Comercial)")
        if not carpeta:
            return

        try:
            # Persistir en ini
            from config.config import Config
            import configparser
            cfg = configparser.ConfigParser()
            if Config.CONFIG_FILE.exists():
                cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
            rutas = cfg.setdefault("RUTAS", {})
            rutas["carpeta_avisos"] = carpeta
            with open(Config.CONFIG_FILE, "w", encoding="utf-8") as f:
                cfg.write(f)

            # Actualizar estado en RutasEstado
            self.controller.rutas.avisos_root = Path(carpeta)

            # Re-sincronizar para recalcular avisos_dir del día
            self.controller._sincronizar_rutas_en_file_service()

            # Aviso suave y repaint (si estás en Maquetación, la maqueta lo usará luego)
            self.statusBar().showMessage("Carpeta de avisos configurada.", 3000)
            if self.controller.perfil == "Maquetación y avisos":
                self.maqueta_widget.update()

        except Exception as e:
            QMessageBox.critical(self, "Avisos", f"No pude configurar la carpeta de avisos:\n{e}")


    def on_configurar_rutas(self):
        try:
            def prompt_fn(clave, titulo):
                return QFileDialog.getExistingDirectory(self, titulo)

            # ✅ Obtener perfil activo desde los botones toggle
            if self.btn_maquetacion.isChecked():
                perfil = "Maquetación y avisos"
            else:
                perfil = "Armado y corrección"

            self.controller.rutas.ensure_roots(prompt_fn, perfil=perfil)

            # --- Sincronizar pool_root con la UI ---
            if self.controller.rutas.pool_root:
                self.pool_root = self.controller.rutas.pool_root
            else:
                self.pool_root = None  # por si se limpió


            QMessageBox.information(self, "Rutas configuradas", "Las rutas se configuraron correctamente.")

            # Restablecer estado de interfaz por seguridad (opcional)
            self.base_activa = False
            if self.timer.isActive():
                self.timer.stop()
            self.boton_pegar.setEnabled(False)
            self.boton_quitar.setEnabled(False)
            self.boton_mover.setEnabled(False)
            self.boton_devolver.setEnabled(False)
            self.pagina_activa = None
            self.colorear_paginas()
            self.label_pagina_activa.setText("Página activa: -")
            self.texto_noticia.clear()
            self.lista_fragmentos.clear()
            self.info_estado.set_valor("—")
            self.info_usuario.set_valor("—"); self.info_usuario.set_enabled(False)
            self.info_link.set_enabled(False)
            self._info_links = []; self._info_by = ""; self._info_ts = ""
            self.visor_panel.limpiar()
            self.panel_fotos.limpiar()
            self._fotos_estado = {}
            self._noticias = []
            self._noticia_index = 0
            self.btn_prev_noticia.setEnabled(False)
            self.btn_next_noticia.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, "Error al configurar rutas", str(e))


    def on_configurar_maquetas(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de maquetas (.qxp)")
        if not carpeta:
            return
        try:
            import configparser
            from config.config import Config
            cfg = configparser.ConfigParser()
            if Config.CONFIG_FILE.exists():
                cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
            cfg.setdefault("RUTAS", {})["carpeta_maquetas"] = carpeta
            with open(Config.CONFIG_FILE, "w", encoding="utf-8") as f:
                cfg.write(f)
            self.controller.rutas.maquetas_root = Path(carpeta)
            self.controller._sincronizar_rutas_en_file_service()
            from services.maqueta_reader_service import set_override_maquetas_dir
            set_override_maquetas_dir(Path(carpeta))
            self.statusBar().showMessage(f"Carpeta de maquetas configurada: {carpeta}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Maquetas", f"No pude configurar la carpeta de maquetas:\n{e}")


    def _accion_asignar_aviso_robapagina(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.file_service.mark_aviso_robapagina(numero, by=usuario)
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        pag.aviso_full = False
        pag.aviso_half = False
        pag.aviso_footer = False
        pag.aviso_robapagina = True
        self._despues_de_cambio_estado(numero)
        self.maqueta_widget.set_pagina(pag)
        self._update_aviso_nombre(pag)




    def _accion_asignar_aviso_full(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.file_service.mark_aviso_full(numero, by=usuario)
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        pag.aviso_full = True
        pag.aviso_half = False
        pag.aviso_footer = False
        self._despues_de_cambio_estado(numero)
        self.maqueta_widget.set_pagina(pag)
        self._update_aviso_nombre(pag)


    def _accion_asignar_aviso_half(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.file_service.mark_aviso_half(numero, by=usuario)
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        pag.aviso_full = False
        pag.aviso_half = True
        pag.aviso_footer = False
        self._despues_de_cambio_estado(numero)
        self.maqueta_widget.set_pagina(pag)
        self._update_aviso_nombre(pag)

    def _accion_asignar_aviso_footer(self, numero: int):
        usuario = (self.controller.usuario or "").strip()
        self.controller.file_service.mark_aviso_footer(numero, by=usuario)
        pag = self.controller.gestor_paginas.obtener_pagina(numero)
        pag.aviso_full = False
        pag.aviso_half = False
        pag.aviso_footer = True
        self._despues_de_cambio_estado(numero)
        self.maqueta_widget.set_pagina(pag)
        self._update_aviso_nombre(pag)

    def _accion_asignar_aviso_archivo(self, numero: int):
        """
        Abre un diálogo de archivo para seleccionar un aviso manualmente
        y lo copia a materiales/Pxx/.
        Luego actualiza la maqueta y el estado visual.
        """
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                f"Seleccionar aviso para la página {numero:02d}",
                "",
                "Archivos de imagen o PDF (*.jpg *.jpeg *.png *.tif *.tiff *.pdf *.eps)"
            )
            if not file_path:
                return

            src = Path(file_path)
            if not src.exists():
                QMessageBox.warning(self, "Asignar aviso", "El archivo seleccionado no existe.")
                return

            # Carpeta de destino
            dest_dir = self.controller.file_service.material / f"P{numero:02d}"
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Copiar el archivo al destino
            dest_path = dest_dir / src.name
            import shutil
            shutil.copy2(src, dest_path)

            # Actualizar el INI con el nombre del aviso
            usuario = (self.controller.usuario or "").strip()
            self.controller.file_service.set_aviso_nombre(numero, src.name, by=usuario)

            # Actualizar visualmente la página
            pag = self.controller.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.aviso_nombre = src.name
                pag.aviso_path = dest_path
                pag.aviso_mtime = dest_path.stat().st_mtime

            # Refrescar la maqueta
            self._despues_de_cambio_estado(numero)
            self.maqueta_widget.set_pagina(pag)
            self._update_aviso_nombre(pag)



        except Exception as e:
            QMessageBox.critical(self, "Asignar aviso", f"Error al asignar el aviso:\n{e}")

    def _accion_limpiar_aviso(self, numero: int):
        """Elimina el aviso físico y limpia los datos de la página correspondiente."""
        pagina = self.controller.gestor_paginas.obtener_pagina(numero)
        if not pagina:
            _log.warning(f"[WARN] No se encontró página {numero} para limpiar aviso.")
            return

        aviso_path = getattr(pagina, "aviso_path", None)

        try:
            # 1️⃣ Eliminar archivo físico si existe
            if aviso_path and Path(aviso_path).exists():
                Path(aviso_path).unlink()
                _log.info(f"[DEL] Archivo aviso eliminado: {aviso_path}")

            # 2️⃣ Limpiar atributos (solo el aviso, no los flags de tipo)
            for campo in ["aviso_nombre", "aviso_path", "aviso_pixmap", "aviso_mtime"]:
                if hasattr(pagina, campo):
                    setattr(pagina, campo, None if campo != "aviso_nombre" else "")

            # 3️⃣ Actualizar INI (dejar flags como están)
            usuario = (self.controller.usuario or "").strip()
            self.controller.file_service.set_aviso_nombre(numero, "", by=usuario)

            # 4️⃣ Refrescar maqueta y etiquetas
            self._despues_de_cambio_estado(numero)
            self.maqueta_widget.set_pagina(pagina)
            self.maqueta_widget.update()
            self._update_aviso_nombre(pagina)

            # 5️⃣ Forzar repintado del botón
            if numero in self.boton_paginas:
                self.boton_paginas[numero].update()

            _log.info(f"[OK] Aviso limpiado completamente en P{numero:02d}")

        except Exception as e:
            QMessageBox.critical(self, "Limpiar aviso", f"Error al limpiar aviso:\n{e}")



    def _accion_abrir_asociado(self, numero: int):
        self.on_doble_click_pagina(numero)

    def _accion_pegar_quark(self, numero: int):
        self._refresh_after_action(numero)
        self.on_pegar()

    def _accion_mover(self, numero: int):
        self._refresh_after_action(numero)
        self.on_mover()

    def _accion_devolver(self, numero: int):
        self._refresh_after_action(numero)
        self.on_devolver()

    def _accion_quitar_asignacion(self, numero: int):
        self._refresh_after_action(numero)
        self.on_quitar()

    def _despues_de_cambio_estado(self, numero: int):
        # Mantener la maqueta en sync con el aviso al cambiar el estado (asignar aviso, etc.)
        try:
            self.controller.file_service.sincronizar_maqueta_pagina(numero)
        except Exception:
            pass
        self._refresh_after_action(numero)
        self.on_poll()



    def _estado_visible(self, pagina) -> str:
        # --- PDF tiene prioridad máxima ---
        if pagina.impreso:
            return "impreso"        # verde claro (PDF en OK)
        if pagina.revisado:
            return "revisado"       # verde oscuro (PDF en PDF)

        if self.controller.perfil == "Armado y corrección":
            if pagina.fotocromia:
                return "fotocromia"
            if getattr(pagina, "asignada_por_otro", False):
                return "asignado_remoto"
            if getattr(pagina, "asignada_por_ini", False):
                return "asignado"
            if pagina.asignado:
                return "txt"
            if pagina.apdf:
                return "apdf"        # lila  (QXP en A PDF)
            return "vacío"
            

        elif self.controller.perfil == "Maquetación y avisos":
            if pagina.corregido:
                return "corregido"   # amarillo (QXP en Final/Mandar)
            if pagina.armado:
                return "armado"      # blanco (QXP en Base)
            #if pagina.asignado or getattr(pagina, "asignada_por_ini", False) or getattr(pagina, "asignada_por_otro", False):
            #    return "txt"         # gris claro (asignada) AHORA ES AZUL
            if pagina.apdf:
                return "apdf"       # lila  (QXP en A PDF)
            if pagina.fotocromia:
                return "azul"          # azul 
            return "vacío"           # gris oscuro (nada)

        # fallback genérico (otros perfiles que puedan aparecer)
        if pagina.armado:
            return "armado"
        if pagina.corregido:
            return "corregido"
        if getattr(pagina, "asignada_por_otro", False):
            return "asignado_remoto"
        if getattr(pagina, "asignada_por_ini", False):
            return "asignado"
        if pagina.asignado:
            return "txt"
        if pagina.apdf:
                return "apdf"        # lila  (QXP en A PDF)
        return "vacío"

    def on_actualizar_paginas(self):
        """
        Limpia la caché de estados (QXP/PDF) y fuerza un refresco inmediato.
        """
        try:
            self.controller.file_service.clear_cache()
            self.on_poll()
            
        except Exception as e:
            QMessageBox.warning(self, "Actualizar páginas", f"No se pudo actualizar:\n{e}")


    def _toggle_info_noticia(self):
        """Abre/cierra el panel de fragmentos (cierra el de aviso si estaba abierto)."""
        target = 0 if getattr(self, "_panel_modo", 0) == 1 else 1
        self._set_panel_modo(target)

    def _toggle_panel_aviso(self):
        """Abre/cierra el panel de aviso (cierra el de fragmentos si estaba abierto)."""
        target = 0 if getattr(self, "_panel_modo", 0) == 2 else 2
        self._set_panel_modo(target)

    def _set_panel_modo(self, modo: int):
        """Estado mutuamente excluyente: 0=fotos, 1=fragmentos, 2=aviso."""
        self._panel_modo = modo
        self._info_noticia_expandido = (modo == 1)
        self.tab_info_noticia.set_expandido(modo == 1)
        if hasattr(self, "tab_panel_aviso"):
            self.tab_panel_aviso.set_expandido(modo == 2)
        if modo == 2 and getattr(self, "pagina_activa", None):
            pag = self.controller.gestor_paginas.obtener_pagina(self.pagina_activa)
            if pag:
                self.maqueta_widget.set_pagina(pag)
        # expandir = mostrar algo distinto de las fotos (desliza desde la izquierda)
        self._animar_stack_info(modo, expandir=(modo != 0))

    def _animar_stack_info(self, nuevo_idx: int, expandir: bool = True):
        """Desliza la nueva página: al expandir entra desde la izquierda (rebote al máximo,
        a la derecha); al colapsar entra desde la derecha (rebote a la izquierda)."""
        stack = self.stack_info
        if stack.currentIndex() == nuevo_idx:
            return

        prev = getattr(self, "_stack_anim_pos", None)
        if prev is not None:
            try:
                prev.stop()
            except Exception:
                pass
        # Sin desvanecimiento: asegurar opacidad plena por si quedó un efecto residual
        eff = stack.graphicsEffect()
        if isinstance(eff, QGraphicsOpacityEffect):
            eff.setOpacity(1.0)

        stack.setCurrentIndex(nuevo_idx)
        w = stack.currentWidget()
        if w is None:
            return

        y = w.y()
        ancho = max(40, stack.width())
        x0 = -ancho if expandir else ancho     # izquierda→derecha (expandir) / derecha→izquierda (colapsar)
        fin = QPoint(0, y)
        w.move(x0, y)

        curva = QEasingCurve(QEasingCurve.OutBack)
        curva.setOvershoot(1.2)                # rebote mínimo al llegar al final

        anim = QPropertyAnimation(w, b"pos", self)
        anim.setDuration(280)
        anim.setStartValue(QPoint(x0, y))
        anim.setEndValue(fin)
        anim.setEasingCurve(curva)
        self._stack_anim_pos = anim
        anim.start()

    def _plegar_info_noticia(self):
        """Fuerza el estado plegado (panel de fotos visible), sin animación."""
        self._panel_modo = 0
        self._info_noticia_expandido = False
        prev = getattr(self, "_stack_anim_pos", None)
        if prev is not None:
            try:
                prev.stop()
            except Exception:
                pass
        self.stack_info.setCurrentIndex(0)
        w = self.stack_info.currentWidget()
        if w is not None:
            w.move(0, w.y())                 # restaurar posición por si quedó deslizada
        eff = self.stack_info.graphicsEffect()
        if isinstance(eff, QGraphicsOpacityEffect):
            eff.setOpacity(1.0)
        self.tab_info_noticia.set_expandido(False)
        if hasattr(self, "tab_panel_aviso"):
            self.tab_panel_aviso.set_expandido(False)

    def on_cambiar_perfil(self, perfil: str):
        # NO forzar ocultar 'Armar mono' si está activo
        if not self.action_armar_mono.isChecked():
            # Solo si NO está activo, volvemos al panel estándar
            self.stack_left.setCurrentWidget(self.panel_armado_maquetacion)

        # info_scroll visible siempre. La maqueta vive ahora en el stack (página 2),
        # gestionada por las solapas; no se la muestra/oculta directamente.
        self.info_scroll.setVisible(True)
        # Ambas solapas visibles en los dos perfiles.
        self.tab_info_noticia.setVisible(True)
        self.tab_panel_aviso.setVisible(True)
        # Armado arranca en fotos (modo 0); Maquetación muestra el aviso (modo 2).
        if perfil == "Maquetación y avisos":
            self._set_panel_modo(2)
        else:
            self._plegar_info_noticia()
        self.label_aviso_nombre.setVisible(perfil == "Maquetación y avisos")


        self.controller.cambiar_perfil(perfil)
        es_maquetacion = (perfil == "Maquetación y avisos")
        for boton in self.boton_paginas.values():
            boton.modo_maquetacion = es_maquetacion
            boton.update()

        if perfil == "Maquetación y avisos":
            self.boton_pegar.setText("Abrir imagen")
            self.boton_abrir_quark.setVisible(True)

            # Maqueta/aviso se muestra vía el stack (solapa "Panel de aviso", modo 2)
            self.label_aviso_nombre.setVisible(True)

            # Ocultar navegación de noticias
            #self.btn_prev_noticia.setVisible(False)
            #self.btn_next_noticia.setVisible(False)
            #self.label_noticia_titulo.setVisible(False)

        else:
            
            self.boton_pegar.setText(f"Pegar en Quark")
            self.boton_abrir_quark.setVisible(False)

            # Armado: el aviso se ve al desplegar "Panel de aviso" (stack página 2)
            self.label_aviso_nombre.setVisible(False)

            # Mostrar navegación de noticias
            self.btn_prev_noticia.setVisible(True)
            self.btn_next_noticia.setVisible(True)
            self.label_noticia_titulo.setVisible(bool(self._noticias))

        # 🔹 Forzar actualización de layout del panel izquierdo
        if hasattr(self, "panel_izquierdo"):
            self.panel_izquierdo.update()
            self.panel_izquierdo.adjustSize()

        if not getattr(self, "base_activa", False):
            return

        self.colorear_paginas()
        self.actualizar_botonera_mover_devolver()

        if self.pagina_activa:
            pagina = self.controller.gestor_paginas.obtener_pagina(self.pagina_activa)
            self.actualizar_info_pagina(pagina)
            self._load_images_for_page(self.pagina_activa)
            self.maqueta_widget.set_pagina(pagina)



    def _set_perfil(self, perfil: str):
        """Sincroniza botones y ejecuta cambio de perfil."""
        if perfil == "Armado y corrección":
            self.btn_armado.setChecked(True)
            self.btn_maquetacion.setChecked(False)
        else:
            self.btn_armado.setChecked(False)
            self.btn_maquetacion.setChecked(True)

        # Ejecuta el cambio de perfil como antes
        self.on_cambiar_perfil(perfil)


    ### Funciones y métodos de Armado de MONO ###

    def cargar_pool_hoy(self):
        """
        Carga las notas del pool de HOY desde el controller y
        arma la lista interna + la vista mono_lista.
        """
        # 1) Actualiza datos desde el scraper / disco
        #self.controller.refresh_pool_notas_hoy()

        # 2) Pobla estructuras internas y aplica filtro/orden actual
        self._poblar_pool_ui()


    def _cargar_pool_filtrado(self, notas):
        """Recarga el listado usando la lógica plana."""
        self.mono_lista.clear()

        for n in notas:
            item = QTreeWidgetItem([
                n.estado_pub or "",
                n.titulo or "",
                n.seccion or "",
                str(n.chars),
                n.created.strftime("%H:%M"),
            ])
            item.setData(0, Qt.UserRole, {
                "dir": str(n.dir_path),
                "txt": str(n.txt_path),
            })

            self.mono_lista.addTopLevelItem(item)

        self._pool_filtrado = notas

    def _filtrar_y_ordenar_pool(self):
        """Filtra y ordena el pool según búsqueda y combo."""
        if not self._pool_original:
            return

        texto = (self.mono_busqueda.text() or "").strip().lower()
        modo = self.mono_orden.currentText()

        # 1 - FILTRADO
        if texto:
            filtrados = []
            for n in self._pool_original:
                if (texto in (n.titulo or "").lower() or
                    texto in (n.seccion or "").lower()):
                    filtrados.append(n)
        else:
            filtrados = list(self._pool_original)

        # 2 - ORDENAMIENTO
        if modo == "Por sección":
            filtrados.sort(key=lambda n: (n.seccion or "").lower())
        elif modo == "Por título":
            filtrados.sort(key=lambda n: (n.titulo or "").lower())
        elif modo == "Por caracteres":
            filtrados.sort(key=lambda n: n.chars)
        elif modo == "Por fecha":
            filtrados.sort(key=lambda n: n.created)
        elif modo == "Por hora ↑":
            filtrados.sort(key=lambda n: n.created)
        elif modo == "Por hora ↓":
            filtrados.sort(key=lambda n: n.created, reverse=True)
        elif modo == "Por palabras ↓":
            filtrados.sort(key=lambda n: n.chars, reverse=True)
        elif modo == "Por palabras ↑":
            filtrados.sort(key=lambda n: n.chars)
        elif modo == "Por texto ↓":
            filtrados.sort(key=lambda n: len(n.titulo or ""), reverse=True)
        elif modo == "Por texto ↑":
            filtrados.sort(key=lambda n: len(n.titulo or ""))

        # 3 - Aplicar
        self._cargar_pool_filtrado(filtrados)

    
    def _poblar_pool_ui(self):
        """
        Actualiza los buffers internos del pool (lista plana) a partir de
        controller.pool_notas y aplica el filtro/orden actual para poblar
        mono_lista.
        """
        # Guardamos copia de la lista de notas
        self._pool_original = list(getattr(self.controller, "pool_notas", []))
        self._pool_filtrado = list(self._pool_original)

        # Aplica búsqueda + orden y recarga mono_lista
        self._filtrar_y_ordenar_pool()

 

    
    def on_pool_timer(self):
        if not self.action_armar_mono.isChecked():
            return
        self._iniciar_scraping_pool_async()


    
    def on_drop_pool_nota(self, numero_pagina: int, dir_pool: Path):
        """
        Se dispara cuando se suelta una nota del pool sobre un PageButton.
        Copia TXT+IMG desde el pool a materiales/Pnn y actualiza INI.
        """
        try:
            self.controller.copiar_pool_a_pagina(numero_pagina, dir_pool)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error al asignar nota",
                                          f"No se pudo copiar la nota del pool a P{numero_pagina:02d}:\n{e}")
            return

        # Refrescar UI de la página
        pagina = self.controller.gestor_paginas.obtener_pagina(numero_pagina)
        if pagina:
            self.actualizar_info_pagina(pagina)
        self.colorear_paginas()

    
    def on_toggle_armar_mono(self, checked: bool):
        if checked:
            self.stack_left.setCurrentWidget(self.panel_mono)
            # Cargar notas en disco inmediatamente (sin scraping)
            try:
                self.controller.refresh_pool_notas_hoy()
                notas = self.controller.pool_notas
                if notas:
                    self._pool_original = list(notas)
                    self._cargar_pool_filtrado(notas)
            except Exception as e:
                _log.error(f"[POOL] Error cargando notas previas: {e}")
            # Actualizar label del botón según estado
            self._actualizar_btn_pool_scan()
        else:
            # Destildar el menú: el pool continúa en segundo plano.
            # El usuario vuelve al panel de armado; los botones de carga
            # de link siguen bloqueados si el scraper sigue corriendo.
            self.stack_left.setCurrentWidget(self.panel_armado_maquetacion)
            # Refrescar restricción por si la página activa tiene "Cargar link"
            self._aplicar_restriccion_pool()


    
    # =========================
    # Armar mono – notas del día
    # =========================
    
    from PyQt5.QtCore import QPoint

    from PyQt5.QtCore import QPoint

    def _posicionar_pool_spinner(self):
        """Centra el spinner sobre la lista del pool, como overlay."""
        if not self.pool_spinner.isVisible():
            return

        lista = self.mono_lista
        vp = lista.viewport()

        # Obtener centro visible
        rect = vp.rect()
        cx = rect.width() // 2
        cy = rect.height() // 2

        center_global = vp.mapTo(self.panel_mono, QPoint(cx, cy))

        # Ajustar al tamaño real del GIF
        w = self.pool_spinner.width()
        h = self.pool_spinner.height()

        self.pool_spinner.move(center_global.x() - w // 2,
                           center_global.y() - h // 2)
        self.pool_spinner.raise_()



    
    def _on_scrape_pool_finished(self):
        """UI-only: spinner y botón. NO tocar _pool_thread/_pool_worker aquí."""
        self.pool_spinner_movie.stop()
        self.pool_spinner.setVisible(False)
        self._pool_estado = "idle"
        self._actualizar_btn_pool_scan()
        _log.info("[POOL] Scraping completado.")

    def _on_pool_item_ready(self, nota):
        # Primera nota recibida: el descargador ya arrancó → pasar a "corriendo"
        if self._pool_estado == "iniciando":
            self._pool_estado = "corriendo"
            self._actualizar_btn_pool_scan()

        # 1) Agregar al buffer original
        self._pool_original.append(nota)

        # 2) Reaplicar filtro/orden SIN borrar scroll
        self._filtrar_y_ordenar_pool()
    
    def _iniciar_scraping_pool_async(self):
        """
        Lanza el scraping del pool en un QThread.

        Ciclo de vida seguro:
          worker.finished/stopped/error  →  _pool_thread.quit()
          _pool_thread.finished          →  _cleanup_pool_thread()   ← ÚNICO lugar
                                            donde se tocan _pool_thread/_pool_worker
        Los slots de UI (spinner, botón) NO nullean las referencias Qt para no
        triggear GC mientras el hilo todavía está procesando señales.
        """
        if self._pool_estado != "idle":
            return  # ya hay un ciclo activo (guard robusto)

        self._pool_estado = "iniciando"   # visible inmediatamente antes de crear el hilo
        self._actualizar_btn_pool_scan()

        # Spinner
        self.pool_spinner.setVisible(True)
        self.pool_spinner_movie.start()
        self._posicionar_pool_spinner()

        # Crear hilo y worker
        self._pool_thread = QtCore.QThread()
        self._pool_worker = PoolScrapeWorker(self.controller)
        self._pool_worker.moveToThread(self._pool_thread)

        # ── Señales de progreso → UI (solo actualizan interfaz) ──
        self._pool_worker.item_ready.connect(self._on_pool_item_ready)
        self._pool_worker.finished.connect(self._on_scrape_pool_finished)
        self._pool_worker.stopped.connect(self._on_scrape_pool_stopped)
        self._pool_worker.error.connect(self._on_scrape_pool_error)

        # ── Ciclo de vida: worker terminado → hilo sale ──
        self._pool_worker.finished.connect(self._pool_thread.quit)
        self._pool_worker.stopped.connect(self._pool_thread.quit)
        self._pool_worker.error.connect(self._pool_thread.quit)

        # ── Limpieza de objetos Qt: SOLO cuando el hilo realmente terminó ──
        self._pool_thread.finished.connect(self._cleanup_pool_thread)

        self._pool_thread.started.connect(self._pool_worker.run)
        self._pool_thread.start()

  

    def _on_queue_scrape_error(self, numero: int, msg: str):
        """Called by controller when queue worker fails a scrape."""
        if "NOTA_NO_DISPONIBLE" in msg.upper():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                f"P{numero:02d} — nota no disponible",
                f"La nota P{numero:02d} no está disponible (ocupada o sin respuesta).\n"
                "Podés reintentar más tarde desde el menú contextual → Asignación / avisos → Cargar link."
            )
        self._despues_de_cambio_estado(numero)

    def _on_scrape_pool_error(self, msg):
        """UI-only: spinner y botón. NO tocar _pool_thread/_pool_worker aquí."""
        _log.info(f"[POOL] Error en scraping asincrónico:\n{msg}")
        self.pool_spinner_movie.stop()
        self.pool_spinner.setVisible(False)
        self._pool_estado = "idle"
        self._actualizar_btn_pool_scan()

    def _on_scrape_pool_stopped(self) -> None:
        """UI-only: spinner y botón. NO tocar _pool_thread/_pool_worker aquí."""
        self.pool_spinner_movie.stop()
        self.pool_spinner.setVisible(False)
        self._pool_estado = "idle"
        self._actualizar_btn_pool_scan()
        _log.info("[POOL] Scraping detenido por el usuario.")

    def _cleanup_pool_thread(self) -> None:
        """
        Llamado por _pool_thread.finished — el hilo ya paró completamente.
        Es el ÚNICO lugar donde se anulan y se schedula la eliminación de
        _pool_worker y _pool_thread, evitando "QThread: Destroyed while running".
        """
        worker = self._pool_worker
        thread = self._pool_thread
        # Soltar referencias Python ANTES de deleteLater para que el GC no
        # interfiera con la eliminación gestionada por Qt.
        self._pool_worker = None
        self._pool_thread = None
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception:
                pass
        if thread is not None:
            try:
                thread.deleteLater()
            except Exception:
                pass
        _log.info("[POOL] Hilo liberado correctamente.")

    def _aplicar_restriccion_pool(self) -> None:
        """
        Bloquea o desbloquea el botón 'Cargar link' de la toolbar según si
        el pool scraper está activo. Se llama:
          - Al iniciar/detener/terminar el pool (_actualizar_btn_pool_scan).
          - Al volver al panel de armado con el pool activo (on_toggle_armar_mono).
          - Al actualizar el boton_quitar en actualizar_info_pagina (ya inline).

        Sólo actúa cuando el botón muestra "Cargar link"; los estados
        "Asignar" y "Quitar asignación" no tienen riesgo de colisión.
        """
        corriendo = self._pool_estado != "idle"
        btn = getattr(self, "boton_quitar", None)
        if btn is None:
            return
        if btn.text().strip().lower() == "cargar link":
            if corriendo:
                btn.setEnabled(False)
                btn.setToolTip("El bot está en uso con la lista de noticias. Esperá a que termine.")
            else:
                btn.setEnabled(True)
                btn.setToolTip("")

    def _actualizar_btn_pool_scan(self) -> None:
        """
        Sincroniza texto, estilo y habilitación del botón con _pool_estado.

          "idle"       → "Iniciar" o "Actualizar"  (habilitado)
          "iniciando"  → "Iniciando…"              (deshabilitado)
          "corriendo"  → "Detener"                 (habilitado)
          "deteniendo" → "Deteniendo…"             (deshabilitado)
        """
        estado = self._pool_estado

        if estado == "iniciando":
            self.btn_pool_scan.setText("Iniciando…")
            self.btn_pool_scan.setEnabled(False)
            self.btn_pool_scan.setProperty("detener", False)

        elif estado == "corriendo":
            self.btn_pool_scan.setText("Detener")
            self.btn_pool_scan.setEnabled(True)
            self.btn_pool_scan.setProperty("detener", True)

        elif estado == "deteniendo":
            self.btn_pool_scan.setText("Deteniendo…")
            self.btn_pool_scan.setEnabled(False)
            self.btn_pool_scan.setProperty("detener", True)

        else:  # "idle"
            hay_notas = bool(getattr(self, "_pool_original", []))
            self.btn_pool_scan.setText("Actualizar" if hay_notas else "Iniciar")
            self.btn_pool_scan.setEnabled(True)
            self.btn_pool_scan.setProperty("detener", False)

        self.btn_pool_scan.style().unpolish(self.btn_pool_scan)
        self.btn_pool_scan.style().polish(self.btn_pool_scan)
        self._aplicar_restriccion_pool()

    def _on_btn_pool_scan_clicked(self) -> None:
        """Click en el botón Iniciar / Actualizar / Detener."""
        estado = self._pool_estado
        if estado == "idle":
            self._iniciar_scraping_pool_async()
        elif estado == "corriendo":
            self._detener_scraping_pool()
        # "iniciando" y "deteniendo": botón deshabilitado, no llega aquí

    def _detener_scraping_pool(self) -> None:
        """
        Detiene el scraping en curso:
        1. Cambia el estado a "deteniendo" → botón muestra "Deteniendo…" (deshabilitado).
        2. Pide al worker que se detenga en la próxima iteración.
        3. El worker emite stopped() → _pool_thread.quit() → _cleanup_pool_thread().
        4. Navega Chrome al home del Manager (libera la nota abierta).
        """
        if self._pool_estado not in ("corriendo", "iniciando"):
            return

        self._pool_estado = "deteniendo"
        self._actualizar_btn_pool_scan()

        try:
            if self._pool_worker is not None:
                self._pool_worker.stop()
        except Exception as e:
            _log.info(f"[POOL] Error al pedir stop al worker: {e}")

        try:
            scraper = self.controller._get_scraper()
            drv = getattr(scraper, "_driver", None)
            if drv:
                drv.get(scraper.base_url.rstrip("/"))
                _log.info("[POOL] Navegador restaurado al home tras detener.")
        except Exception as e:
            _log.warning(f"[POOL] No se pudo navegar al home tras detener: {e}")

    def on_pool_selection_changed(self):
        """
        Cuando el usuario selecciona una nota del pool, reutilizamos el visor de texto
        y fragmentos.

        Más adelante, esta función delegará en el controlador para obtener los
        fragmentos reales (///). Por ahora, si hay una ruta de TXT válida en el item,
        se muestra el texto completo.
        """
        if not hasattr(self, "mono_lista"):
            return

        selected_items = self.mono_lista.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict):
            # Nodo de sección u objeto sin datos de TXT (solo encabezado de sección)
            return

        txt = data.get("txt")
        if not txt:
            return

        try:
            path = Path(txt)
            if path.exists():
                contenido = path.read_text(encoding="utf-8", errors="ignore")
                # Reutilizamos el editor de texto actual
                self.texto_noticia.setPlainText(contenido)
                # TODO: más adelante poblar self.lista_fragmentos con fragmentos reales
                self.lista_fragmentos.clear()
        except Exception as e:
            _log.warning(f"[WARN] No se pudo leer TXT del pool: {e}")
        
        # --- FIX 2: si el diálogo está abierto, recargarlo ---
        if hasattr(self, "pool_editor") and self.pool_editor.isVisible():
            # Reutilizamos TODA la lógica que ya existe en el doble clic
            self.on_pool_item_double_clicked(item, 0)

    


    def on_pool_item_double_clicked(self, item, column):
        """
        Abre el editor flotante para la noticia seleccionada del POOL.
        Usa el dict cargado en Qt.UserRole (no índices).
        """
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict):
            return

        dir_path = Path(data.get("dir", ""))
        txt_path = Path(data.get("txt", ""))

        if not dir_path or not txt_path.exists():
            return

        

        # ---------- CARGAR META.JSON ----------
        meta_path = dir_path / "_meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except:
                meta = {}

        # ============ CARGAR Y PARSEAR TXT ============
        try:
            texto = txt_path.read_text(encoding="utf-8", errors="ignore")
        except:
            texto = ""

        partes = [p.strip() for p in texto.split("///")]

        volanta = partes[0] if len(partes) > 0 else ""
        titulo  = partes[1] if len(partes) > 1 else ""
        bajada  = partes[2] if len(partes) > 2 else ""

        # IMPORTANTE:
        # La 4ta parte del TXT es la FIRMA, NO el autor del Manager.
        firma   = partes[3] if len(partes) > 3 else ""

        # Cuerpo = todo lo que sigue
        if len(partes) > 4:
            cuerpo = "///".join(partes[4:]).strip()
        else:   
            cuerpo = ""

        # ==============================================
        # USAMOS EL AUTOR/FECHAS DESDE EL META.JSON
        # ==============================================
        autor_creacion = meta.get("autor_creacion", "")
        fecha_creacion = meta.get("fecha_creacion", "")
        autor_modif    = meta.get("autor_modificacion", "")
        fecha_modif    = meta.get("fecha_modificacion", "")

        # Este dict es lo que recibe PoolEditorDialog
        meta_parseado = {
            "volanta": volanta,
            "titulo": titulo,
            "bajada": bajada,
            "firma": firma,
            "autor_creacion": autor_creacion,
            "fecha_creacion": fecha_creacion,
            "autor_modificacion": autor_modif,
            "fecha_modificacion": fecha_modif,
        }

        # --------- ABRIR EDITOR FLOTANTE ---------
        self.pool_editor.cargar_noticia(dir_path, meta_parseado, cuerpo)

        self.pool_editor.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.pool_editor.show()
        self.pool_editor.activateWindow()

        self._pool_editor_activo = True



    def _on_pool_guardar_cambios(self, data: dict):
        """
        Guarda los cambios del dialogo en:
        - TXT del pool (formato ///)
        - _meta.json
        - Renombrado de carpeta SI cambia el título
        - Refresco de la lista del pool
        """ 
        dir_pool: Path = data["dir"]
        nuevo_titulo   = data["titulo"]
        nueva_volanta  = data["volanta"]
        nueva_bajada   = data["bajada"]
        nuevo_autor    = data["autor_creacion"]
        firma_flag     = data.get("firmado", False)
        firma          = nuevo_autor if firma_flag else ""
        cuerpo         = data["cuerpo"].strip()

        # (1) ============================
        #   ACTUALIZAR _meta.json
        # ================================
        meta_path = dir_pool / "_meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except:
                meta = {}

        meta["titulo"]          = nuevo_titulo
        meta["volanta"]         = nueva_volanta
        meta["bajada"]          = nueva_bajada
        meta["autor_creacion"]  = nuevo_autor
        meta["firmado"]         = bool(firma_flag)
        meta["imagenes"]        = data.get("imagenes", [])

        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # (2) ============================
        #   RECONSTRUIR TXT (FORMATO ///)
        # ==    ==============================
        txt_main = next((f for f in dir_pool.iterdir() if f.suffix.lower() == ".txt"), None)

        if txt_main:
            # Si había epígrafe antes, intentamos preservarlo
            try:    
                partes = txt_main.read_text(encoding="utf-8", errors="ignore").split("///")
                epigrafe_original = partes[4].strip() if len(partes) > 4 else ""
            except:
                epigrafe_original = ""

            # Si hay epígrafe en meta (nuevo), usar ese
            # Si no, conservar el original
            imgs_meta = meta.get("imagenes", [])
            if imgs_meta:
                epi_nuevo = imgs_meta[0].get("epigrafe", "")
                if epi_nuevo.strip():
                    epigrafe_original = epi_nuevo.strip()

            # Construcción final del TXT
            nuevo_txt = (
                f"{nueva_volanta.strip()}\n///\n"
                f"{nuevo_titulo.strip()}\n///\n"
                f"{nueva_bajada.strip()}\n///\n"
                f"{firma.strip()}\n///\n"
                f"{epigrafe_original.strip()}\n///\n"
                f"{cuerpo.strip()}"
            )

            txt_main.write_text(nuevo_txt, encoding="utf-8")

        # (3) ============================
        #   RENOMBRAR CARPETA SI CAMBIÓ EL TÍTULO
        # ================================
        carpeta_actual = dir_pool
        nueva_carpeta_nombre = f"{meta.get('seccion','')} - {nuevo_titulo}".strip()
        nueva_carpeta_nombre = self.controller.sanitize_folder_name(nueva_carpeta_nombre)

        if nueva_carpeta_nombre and carpeta_actual.name != nueva_carpeta_nombre:
            nueva_carpeta = carpeta_actual.parent / nueva_carpeta_nombre
            try:    
                carpeta_actual.rename(nueva_carpeta)
                _log.info(f"[POOL] Carpeta renombrada: {carpeta_actual.name} → {nueva_carpeta.name}")
            except Exception as e:
                _log.error(f"[POOL] No pude renombrar carpeta del pool: {e}")
                nueva_carpeta = carpeta_actual
        else:
            nueva_carpeta = carpeta_actual

        # (4) ============================
        #   REFRESCAR POOL
        # ================================
        self.controller.refresh_pool_notas_hoy()
        self._refrescar_lista_pool()

        self._pool_editor_activo = False


    def _refrescar_lista_pool(self):
        """
        Refresca la lista del POOL manteniendo:
        - selección actual (si existe)
        - scroll actual
        Además:
        - vuelve a leer controller.pool_notas
        - reprocesa filtros y orden
        - actualiza el visor de imágenes si corresponde
        """
        lista = self.mono_lista  # QTreeWidget real

        # --- 1. Guardar selección previa ---
        item_prev = lista.currentItem()
        prev_dir = None
        if item_prev:
            data = item_prev.data(0, Qt.UserRole)
            if isinstance(data, dict):
                prev_dir = str(data.get("dir", "")).strip()

        # Guardar posición de scroll
        try:
            scroll_bar = lista.verticalScrollBar()
            prev_scroll = scroll_bar.value()
        except Exception:
            prev_scroll = 0

        # --- 2. Recargar datos desde el controller ---
        try:
            self.controller.refresh_pool_notas_hoy()
            self._poblar_pool_ui()  # esto aplica filtro/orden y rellena mono_lista
        except Exception as e:
            _log.info(f"[POOL] Error refrescando pool: {e}")
            return

        # --- 3. Restaurar selección si es posible ---
        restored = False
        if prev_dir:
            root = lista.invisibleRootItem()
            for i in range(root.childCount()):
                item = root.child(i)
                data = item.data(0, Qt.UserRole)
                if isinstance(data, dict):
                    dir_val = str(data.get("dir", "")).strip()
                    if dir_val == prev_dir:
                        lista.setCurrentItem(item)
                        restored = True
                        break

        

        # --- 5. Restaurar scroll ---
        try:
            scroll_bar = lista.verticalScrollBar()
            scroll_bar.setValue(prev_scroll)
        except Exception:
            pass

        # --- 6. Restaurar foco ---
        try:
            lista.setFocus()
        except Exception:
            pass


    
    
    def _actualizar_editor_si_navega_pool(self):
        """
        Si el editor está abierto y el usuario selecciona otra noticia,
        actualizar contenido del diálogo sin cerrarlo.
        """
        if not self.pool_editor.isVisible():
            return
        if self.pool_editor.hay_cambios_pendientes():
            return  # no pisar cambios sin guardar

        item = self.pool_list.currentItem()
        if not item:
            return

        idx = item.data(Qt.UserRole)
        if idx is None or idx < 0 or idx >= len(self.controller.pool_notas):
            return

        nota = self.controller.pool_notas[idx]

        # meta
        meta_path = nota.dir_path / "_meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except:
                meta = {}

        # txt
        try:
            texto = nota.txt_path.read_text(encoding="utf-8", errors="ignore")
        except:
            texto = ""

        self.pool_editor.cargar_noticia(nota.dir_path, meta, texto)

    ### --- fin sección armado mono --- ###
    
    
    def on_click_pagina(self, numero: int):
        if not getattr(self, "base_activa", False):
            return

        # En modo enroque, el click elige/deselecciona la página Y (no activa la página).
        if getattr(self, "_enroque_mode", False):
            if numero == self._enroque_x:
                return                              # X no puede ser Y
            if self._enroque_y == numero:
                self._enroque_y = None              # segundo clic en la misma → deselecciona
            else:
                self._enroque_y = numero            # clic en otra → cambia selección
            self._enroque_label.setText(self._enroque_texto())
            self._enroque_btn_aceptar.setEnabled(self._enroque_y is not None)
            self.colorear_paginas()
            return

        if self.pagina_activa:
            pagina_ant = self.controller.gestor_paginas.obtener_pagina(self.pagina_activa)
            self._apply_button_style_for_page(self.boton_paginas[self.pagina_activa], pagina_ant)

        self.pagina_activa = numero
        self._load_images_for_page(numero)
        self.label_pagina_activa.setText(f"Página activa: {numero}")
        pagina = self.controller.seleccionar_pagina(numero)
        self._update_label_asignacion(numero)
        self._apply_button_style_for_page(self.boton_paginas[numero], pagina)

        tiene_txt = bool(pagina.asignado)
        tiene_aviso_full = bool(getattr(pagina, "aviso_full", False))
        tiene_aviso_half = bool(getattr(pagina, "aviso_half", False))
        tiene_aviso_footer = bool(getattr(pagina, "aviso_footer", False))
        tiene_aviso_roba = bool(getattr(pagina, "aviso_robapagina", False))
        tiene_asignada_ini = bool(getattr(pagina, "asignada_por_ini", False))

        # "Hay algo" significa: texto o cualquier aviso
        tiene_algo = bool(
            tiene_txt
            or tiene_aviso_full
            or tiene_aviso_half
            or tiene_aviso_footer
            or tiene_aviso_roba
        )

        if tiene_asignada_ini and not tiene_algo:
            self.statusBar().showMessage(
                f"Pág. {numero}: asignada por otro puesto. Usá 'Quitar asignación' si querés limpiarla o reasignarla.",
                4000
            )
            self._update_label_asignacion(numero)
            return

        self._update_aviso_nombre(pagina)
        self.actualizar_info_pagina(pagina)
        self.colorear_paginas()
        self.mostrar_fragmentos(numero)
        self.actualizar_botonera_mover_devolver()
        estilos = self.boton_paginas[numero].styleSheet()
        self.boton_paginas[numero].setStyleSheet(estilos + " border: 6px solid #4043EB;")
        self._update_label_asignacion(numero)
        # Actualizar maqueta si corresponde (Maquetación, o si el "Panel de aviso" está abierto)
        if self.controller.perfil == "Maquetación y avisos" or getattr(self, "_panel_modo", 0) == 2:
            self.maqueta_widget.set_pagina(pagina)

    def _update_aviso_nombre(self, pagina):
        nombre = (getattr(pagina, "aviso_nombre", "") or "").strip()
        self.label_aviso_nombre.setText(f"Aviso: {nombre if nombre else '—'}")

    
    def on_cargar_avisos_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Excel de avisos",
            "",
            "Archivos Excel (*.xlsx *.xls)"
        )
        if not path:
            return
        
        try:
            mapping, skipped = self.controller.importar_avisos_desde_excel(Path(path))

            # Backup del INI por seguridad (opcional)
            try:
                self.controller.file_service.backup_shared_ini_copy()
            except Exception:
                pass

            usuario = (self.controller.usuario or "").strip()
            for n, nombre in mapping.items():
            # Guardar el nombre del aviso (no el del Excel)
                self.controller.file_service.set_aviso_nombre(n, nombre, by=usuario)

            # Refrescar estados y UI
            self.controller.refrescar_avisos_desde_ini()
            self.colorear_paginas()

            if self.pagina_activa:
                pag = self.controller.gestor_paginas.obtener_pagina(self.pagina_activa)
                self.maqueta_widget.set_pagina(pag)
                self._update_aviso_nombre(pag)

            QMessageBox.information(
                self,
                "Importación de avisos",
                f"Importados {len(mapping)} avisos. Filas omitidas: {skipped}."
            )
        except Exception as e:
            QMessageBox.critical(self, "Importación de avisos", str(e))




    def on_crear_base(self):
        #try:
        #    asegurar_rutas_ini()
        #except SystemExit:
        #    return
        #except Exception as e:
        #    QMessageBox.critical(self, "Rutas/Base", str(e))
        #    return
        
        ini_path = Config.CONFIG_FILE
        cfg = configparser.ConfigParser()
        if ini_path.exists():
            cfg.read(str(ini_path), encoding="utf-8")

        usuario_cfg = ""
        if cfg.has_section("USUARIO"):
            usuario_cfg = (cfg.get("USUARIO", "user", fallback="") or "").strip()

        if not usuario_cfg:
            QMessageBox.warning(
                self,
                "Usuario no configurado",
                "Debe configurar el usuario antes de crear la base.\n"
                "Vaya a Usuario → Configurar usuario."
            )
            self.on_configurar_usuario()

            cfg = configparser.ConfigParser()
            if ini_path.exists():
                cfg.read(str(ini_path), encoding="utf-8")
            usuario_cfg = ""
            if cfg.has_section("USUARIO"):
                usuario_cfg = (cfg.get("USUARIO", "user", fallback="") or "").strip()
            if not usuario_cfg:
                return

        self.controller.usuario = usuario_cfg

        try:
            def prompt_fn(clave, titulo):
                return QFileDialog.getExistingDirectory(self, titulo)

            info = self.controller.crear_base_on_click(prompt_fn)

        except Exception as e:
            QMessageBox.critical(self, "Rutas/Base", str(e))
            return

        self.controller.refrescar_avisos_desde_ini()

        # En lugar de hacer un verificar_qxp_pdf() sincrónico aquí,
        # activamos la base y disparamos el poll en background.
        self.base_activa = True
        if not self.timer.isActive():
            self.timer.start()

        # Watcher de extensión Chrome — arranca junto con la base
        self._chrome_watcher = ChromeWatcher(
            self.controller.file_service,
            by=(self.controller.usuario or ""),
        )
        self._chrome_watcher.nota_descargada.connect(self._on_chrome_nota_descargada)
        self._chrome_watcher.error_proceso.connect(
            lambda msg: self.statusBar().showMessage(f"[Chrome] {msg}", 5000)
        )
        self._chrome_watcher.start(5000)

        self.colorear_paginas()
        self.on_poll()




    def on_poll(self):
        if not getattr(self, "base_activa", False):
            return
        if getattr(self, "_poll_running", False):
            return  # evitar solapamiento si la red viene lenta

        self._poll_running = True

        th = QThread(self)
        wk = PollWorker(self.controller)

        wk.moveToThread(th)
        th.started.connect(wk.run)

        # Al terminar el trabajo, actualizamos UI en el hilo principal
        wk.done.connect(self._on_poll_done)
        wk.error.connect(self._on_poll_error)

        # Limpieza del thread/worker
        wk.finished.connect(th.quit)
        wk.finished.connect(lambda: setattr(self, "_poll_running", False))
        wk.finished.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)

        # Guardar referencias (opcional, por si querés chequear estado)
        self._poll_thread = th
        self._poll_worker = wk

        th.start()

    def _on_poll_done(self, hubo_cambios: bool):
        self._poll_running = False

        # ✅ Refrescar INI en el hilo principal (seguro)
        try:
            self.controller.refrescar_avisos_desde_ini()
        except Exception as e:
            _log.warning(f"[WARN] refrescar_avisos_desde_ini: {e}")

        # Luego de actualizar, refrescar vista
        self.colorear_paginas()
        if hubo_cambios:
            self.actualizar_botonera_mover_devolver()
        elif self.pagina_activa:
            self._update_label_asignacion(self.pagina_activa)
            pag = self.controller.gestor_paginas.obtener_pagina(self.pagina_activa)
            if pag:
                self._update_aviso_nombre(pag)
        
        # --- Reactivar botón "+" si la página tiene al menos una nota asignada ---
        if hasattr(self, "boton_agregar_nota") and hasattr(self, "pagina_activa") and self.pagina_activa:
            try:
                entry = self.controller.file_service.read_page_entry(self.pagina_activa)
                tiene_txt = self.controller.file_service.has_notas(self.pagina_activa)
                self.boton_agregar_nota.setEnabled(tiene_txt)
                self.boton_agregar_nota.setText("+")
                if tiene_txt:
                    self.statusBar().showMessage(f"✅ P{self.pagina_activa:02d}: nueva nota agregada correctamente", 3000)
            except Exception as e:
                _log.warning(f"[WARN] No se pudo reactivar botón '+': {e}")




    def _on_poll_error(self, msg: str):
        self._poll_running = False
        # No frenes la app por errores de red: mostrás un aviso suave
        self.statusBar().showMessage(f"Problema al refrescar estados: {msg}", 4000)




    def mostrar_fragmentos(self, numero: int):
        """
        Muestra los fragmentos de la noticia actual (A/B/C) de la página indicada.
        """
        indice = getattr(self, "_noticia_index", 0)
        frags = self.controller.obtener_fragmentos(numero, indice)
        self.lista_fragmentos.blockSignals(True)
        self.lista_fragmentos.clear()
        for i, frag in enumerate(frags, start=1):
            preview = frag if len(frag) <= 120 else frag[:120] + "…"
            self.lista_fragmentos.addItem(f"{i}. {preview}")
        if len(frags) > 1:
            self.lista_fragmentos.setCurrentRow(1)
        elif len(frags) == 1:
            self.lista_fragmentos.setCurrentRow(0)

        
        self.lista_fragmentos.blockSignals(False)


    def on_fragment_selected(self, index: int):
        if index is None or index < 0 or not self.pagina_activa:
            self.texto_noticia.clear()
            self.texto_noticia.setReadOnly(True)
            return

        indice = getattr(self, "_noticia_index", 0)
        frags = self.controller.obtener_fragmentos(self.pagina_activa, indice)


        if 0 <= index < len(frags):
            self.texto_noticia.setPlainText(frags[index])
            self.texto_noticia.setReadOnly(False)
        else:
            self.texto_noticia.clear()



    def colorear_paginas(self):
        for i, boton in self.boton_paginas.items():
            pagina = self.controller.gestor_paginas.obtener_pagina(i)
            boton.pagina = pagina
            self._apply_button_style_for_page(boton, pagina)
            if isinstance(boton, PageButton):
                boton.set_activa(i == self.pagina_activa)
        if self.pagina_activa:
            pag_act = self.controller.gestor_paginas.obtener_pagina(self.pagina_activa)
            self._apply_button_style_for_page(self.boton_paginas[self.pagina_activa], pag_act)
            estilos = self.boton_paginas[self.pagina_activa].styleSheet()
            self.boton_paginas[self.pagina_activa].setStyleSheet(estilos + " border: 6px solid #4043EB;")
        # Post-proceso: cuando la grilla ya está repintada
        if not self._avisos_real_cargando:
            QTimer.singleShot(0, self._cargar_avisos_reales_despues_de_pintado)



    def _apply_button_style_for_page(self, boton: QPushButton, pagina):
        estado = self._estado_visible(pagina)
        # Si la base aún no fue creada, forzar gris claro para todos
        if not getattr(self, "base_activa", False): 
            color_base = "#a8a8a8"   # gris claro inicial (antes de crear base)
        else:
            color_base = COLOR_ESTADOS.get(estado, "#d3d3d3")
        
        # --- Detectar cambio de color (para forzar repaint solo si cambia) ---
        prev_color = getattr(boton, "_estado_color", None)
        if not prev_color or prev_color.name() != color_base:
            boton.update()

        # --- Guardar estado y color para que el paintEvent y draw_static lo usen ---
        boton._estado = estado
        boton._estado_color = QColor(color_base)

        # --- Modo enroque: las páginas X e Y seleccionadas se pintan naranja ---
        if getattr(self, "_enroque_mode", False):
            n = getattr(pagina, "numero", None)
            if n is not None and n in (getattr(self, "_enroque_x", None),
                                       getattr(self, "_enroque_y", None)):
                color_base = "#e7885f"                    # modo armado (stylesheet)
                boton._estado_color = QColor("#e7885f")   # modo maquetación (paintEvent)
                boton.update()   # forzar repaint (el color puede no haber cambiado en la detección)



        base_text = str(pagina.numero)
        seccion_label = (getattr(pagina, "seccion", "") or "").strip()
        if getattr(pagina, "aviso_full", False):
            aviso_label = "Completa"
        elif getattr(pagina, "aviso_half", False):
            aviso_label = "Media"
        elif getattr(pagina, "aviso_footer", False):
            aviso_label = "Pie"
        elif getattr(pagina, "aviso_robapagina", False):
            aviso_label = "Robapágina"
        else:
            aviso_label = ""

        if seccion_label and aviso_label:
            font_px = 13
        elif seccion_label or aviso_label:
            font_px = 16
        else:
            font_px = 18

        usable_w = max(10, boton.width() - 12)
        wrapped_sec = self._wrap_lines(seccion_label, font_px, usable_w, max_lines=2)

        total_lines = 1 + len(wrapped_sec) + (1 if aviso_label else 0)
        if total_lines >= 4 and font_px > 12:
            font_px = 12
            wrapped_sec = self._wrap_lines(seccion_label, font_px, usable_w, max_lines=2)
            total_lines = 1 + len(wrapped_sec) + (1 if aviso_label else 0)

        # El tipo de aviso ya NO se muestra como label (se ve el aviso real vía draw_static);
        # la sección permanece. El texto visible lo pinta paintEvent; setText queda de fallback.
        lines = [base_text]
        lines.extend(wrapped_sec)

        color_text = "white" if color_base == "#2d2f30" else "black"

        # --- Flags primero: deben estar correctos antes del repaint de setStyleSheet ---
        if isinstance(boton, PageButton):
            boton.set_tapa_flags(
                getattr(pagina, "tapa_foto", False),
                getattr(pagina, "tapa_titulo", False)
            )
            boton.set_listo_flag(getattr(pagina, "listo_para_armar", False))
            boton.set_editando_flag(getattr(pagina, "editando", False))

        boton.setText("\n".join(lines))
        boton.setStyleSheet(
            f"background-color: {color_base}; "
            f"color: {color_text}; "
            f"font-size: {font_px}px; border-radius:8px; "
            f"text-align: center; padding: 0 4px;"
        )


    def actualizar_info_pagina(self, pagina):
        indice = getattr(self, "_noticia_index", 0)
        entry = self.controller.file_service.read_page_entry(pagina.numero)
        frags = self.controller.obtener_fragmentos(pagina.numero, indice)
        self.lista_fragmentos.blockSignals(True)
        self.lista_fragmentos.clear()
        
        for f in frags:
            self.lista_fragmentos.addItem(f)
        if len(frags) > 1:
            self.lista_fragmentos.setCurrentRow(1)
        elif len(frags) == 1:
            self.lista_fragmentos.setCurrentRow(0)
        self.lista_fragmentos.blockSignals(False)

        self.texto_noticia.clear()
        if len(frags) > 1:
            self.texto_noticia.setPlainText(frags[1])
            self.texto_noticia.setReadOnly(False)
        elif len(frags) == 1:
            self.texto_noticia.setPlainText(frags[0])
            self.texto_noticia.setReadOnly(False)
        else:
            # cargar txt desde la subcarpeta actual según el sistema de INI múltiple
            if hasattr(self, "_noticias") and self._noticias:
                noticia_dir = self._noticias[indice]
                txt_path = noticia_dir / f"{noticia_dir.name}.txt"
                if txt_path.exists():
                    try:
                        self.texto_noticia.setPlainText(txt_path.read_text(encoding="utf-8"))
                    except Exception:
                        self.texto_noticia.setPlainText(txt_path.read_text(encoding="utf-8-sig"))
                else:
                    self.texto_noticia.setPlainText("(Sin texto)")
            else:
                self.texto_noticia.setPlainText("(Sin texto)")

            self.texto_noticia.setReadOnly(True)

        # --- Ajuste de botones según perfil ---
        if self.controller.perfil == "Maquetación y avisos":
            # "Abrir imagen"
            img = self.controller.file_service.find_material_image_for_page(pagina.numero)
            self.boton_pegar.setEnabled(bool(img))

            # En Maquetación no se usa "Quitar asignación": lo ocultamos
            self.boton_quitar.setVisible(False)

            # "Abrir Quark"
            self.boton_abrir_quark.setEnabled(
                bool(self.controller.file_service.find_qxp_final(pagina.numero)
                    or self.controller.file_service.find_qxp_base(pagina.numero))
            )
        else:
            # Perfil Armado: comportamiento original
            self.boton_quitar.setVisible(True)  # restaurar en perfil Armado
            tiene_txt = bool(pagina.asignado)
            asignacion_local = bool(getattr(pagina, "asignada_por_ini", False))
            asignada_cualquiera = bool(getattr(pagina, "asignada_por_ini", False))
            
            es_completa = bool(getattr(pagina, "aviso_full", False))
            #has_aviso = bool(
            #    entry.get("aviso_full") or
            #    entry.get("aviso_half") or
            #    entry.get("aviso_footer") or
            #    entry.get("aviso_robapagina") or
            #    (entry.get("aviso_nombre") or "").strip()
            #)

            self.boton_pegar.setEnabled(asignacion_local and (bool(frags) or es_completa))

            if not tiene_txt and not es_completa:
                self.boton_quitar.setText("Cargar link")
                if self._pool_estado != "idle":
                    self.boton_quitar.setEnabled(False)
                    self.boton_quitar.setToolTip("El bot está en uso con la lista de noticias. Esperá a que termine.")
                else:
                    self.boton_quitar.setEnabled(True)
                    self.boton_quitar.setToolTip("")
            else:
                if asignada_cualquiera:
                    self.boton_quitar.setText("Quitar asignación")
                    self.boton_quitar.setEnabled(True)
                else:
                    self.boton_quitar.setText("Asignar")
                    self.boton_quitar.setEnabled(True)
            self.boton_abrir_quark.setEnabled(False)
        # --- Habilitar el botón "+" solo si ya hay una nota asignada ---

        tiene_txt = self.controller.file_service.has_notas(pagina.numero)
        self.boton_agregar_nota.setEnabled(tiene_txt)

        self._update_label_asignacion(pagina.numero)
        self._update_aviso_nombre(pagina)



    def actualizar_botonera_mover_devolver(self):
        pag = self.controller.gestor_paginas.get_activa()
        if not pag:
            self.boton_mover.setEnabled(False)
            self.boton_devolver.setEnabled(False)
            return
        decision = self.controller.decidir_botones(pag.numero)
        m = decision["mover"]; d = decision["devolver"]

        self.boton_mover.setText(m["label"])
        self.boton_mover.setEnabled(m["enabled"])
        self.boton_mover._src = m["src"]
        self.boton_mover._dest = m["dest"]

        self.boton_devolver.setText(d["label"])
        self.boton_devolver.setEnabled(d["enabled"])
        self.boton_devolver._src = d["src"]
        self.boton_devolver._dest = d["dest"]

        # --- Color especial si el QXP está en proceso pero no en Base/Final/Mandar ---
        try:
            perfil = getattr(self.controller, "perfil", "Armado y corrección")  # default por seguridad

            if perfil == "Armado y corrección":
                rutas = self.controller.file_service.rutas or {}
                base = Path(rutas.get("quark_output_dir") or "")
                personal = Path(rutas.get("personal_folder") or "")
                final = base / "final"
                mandar = final / "mandar"

                en_proceso = personal.exists() and self.controller.file_service.buscar_qxp_por_numero(personal, pag.numero)
                en_destino = (
                    (base.exists()   and self.controller.file_service.buscar_qxp_por_numero(base, pag.numero)) or
                    (final.exists()  and self.controller.file_service.buscar_qxp_por_numero(final, pag.numero)) or
                    (mandar.exists() and self.controller.file_service.buscar_qxp_por_numero(mandar, pag.numero))
                )

                if en_proceso and not en_destino:
                    self.boton_mover.setStyleSheet(
                        self.boton_mover.styleSheet() + """
                            QPushButton {
                            color: white;
                            font-weight: bold;
                            background-color: goldenrod;
                            }
                            """
                        ) 
                else:
                    self.boton_mover.setStyleSheet(style_btn)
            else:
                # En Maquetación y otros perfiles → nunca naranja
                self.boton_mover.setStyleSheet(style_btn)
        except Exception:
            self.boton_mover.setStyleSheet(style_btn)



    def on_pegar(self):
        """Genera los fragmentos y lanza el pegado en Quark."""

        # --- En perfil Maquetación ---
        if self.controller.perfil == "Maquetación y avisos":
            self.on_abrir_imagen()
            return

        pagina = self.pagina_activa
        indice = getattr(self, "_noticia_index", 0)
        subfolder = self._subfolder_activo()

        cfg = configparser.ConfigParser()
        cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
        version_quark = cfg.get("quark", "quark_seleccionado", fallback="Quark 8").strip()

        texto = self.controller._leer_y_normalizar(pagina, indice)

        # En Quark 8 (flujo AHK) solo se puede pegar texto
        if version_quark == "Quark 8" and not texto:
            QMessageBox.information(self, "Sin texto",
                                    "Esta página no tiene texto para pegar todavía.")
            return

        # En Quark 2018+ permitimos pegar aviso aunque no haya texto
        if version_quark != "Quark 8" and not texto:
            entry = self.controller.file_service.read_page_entry(pagina)
            aviso_nombre = (entry.get("aviso_nombre") or "").strip()
            aviso_path = (
                self.controller.file_service.material / f"P{pagina:02d}" / aviso_nombre
                if aviso_nombre else None
            )
            fotos_estado = self._fotos_estado
            tiene_fotos  = bool(fotos_estado.get("fotos"))
            if not (aviso_path and aviso_path.exists()) and not tiene_fotos:
                QMessageBox.information(self, "Sin contenido",
                                        "Esta página no tiene texto, aviso ni fotos para pegar.")
                return

        # ── Comprobación 1: ¿ya fue pegado con el mismo estado? ──────────────
        if self.controller.ya_fue_pegado(pagina, subfolder, texto):
            resp = QMessageBox.question(
                self, "Contenido ya pegado",
                "Las fotos, texto y/o avisos ya fueron pegados con este mismo estado.\n\n"
                "¿Desea continuar y pegar de todas formas?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

        # ── Comprobación 2: ¿hay fotos seleccionadas sin editar? ──────────────
        excluir_fotos = False
        sin_editar = self.controller.fotos_sin_editar(pagina, subfolder)
        if sin_editar:
            nombres = "\n".join(f"  • {Path(p).name}" for p in sin_editar)
            msg = (
                f"Las siguientes fotos seleccionadas no han sido editadas "
                f"desde su descarga:\n\n{nombres}\n\n"
                f"¿Desea pegarlas de todas formas?"
            )
            mb = QMessageBox(self)
            mb.setWindowTitle("Fotos sin editar")
            mb.setText(msg)
            mb.setIcon(QMessageBox.Warning)
            btn_si       = mb.addButton("Sí, pegar todo",         QMessageBox.YesRole)
            btn_solo_txt = mb.addButton("Sólo texto/aviso",       QMessageBox.NoRole)
            btn_no       = mb.addButton("No, cancelar",           QMessageBox.RejectRole)
            mb.setDefaultButton(btn_no)
            mb.exec_()
            clicked = mb.clickedButton()
            if clicked == btn_no:
                return
            if clicked == btn_solo_txt:
                excluir_fotos = True

        # ── Pegado ────────────────────────────────────────────────────────────
        if version_quark == "Quark 8":
            fragments_path = Config.RUNTIME_SCRIPTS_DIR / "fragments.txt"
            flag_path      = Config.RUNTIME_SCRIPTS_DIR / "flag.txt"
            fragments_path.write_text(texto, encoding="utf-8")
            flag_path.write_text("OK", encoding="utf-8")
            _log.info("Flag 'OK' creado en %s", flag_path)
        else:
            self.controller.pegar_en_quark(
                pagina, indice, texto=texto,
                subfolder=subfolder, excluir_fotos=excluir_fotos
            )
            # Apertura automática del QXP desde materiales/Pnn/
            try:
                qxp_path = self.controller.file_service.find_qxp_en_materiales(pagina)
                if qxp_path and qxp_path.exists():
                    _log.info("Abriendo Quark con %s", qxp_path)
                    cfg2 = configparser.ConfigParser()
                    cfg2.read(str(Config.CONFIG_FILE), encoding="utf-8")
                    quark_exe = cfg2.get("apps", "quark2018", fallback="").strip()
                    if quark_exe and Path(quark_exe).exists():
                        subprocess.Popen([quark_exe, str(qxp_path)], shell=False)
                    else:
                        _log.error("No se encontró el ejecutable de Quark 2018: %s", quark_exe)
                else:
                    _log.warning("No se encontró el QXP en materiales para P%02d.", pagina)
            except Exception as e:
                _log.error("No se pudo abrir el QXP en Quark: %s", e)

        # Marcar como pegado (actualiza hashes y timestamp)
        if version_quark != "Quark 8":
            self.controller.marcar_pegadas(pagina, subfolder, texto)
            # Recargar estado en memoria
            self._fotos_estado = self.controller.cargar_estado_fotos_pagina(pagina, subfolder)

        self.showMinimized()
        self.mostrar_fragmentos(pagina)




    def on_abrir_quark(self):
        if not getattr(self, "base_activa", False) or self.pagina_activa is None:
            return

        # 1) Resolver el archivo asociado
        path = self.controller.archivo_asociado_a_estado(self.pagina_activa)

        # 2) Forzar QXP: si no es QXP o no existe, buscar explícitamente QXP en Final/Base
        if not (path and path.exists() and path.suffix.lower() == ".qxp"):
            n = self.pagina_activa
            path = (self.controller.file_service.find_qxp_final(n)
                    or self.controller.file_service.find_qxp_base(n))

        if not (path and path.exists() and path.suffix.lower() == ".qxp"):
            QMessageBox.information(self, "Abrir Quark", "No encontré un QXP para esta página.")
            return

        # 3) Leer configuración de Quark seleccionado (igual que doble clic)
        config = configparser.ConfigParser()
        config.read(str(Config.CONFIG_FILE), encoding="utf-8")

        quark_sel = config.get("quark", "quark_seleccionado", fallback="Quark 8").strip().lower()
        if "quark 8" in quark_sel:
            quark_exe = config.get("apps", "quark8", fallback=None)
        else:
            quark_exe = config.get("apps", "quark2018", fallback=None)

        if not quark_exe or not Path(quark_exe).exists():
            QMessageBox.warning(
                self,
                "Error",
                f"No se encontró la ruta al ejecutable de {quark_sel}.\nVerificá la sección [apps] en config.ini."
            )
            return

        # 4) Abrir QXP con el mismo criterio que doble clic
        try:
            if "quark 8" in quark_sel:
                os.startfile(str(path))
            else:
                subprocess.Popen([quark_exe, str(path)])
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error al abrir Quark",
                f"No se pudo abrir {path}:\n{e}"
            )
            return

        QTimer.singleShot(1200, self._maximizar_quark)


        
    def _load_images_for_page(self, n: int):
        """Carga imágenes y detecta subcarpetas de noticias para la página."""
        self.visor_panel.set_pagina(n)
        # --- Detectar subcarpetas de noticias ---
        self._noticias = self.controller.file_service.get_noticia_dirs(n)
        self._noticia_index = 0
        if not self._noticias:
            self.btn_prev_noticia.setEnabled(False)
            self.btn_next_noticia.setEnabled(False)
            # Fallback: estructura vieja sin subcarpetas
            imgs = self._gather_images_for_page_via_visor(n)
            foto_activa = self.controller.foto_tapa_pagina_origen() == n
            self.visor_panel.cargar_imagenes(imgs, foto_tapa_activa=foto_activa)
            self.visor_panel.set_epigrafes({})
            self.label_noticia_titulo.setVisible(False)
            self.label_noticia_titulo.setText("")
            # Cargar estado de fotos seleccionadas (sin subfolder)
            self._cargar_fotos_estado()
            self._refrescar_panel_fotos()
            self._refrescar_visor_seleccion()
            return

        # Si hay subcarpetas, cargar la primera
        self._load_noticia_actual()



    def resizeEvent(self, event):
        """
        ResizeEvent unificado para toda la ventana principal.
        Maneja:
        - Reescalado del visor de imágenes
        - Reacomodo de la grilla de páginas
        - Reposicionamiento de overlays/spinner
        """
        super().resizeEvent(event)

        # 1) Reacomodar la grilla de botones de página
        try:
            QTimer.singleShot(50, self._crear_botones_grilla)
        except Exception:
            pass

        # 2) Reescalar imagen del visor (si hay una imagen activa)
        try:
            if hasattr(self, "visor_panel"):
                self.visor_panel.reescalar()
        except Exception:
            pass

        # 3) Reposicionar spinner del pool (si está presente)
        try:
            # Reposicionar el spinner si está visible
            if hasattr(self, "pool_spinner") and self.pool_spinner.isVisible():
                self._posicionar_pool_spinner()
        except Exception:
            pass

        # 4) Reposicionar el panel de enroque (overlay inferior)
        try:
            self._reposicionar_enroque_panel()
        except Exception:
            pass



    # =========================================================
    # 🔹 Navegación entre noticias de una misma página (02a, 02b...)
    # =========================================================
    def _nav_prev_noticia(self):
        if self._noticia_index > 0:
            self._noticia_index -= 1
            self._load_noticia_actual()

            # === replicar clic en página ===
            numero = self.pagina_activa
            self.mostrar_fragmentos(numero)

            # seleccionar el título si existe
            if self.lista_fragmentos.count() > 1:
                self.lista_fragmentos.setCurrentRow(1)  # título
            elif self.lista_fragmentos.count() == 1:
                self.lista_fragmentos.setCurrentRow(0)


    def _nav_next_noticia(self):
        if self._noticia_index < len(self._noticias) - 1:
            self._noticia_index += 1
            self._load_noticia_actual()

            # === replicar clic en página ===
            numero = self.pagina_activa
            self.mostrar_fragmentos(numero)

            # seleccionar el título si existe
            if self.lista_fragmentos.count() > 1:
                self.lista_fragmentos.setCurrentRow(1)  # título
            elif self.lista_fragmentos.count() == 1:
                self.lista_fragmentos.setCurrentRow(0)

            

    def _load_noticia_actual(self):
        """Carga el texto e imágenes correspondientes a la noticia seleccionada."""
        if not self._noticias or self.pagina_activa is None:
            return

        noticia_dir = self._noticias[self._noticia_index]
        txt_path = noticia_dir / f"{noticia_dir.name}.txt"

        # --- Cargar texto ---
        self.texto_noticia.clear()
        if txt_path.exists():
            try:
                self.texto_noticia.setPlainText(txt_path.read_text(encoding="utf-8"))
            except Exception:
                self.texto_noticia.setPlainText(txt_path.read_text(encoding="utf-8-sig"))
        else:
            self.texto_noticia.setPlainText("(Sin texto)")

        # --- Imágenes de la noticia ---
        try:
            it = noticia_dir.iterdir()
        except (PermissionError, FileNotFoundError) as e:
            # No romper la UI si un subdirectorio quedó inaccesible en red (Z: / UNC)
            _log.error(f"[WARN] No pude listar noticia_dir: {noticia_dir} -> {type(e).__name__}: {e}")
            it = []

        imgs_noticia = []
        for p in it:
            try:
                if p.is_file() and p.suffix.lower() in IMG_EXTS:
                    imgs_noticia.append(p)
            except (PermissionError, FileNotFoundError):
                # En shares puede fallar al consultar metadata de un entry individual
                continue

        n = self.pagina_activa

        # Fotos marcadas como principal en el editor (fotos_seleccionadas.json)
        _principal_editor: set[str] = set()
        try:
            _sel_path = noticia_dir / "fotos_seleccionadas.json"
            if _sel_path.exists():
                import json as _json
                for entry in _json.loads(_sel_path.read_text(encoding="utf-8")):
                    if (entry.get("rol") or "") == "principal":
                        _principal_editor.add(Path(entry["path"]).name.lower())
        except Exception:
            pass

        def ordenar(p):
            import re as _re
            name = p.name.lower()
            if name in _principal_editor:                                return (0, 0, name)
            if _re.match(r"^principal", name):                           return (1, 0, name)
            if _re.search(rf"para[\s_-]*la[\s_-]*0*{n}\b", name):       return (2, 0, name)
            m = _re.match(rf"^extra(\d*)[_\s-]*{n:02d}\.", name)
            if m: return (3, int(m.group(1) or 0), name)
            return (4, 0, name)

        # En Maquetación incluimos avisos raíz + imágenes de noticia
        if self.controller.perfil == "Maquetación y avisos":
            imgs_raiz = self.controller.file_service.list_material_images_for_page(self.pagina_activa)

            # fusionar sin duplicados
            nombres = set()
            fusion = []
            for p in imgs_raiz + imgs_noticia:
                if p.name.lower() not in nombres:
                    nombres.add(p.name.lower())
                    fusion.append(p)

            # aplicar mismo orden que gather_images_for_page
            _imgs = sorted(fusion, key=ordenar)

        else:
            # Noticia normal: solo imágenes de la subcarpeta
            _imgs = sorted(imgs_noticia, key=ordenar)


        # --- Inicializar visor ---
        foto_activa = self.controller.foto_tapa_pagina_origen() == self.pagina_activa
        self.visor_panel.cargar_imagenes(_imgs, foto_tapa_activa=foto_activa)
        self._cargar_epigrafes_visor(noticia_dir)

        # Cargar estado de fotos seleccionadas para esta noticia/subfolder
        self._cargar_fotos_estado()
        self._refrescar_panel_fotos()
        self._refrescar_visor_seleccion()

        # --- Actualizar estado de los botones ---
        self.btn_prev_noticia.setEnabled(self._noticia_index > 0)
        self.btn_next_noticia.setEnabled(self._noticia_index < len(self._noticias) - 1)

        # --- Mostrar label de noticia con len (calculado del disco) ---
        sufijo = noticia_dir.name[-1].upper()
        try:
            txt_path = noticia_dir / f"{noticia_dir.name}.txt"
            n = self.controller.file_service.nota_len(txt_path) if txt_path.exists() else 0
            txt_len_str = str(n) if n else ""
        except Exception:
            txt_len_str = ""

        self.label_noticia_titulo.setVisible(True)
        if txt_len_str:
            # Formato en dos líneas
            self.label_noticia_titulo.setText(f"Noticia {sufijo}\n({txt_len_str})")
        else:
            self.label_noticia_titulo.setText(f"Noticia {sufijo}")

        # --- Efecto visual ---
        self.label_noticia_titulo.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: orange;"
        )
        QTimer.singleShot(800, lambda: self.label_noticia_titulo.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #ccc;"
        ))




    def on_agregar_nota(self):
        """Agrega una nueva noticia (02b, 02c...) a la página activa."""
        if not getattr(self, "base_activa", False) or self.pagina_activa is None:
            return

        numero = self.pagina_activa
        link, ok = QInputDialog.getText(self, "Agregar nota", "Pegá el link de la nota adicional:")
        if not ok or not link.strip():
            return

        # 🔸 Desactivar temporalmente el botón "+"
        self.boton_agregar_nota.setEnabled(False)
        self.boton_agregar_nota.setText("⏳")
        self.statusBar().showMessage(f"P{numero:02d}: Agregando nueva nota…", 4000)

        try:
            self.controller.enqueue_scrape(numero, link.strip())
            self.statusBar().showMessage(f"P{numero:02d}: Agregada nota adicional…", 3000)
            # el refresco de estado ocurrirá desde on_poll()
        except Exception as e:
            QMessageBox.critical(self, "Agregar nota", str(e))
            # Si hubo error, reactivamos el botón
            self.boton_agregar_nota.setEnabled(True)



    def on_quitar(self):
        if not getattr(self, "base_activa", False) or self.pagina_activa is None:
            return

        numero = self.pagina_activa
        etiqueta = self.boton_quitar.text().strip().lower()

        if "cargar link" in etiqueta:
            link, ok = QInputDialog.getText(self, "Cargar link", "Pegá el link de la nota:")
            if not ok or not link.strip():
                return
             # 🔸 Estado UI intermedio (igual que Agregar nota)
            self.boton_quitar.setEnabled(False)
            self.boton_quitar.setText("⏳")
            self.statusBar().showMessage(f"P{numero:02d}: Cargando link…", 4000)

            try:
                self.controller.enqueue_scrape(numero, link.strip())
                self.statusBar().showMessage(f"P{numero:02d}: link cargado…", 3000)
                # El refresco real vendrá luego, cuando exista TXT
            except Exception as e:
                QMessageBox.critical(self, "Cargar link", str(e))
                # fallback inmediato
                self.boton_quitar.setEnabled(True)

        if "asignar" in etiqueta:
            try:
                pagina = self.controller.gestor_paginas.obtener_pagina(numero)
                entry = self.controller.file_service.read_page_entry(pagina.numero)
                tiene_aviso = entry.get("aviso_full", False)
                txt_path = self.controller.file_service.obtener_txt(numero)
                pagina = self.controller.gestor_paginas.obtener_pagina(numero)
                # --- CASO 1: página con aviso full ---
                if tiene_aviso:
                    self.controller.file_service.mark_assigned(
                        numero,
                        txt_name="",
                        by=(self.controller.usuario or "desconocido"),
                        apagar_aviso_full=False
                    )
                    pag = self.controller.gestor_paginas.obtener_pagina(numero)
                    if pag:
                        pag.asignada_por_ini = True

                    self._despues_de_cambio_estado(numero)
                    self.colorear_paginas()
                    self.actualizar_info_pagina(pag)
                    return

                # --- CASO 2: página SIN aviso full → exige TXT ---
                if txt_path is None or not txt_path.exists():
                    QMessageBox.warning(
                        self,
                        "Asignar",
                        "No hay TXT en materiales para asignar."
                    )
                    return

                # --- Asignación normal con texto ---
                self.controller.file_service.mark_assigned(
                    numero,
                    txt_path.name,
                    by=(self.controller.usuario or "desconocido")
                )

                pag = self.controller.gestor_paginas.obtener_pagina(numero)
                if pag:
                    pag.asignada_por_ini = True

                self._despues_de_cambio_estado(numero)
                self.colorear_paginas()
                self.actualizar_info_pagina(pag)

            except Exception as e:
                QMessageBox.critical(self, "Asignar", str(e))
            return

        if "quitar asignación" in etiqueta:

            # ----------------------------------------
            # 1) Detectar nombre real del QXP (sin tocar disco)
            # ----------------------------------------
            qxp_real = None
            try:
                # Buscar en materiales/Pnn/ primero (migración JSON 2026-05-06)
                qxp_real = self.controller.file_service.find_qxp_en_materiales(numero)
                if not qxp_real:
                    rutas = self.controller.file_service.rutas or {}
                    en_proc_dir = Path(rutas.get("personal_folder") or "")
                    if en_proc_dir.exists():
                        qxp_real = self.controller.file_service.buscar_qxp_por_numero(en_proc_dir, numero)
            except Exception as e:
                _log.warning(f"[WARN] Error al detectar QXP de P{numero:02d}: {e}")

            # ----------------------------------------
            # 1b) Guard: no quitar asignación si el QXP está abierto en Quark.
            #     (Si se borrara con el archivo abierto, el sistema creería que
            #      no hay QXP y al re-asignar generaría Pnn (2).qxp.)
            # ----------------------------------------
            if qxp_real and qxp_real.exists():
                try:
                    bloqueado = self.controller.file_service._archivo_bloqueado(qxp_real)
                except Exception:
                    bloqueado = False
                if bloqueado:
                    QMessageBox.warning(
                        self,
                        "Archivo de Quark abierto",
                        f"El archivo de Quark está abierto:\n\n{qxp_real.name}\n\n"
                        "Cerralo en QuarkXPress antes de quitar la asignación."
                    )
                    return

            # ----------------------------------------
            # 2) Armar mensaje según si existe QXP
            # ----------------------------------------
            if qxp_real and qxp_real.exists():
                msg = (
                    "Se eliminará el archivo de Quark:\n\n"
                    f"{qxp_real.name}\n\n"
                    "¿Deseás continuar?"
                )
                borrar_qxp = True
            else:
                msg = "¿Seguro que querés quitar la asignación? (El TXT queda en materiales)"
                borrar_qxp = False

            resp = QMessageBox.question(
                self,
                "Quitar asignación",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if resp != QMessageBox.Yes:
                return

            # ----------------------------------------
            # 3) Ejecutar operación delegada TOTALMENTE en FileService
            # ----------------------------------------
            try:
                self.controller.quitar_asignacion(numero, borrar_qxp=borrar_qxp)
                self._despues_de_cambio_estado(numero)
                self.colorear_paginas()
            except Exception as e:
                QMessageBox.critical(self, "Quitar asignación", str(e))
            return



    def on_mover(self):
        if not getattr(self, "base_activa", False):
            return
        pag = self.controller.gestor_paginas.get_activa()
        if not pag:
            return

        src = getattr(self.boton_mover, "_src", None)
        dest = getattr(self.boton_mover, "_dest", None)

        if src and dest:
            result = self.controller.ejecutar_mover(src, dest)

            if result == "locked":
                QMessageBox.warning(
                    self,
                    "Archivo en uso",
                    "No puedo mover la página porque el archivo está abierto en otra estación.\n"
                    "Cerralo y volvé a intentar."
                )
                return

            if result is False:
                QMessageBox.critical(
                    self,
                    "Error al mover",
                    "No se pudo mover el archivo.\nRevisá permisos o conexión de red."
                )
                return

            # Caso OK
            self.colorear_paginas()
            self.actualizar_botonera_mover_devolver()
            self.on_poll()


    def on_devolver(self):
        if not getattr(self, "base_activa", False):
            return
        pag = self.controller.gestor_paginas.get_activa()
        if not pag:
            return

        src = getattr(self.boton_devolver, "_src", None)
        dest = getattr(self.boton_devolver, "_dest", None)

        if src and dest:
            result = self.controller.ejecutar_devolver(src, dest)

            if result == "locked":
                QMessageBox.warning(
                    self,
                    "Archivo en uso",
                    "No puedo devolver la página porque el archivo está abierto en otra estación.\n"
                    "Cerralo y volvé a intentar."
                )
                return

            if result is False:
                QMessageBox.critical(
                    self,
                    "Error al devolver",
                    "No se pudo devolver el archivo.\nRevisá permisos o conexión de red."
                )
                return

            # OK
            self.colorear_paginas()
            self.actualizar_botonera_mover_devolver()
            self.on_poll()




    def _fmt_ts(self, ts_str: str) -> str:
        if not ts_str:
            return ""
        try:
            dt = datetime.fromisoformat(ts_str.strip())
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return ts_str

    def _update_label_asignacion(self, pagina_n: int) -> None:
        entry = None
        try:
            entry = self.controller.file_service.read_page_entry(pagina_n)
        except Exception:
            entry = None

        line1 = ""
        if entry and entry.get("assigned"):
            by = (entry.get("by") or "desconocido").strip()
            ts = self._fmt_ts(entry.get("ts") or "")
            line1 = f"Asignada por {by} el {ts}" if ts else f"Asignada por {by}"

        estado_txt = ""
        try:
            pag = self.controller.gestor_paginas.obtener_pagina(pagina_n)
        except Exception:
            pag = None

        if pag:
            if pag.impreso:
                estado_txt = "en OK"
            elif pag.revisado:
                estado_txt = "en PDF"
            elif pag.apdf:
                estado_txt = "en apdf"
            elif pag.corregido:
                estado_txt = "en mandar"
            elif pag.fotocromia:
                estado_txt = "en final"
            elif pag.armado:
                estado_txt = "en base"
            else:
                try:
                    rutas = self.controller.file_service.rutas or {}
                    personal = Path(rutas.get("personal_folder") or "")
                    if personal.exists() and self.controller.file_service.buscar_qxp_por_numero(personal, pagina_n):
                        estado_txt = "en proceso"
                except Exception:
                    pass

        # --- Links por noticia (título + url) para el ícono "Link" ---
        links = []   # list of (etiqueta, url)
        try:
            for nota in self.controller.file_service.get_notas(pagina_n):
                jp = nota.get("json_path")
                if not jp:
                    continue
                try:
                    nd = json.loads(jp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                url = (nd.get("link") or "").strip()
                if not url:
                    continue
                suf = (nota.get("sufijo") or "").upper()
                titulo = (nd.get("titulo") or "").strip() or f"Noticia {suf}"
                links.append((f"Noticia {suf}: {titulo}", url))
        except Exception:
            pass

        # --- Actualizar la fila de íconos (Estado / Link / Información) ---
        self._info_links = links
        self._info_by = (entry.get("by") if entry else "") or ""
        self._info_ts = (entry.get("ts") if entry else "") or ""

        self.info_estado.set_valor(estado_txt or "—")

        self.info_link.set_enabled(bool(links))

        # Información: último usuario + hora (la concatenación histórica se parsea al click)
        ult_by = self._info_by.split(";")[-1].strip() if self._info_by else ""
        ult_ts = self._info_ts.split(";")[-1].strip() if self._info_ts else ""
        info_val = ""
        if ult_by:
            fts = self._fmt_ts(ult_ts) if ult_ts else ""
            info_val = f"{ult_by}\n{fts}" if fts else ult_by
        self.info_usuario.set_valor(info_val or "—")
        self.info_usuario.set_enabled(bool(ult_by))

    def _on_info_link_clicked(self):
        links = getattr(self, "_info_links", []) or []
        if not links:
            return
        if len(links) == 1:
            QDesktopServices.openUrl(QUrl(links[0][1]))
            return
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)
        for etiqueta, url in links:
            act = QAction(etiqueta, self)
            act.triggered.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            m.addAction(act)
        m.exec_(self.info_link.mapToGlobal(QPoint(self.info_link.width() // 2,
                                                  self.info_link.height())))

    def _on_info_usuario_clicked(self):
        bys = [b.strip() for b in (getattr(self, "_info_by", "") or "").split(";") if b.strip()]
        tss = [t.strip() for t in (getattr(self, "_info_ts", "") or "").split(";")]
        if not bys:
            return
        m = QMenu(self); m.setStyleSheet(_AJUSTES_MENU_QSS)
        titulo = QAction("Usuarios que trabajaron la página:", self)
        titulo.setEnabled(False)
        m.addAction(titulo)
        m.addSeparator()
        for i, b in enumerate(bys):
            ts = tss[i] if i < len(tss) else ""
            fts = self._fmt_ts(ts) if ts else ""
            act = QAction(f"{b}   {fts}".strip(), self)
            act.setEnabled(False)
            m.addAction(act)
        m.exec_(self.info_usuario.mapToGlobal(QPoint(self.info_usuario.width() // 2,
                                                     self.info_usuario.height())))

    ### === Atajos del teclado === ###
    def _setup_shortcuts(self):
        """
        Registra todos los atajos de teclado usando ShortcutManager.
        Cada acción obtiene su QShortcut con la combinación actual desde config.ini.
        """
        # Primero limpiamos posibles instancias previas
        for sc in getattr(self, "_shortcuts", []):
            sc.setParent(None)
        self._shortcuts = []

        def make_shortcut(action_key, callback):
            seq = self.shortcut_mgr.get(action_key)
            if not seq:
                return
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

        # === ACCIONES DISPONIBLES ===
        make_shortcut("open_pdf", self._accion_abrir_asociado_actual)
        make_shortcut("move_page", self.on_mover)
        make_shortcut("return_page", self.on_devolver)
        make_shortcut("refresh", self.on_actualizar_paginas)
        make_shortcut("create_base", self.on_crear_base)
        make_shortcut("paste_quark", self.on_pegar)
        make_shortcut("open_image", self.on_abrir_imagen)
        make_shortcut("open_mono", self.abrir_dialogo_mono)
        make_shortcut("open_aviso", self.on_cargar_avisos_excel)
        #make_shortcut("open_qr", self.on_abrir_qr)
        make_shortcut("borrar_archivo", lambda: self._accion_descartar_pdf)

        # Si más adelante agregás atajos nuevos, solo extendés este bloque

    def reload_shortcuts(self):
        """Permite recargar los atajos después de editarlos en el diálogo de configuración."""
        self.shortcut_mgr = ShortcutManager()
        self._setup_shortcuts()

    def _accion_abrir_asociado_actual(self):
        """Abre el archivo asociado a la página activa."""
        if not self.pagina_activa:
            return
        self._accion_abrir_asociado(self.pagina_activa)

    def abrir_configuracion_atajos(self):
        """Abre el cuadro de configuración de atajos y recarga al guardar."""
        dlg = ShortcutConfigDialog(self)
        dlg.shortcuts_changed.connect(self.reload_shortcuts)
        dlg.exec_()

    def _abrir_config_secciones(self):
        dlg = SeccionesConfigDialog(self)
        if hasattr(self, '_chrome_watcher') and self._chrome_watcher:
            dlg.secciones_guardadas.connect(self._chrome_watcher.reload_secciones)
        dlg.exec_()

    def _cargar_avisos_reales_despues_de_pintado(self):
        """
        Tras renderizar la grilla, carga los avisos reales en un HILO dedicado
        (GhostScript/fitz a PNG de caché, sin congelar la UI) y, al terminar,
        crea los QPixmap en el hilo GUI y repinta las mini-maquetas. Funciona en
        ambos perfiles (Armado y Maquetación).
        """
        if self._avisos_real_cargando:
            return  # evita reentrancia

        # --- Construir tareas (I/O liviano en el hilo GUI): solo páginas cuyo aviso cambió ---
        tareas = []
        for i, boton in self.boton_paginas.items():
            pagina = boton.pagina
            if not pagina:
                continue
            if not (getattr(pagina, "aviso_nombre", "") or "").strip():
                continue
            try:
                match = self.controller.file_service.find_aviso_image_for_page(i)
                if not match:
                    continue
                path = Path(match)
                mtime = path.stat().st_mtime
                old_path = getattr(pagina, "aviso_path", None)
                old_mtime = getattr(pagina, "aviso_mtime", None)
                pagina.aviso_path = match
                if match != old_path or not old_mtime or mtime != old_mtime or \
                        getattr(pagina, "aviso_pixmap", None) is None:
                    tareas.append((i, str(path), mtime))
            except Exception as e:
                _log.warning(f"[WARN] aviso P{i:02d}: {e}")

        if not tareas:
            return

        self._avisos_real_cargando = True

        # --- Diálogo modal "Cargando aviso, por favor espere" (sin botones) ---
        from PyQt5.QtWidgets import QProgressDialog
        dlg = QProgressDialog("Cargando aviso, por favor espere…", "", 0, 0, self)
        dlg.setWindowTitle("Avisos")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.show()
        self._aviso_dlg = dlg

        th = QThread(self)
        wk = AvisoCacheWorker(tareas)
        wk.moveToThread(th)
        th.started.connect(wk.run)
        wk.done.connect(self._on_avisos_cache_listo)
        wk.finished.connect(th.quit)
        wk.finished.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)
        self._aviso_thread = th
        self._aviso_worker = wk
        th.start()

    def _on_avisos_cache_listo(self, resultados: dict):
        """Hilo GUI: crea los QPixmap desde los PNG cacheados y repinta los botones."""
        try:
            for numero, (png_path, mtime) in resultados.items():
                pagina = self.controller.gestor_paginas.obtener_pagina(numero)
                if not pagina:
                    continue
                pm = QPixmap(png_path)
                if pm and not pm.isNull():
                    pagina.aviso_pixmap = pm
                    pagina.aviso_mtime = mtime
                else:
                    pagina.aviso_pixmap = None
                boton = self.boton_paginas.get(numero)
                if boton:
                    boton.update()
            _log.info("[OK] Avisos reales cargados (%d).", len(resultados))
        except Exception as e:
            _log.error(f"[ERROR] _on_avisos_cache_listo: {e}")
        finally:
            self._avisos_real_cargando = False
            dlg = getattr(self, "_aviso_dlg", None)
            if dlg is not None:
                dlg.close()
                self._aviso_dlg = None


    def _activate_qr_mode(self):
        """Activa overlay y comienza a vigilar los procesos PDF."""
        self.qr_overlay = start_overlay()
        if self.qr_overlay:
            self.qr_overlay.qr_detected.connect(self._on_qr_detected)
            self.qr_overlay.overlay_closed.connect(self._on_overlay_closed)
        self._pdf_processes = self._detect_pdf_processes()
        self._pdf_watcher = QTimer(self)
        self._pdf_watcher.timeout.connect(self._check_pdf_processes)
        self._pdf_watcher.start(3000)
        _log.info("[QR] Overlay activado por PDF.")


    def _maximizar_quark(self):
        """
        Maximiza y trae al frente la ventana de QuarkXPress.
        Busca por prefijo de título o clase de ventana.
        """
        import ctypes
        import ctypes.wintypes as wintypes

        user32 = ctypes.windll.user32
        SW_MAXIMIZE = 3

        TITLE_PREFIX = "QuarkXPress (R)"
        CLASS_NAMES = {"QXMainWinClass", "QXMainWindow"}

        found_hwnd = []

        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(hwnd, lParam):
            # Solo ventanas visibles
            if not user32.IsWindowVisible(hwnd):
                return True

            # Título
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value or ""
                if title.startswith(TITLE_PREFIX):
                    found_hwnd.append(hwnd)
                    return False  # cortar enumeración

            # Clase
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            cls = class_buff.value or ""
            if cls in CLASS_NAMES:
                found_hwnd.append(hwnd)
                return False

            return True

        user32.EnumWindows(EnumWindowsProc(enum_cb), 0)

        if not found_hwnd:
            _log.warning("[WARN] No se encontró la ventana de QuarkXPress.")
            return

        hwnd = found_hwnd[0]
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)

        _log.info("[OK] Quark maximizado y enfocado correctamente.")


    def seleccionar_quark(self, version: str):
        """Guarda en config.ini la versión de Quark seleccionada y actualiza el tilde."""
        cfg = configparser.ConfigParser()
        cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")

        if not cfg.has_section("quark"):
            cfg.add_section("quark")

        cfg.set("quark", "quark_seleccionado", version)

        with open(Config.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
        _log.info(f"[OK] Quark seleccionado: {version}")

        




    