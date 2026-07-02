"""Pasada de calibración del punto de agarre (autocalibración B↔C) asistida por el usuario.

Requiere una maqueta abierta y maximizada en Quark, con los recursos (src/dst) ya calibrados
por áreas. Para cada recurso movible:
  1. captura el recorte del origen A (área {rec}_src) → plantilla para template matching;
  2. clona+arrastra a C (centro de {rec}_dst_1) con el offset de agarre actual;
  3. detecta dónde quedó (B) con cv2; si falla, o para que el usuario valide, muestra el
     ComparadorOverlay para afinar B manualmente;
  4. calcula el error B−C y actualiza el offset aprendido (media móvil + convergencia);
  5. deshace (Ctrl+Z) el clon+arrastre para dejar la maqueta como estaba;
  6. repite hasta converger o agotar las iteraciones.

Corre de forma secuencial en el hilo GUI: pyautogui bloquea la UI durante cada arrastre
(aceptable para una herramienta de calibración manual).
"""
from __future__ import annotations

import logging

from PyQt5.QtWidgets import QMessageBox

from config.config import config_global
from services.armado_auto_schema import RECURSOS_MOVIBLES, normalizar_seccion
from services.quark_auto import QuarkAutomator
import services.calib_visual as cvis

_log = logging.getLogger(__name__)

MAX_ITER = 5   # iteraciones máximas por recurso


class CalibradorAgarre:
    def __init__(self, parent=None, seccion=None):
        self._parent = parent
        self._sec = normalizar_seccion(seccion) if seccion else None
        self._pref = f"{self._sec}__" if self._sec else ""
        self._auto = QuarkAutomator(simular=False)

    def _clave(self, base: str) -> str:
        return f"{self._pref}{base}"

    def ejecutar(self) -> int:
        """Calibra el agarre de todos los recursos con src+dst calibrados. Devuelve cuántos
        recursos se ajustaron."""
        if not self._auto.focus_quark(timeout=15.0):
            QMessageBox.warning(self._parent, "Calibrar agarre",
                                "No se pudo enfocar QuarkXPress. Abrí la maqueta y reintentá.")
            return 0

        ajustados = 0
        for rec in RECURSOS_MOVIBLES:
            area_src = config_global.auto_area(self._clave(f"{rec}_src")) \
                or config_global.auto_area(f"{rec}_src")
            centro_src = config_global.auto_centro(self._clave(f"{rec}_src")) \
                or config_global.auto_centro(f"{rec}_src")
            centro_dst = config_global.auto_centro(self._clave(f"{rec}_dst_1")) \
                or config_global.auto_centro(f"{rec}_dst_1")
            if not (area_src and centro_src and centro_dst):
                _log.info("Calibrar agarre: '%s' sin src/dst calibrado → se saltea.", rec)
                continue
            if self._calibrar_recurso(rec, area_src, centro_src, centro_dst):
                ajustados += 1
        return ajustados

    def _calibrar_recurso(self, rec, area_src, centro_src, centro_dst) -> bool:
        off_key = f"{self._pref}{rec}"
        # Recortar A y guardar la plantilla (se reusa luego en los pegados reales).
        self._auto.focus_quark(timeout=8.0)
        tpl = cvis.capturar_recorte(area_src, clave=off_key)
        if tpl is None:
            return False

        mostrado_overlay = False
        for it in range(MAX_ITER):
            offset = cvis.offset_agarre(off_key)
            self._auto.focus_quark(timeout=8.0)
            self._auto.clonar_y_arrastrar(centro_src, centro_dst, offset_agarre=offset)

            # B automático con cv2.
            b = None
            try:
                det = cvis.localizar(tpl, centro_esperado=centro_dst)
                if det:
                    b = (det[0], det[1])
            except Exception as e:
                _log.debug("localizar '%s' falló: %s", off_key, e)

            # Overlay de ajuste manual: siempre en la 1ª iteración (validación) o si falló cv2.
            if (not mostrado_overlay) or (b is None):
                b_manual = self._overlay(tpl, b or centro_dst, rec)
                mostrado_overlay = True
                if b_manual is not None:
                    b = b_manual

            # Revertir el clon+arrastre (clon = 1 undo, arrastre = 1 undo).
            self._auto.focus_quark(timeout=8.0)
            self._auto.deshacer(2)

            if b is None:
                _log.info("Calibrar agarre '%s' it %d: sin B → se detiene.", off_key, it + 1)
                break
            _dx, _dy, _n, conv = cvis.actualizar_agarre(
                off_key, b, centro_dst, offset_usado=offset)
            if conv >= cvis.MUESTRAS_CONVERGENCIA:
                _log.info("Calibrar agarre '%s': convergió en it %d.", off_key, it + 1)
                break
        return True

    def _overlay(self, tpl, centro_inicial, rec):
        from ui.comparador_overlay import ComparadorOverlay
        dlg = ComparadorOverlay(tpl, centro_inicial, parent=self._parent,
                                titulo=f"Verificar posición: {rec}")
        dlg.exec_()
        return dlg.resultado()


def lanzar_calibrador_agarre(parent=None, seccion=None) -> int:
    """Corre la pasada de calibración de agarre. Devuelve cuántos recursos se ajustaron."""
    return CalibradorAgarre(parent=parent, seccion=seccion).ejecutar()
