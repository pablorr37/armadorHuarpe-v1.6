"""
Modelo Python del "maquetador" interno de ArmadorHuarpe.

Representa una maqueta como un lienzo (mm) con cajas posicionadas (mm), su rol
editorial, su límite de caracteres y su estilo. Sirve para tres orígenes:
  - PREARMADAS: plantillas del repositorio (maquetas/).
  - REALES: pobladas por el lector CDP (services.maqueta_introspect.leer_maqueta_cdp).
  - DIBUJAR: lienzo en blanco al que el usuario agrega cajas.

Es serializable a JSON (round-trip) y, en fases posteriores, se replicará a
QuarkXPress escribiendo la geometría de las cajas por DOM/JS (ver el spike
scripts/MoverCajaMM_spike.js y el roadmap en docs/).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Caja:
    """Una caja de la maqueta, en milímetros (sistema del layout de Quark)."""
    nombre: str                       # box-name en Quark
    tipo: str = "text"                # "text" | "picture"
    left_mm: float = 0.0
    top_mm: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0
    page: Optional[str] = None        # "1", "1*", … (página/pasteboard)
    rol: Optional[str] = None         # volanta | titulo | bajada | epigrafe | cuerpo | foto | textual | …
    limite: Optional[int] = None      # capacidad de caracteres (medida o estimada)
    # Estilo tipográfico (para estimar capacidad / replicar)
    font_family: Optional[str] = None
    font_size: Optional[float] = None      # pt
    leading: Optional[float] = None        # pt
    text_align: Optional[str] = None
    style_class: Optional[str] = None      # clase de estilo de párrafo (pr-C-…)

    @property
    def right_mm(self) -> float:
        return self.left_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        return self.top_mm + self.height_mm

    def estimar_limite(self, factor: float = 0.98) -> int:
        """Capacidad estimada por geometría + fuente (sin rellenar). 0 si faltan datos."""
        from services.maqueta_introspect import estimar_capacidad
        return estimar_capacidad(
            self.width_mm, self.height_mm, self.font_size,
            self.font_family, self.leading, factor=factor,
        )


@dataclass
class Maqueta:
    """Un lienzo con cajas. `origen` documenta de dónde salió."""
    nombre: str = ""
    canvas_width_mm: float = 0.0
    canvas_height_mm: float = 0.0
    origen: str = "dibujar"           # "prearmada" | "real" | "dibujar"
    source: Optional[str] = None      # ruta .qxp de origen (si es real)
    cajas: list[Caja] = field(default_factory=list)
    # Márgenes de página (mm). Lectura best-effort por CDP, pendiente de
    # validar en vivo (ver scripts/LeerMaquetaCDP.js) — 0.0 si Quark no
    # expone el dato, editable a mano en el maquetador.
    margin_top_mm: float = 0.0
    margin_bottom_mm: float = 0.0
    margin_left_mm: float = 0.0
    margin_right_mm: float = 0.0

    # ── round-trip JSON ──

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Maqueta":
        cajas = [Caja(**c) for c in d.get("cajas", [])]
        data = {k: v for k, v in d.items() if k != "cajas"}
        return cls(cajas=cajas, **data)

    # ── construcción desde el lector CDP ──

    @classmethod
    def from_cdp(cls, data: dict, nombre: str = "") -> "Maqueta":
        """Construye una Maqueta a partir del dict de maqueta_introspect.leer_maqueta_cdp()."""
        canvas = (data or {}).get("canvas") or {}
        mq = cls(
            nombre=nombre,
            canvas_width_mm=canvas.get("width_mm") or 0.0,
            canvas_height_mm=canvas.get("height_mm") or 0.0,
            origen="real",
            source=(data or {}).get("source"),
            margin_top_mm=canvas.get("margin_top_mm") or 0.0,
            margin_bottom_mm=canvas.get("margin_bottom_mm") or 0.0,
            margin_left_mm=canvas.get("margin_left_mm") or 0.0,
            margin_right_mm=canvas.get("margin_right_mm") or 0.0,
        )
        for b in (data or {}).get("boxes", []):
            caja = Caja(
                nombre=b.get("name", ""),
                tipo=b.get("type") or "text",
                left_mm=b.get("left_mm") or 0.0,
                top_mm=b.get("top_mm") or 0.0,
                width_mm=b.get("width_mm") or 0.0,
                height_mm=b.get("height_mm") or 0.0,
                page=b.get("page"),
                font_family=b.get("font_family"),
                font_size=b.get("font_size"),
                leading=b.get("leading"),
                text_align=b.get("text_align"),
                style_class=b.get("style_class"),
            )
            if b.get("type") == "text":
                caja.limite = caja.estimar_limite() or (b.get("chars") or None)
            mq.cajas.append(caja)
        return mq

    def caja(self, nombre: str) -> Optional[Caja]:
        return next((c for c in self.cajas if c.nombre == nombre), None)
