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
    es_nuevo: bool = False
    grupo_id: Optional[str] = None      # id compartido por los miembros de un recurso-grupo rígido (textual/dato/numero/qr)
    grupo_campo: Optional[str] = None   # sub-slot dentro del grupo (ej. "texto", "graf", "campo_1")
    box_name_deseado: Optional[str] = None  # nombre determinístico (services.maquetador_nomenclatura) a usar al clonar

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
            grupo_id=r.get("grupo_id"), grupo_campo=r.get("grupo_campo"),
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

    def miembros_del_grupo(self, grupo_id: str) -> list[RecursoEditable]:
        return [r for r in self.recursos.values() if r.grupo_id == grupo_id]

    def mover(self, id_: str, left_mm: float, top_mm: float) -> None:
        r = self.recursos[id_]
        if r.grupo_id:
            dx, dy = left_mm - r.left_mm, top_mm - r.top_mm
            for miembro in self.miembros_del_grupo(r.grupo_id):
                miembro.left_mm += dx
                miembro.top_mm += dy
            return
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

    def _siguiente_indice(self, rol: str) -> int:
        """Cuenta instancias EN USO (no repuestos de pasteboard) de un rol,
        para la nomenclatura determinística rol_N (services.maquetador_nomenclatura).
        El repuesto nunca cuenta como índice 1 — el primer clon materializado sí."""
        return 1 + sum(1 for r in self.recursos.values() if r.rol == rol and not r.en_pasteboard)

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

        from services.maquetador_nomenclatura import ROLES_SIMPLES, formatear_box_name

        nuevo_id = self._nuevo_id(rol)
        box_name_deseado = (
            formatear_box_name(rol, self._siguiente_indice(rol)) if rol in ROLES_SIMPLES else None
        )
        nuevo = RecursoEditable(
            id=nuevo_id, rol=rol, tipo=origen.tipo, box_name=None,
            left_mm=origen.left_mm, top_mm=origen.top_mm,
            width_mm=origen.width_mm, height_mm=origen.height_mm,
            page=origen.page, en_pasteboard=False,
            origen_clon=origen.box_name or origen.origen_clon,
            font_family=origen.font_family, font_size=origen.font_size,
            leading=origen.leading, style_class=origen.style_class,
            es_nuevo=True, box_name_deseado=box_name_deseado,
        )
        self.recursos[nuevo_id] = nuevo
        self.recalcular_capacidad(nuevo_id)
        return nuevo

    def clonar_recurso_compuesto(self, rol_grupo: str, desde_grupo_id: Optional[str] = None) -> list[RecursoEditable]:
        """Clona TODAS las cajas de un recurso-grupo rígido (textual/dato/
        numero/qr) a la vez, preservando sus offsets relativos reales
        (medidos de la geometría de los repuestos, no de una tabla
        hardcodeada) y asignándoles el mismo grupo_id — se mueven siempre
        juntas (ver MaquetadorDocumento.mover)."""
        from services.maquetador_nomenclatura import ROLES_GRUPO, formatear_box_name

        campos = ROLES_GRUPO.get(rol_grupo)
        if not campos:
            raise ValueError(f"'{rol_grupo}' no es un recurso-grupo conocido.")

        repuestos = [
            r for r in self.recursos.values()
            if r.rol == rol_grupo and r.en_pasteboard
            and (desde_grupo_id is None or r.grupo_id == desde_grupo_id)
        ]
        if not repuestos:
            raise ValueError(f"No hay ningún repuesto de grupo '{rol_grupo}' del cual clonar.")
        repuestos.sort(key=lambda r: campos.index(r.grupo_campo) if r.grupo_campo in campos else 999)
        base = repuestos[0]

        indice = self._siguiente_indice(rol_grupo)
        grupo_id = f"{rol_grupo}_{indice}"
        nuevos: list[RecursoEditable] = []
        for repuesto in repuestos:
            dx, dy = repuesto.left_mm - base.left_mm, repuesto.top_mm - base.top_mm
            nuevo_id = self._nuevo_id(f"{rol_grupo}_{repuesto.grupo_campo}")
            nuevo = RecursoEditable(
                id=nuevo_id, rol=rol_grupo, tipo=repuesto.tipo, box_name=None,
                left_mm=base.left_mm + dx, top_mm=base.top_mm + dy,
                width_mm=repuesto.width_mm, height_mm=repuesto.height_mm,
                page=repuesto.page, en_pasteboard=False,
                origen_clon=repuesto.box_name or repuesto.origen_clon,
                font_family=repuesto.font_family, font_size=repuesto.font_size,
                leading=repuesto.leading, style_class=repuesto.style_class,
                es_nuevo=True, grupo_id=grupo_id, grupo_campo=repuesto.grupo_campo,
                box_name_deseado=formatear_box_name(rol_grupo, indice, repuesto.grupo_campo),
            )
            self.recursos[nuevo_id] = nuevo
            self.recalcular_capacidad(nuevo_id)
            nuevos.append(nuevo)
        return nuevos

    def eliminar_recurso(self, id_: str) -> RecursoEditable:
        """Elimina el recurso directamente (sin soft-delete). Devuelve el
        objeto quitado para que el QUndoCommand pueda reinsertarlo en undo()."""
        return self.recursos.pop(id_)

    def restaurar_recurso(self, recurso: RecursoEditable) -> None:
        """Contraparte de eliminar_recurso() — usada por undo()."""
        self.recursos[recurso.id] = recurso

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
        """El borrado se infiere solo, sin ningún flag: un id que estaba en
        el manifest original y ya no está en self.recursos (porque se llamó
        eliminar_recurso) se traduce en una operación 'eliminar'. Un recurso
        es_nuevo que se elimina simplemente desaparece de ambos conjuntos —
        nunca estuvo en manifest_original, así que no genera nada."""
        objetivos: list[RecursoObjetivo] = []
        for r in self.recursos.values():
            if r.rol is None:
                continue
            objetivos.append(RecursoObjetivo(
                id=r.id, rol=r.rol, left_mm=r.left_mm, top_mm=r.top_mm,
                width_mm=r.width_mm, height_mm=r.height_mm, page=r.page,
                box_name_deseado=r.box_name_deseado,
            ))
        ids_originales = {r.get("id") for r in (self.manifest_original or {}).get("recursos", [])}
        eliminar_ids = ids_originales - set(self.recursos.keys())
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
            # Tolerar sesiones guardadas con el ciclo anterior (soft-delete).
            rd = {k: v for k, v in rd.items() if k != "marcado_eliminar"}
            doc.recursos[rid] = RecursoEditable(**rd)
        return doc

    # ── conversión a Caja/Maqueta para guardar en el pool ──

    def a_cajas(self) -> list[Caja]:
        """Cajas resultantes para persistir como entrada del pool de maquetas."""
        cajas = []
        for r in self.recursos.values():
            cajas.append(Caja(
                nombre=r.box_name or r.id, tipo=r.tipo,
                left_mm=r.left_mm, top_mm=r.top_mm,
                width_mm=r.width_mm, height_mm=r.height_mm,
                page=r.page, rol=r.rol, limite=r.capacidad,
                font_family=r.font_family, font_size=r.font_size,
                leading=r.leading, style_class=r.style_class,
            ))
        return cajas
