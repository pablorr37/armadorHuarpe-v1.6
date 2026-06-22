# ui/visor_img.py
"""
Módulo de visores de imágenes para ArmadorHuarpe.

Contiene dos widgets:

VisorImagenes
    Visor navegable para el pool de noticias (PoolEditorDialog).
    Compacto, con epígrafe editable y botón estrella (foto de tapa).

VisorPanelWidget
    Visor del panel izquierdo principal (MainWindow).
    Muestra la imagen de la noticia activa, permite renombrar (doble click),
    borrar (menú contextual) y marcar como foto de tapa (botón estrella).
    Emite señales para que MainWindow coordine con el controller.
"""

from __future__ import annotations

import configparser
import re
import subprocess
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from config.config import Config
from utils.app_logger import get_logger
from utils.resources import resource_path
from ui.widgets.circle_icon_button import CircleIconButton

_log = get_logger(__name__)

# Extensiones de imagen reconocidas (igual que file_service.IMG_EXTS)
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


# ═══════════════════════════════════════════════════════════════════════════════
# VisorImagenes — visor del pool (PoolEditorDialog)
# ═══════════════════════════════════════════════════════════════════════════════

class VisorImagenes(QWidget):
    """
    Widget navegable de imágenes con epígrafe editable.
    Pensado para embeberlo dentro de PoolEditorDialog.

    Señales:
        epigrafe_changed(fname, texto) — epígrafe editado.
    """

    epigrafe_changed = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._imagenes_paths:    list[Path]      = []
        self._imagenes_epigrafes: dict[str, str] = {}
        self._img_index:  int  = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.lbl_img = QLabel("No hay imágenes")
        self.lbl_img.setAlignment(Qt.AlignCenter)
        self.lbl_img.setMinimumHeight(180)
        layout.addWidget(self.lbl_img)

        self.ed_epigrafe = QTextEdit()
        self.ed_epigrafe.setFixedHeight(60)
        self.ed_epigrafe.setPlaceholderText("Epígrafe de la imagen…")
        self.ed_epigrafe.textChanged.connect(self._on_epigrafe_changed)
        layout.addWidget(self.ed_epigrafe)

        nav = QHBoxLayout()
        nav.setSpacing(6)

        self.btn_prev = QPushButton("<< Anterior")
        self.btn_prev.setFixedHeight(28)
        self.btn_prev.clicked.connect(self._img_prev)

        self.btn_next = QPushButton("Siguiente >>")
        self.btn_next.setFixedHeight(28)
        self.btn_next.clicked.connect(self._img_next)

        nav.addWidget(self.btn_prev)
        nav.addStretch()
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        self.lbl_contador = QLabel("")
        self.lbl_contador.setAlignment(Qt.AlignCenter)
        self.lbl_contador.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.lbl_contador)

    # ── API pública ──────────────────────────────────────────────────────────

    def cargar(
        self,
        imagenes_paths: list[Path],
        epigrafes: dict[str, str],
        foto_tapa_activa: bool = False,   # ignorado; mantenido por compatibilidad
    ) -> None:
        self._imagenes_paths     = list(imagenes_paths)
        self._imagenes_epigrafes = dict(epigrafes)
        self._img_index          = 0
        self._refrescar()

    def epigrafes_actuales(self) -> dict[str, str]:
        self._volcar_epigrafe_actual()
        return dict(self._imagenes_epigrafes)

    def imagen_actual(self) -> Optional[Path]:
        if not self._imagenes_paths:
            return None
        return self._imagenes_paths[self._img_index]

    # ── Slots privados ───────────────────────────────────────────────────────

    def _img_prev(self) -> None:
        if not self._imagenes_paths:
            return
        self._volcar_epigrafe_actual()
        self._img_index = max(0, self._img_index - 1)
        self._refrescar()

    def _img_next(self) -> None:
        if not self._imagenes_paths:
            return
        self._volcar_epigrafe_actual()
        self._img_index = min(len(self._imagenes_paths) - 1, self._img_index + 1)
        self._refrescar()

    def _on_epigrafe_changed(self) -> None:
        if not self._imagenes_paths:
            return
        img   = self._imagenes_paths[self._img_index]
        texto = self.ed_epigrafe.toPlainText()
        self._imagenes_epigrafes[img.name] = texto
        self.epigrafe_changed.emit(img.name, texto)

    # ── Helpers privados ─────────────────────────────────────────────────────

    def _refrescar(self) -> None:
        if not self._imagenes_paths:
            self.lbl_img.setText("No hay imágenes")
            self.lbl_img.setPixmap(QPixmap())
            self.ed_epigrafe.blockSignals(True)
            self.ed_epigrafe.setText("")
            self.ed_epigrafe.blockSignals(False)
            self.lbl_contador.setText("")
            return

        total    = len(self._imagenes_paths)
        img_path = self._imagenes_paths[self._img_index]

        pix = QPixmap(str(img_path))
        if not pix.isNull():
            self.lbl_img.setPixmap(pix.scaledToWidth(580, Qt.SmoothTransformation))
        else:
            self.lbl_img.setText(f"No se pudo cargar {img_path.name}")

        self.ed_epigrafe.blockSignals(True)
        self.ed_epigrafe.setText(self._imagenes_epigrafes.get(img_path.name, ""))
        self.ed_epigrafe.blockSignals(False)

        self.lbl_contador.setText(
            f"{self._img_index + 1} / {total}  —  {img_path.name}"
        )
        self.btn_prev.setEnabled(self._img_index > 0)
        self.btn_next.setEnabled(self._img_index < total - 1)

    def _volcar_epigrafe_actual(self) -> None:
        if not self._imagenes_paths:
            return
        img = self._imagenes_paths[self._img_index]
        self._imagenes_epigrafes[img.name] = self.ed_epigrafe.toPlainText()


# ═══════════════════════════════════════════════════════════════════════════════
# VisorPanelWidget — visor del panel izquierdo principal (MainWindow)
# ═══════════════════════════════════════════════════════════════════════════════

class VisorPanelWidget(QWidget):
    """
    Visor compacto de imágenes para el panel izquierdo de MainWindow.

    Muestra la imagen de la noticia activa con navegación, renombrado
    (doble click), borrado (menú contextual) y marcado de foto de tapa (★).

    La lógica de negocio (renombrar en disco, copiar a P01, etc.) se delega
    al controller a través de señales, manteniendo el widget desacoplado.

    Señales:
        foto_tapa_marcar(Path)   — pedir copia a P01.
        foto_tapa_desmarcar()    — pedir borrado en P01.
        imagen_eliminada(Path)   — imagen borrada del disco.
        imagen_renombrada(Path, str) — (src, nuevo_stem) para que el controller renombre.
        abrir_en_editor_solicitado(Path) — abrir imagen en Photoshop/editor externo.
    """

    foto_tapa_marcar           = pyqtSignal(Path)
    foto_tapa_desmarcar        = pyqtSignal()
    imagen_eliminada           = pyqtSignal(Path)
    imagen_renombrada          = pyqtSignal(Path, str)
    abrir_en_editor_solicitado = pyqtSignal(Path)
    qr_link_solicitado         = pyqtSignal(str)   # #11: pedir generar un QR desde un link

    # Señales para selección de fotos de página
    foto_seleccionar   = pyqtSignal(Path)   # pedir agregar imagen a la lista de la página
    foto_deseleccionar = pyqtSignal(Path)   # pedir quitar imagen de la lista

    # Señal para aplicar epígrafe del scraper al campo de la nota
    usar_epigrafe = pyqtSignal(str)

    # Señal emitida al navegar a otra imagen (para que MainWindow actualice el pin)
    imagen_navegada = pyqtSignal(Path)

    _STYLE_BTN = """
        QPushButton {
            background-color: #1e293b; color: #e2e8f0;
            border-radius: 6px; padding: 6px 12px;
        }
        QPushButton:hover  { background-color: #334155; }
        QPushButton:pressed { background-color: #475569; }
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._images:       list[Path] = []
        self._image_index:  int        = -1
        self._foto_tapa_activa: bool   = False
        self._pagina_activa: Optional[int] = None
        self._foto_seleccionada: bool       = False   # imagen activa en la lista de fotos
        self._foto_orden:  Optional[int]    = None    # orden 0-based en la lista
        self._imagenes_epigrafes: dict[str, str] = {}

        # ── Layout ──────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Scroll de imagen
        self.img_scroll = QScrollArea()
        self.img_scroll.setWidgetResizable(True)
        self.img_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.img_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.img_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img_scroll.setMaximumHeight(160)

        self.image_label = QLabel("Sin imagen")
        self.image_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.image_label.customContextMenuRequested.connect(self._on_context_menu)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet(
            "background:#111; color:#aaa; border:1px solid #333;"
        )
        self.image_label.setMinimumHeight(150)
        self.image_label.mouseDoubleClickEvent = self._on_double_click
        self.img_scroll.setWidget(self.image_label)
        layout.addWidget(self.img_scroll, stretch=2)

        # Fila 1: botones de navegación (ocupan todo el ancho)
        nav = QHBoxLayout()
        nav.setSpacing(4)

        self.btn_prev = QPushButton("<")
        self.btn_next = QPushButton(">")
        for b in (self.btn_prev, self.btn_next):
            b.setEnabled(False)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.btn_prev.clicked.connect(self._nav_prev)
        self.btn_next.clicked.connect(self._nav_next)

        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        # Fila 2: íconos circulares centrados debajo de los botones de navegación
        self.btn_seleccionar = CircleIconButton(
            QPixmap(resource_path("ui/assets/pin.png")), "Marcar principal")
        self.btn_seleccionar.clicked.connect(self._on_seleccionar_clicked)

        self.btn_foto_tapa = CircleIconButton(
            QPixmap(resource_path("ui/assets/favorito.png")), "Marcar foto tapa")
        self.btn_foto_tapa.clicked.connect(self._on_foto_tapa_clicked)

        self.btn_editar_foto = CircleIconButton(
            QPixmap(resource_path("ui/assets/color.png")), "Editar foto")
        self.btn_editar_foto.clicked.connect(self._on_editar_foto_clicked)

        self.btn_qr = CircleIconButton(
            QPixmap(resource_path("ui/assets/qr.png")), "Generar QR")
        self.btn_qr.clicked.connect(self._on_qr_clicked)

        self._aplicar_estilo_estrella(False)
        self._aplicar_estilo_seleccionar(False)

        iconos = QHBoxLayout()
        iconos.setSpacing(8)
        iconos.addStretch()
        iconos.addWidget(self.btn_seleccionar)
        iconos.addWidget(self.btn_foto_tapa)
        iconos.addWidget(self.btn_editar_foto)
        iconos.addWidget(self.btn_qr)
        iconos.addStretch()
        layout.addLayout(iconos)

        # Nombre de la imagen
        self.label_nombre_img = QLabel("")
        self.label_nombre_img.setAlignment(Qt.AlignCenter)
        self.label_nombre_img.setStyleSheet(
            "font-size: 16px; color: #cccaca; font-weight: bold;"
        )
        layout.addWidget(self.label_nombre_img)

        # Epígrafe detectado por scraper
        self._lbl_epigrafe_visor = QLabel("")
        self._lbl_epigrafe_visor.setWordWrap(True)
        self._lbl_epigrafe_visor.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._lbl_epigrafe_visor.setStyleSheet(
            "color: rgba(255,255,255,0.55); font-size: 11px; padding: 2px 4px;"
        )
        layout.addWidget(self._lbl_epigrafe_visor)

        self.btn_usar_epi_visor = QPushButton("Usar este epígrafe")
        self.btn_usar_epi_visor.setCursor(Qt.PointingHandCursor)
        self.btn_usar_epi_visor.setEnabled(False)
        self.btn_usar_epi_visor.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 10px;"
            " background: rgba(230,100,30,0.18); border: 1px solid rgba(230,100,30,0.45);"
            " border-radius: 5px; color: #f59e0b; }"
            " QPushButton:hover { background: rgba(230,100,30,0.32); }"
            " QPushButton:disabled { color: rgba(255,255,255,0.20);"
            " border-color: rgba(255,255,255,0.08); background: transparent; }"
        )
        self.btn_usar_epi_visor.clicked.connect(self._on_usar_epigrafe)
        layout.addWidget(self.btn_usar_epi_visor)

    # ── API pública (llamada desde MainWindow) ───────────────────────────────

    def set_pagina(self, numero: Optional[int]) -> None:
        """Registra qué página está activa (necesario para el diálogo de renombrado)."""
        self._pagina_activa = numero

    def set_epigrafes(self, epigrafes: dict[str, str]) -> None:
        """Recibe los epígrafes por filename para mostrar junto a la imagen navegada."""
        self._imagenes_epigrafes = epigrafes or {}
        self._actualizar_epigrafe_visor()

    def cargar_imagenes(self, images: list[Path], foto_tapa_activa: bool = False) -> None:
        """Reemplaza la lista de imágenes y muestra la primera."""
        self._images      = list(images)
        self._image_index = 0 if images else -1
        self._foto_tapa_activa = foto_tapa_activa
        self._aplicar_estilo_estrella(foto_tapa_activa)
        self._show_current()
        self._emit_navegada()

    def actualizar_imagenes(self, images: list[Path]) -> None:
        """Recarga la lista preservando el índice actual si es posible."""
        self._images = list(images)
        if self._image_index >= len(self._images):
            self._image_index = len(self._images) - 1
        self._show_current()

    def limpiar(self) -> None:
        """Limpia el visor (sin página activa)."""
        self._images      = []
        self._image_index = -1
        self._foto_tapa_activa  = False
        self._foto_seleccionada = False
        self._foto_orden        = None
        self._imagenes_epigrafes = {}
        self._aplicar_estilo_estrella(False)
        self._aplicar_estilo_seleccionar(False)
        self.image_label.clear()
        self.image_label.setText("Sin imagen")
        self.label_nombre_img.setText("")
        self._lbl_epigrafe_visor.setText("")
        self.btn_usar_epi_visor.setEnabled(False)
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)

    def imagen_actual(self) -> Optional[Path]:
        if 0 <= self._image_index < len(self._images):
            return self._images[self._image_index]
        return None

    def indice_actual(self) -> int:
        return self._image_index

    def set_foto_tapa_activa(self, activa: bool) -> None:
        self._foto_tapa_activa = activa
        self._aplicar_estilo_estrella(activa)

    def set_foto_seleccionada(self, seleccionada: bool,
                               orden: Optional[int] = None) -> None:
        """
        Actualiza el estado visual del botón 📌 y el sufijo del label de nombre.

        Llamar desde MainWindow cada vez que cambia la imagen visible en el visor
        o cuando el estado de selección cambia.
        """
        self._foto_seleccionada = seleccionada
        self._foto_orden = orden
        self._aplicar_estilo_seleccionar(seleccionada)
        # Refresca el label para mostrar/ocultar [#N]
        if self._image_index >= 0:
            self._show_current()

    def reescalar(self) -> None:
        """Llamar desde resizeEvent de MainWindow para reescalar la imagen visible."""
        if self._image_index >= 0:
            self._show_current()

    # ── Navegación ───────────────────────────────────────────────────────────

    def _nav_prev(self) -> None:
        if self._image_index > 0:
            self._image_index -= 1
            self._show_current()
            self._emit_navegada()

    def _nav_next(self) -> None:
        if self._image_index < len(self._images) - 1:
            self._image_index += 1
            self._show_current()
            self._emit_navegada()

    def _emit_navegada(self) -> None:
        if 0 <= self._image_index < len(self._images):
            self.imagen_navegada.emit(self._images[self._image_index])

    def _actualizar_epigrafe_visor(self) -> None:
        if 0 <= self._image_index < len(self._images):
            epi = self._imagenes_epigrafes.get(self._images[self._image_index].name, "")
        else:
            epi = ""
        self._lbl_epigrafe_visor.setText(epi)
        self.btn_usar_epi_visor.setEnabled(bool(epi))

    def _on_usar_epigrafe(self) -> None:
        epi = self._lbl_epigrafe_visor.text()
        if epi:
            self.usar_epigrafe.emit(epi)

    # ── Render ───────────────────────────────────────────────────────────────

    def _show_current(self) -> None:
        if self._image_index < 0 or self._image_index >= len(self._images):
            self.image_label.clear()
            self.image_label.setText("Sin imagen")
            self.label_nombre_img.setText("")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self._actualizar_botones_foto()
            return

        path = self._images[self._image_index]
        pm   = QPixmap(str(path))
        if pm.isNull():
            self.image_label.clear()
            self.image_label.setText(f"No se pudo abrir:\n{path.name}")
            sufijo_orden = (
                f"  [#{self._foto_orden + 1}]"
                if self._foto_seleccionada and self._foto_orden is not None
                else ""
            )
            self.label_nombre_img.setText(path.name + sufijo_orden)
        else:
            vw = self.img_scroll.viewport().width() - 8
            if vw > 50:
                pm = pm.scaledToWidth(vw, Qt.SmoothTransformation)
            self.image_label.setPixmap(pm)
            sufijo_orden = (
                f"  [#{self._foto_orden + 1}]"
                if self._foto_seleccionada and self._foto_orden is not None
                else ""
            )
            self.label_nombre_img.setText(path.name + sufijo_orden)

        self.btn_prev.setEnabled(self._image_index > 0)
        self.btn_next.setEnabled(self._image_index < len(self._images) - 1)
        self.image_label.setStyleSheet(
            "background:#111; color:#aaa; border:1px solid #333;"
        )
        self._actualizar_botones_foto()
        self._actualizar_epigrafe_visor()

    # ── Selección de fotos de página ─────────────────────────────────────────

    def _on_seleccionar_clicked(self) -> None:
        if not self._images or self._image_index < 0:
            return
        src = self._images[self._image_index]
        if self._foto_seleccionada:
            # Deseleccionar
            self._foto_seleccionada = False
            self._foto_orden        = None
            self._aplicar_estilo_seleccionar(False)
            self.foto_deseleccionar.emit(src)
            _log.debug("Foto deseleccionada vía botón: %s", src.name)
        else:
            # Seleccionar
            self._foto_seleccionada = True
            self._aplicar_estilo_seleccionar(True)
            self.foto_seleccionar.emit(src)
            _log.debug("Foto seleccionada vía botón: %s", src.name)

    def _aplicar_estilo_seleccionar(self, activa: bool) -> None:
        self.btn_seleccionar.set_activo(bool(activa))

    def _on_editar_foto_clicked(self) -> None:
        img = self.imagen_actual()
        if img:
            self.abrir_en_editor_solicitado.emit(img)

    def _on_qr_clicked(self) -> None:
        """#11 — pide un link y solicita generar un QR para la página actual."""
        from PyQt5.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, "Generar QR", "Pegá el link del QR:")
        if ok and url and url.strip():
            self.qr_link_solicitado.emit(url.strip())

    def _actualizar_botones_foto(self) -> None:
        """Habilita/deshabilita (gris) los 3 íconos según si hay imagen visible."""
        hay = self.imagen_actual() is not None
        for b in (self.btn_seleccionar, self.btn_foto_tapa, self.btn_editar_foto):
            b.set_enabled(hay)

    # ── Foto de tapa ─────────────────────────────────────────────────────────

    def _on_foto_tapa_clicked(self) -> None:
        if not self._images or self._image_index < 0:
            return
        if self._foto_tapa_activa:
            resp = QMessageBox.question(
                self, "Quitar foto de tapa",
                "La imagen marcada como foto de tapa se deseleccionará.\n\n"
                "El archivo copiado en materiales/P01 será borrado.\n"
                "La imagen original NO se modifica.\n\n"
                "¿Querés continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resp == QMessageBox.Yes:
                self._foto_tapa_activa = False
                self._aplicar_estilo_estrella(False)
                self.foto_tapa_desmarcar.emit()
        else:
            src = self._images[self._image_index]
            self._foto_tapa_activa = True
            self._aplicar_estilo_estrella(True)
            self.foto_tapa_marcar.emit(src)

    def _aplicar_estilo_estrella(self, activa: bool) -> None:
        self.btn_foto_tapa.set_activo(bool(activa))

    # ── Menú contextual (clic derecho) ───────────────────────────────────────

    def _on_context_menu(self, pos) -> None:
        if self._image_index < 0 or self._image_index >= len(self._images):
            return
        menu = QMenu(self)
        act  = QAction("Eliminar imagen", self)
        act.triggered.connect(self._on_delete_current)
        menu.addAction(act)
        menu.exec_(self.image_label.mapToGlobal(pos))

    def _on_delete_current(self) -> None:
        if self._image_index < 0 or self._image_index >= len(self._images):
            return
        path = self._images[self._image_index]
        if not path.exists():
            QMessageBox.warning(self, "Eliminar imagen", "El archivo no existe en disco.")
            return
        resp = QMessageBox.question(
            self, "Eliminar imagen",
            f"¿Seguro que querés eliminar '{path.name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        try:
            path.unlink()
            self.imagen_eliminada.emit(path)
            QMessageBox.information(self, "Eliminar imagen", "Imagen eliminada correctamente.")
        except Exception as e:
            QMessageBox.critical(self, "Eliminar imagen", f"No se pudo eliminar:\n{e}")

    # ── Doble click → diálogo de renombrado con visor ampliado ───────────────

    def _on_double_click(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._image_index < 0 or self._pagina_activa is None:
            return
        self._abrir_dialogo_renombrado()

    def _abrir_dialogo_renombrado(self) -> None:
        src = self._images[self._image_index]
        n   = self._pagina_activa

        dlg = QDialog(self)
        dlg.setWindowTitle(
            f"Visor de imágenes – Página {n:02d} "
            f"({self._image_index + 1}/{len(self._images)})"
        )
        dlg.setStyleSheet("background:#0f172a; color:#e0e0e0;")
        dlg.setWindowState(Qt.WindowMaximized)
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 40)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setStyleSheet("background:#111; border:1px solid #333;")
        lbl_preview = QLabel()
        lbl_preview.setAlignment(Qt.AlignCenter)
        sc_content = QWidget()
        sc_layout  = QVBoxLayout(sc_content)
        sc_layout.addWidget(lbl_preview)
        sc_layout.setAlignment(Qt.AlignCenter)
        scroll.setWidget(sc_content)
        layout.addWidget(scroll, stretch=1)

        screen   = QApplication.primaryScreen().availableGeometry()
        screen_w = int(screen.width()  * 0.9)
        screen_h = int(screen.height() * 0.8)

        def mostrar(idx: int) -> None:
            if 0 <= idx < len(self._images):
                pm2 = QPixmap(str(self._images[idx]))
                if not pm2.isNull():
                    lbl_preview.setPixmap(
                        pm2.scaled(screen_w, screen_h,
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
                self._image_index = idx
                dlg.setWindowTitle(
                    f"Visor de imágenes – Página {n:02d} "
                    f"({self._image_index + 1}/{len(self._images)})"
                )
                edit.setText(self._images[idx].stem)
            btn_dlg_prev.setEnabled(self._image_index > 0)
            btn_dlg_next.setEnabled(self._image_index < len(self._images) - 1)

        # Mostrar imagen inicial
        pm0 = QPixmap(str(src))
        if not pm0.isNull():
            lbl_preview.setPixmap(
                pm0.scaled(screen_w, screen_h,
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        # Navegación interna del diálogo
        nav_dlg = QHBoxLayout()
        btn_dlg_prev = QPushButton("< Anterior")
        btn_dlg_next = QPushButton("Siguiente >")
        for b in (btn_dlg_prev, btn_dlg_next):
            b.setStyleSheet(self._STYLE_BTN)
            b.setFixedHeight(36)
        nav_dlg.addWidget(btn_dlg_prev)
        nav_dlg.addWidget(btn_dlg_next)
        layout.addLayout(nav_dlg)

        btn_dlg_prev.setEnabled(self._image_index > 0)
        btn_dlg_next.setEnabled(self._image_index < len(self._images) - 1)
        btn_dlg_prev.clicked.connect(lambda: mostrar(self._image_index - 1))
        btn_dlg_next.clicked.connect(lambda: mostrar(self._image_index + 1))

        # Input de nombre
        edit = QLineEdit(dlg)
        edit.setFont(QFont("Arial", 14))
        edit.setText(src.stem)
        edit.setPlaceholderText(f"Nombre para la imagen (sin 'para la {n:02d}')")
        layout.addWidget(edit)

        # Checkbox: seleccionar foto para la página al renombrar
        chk_seleccionar = QCheckBox("Seleccionar esta foto para la página al renombrar")
        chk_seleccionar.setChecked(not self._foto_seleccionada)  # pre-marcado si no estaba
        chk_seleccionar.setStyleSheet("color: #94a3b8; font-size: 12px; padding: 2px 0;")
        layout.addWidget(chk_seleccionar)

        # Botones ok/cancel
        bottom = QHBoxLayout()
        bottom.setSpacing(20)
        bottom.setAlignment(Qt.AlignCenter)
        btn_ok     = QPushButton("Aceptar")
        btn_cancel = QPushButton("Cancelar")
        for b in (btn_ok, btn_cancel):
            b.setStyleSheet(self._STYLE_BTN)
            b.setFixedWidth(120)
        bottom.addWidget(btn_ok)
        bottom.addWidget(btn_cancel)
        layout.addLayout(bottom)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        def on_key(e) -> None:
            if   e.key() == Qt.Key_Left:               mostrar(self._image_index - 1)
            elif e.key() == Qt.Key_Right:              mostrar(self._image_index + 1)
            elif e.key() == Qt.Key_Escape:             dlg.reject()
            elif e.key() in (Qt.Key_Return, Qt.Key_Enter): dlg.accept()
            else: QDialog.keyPressEvent(dlg, e)

        dlg.keyPressEvent = on_key

        result = dlg.exec_()

        if result == QDialog.Accepted:
            nuevo_nombre = (edit.text() or "").strip()
            src_final    = self._images[self._image_index]
            if nuevo_nombre and nuevo_nombre != src_final.stem:
                self.imagen_renombrada.emit(src_final, nuevo_nombre)
            # Seleccionar la foto si el checkbox estaba marcado y no estaba ya seleccionada
            if chk_seleccionar.isChecked() and not self._foto_seleccionada:
                self._foto_seleccionada = True
                self._aplicar_estilo_seleccionar(True)
                self.foto_seleccionar.emit(src_final)

        # Restaurar navegación del mini-visor
        self._show_current()
