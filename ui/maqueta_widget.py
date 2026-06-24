from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QPen
from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QApplication,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMenu, QAction
)
from pathlib import Path
import fitz  # PyMuPDF
import subprocess
import hashlib
import configparser
from config.config import Config
import logging
_log = logging.getLogger(__name__)




# ============================================================
# 🔹 Conversión EPS → PNG (con cacheado)
# ============================================================
def _eps_to_png(eps_path: Path, cache_dir: Path, dpi: int = 150) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(str(eps_path).encode("utf-8")).hexdigest()[:8]
    out_path = cache_dir / f"{eps_path.stem}_{h}.png"

    if out_path.exists() and out_path.stat().st_mtime >= eps_path.stat().st_mtime:
        return out_path

    cfg = configparser.ConfigParser()
    cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
    gs_path = cfg.get("APPS", "ghostscript", fallback="gswin64c")

    cmd = [
        gs_path, "-dEPSCrop", "-sDEVICE=pngalpha",
        f"-r{dpi}", "-o", str(out_path), str(eps_path)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if out_path.exists():
            _log.info(f"[OK] EPS convertido → {out_path}")
            return out_path
    except Exception as e:
        _log.warning(f"[WARN] Falló conversión EPS: {e}")
    return None


# ============================================================
# 🔹 Conversión PDF → PNG en disco (cacheado, SIN Qt → seguro en hilos)
# ============================================================
def pdf_to_png(pdf_path: Path, cache_dir: Path, scale_factor: int = 2) -> Path | None:
    """Rasteriza la 1ª página del PDF a un PNG de caché usando PyMuPDF (sin Qt).
    Apto para correr en un hilo de trabajo (no crea QPixmap)."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        h = hashlib.md5(str(pdf_path).encode("utf-8")).hexdigest()[:8]
        out_path = cache_dir / f"{pdf_path.stem}_{h}.png"
        if out_path.exists() and out_path.stat().st_mtime >= pdf_path.stat().st_mtime:
            return out_path
        doc = fitz.open(str(pdf_path))
        if doc.page_count == 0:
            return None
        pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(scale_factor, scale_factor), alpha=False)
        pix.save(str(out_path))
        return out_path if out_path.exists() else None
    except Exception as e:
        _log.warning(f"[WARN] Falló rasterización PDF→PNG: {e}")
        return None


# ============================================================
# 🔹 Conversión PDF → QPixmap
# ============================================================
def pdf_to_pixmap(path: str, scale_factor: int = 3) -> QPixmap:
    """Convierte el primer página de un PDF en QPixmap (usa PyMuPDF, sin poppler)."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        if doc.page_count == 0:
            return QPixmap()
        page = doc.load_page(0)
        mat = fitz.Matrix(scale_factor, scale_factor)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        if qimg.isNull():
            return QPixmap()
        return QPixmap.fromImage(qimg)
    except Exception as e:
        _log.warning(f"[WARN] Error al convertir PDF (fitz): {e}")
        return QPixmap()



# ============================================================
# 🔹 Visor con zoom (Ctrl + Rueda)
# ============================================================
class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene().addItem(self.pixmap_item)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.scale_factor = 1.5
        self.setSceneRect(self.pixmap_item.boundingRect())
        self.scale(0.5, 0.5)

    def wheelEvent(self, event):
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.ControlModifier:
            zoom = self.scale_factor if event.angleDelta().y() > 0 else 1 / self.scale_factor
            self.scale(zoom, zoom)
        else:
            super().wheelEvent(event)


# ============================================================
# 🔹 Maqueta principal (render no bloqueante)
# ============================================================
class MaquetaWidget(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.pagina = None
        self._last_pixmap = None
        self._loading = False
        self.setMinimumHeight(200)
        self.setStyleSheet("background:#1b1d1f; border:1px solid #334155;")

        # Miniaturas pdf para maqueta grande izquierda
        self._last_pixmap_pdf = None
        self._pdf_mtime = None


    # --------------------------------------------------------
    # Asignar página y cargar aviso fuera del paintEvent
    # --------------------------------------------------------
    def set_pagina(self, pagina):
        self.pagina = pagina
        self._last_pixmap = None
        self._last_pixmap_pdf = None
        self._pdf_mtime = None      
        self._loading = False
        self.update()
        if pagina:
            # dispara carga asincrónica sin bloquear la UI
            QTimer.singleShot(0, self.load_aviso_async)
            entry = self.controller.file_service.read_page_entry(pagina.numero)
            estado = (entry.get("estado") or "").strip().lower()
            if estado in ("pdf", "ok"):
                QTimer.singleShot(0, self.load_pdf_async)


    # --------------------------------------------------------
    # Carga de PDF miniatura (asíncrona)
    # --------------------------------------------------------
    def load_pdf_async(self):
        """Carga una miniatura del PDF asociado si existe y no está cacheado."""
        if not self.pagina:
            return
        numero = self.pagina.numero
        pdf_path = self.controller.file_service.find_pdf_for_page(numero)
        if not pdf_path or not pdf_path.exists():
            return

        mtime = pdf_path.stat().st_mtime
        if self._pdf_mtime == mtime and self._last_pixmap_pdf:
            return

        pixmap = pdf_to_pixmap(str(pdf_path), scale_factor=2)
        if not pixmap.isNull():
            self._last_pixmap_pdf = pixmap
            self._pdf_mtime = mtime
            self._last_pixmap = pixmap  # prioriza PDF sobre aviso
            _log.info(f"[OK] Miniatura PDF cargada para P{numero:02d}")
            self.update()

    
    
    # --------------------------------------------------------
    # Carga de aviso (asíncrona)
    # --------------------------------------------------------
    def load_aviso_async(self):
        """Carga el aviso sin bloquear la GUI (solo una vez por cambio de página)."""
        if not self.pagina or self._loading:
            return

        self._loading = True
        numero = self.pagina.numero
        nombre = getattr(self.pagina, "aviso_nombre", "")
        tipo = ""
        if getattr(self.pagina, "aviso_full", False):
            tipo = "COMPLETA"
        elif getattr(self.pagina, "aviso_half", False):
            tipo = "MEDIA"
        elif getattr(self.pagina, "aviso_footer", False):
            tipo = "PIE"
        elif getattr(self.pagina, "aviso_robapagina", False):
            tipo = "ROBAPAGINA"

        _log.debug(f"[LOAD] Iniciando carga aviso P{numero:02d} ({nombre}, {tipo})...")

        try:
            aviso_file = self.controller.file_service.resolver_aviso_local(
                numero, nombre, tipo_aviso=tipo
            )
            if not aviso_file or not aviso_file.exists():
                _log.warning(f"[WARN] No se encontró archivo aviso para P{numero:02d}")
                self._last_pixmap = None
                self.pagina.aviso_pixmap = None
                return

            # --- Detección de cambios por fecha de modificación ---
            mtime = aviso_file.stat().st_mtime
            old_mtime = getattr(self.pagina, "aviso_mtime", None)
            cached_pix = getattr(self.pagina, "aviso_pixmap", None)

            # Si no cambió, usar caché
            if old_mtime and mtime == old_mtime and cached_pix and not cached_pix.isNull():
                self._last_pixmap = cached_pix
                _log.debug(f"[CACHE] Aviso sin cambios para P{numero:02d}")
                return

            # --- Cargar pixmap nuevo ---
            pixmap = None
            ext = aviso_file.suffix.lower()
            if ext == ".pdf":
                pixmap = pdf_to_pixmap(str(aviso_file))
            elif ext == ".eps":
                cache_dir = Path("cache_eps")
                png = _eps_to_png(aviso_file, cache_dir)
                if png and png.exists():
                    pixmap = QPixmap(str(png))
            else:
                pixmap = QPixmap(str(aviso_file))

            # --- Guardar resultados ---
            if pixmap and not pixmap.isNull():
                self._last_pixmap = pixmap
                self.pagina.aviso_pixmap = pixmap
                self.pagina.aviso_mtime = mtime
                _log.info(f"[OK] Aviso cargado o actualizado: {aviso_file.name}")
            else:
                _log.warning(f"[WARN] Aviso inválido o vacío: {aviso_file.name}")
                self._last_pixmap = None
                self.pagina.aviso_pixmap = None

        except Exception as e:
            _log.error(f"[ERROR] load_aviso_async: {e}")
            self._last_pixmap = None
            self.pagina.aviso_pixmap = None

        finally:
            self._loading = False
            self.update()

            # 🔹 Sincroniza el botón de la grilla si existe
            if hasattr(self.controller, "main_window"):
                boton = getattr(self.controller.main_window, "boton_paginas", {}).get(numero)
                if boton:
                    boton.update()



    # --------------------------------------------------------
    # Dibujo principal (solo render, sin I/O)
    # --------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#1e293b"))

        if not self.pagina:
            return

        try:
            # --- calcular marco proporcional ---
            W, H = self.width(), self.height()
            max_w, max_h = W * 0.6, H * 0.9
            ratio = 1.4
            w, h = max_w, max_w * ratio
            if h > max_h:
                h, w = max_h, max_h / ratio
            x, y = (W - w) / 2, (H - h) / 2
            rect = QRectF(x, y, w, h)

            painter.setPen(QPen(Qt.black, 2))
            painter.drawRect(rect)

            # --- determinar área del aviso según tipo ---
            area = None
            if getattr(self.pagina, "aviso_full", False):
                area = rect
            elif getattr(self.pagina, "aviso_half", False):
                # Mitad inferior
                area = QRectF(rect.left(), rect.top() + rect.height() / 2,
                              rect.width(), rect.height() / 2)
            elif getattr(self.pagina, "aviso_footer", False):
                # Cuarto inferior
                area = QRectF(rect.left(), rect.bottom() - rect.height() / 4,
                              rect.width(), rect.height() / 4)
            elif getattr(self.pagina, "aviso_robapagina", False):
                ancho = rect.width() / 2
                if self.pagina.numero % 2 == 0:
                    area = QRectF(rect.left(), rect.top(), ancho, rect.height())
                else:
                    area = QRectF(rect.left() + ancho, rect.top(), ancho, rect.height())

            # Si hay PDF miniatura disponible
            if not self.pagina:
                self._last_pixmap_pdf = None
                self._pdf_mtime = None
                return

            if self._last_pixmap_pdf and not self._last_pixmap_pdf.isNull():
                scaled = self._last_pixmap_pdf.scaled(
                    int(self.width() * 0.9),
                    int(self.height() * 0.9),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                x = int((self.width() - scaled.width()) / 2)
                y = int((self.height() - scaled.height()) / 2)
                painter.drawPixmap(x, y, scaled)
                return


            # --- si hay pixmap cacheado (aviso real) ---
            if self._last_pixmap and not self._last_pixmap.isNull():
                target = area or rect

                # 🔹 margen sutil en todos los tipos (2.5%)
                margin = target.width() * 0.025
                target = target.adjusted(margin, margin, -margin, -margin)

                # 🔹 deformación leve solo en medias
                if getattr(self.pagina, "aviso_half", False):
                    aspect_mode = Qt.IgnoreAspectRatio
                else:
                    aspect_mode = Qt.KeepAspectRatio

                scaled = self._last_pixmap.scaled(
                    int(target.width()),
                    int(target.height()),
                    aspect_mode,
                    Qt.SmoothTransformation
                )

                x = int(target.x() + (target.width() - scaled.width()) / 2)
                y = int(target.y() + (target.height() - scaled.height()) / 2)
                painter.drawPixmap(x, y, scaled)
                _log.debug(f"[DRAW] Aviso real en área {aspect_mode} (P{self.pagina.numero:02d})")
                return

            # --- si no hay imagen: placeholder naranja o gris ---
            gris = QColor("#d9d9d9")
            naranja = QColor("#eb7846")

            # --- Fondo base del marco ---
            painter.fillRect(rect, gris)
            painter.setPen(QPen(Qt.black, 2))
            painter.drawRect(rect)
            painter.setPen(QPen(QColor("#999"), 1, Qt.DashLine))
            painter.drawLine(rect.topLeft(), rect.bottomRight())
            painter.drawLine(rect.topRight(), rect.bottomLeft())

            # --- Si tiene tipo de aviso, resaltar el área ---
            if area is not None:
                painter.fillRect(area, naranja)
                painter.setPen(QPen(Qt.black, 1.2))
                painter.drawRect(area)
                painter.drawText(
                area,
                Qt.AlignCenter,
                "Asigne aviso \n(Clic derecho en página\n -> Avisos -> Asignar aviso)"
                )       


        except Exception as e:
            _log.warning(f"[WARN] paintEvent: {e}")


    # --------------------------------------------------------
    # Doble clic → visor ampliado
    # --------------------------------------------------------
    def mouseDoubleClickEvent(self, event):
        if self._last_pixmap is not None and not self._last_pixmap.isNull():
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Página {self.pagina.numero:02d} - Aviso")
            layout = QVBoxLayout(dlg)
            view = ZoomableGraphicsView(self._last_pixmap, dlg)
            layout.addWidget(view)
            dlg.resize(900, 700)
            dlg.exec_()
        else:
            super().mouseDoubleClickEvent(event)

        # --------------------------------------------------------
    # Menú contextual (clic derecho en toda la maqueta)
    # --------------------------------------------------------
    def contextMenuEvent(self, event):
        """Abre menú contextual al hacer clic derecho en toda la maqueta."""
        if not self.pagina:
            return

        menu = QMenu(self)
        act_clear = QAction("Limpiar aviso", self)
        act_clear.triggered.connect(self._on_clear_aviso)
        menu.addAction(act_clear)
        # --- Estilo visual: fondo celeste claro, texto negro ---
        menu.setStyleSheet("""
        QMenu {
            background-color: #f0f7ff;   /* gris celeste claro */
            color: #000000;              /* texto negro */
            border: 1px solid #b5c9e2;
            padding: 4px;
        }
        QMenu::item {
            padding: 6px 24px 6px 24px;
            background-color: transparent;
        }
        QMenu::item:selected {
            background-color: #cfe5ff;   /* celeste más intenso al hover */
            color: #000000;              /* texto sigue negro */
        }
        QMenu::separator {
            height: 1px;
            background: #b5c9e2;
            margin: 4px 8px 4px 8px;
        }
        """)


        menu.exec_(event.globalPos())

    # --------------------------------------------------------
    # Acción: limpiar aviso completamente
    # --------------------------------------------------------
    def _on_clear_aviso(self):
        """Elimina el archivo físico (si existe) y limpia nombre/pixmap,
        preservando el tipo de aviso en INI y memoria."""
        if not self.pagina:
            return

        numero = self.pagina.numero
        aviso_path = getattr(self.pagina, "aviso_path", None)

        try:
            # 1️⃣ Eliminar archivo físico directamente
            if aviso_path and Path(aviso_path).exists():
                Path(aviso_path).unlink()
                _log.info(f"[DEL] Archivo aviso eliminado: {aviso_path}")

            # 2️⃣ Limpiar nombre y pixmap en memoria (preservar tipo)
            self.pagina.aviso_nombre = ""
            self.pagina.aviso_path = None
            self.pagina.aviso_pixmap = None
            self.pagina.aviso_mtime = None

            # 3️⃣ Actualizar INI: solo limpiar el nombre
            if hasattr(self.controller, "file_service"):
                fs = self.controller.file_service
                fs.set_aviso_nombre(numero, "", by=self.controller.usuario or "")

            # 4️⃣ Refrescar visualmente
            self._last_pixmap = None
            self.update()

            # 5️⃣ Sincronizar MainWindow si existe
            if hasattr(self.controller, "main_window"):
                mw = self.controller.main_window
                mw._update_aviso_nombre(self.pagina)
                if numero in mw.boton_paginas:
                    mw.boton_paginas[numero].update()
                # 🔹 Refrescar maqueta visible si está activa
                if getattr(mw, "maqueta_widget", None):
                    mw.maqueta_widget.set_pagina(self.pagina)
                    mw.maqueta_widget.update()

            _log.info(f"[OK] Aviso limpiado (tipo preservado) en P{numero:02d}")

        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Limpiar aviso", f"Error al limpiar aviso:\n{e}")





    # --------------------------------------------------------
    # Mini-maqueta (para PageButton)
    # --------------------------------------------------------
    @staticmethod
    def draw_static(painter, pagina, rect, controller=None, mostrar_aviso=True):
        """
        Render estático (sin I/O pesado) de la maqueta o aviso.
        Usado por los botones de página.

        mostrar_aviso=False oculta SOLO la previsualización (la imagen del aviso),
        preservando el dibujo de la maqueta (la zona naranja del aviso).
        """
        if not pagina:
            return

        naranja = QColor("#eb7846")

        # === Determinar área del aviso según tipo ===
        area_aviso = None
        if getattr(pagina, "aviso_full", False):
            area_aviso = rect
        elif getattr(pagina, "aviso_half", False):
            # Mitad inferior
            area_aviso = QRectF(
                rect.left(),
                rect.top() + rect.height() / 2,
                rect.width(),
                rect.height() / 2
            )
        elif getattr(pagina, "aviso_footer", False):
            area_aviso = QRectF(
                rect.left(),
                rect.bottom() - rect.height() / 4,
                rect.width(),
                rect.height() / 4
            )
        elif getattr(pagina, "aviso_robapagina", False):
            ancho = rect.width() / 2
            if pagina.numero % 2 == 0:
                area_aviso = QRectF(rect.left(), rect.top(), ancho, rect.height())
            else:
                area_aviso = QRectF(rect.left() + ancho, rect.top(), ancho, rect.height())

        # === Si hay aviso real, dibujarlo ===
        # SOLO si hay un área de aviso (flags activos). Esto evita que un pixmap
        # cacheado de otra edición (flags apagados) se dibuje a página completa.
        pixmap = getattr(pagina, "aviso_pixmap", None)
        if mostrar_aviso and pixmap and not pixmap.isNull() and area_aviso is not None:
            target = area_aviso

            # 🔹 Margen mínimo y uniforme
            margin = target.width() * 0.025
            target = target.adjusted(margin, margin, -margin, -margin)

            # 🔹 Escalado: medias llenan su espacio completo (puede deformar levemente)
            if getattr(pagina, "aviso_half", False):
                aspect_mode = Qt.IgnoreAspectRatio    # ✅ llena completamente la mitad inferior
            else:
                aspect_mode = Qt.KeepAspectRatio

            scaled = pixmap.scaled(
                int(target.width()),
                int(target.height()),
                aspect_mode,
                Qt.SmoothTransformation
            )

            x = int(target.x() + (target.width() - scaled.width()) / 2)
            y = int(target.y() + (target.height() - scaled.height()) / 2)
            painter.drawPixmap(x, y, scaled)
            return

        # === Si no hay imagen pero hay tipo de aviso → pintar área naranja ===
        if area_aviso is not None:
            painter.fillRect(area_aviso, naranja)
            painter.setPen(QPen(Qt.black, 0.1))
            painter.drawRect(area_aviso)





