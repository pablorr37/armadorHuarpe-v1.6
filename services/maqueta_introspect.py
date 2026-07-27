"""
Lectura de maqueta desde QuarkXPress por CDP (Chrome DevTools Protocol) y
estimación ANALÍTICA de cuántos caracteres entran en cada caja — sin rellenar
ni inyectar texto.

Combina:
  - scripts/LeerMaquetaCDP.js: devuelve por CDP (returnByValue) la geometría en
    mm, la fuente/tamaño/interlineado y la clase de estilo de cada caja, más el
    lienzo. Funciona con maquetas llenas o vacías.
  - QFontMetrics (PyQt5): estima la capacidad = chars_por_línea × líneas a partir
    de la geometría y la fuente, con un factor de calibración.
"""
from __future__ import annotations

import math

from config.config import config_global
from services import quark_cdp
from utils.app_logger import get_logger

_log = get_logger(__name__)

# 1 punto tipográfico = 1/72 pulgada = 0.3527777… mm
PT_TO_MM = 25.4 / 72.0
# Inset de texto por defecto de Quark (1 pt a cada lado ≈ 0.353 mm)
DEFAULT_INSET_MM = 1.0
# Factor de calibración por defecto (justificación/partición/espacios).
DEFAULT_FACTOR = 0.98


def leer_maqueta_cdp(puerto: int = quark_cdp.PUERTO_DEFAULT,
                     timeout: float = 15.0) -> dict | None:
    """Lee la maqueta abierta en Quark por CDP. Devuelve el dict del JS
    (ok, source, boxes[], canvas) o None si Quark no está disponible."""
    ws = quark_cdp.descubrir_target(puerto, timeout=2.0)
    if not ws:
        _log.info("leer_maqueta_cdp: Quark no disponible por CDP (puerto %d).", puerto)
        return None
    js_path = config_global.SCRIPTS_DIR / "LeerMaquetaCDP.js"
    try:
        expr = js_path.read_text(encoding="utf-8")
    except Exception as e:
        _log.warning("leer_maqueta_cdp: no se pudo leer %s (%s)", js_path, e)
        return None
    try:
        res = quark_cdp.evaluar(ws, expr, timeout=timeout)
    except Exception as e:
        _log.warning("leer_maqueta_cdp: fallo la evaluación CDP (%s)", e)
        return None
    data = res.get("value") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        _log.warning("leer_maqueta_cdp: respuesta inesperada: %r", res)
        return None
    if not data.get("ok"):
        _log.warning("leer_maqueta_cdp: el script reportó error: %s", data.get("error"))
    return data


# ------------------------------------------------------------------
# Estimación analítica de capacidad (QFontMetrics)
# ------------------------------------------------------------------

_fm_cache: dict[str, tuple[float, float]] = {}   # familia → (avg_adv_per_em, height_per_em)


def _metricas_fuente(font_family: str | None) -> tuple[float, float]:
    """(ancho medio de carácter, alto de línea) por em, adimensionales.
    Usa un tamaño en px grande para precisión y cachea por familia."""
    fam = font_family or ""
    if fam in _fm_cache:
        return _fm_cache[fam]
    try:
        from PyQt5.QtGui import QFont, QFontMetricsF
    except Exception:
        return (0.5, 1.2)  # fallback razonable si no hay Qt
    EM = 1000.0
    font = QFont(fam) if fam else QFont()
    font.setPixelSize(int(EM))
    fm = QFontMetricsF(font)
    avg = fm.averageCharWidth() / EM
    hgt = fm.height() / EM
    if avg <= 0:
        avg = 0.5
    if hgt <= 0:
        hgt = 1.2
    _fm_cache[fam] = (avg, hgt)
    return (avg, hgt)


def estimar_capacidad(
    width_mm: float | None,
    height_mm: float | None,
    font_size_pt: float | None,
    font_family: str | None = None,
    leading_pt: float | None = None,
    inset_mm: float = DEFAULT_INSET_MM,
    factor: float = DEFAULT_FACTOR,
) -> int:
    """Estima cuántos caracteres entran en una caja de texto dada su geometría
    (mm) y su fuente/tamaño (pt), sin rellenarla. Devuelve 0 si faltan datos."""
    if not width_mm or not height_mm or not font_size_pt:
        return 0
    avg_per_em, height_per_em = _metricas_fuente(font_family)
    em_mm = font_size_pt * PT_TO_MM
    avg_char_mm = avg_per_em * em_mm
    if avg_char_mm <= 0:
        return 0
    if leading_pt and leading_pt > 0:
        line_h_mm = leading_pt * PT_TO_MM
    else:
        line_h_mm = height_per_em * em_mm
    usable_w = max(0.0, width_mm - 2 * inset_mm)
    usable_h = max(0.0, height_mm - 2 * inset_mm)
    chars_por_linea = math.floor(usable_w / avg_char_mm)
    lineas = math.floor(usable_h / line_h_mm)
    if chars_por_linea <= 0 or lineas <= 0:
        return 0
    return int(chars_por_linea * lineas * factor)


def capacidades_por_caja(data: dict, factor: float = DEFAULT_FACTOR) -> dict[str, int]:
    """{box-name: capacidad_estimada} para las cajas de texto con fuente conocida."""
    result: dict[str, int] = {}
    for b in (data or {}).get("boxes", []):
        if b.get("type") != "text":
            continue
        cap = estimar_capacidad(
            b.get("width_mm"), b.get("height_mm"), b.get("font_size"),
            b.get("font_family"), b.get("leading"), factor=factor,
        )
        if cap > 0:
            result[b["name"]] = cap
    return result


def probar_escritura_geometria(puerto: int = quark_cdp.PUERTO_DEFAULT,
                               timeout: float = 15.0) -> dict | None:
    """Spike F2: ejecuta MoverCajaMM_spike.js sobre la caja seleccionada en Quark
    y devuelve el resultado (antes/después/movio). Requiere una caja seleccionada."""
    ws = quark_cdp.descubrir_target(puerto, timeout=2.0)
    if not ws:
        return None
    js_path = config_global.SCRIPTS_DIR / "MoverCajaMM_spike.js"
    try:
        expr = js_path.read_text(encoding="utf-8")
        res = quark_cdp.evaluar(ws, expr, timeout=timeout)
    except Exception as e:
        _log.warning("probar_escritura_geometria: %s", e)
        return None
    return res.get("value") if isinstance(res, dict) else None


def calibrar_factor(data: dict) -> float | None:
    """Deriva un factor de calibración comparando la capacidad geométrica (factor=1)
    contra los chars reales de las cajas que tienen placeholder. Devuelve el
    promedio de (chars_reales / capacidad_geométrica), o None si no hay muestras."""
    ratios = []
    for b in (data or {}).get("boxes", []):
        if b.get("type") != "text" or not b.get("chars"):
            continue
        cap = estimar_capacidad(
            b.get("width_mm"), b.get("height_mm"), b.get("font_size"),
            b.get("font_family"), b.get("leading"), factor=1.0,
        )
        if cap > 0:
            ratios.append(b["chars"] / cap)
    if not ratios:
        return None
    return sum(ratios) / len(ratios)
