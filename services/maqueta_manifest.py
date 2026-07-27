"""
Manifest semántico por maqueta — la "clave más robusta" que reemplaza, para el
NUEVO modelo de recursos del maquetador, a los mapas de nombres de caja
hardcodeados y desconectados que hoy coexisten (maqueta_roles.json, UNIVERSAL/
AVISO_TARGETS/rutinas por sección en PegarNota_JSON.js, el switch de
textual/dato/número, y config.ini [MAQUETA:<nombre>]).

Cada recurso del manifest tiene un `id` SEMÁNTICO y ESTABLE (ej. "cuerpo",
"foto_principal", "foto_secundaria_1") — no depende de que el nombre de caja de
Quark no cambie entre lecturas; el `box_name` es un puntero MUTABLE que se
re-resuelve cada vez que se lee la maqueta.

Este módulo NO reemplaza a maqueta_roles.json ni al pegado de texto existente
(PegarNota_JSON.js) — los usa como referencia de solo lectura para clasificar
roles. Es la base de datos que el "modelo de recursos" (model/recurso_plan.py)
edita y que el director de diferencias (scripts/AplicarModeloRecursos.js)
aplica de vuelta a Quark.

LIMITACIÓN CONOCIDA: un mismo .qxp suele contener varias "páginas" internas que
son VARIANTES alternativas del mismo rol para distintos escenarios editoriales
(ej. layout para 1 noticia vs 2 noticias), no recursos simultáneos. El manifest
es del documento completo y por eso puede listar, p.ej., varios "cuerpo_N" que
en realidad son la misma caja lógica en páginas distintas. El campo `page` de
cada recurso permite filtrar a UN escenario concreto — usar
`recursos_de_pagina(manifest, page)` antes de construir un plan de recursos
para no confundir variantes de escenario con recursos realmente simultáneos.
"""
from __future__ import annotations

from config.config import config_global
from services.maqueta_reader_service import roles_reverse_map
from utils.app_logger import get_logger

_log = get_logger(__name__)


def construir_manifest(data: dict, stem: str = "") -> dict:
    """
    Construye el manifest semántico de una maqueta a partir del dict crudo de
    leer_maqueta_cdp() (o de una entrada de caché). Clasifica cada caja de
    texto/foto en un rol editorial usando maqueta_roles.json (vía
    roles_reverse_map) + config.maqueta_config_for()['foto_box_principal'] para
    distinguir la foto principal de las secundarias. Las cajas sin rol conocido
    quedan igual en el manifest (rol=None) para no perder información — nunca
    se descartan en silencio.
    """
    from services.maqueta_introspect import (
        estimar_capacidad, _resolver_estilo_caja,
        _aprender_fuentes_por_clase, _cargar_override_fuentes,
    )

    rev = roles_reverse_map()
    aprendidos = _aprender_fuentes_por_clase()
    override = _cargar_override_fuentes()

    foto_principal_box = None
    try:
        nombre_qxp = f"{stem}.qxp" if stem and not stem.endswith(".qxp") else stem
        cfg = config_global.maqueta_config_for(nombre_qxp)
        foto_principal_box = cfg.get("foto_box_principal")
    except Exception as e:
        _log.debug("construir_manifest: no se pudo resolver foto_box_principal (%s)", e)

    recursos: list[dict] = []
    contador_por_rol: dict[str, int] = {}
    primer_box_por_rol: dict[str, str] = {}

    for b in (data or {}).get("boxes", []):
        name = b.get("name")
        tipo = b.get("type")
        if not name or tipo not in ("text", "picture"):
            continue

        rol: str | None
        capacidad: int | None = None
        if tipo == "text":
            rol = rev.get(name)
            fs, fam, ld = _resolver_estilo_caja(b, aprendidos, override)
            cap = estimar_capacidad(b.get("width_mm"), b.get("height_mm"), fs, fam, ld)
            capacidad = cap or None
        else:  # picture
            rol = "foto_principal" if (foto_principal_box and name == foto_principal_box) else "foto_secundaria"

        if rol:
            n = contador_por_rol.get(rol, 0) + 1
            contador_por_rol[rol] = n
            rid = rol if n == 1 else f"{rol}_{n}"
        else:
            rid = f"sin_rol_{name}"

        clonable_desde = primer_box_por_rol.get(rol, name) if rol else name
        if rol and rol not in primer_box_por_rol:
            primer_box_por_rol[rol] = name

        recursos.append({
            "id": rid,
            "tipo": tipo,
            "box_name": name,
            "left_mm": b.get("left_mm"),
            "top_mm": b.get("top_mm"),
            "width_mm": b.get("width_mm"),
            "height_mm": b.get("height_mm"),
            "page": b.get("page"),
            "rol": rol,
            "capacidad": capacidad,
            "clonable_desde": clonable_desde,
        })

    return {
        "maqueta": stem,
        "canvas": (data or {}).get("canvas"),
        "recursos": recursos,
    }


def manifest_desde_cache(stem: str) -> dict | None:
    """Construye el manifest a partir de la entrada de caché ya leída de esta
    maqueta (services.maqueta_introspect). None si no está cacheada."""
    from services.maqueta_introspect import cache_maqueta

    entry = cache_maqueta(stem)
    if not entry:
        return None
    data = dict(entry.get("data") or {})
    data["canvas"] = entry.get("canvas") or data.get("canvas")
    return construir_manifest(data, stem)


def recurso_por_id(manifest: dict, rid: str) -> dict | None:
    """Busca un recurso del manifest por su id semántico."""
    for r in (manifest or {}).get("recursos", []):
        if r.get("id") == rid:
            return r
    return None


def recursos_por_rol(manifest: dict, rol: str) -> list[dict]:
    """Todos los recursos del manifest con un rol dado (ej. 'foto_secundaria')."""
    return [r for r in (manifest or {}).get("recursos", []) if r.get("rol") == rol]


def recursos_de_pagina(manifest: dict, page: str) -> list[dict]:
    """Recursos del manifest que pertenecen a UNA página/escenario concreto
    (ver limitación documentada arriba: evita confundir variantes de escenario
    editorial con recursos realmente simultáneos en la misma página)."""
    return [r for r in (manifest or {}).get("recursos", []) if r.get("page") == page]


def paginas_disponibles(manifest: dict) -> list[str]:
    """Lista de valores de 'page' presentes en el manifest, para que el llamador
    elija con cuál escenario trabajar."""
    vistas: list[str] = []
    for r in (manifest or {}).get("recursos", []):
        p = r.get("page")
        if p and p not in vistas:
            vistas.append(p)
    return vistas
