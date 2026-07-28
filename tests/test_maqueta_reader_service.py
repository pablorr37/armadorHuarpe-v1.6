"""
Tests headless de services/maqueta_reader_service.py — el listado del combo
de maquetas del editor de notas (get_templates/get_templates_for_page), sin
depender de la carpeta real de maquetas ni de maquetas_cache.json real.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services import maqueta_reader_service as mrs


class _Pagina(SimpleNamespace):
    """Fake mínimo de model.pagina_model.Pagina — solo los atributos que
    get_templates_for_page() lee con getattr."""
    pass


class TestGetTemplatesForPage(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        d = Path(self._tmpdir.name)
        for nombre in ("vaciaGenerica.qxp", "vaciaGenerica_test.qxp", "vaciaDeportes.qxp",
                       "completa.qxp", "pieCultura.qxp"):
            (d / nombre).touch()
        mrs.set_override_maquetas_dir(d)
        # Aislar de maquetas_cache.json real — estos tests son solo sobre archivos.
        self._cache_patch = patch("services.maqueta_introspect.leer_cache", return_value={})
        self._cache_patch.start()

    def tearDown(self):
        self._cache_patch.stop()
        mrs.set_override_maquetas_dir(None)
        self._tmpdir.cleanup()

    def test_sin_pagina_devuelve_todo(self):
        self.assertEqual(set(mrs.get_templates()), {
            "vaciaGenerica.qxp", "vaciaGenerica_test.qxp", "vaciaDeportes.qxp",
            "completa.qxp", "pieCultura.qxp",
        })

    def test_seccion_real_ya_no_excluye_sufijos_no_estandar(self):
        """Antes del fix, 'vaciaGenerica_test.qxp' quedaba afuera apenas la
        página tenía una sección real (sufijo no coincide exacto) — ahora el
        filtro es solo por tipo de aviso, no por sección."""
        pagina = _Pagina(seccion="Deportes", aviso_full=False, aviso_half=False,
                          aviso_footer=False, aviso_robapagina=False, aviso_doblemedia=False)
        result = mrs.get_templates_for_page(pagina)
        self.assertIn("vaciaGenerica_test.qxp", result)
        self.assertIn("vaciaGenerica.qxp", result)
        self.assertIn("vaciaDeportes.qxp", result)
        # Tipo de aviso SÍ sigue filtrando: nada de "completa"/"pie" para una vacía.
        self.assertNotIn("completa.qxp", result)
        self.assertNotIn("pieCultura.qxp", result)

    def test_filtro_por_tipo_de_aviso_se_mantiene(self):
        pagina = _Pagina(seccion="", aviso_full=True, aviso_half=False,
                          aviso_footer=False, aviso_robapagina=False, aviso_doblemedia=False)
        result = mrs.get_templates_for_page(pagina)
        self.assertEqual(result, ["completa.qxp"])


class TestTemplatesSoloCache(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        d = Path(self._tmpdir.name)
        (d / "vaciaGenerica.qxp").touch()
        mrs.set_override_maquetas_dir(d)

    def tearDown(self):
        mrs.set_override_maquetas_dir(None)
        self._tmpdir.cleanup()

    def _cache_fixture(self):
        return {
            "vaciaGenerica": {"data": {"editor_origen": None}},   # tiene .qxp real -> no es "solo caché"
            "miPruebaMaquetador": {"data": {"editor_origen": "maquetador"}},
            "otraLeidaPorCdp": {"data": {}},   # sin editor_origen -> no es del maquetador
        }

    def test_incluye_solo_las_del_maquetador_sin_qxp_real(self):
        with patch("services.maqueta_introspect.leer_cache", return_value=self._cache_fixture()):
            templates = mrs.get_templates()
        self.assertIn("miPruebaMaquetador", templates)
        self.assertNotIn("otraLeidaPorCdp", templates)
        # La real no se duplica ni aparece dos veces sin extensión.
        self.assertEqual(templates.count("vaciaGenerica.qxp"), 1)
        self.assertNotIn("vaciaGenerica", templates)

    def test_solo_cache_se_agrega_siempre_sin_filtrar_por_aviso(self):
        pagina = _Pagina(seccion="Deportes", aviso_full=True, aviso_half=False,
                          aviso_footer=False, aviso_robapagina=False, aviso_doblemedia=False)
        with patch("services.maqueta_introspect.leer_cache", return_value=self._cache_fixture()):
            result = mrs.get_templates_for_page(pagina)
        # aviso_full=True -> solo "completa*" entre las reales, pero la
        # solo-caché del maquetador se agrega igual, sin filtrar.
        self.assertIn("miPruebaMaquetador", result)


if __name__ == "__main__":
    unittest.main()
