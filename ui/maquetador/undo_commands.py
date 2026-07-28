"""
Comandos de undo/redo del editor visual del maquetador — primera vez que se
usa QUndoStack/QUndoCommand en el repo (el patrón custom de listas de
ui/widgets/story_panel.py es para edición de texto carácter por carácter, no
para operaciones estructuradas mover/redimensionar/clonar/eliminar). Da además
el texto "Deshacer: mover foto_2" gratis vía createUndoAction/createRedoAction.

Todos los comandos operan sobre `doc` (MaquetadorDocumento) + `canvas`
(MaquetadorCanvasView) — nunca tocan un QGraphicsItem directamente, para que
el modelo en memoria sea siempre la fuente de verdad.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QUndoCommand

from model.maquetador_state import MaquetadorDocumento, RecursoEditable
from ui.maquetador.canvas_view import MaquetadorCanvasView


def _refrescar_con_grupo(doc: MaquetadorDocumento, canvas: MaquetadorCanvasView, id_: str) -> None:
    """Refresca el item movido/redimensionado y, si es miembro de un grupo
    rígido (textual/dato/numero/qr), también a sus hermanos."""
    canvas.refrescar_item(id_)
    recurso = doc.recursos.get(id_)
    if recurso and recurso.grupo_id:
        for miembro in doc.miembros_del_grupo(recurso.grupo_id):
            if miembro.id != id_:
                canvas.refrescar_item(miembro.id)


class MoverCommand(QUndoCommand):
    def __init__(self, doc: MaquetadorDocumento, canvas: MaquetadorCanvasView,
                 id_: str, left0: float, top0: float, left1: float, top1: float):
        super().__init__(f"mover {id_}")
        self._doc, self._canvas, self._id = doc, canvas, id_
        self._pos0, self._pos1 = (left0, top0), (left1, top1)

    def redo(self):
        self._doc.mover(self._id, *self._pos1)
        _refrescar_con_grupo(self._doc, self._canvas, self._id)

    def undo(self):
        self._doc.mover(self._id, *self._pos0)
        _refrescar_con_grupo(self._doc, self._canvas, self._id)


class RedimensionarCommand(QUndoCommand):
    """geom0/geom1 son tuplas (left_mm, top_mm, width_mm, height_mm) — el
    handle tl/t/l también desplaza la posición, no solo el tamaño."""

    def __init__(self, doc: MaquetadorDocumento, canvas: MaquetadorCanvasView,
                 id_: str, geom0: tuple, geom1: tuple):
        super().__init__(f"redimensionar {id_}")
        self._doc, self._canvas, self._id = doc, canvas, id_
        self._geom0, self._geom1 = geom0, geom1

    def _aplicar(self, geom: tuple):
        left, top, width, height = geom
        self._doc.mover(self._id, left, top)
        self._doc.redimensionar(self._id, width, height)
        _refrescar_con_grupo(self._doc, self._canvas, self._id)

    def redo(self):
        self._aplicar(self._geom1)

    def undo(self):
        self._aplicar(self._geom0)


class ClonarCommand(QUndoCommand):
    """redo() clona la PRIMERA vez y guarda el RecursoEditable resultante;
    en un redo posterior (tras undo) reinserta esa misma copia en vez de
    clonar de nuevo, para no generar ids/box-names distintos cada vez."""

    def __init__(self, doc: MaquetadorDocumento, canvas: MaquetadorCanvasView,
                 rol: str, desde_id: str | None, left_mm: float, top_mm: float):
        super().__init__(f"clonar {rol}")
        self._doc, self._canvas = doc, canvas
        self._rol, self._desde_id = rol, desde_id
        self._left_mm, self._top_mm = left_mm, top_mm
        self._recurso: RecursoEditable | None = None

    def redo(self):
        if self._recurso is None:
            nuevo = self._doc.clonar_recurso(self._rol, self._desde_id)
            self._doc.mover(nuevo.id, self._left_mm, self._top_mm)
            self._recurso = nuevo
        else:
            self._doc.restaurar_recurso(self._recurso)
        self._canvas.agregar_recurso_nuevo(self._recurso)
        self._canvas.refrescar_item(self._recurso.id)

    def undo(self):
        self._doc.eliminar_recurso(self._recurso.id)
        self._canvas.quitar_item(self._recurso.id)


class ClonarGrupoCommand(QUndoCommand):
    """Análogo a ClonarCommand pero para un recurso-grupo rígido completo
    (varios RecursoEditable creados a la vez, ver clonar_recurso_compuesto)."""

    def __init__(self, doc: MaquetadorDocumento, canvas: MaquetadorCanvasView,
                 rol_grupo: str, left_mm: float, top_mm: float):
        super().__init__(f"clonar grupo {rol_grupo}")
        self._doc, self._canvas = doc, canvas
        self._rol_grupo = rol_grupo
        self._left_mm, self._top_mm = left_mm, top_mm
        self._recursos: list[RecursoEditable] | None = None

    def redo(self):
        if self._recursos is None:
            nuevos = self._doc.clonar_recurso_compuesto(self._rol_grupo)
            self._doc.mover(nuevos[0].id, self._left_mm, self._top_mm)
            self._recursos = nuevos
        else:
            for r in self._recursos:
                self._doc.restaurar_recurso(r)
        for r in self._recursos:
            self._canvas.agregar_recurso_nuevo(r)
            self._canvas.refrescar_item(r.id)

    def undo(self):
        for r in self._recursos:
            self._doc.eliminar_recurso(r.id)
            self._canvas.quitar_item(r.id)


class EliminarCommand(QUndoCommand):
    """Acepta una lista de ids para que Supr sobre una selección múltiple sea
    UN solo undo. panel_propiedades se limpia si mostraba alguno de los ids
    eliminados (evita quedar mostrando un recurso que ya no existe)."""

    def __init__(self, doc: MaquetadorDocumento, canvas: MaquetadorCanvasView,
                 panel_propiedades, ids: list[str]):
        super().__init__("eliminar recurso" if len(ids) == 1 else f"eliminar {len(ids)} recursos")
        self._doc, self._canvas, self._panel = doc, canvas, panel_propiedades
        self._ids = list(ids)
        self._borrados: dict[str, RecursoEditable] = {}

    def redo(self):
        for id_ in self._ids:
            if id_ not in self._doc.recursos:
                continue
            self._borrados[id_] = self._doc.eliminar_recurso(id_)
            self._canvas.quitar_item(id_)
        if self._panel.recurso_actual_id in self._ids:
            self._panel.mostrar_recurso(None)

    def undo(self):
        for id_, recurso in self._borrados.items():
            self._doc.restaurar_recurso(recurso)
            self._canvas.agregar_recurso_nuevo(recurso)
            self._canvas.refrescar_item(id_)
