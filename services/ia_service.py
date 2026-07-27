"""
Reescritura de texto periodístico con IA (OpenAI / ChatGPT).

Expone reescritura POR CAMPO (volanta, título, bajada, epígrafe, cuerpo) y
de la NOTA COMPLETA en una sola llamada, respetando el límite de caracteres
de cada campo según la maqueta y preservando sentido, foco, datos y textuales.

La API key se lee del vault del SO (Windows Credential Manager) vía
config_global.openai_api_key — nunca de texto plano.
"""
from __future__ import annotations

import json
import re

from openai import OpenAI

from config.config import config_global
from utils.app_logger import get_logger

_log = get_logger(__name__)

# Campos que sabe reescribir, con su rol editorial y guía de estilo.
CAMPOS = ("volanta", "titulo", "bajada", "epigrafe", "cuerpo")

_ROLES = {
    "volanta": (
        "VOLANTA (antetítulo): línea breve que va ARRIBA del título y aporta "
        "contexto o ubicación temática. Sin punto final. Tono sobrio."
    ),
    "titulo": (
        "TÍTULO (titular principal): frase impactante y clara que sintetiza la "
        "noticia. Sin punto final. No uses comillas salvo que citen algo textual."
    ),
    "bajada": (
        "BAJADA (copete): una o dos oraciones que amplían el título y resumen lo "
        "esencial de la noticia (qué, quién, cuándo, dónde)."
    ),
    "epigrafe": (
        "EPÍGRAFE (pie de foto): describe lo que muestra la imagen de la nota, "
        "de forma concisa y factual."
    ),
    "cuerpo": (
        "CUERPO: el texto completo de la nota. REESCRIBÍ efectivamente la redacción "
        "(mejorá claridad, ritmo y estilo periodístico) — no devuelvas el texto igual. "
        "Conservá la estructura de párrafos y los intertítulos (líneas que empiezan con "
        "'## '), todos los datos y las citas textuales. No agregues ni quites secciones "
        "de contenido."
    ),
}

_SYSTEM = (
    "Sos un redactor y editor profesional de un diario argentino (español "
    "rioplatense neutro). Reescribís textos periodísticos mejorando la redacción "
    "SIN cambiar los hechos.\n"
    "Reglas invariables:\n"
    "1. Mantené el sentido, el foco y la intención de la noticia.\n"
    "2. Conservá TODOS los datos: nombres propios, cargos, lugares, fechas y "
    "cifras, exactamente como están.\n"
    "3. Conservá las citas textuales (lo que está entre comillas) palabra por "
    "palabra; no las parafrasees.\n"
    "4. No inventes ni agregues información que no esté en el original.\n"
    "5. Respetá el límite máximo de caracteres indicado para cada campo.\n"
    "6. Devolvé solo el texto pedido, sin comillas de envoltura ni comentarios."
)


class IAConfigError(RuntimeError):
    """Falta configuración (API key) para usar la IA."""


class AIRewriter:
    def __init__(self, model: str | None = None):
        key = config_global.openai_api_key
        if not key:
            raise IAConfigError(
                "Falta la API key de OpenAI. Configurala en Edición → "
                "Configurar IA…"
            )
        self.model = model or config_global.ia_model
        self.client = OpenAI(api_key=key)

    # ------------------------------------------------------------------
    # Reescritura de un solo campo
    # ------------------------------------------------------------------
    def reescribir_campo(
        self, campo: str, texto: str, limite: int | None = None, contexto: str = ""
    ) -> str:
        """Reescribe UN campo respetando su rol y el límite de caracteres."""
        campo = (campo or "").lower()
        texto = (texto or "").strip()
        if not texto:
            return texto
        rol = _ROLES.get(campo, f"Campo '{campo}'.")

        partes = [f"Reescribí el siguiente campo de una noticia.\n\nCampo: {rol}"]
        if limite and limite > 0:
            partes.append(
                f"\nLÍMITE ESTRICTO: máximo {int(limite)} caracteres "
                f"(el texto actual tiene {len(texto)})."
            )
        if contexto:
            partes.append(f"\nContexto de la nota (solo para coherencia, no lo reescribas):\n{contexto[:1500]}")
        partes.append(f"\nTexto original del campo:\n{texto}\n\nTexto reescrito:")
        prompt = "".join(partes)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )
            out = (resp.choices[0].message.content or "").strip()
            out = _limpiar_envoltura(out)
            if limite and limite > 0 and len(out) > limite:
                out = self._acortar(campo, out, limite)
            return out
        except Exception as e:  # noqa: BLE001
            _log.error("Error IA reescribir_campo(%s): %s", campo, e)
            raise RuntimeError(f"Error al contactar la API: {e}")

    def _acortar(self, campo: str, texto: str, limite: int) -> str:
        """Segunda pasada para ajustar un campo que excedió el límite."""
        rol = _ROLES.get(campo, f"Campo '{campo}'.")
        prompt = (
            f"El siguiente texto ({rol}) tiene {len(texto)} caracteres y debe tener "
            f"como máximo {int(limite)}. Acortalo manteniendo los datos, las citas "
            f"textuales y el sentido. Devolvé solo el texto.\n\n{texto}"
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            out = _limpiar_envoltura((resp.choices[0].message.content or "").strip())
            return out or texto
        except Exception:  # noqa: BLE001
            return texto

    # ------------------------------------------------------------------
    # Reescritura de la nota completa (una sola llamada, salida JSON)
    # ------------------------------------------------------------------
    def reescribir_nota_completa(
        self, datos: dict, limites: dict | None = None
    ) -> dict:
        """
        Reescribe todos los campos presentes en `datos` a la vez.
        `datos`   : {campo: texto} con las claves de CAMPOS que tengan contenido.
        `limites` : {campo: int} límite de caracteres por campo (opcional).
        Devuelve  : {campo: texto_reescrito} solo para los campos de entrada.
        """
        limites = limites or {}
        presentes = {c: (datos.get(c) or "").strip() for c in CAMPOS if (datos.get(c) or "").strip()}
        if not presentes:
            return {}

        out: dict = {}

        # El CUERPO se reescribe SIEMPRE con su propia llamada: dentro del JSON de la
        # nota completa el modelo suele omitirlo o devolverlo casi igual (texto largo).
        cuerpo_txt = presentes.pop("cuerpo", None)

        # Campos cortos (volanta/título/bajada/epígrafe): una sola llamada JSON.
        if presentes:
            lineas = ["Reescribí los campos de esta noticia. Devolvé un objeto JSON con "
                      "exactamente estas claves y el texto reescrito de cada una:\n"]
            for c, _txt in presentes.items():
                lim = limites.get(c)
                cab = f"- {c} — {_ROLES.get(c, c)}"
                if lim and lim > 0:
                    cab += f" (máx {int(lim)} caracteres)"
                lineas.append(cab)
            lineas.append("\nContenido actual de cada campo:")
            lineas.append(json.dumps(presentes, ensure_ascii=False, indent=2))
            lineas.append(
                "\nRespondé ÚNICAMENTE con el JSON, con las mismas claves, "
                "manteniendo coherencia entre volanta, título, bajada y cuerpo."
            )
            prompt = "\n".join(lineas)
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.4,
                    response_format={"type": "json_object"},
                )
                raw = (resp.choices[0].message.content or "{}").strip()
                data = json.loads(raw)
            except Exception as e:  # noqa: BLE001
                _log.error("Error IA reescribir_nota_completa (campos cortos): %s", e)
                raise RuntimeError(f"Error al contactar la API: {e}")

            for c in presentes:
                val = data.get(c)
                if isinstance(val, str) and val.strip():
                    val = _limpiar_envoltura(val.strip())
                    lim = limites.get(c)
                    if lim and lim > 0 and len(val) > lim:
                        val = self._acortar(c, val, lim)
                    out[c] = val
                else:
                    # Fallback: el JSON omitió este campo → reescribirlo individualmente.
                    _log.info("IA nota completa: campo '%s' ausente en JSON → fallback individual.", c)
                    indiv = self.reescribir_campo(c, presentes[c], limites.get(c),
                                                  contexto=datos.get("titulo", ""))
                    if indiv and indiv.strip():
                        out[c] = indiv

        # Cuerpo: llamada dedicada (fiable para texto largo).
        if cuerpo_txt:
            contexto = f"Título: {datos.get('titulo', '')}".strip()
            cuerpo_nuevo = self.reescribir_campo("cuerpo", cuerpo_txt, limites.get("cuerpo"),
                                                 contexto=contexto)
            if cuerpo_nuevo and cuerpo_nuevo.strip():
                out["cuerpo"] = cuerpo_nuevo

        _log.info("IA nota completa: reescritos %s.", sorted(out.keys()))
        return out

    # ------------------------------------------------------------------
    # Compatibilidad con el código existente (dialogo_pool_editor)
    # ------------------------------------------------------------------
    def reescribir_cuerpo(self, texto: str) -> str:
        return self.reescribir_campo("cuerpo", texto)


def _limpiar_envoltura(texto: str) -> str:
    """Quita comillas/etiquetas de envoltura que a veces agrega el modelo."""
    t = texto.strip()
    # Fences de código accidentales
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    # Comillas envolviendo todo el texto
    if len(t) >= 2 and t[0] in "\"“'" and t[-1] in "\"”'":
        t = t[1:-1].strip()
    # Prefijos tipo "Texto reescrito:"
    t = re.sub(r"^(texto reescrito|reescrito|resultado)\s*:\s*", "", t, flags=re.IGNORECASE)
    return t
