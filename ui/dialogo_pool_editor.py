# ui/dialogo_pool_editor.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

from services.ia_service import AIRewriter
from ui.visor_img import VisorImagenes
import logging
_log = logging.getLogger(__name__)



class PoolEditorDialog(QDialog):
    """
    Editor flotante para una noticia del POOL.

    Reutilizable: no se destruye al cerrar (se oculta).
    El visor de imágenes vive en ui/visor_img.py (VisorImagenes).

    Señales:
        guardar_cambios(dict)  — datos listos para persistir en disco.
        cerrado()              — diálogo ocultado/cerrado.
    """

    guardar_cambios = pyqtSignal(dict)
    cerrado = pyqtSignal()

    def __init__(self, controller, parent: Optional[QWidget] = None):
        """
        Args:
            controller: instancia de ArmadorController, necesaria para
                        copiar/borrar la foto de tapa en materiales/P01.
            parent:     ventana padre Qt.
        """
        super().__init__(parent)
        self._controller = controller

        self.setWindowTitle("Edición de noticia del Pool")
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(620, 920)

        self._dir_pool_actual: Optional[Path] = None
        self._meta_actual: dict = {}
        self._cambios_pendientes: bool = False

        # ── Estilos compartidos ────────────────────────────────────
        label_font = QFont()
        label_font.setPointSize(12)
        label_font.setBold(True)
        label_style = "color: #F28C28;"
        font_normal = QFont("Arial", 12)

        # ── Layout raíz ───────────────────────────────────────────
        main_layout = QVBoxLayout(self)

        # ── Scroll principal ──────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; }
            QScrollBar:vertical {
                width: 12px; background: #2b2b2b;
                margin: 0px; border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #F28C28; min-height: 30px; border-radius: 6px;
            }
            QScrollBar::add-line, QScrollBar::sub-line { height: 0px; }
        """)

        scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(scroll_content)
        self._scroll_layout.setSpacing(20)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        def _lbl(texto: str) -> QLabel:
            l = QLabel(texto)
            l.setFont(label_font)
            l.setStyleSheet(label_style)
            return l

        # ── Volanta ───────────────────────────────────────────────
        self._scroll_layout.addWidget(_lbl("Volanta"))
        self.ed_volanta = QTextEdit()
        self.ed_volanta.setFixedHeight(60)
        self.ed_volanta.setFont(font_normal)
        self._scroll_layout.addWidget(self.ed_volanta)

        # ── Título ────────────────────────────────────────────────
        self._scroll_layout.addWidget(_lbl("Título"))
        self.ed_titulo = QTextEdit()
        self.ed_titulo.setFixedHeight(80)
        self.ed_titulo.setFont(QFont("Arial", 16))
        self._scroll_layout.addWidget(self.ed_titulo)

        # ── Bajada ────────────────────────────────────────────────
        self._scroll_layout.addWidget(_lbl("Bajada"))
        self.ed_bajada = QTextEdit()
        self.ed_bajada.setFixedHeight(80)
        self.ed_bajada.setFont(QFont("Arial", 14))
        self._scroll_layout.addWidget(self.ed_bajada)

        # ── Autor ─────────────────────────────────────────────────
        self._scroll_layout.addWidget(_lbl("Autor de creación"))
        self.ed_autor = QTextEdit()
        self.ed_autor.setFixedHeight(50)
        self.ed_autor.setFont(font_normal)
        self._scroll_layout.addWidget(self.ed_autor)

        # ── Firma ─────────────────────────────────────────────────
        self.chk_firmado = QCheckBox("Nota firmada")
        self.chk_firmado.setStyleSheet("color: #F28C28; font-weight: bold;")
        self._scroll_layout.addWidget(self.chk_firmado)

        # ── Cuerpo ────────────────────────────────────────────────
        self._scroll_layout.addWidget(_lbl("Cuerpo"))
        self.ed_cuerpo = QTextEdit()
        self.ed_cuerpo.setMinimumHeight(400)
        self.ed_cuerpo.setFont(font_normal)
        self._scroll_layout.addWidget(self.ed_cuerpo)

        # ── Visor de imágenes ─────────────────────────────────────
        self._scroll_layout.addWidget(_lbl("Imágenes asociadas"))
        self.visor = VisorImagenes(self)
        self._scroll_layout.addWidget(self.visor)

        # ── Botones principales ───────────────────────────────────
        btns = QHBoxLayout()
        self.btn_aceptar    = QPushButton("Guardar")
        self.btn_cancelar   = QPushButton("Cancelar")
        self.btn_reescribir = QPushButton("Reescribir con IA")
        btns.addWidget(self.btn_aceptar)
        btns.addWidget(self.btn_cancelar)
        btns.addWidget(self.btn_reescribir)
        main_layout.addLayout(btns)

        # Conexiones
        self.btn_cancelar.clicked.connect(self._on_cancelar)
        self.btn_aceptar.clicked.connect(self._on_guardar)
        self.btn_reescribir.clicked.connect(self._on_reescribir_ai)

    # ──────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────

    def cargar_noticia(self, dir_pool: Path, meta: dict, texto: str) -> None:
        """
        Carga los campos de texto y las imágenes de la noticia seleccionada.
        Detecta automáticamente si ya hay una foto de tapa en P01 para esta noticia.
        """
        self._dir_pool_actual = Path(dir_pool)
        self._meta_actual = meta
        self._cambios_pendientes = False

        # ── Campos de texto ───────────────────────────────────────
        self.chk_firmado.setChecked(bool(meta.get("firmado", False)))
        self.ed_volanta.setText(meta.get("volanta", ""))
        self.ed_titulo.setText(meta.get("titulo", ""))
        self.ed_bajada.setText(meta.get("bajada", ""))
        self.ed_autor.setText(meta.get("autor_creacion", ""))
        self.ed_cuerpo.setText(texto or "")

        for widget in (self.ed_volanta, self.ed_titulo,
                       self.ed_bajada, self.ed_autor, self.ed_cuerpo):
            c = widget.textCursor()
            c.movePosition(c.Start)
            widget.setTextCursor(c)

        # ── Imágenes ──────────────────────────────────────────────
        exts = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")
        paths: list[Path] = []
        if self._dir_pool_actual.exists():
            paths = [
                f for f in sorted(self._dir_pool_actual.iterdir())
                if f.is_file() and f.suffix.lower() in exts
            ]

        # Principal primero
        principal = meta.get("imagen_principal")
        if principal:
            p = self._dir_pool_actual / principal
            if p in paths:
                paths.remove(p)
                paths.insert(0, p)

        # Epígrafes
        epis: dict[str, str] = {}
        for im in (meta.get("imagenes") or []):
            fname = im.get("filename")
            if fname:
                epis[fname] = im.get("epigrafe", "")

        self.visor.cargar(paths, epis)

    def hay_cambios_pendientes(self) -> bool:
        return self._cambios_pendientes

    def mark_dirty(self) -> None:
        self._cambios_pendientes = True

    # ──────────────────────────────────────────────────────────────
    # Slots internos — botones de diálogo
    # ──────────────────────────────────────────────────────────────

    def _on_cancelar(self) -> None:
        self.hide()
        self.cerrado.emit()

    def _on_guardar(self) -> None:
        if not self._dir_pool_actual:
            return

        epis = self.visor.epigrafes_actuales()

        data = {
            "dir":           self._dir_pool_actual,
            "volanta":       self.ed_volanta.toPlainText().strip(),
            "titulo":        self.ed_titulo.toPlainText().strip(),
            "bajada":        self.ed_bajada.toPlainText().strip(),
            "autor_creacion": self.ed_autor.toPlainText().strip(),
            "cuerpo":        self.ed_cuerpo.toPlainText().strip(),
            "firmado":       self.chk_firmado.isChecked(),
            "imagenes": [
                {"filename": p.name, "epigrafe": epis.get(p.name, "")}
                for p in (self.visor._imagenes_paths or [])
            ],
        }

        self.guardar_cambios.emit(data)
        self._cambios_pendientes = False
        self.hide()
        self.cerrado.emit()

    def _on_reescribir_ai(self) -> None:
        original = self.ed_cuerpo.toPlainText().strip()
        if not original:
            return
        try:
            rewriter = AIRewriter()
            nuevo = rewriter.reescribir_cuerpo(original)
            if nuevo:
                self.ed_cuerpo.setPlainText(nuevo)
                self.mark_dirty()
        except Exception as e:
            QMessageBox.warning(self, "Error IA", f"Error al reescribir con IA:\n{e}")
            _log.info(f"[AI] Error: {e}")

    def closeEvent(self, event) -> None:
        self.cerrado.emit()
        super().closeEvent(event)

    # ──────────────────────────────────────────────────────────────
    # Helper
    # ──────────────────────────────────────────────────────────────

    # (sin métodos de foto de tapa; esa funcionalidad vive
    #  exclusivamente en VisorPanelWidget / main_window)
