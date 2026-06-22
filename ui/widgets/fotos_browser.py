from __future__ import annotations
from pathlib import Path
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QWidget, QScrollArea, QHBoxLayout, QVBoxLayout, QLabel,
    QFrame, QSizePolicy, QMenu, QAction, QMessageBox, QDialog, QPushButton
)

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


class _BoundFPS:
    """Wraps FotoPaginaService con pagina/subfolder/material ya fijados."""

    def __init__(self, svc, pagina: int, subfolder, material: Path):
        self._svc = svc
        self._pagina = pagina
        self._subfolder = subfolder
        self._mat = material

    def cargar(self) -> dict:
        return self._svc.cargar(self._pagina, self._subfolder, self._mat)

    def seleccionar(self, path: Path, rol: str = "principal") -> None:
        estado = self.cargar()
        path_str = str(path)
        fotos = [f for f in estado.get("fotos", []) if f["path"] != path_str]
        if rol == "principal":
            fotos.insert(0, {"path": path_str, "nombre": path.name, "orden": 0, "rol": "principal"})
        else:
            fotos.append({"path": path_str, "nombre": path.name, "orden": len(fotos), "rol": "secundaria"})
        for i, f in enumerate(fotos):
            f["orden"] = i
            f["rol"] = "principal" if i == 0 else "secundaria"
        estado["fotos"] = fotos
        estado["pegadas_at"] = None
        self._svc.guardar(estado, self._pagina, self._subfolder, self._mat)

    def guardar(self) -> None:
        pass  # seleccionar() ya guarda; método presente para compatibilidad
_THUMB_W = 120
_THUMB_H = 90
_PREVIEW_H   = 200   # altura fija del preview — no se expande
_PREVIEW_MAX_W = 700  # ancho máximo fijo para evitar feedback loop en scaled()


class _PreviewDialog(QDialog):
    """Muestra la imagen en tamaño completo en una ventana aparte."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(path.name)
        self.setModal(False)
        self.resize(900, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl)
        px = QPixmap(str(path))
        if not px.isNull():
            px = px.scaled(880, 660, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl.setPixmap(px)
        else:
            lbl.setText("No se pudo cargar la imagen.")


class _ThumbCard(QFrame):
    clicked        = pyqtSignal(Path)
    double_clicked = pyqtSignal(Path)
    set_principal_requested = pyqtSignal(Path)
    qr_solicitada           = pyqtSignal(Path)

    def __init__(self, img_path: Path, is_principal: bool = False, parent=None):
        super().__init__(parent)
        self.img_path = img_path
        self.setFixedWidth(_THUMB_W + 8)
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        self.lbl_img = QLabel()
        self.lbl_img.setFixedSize(_THUMB_W, _THUMB_H)
        self.lbl_img.setAlignment(Qt.AlignCenter)
        self.lbl_img.setStyleSheet("background: #0f172a;")
        lay.addWidget(self.lbl_img)

        self.lbl_name = QLabel(img_path.name)
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setAlignment(Qt.AlignCenter)
        self.lbl_name.setStyleSheet("font-size: 10px; color: rgba(255,255,255,0.6);")
        lay.addWidget(self.lbl_name)

        self.lbl_principal = QLabel("📌 Principal")
        self.lbl_principal.setAlignment(Qt.AlignCenter)
        self.lbl_principal.setStyleSheet("font-size: 10px; color: #16a34a; font-weight: bold;")
        self.lbl_principal.setVisible(is_principal)
        lay.addWidget(self.lbl_principal)

        self.lbl_qr = QLabel("QR")
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setStyleSheet("font-size: 10px; color: #38bdf8; font-weight: bold;")
        self.lbl_qr.setVisible(False)
        lay.addWidget(self.lbl_qr)

        self._load_thumb()

    def _load_thumb(self):
        try:
            px = QPixmap(str(self.img_path))
            if not px.isNull():
                px = px.scaled(_THUMB_W, _THUMB_H, Qt.KeepAspectRatio, Qt.FastTransformation)
                self.lbl_img.setPixmap(px)
            else:
                self.lbl_img.setText("?")
        except Exception:
            self.lbl_img.setText("?")

    def set_principal(self, val: bool):
        self.lbl_principal.setVisible(val)
        self.setProperty("principal", val)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_qr(self, val: bool):
        self.lbl_qr.setVisible(val)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.img_path)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit(self.img_path)
        super().mouseDoubleClickEvent(e)

    def _show_menu(self, pos):
        menu = QMenu(self)
        act = QAction("Establecer como principal", self)
        act.triggered.connect(lambda: self.set_principal_requested.emit(self.img_path))
        menu.addAction(act)
        act_qr = QAction("Marcar como QR", self)
        act_qr.triggered.connect(lambda: self.qr_solicitada.emit(self.img_path))
        menu.addAction(act_qr)
        act2 = QAction("Ver en tamaño completo", self)
        act2.triggered.connect(lambda: self.double_clicked.emit(self.img_path))
        menu.addAction(act2)
        menu.exec_(self.mapToGlobal(pos))


class FotosBrowser(QWidget):
    foto_seleccionada = pyqtSignal(Path)
    usar_epigrafe     = pyqtSignal(str)
    qr_seleccionada   = pyqtSignal(object)  # Path | None

    def __init__(self, img_dir: Path, foto_pagina_service=None, epigrafes: dict | None = None, parent=None):
        super().__init__(parent)
        self._dir = img_dir
        self._fps = foto_pagina_service
        self._epigrafes: dict[str, str] = epigrafes or {}
        self._cards: list[_ThumbCard] = []
        self._preview_path: Path | None = None
        self._preview_dlg: _PreviewDialog | None = None
        self._current_epi: str = ""
        self._qr_path: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(_THUMB_H + 80)

        self._strip = QWidget()
        self._strip_lay = QHBoxLayout(self._strip)
        self._strip_lay.setContentsMargins(4, 4, 4, 4)
        self._strip_lay.setSpacing(8)
        self._strip_lay.addStretch(1)
        self._scroll.setWidget(self._strip)
        root.addWidget(self._scroll)

        # Preview con altura FIJA (no se expande)
        self._lbl_preview = QLabel()
        self._lbl_preview.setAlignment(Qt.AlignCenter)
        self._lbl_preview.setFixedHeight(_PREVIEW_H)
        self._lbl_preview.setMaximumWidth(_PREVIEW_MAX_W)
        self._lbl_preview.setStyleSheet("background: #0f172a; border-radius: 8px;")
        self._lbl_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hint = QLabel("Clic para previsualizar · Doble clic para ampliar")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: rgba(255,255,255,0.35); font-size: 10px;")
        root.addWidget(self._lbl_preview)
        root.addWidget(hint)

        self._lbl_epigrafe = QLabel("")
        self._lbl_epigrafe.setWordWrap(True)
        self._lbl_epigrafe.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._lbl_epigrafe.setMinimumHeight(32)
        self._lbl_epigrafe.setStyleSheet(
            "color: rgba(255,255,255,0.55); font-size: 11px; padding: 4px 2px;"
        )
        root.addWidget(self._lbl_epigrafe)

        self.btn_usar_epi = QPushButton("Usar este epígrafe")
        self.btn_usar_epi.setCursor(Qt.PointingHandCursor)
        self.btn_usar_epi.setEnabled(False)
        self.btn_usar_epi.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 4px 10px;"
            " background: rgba(230,100,30,0.18); border: 1px solid rgba(230,100,30,0.45);"
            " border-radius: 6px; color: #f59e0b; }"
            " QPushButton:hover { background: rgba(230,100,30,0.32); }"
            " QPushButton:disabled { color: rgba(255,255,255,0.20);"
            " border-color: rgba(255,255,255,0.08); background: transparent; }"
        )
        self.btn_usar_epi.clicked.connect(lambda: self.usar_epigrafe.emit(self._current_epi))
        root.addWidget(self.btn_usar_epi)

        self._lbl_no_fotos = QLabel("No hay fotos en esta carpeta.")
        self._lbl_no_fotos.setAlignment(Qt.AlignCenter)
        self._lbl_no_fotos.setStyleSheet("color: rgba(255,255,255,0.4);")
        root.addWidget(self._lbl_no_fotos)

        self.reload(img_dir)

    def set_epigrafes(self, epigrafes: dict[str, str]) -> None:
        self._epigrafes = epigrafes or {}

    def set_qr_path(self, path: Path | None) -> None:
        self._qr_path = path
        for card in self._cards:
            card.set_qr(card.img_path == path)

    def reload(self, img_dir: Path):
        self._dir = img_dir
        self._current_epi = ""
        self._lbl_epigrafe.setText("")
        self.btn_usar_epi.setEnabled(False)
        while self._strip_lay.count() > 1:
            item = self._strip_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards.clear()
        self._lbl_preview.clear()
        self._preview_path = None

        if not img_dir or not img_dir.exists():
            self._lbl_no_fotos.show()
            return

        imgs = sorted(
            [f for f in img_dir.iterdir()
             if f.is_file() and f.suffix.lower() in _IMG_EXTS and not f.name.startswith("qr_")],
            key=lambda f: f.name
        )
        self._lbl_no_fotos.setVisible(len(imgs) == 0)

        principal_path: Path | None = None
        if self._fps:
            try:
                estado = self._fps.cargar()
                for f in estado.get("fotos", []):
                    if f.get("rol") == "principal":
                        principal_path = Path(f["path"])
                        break
            except Exception:
                pass

        for img in imgs:
            card = _ThumbCard(img, is_principal=(principal_path is not None and img == principal_path))
            card.clicked.connect(self._on_thumb_click)
            card.double_clicked.connect(self._on_thumb_double_click)
            card.set_principal_requested.connect(self._on_set_principal)
            card.qr_solicitada.connect(self._on_qr_solicitada)
            if self._qr_path is not None and img == self._qr_path:
                card.set_qr(True)
            self._strip_lay.insertWidget(self._strip_lay.count() - 1, card)
            self._cards.append(card)

    def _on_thumb_click(self, path: Path):
        self._preview_path = path
        try:
            px = QPixmap(str(path))
            if not px.isNull():
                px = px.scaled(
                    _PREVIEW_MAX_W,
                    _PREVIEW_H,
                    Qt.KeepAspectRatio,
                    Qt.FastTransformation,
                )
                self._lbl_preview.setPixmap(px)
        except Exception:
            pass
        epi = self._epigrafes.get(path.name, "")
        self._current_epi = epi
        self._lbl_epigrafe.setText(epi if epi else "")
        self.btn_usar_epi.setEnabled(bool(epi))
        self.foto_seleccionada.emit(path)

    def _on_thumb_double_click(self, path: Path):
        # Cerrar diálogo anterior si sigue abierto
        if self._preview_dlg is not None:
            try:
                self._preview_dlg.close()
            except Exception:
                pass
        self._preview_dlg = _PreviewDialog(path, parent=self)
        self._preview_dlg.show()

    def _on_set_principal(self, path: Path):
        if self._fps:
            try:
                self._fps.seleccionar(path, rol="principal")
                self._fps.guardar()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo guardar como principal:\n{e}")
        for card in self._cards:
            card.set_principal(card.img_path == path)

    def _on_qr_solicitada(self, path: Path):
        if self._qr_path == path:
            # Toggle off
            self._qr_path = None
            for card in self._cards:
                card.set_qr(False)
            self.qr_seleccionada.emit(None)
        else:
            self._qr_path = path
            for card in self._cards:
                card.set_qr(card.img_path == path)
            self.qr_seleccionada.emit(path)

    def set_fps(self, svc, pagina: int, subfolder, material: Path) -> None:
        """Conecta el servicio de fotos con los parámetros de página ya fijados."""
        self._fps = _BoundFPS(svc, pagina, subfolder, material)
        self.reload(self._dir)

    # No resizeEvent: preview height es fija, no hay nada que recalcular
