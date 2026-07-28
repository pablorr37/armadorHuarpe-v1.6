"""
Ventana del editor visual del maquetador (F3 visor + F4 editor). Trabaja
100% en memoria/JSON — no llama a Quark en ningún punto: ni para leer (usa
maquetas_cache.json ya poblado por "Maquetas → Leer maquetas") ni para
aplicar el plan resultante (eso queda pendiente de autorización explícita,
ver docs/maquetador_arquitectura.md).
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction, QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QInputDialog,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QUndoStack, QVBoxLayout,
)

from model.maquetador_state import MaquetadorDocumento
from model.recurso_plan import calcular_diferencias
from ui.maquetador.canvas_view import MaquetadorCanvasView
from ui.maquetador.propiedades_panel import PropiedadesPanelDock
from ui.maquetador.recursos_panel import RecursosPanelDock
from ui.maquetador.undo_commands import (
    ClonarCommand, ClonarGrupoCommand, EliminarCommand, MoverCommand, RedimensionarCommand,
)
from services import maquetador_io


class MaquetadorWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Maquetador — editor visual")
        self.resize(1100, 750)
        self.doc: MaquetadorDocumento | None = None
        self.undo_stack = QUndoStack(self)

        self.canvas = MaquetadorCanvasView(self)
        self.setCentralWidget(self.canvas)

        self.dock_recursos = RecursosPanelDock(self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_recursos)
        self.dock_propiedades = PropiedadesPanelDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_propiedades)

        self._crear_toolbar()
        self._conectar_senales()

    # ── toolbar ──

    def _crear_toolbar(self) -> None:
        act_undo = self.undo_stack.createUndoAction(self, "Deshacer")
        act_undo.setShortcut(QKeySequence.Undo)
        act_redo = self.undo_stack.createRedoAction(self, "Rehacer")
        act_redo.setShortcut(QKeySequence.Redo)
        menu_edicion = self.menuBar().addMenu("Edición")
        menu_edicion.addAction(act_undo)
        menu_edicion.addAction(act_redo)

        tb = self.addToolBar("Maquetador")
        tb.addAction(act_undo)
        tb.addAction(act_redo)
        tb.addSeparator()

        act_abrir = QAction("Abrir desde caché…", self)
        act_abrir.triggered.connect(self._on_abrir_desde_cache)
        tb.addAction(act_abrir)

        act_nueva = QAction("Nueva (lienzo en blanco)…", self)
        act_nueva.triggered.connect(self._on_nueva_en_blanco)
        tb.addAction(act_nueva)

        act_margenes = QAction("Márgenes…", self)
        act_margenes.triggered.connect(self._on_editar_margenes)
        tb.addAction(act_margenes)

        tb.addSeparator()

        act_guardar = QAction("Guardar en el pool…", self)
        act_guardar.triggered.connect(self._on_guardar)
        tb.addAction(act_guardar)

        act_plan = QAction("Ver plan de cambios…", self)
        act_plan.triggered.connect(self._on_ver_plan)
        tb.addAction(act_plan)

        tb.addSeparator()

        self.chk_snap = QCheckBox("Snap 1mm")
        self.chk_snap.toggled.connect(lambda on: self.canvas.set_snap(1.0 if on else None))
        tb.addWidget(self.chk_snap)

    def _conectar_senales(self) -> None:
        self.canvas.signals.recurso_movido.connect(self._on_recurso_movido)
        self.canvas.signals.recurso_redimensionado.connect(self._on_recurso_redimensionado)
        self.canvas.signals.recurso_seleccionado.connect(self._on_recurso_seleccionado)
        self.canvas.signals.recurso_movido_fin.connect(self._on_recurso_movido_fin)
        self.canvas.signals.recurso_redimensionado_fin.connect(self._on_recurso_redimensionado_fin)
        self.canvas.solicitud_clonar.connect(self._on_solicitud_clonar)
        self.canvas.solicitud_clonar_grupo.connect(self._on_solicitud_clonar_grupo)
        self.canvas.solicitud_eliminar_seleccion.connect(self._on_eliminar)

        self.dock_recursos.solicitud_agregar_custom.connect(self._on_agregar_custom)
        self.dock_propiedades.geometria_cambiada.connect(self._on_geometria_editada_a_mano)
        self.dock_propiedades.solicitud_clonar.connect(self._on_clonar_desde_panel)
        self.dock_propiedades.solicitud_eliminar.connect(lambda id_: self._on_eliminar([id_]))

    # ── abrir / nueva ──

    def _on_abrir_desde_cache(self) -> None:
        from services.maqueta_introspect import leer_cache
        stems = sorted(leer_cache().keys())
        if not stems:
            QMessageBox.information(
                self, "Maquetador",
                "No hay ninguna maqueta cacheada todavía. Usá primero "
                "«Maquetas → Leer maquetas (capacidades)…».",
            )
            return
        stem, ok = QInputDialog.getItem(self, "Abrir maqueta", "Maqueta cacheada:", stems, 0, False)
        if not ok:
            return
        self._cargar_stem(stem)

    def _cargar_stem(self, stem: str, pagina: str | None = None) -> None:
        try:
            doc = maquetador_io.cargar_desde_cache(stem, pagina=pagina)
        except maquetador_io.AmbiguedadPagina as e:
            elegida, ok = QInputDialog.getItem(
                self, "Elegir escenario",
                "Esta maqueta tiene más de una variante de escenario editorial "
                "(no son recursos simultáneos, son alternativas — ej. 1 noticia vs 2):",
                e.paginas, 0, False,
            )
            if not ok:
                return
            self._cargar_stem(stem, pagina=elegida)
            return
        if doc is None:
            QMessageBox.warning(self, "Maquetador", f"No se pudo leer la maqueta '{stem}' de la caché.")
            return
        self.doc = doc
        self.canvas.cargar_documento(doc)
        self.dock_recursos.sincronizar_disponibilidad(doc.roles_con_repuesto())
        self.dock_propiedades.mostrar_recurso(None)

    def _on_nueva_en_blanco(self) -> None:
        nombre, ok = QInputDialog.getText(self, "Maqueta en blanco", "Nombre:")
        if not ok or not nombre.strip():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Dimensiones del lienzo")
        form = QFormLayout(dlg)
        spin_w = QDoubleSpinBox(); spin_w.setRange(10, 2000); spin_w.setValue(260); spin_w.setSuffix(" mm")
        spin_h = QDoubleSpinBox(); spin_h.setRange(10, 2000); spin_h.setValue(370); spin_h.setSuffix(" mm")
        form.addRow("Ancho", spin_w)
        form.addRow("Alto", spin_h)
        btn = QPushButton("Crear")
        btn.clicked.connect(dlg.accept)
        form.addRow(btn)
        if dlg.exec_() != QDialog.Accepted:
            return
        QMessageBox.information(
            self, "Maquetador",
            "Una maqueta en blanco solo define el lienzo: QuarkXPress no puede crear "
            "cajas desde cero, así que no vas a poder materializar recursos nuevos acá "
            "— usala para planificar el diseño general.",
        )
        self.doc = maquetador_io.cargar_en_blanco(nombre.strip(), spin_w.value(), spin_h.value())
        self.canvas.cargar_documento(self.doc)
        self.dock_recursos.sincronizar_disponibilidad(set())
        self.dock_propiedades.mostrar_recurso(None)

    def _on_editar_margenes(self) -> None:
        if self.doc is None:
            QMessageBox.information(self, "Maquetador", "No hay ninguna maqueta cargada.")
            return
        mq = self.doc.maqueta
        dlg = QDialog(self)
        dlg.setWindowTitle("Márgenes de página")
        form = QFormLayout(dlg)
        spins = {}
        for campo, etiqueta, valor in (
            ("margin_top_mm", "Superior", mq.margin_top_mm),
            ("margin_bottom_mm", "Inferior", mq.margin_bottom_mm),
            ("margin_left_mm", "Izquierdo", mq.margin_left_mm),
            ("margin_right_mm", "Derecho", mq.margin_right_mm),
        ):
            s = QDoubleSpinBox(); s.setRange(0.0, 500.0); s.setValue(valor); s.setSuffix(" mm")
            form.addRow(etiqueta, s)
            spins[campo] = s
        btn = QPushButton("Aplicar")
        btn.clicked.connect(dlg.accept)
        form.addRow(btn)
        if dlg.exec_() != QDialog.Accepted:
            return
        for campo, spin in spins.items():
            setattr(mq, campo, spin.value())
        self.canvas.actualizar_margenes(self.doc)

    # ── edición: eventos del canvas ──

    def _on_recurso_movido(self, id_: str, left_mm: float, top_mm: float) -> None:
        """En vivo, en cada micro-paso del arrastre — no pasa por el
        undo_stack (eso lo hace _on_recurso_movido_fin, una sola vez al
        soltar). Si el recurso es miembro de un grupo rígido, doc.mover() ya
        propaga el delta a los hermanos; acá solo hace falta refrescarlos."""
        if self.doc is None or id_ not in self.doc.recursos:
            return
        self.doc.mover(id_, left_mm, top_mm)
        recurso = self.doc.recursos[id_]
        if recurso.grupo_id:
            for miembro in self.doc.miembros_del_grupo(recurso.grupo_id):
                if miembro.id != id_:
                    self.canvas.refrescar_item(miembro.id)

    def _on_recurso_redimensionado(self, id_: str, width_mm: float, height_mm: float) -> None:
        if self.doc is None or id_ not in self.doc.recursos:
            return
        self.doc.redimensionar(id_, width_mm, height_mm)
        self.canvas.refrescar_item(id_)
        if self.dock_propiedades.recurso_actual_id == id_:
            self.dock_propiedades.mostrar_recurso(self.doc.recursos[id_])

    def _on_recurso_seleccionado(self, id_) -> None:
        recurso = self.doc.recursos.get(id_) if (self.doc and id_) else None
        self.dock_propiedades.mostrar_recurso(recurso)

    def _on_recurso_movido_fin(self, id_: str, left0: float, top0: float, left1: float, top1: float) -> None:
        if self.doc is None:
            return
        self.undo_stack.push(MoverCommand(self.doc, self.canvas, id_, left0, top0, left1, top1))

    def _on_recurso_redimensionado_fin(self, id_: str, geom0: tuple, geom1: tuple) -> None:
        if self.doc is None:
            return
        self.undo_stack.push(RedimensionarCommand(self.doc, self.canvas, id_, geom0, geom1))

    def _on_solicitud_clonar(self, rol: str, left_mm: float, top_mm: float) -> None:
        if self.doc is None:
            return
        if rol not in self.doc.roles_con_repuesto():
            QMessageBox.warning(
                self, "Maquetador",
                f"No hay ninguna caja existente de rol '{rol}' en esta maqueta para clonar "
                "— QuarkXPress no puede crear cajas nuevas desde cero.",
            )
            return
        # Precondición ya validada arriba (roles_con_repuesto) — clonar_recurso()
        # no debería lanzar ValueError acá. QUndoCommand.redo() es un método
        # virtual invocado desde C++ (QUndoStack.push); una excepción Python
        # ahí NO se propaga como excepción normal a este try/except, así que
        # la validación real tiene que pasar ANTES de empujar el comando.
        self.undo_stack.push(ClonarCommand(self.doc, self.canvas, rol, None, left_mm, top_mm))

    def _on_solicitud_clonar_grupo(self, rol_grupo: str, left_mm: float, top_mm: float) -> None:
        if self.doc is None:
            return
        if rol_grupo not in self.doc.roles_con_repuesto():
            QMessageBox.warning(
                self, "Maquetador",
                f"No hay ningún repuesto del grupo '{rol_grupo}' en esta maqueta para clonar "
                "— QuarkXPress no puede crear cajas nuevas desde cero.",
            )
            return
        self.undo_stack.push(ClonarGrupoCommand(self.doc, self.canvas, rol_grupo, left_mm, top_mm))

    # ── edición: eventos de los paneles ──

    def _on_agregar_custom(self, nombre: str, rol: str, tipo: str) -> None:
        if self.doc is None:
            return
        self.doc.agregar_recurso_custom(nombre, rol, tipo)

    def _on_geometria_editada_a_mano(self, id_: str, left: float, top: float, width: float, height: float) -> None:
        if self.doc is None or id_ not in self.doc.recursos:
            return
        r = self.doc.recursos[id_]
        geom0 = (r.left_mm, r.top_mm, r.width_mm, r.height_mm)
        geom1 = (left, top, width, height)
        self.undo_stack.push(RedimensionarCommand(self.doc, self.canvas, id_, geom0, geom1))
        self.dock_propiedades.mostrar_recurso(self.doc.recursos[id_])

    def _on_clonar_desde_panel(self, id_: str) -> None:
        if self.doc is None or id_ not in self.doc.recursos:
            return
        origen = self.doc.recursos[id_]
        self.undo_stack.push(ClonarCommand(
            self.doc, self.canvas, origen.rol, id_,
            origen.left_mm + 10.0, origen.top_mm + 10.0,
        ))

    def _on_eliminar(self, ids: list[str]) -> None:
        if self.doc is None or not ids:
            return
        self.undo_stack.push(EliminarCommand(self.doc, self.canvas, self.dock_propiedades, ids))

    # ── guardar / plan ──

    def _on_guardar(self) -> None:
        if self.doc is None:
            QMessageBox.information(self, "Maquetador", "No hay ninguna maqueta cargada.")
            return
        nombre, ok = QInputDialog.getText(
            self, "Guardar en el pool", "Nombre de la maqueta (stem):",
            text=self.doc.maqueta.nombre or "",
        )
        if not ok or not nombre.strip():
            return
        ruta = maquetador_io.guardar_como_maqueta(self.doc, nombre.strip())
        QMessageBox.information(
            self, "Maquetador",
            f"Maqueta '{nombre.strip()}' guardada en el pool ({ruta}).",
        )

    def _on_ver_plan(self) -> None:
        if self.doc is None:
            QMessageBox.information(self, "Maquetador", "No hay ninguna maqueta cargada.")
            return
        objetivos, eliminar_ids = self.doc.a_objetivos()
        plan = calcular_diferencias(self.doc.manifest_original, objetivos, eliminar_ids)

        dlg = QDialog(self)
        dlg.setWindowTitle("Plan de diferencias (preview — no se aplica a Quark)")
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        texto = QPlainTextEdit()
        texto.setReadOnly(True)
        lineas = [f"{len(plan.operaciones)} operación(es):"]
        for op in plan.operaciones:
            lineas.append(f"  • {op.tipo}: {op.to_dict()}")
        if plan.errores:
            lineas.append("")
            lineas.append("Errores:")
            for err in plan.errores:
                lineas.append(f"  ⚠ {err}")
        texto.setPlainText("\n".join(lineas))
        lay.addWidget(texto)
        dlg.exec_()
