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

import json
import math
import time
from pathlib import Path

from config.config import Config, config_global
from services import quark_cdp
from utils.app_logger import get_logger

_log = get_logger(__name__)

# Caché en disco de la lectura de maquetas (trabajo previo). El editor la consume
# sin necesidad de tener Quark abierto.
CACHE_PATH = Config.RUNTIME_SCRIPTS_DIR / "maquetas_cache.json"

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


# ==================================================================
# Caché de maquetas (trabajo previo) — el editor la consume sin Quark
# ==================================================================

def _es_vacia(data: dict) -> bool:
    """True si la maqueta tiene lienzo pero ninguna caja de texto con fuente
    (candidata a diseñarse con el maquetador — aún no implementado)."""
    for b in (data or {}).get("boxes", []):
        if b.get("type") == "text" and b.get("font_size"):
            return False
    return True


def leer_cache() -> dict:
    """Lee la caché de maquetas: {stem: {data, capacidades, canvas, empty, timestamp}}."""
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        _log.warning("leer_cache: no se pudo leer %s (%s)", CACHE_PATH, e)
    return {}


def guardar_cache_maqueta(stem: str, data: dict) -> None:
    """Guarda/actualiza la entrada de caché de una maqueta (por stem)."""
    if not stem:
        return
    cache = leer_cache()
    cache[stem] = {
        "data": data,
        "capacidades": capacidades_por_caja(data),
        "canvas": (data or {}).get("canvas"),
        "empty": _es_vacia(data),
        "source": (data or {}).get("source"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        _log.info("Maqueta cacheada: %s (%d cajas de texto con capacidad)",
                  stem, len(cache[stem]["capacidades"]))
    except Exception as e:
        _log.warning("guardar_cache_maqueta: no se pudo escribir %s (%s)", CACHE_PATH, e)


def cache_maqueta(stem: str) -> dict | None:
    """Entrada de caché de una maqueta por stem (normalizada, case-insensitive)."""
    if not stem:
        return None
    cache = leer_cache()
    if stem in cache:
        return cache[stem]
    objetivo = _norm_stem(stem)
    for k, v in cache.items():
        if _norm_stem(k) == objetivo:
            return v
    return None


def capacidades_cache(stem: str) -> dict:
    """{box-name: capacidad} cacheada de una maqueta, o {} si no está."""
    entry = cache_maqueta(stem)
    return (entry or {}).get("capacidades", {}) if entry else {}


def _norm_stem(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", (s or "").lower()).encode("ascii", "ignore").decode()
    return s.replace(".qxp", "").strip()


# ==================================================================
# Lectura por CDP: actualizar la abierta / leer todas
# ==================================================================

def _stem_de_source(source: str | None, fallback: str = "") -> str:
    if source:
        return Path(str(source)).stem
    return fallback


def actualizar_maqueta_abierta(puerto: int = quark_cdp.PUERTO_DEFAULT) -> dict | None:
    """Lee la maqueta ACTIVA en Quark ahora mismo y la cachea. Caso: el usuario
    modificó una maqueta y la tiene abierta. Devuelve {stem, capacidades, ...} o None."""
    data = leer_maqueta_cdp(puerto)
    if not data or not data.get("ok"):
        return data  # el llamador muestra data["error"] si vino
    stem = _stem_de_source(data.get("source"))
    if not stem:
        return {"ok": False, "error": "No se pudo determinar el nombre de la maqueta activa."}
    guardar_cache_maqueta(stem, data)
    return {"ok": True, "stem": stem, "capacidades": capacidades_por_caja(data),
            "empty": _es_vacia(data)}


def _quark_exe() -> str | None:
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
    sel = cfg.get("quark", "quark_seleccionado", fallback="Quark 2018").strip().lower()
    key = "quark8" if "quark 8" in sel else "quark2018"
    exe = cfg.get("apps", key, fallback=None)
    return exe if exe and Path(exe).exists() else None


def _cerrar_proyecto_cdp(puerto: int = quark_cdp.PUERTO_DEFAULT) -> None:
    ws = quark_cdp.descubrir_target(puerto, timeout=2.0)
    if not ws:
        return
    try:
        expr = (Config.SCRIPTS_DIR / "CerrarProyecto.js").read_text(encoding="utf-8")
        quark_cdp.evaluar(ws, expr, timeout=15.0)
    except Exception as e:
        _log.warning("_cerrar_proyecto_cdp: %s", e)


def leer_todas_las_maquetas(progress=None, cancel=None,
                            puerto: int = quark_cdp.PUERTO_DEFAULT) -> dict:
    """Trabajo previo: abre cada .qxp de la carpeta de maquetas en Quark, la lee por
    CDP y la cachea, cerrándola al terminar. MANEJA QUARK SOLO — el operador no debe
    usarlo mientras corre.

    progress(i, total, nombre) : callback opcional de avance.
    cancel() -> bool           : callback opcional; si devuelve True, corta.
    Devuelve {'leidas': [...], 'vacias': [...], 'errores': {nombre: msg}}.
    """
    from services import quark_auto
    from services.maqueta_reader_service import _get_maquetas_dir

    resumen = {"leidas": [], "vacias": [], "errores": {}}
    exe = _quark_exe()
    if not exe:
        resumen["errores"]["_config"] = "No se encontró el ejecutable de Quark en [apps]."
        return resumen

    carpeta = _get_maquetas_dir()
    archivos = sorted(carpeta.glob("*.qxp"))
    total = len(archivos)
    if total == 0:
        resumen["errores"]["_dir"] = f"No hay maquetas .qxp en {carpeta}."
        return resumen

    for i, qxp in enumerate(archivos):
        if cancel and cancel():
            break
        stem = qxp.stem
        if progress:
            progress(i, total, stem)
        try:
            quark_auto.lanzar_quark_sin_robar_foco(exe, qxp)
            if not quark_cdp.esperar_proyecto_listo(stem, puerto=puerto, timeout=60.0):
                resumen["errores"][stem] = "Quark no abrió la maqueta a tiempo."
                continue
            data = leer_maqueta_cdp(puerto, timeout=20.0)
            if not data or not data.get("ok"):
                resumen["errores"][stem] = (data or {}).get("error", "Lectura fallida.")
            else:
                guardar_cache_maqueta(stem, data)
                (resumen["vacias"] if _es_vacia(data) else resumen["leidas"]).append(stem)
        except Exception as e:  # noqa: BLE001
            resumen["errores"][stem] = str(e)
        finally:
            _cerrar_proyecto_cdp(puerto)
            time.sleep(0.5)

    if progress:
        progress(total, total, "")
    return resumen
