"""
Nomenclatura semántica y determinística de cajas para maquetas construidas
DESDE CERO con el maquetador (ej. maquetas/listas/vaciaGenerica_test.qxp).

Esto NO reemplaza ni migra scripts/maqueta_roles.json (usado por las ~28
maquetas de producción reales, con nombres nativos de Quark tipo "Box371") —
es un camino de clasificación ADICIONAL: el manifest lo intenta solo cuando
roles_reverse_map() no resuelve nada, y el maquetador lo usa para nombrar las
cajas que clona (en vez de "Res_<slug>", ver model/recurso_plan.py::_slugify_id).

Convención (confirmada con el usuario):
  - Recursos simples (una sola caja): "{rol}_{n}", n en base 1 SIEMPRE.
  - Recursos-grupo (varias cajas que se mueven/clonan juntas, igual que
    RECURSO_GRUPO/moverGrupo en scripts/PegarNota v6.js): "{rol}_{n}_{campo}".
    "dato"/"numero"/"qr" YA son grupos multi-caja en producción (5/5/4 cajas)
    aunque no tengan nombres de campo semánticos documentados — se usan
    placeholders genéricos hasta que se confirmen los reales.
"""
from __future__ import annotations

import re

ROLES_SIMPLES = [
    "volanta", "titulo", "bajada", "firma", "cuerpo", "epigrafe",
    "foto", "folio_seccion", "fecha",
]

CAMPOS_TEXTUAL = ["texto", "graf", "contenedor", "nombrecargo"]

# Placeholder: sin nombres semánticos confirmados por sub-caja de dato/numero/qr.
ROLES_GRUPO: dict[str, list[str]] = {
    "textual": CAMPOS_TEXTUAL,
    "dato": ["campo_1", "campo_2", "campo_3", "campo_4", "campo_5"],
    "numero": ["campo_1", "campo_2", "campo_3", "campo_4", "campo_5"],
    "qr": ["campo_1", "campo_2", "campo_3", "campo_4"],
}

_TODOS_LOS_ROLES = set(ROLES_SIMPLES) | set(ROLES_GRUPO.keys())

_RE_GRUPO = re.compile(
    r"^(?P<rol>" + "|".join(re.escape(r) for r in ROLES_GRUPO) + r")_(?P<indice>\d+)_(?P<campo>[a-z0-9_]+)$"
)
_RE_SIMPLE = re.compile(
    r"^(?P<rol>" + "|".join(re.escape(r) for r in ROLES_SIMPLES) + r")_(?P<indice>\d+)$"
)


def parse_box_name(name: str) -> dict | None:
    """Reconoce un nombre de caja según la convención rol_N / rol_N_campo.
    Devuelve {"rol", "indice", "campo", "es_grupo"} o None si no matchea —
    nombres nativos de Quark ("Box371") nunca matchean (no tienen "_")."""
    if not name:
        return None
    m = _RE_GRUPO.match(name)
    if m:
        campo = m.group("campo")
        rol = m.group("rol")
        if campo not in ROLES_GRUPO.get(rol, []):
            return None
        return {"rol": rol, "indice": int(m.group("indice")), "campo": campo, "es_grupo": True}
    m = _RE_SIMPLE.match(name)
    if m:
        return {"rol": m.group("rol"), "indice": int(m.group("indice")), "campo": None, "es_grupo": False}
    return None


def formatear_box_name(rol: str, indice: int, campo: str | None = None) -> str:
    """Inversa exacta de parse_box_name — una sola fuente de verdad para
    reconocer (manifest) y generar (clonado) nombres de caja."""
    if campo is not None:
        return f"{rol}_{indice}_{campo}"
    return f"{rol}_{indice}"
