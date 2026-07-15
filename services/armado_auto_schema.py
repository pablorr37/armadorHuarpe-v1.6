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
ZOOM_ARMADO = "11"  # % de zoom por defecto (fallback); el valor real es 'zoom_valor' (editable)

# Cada paso: clave, tipo ("punto"|"area"), desc, opcional n (repeticiones por plantilla),
# y opcional "recurso" (para el gating desde composicion_pagina).
PASOS_CALIBRACION = [
    # Área numérica de zoom (abajo-izq. de Quark). El automatizador escribe el zoom (11%, editable
    # en "Valores…") + Enter ahí antes de colocar recursos, para trabajar con la vista calibrada.
    {"clave": "zoom", "tipo": "area",
     "desc": ("el área numérica del ZOOM de Quark (abajo a la izq.). Usá 11% (o el valor que hayas "
              "puesto en «Valores…»), que permite ver las 3 plantillas sin re-centrar la vista.")},

    # Palette del script (pegado base c) — puntos de clic
    {"clave": "script", "tipo": "punto", "desc": "el ítem 'Pegar Auto.js' del palette JavaScript"},
    {"clave": "play",   "tipo": "punto", "desc": "el botón Play ▶ del palette JavaScript"},

    # Bot de export a PDF — modo Script (alternativa al modo Bot/pyautogui). Reusa el mismo
    # botón Play; solo cambia qué ítem del palette está seleccionado antes de tocarlo.
    {"clave": "export_script", "tipo": "punto",
     "desc": "el ítem 'ExportarPDF.js' del palette JavaScript (bot de export a PDF, modo Script)"},

    # Panel de medidas y selector de plantilla (campos donde el bot escribe valores). Globales.
    {"clave": "plantilla_sel", "tipo": "punto",
     "desc": "el SELECTOR DE PLANTILLA (campo donde se escribe 1/2/3 para cambiar de plantilla)"},
    {"clave": "campo_x", "tipo": "punto", "desc": "el campo X (posición horiz.) del panel de medidas"},
    {"clave": "campo_y", "tipo": "punto", "desc": "el campo Y (posición vert.) del panel de medidas"},
    {"clave": "campo_a", "tipo": "punto", "desc": "el campo A (Ancho) del panel de medidas"},
    {"clave": "campo_al", "tipo": "punto", "desc": "el campo Al (Alto) del panel de medidas"},

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

    # f) Recursos movibles: caja de origen (src) a clonar. El clon se posiciona escribiendo X/Y
    #    en el panel (mismos X/Y en las 3 plantillas; el bot cambia de plantilla con el selector).
    #    El src se calibra UNA vez (a 11% la vista no se re-centra al cambiar de plantilla).
    # Todas las variantes de textual comparten el X/Y de 'textual', pero cada una tiene su src.
    {"clave": "textual_src", "tipo": "punto", "recurso": "textual", "desc": "la caja de TEXTUAL simple (origen a clonar)"},
    {"clave": "textual_x2_src", "tipo": "punto", "recurso": "textual", "desc": "la caja de TEXTUAL x2 (origen a clonar)"},
    {"clave": "textual_con_foto_src", "tipo": "punto", "recurso": "textual", "desc": "la caja de TEXTUAL con foto (origen a clonar)"},
    {"clave": "textual_con_foto_xl_src", "tipo": "punto", "recurso": "textual", "desc": "la caja de TEXTUAL con foto XL (origen a clonar)"},
    {"clave": "dato_src", "tipo": "punto", "recurso": "dato", "desc": "la caja de DATO (origen a clonar)"},
    {"clave": "numero_src", "tipo": "punto", "recurso": "numero", "desc": "la caja de NÚMERO (origen a clonar)"},
    {"clave": "qr_src", "tipo": "punto", "recurso": "qr", "desc": "la caja de QR (origen a clonar)"},

    # g) Foto a 3 columnas (wide/ancha): clic sobre cada foto para redimensionarla con A/Al.
    {"clave": "foto_sel", "tipo": "punto", "n": PLANTILLAS, "recurso": "foto3",
     "desc": "clic sobre la FOTO a 3 columnas — plantilla {i}"},
]

# Recursos movibles (clonar + posicionar por X/Y). Firma/epígrafe NO (son reemplazos).
RECURSOS_MOVIBLES = ["textual", "dato", "numero", "qr"]

# El textual tiene variantes por tipo (comp['textual']): cada una clona una caja de origen
# distinta, pero todas se colocan en el MISMO X/Y de 'textual'.
TEXTUAL_SRC_POR_TIPO = {
    "simple": "textual_src",
    "x2": "textual_x2_src",
    "con_foto": "textual_con_foto_src",
    "con_foto_xl": "textual_con_foto_xl_src",
}


def textual_src_key(comp) -> str:
    """Clave del src a clonar para el textual, según su tipo (default: 'textual_src')."""
    return TEXTUAL_SRC_POR_TIPO.get((comp or {}).get("textual") or "", "textual_src")

# Valores numéricos (mm, string con coma decimal) que el bot escribe en el panel de medidas.
# Se exponen/editan en el calibrador ("Valores…") y se guardan por maqueta (cascada sección+aviso);
# estos son los defaults universales.
VALORES_DEFAULT = {
    "zoom_valor": "11",
    # Zoom mayor para pegar en la ÚLTIMA plantilla (contigua a la anterior): a poco zoom Quark
    # pega en la plantilla vecina aunque esté seleccionada la correcta.
    "zoom_valor_final": "60",
    # Cuántos Backspace (⌫) se presionan al escribir X/Y de un recurso, para borrar el signo '-'
    # residual del src negativo. Las fotos usan 0.
    "deletes_recurso": "2",
    "foto_a": "129,574", "foto_al_wide": "69,467", "foto_al_ancha": "82,166",
    # Foto a 4 columnas: posición propia (x/y) + tamaño (A/Al). 4col mueve Y redimensiona.
    "foto_a_4col": "174,577", "foto_al_4col": "82,166",
    "foto_x_4col": "10,424", "foto_y_4col": "63,334",
    # Epígrafe (Box368/504/1866): posición + tamaño por variante de foto (x/y/a/al).
    "epi_x_wide": "55,427", "epi_y_wide": "132,801", "epi_a_wide": "129,575", "epi_al_wide": "10,723",
    "epi_x_ancha": "55,427", "epi_y_ancha": "145,806", "epi_a_ancha": "129,573", "epi_al_ancha": "10,723",
    "epi_x_4col": "10,424", "epi_y_4col": "145,806", "epi_a_4col": "174,576", "epi_al_4col": "10,723",
    # X/Y = posición DESEADA (esquina sup-izq del grupo) en la página, maqueta VACÍA (sin aviso).
    # Son el destino final que debe quedar en la página. moverGrupo (PegarNota v6) le suma la
    # compensación del pasteboard (COMP_X/COMP_Y). El bot los usa directo en el panel de medidas.
    "textual_x": "54,926", "textual_y": "147,089",
    "dato_x": "99,7", "dato_y": "147,089",
    "numero_x": "143,794", "numero_y": "147,089",
    "qr_x": "149,023", "qr_y": "255,543",
}

# Claves de valor que dependen del recurso Y del tipo de aviso (posiciones X/Y). El resto de
# VALORES_EDITABLES son globales (zoom, deletes, foto A/Al). Se cargan por aviso en "Valores…".
VALORES_RECURSO = [f"{rec}_{c}" for rec in RECURSOS_MOVIBLES for c in ("x", "y")]

# Orden en que se muestran en el diálogo "Valores…" (clave, etiqueta).
VALORES_EDITABLES = [
    ("zoom_valor", "Zoom (%)"),
    ("zoom_valor_final", "Zoom última plantilla (%)"),
    ("deletes_recurso", "Borrados ⌫ por campo (recursos)"),
    ("textual_x", "Textual X"), ("textual_y", "Textual Y"),
    ("dato_x", "Dato X"), ("dato_y", "Dato Y"),
    ("numero_x", "Número X"), ("numero_y", "Número Y"),
    ("qr_x", "QR X"), ("qr_y", "QR Y"),
    ("foto_a", "Foto A (Ancho)"),
    ("foto_al_wide", "Foto Al (3 col)"), ("foto_al_ancha", "Foto Al (ancha)"),
    ("foto_a_4col", "Foto A (4 col)"), ("foto_al_4col", "Foto Al (4 col)"),
]


def valor_default(clave: str) -> str:
    """Valor por defecto (universal) de un valor numérico calibrable."""
    return VALORES_DEFAULT.get(clave, "")


def foto3_variante(comp: dict):
    """'wide' | 'ancha' | '4col' | None según foto_tipo. Cubre el rename ('3 columnas' sin
    'ancha' = ex '3 columnas wide') y el legacy con 'wide'. '2 columnas'/'Sin foto'/'' → None."""
    ft = ((comp or {}).get("foto_tipo") or "").lower()
    if not ft or "sin" in ft or "2" in ft:
        return None
    if "4" in ft:
        return "4col"
    if "anch" in ft:
        return "ancha"
    if "3" in ft or "wide" in ft:
        return "wide"
    return None

# Tipos de aviso (para calibrar una maqueta distinta por sección + aviso). El valor coincide
# con composicion_pagina()['aviso_tipo']; "" = sin aviso. El label es para la UI del calibrador.
AVISO_TIPOS = [
    ("", "Sin aviso"),
    ("full", "Completa"),
    ("half", "Media"),
    ("footer", "Pie de página"),
    ("robapagina", "Robapágina"),
    ("doblemedia", "Doble media"),
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
    """True si foto_tipo es una variante que el bot redimensiona (3 col / 3 ancha / 4 col)."""
    return foto3_variante(comp) is not None
