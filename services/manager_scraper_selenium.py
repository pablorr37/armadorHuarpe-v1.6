# services/manager_scraper_selenium.py
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
import time
from datetime import datetime, date
from services.manager_scraper import ManagerScraper, ScraperError


class SeleniumManagerScraper(ManagerScraper):
    """
    Scraper que se conecta a un Chrome ya abierto mediante remote debugging.
    No hace login: usa la sesión viva de ese Chrome.
    Mejora clave: crea un WebDriver NUEVO por cada scrape, y lo cierra al final.
    """

    def __init__(self, base_url: str, debugger_addr: str, timeout: int = 60):
        super().__init__(base_url=base_url, timeout=timeout)
        if not debugger_addr or ":" not in debugger_addr:
            raise ScraperError(
                "Falta o es inválido [MANAGER].debugger_address (ej: 127.0.0.1:9222)."
            )
        self.debugger_addr = debugger_addr.strip()
        self._driver = None  # siempre efímero por scrape

    # ---------------------- Infra del driver (efímero) ----------------------

    def _fresh_driver(self):
        """Crea un WebDriver conectado al Chrome en modo debug."""
        opts = Options()
        # Conecta al Chrome ya abierto con --remote-debugging-port=XXXX
        opts.add_experimental_option("debuggerAddress", self.debugger_addr)
        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as e:
            raise ScraperError(
                "No pude conectar con Chrome (remote debugging). "
                "Verificá que el Chrome de depuración esté abierto en ese puerto.",
                e,
            )
        try:
            driver.set_page_load_timeout(self.timeout)
        except Exception:
            pass
        return driver

    def _quit_driver_safely(self, driver):
        try:
            driver.quit()
        except Exception:
            pass

    def _sync_cookies_to_requests(self, driver):
        """
        Toma las cookies del Chrome y las vuelca a self.s (requests),
        para que las descargas de imágenes usen la sesión autenticada.
        """
        try:
            cookies = driver.get_cookies() or []
        except Exception:
            cookies = []
        pairs = []
        for c in cookies:
            try:
                name = c.get("name")
                value = c.get("value")
                if name and value:
                    pairs.append(f"{name}={value}")
            except Exception:
                continue
        if pairs:
            self.s.headers["Cookie"] = "; ".join(pairs)

    # ---------------------- Obtención de HTML con Selenium ------------------

    def _get_html(self, url: str) -> str:
        """
        Crea un driver nuevo, navega a la URL y espera a que la página del Manager
        esté lista. Inyecta una pequeña rutina para que el cuerpo de CKEditor
        esté disponible como valor de #textoHTML (fallback robusto). Luego
        sincroniza cookies → requests y devuelve el HTML.
        Siempre cierra el driver al terminar.
        """
        driver = self._fresh_driver()
        self._driver = driver
        try:
            driver.get(url)

            # 1) Documento listo
            try:
                WebDriverWait(driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                raise ScraperError("SCRAPE_RETRY")

            # 2) Esperar que aparezca al menos uno de los campos clave del Manager.
            #    (título/volanta/intro/iframe de CKEditor de texto)
            try:
                WebDriverWait(driver, 30).until(
                    lambda d: len(
                        d.find_elements(
                            By.CSS_SELECTOR,
                            "#tituloNota, #tituloEdicionImpresa, #volanta, #introHTML, "
                            "iframe.cke_wysiwyg_frame, #cke_textoHTML iframe"
                        )
                    ) > 0
                )
            except Exception:
                raise ScraperError("SCRAPE_RETRY")


            # 3) Intentar hidratar el valor de #textoHTML con el innerHTML del iframe (cuerpo)
            #    y, si existe, de #imagenTapaDesc (epígrafe) desde su iframe.
            hydrate_js = r"""
            (function(){
            try {
                // Cuerpo (CKEditor)
                var ta = document.querySelector('#textoHTML');
                var ifr = document.querySelector('#cke_textoHTML iframe, iframe.cke_wysiwyg_frame');
                if (ta && ifr && ifr.contentWindow && ifr.contentWindow.document && ifr.contentWindow.document.body) {
                var html = ifr.contentWindow.document.body.innerHTML || '';
                if (html && (!ta.value || ta.value.trim().length < 10)) {
                    // setear tanto value como textContent para que aparezca en page_source
                    ta.value = html;
                    ta.textContent = html;
                }
                }
            } catch(e) {}

            try {
                // Epígrafe (si también es CKEditor)
                var epi = document.querySelector('#imagenTapaDesc');
                var ifre = document.querySelector('#cke_imagenTapaDesc iframe');
                if (epi && ifre && ifre.contentWindow && ifre.contentWindow.document && ifre.contentWindow.document.body) {
                var eh = ifre.contentWindow.document.body.innerHTML || '';
                if (eh && (!epi.value || epi.value.trim().length < 3)) {
                    epi.value = eh;
                    epi.textContent = eh;
                }
                if (eh && !epi.getAttribute('data-plain')) {
                    var txt = eh.replace(/<\/p>\s*<p>/ig,' ')
                                .replace(/<br\s*\/?>/ig,' ')
                                .replace(/<\/?p[^>]*>/ig,' ')
                                .replace(/<[^>]+>/g,' ')
                                .replace(/\s+/g,' ').trim();
                    epi.setAttribute('data-plain', txt);
                }
                }
            } catch(e) {}
            })();
            """

            try:
                driver.execute_script(hydrate_js)
            except Exception:
                pass

            # 4) Sincronizar cookies al cliente requests para descargas
            self._sync_cookies_to_requests(driver)

            html = driver.page_source or ""
            if not html.strip():
                raise ScraperError("No pude obtener HTML (vacío).")

            # Navegar al home antes de cerrar el driver.
            # Esto libera la noticia que estaba abierta para otros usuarios.
            try:
                driver.get(self.base_url.rstrip("/"))
            except Exception:
                pass  # no crítico; el finally cierra el driver de todas formas

            return html

        except TimeoutException as e:
            raise ScraperError("Timeout esperando la carga del Manager (Selenium).", e)
        except ScraperError:
            raise
        except Exception as e:
            # Mensaje claro cuando el Chrome de depuración no está disponible o la sesión no sirve.
            raise ScraperError("No pude obtener la página con Selenium. ¿Sesión autenticada?", e)
        finally:
            self._quit_driver_safely(driver)
            self._driver = None

    # ---------- Descarga de archivos ----------
    # Heredamos _download_file de ManagerScraper que usa self.s (ya con cookies).
    # El resto del flujo (parseo, guardado de TXT/IMG) también se hereda.

    def listar_noticias_del_dia(self):
        import datetime
        from bs4 import BeautifulSoup

        hoy = datetime.date.today().strftime("%Y-%m-%d")

        self.driver.get(self.base_url.rstrip("/") + "/admin/noticias/index")

        # Espera tabla
        import time
        time.sleep(1)

        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        rows = soup.select("table tbody tr")

        resultados = []

        for tr in rows:
            cols = [c.get_text(strip=True) for c in tr.select("td")]
            if len(cols) < 6:
                continue

            titulo = cols[1]
            seccion = cols[2]
            estado_pub = "P" if "Publicado" in cols[3] else "NP"

            created_str = cols[4][:10]
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

    





from datetime import date, datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import logging
_log = logging.getLogger(__name__)



class ScraperLinksNP:
    """
    Scraper que recorre múltiples secciones del Manager y devuelve
    todas las notas del día (solamente lista, NO determina P/NP).
    """

    SECCIONES_URLS = [
        "https://manager.diariohuarpe.com/list/notas/1/comunidad",
        "https://manager.diariohuarpe.com/list/notas/1/cultura-y-espectaculos",
        "https://manager.diariohuarpe.com/list/notas/1/departamentales",
        "https://manager.diariohuarpe.com/list/notas/1/eco-huarpe",
        "https://manager.diariohuarpe.com/list/notas/1/economia",
        "https://manager.diariohuarpe.com/list/notas/1/deportes",
        "https://manager.diariohuarpe.com/list/notas/1/negocios",
        "https://manager.diariohuarpe.com/list/notas/1/huarpe-tv",
        "https://manager.diariohuarpe.com/list/notas/1/judiciales",
        "https://manager.diariohuarpe.com/list/notas/1/mundo",
        "https://manager.diariohuarpe.com/list/notas/1/opinion",
        "https://manager.diariohuarpe.com/list/notas/1/pais",
        "https://manager.diariohuarpe.com/list/notas/1/policiales",
        "https://manager.diariohuarpe.com/list/notas/1/politica",
        "https://manager.diariohuarpe.com/list/notas/1/provinciales",
        "https://manager.diariohuarpe.com/list/notas/1/reddes",
        "https://manager.diariohuarpe.com/list/notas/1/salud-y-bienestar",
        "https://manager.diariohuarpe.com/list/notas/1/sociedad",
        "https://manager.diariohuarpe.com/list/notas/1/telam",
        "https://manager.diariohuarpe.com/list/notas/1/virales",
        "https://manager.diariohuarpe.com/list/notas/1/yo-cocino",
        "https://manager.diariohuarpe.com/list/notas/1/yo-construyo",
        "https://manager.diariohuarpe.com/list/notas/1/yo-te-invito",
    ]

    def __init__(self, debugger_address: str, chrome_profile_dir: str):
        self.debugger_address = debugger_address
        self.chrome_profile_dir = chrome_profile_dir
        self.driver = None

    def _connect_driver(self):
        """Conecta Selenium al Chrome YA ABIERTO y logueado."""
        options = Options()
        options.add_argument(f"--user-data-dir={self.chrome_profile_dir}")
        options.add_experimental_option("debuggerAddress", self.debugger_address)
        self.driver = webdriver.Chrome(options=options)

    def listar_links(self):
        """
        Lista TODAS las notas del día en TODAS las secciones.
        Solo lista títulos/links/fechas. No determina P o NP.
        """
        if not self.driver:
            self._connect_driver()

        hoy = date.today()
        resultados = []

        for url in self.SECCIONES_URLS:
            try:
                self.driver.get(url)
                _log.debug(f"[SCRAPER LINKS] Escaneando sección: {url}")

                tbody = self.driver.find_element(By.CSS_SELECTOR, "#tabla_list tbody")
                rows = tbody.find_elements(By.CSS_SELECTOR, "tr.tabla_nota")

            except Exception as e:
                _log.warning(f"[SCRAPER LINKS] No se encontró la tabla en {url}: {e}")
                continue

            for row in rows:
                try:
                    nota_id = row.get_attribute("data-id")
                    if not nota_id:
                        continue

                    # Fecha
                    fecha_txt = row.find_element(By.CSS_SELECTOR, "td[data-key='fecha_c']").text.strip()
                    try:
                        fecha_obj = datetime.strptime(fecha_txt, "%d/%m/%Y %H:%M")
                    except:
                        continue

                    if fecha_obj.date() != hoy:
                        continue

                    # Título
                    titulo = row.find_element(By.CSS_SELECTOR, "td[data-key='tituloNota']").text.strip()

                    # Secciones
                    secciones_txt = row.find_element(By.CSS_SELECTOR, "td[data-key='secciones']").text.strip()
                    secciones = [s.strip() for s in secciones_txt.split(",") if s.strip()]
                    seccion = secciones[0] if secciones else "General"

                    # Link real
                    link = f"https://manager.diariohuarpe.com/edit/notas/{nota_id}"

                    resultados.append({
                        "titulo": titulo,
                        "seccion": seccion,
                        "link": link,
                        "created_at": fecha_obj,
                        "updated_at": fecha_obj,
                    })

                except Exception as e:
                    _log.info("Error analizando fila:", e)
                    continue

        # Volver al home del Manager y cerrar el WebDriver.
        # Esto libera la nota/sección que quedó abierta, permitiendo
        # que otros usuarios accedan sin ver "Editada por otro usuario".
        try:
            home_url = "https://manager.diariohuarpe.com"
            self.driver.get(home_url)
            _log.info(f"[SCRAPER LINKS] Navegador restaurado a home: {home_url}")
        except Exception as e:
            _log.warning(f"[SCRAPER LINKS] No se pudo navegar al home: {e}")
        finally:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            _log.info("[SCRAPER LINKS] WebDriver cerrado.")

        return resultados


