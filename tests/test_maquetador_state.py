"""
Tests headless de model/maquetador_state.py contra un manifest de fixture
(sin depender de maquetas_cache.json real ni de Quark). Requiere una
QApplication mínima solo porque estimar_capacidad() usa QFontMetricsF.
"""
import unittest

from PyQt5.QtWidgets import QApplication

from model.maqueta_model import Maqueta
from model.maquetador_state import MaquetadorDocumento, es_pasteboard
from model.recurso_plan import calcular_diferencias
from services.maquetador_nomenclatura import formatear_box_name, parse_box_name

_app = QApplication.instance() or QApplication([])


def _manifest_fixture() -> dict:
    return {
        "maqueta": "test",
        "canvas": {"width_mm": 260.0, "height_mm": 370.0},
        "recursos": [
            {
                "id": "titulo", "tipo": "text", "box_name": "Titulo1",
                "left_mm": 10.0, "top_mm": 10.0, "width_mm": 200.0, "height_mm": 30.0,
                "page": "1", "rol": "titulo", "capacidad": 80, "clonable_desde": "Titulo1",
            },
            {
                "id": "cuerpo", "tipo": "text", "box_name": "Cuerpo1",
                "left_mm": 10.0, "top_mm": 45.0, "width_mm": 200.0, "height_mm": 150.0,
                "page": "1", "rol": "cuerpo", "capacidad": 2000, "clonable_desde": "Cuerpo1",
            },
            {
                "id": "foto_secundaria_repuesto", "tipo": "picture", "box_name": "FotoRepuesto1",
                "left_mm": 300.0, "top_mm": 10.0, "width_mm": 80.0, "height_mm": 60.0,
                "page": "1*", "rol": "foto_secundaria", "capacidad": None,
                "clonable_desde": "FotoRepuesto1",
            },
        ],
    }


def _doc() -> MaquetadorDocumento:
    manifest = _manifest_fixture()
    maqueta = Maqueta(nombre="test", canvas_width_mm=260.0, canvas_height_mm=370.0, origen="real")
    return MaquetadorDocumento.desde_manifest(maqueta, manifest)


def _manifest_fixture_con_grupo_textual() -> dict:
    """Repuestos textual_texto/graf/contenedor/nombrecargo parqueados en el
    pasteboard, como los tendría maquetas/listas/vaciaGenerica_test.qxp."""
    base = _manifest_fixture()
    offsets = {"texto": (0.0, 0.0), "graf": (0.0, 20.0), "contenedor": (-2.0, -2.0), "nombrecargo": (0.0, 40.0)}
    for campo, (dx, dy) in offsets.items():
        base["recursos"].append({
            "id": f"textual_{campo}", "tipo": "text", "box_name": f"textual_{campo}",
            "left_mm": 200.0 + dx, "top_mm": 100.0 + dy, "width_mm": 60.0, "height_mm": 15.0,
            "page": "1*", "rol": "textual", "capacidad": 40, "clonable_desde": f"textual_{campo}",
            "grupo_id": "textual_pasteboard", "grupo_campo": campo,
        })
    return base


def _doc_con_grupo_textual() -> MaquetadorDocumento:
    manifest = _manifest_fixture_con_grupo_textual()
    maqueta = Maqueta(nombre="test", canvas_width_mm=260.0, canvas_height_mm=370.0, origen="real")
    return MaquetadorDocumento.desde_manifest(maqueta, manifest)


class TestPasteboard(unittest.TestCase):
    def test_clasificacion_pasteboard(self):
        doc = _doc()
        self.assertFalse(doc.recursos["titulo"].en_pasteboard)
        self.assertFalse(doc.recursos["cuerpo"].en_pasteboard)
        self.assertTrue(doc.recursos["foto_secundaria_repuesto"].en_pasteboard)
        self.assertTrue(es_pasteboard("1*"))
        self.assertTrue(es_pasteboard("1**"))
        self.assertFalse(es_pasteboard("1"))
        self.assertFalse(es_pasteboard(None))

    def test_clonar_desde_pasteboard_no_modifica_el_original(self):
        doc = _doc()
        original = doc.recursos["foto_secundaria_repuesto"]
        left0, top0 = original.left_mm, original.top_mm

        nuevo = doc.clonar_recurso(rol="foto_secundaria", desde_id="foto_secundaria_repuesto")

        self.assertEqual(original.left_mm, left0)
        self.assertEqual(original.top_mm, top0)
        self.assertTrue(original.en_pasteboard)
        self.assertTrue(nuevo.es_nuevo)
        self.assertFalse(nuevo.en_pasteboard)
        self.assertIsNone(nuevo.box_name)
        self.assertEqual(nuevo.origen_clon, "FotoRepuesto1")


class TestEdicion(unittest.TestCase):
    def test_mover_y_redimensionar(self):
        doc = _doc()
        doc.mover("titulo", 20.0, 20.0)
        doc.redimensionar("titulo", 100.0, 40.0)
        r = doc.recursos["titulo"]
        self.assertEqual((r.left_mm, r.top_mm, r.width_mm, r.height_mm), (20.0, 20.0, 100.0, 40.0))

    def test_eliminar_es_explicito(self):
        """No mencionar un recurso en los objetivos NO debe borrarlo — el
        borrado (ahora inferido de manifest_original - recursos actuales,
        sin ningún flag) solo ocurre si realmente se eliminó."""
        doc = _doc()
        objetivos, eliminar_ids = doc.a_objetivos()
        self.assertEqual(eliminar_ids, set())
        self.assertEqual({o.id for o in objetivos}, {"titulo", "cuerpo", "foto_secundaria_repuesto"})

        doc.eliminar_recurso("titulo")
        objetivos, eliminar_ids = doc.a_objetivos()
        self.assertEqual(eliminar_ids, {"titulo"})
        self.assertEqual({o.id for o in objetivos}, {"cuerpo", "foto_secundaria_repuesto"})

    def test_eliminar_restaurar_undo(self):
        """eliminar_recurso()/restaurar_recurso() son la pareja que usan los
        QUndoCommand — restaurar debe dejar el documento exactamente igual."""
        doc = _doc()
        quitado = doc.eliminar_recurso("titulo")
        self.assertNotIn("titulo", doc.recursos)
        doc.restaurar_recurso(quitado)
        self.assertIn("titulo", doc.recursos)
        self.assertIs(doc.recursos["titulo"], quitado)

    def test_clon_eliminado_no_pide_borrado_en_quark(self):
        """Un recurso que nunca se materializó (es_nuevo, box_name=None) no
        necesita una operación 'eliminar' en Quark si se descarta antes de
        guardar — nunca estuvo en manifest_original."""
        doc = _doc()
        nuevo = doc.clonar_recurso(rol="titulo")
        doc.eliminar_recurso(nuevo.id)
        _, eliminar_ids = doc.a_objetivos()
        self.assertNotIn(nuevo.id, eliminar_ids)


class TestPlanDiferencias(unittest.TestCase):
    def test_plan_sin_cambios_no_genera_operaciones(self):
        doc = _doc()
        objetivos, eliminar_ids = doc.a_objetivos()
        plan = calcular_diferencias(doc.manifest_original, objetivos, eliminar_ids)
        self.assertEqual(plan.operaciones, [])
        self.assertEqual(plan.errores, [])

    def test_plan_mueve_lo_movido(self):
        doc = _doc()
        doc.mover("titulo", 50.0, 50.0)
        objetivos, eliminar_ids = doc.a_objetivos()
        plan = calcular_diferencias(doc.manifest_original, objetivos, eliminar_ids)
        tipos = {op.box_name: op.tipo for op in plan.operaciones}
        self.assertEqual(tipos.get("Titulo1"), "mover")

    def test_plan_clona_lo_nuevo(self):
        doc = _doc()
        doc.clonar_recurso(rol="foto_secundaria", desde_id="foto_secundaria_repuesto")
        objetivos, eliminar_ids = doc.a_objetivos()
        plan = calcular_diferencias(doc.manifest_original, objetivos, eliminar_ids)
        clonar_ops = [op for op in plan.operaciones if op.tipo == "clonar"]
        self.assertEqual(len(clonar_ops), 1)
        self.assertEqual(clonar_ops[0].origen_box, "FotoRepuesto1")
        self.assertEqual(plan.errores, [])

    def test_plan_elimina_solo_lo_marcado_explicitamente(self):
        doc = _doc()
        doc.eliminar_recurso("cuerpo")
        objetivos, eliminar_ids = doc.a_objetivos()
        plan = calcular_diferencias(doc.manifest_original, objetivos, eliminar_ids)
        eliminar_ops = [op for op in plan.operaciones if op.tipo == "eliminar"]
        self.assertEqual(len(eliminar_ops), 1)
        self.assertEqual(eliminar_ops[0].box_name, "Cuerpo1")
        # El resto (titulo, repuesto) no debe recibir ninguna operación de eliminar.
        self.assertEqual(
            len([op for op in plan.operaciones if op.tipo == "eliminar" and op.box_name != "Cuerpo1"]),
            0,
        )


class TestNomenclatura(unittest.TestCase):
    def test_roundtrip_simple(self):
        nombre = formatear_box_name("titulo", 2)
        self.assertEqual(nombre, "titulo_2")
        info = parse_box_name(nombre)
        self.assertEqual(info, {"rol": "titulo", "indice": 2, "campo": None, "es_grupo": False})

    def test_roundtrip_grupo(self):
        nombre = formatear_box_name("textual", 3, "nombrecargo")
        self.assertEqual(nombre, "textual_3_nombrecargo")
        info = parse_box_name(nombre)
        self.assertEqual(info, {"rol": "textual", "indice": 3, "campo": "nombrecargo", "es_grupo": True})

    def test_nombres_nativos_quark_no_matchean(self):
        self.assertIsNone(parse_box_name("Box371"))
        self.assertIsNone(parse_box_name(""))
        self.assertIsNone(parse_box_name(None))

    def test_campo_invalido_para_el_rol_no_matchea(self):
        self.assertIsNone(parse_box_name("textual_1_inexistente"))


class TestBoxNameDeseado(unittest.TestCase):
    def test_clonar_rol_simple_asigna_nombre_deterministico(self):
        doc = _doc()
        nuevo = doc.clonar_recurso(rol="titulo")
        self.assertEqual(nuevo.box_name_deseado, "titulo_2")  # ya hay 1 "titulo" en uso

    def test_calcular_diferencias_usa_box_name_deseado(self):
        doc = _doc()
        doc.clonar_recurso(rol="titulo")
        objetivos, eliminar_ids = doc.a_objetivos()
        plan = calcular_diferencias(doc.manifest_original, objetivos, eliminar_ids)
        clonar_ops = [op for op in plan.operaciones if op.tipo == "clonar" and op.origen_box == "Titulo1"]
        self.assertEqual(len(clonar_ops), 1)
        self.assertEqual(clonar_ops[0].nuevo_box_name, "titulo_2")

    def test_rol_sin_convencion_usa_fallback_slugify(self):
        """'foto_secundaria' no está en ROLES_SIMPLES (solo 'foto' lo está) —
        box_name_deseado queda None y calcular_diferencias cae al Res_<slug> viejo."""
        doc = _doc()
        nuevo = doc.clonar_recurso(rol="foto_secundaria", desde_id="foto_secundaria_repuesto")
        self.assertIsNone(nuevo.box_name_deseado)


class TestGrupoTextualRigido(unittest.TestCase):
    def test_clonar_recurso_compuesto_preserva_offsets_y_no_modifica_repuestos(self):
        doc = _doc_con_grupo_textual()
        repuestos_antes = {
            r.grupo_campo: (r.left_mm, r.top_mm) for r in doc.recursos.values() if r.rol == "textual"
        }

        nuevos = doc.clonar_recurso_compuesto("textual")

        self.assertEqual(len(nuevos), 4)
        campos = {n.grupo_campo for n in nuevos}
        self.assertEqual(campos, {"texto", "graf", "contenedor", "nombrecargo"})
        # Mismo grupo_id para los 4, y es EL NUEVO (no el del repuesto).
        grupo_ids = {n.grupo_id for n in nuevos}
        self.assertEqual(len(grupo_ids), 1)
        self.assertNotEqual(grupo_ids.pop(), "textual_pasteboard")
        # Los repuestos originales no se tocaron.
        for r in doc.recursos.values():
            if r.rol == "textual" and r.grupo_id == "textual_pasteboard":
                self.assertEqual((r.left_mm, r.top_mm), repuestos_antes[r.grupo_campo])
        # Los offsets relativos entre campos se preservaron.
        por_campo = {n.grupo_campo: n for n in nuevos}
        base_repuesto = repuestos_antes["texto"]
        base_nuevo = (por_campo["texto"].left_mm, por_campo["texto"].top_mm)
        for campo in ("graf", "contenedor", "nombrecargo"):
            dx_original = repuestos_antes[campo][0] - base_repuesto[0]
            dy_original = repuestos_antes[campo][1] - base_repuesto[1]
            dx_nuevo = por_campo[campo].left_mm - base_nuevo[0]
            dy_nuevo = por_campo[campo].top_mm - base_nuevo[1]
            self.assertAlmostEqual(dx_original, dx_nuevo)
            self.assertAlmostEqual(dy_original, dy_nuevo)

    def test_mover_un_miembro_mueve_todo_el_grupo(self):
        doc = _doc_con_grupo_textual()
        nuevos = doc.clonar_recurso_compuesto("textual")
        por_campo = {n.grupo_campo: n for n in nuevos}
        antes = {n.grupo_campo: (n.left_mm, n.top_mm) for n in nuevos}

        doc.mover(por_campo["texto"].id, 500.0, 500.0)

        dx = 500.0 - antes["texto"][0]
        dy = 500.0 - antes["texto"][1]
        for campo, r in por_campo.items():
            self.assertAlmostEqual(r.left_mm, antes[campo][0] + dx)
            self.assertAlmostEqual(r.top_mm, antes[campo][1] + dy)

    def test_sin_repuesto_de_grupo_lanza_error_explicito(self):
        doc = _doc()  # sin repuestos "textual"
        with self.assertRaises(ValueError):
            doc.clonar_recurso_compuesto("textual")


if __name__ == "__main__":
    unittest.main()
