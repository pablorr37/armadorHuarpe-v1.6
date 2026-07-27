"""
Items gráficos del editor visual del maquetador. La QGraphicsScene que los
contiene vive EN MM (no píxeles): cada RecursoItem se posiciona con
setPos(left_mm, top_mm) y su rect() está en mm — el "zoom" es pura
transformación de la QGraphicsView (ver canvas_view.py), nunca se
recalculan geometrías en mm por el zoom.

QGraphicsItem no es QObject y no puede emitir señales Qt directamente — todos
los items de una escena comparten una única instancia de CanvasSignals.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPen
from PyQt5.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsSimpleTextItem,
)

from model.maquetador_state import RecursoEditable

_COLOR_EN_USO = QColor(30, 41, 59, 170)        # #1e293b, paleta de MaquetaWidget
_COLOR_PASTEBOARD = QColor(148, 163, 184, 60)  # gris translúcido
_COLOR_ELIMINAR = QColor(220, 38, 38, 90)      # rojo translúcido
_COLOR_SELECCION = QColor(59, 130, 246)        # borde azul de selección
_COLOR_TEXTO = QColor(240, 240, 240)

_CORNERS = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
_MIN_SIZE_MM = 2.0


class CanvasSignals(QObject):
    """Bus de señales compartido por todos los RecursoItem de una escena."""
    recurso_movido = pyqtSignal(str, float, float)          # id, left_mm, top_mm
    recurso_redimensionado = pyqtSignal(str, float, float)  # id, width_mm, height_mm
    recurso_seleccionado = pyqtSignal(object)                # id (str) | None


class PasteboardBoundaryItem(QGraphicsRectItem):
    """Rectángulo decorativo (no seleccionable) que delimita la zona de
    repuestos alrededor del área de página."""

    def __init__(self, rect: QRectF):
        super().__init__(rect)
        self.setPen(QPen(QColor(148, 163, 184, 140), 0, Qt.DashLine))
        self.setBrush(QBrush(Qt.NoBrush))
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setZValue(-10)


class ResizeHandleItem(QGraphicsRectItem):
    """Handle de redimensión — hijo de un RecursoItem, tamaño constante en
    píxeles de pantalla (ItemIgnoresTransformations) para que sea manejable
    en cualquier nivel de zoom pese a que la escena esté en mm."""

    SIZE_PX = 7

    def __init__(self, parent_item: "RecursoItem", corner: str):
        super().__init__(parent_item)
        self._corner = corner
        self._dragging = False
        self._start_scene = None
        self._start_geom = None
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setRect(-self.SIZE_PX / 2, -self.SIZE_PX / 2, self.SIZE_PX, self.SIZE_PX)
        self.setBrush(QBrush(_COLOR_SELECCION))
        self.setPen(QPen(Qt.white, 1))
        self.setZValue(10)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        cursors = {
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
        }
        self.setCursor(cursors[corner])

    def reposicionar(self) -> None:
        r: QRectF = self.parentItem().rect()
        xs = {"l": r.left(), "tl": r.left(), "bl": r.left(),
              "t": r.center().x(), "b": r.center().x(),
              "r": r.right(), "tr": r.right(), "br": r.right()}
        ys = {"t": r.top(), "tl": r.top(), "tr": r.top(),
              "l": r.center().y(), "r": r.center().y(),
              "b": r.bottom(), "bl": r.bottom(), "br": r.bottom()}
        self.setPos(xs[self._corner], ys[self._corner])

    def mousePressEvent(self, event):
        self._dragging = True
        self._start_scene = event.scenePos()
        item = self.parentItem()
        self._start_geom = (item.pos().x(), item.pos().y(), item.rect().width(), item.rect().height())
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        dx = event.scenePos().x() - self._start_scene.x()
        dy = event.scenePos().y() - self._start_scene.y()
        left0, top0, w0, h0 = self._start_geom
        c = self._corner
        left, top, w, h = left0, top0, w0, h0
        if c in ("tl", "l", "bl"):
            left = left0 + dx
            w = w0 - dx
        if c in ("tr", "r", "br"):
            w = w0 + dx
        if c in ("tl", "t", "tr"):
            top = top0 + dy
            h = h0 - dy
        if c in ("bl", "b", "br"):
            h = h0 + dy
        if w < _MIN_SIZE_MM:
            if c in ("tl", "l", "bl"):
                left = left0 + (w0 - _MIN_SIZE_MM)
            w = _MIN_SIZE_MM
        if h < _MIN_SIZE_MM:
            if c in ("tl", "t", "tr"):
                top = top0 + (h0 - _MIN_SIZE_MM)
            h = _MIN_SIZE_MM
        self.parentItem().aplicar_geometria(left, top, w, h)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()


class RecursoItem(QGraphicsRectItem):
    """Refleja UN RecursoEditable en el canvas. Toda la lógica de negocio
    (clonado, límites) vive en MaquetadorDocumento — este item solo dibuja y
    traduce interacción del mouse a mm."""

    def __init__(self, recurso: RecursoEditable, signals: CanvasSignals):
        super().__init__(0, 0, max(recurso.width_mm, 0.1), max(recurso.height_mm, 0.1))
        self.recurso_id = recurso.id
        self._signals = signals
        self._handles: list[ResizeHandleItem] = []
        self.snap_mm: float | None = None

        self.setPos(recurso.left_mm, recurso.top_mm)
        self.setFlags(
            QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self._label = QGraphicsSimpleTextItem(self)
        self._label.setBrush(QBrush(_COLOR_TEXTO))
        self._label.setPos(1.0, 1.0)
        self._label.setFlag(QGraphicsItem.ItemIgnoresTransformations)

        self.actualizar_estilo(recurso)

    # ── estilo / etiqueta ──

    def actualizar_estilo(self, recurso: RecursoEditable) -> None:
        if recurso.marcado_eliminar:
            self.setBrush(QBrush(_COLOR_ELIMINAR))
            self.setPen(QPen(QColor(220, 38, 38), 1, Qt.DashLine))
        elif recurso.en_pasteboard:
            self.setBrush(QBrush(_COLOR_PASTEBOARD))
            self.setPen(QPen(QColor(148, 163, 184), 1, Qt.DashLine))
        else:
            self.setBrush(QBrush(_COLOR_EN_USO))
            self.setPen(QPen(QColor(203, 213, 225), 1))

        texto = recurso.rol or recurso.id
        if recurso.tipo == "text" and recurso.capacidad:
            texto += f"\n{recurso.capacidad} car."
        tachado = " (eliminar)" if recurso.marcado_eliminar else ""
        self._label.setText(texto + tachado)

    def sync_geometria(self, recurso: RecursoEditable) -> None:
        """Refleja en el item una geometría cambiada externamente (p. ej. el
        panel de propiedades editó los mm a mano)."""
        self.setRect(0, 0, max(recurso.width_mm, 0.1), max(recurso.height_mm, 0.1))
        self.setPos(recurso.left_mm, recurso.top_mm)
        for h in self._handles:
            h.reposicionar()

    # ── handles de redimensión ──

    def _crear_handles(self) -> None:
        if self._handles:
            return
        self._handles = [ResizeHandleItem(self, c) for c in _CORNERS]
        for h in self._handles:
            h.reposicionar()

    def _quitar_handles(self) -> None:
        for h in self._handles:
            if h.scene():
                h.scene().removeItem(h)
        self._handles = []

    def aplicar_geometria(self, left_mm: float, top_mm: float, width_mm: float, height_mm: float) -> None:
        """Llamado por un ResizeHandleItem hijo mientras se arrastra."""
        self.setRect(0, 0, width_mm, height_mm)
        self.setPos(left_mm, top_mm)
        for h in self._handles:
            h.reposicionar()
        self._signals.recurso_movido.emit(self.recurso_id, left_mm, top_mm)
        self._signals.recurso_redimensionado.emit(self.recurso_id, width_mm, height_mm)

    # ── mouse / selección / mover ──

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.snap_mm:
            grid = self.snap_mm
            x = round(value.x() / grid) * grid
            y = round(value.y() / grid) * grid
            return type(value)(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._signals.recurso_movido.emit(self.recurso_id, value.x(), value.y())
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            if value:
                self._crear_handles()
                self._signals.recurso_seleccionado.emit(self.recurso_id)
            else:
                self._quitar_handles()
                self._signals.recurso_seleccionado.emit(None)
        return super().itemChange(change, value)
