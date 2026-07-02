"""Calibración visual del punto de agarre del clon (autocalibración B↔C).

Contexto: al duplicar con Ctrl+D, QuarkXPress corre el duplicado unos px. El bot lo
"agarra" apuntando con un offset respecto del centro del recurso de origen (src). Si ese
offset está mal, el recurso termina en B en vez de C (la posición destino calibrada por el
usuario). Como el arrastre es una traslación rígida, `error = B - C` es exactamente el error
del punto de agarre; el agarre corregido es `A* = agarre_usado - (B - C)`.

Este módulo:
  * captura la pantalla y recorta el origen (posición A) → plantilla para template matching;
  * localiza el recurso en la escena con cv2.matchTemplate → posición real B;
  * actualiza el offset aprendido con media móvil y lleva un contador de convergencia,
    de modo que, una vez estable, los pegados reales dejan de recalcular.

Reusa el stack ya presente en ui/lectorQR.py (pyautogui.screenshot + cv2 + numpy).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import pyautogui

from config.config import config_global
from services.quark_auto import CLON_OFFSET_X, CLON_OFFSET_Y

_log = logging.getLogger(__name__)

# Confianza mínima de cv2.matchTemplate (TM_CCOEFF_NORMED) para aceptar la detección de B.
# Por debajo de esto se devuelve None y el flujo cae al ajuste manual (overlay).
UMBRAL_MATCH = 0.75

# Tolerancia (px): |B - C| ≤ TOL cuenta como "buena" para la convergencia.
TOL_CONVERGENCIA = 4
# Muestras buenas consecutivas para considerar un recurso convergido.
MUESTRAS_CONVERGENCIA = 3
# Ventana de la media móvil del offset aprendido.
K_MEDIA = 5

# Margen (px) alrededor del destino donde buscar el recurso (acota el matchTemplate).
MARGEN_BUSQUEDA = 220

_TPL_DIR = config_global.DATA_DIR / "calib_tpl"


# ── Captura ───────────────────────────────────────────────────────────────
def capturar_pantalla(region: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
    """Screenshot (BGR) de `region`=(x,y,w,h) global, o de toda la pantalla si None."""
    img = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _ruta_tpl(clave: str) -> Path:
    return _TPL_DIR / f"{clave}.png"


def capturar_recorte(area, clave: Optional[str] = None) -> Optional[np.ndarray]:
    """Recorta el rectángulo `area`=(x,y,w,h) del origen (A) y lo devuelve en BGR.
    Si se pasa `clave`, además persiste la plantilla en DATA_DIR/calib_tpl/{clave}.png."""
    if not area:
        return None
    try:
        x, y, w, h = (int(area[0]), int(area[1]), int(max(1, area[2])), int(max(1, area[3])))
    except Exception:
        return None
    tpl = capturar_pantalla((x, y, w, h))
    if clave:
        try:
            _TPL_DIR.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(_ruta_tpl(clave)), tpl)
        except Exception as e:
            _log.warning("No se pudo guardar la plantilla %s: %s", clave, e)
    return tpl


def cargar_template(clave: str) -> Optional[np.ndarray]:
    """Lee la plantilla guardada del recurso `clave`, o None si no existe."""
    p = _ruta_tpl(clave)
    if not p.exists():
        return None
    try:
        return cv2.imread(str(p), cv2.IMREAD_COLOR)
    except Exception:
        return None


# ── Localización (posición B) ───────────────────────────────────────────────
def _region_alrededor(centro, template) -> Tuple[int, int, int, int]:
    """Región de búsqueda (x,y,w,h) global centrada en `centro`, con margen y del tamaño
    del template. Se recorta a coordenadas ≥ 0."""
    th, tw = template.shape[:2]
    half_w = tw // 2 + MARGEN_BUSQUEDA
    half_h = th // 2 + MARGEN_BUSQUEDA
    x = max(0, int(centro[0]) - half_w)
    y = max(0, int(centro[1]) - half_h)
    return (x, y, half_w * 2, half_h * 2)


def localizar(template: np.ndarray, centro_esperado=None,
              umbral: float = UMBRAL_MATCH) -> Optional[Tuple[int, int, float]]:
    """Busca `template` en pantalla y devuelve (cx, cy, score) del CENTRO en coords globales.
    Si `centro_esperado` está dado, acota la búsqueda a una región alrededor (más rápido y
    robusto). Devuelve None si el mejor match no supera `umbral`."""
    if template is None or template.size == 0:
        return None
    region = _region_alrededor(centro_esperado, template) if centro_esperado else None
    escena = capturar_pantalla(region)
    # El template no puede ser más grande que la escena.
    if (escena.shape[0] < template.shape[0]) or (escena.shape[1] < template.shape[1]):
        escena = capturar_pantalla(None)
        region = None
        if (escena.shape[0] < template.shape[0]) or (escena.shape[1] < template.shape[1]):
            return None
    res = cv2.matchTemplate(escena, template, cv2.TM_CCOEFF_NORMED)
    _minv, maxv, _minl, maxloc = cv2.minMaxLoc(res)
    if maxv < umbral:
        _log.info("matchTemplate score=%.3f < umbral=%.2f → sin detección.", maxv, umbral)
        return None
    th, tw = template.shape[:2]
    ox, oy = (region[0], region[1]) if region else (0, 0)
    cx = ox + maxloc[0] + tw // 2
    cy = oy + maxloc[1] + th // 2
    return (int(cx), int(cy), float(maxv))


# ── Aprendizaje del offset de agarre ────────────────────────────────────────
def offset_agarre(clave: str) -> Tuple[int, int]:
    """Offset (dx, dy) a usar para agarrar el clon del recurso `clave`: el aprendido si
    existe, o el fallback fijo CLON_OFFSET."""
    prev = config_global.auto_grab_offset(clave)
    if prev:
        return (int(prev[0]), int(prev[1]))
    return (CLON_OFFSET_X, CLON_OFFSET_Y)


def convergido(clave: str) -> bool:
    """True si el agarre de `clave` ya convergió (los pegados reales no lo re-miden)."""
    return config_global.auto_grab_conv(clave) >= MUESTRAS_CONVERGENCIA


def actualizar_agarre(clave: str, pos_b, pos_c, offset_usado=None
                      ) -> Tuple[int, int, int, int]:
    """Incorpora una medición: dado dónde quedó el recurso (B=pos_b) y dónde debía quedar
    (C=pos_c), corrige el offset de agarre y lo persiste con media móvil.

    Devuelve (dx, dy, n_muestras, conv). No toca nada si faltan datos."""
    if not pos_b or not pos_c:
        dx, dy = offset_agarre(clave)
        prev = config_global.auto_grab_offset(clave)
        return (dx, dy, prev[2] if prev else 0, config_global.auto_grab_conv(clave))
    error_dx = int(pos_b[0]) - int(pos_c[0])
    error_dy = int(pos_b[1]) - int(pos_c[1])

    prev = config_global.auto_grab_offset(clave)
    if prev:
        dx, dy, n = float(prev[0]), float(prev[1]), int(prev[2])
    else:
        dx, dy, n = float(offset_usado[0]) if offset_usado else float(CLON_OFFSET_X), \
                    float(offset_usado[1]) if offset_usado else float(CLON_OFFSET_Y), 0

    # Offset que hubiera hecho caer el recurso en C esta vez.
    objetivo_dx = dx - error_dx
    objetivo_dy = dy - error_dy
    n_new = n + 1
    peso = 1.0 / min(n_new, K_MEDIA)
    ndx = dx + (objetivo_dx - dx) * peso
    ndy = dy + (objetivo_dy - dy) * peso

    # Convergencia: cuenta muestras buenas consecutivas; se resetea si el error crece.
    buena = (abs(error_dx) <= TOL_CONVERGENCIA and abs(error_dy) <= TOL_CONVERGENCIA)
    conv = config_global.auto_grab_conv(clave) + 1 if buena else 0

    config_global.save_auto_grab_offset(clave, ndx, ndy, n_new, conv=conv)
    _log.info("Agarre '%s': error=(%d,%d) → offset=(%.1f,%.1f) n=%d conv=%d",
              clave, error_dx, error_dy, ndx, ndy, n_new, conv)
    return (int(round(ndx)), int(round(ndy)), n_new, conv)
