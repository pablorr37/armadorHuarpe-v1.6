from __future__ import annotations
import json
import os
import unicodedata
from pathlib import Path
from typing import Optional

from config.config import Config
from utils.app_logger import get_logger

_log = get_logger(__name__)

_MAQUETAS_DIR = Path(r"C:\Users\usuario\AppData\Local\Programs\ArmadorHuarpe\maquetas\listas")
_ROLES_JSON = Path(__file__).resolve().parent.parent / "scripts" / "maqueta_roles.json"

# LeerMaqueta.js siempre escribe en AppData/Roaming, independientemente del modo dev/prod
_QUARK_SCRIPTS = Path(os.getenv("APPDATA", "")) / "ArmadorHuarpe" / "scripts"
_INFO_JSON = _QUARK_SCRIPTS / "maqueta_info.json"


_SECTION_SUFFIX_MAP: dict[str, str] = {
    "cafe de la politica":  "CaféDeLaPolítica",
    "café de la política":  "CaféDeLaPolítica",
    "cultura":              "Cultura",
    "deportes":             "Deportes",
    "eco huarpe":           "EcoHuarpe",
    "economia":             "Economía",
    "economía":             "Economía",
    "locales":              "Locales",
    "politica":             "Política",
    "política":             "Política",
    "policiales":           "Policiales",
    "interes general":      "InterésGeneral",
    "interés general":      "InterésGeneral",
    "opinion":              "Opinión",
    "opinión":              "Opinión",
    "sociedad":             "Sociedad",
    "campo":                "Campo",
    "negocios":             "Negocios",
    "turismo":              "Turismo",
    "espectaculos":         "Espectáculos",
    "espectáculos":         "Espectáculos",
}

_AD_PREFIXES: dict[str, list[str]] = {
    "full":       ["completa"],
    "half":       ["media"],
    "footer":     ["pie"],
    "robapagina": ["roba"],
    "none":       ["vacia"],
}

# Maquetas especiales: secciones que usan UNA maqueta fija, sin patrón {tipo}{sufijo}.
# Clave = sección normalizada (sin acentos, minúsculas); valor = stem del .qxp.
_SECCION_MAQUETA_ESPECIAL: dict[str, str] = {
    "escrache al bache": "EscracheAlBache",
}

_override_maquetas_dir: Path | None = None


def set_override_maquetas_dir(p: "Path | None") -> None:
    global _override_maquetas_dir
    _override_maquetas_dir = p


def _get_maquetas_dir(rutas: dict | None = None) -> Path:
    """
    Resuelve el directorio de maquetas en orden:
    1. rutas["maquetas_root"] si existe y contiene .qxp
    2. APP_DIR / "maquetas" / "listas" (desarrollo)
    3. _MAQUETAS_DIR (producción, hardcoded)
    """
    if rutas:
        raw = rutas.get("maquetas_root") or ""
        if raw:
            p = Path(raw)
            if p.exists():
                return p
    dev = Config.APP_DIR / "maquetas" / "listas"
    if dev.exists():
        return dev
    return _MAQUETAS_DIR


def resolve_maqueta_name(
    aviso_tipo: str,
    seccion: str,
    maquetas_dir: Path,
) -> Optional[str]:
    """
    Determina el nombre de archivo .qxp que corresponde a (aviso_tipo, seccion).

    Lógica:
      1. tipo + sufijo_seccion + ".qxp"  (ej: pieDeportes.qxp)
      2. tipo + "Generica.qxp"           (ej: pieGenerica.qxp)
      3. None  (ninguna encontrada)

    aviso_tipo: "vacia", "pie", "media", "roba", "completa", "doblemedia"
    seccion: nombre de sección tal cual viene del INI (puede tener tildes/espacios)
    maquetas_dir: directorio donde buscar los .qxp
    """
    seccion_norm = _normalizar(seccion)
    suffix = _SECTION_SUFFIX_MAP.get(seccion_norm)

    # Matching insensible a mayúsculas/acentos: el nombre real del archivo puede
    # diferir del CamelCase del mapa (ej. archivo 'vaciaCafédelaPolítica.qxp' vs
    # sufijo 'CaféDeLaPolítica'). Escaneamos el directorio y comparamos normalizado.
    try:
        archivos = list(maquetas_dir.glob("*.qxp"))
    except Exception:
        archivos = []

    def _buscar(nombre_objetivo: str):
        objetivo = _normalizar(nombre_objetivo)
        return next((f.name for f in archivos if _normalizar(f.stem) == objetivo), None)

    # Maqueta especial por sección (ignora el tipo de aviso). Ej.: "Escrache al Bache".
    especial = _SECCION_MAQUETA_ESPECIAL.get(seccion_norm)
    if especial:
        hit = _buscar(especial)
        if hit:
            _log.debug("resolve_maqueta especial: %s (seccion=%s)", hit, seccion)
            return hit

    if suffix:
        hit = _buscar(f"{aviso_tipo}{suffix}")
        if hit:
            _log.debug("resolve_maqueta: %s (tipo=%s, seccion=%s)", hit, aviso_tipo, seccion)
            return hit

    fallback = _buscar(f"{aviso_tipo}Generica")
    if fallback:
        _log.debug("resolve_maqueta fallback: %s (tipo=%s, seccion=%s)", fallback, aviso_tipo, seccion)
        return fallback

    # Último fallback: el archivo plano del tipo (ej. 'completa.qxp', 'vacia.qxp').
    plano = _buscar(aviso_tipo)
    if plano:
        _log.debug("resolve_maqueta plano: %s (tipo=%s)", plano, aviso_tipo)
        return plano

    _log.debug("resolve_maqueta: no se encontró plantilla para tipo='%s', seccion='%s' en %s",
               aviso_tipo, seccion, maquetas_dir)
    return None


def resolve_maqueta(aviso_full: bool, aviso_half: bool, aviso_footer: bool,
                    aviso_robapagina: bool, seccion: str,
                    rutas: dict | None = None) -> Optional[str]:
    """
    Resuelve el nombre de maqueta a partir de los flags de aviso de la página y
    la sección. Mapea flags→tipo (completa/media/pie/roba/vacia) y delega en
    resolve_maqueta_name (sección sin sufijo → {tipo}Generica.qxp).
    """
    if aviso_full:
        tipo = "completa"
    elif aviso_half:
        tipo = "media"
    elif aviso_footer:
        tipo = "pie"
    elif aviso_robapagina:
        tipo = "roba"
    else:
        tipo = "vacia"
    d = _override_maquetas_dir or _get_maquetas_dir(rutas)
    return resolve_maqueta_name(tipo, seccion or "", d)


def get_templates() -> list[str]:
    d = _override_maquetas_dir or _get_maquetas_dir()
    if not d.exists():
        return []
    return sorted(p.name for p in d.glob("*.qxp"))


def get_templates_for_page(pagina) -> list[str]:
    """
    Filtra las maquetas según sección y tipo de aviso de la página.
    Devuelve lista ordenada; si el filtro da vacío devuelve todas.
    """
    all_tpls = get_templates()
    if not all_tpls or pagina is None:
        return all_tpls

    # Determine valid ad prefixes
    if getattr(pagina, "aviso_full", False):
        ad_prefixes = _AD_PREFIXES["full"]
    elif getattr(pagina, "aviso_half", False):
        ad_prefixes = _AD_PREFIXES["half"]
    elif getattr(pagina, "aviso_footer", False):
        ad_prefixes = _AD_PREFIXES["footer"]
    elif getattr(pagina, "aviso_robapagina", False):
        ad_prefixes = _AD_PREFIXES["robapagina"]
    else:
        ad_prefixes = _AD_PREFIXES["none"]

    # Determine valid section suffixes (None = no restriction, show all)
    seccion_norm = _normalizar(getattr(pagina, "seccion", "") or "")
    section_suffix = _SECTION_SUFFIX_MAP.get(seccion_norm)
    # Only restrict by section when a recognised non-generic section is assigned
    restrict_section = section_suffix is not None
    # Comparación normalizada (case/acentos): el sufijo del archivo real puede
    # diferir del CamelCase del mapa (ej. 'Cafédelapolítica' vs 'CaféDeLaPolítica').
    valid_norm = ({_normalizar("Generica"), _normalizar(section_suffix)}
                  if restrict_section else set())

    result = []
    for tpl in all_tpls:
        stem = tpl.replace(".qxp", "")
        matched = next((p for p in ad_prefixes if stem.lower().startswith(p)), None)
        if matched is None:
            continue
        suffix = stem[len(matched):]    # e.g. "Cultura", "Generica", ""
        if not suffix:
            result.append(tpl)          # "completa.qxp" — no section suffix
        elif not restrict_section or _normalizar(suffix) in valid_norm:
            result.append(tpl)

    # Maqueta especial de la sección (no sigue el patrón {tipo}{sufijo}): incluirla.
    especial = _SECCION_MAQUETA_ESPECIAL.get(seccion_norm)
    if especial:
        for tpl in all_tpls:
            if _normalizar(tpl.replace(".qxp", "")) == _normalizar(especial) and tpl not in result:
                result.append(tpl)

    return result if result else all_tpls


def read_maqueta_info() -> dict | None:
    if not _INFO_JSON.exists():
        return None
    try:
        return json.loads(_INFO_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def map_to_editor_limits(info: dict, seccion: str) -> dict:
    """
    Cruza maqueta_info.json con maqueta_roles.json para la sección dada.
    Devuelve dict compatible con maqueta_config más 'picture_count'.
    Si no hay texto placeholder en una caja, ese límite no se incluye.
    """
    try:
        roles = json.loads(_ROLES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}

    seccion_norm = _normalizar(seccion)
    cfg = roles.get(seccion_norm) or roles.get("default") or {}
    variantes = cfg.get("variantes", [])

    # Usar índice plano box_chars si disponible (generado por LeerMaqueta.js >= v2)
    # Fallback: construir desde text_boxes filtrando chars > 0
    box_chars: dict[str, int] = info.get("box_chars") or {
        b["name"]: b["chars"]
        for b in info.get("text_boxes", [])
        if b.get("chars", 0) > 0
    }

    defaults = cfg.get("default_limits", {})
    result: dict = {}

    for v in variantes:
        vname = v.get("volanta", "")
        cname = v.get("cuerpo", "")
        if vname in box_chars:
            result["volanta_limit"] = box_chars[vname]
            if cname and cname in box_chars:
                result["cuerpo_limit"] = box_chars[cname]
            break
    if "volanta_limit" not in result and "volanta_limit" in defaults:
        result["volanta_limit"] = defaults["volanta_limit"]

    epi = cfg.get("epigrafe", "")
    if epi and epi in box_chars:
        result["epigrafe_principal_limit"] = box_chars[epi]
    elif "epigrafe_principal_limit" not in result and "epigrafe_principal_limit" in defaults:
        result["epigrafe_principal_limit"] = defaults["epigrafe_principal_limit"]

    txs = cfg.get("textuales", [])
    if txs:
        tc = next((box_chars[n] for n in txs if n in box_chars), None)
        if tc:
            result["textual_sin_foto_limit"] = tc

    result["picture_count"] = info.get("picture_count", 0)
    return result


def get_story_types(seccion: str, story_count: int, story_index: int) -> list[str]:
    """Devuelve los tipos disponibles para un slot (ej. ['secundaria', 'breve']).
    Lista vacía = un solo tipo, sin selector."""
    try:
        roles = json.loads(_ROLES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    seccion_norm = _normalizar(seccion)
    cfg = roles.get(seccion_norm) or roles.get("default") or {}
    slots = (cfg.get("story_scenarios", {}).get(str(story_count))
             or cfg.get("story_scenarios", {}).get("1") or [])
    slot = next((s for s in slots if s.get("story_index") == story_index), None)
    if slot is None:
        return []
    return list(slot.get("story_types", {}).keys())


def map_limits_for_story(
    info: dict | None, seccion: str, story_count: int, story_index: int,
    story_type: str | None = None
) -> dict:
    """
    Límites para el slot story_index dentro de un layout de story_count noticias.
    Toma el mínimo entre variantes de página (más restrictivo: PegarNota pega en todas).
    Devuelve: volanta_limit, titulo_lineas, epigrafe_principal_limit, tiene_epigrafe,
              cuerpo_limit (capacidad total de la caja), picture_count.
    """
    try:
        roles = json.loads(_ROLES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}

    seccion_norm = _normalizar(seccion)
    cfg = roles.get(seccion_norm) or roles.get("default") or {}
    scenarios = cfg.get("story_scenarios", {})
    slots = scenarios.get(str(story_count)) or scenarios.get("1") or []

    slot = next((s for s in slots if s.get("story_index") == story_index), None)
    if slot is None and slots:
        slot = slots[0]
    if slot is None:
        return map_to_editor_limits(info or {}, seccion)

    # Resolver tipo de historia (secundaria, breve, etc.)
    if "story_types" in slot:
        type_map = slot["story_types"]
        if story_type and story_type in type_map:
            tcfg = type_map[story_type]
        else:
            tcfg = next(iter(type_map.values()))
    else:
        tcfg = slot

    box_chars: dict[str, int] = {}
    if info:
        box_chars = {
            b["name"]: b["chars"]
            for b in info.get("text_boxes", [])
            if b.get("chars", 0) > 0
        }

    def _min_chars(field: str) -> int | None:
        vals = [
            box_chars[p[field]]
            for p in tcfg.get("pages", [])
            if field in p and p[field] in box_chars
        ]
        return min(vals) if vals else None

    defaults = cfg.get("default_limits", {})
    result: dict = {}

    vl = _min_chars("volanta")
    if vl is not None:
        result["volanta_limit"] = vl
    elif "volanta_limit" in defaults:
        result["volanta_limit"] = defaults["volanta_limit"]

    tiene_epi = not tcfg.get("sin_epigrafe", False)
    result["tiene_epigrafe"] = tiene_epi
    if tiene_epi:
        el = _min_chars("epigrafe")
        if el is not None:
            result["epigrafe_principal_limit"] = el
        elif "epigrafe_principal_limit" in defaults:
            result["epigrafe_principal_limit"] = defaults["epigrafe_principal_limit"]

    cl = _min_chars("cuerpo")
    if cl is not None:
        result["cuerpo_limit"] = cl

    result["titulo_lineas"] = tcfg.get("titulo_lineas", slot.get("titulo_lineas", 2))
    result["titulo_chars_linea"] = tcfg.get("titulo_chars_linea", 38)
    result["sin_bajada"] = tcfg.get("sin_bajada", False)
    result["picture_count"] = (info or {}).get("picture_count", 0)
    return result


def _normalizar(s: str) -> str:
    return (
        unicodedata.normalize("NFD", (s or "").lower())
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
    )
