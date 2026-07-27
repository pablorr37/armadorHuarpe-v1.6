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

    def test_marcar_eliminar_es_explicito(self):
        """No mencionar un recurso en los objetivos NO debe borrarlo — el
        borrado es siempre explícito (eliminar_ids)."""
        doc = _doc()
        objetivos, eliminar_ids = doc.a_objetivos()
        self.assertEqual(eliminar_ids, set())
        self.assertEqual({o.id for o in objetivos}, {"titulo", "cuerpo", "foto_secundaria_repuesto"})

        doc.marcar_eliminar("titulo", True)
        objetivos, eliminar_ids = doc.a_objetivos()
        self.assertEqual(eliminar_ids, {"titulo"})
        self.assertEqual({o.id for o in objetivos}, {"cuerpo", "foto_secundaria_repuesto"})

    def test_clon_marcado_eliminar_no_pide_borrado_en_quark(self):
        """Un recurso que nunca se materializó (es_nuevo, box_name=None) no
        necesita una operación 'eliminar' en Quark si se descarta antes de
        guardar — no hay nada que borrar ahí."""
        doc = _doc()
        nuevo = doc.clonar_recurso(rol="titulo")
        doc.marcar_eliminar(nuevo.id, True)
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
        doc.marcar_eliminar("cuerpo", True)
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


if __name__ == "__main__":
    unittest.main()
