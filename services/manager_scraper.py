from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse
import re
import html as ihtml
import requests
from typing import Iterable
from services.file_service import FileService, FileServiceError, _write_text
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from html import unescape
import qrcode
import getpass
import time
import random
import json
from datetime import datetime
from utils.app_logger import get_logger

_log = get_logger(__name__)


try:
    from bs4 import BeautifulSoup  
except Exception:  # fallback mínimo si no hay bs4
    BeautifulSoup = None


@dataclass
class NoteData:
    volanta: str = ""
    titulo: str = ""
    bajada: str = ""
    firma: str = ""
    epigrafe: str = ""
    cuerpo: str = ""

    # Puede ser List[str] (legacy) o List[dict] (nuevo)
    image_urls: List[str] | List[dict] | None = None  
    qr_links: List[str] | None = None

    estado_pub: str = "NP"

    # Nuevos campos: siempre vienen del Manager
    autor_creacion: str = ""
    autor_modificacion: str = ""
    fecha_creacion: str = ""
    fecha_modificacion: str = ""

    # Opcional: para no principales
    galeria: List[dict] | None = None
    firmado: bool = False
    quotes: list = None
    quotes_especiales: list = None   # textuales del bloque "Textuales" (secciones especiales)

    def __post_init__(self):
        if self.quotes is None:
            self.quotes = []
        if self.quotes_especiales is None:
            self.quotes_especiales = []

    

class ScraperError(FileServiceError):
    pass


def _norm_txt(s: str) -> str:
    """trim + minúsculas + sin acentos (para comparar el encabezado 'Textuales')."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _limpiar_cita(s: str) -> str:
    s = (s or "")
    for ch in ("“", "‟", "«", "‹", "”", "„", "»", "›"):
        s = s.replace(ch, '"')
    return re.sub(r"\s+", " ", s).strip()


def _secciones_textuales_norm() -> set:
    """Conjunto normalizado de secciones especiales (textuales del bloque 'Textuales')."""
    try:
        from config.config import config_global
        return {_norm_txt(s) for s in config_global.secciones_textuales}
    except Exception:
        return set()


def _textuales_bloque_textuales(soup) -> list:
    """Textuales del bloque 'Textuales': localiza el encabezado h1..h6 cuyo texto sea
    'textuales' y toma cada <p> de los <blockquote> hermanos siguientes (hasta el próximo
    encabezado). Paralelo del `textualesDeBloqueTextuales` de la extensión."""
    if soup is None:
        return []
    HEADS = ("h1", "h2", "h3", "h4", "h5", "h6")
    head = None
    for h in soup.find_all(list(HEADS)):
        if _norm_txt(h.get_text(" ", strip=True)) == "textuales":
            head = h   # último gana (el bloque va al final)
    if head is None:
        return []
    out: list = []
    for sib in head.next_siblings:
        name = (getattr(sib, "name", "") or "").lower()
        if not name:
            continue   # NavigableString
        if name in HEADS:
            break
        if name == "blockquote":
            ps = sib.find_all("p")
            textos = [p.get_text(" ", strip=True) for p in ps] if ps else [sib.get_text(" ", strip=True)]
            for t in textos:
                t = _limpiar_cita(t)
                if t:
                    out.append(t)
    return out


class ManagerScraper:
    """
    Scraper simple del Manager por cookie de sesión.

    Config esperada en config.ini:
      [MANAGER]
      base_url = https://manager.diariohuarpe.com
      cookie   = <pegar Cookie entera copiada del request de la pestaña del Manager>
    """
    def __init__(self, base_url: str, cookie: Optional[str] = None,
                 timeout: int = 25, foto_pagina_service=None):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self._foto_pagina_service = foto_pagina_service  # FotoPaginaService | None
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "ArmadorHuarpe/1.0 (+scraper)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        })
        if cookie:
            # Cookie completa tal cual (copiada de DevTools → Network → Request Headers → Cookie)
            self.s.headers["Cookie"] = cookie

        self._driver = None


    # ---------- Utilidades internas ----------
    def _absolutize(self, url: str) -> str:
        """
        Convierte rutas relativas o nombres de archivo en URLs absolutas
        del Manager (por ejemplo: 'uploads/foto.jpg' -> 'https://manager.diariohuarpe.com/uploads/foto.jpg')
        """
        if not url:
            return ""
        u = url.strip()
        if not u.lower().startswith("http"):
            return urljoin(self.base_url + "/", u.lstrip("/"))
        return u


    def _decode_html_text(self, s: str) -> str:
        """
        Limpia texto eliminando entidades HTML (&aacute;, &quot;, etc.),
        non-breaking spaces y espacios redundantes.
        """
        if not s:
            return ""
        s = ihtml.unescape(s)
        s = s.replace("\xa0", " ")
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()



    def _leer_cuerpo_html(self, timeout: int = 15) -> str:
        """
        Lee el HTML del cuerpo desde CKEditor, sea modo iframe (CKE clásico)
        o modo inline (.ck-editor__editable). Devuelve HTML (no texto plano).
        """
        drv = getattr(self, "_driver", None)
        if not drv:
            return ""
        wait = WebDriverWait(drv, timeout)

        # 1) Intento: CKEditor clásico con iframe (nombres comunes)
        posibles_iframes = [
            (By.CSS_SELECTOR, "iframe.cke_wysiwyg_frame"),
            (By.CSS_SELECTOR, "iframe.cke_wysiwyg_frame.cke_reset"),
            (By.CSS_SELECTOR, "iframe[title='Editor de texto enriquecido']"),
            (By.CSS_SELECTOR, "iframe[title*='CKEditor']"),
        ]
        for by, sel in posibles_iframes:
            try:
                iframe = wait.until(EC.presence_of_element_located((by, sel)))
                drv.switch_to.frame(iframe)
                body = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
                html = body.get_attribute("innerHTML") or ""
                drv.switch_to.default_content()
                if html.strip():
                    return html
                drv.switch_to.default_content()
            except Exception:
                try:
                    drv.switch_to.default_content()
                except Exception:
                    pass

        # 2) Fallback: CKEditor 5/inline (div contenteditable)
        posibles_inline = [
            (By.CSS_SELECTOR, ".ck-editor__editable[role='textbox']"),
            (By.CSS_SELECTOR, ".ck-content[contenteditable='true']"),
            (By.CSS_SELECTOR, "div[contenteditable='true']"),
        ]
        for by, sel in posibles_inline:
            try:
                editable = wait.until(EC.presence_of_element_located((by, sel)))
                # CKEditor 5 suele renderizar HTML válido en innerHTML
                html = editable.get_attribute("innerHTML") or ""
                if html.strip():
                    return html
            except Exception:
                pass

        # 3) Último recurso: algunos managers guardan el HTML en un textarea oculto
        posibles_textareas = [
            (By.CSS_SELECTOR, "textarea[name='cuerpo']"),
            (By.CSS_SELECTOR, "textarea#cuerpo"),
            (By.CSS_SELECTOR, "textarea.cke_source"),
        ]
        for by, sel in posibles_textareas:
            try:
                ta = drv.find_element(by, sel)
                val = ta.get_attribute("value") or ""
                if val.strip():
                    return val
            except Exception:
                pass

        # Si no hay nada, devolvemos vacío (lo manejará el caller)
        return ""
    
    

    def attach_chrome_cookies(self, domains: Optional[Iterable[str]] = None, profile: Optional[str] = None) -> int:
        """
        Lee cookies del perfil de Chrome (Windows) y las inyecta al requests.Session.
        Sugeridos:
          - domains=[".diariohuarpe.com","manager.diariohuarpe.com"]
          - profile="Default" (o el perfil real si usan otro)
        Devuelve cuántas cookies cargó.
        """
        try:
            from services.chrome_cookies import load_cookies_into_session
        except Exception as e:
            _log.info(f"[SCRAPER] No puedo importar chrome_cookies: {e}")
            return 0

        doms = list(domains or [".diariohuarpe.com", "manager.diariohuarpe.com"])
        try:
            loaded = load_cookies_into_session(self.s, doms, profile=profile)
            if loaded == 0:
                _log.error("[SCRAPER] No pude cargar cookies de Chrome (0).")
            return loaded
        except Exception as e:
            _log.error(f"[SCRAPER] Error cargando cookies de Chrome: {e}")
            return 0
    
    # ---------- API de alto nivel ----------
    
    
    # ---------- HTTP ----------
    def attach_driver(self, driver):
        """Recibe el WebDriver ya creado en la app principal."""
        self._driver = driver

    
    def _get_html(self, url: str) -> str:
        """
        Obtiene el HTML real del Manager usando Selenium.
        Esta versión:
        - Carga siempre la página con driver.get()
        - Detecta inmediatamente el overlay de nota ocupada (userBlockUI)
        - Evita colgarse esperando el formulario si la nota está ocupada
        - Devuelve el page_source completo renderizado por JS
        """

        if not hasattr(self, "_driver") or self._driver is None:
            raise ScraperError("El scraper Selenium no tiene driver iniciado (self._driver es None).")

        try:
            self._driver.get(url)
        except Exception as e:
            raise ScraperError(f"No se pudo cargar la URL en Selenium: {url}", e)

        # Esperar que al menos exista <body>
        try:
            WebDriverWait(self._driver, 8).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception:
            pass  # si llega acá igual seguimos, devolvemos lo que haya

        # ==========================================================
        # DETECCIÓN TEMPRANA ROBUSTA DE NOTA OCUPADA
        # ==========================================================
        try:
            html = self._driver.page_source.lower()

            # Caso A: ID real del manager (dos variantes)
            # --- DETECCIÓN REAL DE NOTA OCUPADA (TODAS LAS VARIANTES) ---
            if (
                'id="userblockui"' in html
                or 'id="userblockui"' in html.lower()
                or "usuario editando" in html
                or 'class="blockui blockoverlay"' in html
                or 'blockui blockmsg blockelement' in html
            ):
                return "__OCUPADA__"


            # Caso B: Overlays blockUI (manager viejo)
            if 'class="blockui blockoverlay"' in html or 'class="blockui blockmsg blockpage"' in html:
                return self._driver.page_source

            # Caso C: texto explícito
            if "usuario editando" in html or "usuario está editando" in html:
                return self._driver.page_source

        except Exception:
            pass


        # ----------------------------------------------------------------------
        # 2) N O   E S T Á   O C U P A D A
        #    Esperamos los elementos del formulario de edición
        # ----------------------------------------------------------------------
        try:
            # tituloInput es el indicador más estable de carga correcta
            WebDriverWait(self._driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#tituloInput"))
            )
        except Exception:
            # Puede ser error de carga → devolvemos lo que haya,
            # dejando que _scrape_core() decida qué hacer
            return self._driver.page_source

        # ----------------------------------------------------------------------
        # 3) OK → Página cargada correctamente
        # ----------------------------------------------------------------------
        return self._driver.page_source


    # ---------- Detección de origen ----------
    def _is_manager_url(self, url: str) -> bool:
        try:
            from urllib.parse import urlparse
            h = (urlparse(url).netloc or "").lower()
            return "manager.diariohuarpe.com" in h or h.startswith("manager.")
        except Exception:
            return False

    def _render_body_and_qr_links(self, html_fragment: str, page_url: str) -> tuple[str, list[str], list[str], list[str]]:
        """
        Renderiza el cuerpo preservando subtítulos y recolectando links de embeds.
        Captura iframes/anchors aunque estén dentro de <p>, <div>, <li>, <blockquote>.
        NO agrega los "Link para el QR:" aquí; sólo devuelve (texto, links, blockquote_quotes).
        """
        if not html_fragment:
            return "", [], []

        if BeautifulSoup is None:
            txt = unescape(re.sub(r"<[^>]+>", "", html_fragment or "")).strip()
            return txt, [], []

        soup = BeautifulSoup(html_fragment, "html.parser")
        root = soup

        tokens: list[tuple[str, str]] = []  # ("p" | "h", texto)
        qr_links: list[str] = []
        blockquote_quotes: list[str] = []

        HEADER_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
        SOCIAL_RE = re.compile(r"(instagram\.com|youtu\.be|youtube\.com)", re.I)

        def clean_text(s: str) -> str:
            s = unescape(s or "")
            s = s.replace("\xa0", " ")
            s = re.sub(r"[ \t]+", " ", s)
            s = re.sub(r"\n{3,}", "\n\n", s)
            return s.strip()

        def normalize_http(u: str) -> str:
            u = (u or "").strip()
            if not u:
                return ""
            # Sólo absolutos. Nada de urljoin con el manager.
            if not u.startswith("http"):
                return ""
            # Limpia casos "https://manager.diariohuarpe.com/https://..."
            u = re.sub(r"^https?://manager\.diariohuarpe\.com/(https?://)", r"\1", u)
            return u

        def maybe_add_qr(url: str):
            u = normalize_http(url)
            if not u:
                return
            # Por pedido: sólo Instagram / YouTube
            if SOCIAL_RE.search(u):
                qr_links.append(u)

        def iframe_any_src(el) -> str:
            v = (el.get("src") or "").strip()
            if v and v.startswith("http"):
                return v
            for key in ("data-src", "data-original", "data-lazy-src", "data-url", "data-href"):
                v = (el.get(key) or "").strip()
                if v:
                    return v

            srcdoc = el.get("srcdoc")
            if srcdoc:
                try:
                    doc = BeautifulSoup(srcdoc, "html.parser")
                    ifr2 = doc.find("iframe")
                    if ifr2:
                        v2 = (ifr2.get("src") or "").strip()
                        if v2 and v2.startswith("http"):
                            return v2
                    a = doc.find("a", href=True)
                    if a and a["href"]:
                        href = a["href"].strip()
                        if href.startswith("http"):
                            return href
                except Exception:
                    pass
                m = re.search(r"https?://[^\s\"']+", srcdoc)
                if m:
                    return m.group(0)
            return ""

        def scan_nested_media(container):
            # iframes anidados
            for ifr in container.find_all("iframe"):
                src = (ifr.get("src") or "").strip() or iframe_any_src(ifr)
                if src:
                    maybe_add_qr(src)
            # anchors anidados (links a IG/YT)
            for a in container.find_all("a", href=True):
                maybe_add_qr((a.get("href") or "").strip())

        def walk(node):
            for el in getattr(node, "children", []):
                if not hasattr(el, "name"):  # NavigableString
                    continue
                name = (el.name or "").lower()

                # 1) Iframes sueltos
                if name == "iframe":
                    src = (el.get("src") or "").strip() or iframe_any_src(el)
                    if src:
                        maybe_add_qr(src)
                    continue

                # 2) Subtítulos H1..H6
                if name in HEADER_TAGS:
                    t = clean_text(el.get_text(" ", strip=True))
                    if t:
                        tokens.append(("h", t))
                    continue  # no seguir hijos

                # 3) Bloques de texto: <p>, <li>, <blockquote>, <div>
                if name in ("p", "li", "blockquote", "div"):
                    t = clean_text(el.get_text(" ", strip=True).strip())
                    if t:
                        tokens.append(("p", t))

                    # ESCANEO NUEVO: iframes y anchors anidados
                    scan_nested_media(el)

                    # Caso especial blockquote de Instagram, etc.
                    if name == "blockquote":
                        perma = (el.get("data-instgrm-permalink") or "").strip()
                        if perma:
                            maybe_add_qr(perma)
                        elif t:
                            blockquote_quotes.append(t)

                    continue

                # 4) Cualquier otro nodo: seguir bajando
                walk(el)

        walk(root)

        # De-duplicar links manteniendo orden
        seen = set()
        uniq_links: list[str] = []
        for u in qr_links:
            if u and u not in seen:
                seen.add(u)
                uniq_links.append(u)

        # Render de texto (subtítulos vs párrafos)
        # Los intertítulos se prefijan con "## " para que el JS pueda
        # aplicarles un estilo Quark diferente (el prefijo se elimina allí).
        # Todos los tokens se separan con \n\n para que el split del JS
        # genere un qx-p independiente por bloque.
        out: list[str] = []
        for i, (kind, txt) in enumerate(tokens):
            if i > 0:
                out.append("\n\n")
            if kind == "h":
                out.append(f"## {txt}")
            else:
                out.append(txt)

        body = "".join(out).strip()

        # Textuales ESPECIALES: los <p> de los <blockquote> que siguen al encabezado "Textuales"
        # (para secciones tipo Café; el llamador elige entre esta lista y blockquote_quotes).
        especiales = _textuales_bloque_textuales(root)

        # IMPORTANTE: no agregamos aquí los "Link para el QR:"
        return body, uniq_links, blockquote_quotes, especiales
        

    
    # ---------- Parsing ----------
    def _parse_note(self, html: str, page_url: str) -> NoteData:
        """
        Parser específico para el Manager.
        """

        
        if BeautifulSoup is None:
            return NoteData(cuerpo="(bs4 no disponible)", image_urls=[])

        soup = BeautifulSoup(html, "html.parser")
        note = NoteData()

        def get_val(idname: str) -> str:
            el = soup.select_one(f"#{idname}")
            if not el:
                return ""
            v = el.get("value") or el.text
            return (v or "").strip()

        # -------- TEXTOS --------
        titulo_imp = self._decode_html_text(get_val("tituloEdicionImpresa"))
        titulo_nota = self._decode_html_text(get_val("tituloNota"))
        note.titulo = titulo_imp or titulo_nota
        note.volanta = self._decode_html_text(get_val("volanta"))
        raw_bajada = get_val("introHTML") or ""
        raw_bajada = re.sub(r"<[^>]+>", "", raw_bajada)
        note.bajada  = self._decode_html_text(raw_bajada)

        # -------- AUTOR / FECHAS (del Manager) --------
        try:
            el_c = soup.select_one("#doc_user_c")
            note.autor_creacion = (el_c.get_text(" ", strip=True) if el_c else "").strip()

            el_m = soup.select_one("#doc_user_m")
            note.autor_modificacion = (el_m.get_text(" ", strip=True) if el_m else "").strip()

            fc = soup.select_one("#doc_fecha_c")
            note.fecha_creacion = (fc.get_text(" ", strip=True) if fc else "").strip()

            fm = soup.select_one("#doc_fecha_m")
            note.fecha_modificacion = (fm.get_text(" ", strip=True) if fm else "").strip()
        except Exception:
            _log.error("[SCRAPER] Aviso: no pude extraer autor/fechas del Manager.")

        
        # -------- CUERPO --------
        note.cuerpo = ""
        raw_html = ""
        # -------- QR LINKS (Multimedia + fallback body) --------
        mm_qr_links, mm_qr_norm = self._extract_multimedia_qr_links(soup)

        # 1) Intentar leer directamente el innerHTML del CKEditor (Selenium)
        try:
            if hasattr(self, "_driver") and self._driver:
                raw_html = self._leer_cuerpo_html()
                if raw_html:
                    _log.debug(f"[SCRAPER] Cuerpo desde iframe CKEditor (len={len(raw_html)})")
        except Exception as e:
            _log.debug(f"[SCRAPER] Error leyendo iframe CKEditor con Selenium: {e}")
            raw_html = ""

        # 2) Si no hay, tomar el contenido REAL del <textarea id="textoHTML">
        #    OJO: muchas veces queda escapado (&lt;p&gt; → <p>), hay que desescapar.
        if not raw_html:
            ta_cuerpo = soup.select_one("#textoHTML")
            if ta_cuerpo:
                raw_html = (ta_cuerpo.get("value") or ta_cuerpo.text or "").strip()
                if raw_html:
                    raw_html = ihtml.unescape(raw_html)

                if not raw_html:
                    # última chance: value/texto crudo sin desescape
                    raw_html = (ta_cuerpo.get("value") or ta_cuerpo.text or "").strip()

                if raw_html:
                    _log.debug(f"[SCRAPER] Cuerpo desde <textarea id='textoHTML'> (len={len(raw_html)})")


        if raw_html:
            body_txt, body_qr_links, bq_quotes, bq_especiales = \
                self._render_body_and_qr_links(raw_html, page_url)
            note.quotes = bq_quotes
            note.quotes_especiales = bq_especiales

            # --- Merge QR links: Multimedia (prioridad) + Body (fallback) ---
            final_qr_links = []
            seen_norm = set()

            # 1) Primero Multimedia (se conserva tal cual)
            if mm_qr_links:
                _log.debug(f"[SCRAPER][QR] Multimedia aporta {len(mm_qr_links)} link(s)")
                final_qr_links.extend(mm_qr_links)
                seen_norm |= set(mm_qr_norm)

            # 2) Luego Body, pero ignorando duplicados respecto a Multimedia
            if body_qr_links:
                _log.debug(f"[SCRAPER][QR] Body detectó {len(body_qr_links)} link(s)")

            for u in (body_qr_links or []):
                norm = u

                # Normalización equivalente para dedupe
                if "youtube.com/embed/" in norm:
                    norm = norm.replace("youtube.com/embed/", "youtube.com/watch?v=")

                if "youtu.be/" in norm.lower():
                    vid = norm.split("youtu.be/")[-1].split("?")[0].split("&")[0].strip("/")
                    norm = f"https://www.youtube.com/watch?v={vid}"

                norm = norm.split("?")[0].rstrip("/")

                if norm in seen_norm:
                    _log.debug(f"[SCRAPER][QR] Duplicado ignorado (body): {u}")
                    continue

                final_qr_links.append(u)
                seen_norm.add(norm)

            # 3) Asignar cuerpo + links finales
            note.cuerpo = body_txt

            if final_qr_links:
                note.cuerpo = (note.cuerpo + "\n\n" + "\n".join(f"Link para el QR: {u}" for u in final_qr_links)).strip()

            note.qr_links = final_qr_links
        else:
            # 3) Fallback: data-plain (sin subtítulos)
            plain = (soup.select_one("#textoHTML").get("data-plain") or "").strip() if soup.select_one("#textoHTML") else ""
            if plain:
                note.cuerpo = plain
                _log.debug(f"[SCRAPER] Cuerpo desde data-plain (len={len(plain)})")
            else:
                # 4) Último recurso: limpieza básica
                raw = ""
                el = soup.select_one("#textoHTML")
                if el:
                    raw = (el.get("value") or el.text or "")
                if raw:
                    raw = re.sub(r"</p>\s*<p>", "\n", raw, flags=re.I)
                    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
                    raw = re.sub(r"</?p[^>]*>", "", raw, flags=re.I)
                    raw = re.sub(r"<[^>]+>", "", raw)
                    note.cuerpo = self._decode_html_text(raw)
                    _log.debug(f"[SCRAPER] Cuerpo desde limpieza básica (len={len(note.cuerpo)})")

        if not note.cuerpo.strip():
            _log.warning("[SCRAPER] AVISO: No se pudo detectar cuerpo en esta nota → vacío.")
            note.cuerpo = "(CUERPO NO DETECTADO)"

        # -------- FIRMA --------
        note.firma = ""
        
        firmante = soup.select_one("#firmanteInput")
        if firmante:
            visibles = [el.get_text(strip=True).rstrip("×").strip() for el in firmante.select(".ms-sel-item")]
            visibles = [t for t in visibles if t]
            if visibles:
                note.firma = ", ".join(visibles)
            else:
                hiddens = [i.get("value") for i in firmante.select("input[name='firmante[]']")]
                hiddens = [(v or "").strip() for v in hiddens if (v or "").strip()]
                if hiddens:
                    note.firma = ", ".join(hiddens)
        note.firmado = bool(note.firma.strip())
        # -------- EPÍGRAFE --------
        note.epigrafe = ""
        ta_epi = soup.select_one("#imagenTapaDesc")
        if ta_epi:
            epi_plain = (ta_epi.get("data-plain") or "").strip()
            if epi_plain:
                note.epigrafe = self._decode_html_text(epi_plain)

        if not note.epigrafe:
            raw = get_val("imagenTapaDesc")
            if raw:
                raw = re.sub(r"</p>\s*<p>", " ", raw, flags=re.I)
                raw = re.sub(r"<br\s*/?>", " ", raw, flags=re.I)
                raw = re.sub(r"</?p[^>]*>", "", raw, flags=re.I)
                raw = re.sub(r"<[^>]+>", "", raw)
                note.epigrafe = self._decode_html_text(raw)

        if not note.epigrafe:
            note.epigrafe = "NO HAY EPIGRAFE"

        # -------- IMÁGENES (principal + galería con epígrafes) --------

        note.image_urls = []
        note.galeria = []

        def _pick_src(img):
            for key in ("data-src", "data-original", "data-lazy-src", "src"):
                v = (img.get(key) or "").strip()
                if v:
                    return v
            return ""

        imagenes: list[dict] = []
        galeria: list[dict] = []

        # 1️⃣ Tabla real del Manager (con epígrafes por imagen)
        for tr in soup.select("tbody.listado_container tr[data-path]"):
            # URL de la imagen
            label = tr.select_one("td label")
            url = (label.get_text(strip=True) if label else "").strip()

            if not url:
                img = tr.select_one("img[src]")
                if img:
                    url = _pick_src(img)

            if not url:
                continue

            abs_url = self._absolutize(url)

            # ¿Es principal?
            radio_interior = tr.select_one("input[name='imagen_interior'][checked]")
            is_principal = radio_interior is not None

            # Epígrafe específico de esta imagen
            epi_input = tr.select_one("input[name='epigrafe_galeria']")
            epi = (epi_input.get("value") or "").strip() if epi_input else ""

            img_record = {
                "url": abs_url,
                "principal": is_principal,
                "epigrafe": epi or ""
            }

            imagenes.append(img_record)

        # 2️⃣ Si ninguna tiene principal, marcar la primera
        if imagenes and not any(img["principal"] for img in imagenes):
            imagenes[0]["principal"] = True

        # 3️⃣ Asignar lista completa a note.image_urls
        note.image_urls = imagenes

        # 4️⃣ Lista de imágenes NO principales → galeria
        note.galeria = [img for img in imagenes if not img["principal"]]

        _log.debug(f"[SCRAPER] {len(imagenes)} imagen(es) detectada(s) con epígrafes.")

        if any(img["principal"] for img in imagenes):
            principal = next((img["url"] for img in imagenes if img["principal"]), None)
            _log.debug(f"[SCRAPER] Imagen principal detectada: {principal}")
        else:
            _log.debug("[SCRAPER] ⚠️ No se detectó imagen marcada como principal.")
        
        # -------- ESTADO PUBLICACIÓN (P o NP) --------
        try:
            label_el = soup.select_one("#notaLink")
            label_txt = (label_el.get_text(strip=True) if label_el else "").lower()

            if label_txt != "nota nueva":
                note.estado_pub = "P"
            else:
                note.estado_pub = "NP"
        except Exception:
            note.estado_pub = "NP"


        
        return note

    # ---------- Extracción de links de QR desde Multimedia (nueva implementación) ----------
    def _extract_multimedia_qr_links(self, soup):
        """
        Extrae links de video desde la pestaña Multimedia (#urlvideo).

        Retorna:
            raw_links (list[str]): links tal como vienen del Manager
            norm_links (set[str]): links normalizados solo para deduplicación
        """
        _log.debug("[SCRAPER][QR] Buscando link multimedia (#urlvideo)...")

        raw_links = []
        norm_links = set()

        input_video = soup.select_one("#urlvideo")

        if not input_video:
            _log.info("[SCRAPER][QR] Input #urlvideo no encontrado")
            return raw_links, norm_links

        value = (input_video.get("value") or "").strip()

        if not value:
            _log.info("[SCRAPER][QR] #urlvideo encontrado pero vacío")
            return raw_links, norm_links

        _log.info(f"[SCRAPER][QR] #urlvideo encontrado: {value}")

        url_lower = value.lower()

        # --- YouTube ---
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            raw_links.append(value)

            norm = value

            if "youtube.com/embed/" in norm:
                norm = norm.replace("youtube.com/embed/", "youtube.com/watch?v=")

            if "youtu.be/" in norm:
                vid = norm.split("youtu.be/")[-1].split("?")[0]
                norm = f"https://www.youtube.com/watch?v={vid}"

            norm_links.add(norm)

            _log.info(f"[SCRAPER][QR] Link YouTube normalizado: {norm}")
            return raw_links, norm_links

        # --- Instagram ---
        if "instagram.com" in url_lower:
            raw_links.append(value)

            # Normalización liviana (sin params)
            norm = value.split("?")[0].rstrip("/")

            norm_links.add(norm)

            _log.info(f"[SCRAPER][QR] Link Instagram normalizado: {norm}")
            return raw_links, norm_links

        _log.info("[SCRAPER][QR] #urlvideo no es YouTube ni Instagram")
        return raw_links, norm_links



    # ---------- Descarga de imágenes ----------
    def _download_images(self, urls: List[str], numero: int, fs: FileService, subfolder: Optional[Path] = None) -> List[Path]:
        """
        Descarga todas las imágenes de una nota (principal + adicionales).
        Espera 1s entre descargas para evitar bloqueos del servidor CDN.
        """
        saved: List[Path] = []
        if not urls:
            return saved

        folder = subfolder or fs.get_txt_path(numero).parent
        folder.mkdir(parents=True, exist_ok=True)

        _log.info("Intentando bajar %d imagen(es)...", len(urls))

        for idx, data in enumerate(urls, start=1):
            url: Optional[str] = None
            try:
                # Soporta lista de dicts {"url":..., "principal":...} o lista simple
                if isinstance(data, dict):
                    url = data.get("url")
                    is_principal = data.get("principal", False)
                else:
                    url = data
                    is_principal = False

                if not url:
                    continue

                clean_url = url.split("?")[0]
                fname = Path(urlparse(clean_url).path).name

                # Prefijo si es la imagen principal
                if is_principal:
                    fname = f"principal_{fname}"

                dest = folder / fname
                if dest.exists():
                    dest = fs._unique_dest(dest)

                # Descarga robusta con reintentos
                self._download_file(url, dest)

                # Convertir WebP a JPG si es necesario (sin pérdida de calidad adicional)
                dest = self._convertir_webp_a_jpg(dest)

                saved.append(dest)
                _log.info("Imagen guardada: %s", dest.name)

                # Registrar stats de descarga para detección de edición posterior
                if self._foto_pagina_service is not None and fs.material is not None:
                    try:
                        self._foto_pagina_service.registrar_foto_descargada(
                            numero, dest, fs.material
                        )
                    except Exception as stats_err:
                        _log.debug("No se pudieron registrar stats de %s: %s",
                                   dest.name, stats_err)

            except Exception as e:
                _log.warning("No se pudo bajar imagen %s: %s", url, e)
                continue

            # Espera antes de continuar con la próxima descarga
            if idx < len(urls):
                time.sleep(1.0)

        _log.info("%d/%d imágenes guardadas correctamente.", len(saved), len(urls))
        return saved







    def _download_file(self, url: str, dest: Path) -> None:
        """
        Descarga una imagen desde el Manager o CDN, con reintentos y headers tolerantes.
        Prefiere JPEG/PNG; evita solicitar WebP/AVIF para obtener mejor calidad sin conversión.
        """
        max_retries = 3
        backoff = 2.0  # segundos base

        for intento in range(1, max_retries + 1):
            try:
                headers = {
                    "Referer": self.base_url,
                    "User-Agent": random.choice([
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0 Safari/537.36",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
                    ]),
                    # Preferir JPEG/PNG; si el CDN igual devuelve WebP, _convertir_webp_a_jpg lo maneja.
                    "Accept": "image/jpeg,image/png,image/gif,image/*;q=0.8,*/*;q=0.5",
                    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
                }

                r = self.s.get(url, timeout=self.timeout, stream=True, headers=headers)
                r.raise_for_status()

                ctype = r.headers.get("Content-Type", "").lower()
                if "image" not in ctype:
                    preview = r.content[:512]
                    if b"<html" in preview.lower():
                        raise ScraperError("Respuesta HTML (sesión expirada o link inválido)")
                    raise ScraperError(f"No es una imagen ({ctype})")

                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                return  # éxito

            except Exception as e:
                _log.warning("Falló intento %d/%d para %s: %s", intento, max_retries, url, e)
                if intento < max_retries:
                    sleep_time = backoff * intento + random.uniform(0, 1)
                    _log.info("Reintentando en %.1fs...", sleep_time)
                    time.sleep(sleep_time)
                else:
                    raise ScraperError(f"Error al descargar imagen {url}: {e}")

    def _convertir_webp_a_jpg(self, path: Path) -> Path:
        """
        Si `path` es un WebP (detectado por magic bytes o sufijo), lo convierte
        a JPEG calidad 95 y elimina el original. Devuelve el path resultante.
        Si no es WebP, devuelve path sin modificar.
        """
        try:
            # Detectar WebP por magic bytes: RIFF????WEBP
            with open(path, "rb") as fh:
                header = fh.read(12)
            is_webp = (
                header[:4] == b"RIFF" and header[8:12] == b"WEBP"
            ) or path.suffix.lower() in (".webp", ".avif")

            if not is_webp:
                return path

            from PIL import Image
            jpg_path = path.with_suffix(".jpg")
            with Image.open(path) as img:
                # Manejar transparencia: pegar sobre fondo blanco
                if img.mode in ("RGBA", "LA") or (
                    img.mode == "P" and "transparency" in img.info
                ):
                    rgba = img.convert("RGBA")
                    bg   = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[3])
                    img_rgb = bg
                else:
                    img_rgb = img.convert("RGB")
                img_rgb.save(jpg_path, "JPEG", quality=100, subsampling=0)

            path.unlink()
            _log.info("WebP→JPG convertido: %s → %s", path.name, jpg_path.name)
            return jpg_path

        except ImportError:
            _log.warning("Pillow no instalado — no se pudo convertir WebP: %s", path.name)
            return path
        except Exception as e:
            _log.warning("No se pudo convertir WebP %s: %s", path.name, e)
            return path


    
    def _save_qr(self, url: str, folder: Path, idx: int = 1) -> Path:
        """
        Normaliza un link de QR y genera un PNG en escala de grises.
        Lo guarda en `folder` como QR_XX.png y devuelve la ruta.
        """
        # 1. Normalizar link YouTube
        if "youtube.com/embed/" in url:
            url = url.replace("youtube.com/embed/", "youtube.com/watch?v=")

        # 2. Crear QR
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img = img.convert("L")  # escala de grises

        # 3. Guardar en carpeta materiales/PXX
        fname = f"QR_{idx:02d}.png"
        out_path = folder / fname
        img.save(out_path, "PNG")

        return out_path
    

    # ================================================
    # SCRAPER 1 – LISTAR NOTAS DEL DÍA (REQUESTS)
    # ================================================
    def listar_noticias_del_dia(self):
        """
        Escanea la tabla del Manager y devuelve todas las notas creadas hoy
        o actualizadas hoy.
        """
        import datetime
        from bs4 import BeautifulSoup

        url = self.base_url.rstrip("/") + "/admin/noticias/index"
        r = self.session.get(url, timeout=30)
        if r.status_code != 200:
            raise ScraperError(f"No pude obtener el listado del Manager ({r.status_code})")

        soup = BeautifulSoup(r.text, "html.parser")

        hoy = datetime.date.today().strftime("%Y-%m-%d")
        rows = soup.select("table tbody tr")

        resultados = []

        for tr in rows:
            cols = [c.get_text(strip=True) for c in tr.select("td")]
            if len(cols) < 6:
                continue

            titulo = cols[1]
            seccion = cols[2]
            estado_pub = "P" if "Publicado" in cols[3] else "NP"

            created_str = cols[4][:10]   # formato YYYY-MM-DD...
            updated_str = cols[5][:10]

            if created_str == hoy or updated_str == hoy:

                link_tag = tr.select_one("a[href*='admin/noticias/']")
                if not link_tag:
                    continue

                href = link_tag.get("href")
                full_link = self.base_url.rstrip("/") + "/" + href.lstrip("/")

                resultados.append({
                    "titulo": titulo,
                    "seccion": seccion,
                    "estado_pub": estado_pub,
                    "link": full_link,
                    "created_at": datetime.datetime.fromisoformat(created_str),
                    "updated_at": datetime.datetime.fromisoformat(updated_str),
                })

        return resultados

        # ---------- API de alto nivel ----------

    def _scrape_core(
        self,
        link: str,
        dest_dir: Path,
        fs: FileService | None = None,
        numero: int | None = None,
        actualizar_ini: bool = False,
    ) -> Tuple[Path, List[Path]]:
        """
        Núcleo común de scraping:
        
        - Parsea volanta/título/bajada/firma/epígrafe/cuerpo.
        - Guarda TXT en dest_dir en formato ' /// ' (6 campos).
        - Descarga imágenes al mismo dest_dir.
        - Genera PNG de QR si hay qr_links.
        - Opcionalmente actualiza INI (cuando se usa materiales/Pnn).
        """
        if not link or not re.match(r"^https?://", link):
            raise ScraperError(f"Link inválido para scraping: {link!r}")
        
        


        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 1) Obtener HTML (si no está listo en 30s, _get_html lanza SCRAPE_RETRY)
        try:
            html = self._get_html(link)
        except ScraperError as e:
            msg = str(e).upper()
            if "SCRAPE_RETRY" in msg:
                raise   # que el controller la reencole
            raise      # otros errores siguen siendo fallas reales


        # === Validación mínima del HTML ===
        if not html or len(re.sub(r"\s+", "", html)) < 50:
            raise ScraperError("SCRAPE_RETRY")
   
        
        # 2) Parsear según origen
        if not self._is_manager_url(link):
            raise ScraperError("El scraper sólo admite URLs del Manager. Nunca del sitio público.")

        try:
            note = self._parse_note(html, link)
        except Exception as e:
            raise ScraperError(f"Error parseando nota desde Manager: {e}")


        # 3) Armar contenido TXT en formato unificado " /// "
        parts = [
            (note.volanta or "").strip(),
            (note.titulo or "").strip(),
            (note.bajada or "").strip(),
            (note.firma or "").strip(),
            (note.epigrafe or "").strip(),
            (note.cuerpo or "").strip(),
        ]
        contenido = " /// ".join(parts).strip()

        # Nombre base del TXT dentro de dest_dir
        txt_path = dest_dir / f"{dest_dir.name}.txt"
        _write_text(txt_path, contenido)

        # 4) Si corresponde, actualizar INI (sólo materiales/Pnn, no pool)
        if actualizar_ini and fs is not None and numero is not None:
            entry = fs.read_page_entry(numero)
            tiene_txt = bool(entry.get("txt_name", "").strip())

            if not tiene_txt:
                # Primera nota de la página
                fs.write_page_entry(
                    numero,
                    txt_name=txt_path.name,
                    link=link,
                )
                _log.info(f"[SCRAPER] INI creado para P{numero:02d}: {txt_path.name}")
            else:
                # Nota adicional
                fs.append_txt_entry(
                    numero,
                    txt_name=txt_path.name,
                    link=link,
                )
                _log.info(f"[SCRAPER] INI actualizado para P{numero:02d}: {txt_path.name} agregado")

        # 5) Descargar imágenes y construir lista para JSON (migración JSON 2026-05-06)
        saved_imgs: List[Path] = []
        imagenes_list: list[dict] = []

        if note.image_urls:
            try:
                # Normalizar SIEMPRE a dicts
                norm = []
                for item in (note.image_urls or []):
                    if isinstance(item, dict):
                        norm.append(item)
                    else:
                        norm.append({"url": item, "principal": False, "epigrafe": ""})
                note.image_urls = norm

                # Iterar sobre note.image_urls
                for idx, data in enumerate(note.image_urls, start=1):
                    url = data.get("url")
                    is_principal = data.get("principal", False)
                    img_epi = data.get("epigrafe", "").strip()

                    if not url:
                        continue

                    clean_url = url.split("?")[0]
                    fname = Path(urlparse(clean_url).path).name

                    if is_principal:
                        fname = f"principal_{fname}"

                    dest = dest_dir / fname
                    if dest.exists():
                        base = dest.stem
                        ext = dest.suffix
                        dest = dest_dir / f"{base}_{idx}{ext}"

                    self._download_file(url, dest)
                    dest = self._convertir_webp_a_jpg(dest)
                    saved_imgs.append(dest)
                    _log.info(f"[SCRAPER] ✅ Imagen guardada: {dest.name}")

                    # Epígrafe: por imagen → general de nota → "NO HAY EPÍGRAFE"
                    epi_final = img_epi or note.epigrafe or "NO HAY EPÍGRAFE"
                    imagenes_list.append({
                        "archivo": dest.name,
                        "url_origen": url,
                        "epigrafe": epi_final,
                        "orden": idx,
                        "es_principal": is_principal,
                    })
            except Exception as e:
                _log.warning(f"[WARN] No se pudieron descargar imágenes: {e}")

        # 6) Generar QR si hay links
        qr_paths: List[Path] = []
        if note.qr_links:
            try:
                for idx, qrlink in enumerate(note.qr_links, start=1):
                    if not qrlink:
                        continue
                    try:
                        qr_path = self._save_qr(qrlink, dest_dir, idx)
                        qr_paths.append(qr_path)
                        _log.info(f"[SCRAPER] QR generado en {qr_path}")
                    except Exception as e:
                        _log.warning(f"[SCRAPER] WARNING: no se pudo generar QR para {qrlink}: {e}")
            except Exception as e:
                _log.warning(f"[SCRAPER] WARNING: error general generando QRs: {e}")

        # 7) Escribir JSON junto al TXT (migración JSON 2026-05-06)
        seccion_nota = ""
        if fs is not None and numero is not None:
            try:
                seccion_nota = fs.read_page_entry(numero).get("seccion", "")
            except Exception:
                pass

        now_iso = datetime.now().isoformat()
        nota_json = {
            "version": 1,
            "tipo": "principal",
            "seccion": seccion_nota,
            "link": link,
            "estado_pub": note.estado_pub,
            "volanta": note.volanta,
            "titulo": note.titulo,
            "bajada": note.bajada,
            "firma": note.firma,
            "epigrafe": note.epigrafe,
            "cuerpo": note.cuerpo,
            "imagenes": imagenes_list,
            "autor_creacion": note.autor_creacion,
            "autor_modificacion": note.autor_modificacion,
            "fecha_creacion": note.fecha_creacion or now_iso,
            "fecha_modificacion": note.fecha_modificacion or now_iso,
            # Sección especial → textuales del bloque "Textuales"; si no, todos los blockquotes.
            "textuales_auto": (note.quotes_especiales
                               if _norm_txt(seccion_nota) in _secciones_textuales_norm()
                               else note.quotes),
        }
        try:
            json_path = txt_path.with_suffix(".json")
            json_path.write_text(json.dumps(nota_json, ensure_ascii=False, indent=2), encoding="utf-8")
            _log.info(f"[SCRAPER] JSON guardado: {json_path.name}")
        except Exception as e:
            _log.warning(f"[SCRAPER] WARNING: no se pudo escribir JSON: {e}")

        # 8) Actualizar meta.json del POOL
        try:
            meta_path = dest_dir / "_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            else:
                meta = {}

            meta["estado_pub"] = note.estado_pub or "NP"

            # ---- NUEVOS CAMPOS ----
            meta["firmado"] = bool(note.firma.strip())
            meta["autor_creacion"] = note.autor_creacion
            meta["autor_modificacion"] = note.autor_modificacion
            meta["fecha_creacion"] = note.fecha_creacion
            meta["fecha_modificacion"] = note.fecha_modificacion

            # Lista completa de imágenes (principal + no principales + epígrafe)
            meta["imagenes"] = note.image_urls or []

            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            _log.info(f"[SCRAPER] meta.json actualizado con autor/fechas/imagenes")
        except Exception as e:
            _log.warning(f"[SCRAPER] WARNING: no se pudo actualizar meta.json: {e}")

        return txt_path, saved_imgs + qr_paths


    def scrape_to_materiales(self, numero: int, link: str, fs: FileService) -> Tuple[Path, List[Path]]:
        """
        Descarga nota + imágenes desde `link` y guarda:
        - TXT en …/materiales/PXX/NN.txt
        - imágenes en …/materiales/PXX/NN_01.ext, NN_02.ext, ...
        """
        if fs is None:
            raise ScraperError("FileService no puede ser None en scrape_to_materiales.")

        # Elegir subcarpeta de noticia (multi-nota)
        sufijo = fs.next_noticia_suffix(numero)
        indice = ord(sufijo) - ord("a")
        noticia_dir = fs.get_or_create_noticia_dir(numero, indice)

        # Núcleo común con actualización de INI
        return self._scrape_core(
            link=link,
            dest_dir=noticia_dir,
            fs=fs,
            numero=numero,
            actualizar_ini=True,
        )

    def scrape_anywhere(self, link: str, folder: Path) -> tuple[Path, list[Path]]:
        """
        Igual a scrape_to_materiales pero guardando en `folder` (POOL).
        NO toca INI ni materiales/PXX, sólo:
        - nota.txt (usando el nombre de la carpeta)
        - imágenes descargadas al mismo folder.
        """
        folder = Path(folder)
        # Reutilizamos el núcleo pero SIN actualizar INI ni depender de FileService
        return self._scrape_core(
            link=link,
            dest_dir=folder,
            fs=None,
            numero=None,
            actualizar_ini=False,
        )
