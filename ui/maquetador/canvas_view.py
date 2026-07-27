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


class MaquetadorCanvasView(QGraphicsView):
    solicitud_clonar = pyqtSignal(str, float, float)  # rol, left_mm, top_mm (drop del panel)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setAcceptDrops(True)
        self._scale_factor = 1.15
        self.signals = CanvasSignals(self)
        self.doc: MaquetadorDocumento | None = None
        self._items: dict[str, RecursoItem] = {}
        self._snap_mm: float | None = None

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

        for recurso in doc.recursos.values():
            self._agregar_item(recurso)

        scene.setSceneRect(-m - 5, -m - 5, ancho + 2 * m + 10, alto + 2 * m + 10)
        self.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

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
        self.solicitud_clonar.emit(rol, pos_escena.x(), pos_escena.y())
        event.acceptProposedAction()
