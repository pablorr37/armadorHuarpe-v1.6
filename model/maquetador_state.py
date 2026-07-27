"""
Estado editable del maquetador visual (F3+F4). Python puro (sin PyQt salvo la
llamada indirecta a estimar_capacidad, que ya requiere QFontMetricsF) — se
puede testear sin instanciar ningún QGraphicsItem/widget.

No toca Quark en ningún punto: trabaja sobre el manifest ya leído
(services/maqueta_manifest.py) y produce un PlanDiferencias (model/recurso_plan.py)
que, en un ciclo posterior con autorización explícita, se aplicaría por CDP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from model.maqueta_model import Caja, Maqueta
from model.recurso_plan import RecursoObjetivo


def es_pasteboard(page: str | None) -> bool:
    """Un recurso está 'parqueado' (de repuesto) si su página trae el sufijo
    '*'/'**' que usa LeerMaquetaCDP.js para las cajas fuera del área de página."""
    return bool(page) and "*" in page


@dataclass
class RecursoEditable:
    """Un recurso (caja) tal como lo ve el operador en el canvas del
    maquetador — refleja un recurso del manifest, o uno nuevo clonado/creado
    durante la sesión de edición."""
    id: str
    rol: Optional[str]
    tipo: str                          # "text" | "picture"
    box_name: Optional[str]            # None si todavía no se materializó (clon pendiente)
    left_mm: float
    top_mm: float
    width_mm: float
    height_mm: float
    page: Optional[str] = None
    en_pasteboard: bool = False
    origen_clon: Optional[str] = None  # box_name origen (clonable_desde heredado)
    capacidad: Optional[int] = None
    font_family: Optional[str] = None
    font_size: Optional[float] = None
    leading: Optional[float] = None
    style_class: Optional[str] = None
    marcado_eliminar: bool = False
    es_nuevo: bool = False

    @classmethod
    def desde_recurso_manifest(cls, r: dict) -> "RecursoEditable":
        page = r.get("page")
        return cls(
            id=r["id"], rol=r.get("rol"), tipo=r.get("tipo") or "text",
            box_name=r.get("box_name"),
            left_mm=r.get("left_mm") or 0.0, top_mm=r.get("top_mm") or 0.0,
            width_mm=r.get("width_mm") or 0.0, height_mm=r.get("height_mm") or 0.0,
            page=page, en_pasteboard=es_pasteboard(page),
            origen_clon=r.get("clonable_desde"),
            capacidad=r.get("capacidad"),
        )


@dataclass
class MaquetadorDocumento:
    """Documento en memoria que edita el operador. `manifest_original` se
    conserva ÍNTEGRO (incluidas las cajas de pasteboard) porque
    calcular_diferencias() busca `clonable_desde` dentro del manifest que se
    le pasa — recortarlo a lo visible en el canvas rompería el clonado."""
    maqueta: Maqueta
    manifest_original: dict
    recursos: dict[str, RecursoEditable] = field(default_factory=dict)
    _seq: int = 0

    @classmethod
    def desde_manifest(cls, maqueta: Maqueta, manifest: dict) -> "MaquetadorDocumento":
        doc = cls(maqueta=maqueta, manifest_original=manifest)
        for r in (manifest or {}).get("recursos", []):
            doc.recursos[r["id"]] = RecursoEditable.desde_recurso_manifest(r)
        return doc

    # ── edición ──

    def mover(self, id_: str, left_mm: float, top_mm: float) -> None:
        r = self.recursos[id_]
        r.left_mm, r.top_mm = left_mm, top_mm

    def redimensionar(self, id_: str, width_mm: float, height_mm: float) -> None:
        r = self.recursos[id_]
        r.width_mm, r.height_mm = max(0.0, width_mm), max(0.0, height_mm)
        self.recalcular_capacidad(id_)

    def _nuevo_id(self, rol: str) -> str:
        n = 1
        candidato = rol
        existentes = self.recursos
        while candidato in existentes:
            n += 1
            candidato = f"{rol}_{n}"
        return candidato

    def clonar_recurso(self, rol: str, desde_id: Optional[str] = None) -> RecursoEditable:
        """Crea un RecursoEditable nuevo (es_nuevo=True, box_name=None) a
        partir de un recurso existente del mismo rol (repuesto o en uso). El
        recurso origen NO se modifica — Quark solo clona, nunca convierte el
        original en la instancia final (ver docs/maquetador_arquitectura.md)."""
        origen: Optional[RecursoEditable] = None
        if desde_id is not None:
            origen = self.recursos.get(desde_id)
        if origen is None:
            for r in self.recursos.values():
                if r.rol == rol:
                    origen = r
                    break
        if origen is None:
            raise ValueError(f"No hay ningún recurso de rol '{rol}' del cual clonar.")

        nuevo_id = self._nuevo_id(rol)
        nuevo = RecursoEditable(
            id=nuevo_id, rol=rol, tipo=origen.tipo, box_name=None,
            left_mm=origen.left_mm, top_mm=origen.top_mm,
            width_mm=origen.width_mm, height_mm=origen.height_mm,
            page=origen.page, en_pasteboard=False,
            origen_clon=origen.box_name or origen.origen_clon,
            font_family=origen.font_family, font_size=origen.font_size,
            leading=origen.leading, style_class=origen.style_class,
            es_nuevo=True,
        )
        self.recursos[nuevo_id] = nuevo
        self.recalcular_capacidad(nuevo_id)
        return nuevo

    def marcar_eliminar(self, id_: str, eliminar: bool = True) -> None:
        self.recursos[id_].marcado_eliminar = eliminar

    def agregar_recurso_custom(self, nombre: str, rol: str, tipo: str = "text") -> RecursoEditable:
        """Registra un rol nuevo (recurso custom del panel de recursos) sin
        materializarlo — queda disponible para clonar_recurso() en cuanto el
        operador lo arrastre y haya (o se agregue) un repuesto de ese rol."""
        rid = nombre if nombre not in self.recursos else self._nuevo_id(nombre)
        nuevo = RecursoEditable(
            id=rid, rol=rol, tipo=tipo, box_name=None,
            left_mm=0.0, top_mm=0.0, width_mm=0.0, height_mm=0.0,
            en_pasteboard=True, es_nuevo=True,
        )
        self.recursos[rid] = nuevo
        return nuevo

    def recalcular_capacidad(self, id_: str) -> Optional[int]:
        r = self.recursos[id_]
        if r.tipo != "text":
            return None
        from services.maqueta_introspect import estimar_capacidad
        r.capacidad = estimar_capacidad(
            r.width_mm, r.height_mm, r.font_size, r.font_family, r.leading,
        ) or None
        return r.capacidad

    def roles_con_repuesto(self) -> set[str]:
        """Roles que tienen al menos un recurso (en uso o en pasteboard) del
        cual clonar_recurso() podría partir."""
        return {r.rol for r in self.recursos.values() if r.rol}

    # ── traducción a PlanDiferencias ──

    def a_objetivos(self) -> tuple[list[RecursoObjetivo], set[str]]:
        objetivos: list[RecursoObjetivo] = []
        eliminar_ids: set[str] = set()
        for r in self.recursos.values():
            if r.marcado_eliminar:
                if not r.es_nuevo:
                    eliminar_ids.add(r.id)
                continue
            if r.rol is None:
                continue
            objetivos.append(RecursoObjetivo(
                id=r.id, rol=r.rol, left_mm=r.left_mm, top_mm=r.top_mm,
                width_mm=r.width_mm, height_mm=r.height_mm, page=r.page,
            ))
        return objetivos, eliminar_ids

    # ── persistencia propia del editor (no confundir con maquetas_cache.json) ──

    def to_dict(self) -> dict:
        return {
            "maqueta": self.maqueta.to_dict(),
            "manifest_original": self.manifest_original,
            "recursos": {rid: vars(r) for rid, r in self.recursos.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MaquetadorDocumento":
        doc = cls(
            maqueta=Maqueta.from_dict(d["maqueta"]),
            manifest_original=d.get("manifest_original") or {},
        )
        for rid, rd in (d.get("recursos") or {}).items():
            doc.recursos[rid] = RecursoEditable(**rd)
        return doc

    # ── conversión a Caja/Maqueta para guardar en el pool ──

    def a_cajas(self) -> list[Caja]:
        """Cajas resultantes (excluye las marcadas para eliminar) para
        persistir como entrada del pool de maquetas."""
        cajas = []
        for r in self.recursos.values():
            if r.marcado_eliminar:
                continue
            cajas.append(Caja(
                nombre=r.box_name or r.id, tipo=r.tipo,
                left_mm=r.left_mm, top_mm=r.top_mm,
                width_mm=r.width_mm, height_mm=r.height_mm,
                page=r.page, rol=r.rol, limite=r.capacidad,
                font_family=r.font_family, font_size=r.font_size,
                leading=r.leading, style_class=r.style_class,
            ))
        return cajas
