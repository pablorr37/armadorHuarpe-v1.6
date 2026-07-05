# controller/controller.py
import json
import sys
import re
import unicodedata
import configparser
import subprocess
import getpass
from dataclasses import dataclass
import shutil

import datetime
import os
from services.manager_scraper_selenium import ScraperLinksNP

from pathlib import Path
from model.gestor_paginas import GestorPaginas
from model.rutas import RutasEstado
from config.config import Config
from typing import Optional, List
from PyQt5.QtCore import QThread
from services.manager_scraper import ManagerScraper, ScraperError
from services.file_service import FileService, FileServiceError
from services.foto_pagina_service import FotoPaginaService
from config.config import config_global
from utils.app_logger import get_logger

_log = get_logger(__name__)





@dataclass
class PoolNota:
    """
    Representa una nota descargada en el pool de 'Armar mono – notas del día'.
    """
    dir_path: Path
    txt_path: Path
    seccion: str
    titulo: str
    estado_pub: str  # "P" o "NP"
    chars: int
    created: datetime.datetime
    modified: datetime.datetime



class ArmadorController:
    def __init__(self):
        self.usuario = ""   # se setea al crear/actualizar base o al configurar usuario
        self.gestor_paginas = GestorPaginas()
        self.rutas = RutasEstado()
        self.file_service = FileService({})
        self._threads = {}  # {numero: (thread, worker)}
        self._queue_thread = None
        self._queue_worker = None
        self.foto_pagina_service = FotoPaginaService()
        self.on_scrape_error = None  # callable(numero, msg) set by UI
        
        ### PARA ARMAR MONO ###
        self.pool_notas: List[PoolNota] = []
        self.pool_root = None
        # Cargar rutas desde config.ini
        self.rutas.try_load()

        # ------------------------------
        # sincronizar pool_root
        # ------------------------------
        if self.rutas.pool_root:
            self.pool_root = self.rutas.pool_root


    # =========================
    # Pool "Armar mono – notas del día"
    # =========================

    def get_pool_day(self) -> Path | None:
        return self.rutas.pool_day_folder()


    def _get_pool_base(self) -> Optional[Path]:
        """
        Devuelve la carpeta base del pool, si está configurada en file_service.rutas["pool"].
        """
        try:
            raw = self.file_service.rutas.get("pool")  # usa el mismo dict de rutas
        except Exception:
            raw = None
        if not raw:
            return None
        base = Path(raw)
        return base if base.exists() else None

    def refresh_pool_notas_hoy(self) -> None:
        """
        Escanea la carpeta de pool del día actual y rellena self.pool_notas.
        Espera estructura:
            BASE/YYYY-MM-DD/(SECCION - TITULO/
        con al menos un .txt dentro.
        """
        base = self._get_pool_base()
        self.pool_notas = []
        if not base:
            _log.info("Sin ruta de pool configurada.")
            return

        hoy = datetime.date.today().strftime("%d-%m-%Y")  # "DD-MM-YYYY"
        day_dir = base / hoy

        if not day_dir.exists():
            _log.info("Carpeta del día no encontrada: %s", day_dir)
            return


        # =============================================================
        # SANITIZAR SUBCARPETAS EXISTENTES ANTES DE PROCESARLAS
        # =============================================================
        for child in list(day_dir.iterdir()):
            if not child.is_dir():
                continue

            safe_name = self.sanitize_folder_name(child.name)
            if safe_name != child.name:
                safe_dir = child.parent / safe_name
                try:
                    child.rename(safe_dir)
                    child = safe_dir
                    _log.info("Renombrada carpeta inválida: %s", child)
                except Exception as e:
                    _log.warning("No se pudo renombrar %s → %s: %s", child, safe_name, e)
                    continue   

        for child in sorted(day_dir.iterdir()):
            meta_path = child / "_meta.json"
            if not meta_path.exists():
                continue

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            estado_pub = meta.get("estado_pub", "NP")
            seccion = meta.get("seccion", "")
            titulo = meta.get("titulo", "")


            # Buscar el TXT principal (primer .txt)
            txt_files = [p for p in child.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
            if not txt_files:
                _log.debug("Carpeta sin TXT: %s", child)
                continue

            txt_path = sorted(txt_files)[0]

            try:
                contenido = txt_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                contenido = txt_path.read_text(encoding="latin-1", errors="ignore")

            chars = len(contenido)

            st = txt_path.stat()
            created = datetime.datetime.fromtimestamp(st.st_ctime)
            modified = datetime.datetime.fromtimestamp(st.st_mtime)

            nota = PoolNota(
                dir_path=child,
                txt_path=txt_path,
                seccion=seccion,
                titulo=titulo,
                estado_pub=estado_pub,
                chars=chars,
                created=created,
                modified=modified,
            )
            self.pool_notas.append(nota)

        _log.info("Notas detectadas hoy: %d", len(self.pool_notas))

    
    def copiar_pool_a_pagina(self, numero: int, dir_pool: Path) -> None:
        """
        Copia el TXT principal e imágenes desde una carpeta de pool a materiales/Pnn,
        crea (o agrega) la noticia en esa página y actualiza el INI con seccion y txt_len.
        No toca gestor_paginas.asignar ni mostrar_fragmentos.
        """
        dir_pool = Path(dir_pool)

        # TXT principal
        txt_files = [p for p in dir_pool.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
        if not txt_files:
            raise FileServiceError(f"La carpeta del pool no contiene TXT:\n{dir_pool}")
        txt_origen = sorted(txt_files)[0]

        # Determinar índice de noticia (a,b,c,...) usando lógica existente
        entry = self.file_service.read_page_entry(numero)
        existing_raw = (entry.get("txt_name") or "").strip()
        if existing_raw:
            parts = [p.strip() for p in existing_raw.split(";") if p.strip()]
            indice = len(parts)  # 0→a,1→b, etc.
        else:
            indice = 0

        # Destino TXT
        destino_txt = self.file_service.get_txt_path(numero, indice)
        contenido = txt_origen.read_text(encoding="utf-8", errors="ignore")
        destino_txt.parent.mkdir(parents=True, exist_ok=True)
        destino_txt.write_text(contenido, encoding="utf-8", newline="\n")

        txt_name = destino_txt.name

        # Actualizar INI: txt_name y estado 'proceso' pero sin tocar 'assigned' si ya había cosas
        if existing_raw:
            nuevos = existing_raw.split(";")
            nuevos = [p.strip() for p in nuevos if p.strip()]
            nuevos.append(txt_name)
            self.file_service.write_page_entry(
                numero,
                txt_name=";".join(nuevos),
                estado="asignado"
            )
        else:
            self.file_service.write_page_entry(
                numero,
                txt_name=txt_name,
                estado="asignado"
            )
        # Actualizar en memoria
        pag = self.gestor_paginas.obtener_pagina(numero)
        if pag:
            pag.estado = "asignado"



        # setear len de caracteres
        self.file_service.set_txt_len(numero, txt_name, len(contenido))

        # ==========================================================
        # NUEVO: Leer sección y título desde _meta.json del POOL
        # ==========================================================
        meta_path = dir_pool / "_meta.json"
        seccion = ""
        titulo = ""

        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                seccion = meta.get("seccion", "").strip()
                titulo = meta.get("titulo", "").strip()
            except Exception as e:
                _log.warning("No pude leer meta.json en %s: %s", dir_pool, e)

        # Guardar sección en INI (si existe)
        if seccion:
            self.file_service.set_seccion(
                numero,
                seccion,
                by=self.usuario if hasattr(self, "usuario") else None
            )
            pag = self.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.seccion = seccion

        # Guardar título principal en INI como mono_extra SOLO si el txt aún no existe
        # (respeta tu lógica general de que el TXT real tiene prioridad)
        if titulo:
            try:
                entry = self.file_service.read_page_entry(numero)
                # Si no hay txt_name todavía, mono_extra se usa como título
                if not entry.get("txt_name"):
                    self.file_service.write_page_entry(
                        numero,
                        mono_extra=titulo,
                        by=self.usuario
                    )
                    pag = self.gestor_paginas.obtener_pagina(numero)
                    if pag:
                        pag.mono_extra = titulo
            except Exception as e:
                _log.warning("No pude guardar título desde meta.json para P%02d: %s", numero, e)


        # Copiar imágenes del pool al directorio de la noticia
        dir_noticia = destino_txt.parent
        for f in dir_pool.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"):
                dst = dir_noticia / f.name
                if not dst.exists():
                    shutil.copy2(f, dst)

        _log.info("Nota copiada desde %s a P%02d (%s)", dir_pool, numero, destino_txt)

    def obtener_links_np(self):
        # Config global accesible sin depender de MainWindow
        cfg = config_global

        dbg = cfg.manager_debugger_address
        prof = cfg.chrome_profile_dir

        scraper = ScraperLinksNP(dbg, prof)
        return scraper.listar_links()

    

    
    @staticmethod
    def sanitize_folder_name(name: str) -> str:
        """
        Normaliza un nombre de carpeta para Windows:
        - Convierte guiones Unicode a ASCII
        - Elimina caracteres invisibles (nbsp, soft hyphen)
        - Elimina separadores de ruta
        - Quita caracteres ilegales
        - Colapsa espacios
        - Evita terminar en punto, espacio o guión
        - Limita longitud a ~120 chars
        """
    
        if not name:
            return "sin_titulo"

        # Convertir a str seguro
        name = str(name)

        # Normalizar unicode (separa tildes, etc.)
        name = unicodedata.normalize("NFKD", name)

        # Reemplazar guiones Unicode por "-"
        name = name.replace("–", "-").replace("—", "-").replace("−", "-")

        # Soft hyphen invisibles → remover
        name = name.replace("\u00ad", "")

        # Espacios no separables → reemplazar por espacio normal
        name = name.replace("\xa0", " ")

        # Eliminar caracteres de control
        name = re.sub(r"[\x00-\x1f\x7f]", " ", name)

        # Reemplazar separadores de ruta por espacio
        name = name.replace("\\", " ").replace("/", " ")

        # Reemplazar caracteres ilegales de Windows
        name = re.sub(r'[<>:"/\\|?*]', " ", name)

        # Colapsar espacios múltiples
        name = re.sub(r"\s+", " ", name).strip()

        # Evitar guiones finales (ASCII)
        name = re.sub(r"-+$", "", name).rstrip()

        # Evitar terminar en punto o espacio
        name = name.rstrip(". ")

        # Si quedó vacío, usar nombre seguro
        if not name:
            name = "sin_titulo"

        # Longitud segura
        if len(name) > 120:
            name = name[:120].rstrip(". -")  # evitar terminar mal tras recorte
            if not name:
                name = "sin_titulo"

        return name



    def scan_manager_iter(self):
        """
        Escanea Manager y va devolviendo notas una a una
        (modo incremental, estilo Cargador Huarpe).
        """
        from services.scraperLinks import ManagerScraper1

        queue = self.scrape_queue  # la cola que ya usás
        scraper = ManagerScraper1(self.driver, queue)

        # Cargar links en la cola
        scraper.run()

        # Consumir la cola UNA NOTA A LA VEZ
        while not queue.empty():
            nota = queue.dequeue()

            # Guardar en pool (usa tu lógica existente)
            try:
                saved = self._guardar_nota_en_pool(nota)
            except Exception as e:
                _log.error("Error guardando nota %s: %s", nota, e)
                continue

            # Actualizar estructura interna
            self.pool_notas.append(saved)

            # DEVOLVER UNA NOTA
            yield saved
    
    def scan_manager_and_update_pool(self, incremental=False):
        """
        1. Obtiene listado de notas del día desde el Manager (Scraper 1)
        2. Crea/actualiza carpetas en POOL/DD-MM-YYYY
        3. Si una nota es nueva o modificada → marca para descarga por scraper 2
        """

        base = self._get_pool_base()
        if not base:
            _log.info("No hay ruta configurada para pool.")
            return

        import datetime, json
        hoy = datetime.date.today().strftime("%d-%m-%Y")
        day_dir = base / hoy
        day_dir.mkdir(parents=True, exist_ok=True)

        # === SCRAPER-1: obtener metadata NP ===
        notas = self.obtener_links_np()

        encolar = []

        for n in notas:
            from html import unescape

            titulo = unescape(n["titulo"] or "").replace("\xa0", " ").strip()
            seccion = unescape(n["seccion"] or "").replace("\xa0", " ").strip()

            raw_name = f"{seccion} - {titulo}"

            folder_name = self.sanitize_folder_name(raw_name)

            # Evitar guiones finales
            folder_name = re.sub(r"-+$", "", folder_name).rstrip()
            if not folder_name:
                folder_name = "sin_titulo"

            target_dir = day_dir / folder_name
            target_dir.mkdir(parents=True, exist_ok=True)

            meta_file = target_dir / "_meta.json"

            # Detectar si hay que descargar (nota nueva o modificada)
            needs_download = False

            if meta_file.exists():
                old = json.loads(meta_file.read_text(encoding="utf-8"))
                if n["updated_at"].isoformat() != old.get("updated_at"):
                    needs_download = True
            else:
                needs_download = True

            # Mantener estado previo si existe y es válido
            old_estado = None
            if meta_file.exists():
                try:
                    old_meta = json.loads(meta_file.read_text())
                    est = old_meta.get("estado_pub", None)
                    if est in ("P", "NP"):
                        old_estado = est
                except:
                    pass

            # Si no hay estado previo válido → default NP hasta que el scraper actualice
            if old_estado is None:
                old_estado = "NP"


            meta = {
                "titulo": n["titulo"],
                "seccion": n["seccion"],
                "estado_pub": old_estado,
                "link": n["link"],
                "created_at": n["created_at"].isoformat(),
                "updated_at": n["updated_at"].isoformat(),
                "imagenes": n.get("imagenes", []),
                "galeria": n.get("galeria", []),
                "epigrafe": n.get("epigrafe", "")

            }

            meta_file.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            if needs_download:
                encolar.append((target_dir, n["link"]))

        # === SCRAPER-2: bajar contenido en cola ===

        pendientes = encolar[:]
        max_vueltas = len(pendientes) * 3 if pendientes else 0
        vueltas = 0

        while pendientes and vueltas < max_vueltas:
            vueltas += 1
            target_dir, link = pendientes.pop(0)

            try:
                saved = self._procesar_nota_pool(target_dir, link)
                _log.info("Pool scraper OK: %s", link)

                # 🔹 NUEVO: si alguien está escuchando, avisar
                yield saved

            except ScraperError as e:
                msg = str(e).upper()

                # === NUEVO FLUJO ===
                # Si no llegó el HTML esperado dentro de 30 segundos → reencolar
                if "SCRAPE_RETRY" in msg:
                    _log.warning("HTML incompleto/Manager no respondió, retry: %s", link)
                    pendientes.append((target_dir, link))
                    continue

                # Mantener compatibilidad con mensajes viejos (por si algo rebota)
                if "OCUPADA" in msg or "EDITADA POR OTRO USUARIO" in msg:
                    _log.warning("Nota ocupada (legacy), retry: %s", link)
                    pendientes.append((target_dir, link))
                    continue

                # Cualquier otro error es definitivo
                _log.error("Error scraper %s: %s", link, e)

            except Exception as e:
                _log.error("Error inesperado scrapeando %s: %s", link, e)

        
        # === Al finalizar TODA la cola, volver al HOME del Manager ===
        try:
            scraper = self._get_scraper()
            drv = getattr(scraper, "_driver", None)
            if drv:
                drv.get(scraper.base_url.rstrip("/"))
                _log.info("Navegador restaurado a HOME del Manager.")

        except Exception as e:
            _log.warning("No se pudo volver al HOME del Manager: %s", e)

        if not incremental:
            for _ in self.scan_manager_and_update_pool(incremental=True):
                pass
            return
        _log.info("Scan pool terminado. Nuevas/actualizadas: %d", len(encolar))


    def _procesar_nota_pool(self, target_dir: Path, link: str) -> PoolNota:
        """
        Procesa UNA nota del pool.
        Devuelve un PoolNota (MISMO tipo que refresh_pool_notas_hoy).
        """ 

        # 1) Scrape real (TXT + imágenes)
        self.scrape_to_pool(target_dir, link)

        # 2) Leer metadata
        meta_file = target_dir / "_meta.json"
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

        seccion = (meta.get("seccion") or "").strip()
        titulo  = (meta.get("titulo") or "").strip()
        estado_pub = meta.get("estado_pub", "NP")

        # 3) Detectar TXT principal
        txt_files = [
            p for p in target_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".txt"
        ]
        if not txt_files:
            raise RuntimeError(f"[POOL] Nota sin TXT tras scrape: {target_dir}")

        txt_path = sorted(txt_files)[0]

        # 4) Métricas de archivo
        try:
            contenido = txt_path.read_text(encoding="utf-8", errors="ignore")
            chars = len(contenido)
        except Exception:
            chars = 0

        st = txt_path.stat()
        created  = datetime.datetime.fromtimestamp(st.st_ctime)
        modified = datetime.datetime.fromtimestamp(st.st_mtime)

        # 5) CONSTRUIR PoolNota (clave)
        nota = PoolNota(
            dir_path=target_dir,
            txt_path=txt_path,
            seccion=seccion,
            titulo=titulo,
            estado_pub=estado_pub,
            chars=chars,
            created=created,
            modified=modified,
        )

        return nota
    
    
    # ---------- Scraper ----------
    
    def scrape_to_pool(self, target_dir: Path, link: str):
        """
        Ejecuta scrape_to_folder(link, target_dir) usando el scraper real.
        """
        scraper = self._get_scraper()
        target_dir.mkdir(parents=True, exist_ok=True)

        txt, imgs = scraper.scrape_anywhere(link, target_dir)
        return txt, imgs

    
    
    def launch_chrome_debug(self) -> tuple[bool, str]:
        """
        Lanza Chrome con --remote-debugging-port y --user-data-dir.
        Si faltan claves en [MANAGER], las crea automáticamente.
        Devuelve (ok, mensaje).
        """
        cfg_path = Config.CONFIG_FILE
        cfg = configparser.ConfigParser()
        try:
            cfg.read(str(cfg_path), encoding="utf-8")
        except Exception:
            pass

        if not cfg.has_section("MANAGER"):
            cfg.add_section("MANAGER")

        # Asegurar claves
        base_url = cfg.get("MANAGER", "base_url", fallback="https://manager.diariohuarpe.com").strip()
        debugger_address = cfg.get("MANAGER", "debugger_address", fallback="127.0.0.1:9222").strip()
        chrome_profile_dir = cfg.get("MANAGER", "chrome_profile_dir", fallback="C:\\ChromeScraperProfile").strip()

        if not cfg.has_option("MANAGER", "base_url"):
            cfg.set("MANAGER", "base_url", base_url)
        if not cfg.has_option("MANAGER", "debugger_address"):
            cfg.set("MANAGER", "debugger_address", debugger_address)
        if not cfg.has_option("MANAGER", "chrome_profile_dir"):
            cfg.set("MANAGER", "chrome_profile_dir", chrome_profile_dir)

        # Crear carpeta de perfil si no existe
        try:
            Path(chrome_profile_dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, f"No pude crear el perfil: {e}"

        # Guardar config actualizada
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception as e:
            return False, f"No pude guardar config.ini: {e}"

        # Buscar chrome.exe
        chrome_candidates = [
            r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            "chrome.exe",
        ]
        chrome_path = None
        for c in chrome_candidates:
            if Path(c).exists() or c == "chrome.exe":
                chrome_path = c
                break
        if not chrome_path:
            return False, "No encontré chrome.exe. Agregalo al PATH o definí la ruta absoluta."

        # Extraer puerto
        host, sep, port = debugger_address.partition(":")
        if not (host and port.isdigit()):
            return False, f"debugger_address inválido: {debugger_address}"

        # Armar argumentos
        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={chrome_profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure",
        ]
        if base_url:
            args.append(base_url)

        try:
            subprocess.Popen(args, shell=False)
            return True, debugger_address
        except Exception as e:
            return False, f"No pude lanzar Chrome: {e}"



    


    def _get_scraper(self):
        """
        Política definitiva:
        - Si existe [MANAGER].debugger_address → usar SIEMPRE SeleniumManagerScraper.
        - Si no existe → usar ManagerScraper (requests) SOLO para sitio público.
        """
        cfg = configparser.ConfigParser()
        try:
            cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
        except Exception:
            pass

        base_url = getattr(Config, "MANAGER_BASE_URL", "https://manager.diariohuarpe.com")
        cookie = ""
        profile = "Default"
        debugger_addr = None

        if cfg.has_section("MANAGER"):
            base_url = (cfg.get("MANAGER", "base_url", fallback=base_url) or base_url).strip()
            cookie = (cfg.get("MANAGER", "cookie", fallback="") or "").strip()
            profile = (cfg.get("MANAGER", "profile", fallback="Default") or "Default").strip()
            debugger_addr = (cfg.get("MANAGER", "debugger_address", fallback="") or "").strip()

        # ------------------------------
        # CASO 1 — Chrome Debug activo → usar Selenium para TODO
        # ------------------------------
        if debugger_addr:
            from services.manager_scraper_selenium import SeleniumManagerScraper
            return SeleniumManagerScraper(base_url=base_url, debugger_addr=debugger_addr, timeout=60)

        # ------------------------------
        # CASO 2 — SIN debug → requests (solo útil para sitio público)
        # ------------------------------
        from services.manager_scraper import ManagerScraper
        scraper = ManagerScraper(base_url=base_url, cookie=cookie,
                                 foto_pagina_service=self.foto_pagina_service)

        if not cookie:
            try:
                loaded = scraper.attach_chrome_cookies(
                    domains=[".diariohuarpe.com", "manager.diariohuarpe.com"],
                    profile=profile
                )
                _log.debug("Cookies desde Chrome cargadas: %s", loaded)
            except Exception as e:
                _log.warning("No pude cargar cookies de Chrome: %s", e)

        return scraper






    def _ensure_queue(self):
        """
        Crea (una vez) el scraper y el worker de cola en un QThread único.
        Si hay debugger_address, usa Selenium; si no, camino legacy.
        """
        if self._queue_worker:
            return

        scraper = self._get_scraper()  # respeta la política sin fallback cuando hay debugger_address
        from services.scrape_queue import ScrapeQueueWorker

        th = QThread()
        wk = ScrapeQueueWorker(scraper, self.file_service)
        wk.moveToThread(th)

        def _on_ok(n: int, txt_path: Path, imgs: list, txt_len: int | None = None):
            """
            Se ejecuta cuando el scraper finaliza correctamente.
            - Actualiza estados en memoria (solo 'asignado' gris por TXT presente).
            - Si viene txt_len, lo persiste en INI como 'nombre.txt (len)'.
            Si no viene, intenta calcularlo leyendo el TXT (fallback).
            - Luego fuerza un refresco completo como hace el cargador del MONO.
            """
            try:
                if not txt_path or not txt_path.exists():
                    _log.warning("Scraper P%02d: txt_path inválido o inexistente", n)
                    return

                _log.info("Scraper finalizado para P%02d: %s", n, txt_path.name)

                # Apagar 'completa' si estaba
                try:
                    entry = self.file_service.read_page_entry(n)
                    if entry.get("aviso_full", False):
                        self.file_service.write_page_entry(n, aviso_full=False)
                except Exception as e:
                    _log.warning("No pude apagar 'aviso_full' para P%02d: %s", n, e)

                # Estado en memoria: hay TXT disponible → gris (NO marcar asignada_por_ini)
                pag = self.gestor_paginas.obtener_pagina(n)
                if pag:
                    pag.asignado = True
                    # ⚠️ No tocar pag.asignada_por_ini ni escribir 'assigned' en INI acá

                # Persistir len en txt_name
                try:
                    if txt_len is None:
                        # fallback: computar largo del contenido (caracteres)
                        try:
                            contenido = txt_path.read_text(encoding="utf-8")
                        except UnicodeDecodeError:
                            contenido = txt_path.read_text(encoding="utf-8-sig")
                        txt_len = len(contenido.strip())

                    self.file_service.set_txt_len(n, txt_path.name, int(txt_len or 0))
                    _log.info("P%02d → %s (%d)", n, txt_path.name, int(txt_len or 0))

                except Exception as e:
                    _log.warning("No pude setear len para P%02d: %s", n, e)

                # --- NUEVO BLOQUE: refrescar como hace el cargador del MONO ---
                try:
                    self.refrescar_avisos_desde_ini()
                    if hasattr(self, "main_window") and hasattr(self.main_window, "colorear_paginas"):
                        self.main_window.colorear_paginas()
                    _log.info("Refrescado estados tras scrape de P%02d", n)
                except Exception as e:
                    _log.warning("No se pudo refrescar colores tras scrape: %s", e)

            except Exception as e:
                _log.warning("Error en _on_ok para P%02d: %s", n, e)






            # Apagar 'completa' si estaba
            try:
                entry = self.file_service.read_page_entry(n)
                if entry.get("aviso_full", False):
                    self.file_service.write_page_entry(n, aviso_full=False)
            except Exception as e:
                _log.warning("No pude apagar 'aviso_full' para P%02d: %s", n, e)

            # Estado en memoria: hay TXT disponible
            pag = self.gestor_paginas.obtener_pagina(n)
            if pag:
                pag.asignado = True

        def _on_err(n: int, msg: str):
            _log.error("Scraper P%02d: %s", n, msg)
            if self.on_scrape_error:
                self.on_scrape_error(n, msg)

        th.started.connect(wk.run)
        wk.item_ok.connect(_on_ok)
        wk.item_err.connect(_on_err)

        self._queue_thread = th
        self._queue_worker = wk
        th.start()

    def enqueue_scrape(self, numero: int, link: str):
        """
        Encola un scraping y **persiste el link** en el INI antes de intentar scrapear.
        El worker único procesa en serie (driver seguro).
        """
        # Normalizar/validar link
        link = (link or "").strip()
        if not re.match(r"^https?://", link, re.I):
            # Importa ScraperError desde services.manager_scraper (ya está en este archivo)
            raise ScraperError(f"Link inválido para scraping: {link!r}")

        # Asegurar rutas/INI (por si el usuario aún no corrió "Crear base" en esta sesión)
        try:
            self._sincronizar_rutas_en_file_service()
            #self.file_service.ensure_shared_ini() # DEPRECADO PORQUE YA NO SE USA INI CENTRAL
        except Exception as e:  
            # No bloqueamos el flujo por esto; sólo avisamos en logs
            _log.warning("No pude preparar rutas/INI antes de persistir link: %s", e)

        # Persistir el link en el INI solo si todavía no está registrado.
        # IMPORTANTE: en notas dobles (P06. link1 + link2), procesar_grilla_mono
        # ya escribe ambos links con write_page_entry + append_txt_entry antes de
        # llamar a enqueue_scrape. Si enqueue_scrape sobreescribiera el campo link,
        # el segundo link pierde al primero. Por eso solo escribimos si el link
        # no está ya presente en la lista separada por ";".
        try:
            entry     = self.file_service.read_page_entry(numero)
            links_ini = [l.strip() for l in (entry.get("link") or "").split(";") if l.strip()]
            if link not in links_ini:
                self.file_service.write_page_entry(
                    numero,
                    link=link,
                )
        except Exception as e:
            # Continuamos igual; el scraping puede ocurrir aunque falle la escritura del INI
            _log.warning("No pude registrar link en INI para P%02d: %s", numero, e)

        # Encolar el scraping (esto puede lanzar ScraperError si no hay Chrome/debug o cookie)
        self._ensure_queue()
        self._queue_worker.enqueue(numero, link)


    def stop_queue(self):
        """
        Detiene el worker de cola y cierra el QThread prolijo (para cierre de la app).
        """
        try:
            if self._queue_worker:
                self._queue_worker.stop()
            if self._queue_thread:
                self._queue_thread.quit()
                self._queue_thread.wait()
        except Exception as e:
            _log.warning("Al cerrar la cola: %s", e)
        finally:
            self._queue_worker = None
            self._queue_thread = None


    

    # ---------- Rutas / Base ----------
    def _sincronizar_rutas_en_file_service(self):
        """
        Sincroniza las rutas actuales de RutasEstado con el FileService.
        Incluye siempre la carpeta de avisos del día de mañana.
        """
        avisos_dir = None
        avisos2_dir = None
        try:
            if getattr(self.rutas, "avisos_root", None):
                avisos_dir = self.rutas.resolve_avisos_maniana()
            if getattr(self.rutas, "avisos2_root", None):
                # reutilizamos la misma función pero forzando root distinto
                original_root = self.rutas.avisos_root
                self.rutas.avisos_root = self.rutas.avisos2_root
                avisos2_dir = self.rutas.resolve_avisos_maniana()
                self.rutas.avisos_root = original_root
        except Exception:
            avisos_dir = None
            avisos2_dir = None

        self.file_service.set_rutas({
            "personal_folder": self.rutas.personal_folder,
            "quark_output_dir": self.rutas.quark_output_dir,
            "pdf_output_dir": self.rutas.pdf_output_dir,
            "pdf_ok_dir": self.rutas.pdf_ok_dir,
            #"shared_ini_path": self.rutas.shared_ini_path, DEPRECADO PORQUE YA NO SE USA INI CENTRAL
            "material": (
                self.rutas.quark_output_dir / "materiales"
                if self.rutas.quark_output_dir else None
            ),
            "avisos_dir": avisos_dir,
            "avisos2_dir": avisos2_dir,
            "pool": self.rutas.pool_root,
            "maquetas_root": self.rutas.maquetas_root,
        })
        if self.rutas.maquetas_root:
            from services.maqueta_reader_service import set_override_maquetas_dir
            set_override_maquetas_dir(self.rutas.maquetas_root)


    # Nuevo flujo: se llama SOLO desde el botón "Crear Base"
    def crear_base_on_click(self, prompt_fn):
        # 1) Cargar de ini o pedir lo que falte (una sola vez)
        self.rutas.ensure_roots(prompt_fn)
        # 2) Crear base/carpeta PDF/OK y En proceso
        info = self.rutas.crear_base_maniana()
        # 3) Sincronizar rutas operativas
        self._sincronizar_rutas_en_file_service()
        #self.file_service.ensure_shared_ini() # DEPRECADO PORQUE YA NO SE USA INI CENTRAL
        # 4) Migrar al esquema completo por si la edición ya tenía un INI antiguo
        #self.file_service.migrate_ini_schema() # DEPRECADO PORQUE YA NO SE USA INI CENTRAL
        return info

    def cargar_edicion(self, base_dir):
        """Carga una edición EXISTENTE como base activa (sin crear una nueva).
        Apunta quark_output_dir a la carpeta elegida; el material se deriva como
        <edición>/materiales en _sincronizar_rutas_en_file_service."""
        from pathlib import Path as _Path
        import re as _re
        base_dir = _Path(base_dir)
        if not base_dir.exists():
            raise FileNotFoundError(f"No existe la edición:\n{base_dir}")
        self.rutas.quark_output_dir = base_dir
        # Derivar carpetas PDF desde la fecha del nombre de la edición (best-effort).
        try:
            meses = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
                     "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
            m = _re.search(r"(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})", base_dir.name.upper())
            if m and m.group(2) in meses:
                dia = int(m.group(1)); mes_str = m.group(2); anio = int(m.group(3))
                mes_idx = meses.index(mes_str) + 1
                # #1 — fecha de la edición cargada (para gatear la sincronización).
                import datetime as _dt
                try:
                    self.rutas.fecha_edicion = _dt.date(anio, mes_idx, dia)
                except ValueError:
                    self.rutas.fecha_edicion = None
                if getattr(self.rutas, "pdf_root", None):
                    pdf_day = _Path(self.rutas.pdf_root) / mes_str / f"{dia}-{mes_idx}"
                    self.rutas.pdf_output_dir = pdf_day
                    self.rutas.pdf_ok_dir = pdf_day / "OK"
        except Exception:
            pass
        self._sincronizar_rutas_en_file_service()
        return {"base_dir": base_dir}

    # ---------- Verificaciones ----------
    def archivo_asociado_a_estado(self, numero: int) -> Optional[Path]:
        """
        Prioridades:
        - impreso/revisado -> PDF (carpeta diaria, luego OK)

        - corregido -> QXP en 'final/mandar'
        - fotocromia -> QXP en 'final'
        - armado -> QXP en base (prefijo 'Pag NN')
        - asignado -> material/NN.txt

        (Unificado) El perfil "Maquetación y avisos" abre con el mismo criterio que el resto.
        """
        pag = self.gestor_paginas.obtener_pagina(numero)
        if not pag:
            return None

        # ✅ Unificación: NO abrir "dos qxps" ni devolver listas
        # (se elimina find_qxp_pares_maquetacion / _ultimo_qxp_multiple)

        # PDF primero si aplica
        if pag.impreso or pag.revisado:
            pdf = self.file_service.find_pdf_for_page(numero)
            if pdf:
                return pdf

        # QXP por estado
        if pag.apdf:
            p = self.file_service.find_qxp_apdf(numero)
            if p:
                return p

        if pag.corregido:
            p = self.file_service.find_qxp_mandar(numero)
            if p:
                return p
        if pag.fotocromia:
            p = self.file_service.find_qxp_final(numero)
            if p:
                return p
        if pag.armado:
            p = self.file_service.find_qxp_base(numero)
            if p:
                return p

        # Material asignado (TXT local presente)
        if pag.asignado:
            txt = self.file_service.obtener_txt(numero)
            if txt and txt.exists():
                return txt

        # Último intento: si hay PDF aunque flags no estén al día
        pdf = self.file_service.find_pdf_for_page(numero)
        if pdf:
            return pdf

        return None
    
    # =====================================================
    #  Resolver fuente para spreads (dobles páginas)
    # =====================================================
    def resolver_fuente_para_spread(self, numero: int) -> Optional[Path]:
        jerarquia = {"proceso": 1, "base": 2, "final": 3, "mandar": 4}
        entry = self.file_service.read_page_entry(numero)
        estado_num = (entry.get("estado") or "").strip().lower()
        nivel_num = jerarquia.get(estado_num, 0)

        pareja = numero + 1 if numero % 2 == 0 else numero - 1
        entry_par = self.file_service.read_page_entry(pareja) if 1 <= pareja <= 16 else {}
        estado_par = (entry_par.get("estado") or "").strip().lower()
        nivel_par = jerarquia.get(estado_par, 0)

        rutas = self.file_service.rutas or {}
        base_dir   = Path(rutas.get("quark_output_dir") or "")
        final_dir  = base_dir / "final"
        mandar_dir = final_dir / "mandar"
        en_proc_dir = Path(rutas.get("personal_folder") or "")

        def buscar_individual(estado: str):
            if estado == "proceso": return self.file_service.buscar_qxp_por_numero(en_proc_dir, numero)
            if estado == "base":    return self.file_service.buscar_qxp_por_numero(base_dir, numero)
            if estado == "final":   return self.file_service.buscar_qxp_por_numero(final_dir, numero)
            if estado == "mandar":  return self.file_service.buscar_qxp_por_numero(mandar_dir, numero)
            return None

        # Sin pareja registrada → individual
        if not entry_par:
            return buscar_individual(estado_num)

        # Distintos niveles → mover solo la individual
        if nivel_num != nivel_par:
            return buscar_individual(estado_num)

        # Misma jerarquía y no "proceso" → spread permitido
        if estado_num != "proceso" and nivel_num > 1:
            spread = self.file_service.buscar_qxp_spread(numero, pareja)
            if spread:
                return spread

        return buscar_individual(estado_num)


    
    def pdf_path_para_descartar(self, numero: int) -> Optional[Path]:
        """
        Devuelve el Path del PDF a descartar según el estado:
        - verde claro (pag.impreso)  -> carpeta OK
        - verde oscuro (pag.revisado)-> carpeta diaria
        """
        pag = self.gestor_paginas.obtener_pagina(numero)
        if not pag:
            return None

        # elegir carpeta base según estado
        pdf_dir = Path(self.file_service.rutas.get("pdf_output_dir") or "")
        ok_dir = Path(self.file_service.rutas.get("pdf_ok_dir") or (pdf_dir / "OK"))

        carpeta = None
        if pag.impreso:
            carpeta = ok_dir
        elif pag.revisado:
            carpeta = pdf_dir
        else:
            return None  # no aplica descartar

        # armar candidatos NN.PDF / NN.pdf
        for ext in (".PDF", ".pdf"):
            cand = carpeta / f"{numero:02}{ext}"
            if cand.exists():
                return cand
        return None

    def descartar_pdf(self, numero: int) -> None:
        """
        Envía a la papelera el PDF de la página según su estado actual.
        """
        pdf_path = self.pdf_path_para_descartar(numero)
        if not pdf_path:
            raise FileServiceError("No encontré un PDF para descartar según el estado actual.")
        self.file_service.eliminar_pdf(pdf_path)
        pag = self.gestor_paginas.obtener_pagina(numero)
        if pag:
            pag.impreso = False
            pag.revisado = False
        

    def descartar_qxp_materiales(self, numero: int) -> int:
        """Descarta el QXP de la página en TODAS las ubicaciones (materiales, proceso,
        base, final, mandar, a pdf). Lanza FileServiceError si alguno está abierto."""
        return self.file_service.eliminar_qxp_todas_ubicaciones(numero)

    def hay_qxp(self, numero: int) -> bool:
        """True si la página tiene algún .qxp en cualquier ubicación."""
        return bool(self.file_service.listar_qxp_todas_ubicaciones(numero))

    def enrocar_paginas(self, x: int, y: int, con_aviso: bool, qxp_mode: str = "ninguno") -> None:
        """Intercambia el contenido de dos páginas y refresca el estado en memoria."""
        self.file_service.enrocar_paginas(x, y, con_aviso, qxp_mode)
        # Releer INI → gestor_paginas (avisos, asignación, estado, sección…)
        self.refrescar_avisos_desde_ini()

    def refrescar_avisos_desde_ini(self):
        me = (self.usuario or "").strip().lower()

        for i in range(1, 17):
            pag = self.gestor_paginas.obtener_pagina(i)
            if not pag:
                continue

            entry = self.file_service.read_page_entry(i)
            # --- TXT local ---
            try:
                p = self.file_service.obtener_txt(i)
                pag.asignado = bool(p and p.exists() and p.stat().st_size > 0)
            except Exception:
                pag.asignado = False

            # Avisos
            pag.aviso_full   = bool(entry.get("aviso_full",   False))
            pag.aviso_half   = bool(entry.get("aviso_half",   False))
            pag.aviso_footer = bool(entry.get("aviso_footer", False))
            pag.aviso_robapagina = bool(entry.get("aviso_robapagina", False))
            pag.aviso_nombre = (entry.get("aviso_nombre") or "").strip()

            # Si la página ya no tiene aviso (p.ej. al cambiar de edición), limpiar el
            # pixmap cacheado para que no persista el aviso de la edición anterior.
            if not (pag.aviso_full or pag.aviso_half or pag.aviso_footer
                    or pag.aviso_robapagina) or not pag.aviso_nombre:
                pag.aviso_pixmap = None
                pag.aviso_mtime = None
                if hasattr(pag, "aviso_path"):
                    pag.aviso_path = None

            # Foto y título de tapa
            pag.tapa_foto = bool(entry.get("tapa_foto", False))
            pag.tapa_titulo = bool(entry.get("tapa_titulo", False))
            pag.listo_para_armar = bool(entry.get("listo_para_armar", False))
            pag.armado_bot = bool(entry.get("armado_bot", False))
            pag.editando = bool(entry.get("editando", False))
            pag.editando_por = (entry.get("editando_por") or "").strip()
            _me_ed = (self.usuario or "").strip().lower()
            pag.editando_por_otro = bool(
                pag.editando and pag.editando_por and pag.editando_por.lower() != _me_ed
            )

            # Intentar mover aviso desde base → materiales
            #if pag.aviso_nombre:
            #    try:
            #        self.file_service.find_aviso_file_from_base(i, pag.aviso_nombre)
            #    except Exception as e:
            #        print(f"[WARN] No pude mover aviso desde base para P{i:02d}: {e}")

            # Sección
            pag.seccion = (entry.get("seccion") or "").strip()

            # Asignación por INI
            assigned_ini = bool(entry.get("assigned", False))
            by_ini       = (entry.get("by") or "").strip()

            pag.asignada_por_ini = assigned_ini
            pag.asignada_por_ini_user = by_ini
            pag.asignada_por_otro = bool(assigned_ini and by_ini and by_ini.strip().lower() != me)

            # Mantener la maqueta de nota.json en sync con el aviso del INI (poll incluido)
            try:
                self.file_service.sincronizar_maqueta_pagina(i)
            except Exception:
                pass

    def marcar_tapa_foto(self, numero: int, by: str = ""):
        self.file_service.write_page_entry(numero, tapa_foto=True, by=by)
        pag = self.gestor_paginas.obtener_pagina(numero)
        if pag: pag.tapa_foto = True

    def marcar_tapa_titulo(self, numero: int, by: str = ""):
        self.file_service.write_page_entry(numero, tapa_titulo=True, by=by)
        pag = self.gestor_paginas.obtener_pagina(numero)
        if pag: pag.tapa_titulo = True

    def limpiar_tapa_flags(self, numero: int, by: str = ""):
        self.file_service.write_page_entry(numero, tapa_foto=False, tapa_titulo=False, by=by)
        pag = self.gestor_paginas.obtener_pagina(numero)
        if pag:
            pag.tapa_foto = False
            pag.tapa_titulo = False




    # ──────────────────────────────────────────────────────────────
    # Foto de tapa desde el visor de imágenes del pool
    # ──────────────────────────────────────────────────────────────

    FOTO_TAPA_NOMBRE  = "foto de tapa"          # sin extensión
    FOTO_TAPA_ORIGEN  = "foto_tapa_origen.json"  # metadato de qué página/pool la marcó

    def copiar_foto_tapa_a_p01(
        self,
        src: Path,
        pagina: Optional[int] = None,
        pool_dir: Optional[Path] = None,
    ) -> Path:
        """
        Copia `src` a materiales/P01/ con el nombre "foto de tapa<ext>".
        Sobreescribe si ya existía.

        Parámetros opcionales de origen (solo uno debe venir):
            pagina   — número de página del visor principal (1-16).
            pool_dir — carpeta del pool desde cuyo editor se marcó.

        Guarda `foto_tapa_origen.json` en P01 para que la UI sepa cuál
        página/pool "posee" la foto de tapa y muestre la estrella
        amarilla únicamente allí.
        """
        import json
        import shutil
        from services.file_service import FileServiceError

        mat = self.file_service.material
        if not mat or not mat.exists():
            raise FileServiceError(
                "No hay edición activa configurada.\n"
                "Ejecutá 'Crear base' antes de marcar foto de tapa."
            )

        dest_dir = mat / "P01"
        dest_dir.mkdir(parents=True, exist_ok=True)

        ext  = src.suffix.lower()
        dest = dest_dir / f"{self.FOTO_TAPA_NOMBRE}{ext}"
        shutil.copy2(str(src), str(dest))
        _log.info("Foto tapa copiada: %s → %s", src.name, dest)

        # Guardar origen para que la UI solo active la estrella en esa página/pool
        # y SOLO cuando la imagen visible es la marcada (#6) → guardamos el nombre original.
        origen: dict = {"archivo": src.name}
        if pagina is not None:
            origen["pagina"] = pagina
        if pool_dir is not None:
            origen["pool_dir"] = str(pool_dir)

        try:
            origen_path = dest_dir / self.FOTO_TAPA_ORIGEN
            origen_path.write_text(
                json.dumps(origen, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            _log.warning("No se pudo guardar origen foto tapa: %s", e)

        return dest

    def borrar_foto_tapa_de_p01(self) -> None:
        """
        Elimina el archivo "foto de tapa.*" y el metadato de origen
        de materiales/P01/ si existen. No lanza excepción si no se encuentran.
        """
        import os

        mat = self.file_service.material
        if not mat:
            return

        dest_dir = mat / "P01"
        if not dest_dir.exists():
            return

        borrados = []
        for f in dest_dir.iterdir():
            if f.is_file() and f.stem.lower() == self.FOTO_TAPA_NOMBRE:
                try:
                    os.remove(f)
                    borrados.append(f.name)
                    _log.info("Foto tapa borrada: %s", f)
                except OSError as e:
                    _log.warning("No se pudo borrar foto tapa %s: %s", f, e)

        # Borrar también el metadato de origen
        origen_path = dest_dir / self.FOTO_TAPA_ORIGEN
        if origen_path.exists():
            try:
                origen_path.unlink()
            except OSError:
                pass

        if not borrados:
            _log.debug("No se encontró archivo para borrar en P01.")

    def foto_tapa_en_p01(self) -> Optional[Path]:
        """
        Devuelve el Path del archivo "foto de tapa.*" en P01 si existe, o None.
        """
        mat = self.file_service.material
        if not mat:
            return None
        dest_dir = mat / "P01"
        if not dest_dir.exists():
            return None
        for f in dest_dir.iterdir():
            if f.is_file() and f.stem.lower() == self.FOTO_TAPA_NOMBRE:
                return f
        return None

    def foto_tapa_pagina_origen(self) -> Optional[int]:
        """
        Devuelve el número de página que marcó la foto de tapa, o None si
        fue marcada desde el pool o si no hay origen guardado.
        """
        import json
        mat = self.file_service.material
        if not mat:
            return None
        origen_path = mat / "P01" / self.FOTO_TAPA_ORIGEN
        if not origen_path.exists():
            return None
        try:
            data = json.loads(origen_path.read_text(encoding="utf-8"))
            v = data.get("pagina")
            return int(v) if v is not None else None
        except Exception:
            return None

    def foto_tapa_archivo_origen(self) -> Optional[str]:
        """Nombre del archivo original marcado como foto de tapa, o None (#6)."""
        import json
        mat = self.file_service.material
        if not mat:
            return None
        origen_path = mat / "P01" / self.FOTO_TAPA_ORIGEN
        if not origen_path.exists():
            return None
        try:
            data = json.loads(origen_path.read_text(encoding="utf-8"))
            arch = (data.get("archivo") or "").strip()
            return arch or None
        except Exception:
            return None

    def foto_tapa_pool_dir_origen(self) -> Optional[Path]:
        """
        Devuelve el Path del pool que marcó la foto de tapa, o None.
        """
        import json
        mat = self.file_service.material
        if not mat:
            return None
        origen_path = mat / "P01" / self.FOTO_TAPA_ORIGEN
        if not origen_path.exists():
            return None
        try:
            data = json.loads(origen_path.read_text(encoding="utf-8"))
            v = data.get("pool_dir")
            return Path(v) if v else None
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Selección de fotos de página
    # ──────────────────────────────────────────────────────────────

    def _mat(self) -> Optional[Path]:
        """Devuelve material Path o None si no hay edición activa."""
        return self.file_service.material

    def cargar_estado_fotos_pagina(self, pagina: int,
                                    subfolder: Optional[str]) -> dict:
        """Carga fotos_seleccionadas.json desde disco."""
        mat = self._mat()
        if not mat:
            return {}
        return self.foto_pagina_service.cargar(pagina, subfolder, mat)

    def seleccionar_foto_pagina(self, pagina: int, subfolder: Optional[str],
                                 path: Path, nombre: str) -> dict:
        """Agrega path a la lista de fotos seleccionadas y persiste."""
        mat = self._mat()
        if not mat:
            return {}
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        estado = self.foto_pagina_service.seleccionar(estado, path, nombre)
        self.foto_pagina_service.guardar(estado, pagina, subfolder, mat)
        return estado

    def deseleccionar_foto_pagina(self, pagina: int, subfolder: Optional[str],
                                   path: Path) -> dict:
        """Quita path de la lista y persiste."""
        mat = self._mat()
        if not mat:
            return {}
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        estado = self.foto_pagina_service.deseleccionar(estado, path)
        self.foto_pagina_service.guardar(estado, pagina, subfolder, mat)
        return estado

    def mover_foto_arriba(self, pagina: int, subfolder: Optional[str],
                           path: Path) -> dict:
        mat = self._mat()
        if not mat:
            return {}
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        estado = self.foto_pagina_service.mover_arriba(estado, path)
        self.foto_pagina_service.guardar(estado, pagina, subfolder, mat)
        return estado

    def mover_foto_abajo(self, pagina: int, subfolder: Optional[str],
                          path: Path) -> dict:
        mat = self._mat()
        if not mat:
            return {}
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        estado = self.foto_pagina_service.mover_abajo(estado, path)
        self.foto_pagina_service.guardar(estado, pagina, subfolder, mat)
        return estado

    def actualizar_path_foto_renombrada(self, pagina: int, subfolder: Optional[str],
                                         src: Path, dest: Path) -> dict:
        """Actualiza el path de una foto en la selección tras renombrarla en disco."""
        mat = self._mat()
        if not mat:
            return {}
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        estado = self.foto_pagina_service.actualizar_path(estado, src, dest)
        self.foto_pagina_service.guardar(estado, pagina, subfolder, mat)
        return estado

    def marcar_pegadas(self, pagina: int, subfolder: Optional[str],
                       texto: Optional[str] = None) -> None:
        """Sella pegadas_at y hashes en fotos_seleccionadas.json."""
        mat = self._mat()
        if not mat:
            return
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        estado = self.foto_pagina_service.marcar_pegadas(estado, texto)
        self.foto_pagina_service.guardar(estado, pagina, subfolder, mat)

    def ya_fue_pegado(self, pagina: int, subfolder: Optional[str],
                      texto_actual: Optional[str] = None) -> bool:
        """True si el contenido actual ya fue pegado con el mismo estado."""
        mat = self._mat()
        if not mat:
            return False
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        return self.foto_pagina_service.ya_fue_pegado(estado, texto_actual)

    def fotos_sin_editar(self, pagina: int,
                          subfolder: Optional[str]) -> list:
        """Devuelve lista de paths (str) de fotos seleccionadas no editadas."""
        mat = self._mat()
        if not mat:
            return []
        estado = self.foto_pagina_service.cargar(pagina, subfolder, mat)
        return self.foto_pagina_service.fotos_no_editadas(
            estado.get("fotos", []), pagina, mat
        )

    def verificar_qxp_pdf(self):
        """Lee disco y actualiza estados del Gestor; devuelve True si hubo cambios."""
        qxp = self.file_service.snapshot_qxp()
        pdf = self.file_service.snapshot_pdf()

        hubo_cambio = False
        for i in range(1, 17):
            pag = self.gestor_paginas.obtener_pagina(i)
            est_q = qxp.get(i, {})
            est_p = pdf.get(i, {})
            cambios = {
                "armado": bool(est_q.get("armado")),
                "fotocromia": bool(est_q.get("fotocromia")),
                "corregido": bool(est_q.get("corregido")),
                "apdf": bool(est_q.get("apdf")),
                "revisado": bool(est_p.get("revisado")),
                "impreso": bool(est_p.get("impreso")),
            }
            for k, v in cambios.items():
                if getattr(pag, k) != v:
                    setattr(pag, k, v)
                    hubo_cambio = True

            # --- Leer INI una vez para esta página ---
            entry = self.file_service.read_page_entry(i)

            # qxp detectado en base → ya no está "listo para armar" ni "armado bot". Se mira el
            # INI (no el flag en memoria, que puede quedar desincronizado).
            if cambios["armado"] and str(entry.get("listo_para_armar", "")).strip().lower() == "true":
                pag.listo_para_armar = False
                try:
                    self.file_service.write_page_entry(i, listo_para_armar="false")
                except Exception:
                    pass
                hubo_cambio = True
            if cambios["armado"] and str(entry.get("armado_bot", "")).strip().lower() == "true":
                pag.armado_bot = False
                try:
                    self.file_service.write_page_entry(i, armado_bot="false")
                except Exception:
                    pass
                hubo_cambio = True

            # --- NUEVO BLOQUE ---
            estado_ini = (entry.get("estado") or "").strip().lower()

            # Calcular nuevo estado detectado en disco
            nuevo_estado = ""
            if cambios["armado"]:
                nuevo_estado = "base"
            if cambios["fotocromia"]:
                nuevo_estado = "final"
            if cambios["corregido"]:
                nuevo_estado = "mandar"
            if cambios["revisado"]:
                nuevo_estado = "pdf"
            if cambios["impreso"]:
                nuevo_estado = "ok"

            # Si el nuevo estado detectado es distinto del INI, actualizar
            if nuevo_estado and nuevo_estado != estado_ini:
                try:
                    # ============================================================
                    # Evitar subida de estado por spread con niveles distintos
                    # ============================================================
                    if nuevo_estado in ("final", "mandar"):
                        pareja = i + 1 if i % 2 == 0 else i - 1
                        if not (1 <= pareja <= 16):
                            pareja = None

                        entry_par = {}
                        if pareja:
                            entry_par = self.file_service.read_page_entry(pareja)

                        estado_num = (entry.get("estado") or "").lower()
                        estado_par = (entry_par.get("estado") or "").lower()

                        jerarquia = {"proceso": 1, "base": 2, "final": 3, "mandar": 4}
                        nivel_num = jerarquia.get(estado_num, 0)
                        nivel_par = jerarquia.get(estado_par, 0)

                        spread = None
                        if pareja:
                            spread = self.file_service.buscar_qxp_spread(i, pareja)

                        if spread and spread.exists() and nivel_num != nivel_par:
                            # Caso A: la página actual está por debajo del spread → no sube
                            if nivel_num < nivel_par:
                                _log.info("Spread %s/%s → P%02d (%s) vs P%02d (%s) → omito actualización (nivel inferior).",
                                          spread.parent.name, spread.name, i, estado_num, pareja, estado_par)
                                continue  # no escribir

                            # Caso B: la página actual está por encima → actualizar solo esta, sin sincronizar pareja inferior
                            elif nivel_num > nivel_par:
                                _log.info("Spread %s/%s → P%02d (%s) > P%02d (%s) → actualizo solo P%02d.",
                                          spread.parent.name, spread.name, i, estado_num, pareja, estado_par, i)
                                # seguimos sin 'continue': se escribe el nuevo estado solo para esta página


                    # Escritura original
                    self.file_service.write_page_entry(i, estado=nuevo_estado)
                    _log.info("P%02d detectada en disco → estado='%s' (antes='%s')", i, nuevo_estado, estado_ini)

                except Exception as e:
                    _log.warning("No pude escribir estado automático para P%02d: %s", i, e)

        return hubo_cambio


    # --- Botonera mover/devolver ---
    def decidir_botones(self, numero: int):
        """
        Determina las acciones posibles (mover / devolver) para la página dada,
        considerando el perfil activo y posibles spreads.
        Evita búsquedas innecesarias en páginas sin pareja (1 y 16).
        """
        decision = self.file_service.decidir_mover_y_devolver(numero)
        
        # 🔹 Guard clause: páginas fuera de rango o sin pareja posible
        if not (1 <= numero <= 16) or numero in (1, 16):
            return decision

        mover = decision.get("mover", {})

        if mover.get("enabled") and mover.get("src"):
            override_src = self.resolver_fuente_para_spread(numero)
            if override_src:
                dest_actual = mover.get("dest")
                if dest_actual:
                    dest_dir = Path(dest_actual).parent
                    decision["mover"].update(src=override_src, dest=dest_dir / override_src.name)
                else:
                    decision["mover"].update(src=override_src)

        return decision

    def ejecutar_mover(self, src: Path, dest: Path):
        """
        Ejecuta el movimiento o copia del archivo indicado.
        La operación real (copiar/mover + actualización del INI)
        se realiza exclusivamente dentro de FileService.
        """
        try:
            result = self.file_service.ejecutar_mover(src, dest)

            # Archivo abierto → no hacer nada, avisar a UI
            if result == "locked":
                _log.warning("No se puede mover porque está abierto: %s -> %s", src, dest)
                return "locked"

            # Error general
            if result is False:
                _log.error("mover falló: %s -> %s", src, dest)
                return False

            # Movimiento/copia exitoso
            return True

        except Exception as e:
            _log.error("ejecutar_mover falló: %s -> %s | %s", src, dest, e)
            return False



    def ejecutar_devolver(self, src: Path, dest: Path):
        """
        Ejecuta la devolución del archivo indicado.
        La operación real se delega completamente a FileService.
        """
        try:
            result = self.file_service.ejecutar_devolver(src, dest)

            if result == "locked":
                _log.warning("No se puede devolver porque está abierto: %s -> %s", src, dest)
                return "locked"

            if result is False:
                _log.error("devolver falló: %s -> %s", src, dest)
                return False

            return True

        except Exception as e:
            _log.error("ejecutar_devolver falló: %s -> %s | %s", src, dest, e)
            return False




    # ---------- Quark ----------
    ## ESTO LUEGO SE ARREGLA, POR EL MOMENTO FUNCIONA CON Z EN LUGAR DE 192.168...ETC
    def _forzar_z_desde_unc(self, p: str) -> str: 
        if not p:
            return p

        # Normalizar separadores por si viene con / mezclados
        s = p.replace("/", "\\").strip()

        # Caso 1: UNC exacto del vault nuevo
        prefix = "\\\\192.168.20.19\\vault\\"  # en memoria: \\192.168.20.19\vault\
        if s.lower().startswith(prefix.lower()):
            resto = s[len(prefix):]  # lo que viene después de \\server\vault\
            return "Z:\\vault\\" + resto  # en memoria: Z:\vault\

        # Caso 2: ya viene con letra, no tocar
        if len(s) >= 3 and s[1] == ":" and (s[2] == "\\" or s[2] == "/"):
            return s

        return s


    def composicion_pagina(self, numero: int, subfolder: Optional[str] = None) -> dict:
        """Resumen de composición de la nota principal de la página (para el overlay del QR
        al pegar y el aviso final del script de pegado):
        {seccion, fecha, textual: <tipo|None>, textual_cargo, dato, numero,
         foto_tipo, foto_cant, firma, aviso, qr}."""
        comp = {"seccion": "", "fecha": "", "textual": None, "textual_cargo": "",
                "textual_nombre": "", "dato": False, "numero": False, "foto_tipo": "",
                "foto_cant": 0, "foto_nombres": [], "firma": False, "firma_nombre": "",
                "aviso": "", "aviso_nombre": "", "aviso_tipo": "", "qr": False}
        try:
            entry = self.file_service.read_page_entry(numero)
            comp["seccion"] = (entry.get("seccion") or "").strip()
            # --- Aviso (nombre + tipo) ---
            aviso_nombre = (entry.get("aviso_nombre") or "").strip()
            if entry.get("aviso_full"):
                comp["aviso_tipo"] = "full"
            elif entry.get("aviso_half"):
                comp["aviso_tipo"] = "half"
            elif entry.get("aviso_footer"):
                comp["aviso_tipo"] = "footer"
            elif entry.get("aviso_robapagina"):
                comp["aviso_tipo"] = "robapagina"
            comp["aviso_nombre"] = aviso_nombre
            if aviso_nombre:
                _label = {"full": "Completa", "half": "Media", "footer": "Pie",
                          "robapagina": "Robapágina"}.get(comp["aviso_tipo"], "")
                comp["aviso"] = f"{aviso_nombre} ({_label})" if _label else aviso_nombre
            # --- Fecha de edición ---
            try:
                fe = getattr(self.rutas, "fecha_edicion", None)
                if fe:
                    comp["fecha"] = fe.strftime("%d/%m/%Y")
            except Exception:
                pass
            # --- Cantidad de fotos seleccionadas ---
            try:
                mat = self._mat()
                if mat:
                    sel = self.foto_pagina_service.cargar(numero, subfolder, mat)
                    fotos = sel.get("fotos", [])
                    comp["foto_cant"] = len(fotos)
                    comp["foto_nombres"] = [
                        (f.get("nombre") or "").strip()
                        for f in fotos if (f.get("nombre") or "").strip()
                    ]
            except Exception:
                pass
            for nota in self.file_service.get_notas(numero):
                if (nota.get("rol") or "").lower() != "principal":
                    continue
                jp = nota.get("json_path")
                if not jp:
                    break
                nd = json.loads(jp.read_text(encoding="utf-8"))
                tx = nd.get("textual")
                if isinstance(tx, dict):
                    comp["textual"] = tx.get("tipo") or None
                    comp["textual_nombre"] = (tx.get("nombre1") or "").strip()
                    comp["textual_cargo"] = (tx.get("cargo1") or "").strip()
                dato = nd.get("dato")
                comp["dato"] = bool(dato.strip()) if isinstance(dato, str) else bool(dato)
                comp["numero"] = bool(nd.get("numero"))
                comp["foto_tipo"] = (nd.get("foto_tipo") or "").strip()
                comp["firma"] = bool(nd.get("firma_habilitada"))
                if comp["firma"]:
                    comp["firma_nombre"] = (nd.get("firma") or "").strip()
                comp["qr"] = bool(nd.get("qr_path") or (nd.get("_debug_qr") or {}).get("qrLinks"))
                break
        except Exception as e:
            _log.debug("composicion_pagina P%02d: %s", numero, e)
        return comp

    def _box_positions_para_js(self) -> dict:
        """P6a (spike): mapea box-name → posición destino (coords de PANTALLA calibradas) para
        que el JS pruebe mover cajas. Test inicial: Box427 (textual simple) → 'textual_dst_1'."""
        pos = {}
        try:
            p = config_global.auto_centro("textual_dst_1")
            if p:
                pos["Box427"] = {"x": int(p[0]), "y": int(p[1])}
        except Exception:
            pass
        return pos

    def _preparar_data_pagina(self, numero: int, tiene_texto: bool = True,
                               subfolder: Optional[str] = None,
                               excluir_fotos: bool = False):
        """
        Genera el archivo JSON con número de página, sección, avisos y fotos
        para que el script de Quark lo lea antes del pegado.

        Parámetros:
            numero        — número de página (1-16).
            tiene_texto   — si hay texto a pegar.
            subfolder     — nombre del subfolder activo (p.ej. '06a') o None.
            excluir_fotos — si True, escribe "fotos": [] (pegar solo texto/aviso).
        """
        try:
            base_scripts = Config.RUNTIME_SCRIPTS_DIR
            base_scripts.mkdir(parents=True, exist_ok=True)
            ruta_json = base_scripts / "data_pagina.json"

            # --- Obtener sección desde INI o desde memoria ---
            entry = self.file_service.read_page_entry(numero)
            seccion = (entry.get("seccion") or "").strip()

            if not seccion:
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag and getattr(pag, "seccion", ""):
                    seccion = pag.seccion.strip()

            if not seccion:
                seccion = ""

            # --- Avisos (opcional) ---
            avisos = []
            try:
                aviso_nombre = (entry.get("aviso_nombre") or "").strip()
                if aviso_nombre:
                    if entry.get("aviso_footer"):
                        tipo = "pie"
                    elif entry.get("aviso_half"):
                        tipo = "media"
                    elif entry.get("aviso_full"):
                        tipo = "completa"
                    elif entry.get("aviso_robapagina"):
                        tipo = "robapagina"
                    else:
                        tipo = ""

                    if tipo:
                        aviso_path = (self.file_service.material / f"P{numero:02d}" / aviso_nombre)
                        _log.debug("aviso_path: %s", aviso_path)
                        path_str = self._forzar_z_desde_unc(str(aviso_path))
                        _log.debug("path_str: %s", path_str)
                        from services.file_service import espacio_color as _espacio
                        avisos.append({"tipo": tipo, "path": str(path_str),
                                       "espacio": _espacio(aviso_path)})
            except Exception:
                avisos = []

            # --- Fotos seleccionadas ---
            fotos_data: list = []
            if not excluir_fotos:
                try:
                    from pathlib import Path as _PP
                    from services.file_service import firma_imagen as _firma
                    from services.file_service import espacio_color as _espacio
                    mat = self._mat()
                    if mat:
                        sel_path = self.foto_pagina_service._base_dir(
                            numero, subfolder, mat) / "fotos_seleccionadas.json"
                        fotos_estado = self.foto_pagina_service.cargar(
                            numero, subfolder, mat
                        )
                        seleccion = fotos_estado.get("fotos", [])
                        _log.info("Fotos P%02d: subfolder=%s, excluir_fotos=%s, "
                                  "seleccionadas=%d (%s)",
                                  numero, subfolder, excluir_fotos, len(seleccion), sel_path)
                        for f in seleccion:
                            path_str = self._forzar_z_desde_unc(f["path"])
                            p = _PP(path_str)
                            if not p.exists():
                                # Resiliencia: buscar por stem en el subfolder (.jpeg↔.jpg,
                                # renombres menores) antes de descartar la foto.
                                alt = None
                                try:
                                    for cand in p.parent.iterdir():
                                        if (cand.is_file()
                                                and cand.stem.lower() == p.stem.lower()):
                                            alt = cand
                                            break
                                except Exception:
                                    alt = None
                                if alt is not None:
                                    _log.info("Foto P%02d resuelta por stem: %s → %s",
                                              numero, p.name, alt.name)
                                    path_str, p = str(alt), alt
                                else:
                                    _log.warning("Foto P%02d seleccionada NO está en disco "
                                                 "(se omite): %s", numero, path_str)
                                    continue
                            _log.info("Foto P%02d servida [%s]: %s [%s]",
                                      numero, f.get("rol"), p.name, _firma(p))
                            fotos_data.append({
                                "path":   path_str,
                                "nombre": f["nombre"],
                                "orden":  f["orden"],
                                "rol":    f["rol"],
                                "espacio": _espacio(p),
                            })
                        _log.info("Fotos P%02d servidas al pegado: %d", numero, len(fotos_data))
                except Exception as e:
                    _log.warning("No se pudieron leer fotos_seleccionadas: %s", e)

            # --- Notas derivadas del DISCO, ordenadas por rol↔sufijo (a,b,c…) ---
            #     rol = sufijo (a=principal, b=secundaria, c=noticia_3…). Sin txt_name.
            mat = self._mat()
            notas_data: list = []
            for nota in self.file_service.get_notas(numero):
                rol = nota["rol"]
                base_name = nota["dir"].name
                if nota["json_path"]:
                    try:
                        nota_data = json.loads(nota["json_path"].read_text(encoding="utf-8"))
                        nota_data["indice"] = base_name
                        nota_data["rol"] = rol
                        if nota_data.get("qr_path"):
                            nota_data["qr_path"] = self._forzar_z_desde_unc(nota_data["qr_path"])
                        notas_data.append(nota_data)
                    except Exception as e_json:
                        _log.warning("No se pudo leer JSON de nota %s: %s", base_name, e_json)
                elif nota["txt_path"]:
                    try:
                        partes = nota["txt_path"].read_text(encoding="utf-8").split(" /// ")
                        notas_data.append({
                            "indice": base_name,
                            "rol": rol,
                            "tipo": rol,
                            "volanta": partes[0].strip() if len(partes) > 0 else "",
                            "titulo": partes[1].strip() if len(partes) > 1 else "",
                            "bajada": partes[2].strip() if len(partes) > 2 else "",
                            "firma": partes[3].strip() if len(partes) > 3 else "",
                            "epigrafe": partes[4].strip() if len(partes) > 4 else "",
                            "cuerpo": partes[5].strip() if len(partes) > 5 else "",
                            "imagenes": [],
                        })
                    except Exception as e_txt:
                        _log.warning("No se pudo leer TXT de nota %s: %s", base_name, e_txt)

            # --- #7: adjuntar el epígrafe de cada foto (maquetas multi-imagen, p.ej.
            #     Escrache al Bache). Se cruza por nombre de archivo con las imágenes
            #     detectadas en la nota principal. ---
            try:
                from pathlib import Path as _P
                # Matchear por STEM (sin extensión): el JSON guarda .jpeg pero las fotos
                # en disco/fotos_seleccionadas quedan .jpg tras la conversión.
                epi_por_stem: dict = {}
                for nd in notas_data:
                    if (nd.get("rol") or nd.get("tipo") or "").lower() == "principal":
                        for im in (nd.get("imagenes") or []):
                            arch = (im.get("archivo") or "").strip()
                            epi = (im.get("epigrafe") or "").strip()
                            if arch and epi and "NO HAY EP" not in epi.upper():
                                epi_por_stem[_P(arch).stem.lower()] = epi
                        break
                for f in fotos_data:
                    f["epigrafe"] = epi_por_stem.get(_P(f.get("nombre", "")).stem.lower(), "")
            except Exception as e:
                _log.debug("No se pudo adjuntar epígrafe por foto P%02d: %s", numero, e)

            # --- Maqueta: qxp en materiales si existe; si no, la resuelta por sección/aviso ---
            nombre_maqueta = ""
            maqueta_path_str = ""
            qxp_mat = self.file_service.find_qxp_en_materiales(numero)
            if qxp_mat:
                nombre_maqueta = qxp_mat.name
                maqueta_path_str = self._forzar_z_desde_unc(str(qxp_mat))
            else:
                try:
                    from services.maqueta_reader_service import resolve_maqueta, _get_maquetas_dir
                    nombre_maqueta = resolve_maqueta(
                        entry.get("aviso_full"), entry.get("aviso_half"),
                        entry.get("aviso_footer"), entry.get("aviso_robapagina"),
                        seccion, self.rutas,
                    ) or ""
                    if nombre_maqueta:
                        mq_path = _get_maquetas_dir(self.rutas) / nombre_maqueta
                        maqueta_path_str = self._forzar_z_desde_unc(str(mq_path))
                except Exception as e:
                    _log.warning("No se pudo resolver maqueta P%02d: %s", numero, e)

            # --- Fecha de edición (formato Quark, calculada en Python para no adelantar
            #     un día cuando el armado se hace pasada la medianoche). ---
            fecha_texto = ""
            try:
                fe = getattr(self.rutas, "fecha_edicion", None)
                if fe:
                    _dias = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES",
                             "SÁBADO", "DOMINGO"]
                    _meses = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                              "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE",
                              "DICIEMBRE"]
                    fecha_texto = (f"{_dias[fe.weekday()]} {fe.day} DE "
                                   f"{_meses[fe.month - 1]} DE {fe.year}")
            except Exception as e:
                _log.debug("No se pudo derivar fecha de edición P%02d: %s", numero, e)

            data = {
                "numero_pagina":      numero,
                "seccion":            seccion,
                "fecha":              fecha_texto,
                "usuario":            getpass.getuser(),
                "tiene_texto":        bool(tiene_texto),
                "maqueta":            nombre_maqueta,
                "maqueta_path":       maqueta_path_str,
                "avisos":             avisos,
                "fotos":              fotos_data,
                "notas":              notas_data,
                "composicion":        self.composicion_pagina(numero, subfolder),
                "foto_box_principal": config_global.maqueta_config.get("foto_box_principal", "Box369"),
                # P6a (spike): posiciones destino (coords de pantalla calibradas) para que el JS
                # intente mover cajas. Test inicial: Box427 (textual solo) → 'textual_dst_1'.
                "box_positions":      self._box_positions_para_js(),
            }

            ruta_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            _log.info("data_pagina.json escrito → P%02d, sección: '%s', fotos: %d, notas: %d",
                      numero, seccion, len(fotos_data), len(notas_data))
            _log.info("data_pagina P%02d: notas=%s",
                      numero, [(n.get("rol"), n.get("indice")) for n in notas_data])

            # Copia canónica en materiales/Pnn/ + runtime_config para PegarNota.js (migración JSON 2026-05-06)
            if mat:
                try:
                    mat_pnn = mat / f"P{numero:02d}"
                    mat_pnn.mkdir(parents=True, exist_ok=True)
                    (mat_pnn / "data_pagina.json").write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    _log.info("data_pagina.json escrito en materiales/P%02d/", numero)
                    # runtime_config.json: path exacto al data_pagina.json de la página activa
                    # Solo se actualiza al hacer "Pegar en Quark" → PegarNota.js lo lee directamente
                    import os as _os
                    prod_scripts = Path(_os.getenv("APPDATA", "")) / "ArmadorHuarpe" / "scripts"
                    prod_scripts.mkdir(parents=True, exist_ok=True)
                    data_pagina_fwd = str(mat_pnn / "data_pagina.json").replace("\\", "/")
                    (prod_scripts / "runtime_config.json").write_text(
                        json.dumps({"data_pagina_path": data_pagina_fwd}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    _log.info("runtime_config.json → %s", data_pagina_fwd)
                except Exception as e_mat:
                    _log.warning("No se pudo escribir data_pagina.json en materiales: %s", e_mat)

        except Exception as e:
            _log.error("No se pudo escribir data_pagina.json: %s", e)

    def pegar_en_quark(self, numero: int, indice: int = 0,
                       texto: Optional[str] = None,
                       subfolder: Optional[str] = None,
                       excluir_fotos: bool = False):
        """
        Prepara los archivos necesarios para el pegado en Quark:
        - Genera data_pagina.json con número, sección, avisos y fotos.
        - Copia el TXT real de la noticia activa a scripts/nota.txt.
        - No ejecuta Quark ni scripts. La UI luego minimiza la app.

        Parámetros:
            subfolder    — subfolder activo (p.ej. '06a') para fotos multi-story.
            excluir_fotos — si True, escribe fotos:[] (pegar solo texto/aviso).
        """
        try:
            _log.info("Iniciando pegado → P%02d (índice %d, subfolder=%s, excluir_fotos=%s)",
                      numero, indice, subfolder, excluir_fotos)

            scripts_dir = Config.RUNTIME_SCRIPTS_DIR
            scripts_dir.mkdir(parents=True, exist_ok=True)
            ruta_txt  = scripts_dir / "nota.txt"
            ruta_json = scripts_dir / "data_pagina.json"

            texto_norm  = (texto or "").strip()
            tiene_texto = bool(texto_norm)

            self._preparar_data_pagina(numero, tiene_texto=tiene_texto,
                                       subfolder=subfolder,
                                       excluir_fotos=excluir_fotos)

            if not tiene_texto:
                _log.info("P%02d — sin texto, pegando solo avisos/fotos.", numero)
                return

            archivo_txt = self.file_service.obtener_txt(numero, indice)
            if not archivo_txt or not archivo_txt.exists():
                _log.error("No se encontró el TXT para P%02d (índice %d)", numero, indice)
                return

            contenido = archivo_txt.read_text(encoding="utf-8", errors="ignore").strip()
            ruta_txt.write_text(contenido, encoding="utf-8", newline="\n")

            _log.info("Pegado preparado — P%02d | noticia: %s | JSON: %s | TXT: %s",
                      numero, archivo_txt.name, ruta_json, ruta_txt)

        except Exception as e:
            _log.error("pegar_en_quark falló para P%02d: %s", numero, e)

    
    def abrir_imagen_principal(self, numero: int) -> Optional[Path]:
        return self.file_service.find_material_image_for_page(numero)

    def asignar_maqueta(self, numero: int, nombre_maqueta: str) -> Optional[Path]:
        """
        Copia la maqueta seleccionada a materiales/Pnn/ y guarda el nombre en el INI.
        (migración JSON 2026-05-06)
        """
        return self.file_service.copiar_maqueta_a_materiales(numero, nombre_maqueta)

    # ---------- Lectura/fragmentos ----------
    def _leer_y_normalizar(self, numero: int, indice: int = 0) -> Optional[str]:
        """
        Lee el archivo TXT correspondiente a la página `numero` y subnoticia `indice`,
        normaliza su contenido y devuelve el texto listo para fragmentar.
        Si no existe el TXT (página vacía), devuelve None sin lanzar error.
        """
        txt_path = self.file_service.obtener_txt(numero, indice)

        # 🔹 Si todavía no hay carpeta o txt, devolvemos None sin error
        if not txt_path or not txt_path.exists():
            _log.debug("No hay TXT para P%02d (índice %d) todavía.", numero, indice)
            return None

        try:
            texto = txt_path.read_text(encoding="utf-8")
        except Exception as e:
            # Si ya tenés FileServiceError importado, podés usarlo;
            # si no, con Exception alcanza para no romper el flujo.
            _log.warning("Error al leer el archivo TXT de P%02d: %s", numero, e)
            return None

        # 🔹 Normalización ligera (idéntica a tu versión)
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        texto = re.sub(r"[ \t]+\n", "\n", texto)
        texto = re.sub(r"\n[ \t]+", "\n", texto)
        texto = texto.strip()
        texto = re.sub(r"<[^>]*>", "", texto)
        return texto or None

    def obtener_fragmentos(self, numero: int, indice: int = 0) -> list[str]:
        """
        Devuelve la lista de fragmentos (separados por '///') para la página y subnoticia indicada.
        """
        base = self._leer_y_normalizar(numero, indice)
        if not base:
            return []
        partes = [p.strip() for p in base.split("///")]
        return [p for p in partes if p]


    # ---------- Perfil / selección / asignaciones ----------
    def seleccionar_pagina(self, numero: int):
        self.gestor_paginas.set_pagina_activa(numero)
        pagina = self.gestor_paginas.obtener_pagina(numero)

        # TXT local
        p = self.file_service.obtener_txt(numero)
        pagina.asignado = bool(p and p.exists() and p.stat().st_size > 0)

        # INI: avisos + asignación propia/ajena
        entry = self.file_service.read_page_entry(numero)
        pagina.aviso_full = bool(entry.get("aviso_full", False))
        pagina.aviso_half = bool(entry.get("aviso_half", False))
        pagina.aviso_footer = bool(entry.get("aviso_footer", False))
        pagina.aviso_robapagina = bool(entry.get("aviso_robapagina", False))
        pagina.seccion = str(entry.get("seccion") or "").strip()
        pagina.aviso_nombre = (entry.get("aviso_nombre") or "").strip()
        # Esta parte está rara
        assigned_ini = bool(entry.get("assigned", False))
        by_ini = (entry.get("by") or "").strip()
        me = (self.usuario or "").strip().lower()

        pagina.asignada_por_ini = assigned_ini
        pagina.asignada_por_ini_user = by_ini
        pagina.asignada_por_otro = bool(assigned_ini and by_ini and by_ini.strip().lower() != me)
        # Fin de parte rara

        # Edición por otro usuario (guard de asignar/mover/eliminar)
        editando = bool(entry.get("editando", False))
        editando_por = (entry.get("editando_por") or "").strip()
        pagina.editando = editando
        pagina.editando_por = editando_por
        pagina.editando_por_otro = bool(editando and editando_por and editando_por.lower() != me)
        return pagina

    ### ESTA FUNCION NO PARECE SER USADA ###
    def asignar_texto_a_pagina(self, numero: int, origen: Path):
        try:
            self.file_service.asignar_txt(numero, origen)
            self.gestor_paginas.asignar(numero)
            # INI: marcar asignada con txt_name
            usuario = self.usuario or "desconocido"
            txt_name = f"{numero:02}.txt"
            self.file_service.mark_assigned(numero, txt_name, by=usuario)


        except Exception as e:
            _log.error("No se pudo asignar texto a la página %d: %s", numero, e)
            raise

    def quitar_asignacion(self, numero: int, borrar_qxp: bool = False):
        """
        Desasigna la página y delega en FileService el borrado del QXP personal.
        """
        self.file_service.clear_assignment(
            numero,
            by=self.usuario,
            borrar_qxp=borrar_qxp
        )

    def quitar_link_pagina(self, numero: int):
        
        """
        Limpia el campo link del INI para la página.
        """
        self.file_service.clear_link(numero)
        

    def mover_pagina(self, numero: int):
        # (optimista en memoria; el movimiento real lo hace file_service.ejecutar_mover +
        # verificar_qxp_pdf que relee disco). Sin perfiles.
        pagina = self.gestor_paginas.obtener_pagina(numero)
        if pagina.asignado and not pagina.armado:
            pagina.armado = True
        elif pagina.armado and not pagina.fotocromia:
            pagina.fotocromia = True

    def devolver_pagina(self, numero: int):
        pagina = self.gestor_paginas.obtener_pagina(numero)
        if pagina.fotocromia:
            pagina.fotocromia = False
        elif pagina.armado:
            pagina.armado = False
        elif pagina.asignado:
            pagina.asignado = False

    # ---------- Procesar MONO ----------
    
   

    
    
    def procesar_grilla_mono(self, texto: str):
        """
        Procesa la grilla MONO, detecta avisos, secciones, títulos y links múltiples.
        Si el link está presente y la página no tiene TXT asignado, encola scraping.
        """
        try:
            self._sincronizar_rutas_en_file_service()
        except Exception:
            pass

        errores = []
        re_head = re.compile(r"^P?\s*(\d{1,2})[.\-:]?\s*(.*)$", re.IGNORECASE)
        re_aviso_any = re.compile(
            r"\s*\(?\s*(COMPLETA|MEDIA|PIE|ROBAPAGINA|ROBA\s*P[ÁA]GINA|VAC[IÍ]A)\s*\)?\s*",
            re.IGNORECASE
        )
        re_link = re.compile(r"(https?://\S+)", re.IGNORECASE)

        raw_lines = [ln.rstrip() for ln in (texto or "").splitlines()]

        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line or line.upper().startswith("MONO"):
                continue

            m = re_head.match(line)
            if not m:
                errores.append(raw_line)
                continue

            try:
                numero = int(m.group(1))
                tail = (m.group(2) or "").strip()
                by = (self.usuario or "").strip() if hasattr(self, "usuario") else ""
            except Exception:
                errores.append(raw_line)
                continue

            if not (1 <= numero <= 16):
                errores.append(raw_line)
                continue

            # ================================================================
            #   LIMPIAR NOTAS ANTERIORES (siempre antes de procesar nuevas)    SE DEPRECA PARA TESTEAR 19/11
            # ================================================================
            #try:
            #    self.file_service.limpiar_notas(numero, by=by)
            #except Exception as e:
            #    print(f"[WARN] No se pudieron limpiar notas previas de P{numero:02d}: {e}")

            # ---------------- AVISO ----------------
            aviso = None
            av = re_aviso_any.search(tail)
            if av:
                aviso = av.group(1).upper()
                tail = re_aviso_any.sub(" ", tail)

            # ---------------- Flags de tapa ----------------
            if re.search(r"\*+\s*TITULO\s*\*+", tail, re.IGNORECASE):
                self.file_service.mark_tapa_titulo(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag: pag.tapa_titulo = True
                tail = re.sub(r"\*+\s*TITULO\s*\*+", " ", tail, flags=re.IGNORECASE)

            if re.search(r"\*+\s*FOTO\s*\*+", tail, re.IGNORECASE):
                self.file_service.mark_tapa_foto(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag: pag.tapa_foto = True
                tail = re.sub(r"\*+\s*FOTO\s*\*+", " ", tail, flags=re.IGNORECASE)

            # limpiar asteriscos normales
            tail = re.sub(r"\(\s*\)", " ", tail)
            tail = re.sub(r"\*[^*\n]+\*", " ", tail)

            # flags "TITULO"/"FOTO" sin asteriscos
            if re.search(r"\bFOTO\b", tail, re.IGNORECASE):
                self.file_service.mark_tapa_foto(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag: pag.tapa_foto = True
                tail = re.sub(r"\bFOTO\b", " ", tail, flags=re.IGNORECASE)

            if re.search(r"\bTITULO\b", tail, re.IGNORECASE):
                self.file_service.mark_tapa_titulo(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag: pag.tapa_titulo = True
                tail = re.sub(r"\bTITULO\b", " ", tail, flags=re.IGNORECASE)

            # ---------------- SECCIÓN ----------------
            # Sección real previa (si ya estaba en INI)
            entry = self.file_service.read_page_entry(numero)
            seccion_real = entry.get("seccion", "").strip()

            seccion = None

            # ============================================================
            # 1) INTENTAR DETECCIÓN CON GUION (parser original)
            #    Formato esperado:
            #    SECCION - Título
            # ============================================================
            seccion_guion = None
            if tail and " - " in tail:
                partes = re.split(r"\s+-\s+", tail, maxsplit=1)
                posible = (partes[0] or "").strip(" .-–—()")
                if posible:
                    seccion_guion = posible.title()

            # ============================================================
            # 2) INTENTAR DETECCIÓN SIN GUION (nuevo parser)
            #    Formato real del MONO:
            #    (AVISO) SECCION Título Link + ...
            #    Tomamos el primer token textual después del aviso.
            # ============================================================
            seccion_singuion = None
            if tail:
                tokens = tail.split()
                if tokens:
                    posible = tokens[0].strip(" .,:;()[]{}\"'")
                    # Descartar falsos positivos
                    if (
                        posible
                        and not posible.upper() in ("COMPLETA","MEDIA","PIE","ROBAPAGINA","ROBA","VACIA","VACÍA")
                        and not re.match(r"https?://", posible, re.IGNORECASE)
                    ):
                        seccion_singuion = posible.title()

            # ============================================================
            # 3) PRIORIDAD DE DETECCIÓN:
            #    1) por guion
            #    2) sin guion
            #    3) sección previa del INI
            # ============================================================
            if seccion_guion:
                seccion = seccion_guion
            elif seccion_singuion:
                seccion = seccion_singuion
            else:
                seccion = seccion_real  # conservar lo que tenía antes



            # ================================================================
            #   TÍTULOS → van a mono_extra (separados con ";")
            #   Formato esperado:
            #   SECCION - titulo1 link1 + titulo2 link2 + titulo3 link3
            # ================================================================
            mono_extra_val = ""

            # Separar SECCIÓN del resto
            partes_tit = re.split(r"\s+-\s+", tail, maxsplit=1)
            if len(partes_tit) == 2:
                resto_titulos = partes_tit[1].strip()
            else:
                resto_titulos = ""

            if resto_titulos:
                # quitar los links
                resto_sin_links = re.sub(r"https?://\S+", " ", resto_titulos)

                # dividir por " + "
                lista_tit = [t.strip() for t in resto_sin_links.split("+") if t.strip()]

                # unificar para guardar en INI
                mono_extra_val = "; ".join(lista_tit).strip()

            # persistir mono_extra (SIEMPRE se guarda, incluso vacío)
            self.file_service.write_page_entry(
                numero,
                mono_extra=mono_extra_val,
                by=by
            )

            # actualizar objeto en memoria
            pag = self.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.mono_extra = mono_extra_val

            # ---------------- Guardar sección ----------------
            if seccion:
                self.file_service.set_seccion(numero, seccion, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag: pag.seccion = seccion
            else:
                # borrar sección si corresponde
                if aviso and ("VAC" in aviso):
                    self.file_service.clear_seccion(numero, by=by)
                    pag = self.gestor_paginas.obtener_pagina(numero)
                    if pag: pag.seccion = ""

            # ---------------- Avisos ----------------
            if aviso == "COMPLETA":
                self.file_service.mark_aviso_full(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag:
                    pag.aviso_full, pag.aviso_half, pag.aviso_footer = True, False, False
                    pag.asignado = False

            elif aviso and aviso.startswith("ROBA"):
                self.file_service.mark_aviso_robapagina(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag:
                    pag.aviso_full = pag.aviso_half = pag.aviso_footer = False
                    pag.aviso_robapagina = True

            elif aviso == "MEDIA":
                self.file_service.mark_aviso_half(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag:
                    pag.aviso_full, pag.aviso_half, pag.aviso_footer = False, True, False

            elif aviso == "PIE":
                self.file_service.mark_aviso_footer(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag:
                    pag.aviso_full, pag.aviso_half, pag.aviso_footer = False, False, True

            elif aviso and ("VAC" in aviso):
                self.file_service.clear_avisos(numero, by=by)
                pag = self.gestor_paginas.obtener_pagina(numero)
                if pag:
                    pag.aviso_full = pag.aviso_half = pag.aviso_footer = pag.aviso_robapagina = False

            # ================================================================
            #  LINKS MÚLTIPLES: noticia principal + adicionales (a,b,c…)
            # ================================================================
            links = re.findall(r"(https?://\S+)", tail, re.IGNORECASE)
            if links:

                # limpiar links para no contaminar sección/título
                for l in links:
                    tail = tail.replace(l, " ")
                tail = tail.strip()

                for idx, link in enumerate(links):

                    # ------- Primera noticia -------
                    if idx == 0:
                        self.file_service.write_page_entry(
                            numero,
                            seccion=seccion,
                            
                            link=link,
                        by=by
                        )

                    # ------- Notas adicionales -------
                    else:
                        self.file_service.append_txt_entry(
                            numero,
                            txt_name="",   # se asignará cuando scrapée
                            link=link
                            
                        )

                    # NOTA: "Procesar" del MONO solo persiste (sección, links, aviso, tapa,
                    # mono_extra). El scraping ya NO se encola desde acá.

        # ---------------- Fin de líneas ----------------
        self.refrescar_avisos_desde_ini()
        return errores


    # ---------- MONO (lectura/escritura desde diálogo) ----------

    def generar_mono(self) -> str:
        """
        Genera el MONO automáticamente a partir de los INI por página.

        Reglas clave:
        - Una sola SECCIÓN por línea de página (no se repite en cada noticia).
        - Links y títulos se alinean por índice (listas separadas por ';').
        - Si hay tapa_foto / tapa_titulo en la página, se agregan *FOTO* / *TITULO*.
        """
        mañana = datetime.date.today() + datetime.timedelta(days=1)

        dias = [
            "LUNES", "MARTES", "MIÉRCOLES",
            "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"
        ]

        meses = [
            "ENERO", "FEBRERO", "MARZO", "ABRIL",
            "MAYO", "JUNIO", "JULIO", "AGOSTO",
            "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"
        ]

        fecha_formateada = (
            f"{dias[mañana.weekday()]} "
            f"{mañana.day} DE "
            f"{meses[mañana.month - 1]} "
            f"{mañana.year}"
        )
        lineas = []
        lineas.append(f"MONO DE EDICIÓN {fecha_formateada}\n")

        for n in range(1, 17):
            entry = self.file_service.read_page_entry(n)

            # --- Aviso ---
            if entry.get("aviso_full"):
                aviso = "COMPLETA"
            elif entry.get("aviso_half"):
                aviso = "MEDIA"
            elif entry.get("aviso_footer"):
                aviso = "PIE"
            elif entry.get("aviso_robapagina"):
                aviso = "ROBAPAGINA"
            else:
                aviso = "VACÍA"

            # --- Sección ---
            seccion = (entry.get("seccion") or "").strip().upper()

            # ----------------------------------------------------------
            #   TÍTULO + LINK de cada nota, desde su nota.json en disco
            #   (fuente única de verdad; el INI ya no guarda link/txt_name).
            #   Fallback de título: campo [1] del TXT (volanta /// titulo /// …).
            # ----------------------------------------------------------
            partes_noticias = []
            for nota in self.file_service.get_notas(n):
                titulo = ""
                link_i = ""
                jp = nota.get("json_path")
                if jp:
                    try:
                        nd = json.loads(jp.read_text(encoding="utf-8"))
                        titulo = (nd.get("titulo") or "").strip()
                        link_i = (nd.get("link") or "").strip()
                    except Exception:
                        pass
                if not titulo and nota.get("txt_path"):
                    try:
                        campos = nota["txt_path"].read_text(encoding="utf-8", errors="ignore").split("///")
                        if len(campos) >= 2:
                            titulo = campos[1].strip()
                    except Exception:
                        pass

                if titulo and link_i:
                    bloque = f"{titulo} {link_i}"
                elif titulo:
                    bloque = titulo
                elif link_i:
                    bloque = link_i
                else:
                    bloque = ""

                if bloque:
                    partes_noticias.append(bloque.strip())

            # --- línea base: Pnn + aviso + sección (si hay) ---
            if seccion:
                base_line = f"P{n:02d}. ({aviso}) {seccion}"
            else:
                base_line = f"P{n:02d}. ({aviso})"

            if partes_noticias:
                linea = base_line + " - " + " + ".join(partes_noticias)
            else:
                linea = base_line

            # --- Marcas de tapa: *TITULO* / *FOTO* ---
            marcas = []
            if entry.get("tapa_titulo"):
                marcas.append("*TITULO*")
            if entry.get("tapa_foto"):
                marcas.append("*FOTO*")
            if marcas:
                linea += " " + " ".join(marcas)

            lineas.append(linea)

        return "\n".join(lineas)





    
    def leer_mono(self) -> str:
        """Devuelve el texto guardado del MONO (o vacío)."""
        try:
            return self.file_service.read_mono()
        except Exception as e:
            _log.warning("No se pudo leer el MONO: %s", e)
            return ""



    def descargar_nota_desde_link(self, numero: int, link: str):
        """
        Scrapea la nota real desde el Manager y guarda TXT + imágenes en materiales/PXX.
        No asigna la página ni toca 'assigned'.
        """
        self._sincronizar_rutas_en_file_service()
        #self.file_service.ensure_shared_ini() # DEPRECADO PORQUE YA NO SE USA INI CENTRAL

        # 🔹 Reutilizamos la misma lógica de procesar_grilla_aviso para persistir el link
        try:
            if link:
                _log.debug("Registrando link manual en INI para P%02d: %s", numero, link)
                self.file_service.write_page_entry(
                    numero,
                    link=link,
                    by=self.usuario  # usamos siempre el usuario seteado
                )
        except Exception as e:
            _log.warning("No pude registrar link en INI para P%02d: %s", numero, e)

        scraper = self._get_scraper()
        try:
            txt_path, imgs = scraper.scrape_to_materiales(numero, link, self.file_service)
            _log.debug("descargar_nota_desde_link usuario=%r, link=%r", self.usuario, link)
            # Registrar txt_name REAL + guardar len
            try:
                # nombre real del archivo descargado
                nombre_real = txt_path.name

                # longitud real del contenido
                try:
                    contenido = txt_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    contenido = txt_path.read_text(encoding="utf-8-sig")
                txt_len = len(contenido.strip())

                # guardar nombre + (len)
                self.file_service.set_txt_len(numero, nombre_real, txt_len)

                # apagar completa si corresponde
                entry = self.file_service.read_page_entry(numero)
                if entry.get("aviso_full", False):
                    self.file_service.write_page_entry(numero, aviso_full=False, by=self.usuario)

            except Exception as e:
                _log.warning("No pude registrar txt_name + len en INI para P%02d: %s", numero, e)


            # Estado en memoria: hay TXT disponible
            pag = self.gestor_paginas.obtener_pagina(numero)
            if pag:
                pag.asignado = True

            return txt_path, imgs
        except ScraperError as e:
            _log.error("Scraper error para P%02d: %s", numero, e)
            msg = str(e).upper()
            if "OCUPADA" in msg or "SCRAPE_RETRY" in msg:
                try:
                    mat_dir = self.file_service.get_material_dir(numero)
                    if mat_dir.exists() and not any(mat_dir.iterdir()):
                        mat_dir.rmdir()
                except Exception:
                    pass
                raise ScraperError(f"NOTA_NO_DISPONIBLE: {e}")
            else:
                try:
                    self.file_service.write_page_entry(numero, link="", by=self.usuario)
                except Exception:
                    pass
            raise
        except Exception as e:
            _log.error("Scraper error inesperado P%02d: %s", numero, e)
            raise


    # Carga de avisos
    def _norm_header(self, s: str) -> str:
        # min-normalización SOLO para detectar encabezados; no se usa en nombres
        if not s:
            return ""
        s = s.strip().lower()
        # quitar acentos básicos
        trans = str.maketrans("áéíóúäëïöüÁÉÍÓÚÄËÏÖÜñÑ", "aeiouaeiouaeiouaeiounn")
        return s.translate(trans)

    def importar_avisos_desde_excel(self, xlsx_path: Path):
        """
        Lee un Excel de grilla de avisos sin estructura fija.
        Busca cualquier celda con 'PAGINA X' (regex) y toma de esa fila el nombre del aviso.
        Devuelve:
            mapping = { pagina(int) : aviso_nombre(str TAL CUAL) }
            skipped = cantidad de filas ignoradas.
        """
        try:
            from openpyxl import load_workbook
        except Exception:
            raise RuntimeError("Falta dependencia: openpyxl")

        import re

        wb = load_workbook(str(xlsx_path), data_only=True, read_only=True)
        ws = wb.active

        mapping = {}
        skipped = 0
        re_pagina = re.compile(r"pagina\s*(\d+)", re.IGNORECASE)

        for row in ws.iter_rows(values_only=True):
            # Convertir todas las celdas a str
            celdas = [str(c).strip() if c is not None else "" for c in row]
            if not any(celdas):
                continue

            # --- Detectar número de página ---
            numero = None
            for celda in celdas:
                if "contratapa" in celda.lower():
                    numero = 16
                    break
                m = re_pagina.search(celda)
                if m:
                    try:
                        numero = int(m.group(1))
                        break
                    except Exception:
                        pass

            if not numero:
                skipped += 1
                continue
            
            # Aviso_nombre = primera celda "legible" distinta de PAGINA/tipo
            aviso_nombre = ""
            for celda in celdas:
                txt = celda.strip()
                if not txt:
                    continue
                if re_pagina.search(txt):
                    continue
                if txt.upper() in ("AVISO", "UBICACIÓN", "UBICACION", "TIPO", "PÁGINA", "PAGINA"):
                    continue
                # saltar tipos conocidos, porque esos vienen del MONO
                if any(t in txt.upper() for t in ("MEDIA", "PIE", "COMPLETA", "ROBA")):
                    continue
                aviso_nombre = txt
                break

            if aviso_nombre:
                mapping[numero] = aviso_nombre  # última ocurrencia gana
                _log.info("P%02d → aviso_nombre='%s'", numero, aviso_nombre)

                # Importar archivo real y persistir nombre con extensión en INI
                try:
                    self._sincronizar_rutas_en_file_service()

                    destino = self.file_service.importar_aviso_inicial(
                        numero,
                        aviso_nombre,
                        self.rutas.avisos_root,
                        self.rutas.avisos2_root
                    )

                    # Si se pudo resolver/copiar (o ya existía), persistir el nombre REAL (con extensión)
                    if destino:
                        aviso_real = destino.name  # <-- incluye extensión
                        self.file_service.write_page_entry(numero, aviso_nombre=aviso_real, by=self.usuario)
                        mapping[numero] = aviso_real  # <-- clave: evita que on_cargar_avisos_excel lo pise sin extensión
                        _log.info("P%02d → aviso_real='%s' (desde archivo encontrado)", numero, aviso_real)
                    else:
                        # Fallback: si no encontró archivo, al menos guarda lo del Excel (sin extensión)
                        self.file_service.write_page_entry(numero, aviso_nombre=aviso_nombre, by=self.usuario)
                        _log.warning("P%02d → no se encontró archivo; INI='%s' (sin extensión)", numero, aviso_nombre)
                except Exception as e:
                    _log.warning("No pude importar aviso inicial para P%02d: %s", numero, e)
            else:
                skipped += 1

        _log.info("Importación de avisos completa: %d válidos, %d filas ignoradas", len(mapping), skipped)
        return mapping, skipped
