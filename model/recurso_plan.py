"""
Modelo objetivo de recursos + cálculo de diferencias contra un manifest leído
(services/maqueta_manifest.py) — el "director" que decide qué operaciones hacen
falta para llevar una maqueta de su estado actual al estado deseado.

Usa EXCLUSIVAMENTE los 5 primitivos que la investigación técnica confirmó como
seguros y ya probados en producción (ver scripts/PegarNota v6.js):
  - MOVER / REDIMENSIONAR: reescritura de --qx-left/top/right/bottom en mm.
  - CLONAR: cloneNode(true) + limpiar box-id/box-uid + reposicionar + renombrar.
    SIEMPRE requiere una caja YA EXISTENTE del mismo rol en la misma maqueta
    (QX.js no puede crear una caja desde la nada) — el campo `clonable_desde`
    del manifest es esa caja origen.
  - ELIMINAR: box.parentNode.removeChild(box).
  - RENOMBRAR: setAttribute('box-name', ...).

Este módulo NO toca el pegado de texto (PegarNota_JSON.js) — es un subsistema
aislado para geometría y cantidad de recursos (fotos, cajas de aviso, etc.).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from services.maqueta_manifest import recurso_por_id


# Tolerancia (mm) por debajo de la cual no vale la pena generar una operación
# de mover/redimensionar (evita "diffs" espurios por redondeo de lectura).
_TOLERANCIA_MM = 0.05


@dataclass
class RecursoObjetivo:
    """Estado DESEADO de un recurso — el maquetador (Python) construye una
    lista de estos y calcular_diferencias() decide cómo llegar a ellos."""
    id: str
    rol: str
    left_mm: float
    top_mm: float
    width_mm: float
    height_mm: float
    page: str | None = None


@dataclass
class Operacion:
    """Una operación atómica a aplicar en Quark (ver scripts/AplicarModeloRecursos.js)."""
    tipo: str  # "mover" | "redimensionar" | "clonar" | "eliminar" | "renombrar"
    box_name: str | None = None        # caja existente a operar
    origen_box: str | None = None      # (clonar) caja origen
    nuevo_box_name: str | None = None  # (clonar/renombrar) nombre a asignar
    left_mm: float | None = None
    top_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    page: str | None = None
    nota: str = ""                     # para diagnóstico/logging

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class PlanDiferencias:
    operaciones: list[Operacion] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)


def _slugify_id(rid: str) -> str:
    """Nombre de caja tentativo para una clonación (Quark exige unicidad)."""
    return "Res_" + "".join(c if c.isalnum() else "_" for c in rid)


def aplicar_plan_recursos(plan: PlanDiferencias, puerto: int | None = None) -> dict:
    """
    Escribe `plan.operaciones` a plan_recursos.json (carpeta de scripts de la
    app en AppData/Roaming, mismo canal que el resto de los scripts IPC) y
    ejecuta scripts/AplicarModeloRecursos.js por CDP, que las aplica en Quark
    envueltas en UN solo compound-undo. Devuelve {ok, resultados, error}.

    Requiere QuarkXPress abierto con la maqueta activa. No aplica nada si
    `plan.errores` no está vacío — revisar y resolverlos antes (normalmente
    "no hay caja para clonar de este rol").
    """
    import json
    import os
    from pathlib import Path

    from config.config import Config
    from services import quark_cdp

    if plan.errores:
        return {"ok": False, "error": "El plan tiene errores sin resolver: "
                + "; ".join(plan.errores), "resultados": []}
    if not plan.operaciones:
        return {"ok": True, "resultados": [], "error": None}

    puerto = puerto if puerto is not None else quark_cdp.PUERTO_DEFAULT
    ws = quark_cdp.descubrir_target(puerto, timeout=2.0)
    if not ws:
        return {"ok": False, "error": "Quark no disponible por CDP.", "resultados": []}

    appdata_scripts = Path(os.getenv("APPDATA", "")) / "ArmadorHuarpe" / "scripts"
    appdata_scripts.mkdir(parents=True, exist_ok=True)
    payload = {"operaciones": [op.to_dict() for op in plan.operaciones]}
    (appdata_scripts / "plan_recursos.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    js_path = Config.SCRIPTS_DIR / "AplicarModeloRecursos.js"
    try:
        expr = js_path.read_text(encoding="utf-8")
        res = quark_cdp.evaluar(ws, expr, timeout=30.0)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "resultados": []}
    data = res.get("value") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        return {"ok": False, "error": f"Respuesta inesperada de Quark: {res!r}", "resultados": []}
    return data


def calcular_diferencias(
    manifest: dict, objetivos: list[RecursoObjetivo], eliminar_ids: set[str] | None = None,
) -> PlanDiferencias:
    """
    Compara el estado actual (manifest) contra `objetivos` y devuelve el plan
    de operaciones necesario. Nunca inventa una caja: si un objetivo no existe
    y su rol tampoco tiene ninguna caja `clonable_desde` en el manifest, se
    reporta como error en vez de generar una operación imposible.

    IMPORTANTE (seguridad): el borrado es SIEMPRE explícito vía `eliminar_ids`
    — un recurso del manifest que simplemente no aparece en `objetivos` NO se
    borra. Omitir un rol del objetivo no debe implicar destruirlo en Quark.

    NOTA sobre `clonable_desde`: solo se buscan orígenes de clonado DENTRO del
    `manifest` recibido. Si se lo filtró a una sola página (recursos_de_pagina),
    no vas a encontrar las plantillas parqueadas en el pasteboard de OTRAS
    variantes (page con sufijo '*'/'**') que PegarNota_JSON.js usa como origen
    real de clonado. Para permitir clonar, pasar el manifest completo del
    documento (o incluir explícitamente esas cajas parqueadas).
    """
    plan = PlanDiferencias()
    eliminar_ids = eliminar_ids or set()

    # Índice rol -> primera caja clonable vista en el manifest (plantilla origen).
    clonables_por_rol: dict[str, str] = {}
    for r in (manifest or {}).get("recursos", []):
        rol = r.get("rol")
        if rol and rol not in clonables_por_rol and r.get("clonable_desde"):
            clonables_por_rol[rol] = r["clonable_desde"]

    for obj in objetivos:
        actual = recurso_por_id(manifest, obj.id)
        if actual is not None:
            # Ya existe: mover/redimensionar solo si cambió más que la tolerancia.
            box = actual["box_name"]
            movio = (
                abs((actual.get("left_mm") or 0) - obj.left_mm) > _TOLERANCIA_MM
                or abs((actual.get("top_mm") or 0) - obj.top_mm) > _TOLERANCIA_MM
            )
            redimensiono = (
                abs((actual.get("width_mm") or 0) - obj.width_mm) > _TOLERANCIA_MM
                or abs((actual.get("height_mm") or 0) - obj.height_mm) > _TOLERANCIA_MM
            )
            if movio or redimensiono:
                plan.operaciones.append(Operacion(
                    tipo="redimensionar" if redimensiono else "mover",
                    box_name=box,
                    left_mm=obj.left_mm, top_mm=obj.top_mm,
                    width_mm=obj.width_mm, height_mm=obj.height_mm,
                    page=obj.page,
                    nota=f"objetivo {obj.id}",
                ))
            continue

        # No existe: hace falta clonar desde una caja del mismo rol.
        origen = clonables_por_rol.get(obj.rol)
        if not origen:
            plan.errores.append(
                f"No se puede crear '{obj.id}' (rol '{obj.rol}'): la maqueta no tiene "
                "ninguna caja existente de ese rol para clonar (QX.js no crea cajas "
                "desde cero)."
            )
            continue
        nuevo_nombre = _slugify_id(obj.id)
        plan.operaciones.append(Operacion(
            tipo="clonar",
            origen_box=origen,
            nuevo_box_name=nuevo_nombre,
            left_mm=obj.left_mm, top_mm=obj.top_mm,
            width_mm=obj.width_mm, height_mm=obj.height_mm,
            page=obj.page,
            nota=f"objetivo {obj.id} (clonado de {origen})",
        ))

    # Borrado EXPLÍCITO únicamente (ver nota de seguridad en el docstring).
    for rid in eliminar_ids:
        r = recurso_por_id(manifest, rid)
        if r is None:
            plan.errores.append(f"No se puede eliminar '{rid}': no está en el manifest.")
            continue
        plan.operaciones.append(Operacion(
            tipo="eliminar", box_name=r["box_name"],
            nota=f"recurso '{rid}' marcado para eliminar explícitamente",
        ))

    return plan


# ----------------------------------------------------------------------
# Asistente: "poner tantas imágenes como pueda" en un área disponible.
# ----------------------------------------------------------------------

def planificar_grilla_fotos(
    area_left_mm: float, area_top_mm: float, area_width_mm: float, area_height_mm: float,
    foto_width_mm: float, foto_height_mm: float,
    gap_mm: float = 3.0, rol: str = "foto_secundaria", id_prefijo: str = "foto_secundaria",
) -> list[RecursoObjetivo]:
    """
    Calcula cuántas fotos de tamaño (foto_width_mm × foto_height_mm) entran en
    una grilla simple (fila por fila) dentro del área disponible, con `gap_mm`
    de separación. Devuelve la lista de RecursoObjetivo con sus posiciones —
    "poner tantas imágenes como pueda" resuelto como asistencia de layout, sin
    pretender ser un empaquetador óptimo (bin-packing).
    """
    if foto_width_mm <= 0 or foto_height_mm <= 0 or area_width_mm <= 0 or area_height_mm <= 0:
        return []
    cols = max(0, math.floor((area_width_mm + gap_mm) / (foto_width_mm + gap_mm)))
    filas = max(0, math.floor((area_height_mm + gap_mm) / (foto_height_mm + gap_mm)))
    objetivos: list[RecursoObjetivo] = []
    n = 0
    for fila in range(filas):
        for col in range(cols):
            n += 1
            x = area_left_mm + col * (foto_width_mm + gap_mm)
            y = area_top_mm + fila * (foto_height_mm + gap_mm)
            rid = id_prefijo if n == 1 else f"{id_prefijo}_{n}"
            objetivos.append(RecursoObjetivo(
                id=rid, rol=rol, left_mm=x, top_mm=y,
                width_mm=foto_width_mm, height_mm=foto_height_mm,
            ))
    return objetivos
