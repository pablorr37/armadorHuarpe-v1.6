"""
Schema del Armado automático — única fuente de verdad (en datos) para:
  * el asistente de calibración (qué áreas/puntos pedir y en qué orden), y
  * el ejecutor (`_PaginaWorker`), que sabe qué recursos colocar y con qué claves.

Modelo:
  Cada qxp de maqueta tiene 3 PLANTILLAS (variantes). Los recursos movibles se
  clonan (Ctrl+D) y se arrastran a su posición, una vez por plantilla → cada
  recurso movible tiene `src` (área a seleccionar) + 3 destinos `*_dst_1..3`.
  Firma/epígrafe son reemplazos de texto (copiar del box universal → reemplazar
  en el cuerpo con Ctrl+Alt+U), también por plantilla.

Las claves resultantes (para config.ini [AUTO]) se derivan de `clave` + sufijo:
  - tipo "punto": una clave (p.ej. "play")           → config.auto_coord("play")
  - tipo "area", sin n: una clave (p.ej. "firma_src")  → config.auto_area("firma_src")
  - tipo "area", n=3:  "firma_dst_1".."firma_dst_3"    → config.auto_area("firma_dst_2")
"""
from __future__ import annotations

import unicodedata

PLANTILLAS = 3  # 3 variantes por qxp


def normalizar_seccion(s) -> str:
    """minúsculas + sin acentos, para comparar/guardar secciones de forma estable."""
    s = (s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")
ZOOM_ARMADO = "22"  # % de zoom con el que se calibra/arma (Quark no abre a este zoom por defecto)

# Cada paso: clave, tipo ("punto"|"area"), desc, opcional n (repeticiones por plantilla),
# y opcional "recurso" (para el gating desde composicion_pagina).
PASOS_CALIBRACION = [
    # Área numérica de zoom (abajo-izq. de Quark). El automatizador escribe 22 + Enter ahí
    # antes de colocar recursos, para que los arrastres caigan en las coords calibradas.
    {"clave": "zoom", "tipo": "area",
     "desc": ("el área numérica del ZOOM de Quark (abajo a la izq.). Elegí un % que permita ver "
              "las 3 plantillas y TODOS los recursos a la vez — 22% en pantalla 1366×768.")},

    # Palette del script (pegado base c) — puntos de clic
    {"clave": "script", "tipo": "punto", "desc": "el ítem 'Pegar Auto.js' del palette JavaScript"},
    {"clave": "play",   "tipo": "punto", "desc": "el botón Play ▶ del palette JavaScript"},

    # d) Firma: origen (box universal) + destino en cuerpo por plantilla
    {"clave": "firma_src", "tipo": "area", "recurso": "firma",
     "desc": "el box UNIVERSAL de FIRMA (origen a copiar)"},
    {"clave": "firma_dst", "tipo": "area", "n": PLANTILLAS, "recurso": "firma",
     "desc": "el texto de FIRMA en el cuerpo — plantilla {i}"},

    # e) Epígrafe: origen + destino por plantilla
    {"clave": "epigrafe_src", "tipo": "area", "recurso": "epigrafe",
     "desc": "el box de EPÍGRAFE de origen"},
    {"clave": "epigrafe_dst", "tipo": "area", "n": PLANTILLAS, "recurso": "epigrafe",
     "desc": "el EPÍGRAFE en el cuerpo — plantilla {i}"},

    # f) Recursos movibles: clonar (Ctrl+D) + arrastrar, por plantilla.
    #    Tras marcar el `src`, el calibrador clona el recurso en Quark; el usuario marca en
    #    `clon` DÓNDE quedó el clon (punto de agarre B). En cada `dst_i` el calibrador arrastra
    #    ese clon al destino para verificar (y deshace con Ctrl+Z). En ejecución se agarra en B.
    {"clave": "textual_src", "tipo": "area", "recurso": "textual", "desc": "la caja de TEXTUAL"},
    {"clave": "textual_clon", "tipo": "area", "recurso": "textual",
     "desc": "el CLON del TEXTUAL (se acaba de duplicar): marcá dónde quedó"},
    {"clave": "textual_dst", "tipo": "area", "n": PLANTILLAS, "recurso": "textual",
     "desc": "destino del TEXTUAL — plantilla {i}"},

    {"clave": "dato_src", "tipo": "area", "recurso": "dato", "desc": "la caja de DATO"},
    {"clave": "dato_clon", "tipo": "area", "recurso": "dato",
     "desc": "el CLON del DATO (se acaba de duplicar): marcá dónde quedó"},
    {"clave": "dato_dst", "tipo": "area", "n": PLANTILLAS, "recurso": "dato",
     "desc": "destino del DATO — plantilla {i}"},

    {"clave": "numero_src", "tipo": "area", "recurso": "numero", "desc": "la caja de NÚMERO"},
    {"clave": "numero_clon", "tipo": "area", "recurso": "numero",
     "desc": "el CLON del NÚMERO (se acaba de duplicar): marcá dónde quedó"},
    {"clave": "numero_dst", "tipo": "area", "n": PLANTILLAS, "recurso": "numero",
     "desc": "destino del NÚMERO — plantilla {i}"},

    {"clave": "qr_src", "tipo": "area", "recurso": "qr", "desc": "la caja de QR"},
    {"clave": "qr_clon", "tipo": "area", "recurso": "qr",
     "desc": "el CLON del QR (se acaba de duplicar): marcá dónde quedó"},
    {"clave": "qr_dst", "tipo": "area", "n": PLANTILLAS, "recurso": "qr",
     "desc": "destino del QR — plantilla {i}"},

    # g) Foto a 3 columnas ancha — TEMPORALMENTE DESHABILITADO (no se calibra ni se ejecuta).
    #    Para reactivar: descomentar estos pasos y el bloque foto3 en _PaginaWorker.run.
    # {"clave": "foto_src", "tipo": "area", "recurso": "foto3", "desc": "la caja de FOTO"},
    # {"clave": "foto_dst", "tipo": "area", "n": PLANTILLAS, "recurso": "foto3",
    #  "desc": "posición de la FOTO a 3 columnas — plantilla {i}"},
    # {"clave": "foto_edge", "tipo": "area", "n": PLANTILLAS, "recurso": "foto3",
    #  "desc": "el BORDE DERECHO de la caja de foto — plantilla {i}"},
    # {"clave": "foto_rlimit", "tipo": "area", "n": PLANTILLAS, "recurso": "foto3",
    #  "desc": "el LÍMITE DERECHO de la maqueta — plantilla {i}"},
]

# Recursos movibles (clonar + arrastrar). Firma/epígrafe NO (son reemplazos).
RECURSOS_MOVIBLES = ["textual", "dato", "numero", "qr"]

# Tipos de aviso (para calibrar una maqueta distinta por sección + aviso). El valor coincide
# con composicion_pagina()['aviso_tipo']; "" = sin aviso. El label es para la UI del calibrador.
AVISO_TIPOS = [
    ("", "Sin aviso"),
    ("full", "Completa"),
    ("half", "Media"),
    ("footer", "Pie de página"),
    ("robapagina", "Robapágina"),
]


def token_aviso(aviso_tipo) -> str:
    """Token estable del tipo de aviso para las claves de calibración. '' → 'sinaviso'."""
    return (aviso_tipo or "").strip().lower() or "sinaviso"


def claves_cascada(seccion, aviso_tipo, clave):
    """Claves de la más específica a la más general, para buscar calibración con fallback:
    '{sec}__{aviso}__{clave}' → '{aviso}__{clave}' → '{clave}'.
    - '{sec}__{aviso}__…': override puntual de una sección con ese aviso.
    - '{aviso}__…': universal para ese aviso (cualquier sección).
    - '{clave}': universal general (fallback último)."""
    sec = normalizar_seccion(seccion) if seccion else ""
    av = token_aviso(aviso_tipo)
    out = []
    if sec:
        out.append(f"{sec}__{av}__{clave}")
    out.append(f"{av}__{clave}")
    out.append(clave)
    return out


def pasos_expandidos():
    """Devuelve la lista concreta de pasos del asistente, expandiendo `n`.
    Cada item: {"clave": <clave concreta>, "tipo", "desc" (con {i} resuelto), "recurso"}."""
    out = []
    for p in PASOS_CALIBRACION:
        n = p.get("n")
        if n:
            for i in range(1, n + 1):
                out.append({
                    "clave": f"{p['clave']}_{i}",
                    "tipo": p["tipo"],
                    "recurso": p.get("recurso"),
                    "desc": p["desc"].replace("{i}", str(i)),
                })
        else:
            out.append({
                "clave": p["clave"],
                "tipo": p["tipo"],
                "recurso": p.get("recurso"),
                "desc": p["desc"].replace("{i}", ""),
            })
    return out


def recurso_activo(comp: dict, recurso: str) -> bool:
    """True si la composición de la página exige colocar `recurso` (gating d–g)."""
    comp = comp or {}
    if recurso == "firma":
        return bool(comp.get("firma"))
    if recurso == "epigrafe":
        # Hay epígrafe si la página lleva foto (el epígrafe acompaña a la foto).
        return bool(comp.get("foto_cant"))
    if recurso == "textual":
        return bool(comp.get("textual"))
    if recurso == "dato":
        return bool(comp.get("dato"))
    if recurso == "numero":
        return bool(comp.get("numero"))
    if recurso == "qr":
        return bool(comp.get("qr"))
    if recurso == "foto3":
        return es_foto_3col_ancha(comp) and bool(comp.get("foto_cant"))
    return False


def es_foto_3col_ancha(comp: dict) -> bool:
    """True si foto_tipo indica '3 columnas ancha/wide' (alineado con foto_3ancha/3wide)."""
    ft = (comp or {}).get("foto_tipo", "") or ""
    ft = ft.lower()
    return ("3" in ft) and ("anch" in ft or "wide" in ft)
