"""
Carga/guardado del editor visual del maquetador (F3+F4). Funciones puras
(sin widgets Qt) para poder testearlas sin instanciar ninguna UI.

Ninguna función de este módulo toca Quark: la carga usa exclusivamente
maquetas_cache.json (ya leído por services/maqueta_introspect) y el guardado
persiste ahí mismo — el mismo pool que ya consume el editor de notas.
"""
from __future__ import annotations

from typing import Optional

from model.maqueta_model import Maqueta
from model.maquetador_state import MaquetadorDocumento, es_pasteboard
from services.maqueta_manifest import manifest_desde_cache, paginas_disponibles


class AmbiguedadPagina(Exception):
    """La maqueta cacheada trae más de una variante de escenario (páginas
    distintas, no pasteboard) — hay que elegir cuál usar antes de construir
    el documento editable (ver limitación documentada en maqueta_manifest.py:
    no son recursos simultáneos, son alternativas editoriales)."""

    def __init__(self, paginas: list[str]):
        self.paginas = paginas
        super().__init__(f"Hay {len(paginas)} escenarios posibles: {paginas}")


def cargar_desde_cache(stem: str, pagina: Optional[str] = None) -> Optional[MaquetadorDocumento]:
    """Construye un MaquetadorDocumento a partir de la caché de maquetas ya
    leída. Si el manifest trae más de un escenario (página) y no se indicó
    cuál usar, levanta AmbiguedadPagina con las opciones disponibles."""
    manifest = manifest_desde_cache(stem)
    if manifest is None:
        return None

    paginas = paginas_disponibles(manifest)
    escenarios = [p for p in paginas if not es_pasteboard(p)]
    if pagina is None and len(escenarios) > 1:
        raise AmbiguedadPagina(escenarios)
    if pagina is None and escenarios:
        pagina = escenarios[0]

    canvas = manifest.get("canvas") or {}
    maqueta = Maqueta(
        nombre=stem,
        canvas_width_mm=canvas.get("width_mm") or 0.0,
        canvas_height_mm=canvas.get("height_mm") or 0.0,
        origen="real",
        source=None,
    )

    manifest_filtrado = manifest
    if pagina is not None:
        recursos = [
            r for r in manifest.get("recursos", [])
            if r.get("page") == pagina or es_pasteboard(r.get("page")) or not r.get("page")
        ]
        manifest_filtrado = dict(manifest, recursos=recursos)

    return MaquetadorDocumento.desde_manifest(maqueta, manifest_filtrado)


def cargar_en_blanco(nombre: str, ancho_mm: float, alto_mm: float) -> MaquetadorDocumento:
    """Origen 'dibujar': lienzo vacío, sin ningún .qxp de referencia. Solo
    permite definir el lienzo y anotar qué recursos debería tener la maqueta
    (agregar_recurso_custom) — no puede materializar cajas nuevas porque
    Quark solo clona cajas existentes, y acá no hay ninguna (ver restricción
    dura en docs/maquetador_arquitectura.md)."""
    maqueta = Maqueta(
        nombre=nombre, canvas_width_mm=ancho_mm, canvas_height_mm=alto_mm,
        origen="dibujar", source=None,
    )
    manifest = {"maqueta": nombre, "canvas": {"width_mm": ancho_mm, "height_mm": alto_mm}, "recursos": []}
    return MaquetadorDocumento.desde_manifest(maqueta, manifest)


def guardar_como_maqueta(doc: MaquetadorDocumento, nombre: str):
    """Persiste el documento editado como entrada de maquetas_cache.json —
    el mismo formato/archivo que ya consumen leer_cache()/cache_maqueta()/
    manifest_desde_cache(), para que la maqueta pase a formar parte del pool
    existente sin inventar un formato paralelo. Devuelve la ruta de la caché."""
    from services.maqueta_introspect import CACHE_PATH, guardar_cache_maqueta

    boxes = []
    for c in doc.a_cajas():
        boxes.append({
            "name": c.nombre, "type": c.tipo,
            "left_mm": c.left_mm, "top_mm": c.top_mm,
            "width_mm": c.width_mm, "height_mm": c.height_mm,
            "right_mm": c.right_mm, "bottom_mm": c.bottom_mm,
            "page": c.page, "font_family": c.font_family,
            "font_size": c.font_size, "leading": c.leading,
            "style_class": c.style_class,
        })
    data = {
        "boxes": boxes,
        "canvas": {"width_mm": doc.maqueta.canvas_width_mm, "height_mm": doc.maqueta.canvas_height_mm},
        "source": doc.maqueta.source,
        "editor_origen": "maquetador",
    }
    guardar_cache_maqueta(nombre, data)
    return CACHE_PATH
