"""
Canvas central del editor visual del maquetador — QGraphicsView/QGraphicsScene
en mm (mismo patrón de zoom que ZoomableGraphicsView de ui/maqueta_widget.py,
pero con items movibles/redimensionables en vez de una imagen estática).
"""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from model.maquetador_state import MaquetadorDocumento
from ui.maquetador.recurso_item import CanvasSignals, PasteboardBoundaryItem, RecursoItem

_PASTEBOARD_MARGIN_MM = 20.0
_COLOR_MARGEN = QColor(59, 130, 246, 160)  # azul — distingue el margen del pasteboard (gris)


class MaquetadorCanvasView(QGraphicsView):
    solicitud_clonar = pyqtSignal(str, float, float)        # rol, left_mm, top_mm (drop del panel)
    solicitud_clonar_grupo = pyqtSignal(str, float, float)  # rol_grupo, left_mm, top_mm (drop de un recurso-grupo)
    solicitud_eliminar_seleccion = pyqtSignal(list)         # ids seleccionados (tecla Supr/Backspace)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._scale_factor = 1.15
        self.signals = CanvasSignals(self)
        self.doc: MaquetadorDocumento | None = None
        self._items: dict[str, RecursoItem] = {}
        self._snap_mm: float | None = None
        self._margen_item: PasteboardBoundaryItem | None = None

    # ── zoom (Ctrl+rueda, mismo patrón que ZoomableGraphicsView) ──

    def wheelEvent(self, event):
        if QApplication.keyboardModifiers() == Qt.ControlModifier:
            zoom = self._scale_factor if event.angleDelta().y() > 0 else 1 / self._scale_factor
            self.scale(zoom, zoom)
        else:
            super().wheelEvent(event)

    # ── snap ──

    def set_snap(self, grid_mm: float | None) -> None:
        self._snap_mm = grid_mm
        for item in self._items.values():
            item.snap_mm = grid_mm

    # ── carga del documento ──

    def cargar_documento(self, doc: MaquetadorDocumento) -> None:
        self.doc = doc
        scene = self.scene()
        scene.clear()
        self._items.clear()

        ancho = doc.maqueta.canvas_width_mm or 200.0
        alto = doc.maqueta.canvas_height_mm or 300.0
        pagina = QGraphicsRectItem(0, 0, ancho, alto)
        pagina.setBrush(QBrush(QColor(255, 255, 255)))
        pagina.setPen(QPen(QColor(30, 41, 59), 0.3))
        pagina.setZValue(-20)
        scene.addItem(pagina)

        m = _PASTEBOARD_MARGIN_MM
        pasteboard = PasteboardBoundaryItem(QRectF(-m, -m, ancho + 2 * m, alto + 2 * m))
        scene.addItem(pasteboard)

        self._margen_item = PasteboardBoundaryItem(self._rect_margen(doc), _COLOR_MARGEN)
        scene.addItem(self._margen_item)

        for recurso in doc.recursos.values():
            self._agregar_item(recurso)

        scene.setSceneRect(-m - 5, -m - 5, ancho + 2 * m + 10, alto + 2 * m + 10)
        self.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

    def _rect_margen(self, doc: MaquetadorDocumento) -> QRectF:
        mq = doc.maqueta
        ancho, alto = mq.canvas_width_mm or 200.0, mq.canvas_height_mm or 300.0
        left, top = mq.margin_left_mm, mq.margin_top_mm
        width = max(0.0, ancho - mq.margin_left_mm - mq.margin_right_mm)
        height = max(0.0, alto - mq.margin_top_mm - mq.margin_bottom_mm)
        return QRectF(left, top, width, height)

    def actualizar_margenes(self, doc: MaquetadorDocumento) -> None:
        """Reposiciona el rect guía de márgenes sin recargar toda la escena
        (evita perder selección/estado de los RecursoItem ya creados)."""
        if self._margen_item is None or self._margen_item.scene() is None:
            self._margen_item = PasteboardBoundaryItem(self._rect_margen(doc), _COLOR_MARGEN)
            self.scene().addItem(self._margen_item)
        else:
            self._margen_item.setRect(self._rect_margen(doc))

    def _agregar_item(self, recurso) -> RecursoItem:
        item = RecursoItem(recurso, self.signals)
        item.snap_mm = self._snap_mm
        self.scene().addItem(item)
        self._items[recurso.id] = item
        return item

    # ── refrescos tras una edición del documento ──

    def agregar_recurso_nuevo(self, recurso) -> None:
        self._agregar_item(recurso)

    def refrescar_item(self, id_: str) -> None:
        if self.doc is None:
            return
        recurso = self.doc.recursos.get(id_)
        item = self._items.get(id_)
        if recurso is None or item is None:
            return
        item.sync_geometria(recurso)
        item.actualizar_estilo(recurso)

    def refrescar_todos(self) -> None:
        for id_ in list(self._items):
            self.refrescar_item(id_)

    def quitar_item(self, id_: str) -> None:
        item = self._items.pop(id_, None)
        if item is not None and item.scene():
            item.scene().removeItem(item)

    # ── teclado: Supr/Backspace elimina la selección ──

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            ids = [it.recurso_id for it in self.scene().selectedItems() if isinstance(it, RecursoItem)]
            if ids:
                self.solicitud_eliminar_seleccion.emit(ids)
                return
        super().keyPressEvent(event)

    # ── drag&drop desde el panel de recursos ──

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-armadorhuarpe-rol"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-armadorhuarpe-rol"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasFormat("application/x-armadorhuarpe-rol"):
            super().dropEvent(event)
            return
        rol = bytes(mime.data("application/x-armadorhuarpe-rol")).decode("utf-8")
        pos_escena = self.mapToScene(event.pos())
        from services.maquetador_nomenclatura import ROLES_GRUPO
        if rol in ROLES_GRUPO:
            self.solicitud_clonar_grupo.emit(rol, pos_escena.x(), pos_escena.y())
        else:
            self.solicitud_clonar.emit(rol, pos_escena.x(), pos_escena.y())
        event.acceptProposedAction()
