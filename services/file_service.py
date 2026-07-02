# services/file_service.py
import shutil
from shutil import copy2
from pathlib import Path
import re
from typing import Optional
import unicodedata
import configparser
import json
import getpass
import datetime
import os
from config.config import Config
from typing import Dict, List
from model.rutas import RutasEstado
import difflib
from PyQt5.QtWidgets import QMessageBox
from utils.app_logger import get_logger

_log = get_logger(__name__)

# --- borrado definitivo (sin papelera) ---
def _eliminar_definitivo(path):
    """Borra definitivamente un archivo o carpeta (sin papelera).

    La confirmación ('advertencia previa') se hace en la capa UI antes de
    invocar el borrado; acá solo se ejecuta."""
    p = Path(path)
    if not p.exists():
        return
    if p.is_dir():
        shutil.rmtree(p)
    else:
        os.remove(p)


# --- info y conversión de imágenes (helpers de módulo) ---
def firma_imagen(path) -> str:
    """Firma corta de una imagen para logging: 'RGB/JPEG prog=0 adobeT=None'
    (mode/format/progresivo/adobe_transform). Import PIL perezoso; no rompe si falla."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return "%s/%s prog=%s adobeT=%s" % (
                im.mode, im.format or "?",
                im.info.get("progression", 0),
                im.info.get("adobe_transform"),
            )
    except Exception as exc:
        return f"<ilegible: {exc}>"


def espacio_color(path) -> str:
    """Espacio de color de una imagen raster: 'RGB' | 'CMYK' | 'GRIS' | '?'.
    '?' para no-raster (PDF/EPS) o ilegibles. Import PIL perezoso."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            mode = im.mode
        if mode == "CMYK":
            return "CMYK"
        if mode in ("L", "LA", "1", "I", "I;16"):
            return "GRIS"
        if mode in ("RGB", "RGBA", "P", "YCbCr"):
            return "RGB"
        return mode or "?"
    except Exception:
        return "?"


def convertir_a_jpg(path) -> Path:
    """Convierte CUALQUIER imagen (WebP, PNG, BMP, GIF, TIFF…) a JPG sin pérdida apreciable
    (quality=100, subsampling=0 / 4:4:4) y aplanando transparencia sobre blanco.
    Si el archivo YA es JPEG no lo re-codifica (cero pérdida): solo normaliza la extensión a
    .jpg si hace falta. Devuelve el path final (.jpg), o el original si algo falla."""
    path = Path(path)
    try:
        from PIL import Image
        out = None
        with Image.open(path) as img:
            fmt = (img.format or "").upper()
            if fmt != "JPEG":
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    rgba = img.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[3])
                    out = bg
                else:
                    out = img.convert("RGB")
        dest = path.with_suffix(".jpg")
        if out is not None:
            out.save(dest, "JPEG", quality=100, subsampling=0)
            if dest != path and path.exists():
                path.unlink()
            _log.info("Imagen %s → JPG sin pérdida: %s → %s", fmt or "?", path.name, dest.name)
            return dest
        # Ya era JPEG: no re-encodear. Normalizar extensión a .jpg si hace falta.
        if path.suffix.lower() == ".jpg":
            return path
        if dest != path and dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        shutil.move(str(path), str(dest))
        _log.info("JPEG normalizado a .jpg: %s → %s", path.name, dest.name)
        return dest
    except Exception as exc:
        _log.warning("No se pudo convertir a JPG %s: %s", path.name, exc)
        return path





class FileServiceError(Exception):
    """Excepción con mensaje apto para usuario final, preservando el error original."""
    def __init__(self, user_message: str, original: Exception = None):
        super().__init__(user_message)
        self.original = original

def _sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    if not name:
        return "sin_nombre"
    stem, dot, ext = name.partition(".")
    reserved = {"CON","PRN","AUX","NUL"} | {*(f"COM{i}" for i in range(1,10))} | {*(f"LPT{i}" for i in range(1,10))}
    if stem.upper() in reserved:
        stem = f"{stem}_"
    return stem + (dot + ext if dot else "")

# =========================
# helpers para txt_name con (len)
# =========================

# --- helper interno ---

_LEN_RE = re.compile(r"\s*\(\s*(\d+)\s*\)\s*$")

def _strip_len_suffix(name: str) -> str:
    """Quita un sufijo ' (1234)' si existe."""
    return _LEN_RE.sub("", name or "").strip()

def _append_len_suffix(name: str, n: int | None) -> str:
    """Agrega ' (n)' si n es válido; si ya tenía len, lo reemplaza."""
    if not isinstance(n, int) or n <= 0:
        return _strip_len_suffix(name)
    base = _strip_len_suffix(name)
    return f"{base} ({n})"


def _ensure_dir(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FileServiceError(
            f"No se pudo crear la carpeta destino:\n{path}\n"
            "Verificá permisos o conexión a la red.", e
        )

def _write_text(path: Path, content: str, encoding: str = "utf-8"):
    _ensure_dir(path.parent)
    try:
        # Forzamos UTF-8 y newline '\n' para evitar problemas de CRLF y tildes
        with open(path, "w", encoding=encoding, newline="\n") as f:
            f.write(content)
    except OSError as e:
        raise FileServiceError(
            f"No se pudo escribir el archivo:\n{path}\n"
            "Cerrá archivos abiertos, verificá permisos/espacio y reintentá.", e
        )

def _read_text(path: Path, encoding: str = "utf-8") -> str:
    if not path.exists():
        raise FileServiceError(f"El archivo no existe:\n{path}")
    try:
        with open(path, "r", encoding=encoding) as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise FileServiceError(
            f"El archivo no está codificado en UTF-8:\n{path}\n"
            "Convertí el archivo a UTF-8 (sin BOM) e intentá de nuevo.", e
        )
    except OSError as e:
        raise FileServiceError(
            f"No se pudo leer el archivo:\n{path}\n"
            "Verificá permisos, antivirus y conexión a la red.", e
        )

def _copy_file(src: Path, dst: Path, overwrite: bool = False) -> Path:
    if not src.exists():
        raise FileServiceError(f"El archivo de origen no existe:\n{src}")
    _ensure_dir(dst.parent)
    try:
        if dst.exists():
            if overwrite:
                if dst.is_dir():
                    raise FileServiceError(f"El destino es una carpeta, no un archivo:\n{dst}")
                os.remove(dst)
            else:
                raise FileServiceError(f"El archivo destino ya existe:\n{dst}")
        shutil.copy2(src, dst)
        return dst
    except OSError as e:
        raise FileServiceError(
            f"No se pudo copiar:\n{src}\n→ {dst}\n"
            "Comprobá permisos, disco libre y antivirus.", e
        )

def _move_file(src: Path, dest: Path, overwrite=False):
    """
    Mueve el archivo de verdad (no copia previa).
    Si el archivo está abierto → PermissionError 32 debe propagarse.
    No debe copiar nada si no puede mover.
    """
    src = Path(src)
    dest = Path(dest)

    # Crear carpeta destino
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Si existe y overwrite=False, error
    if dest.exists() and not overwrite:
        raise FileExistsError(f"Destino ya existe: {dest}")

    try:
        # MOVER REAL (rename)
        src.replace(dest)

    except PermissionError as e:
        # Archivo abierto → PROPAGAR sin copiar
        if hasattr(e, "winerror") and e.winerror == 32:
            raise  # esto permite que controller detecte "locked"
        raise

    except OSError as e:
        # Si no se puede usar replace (p.ej mover entre discos), intentamos move tradicional
        import shutil
        try:
            shutil.move(str(src), str(dest))
        except PermissionError as e2:
            if hasattr(e2, "winerror") and e2.winerror == 32:
                raise
            raise
        except Exception:
            raise





# --- Imágenes permitidas (sin WEBP) ---
IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".psd", ".eps", ".pdf", ".bmp", ".gif"}
# ----





DEFAULT_PAGE_FIELDS = {
    "assigned": "false",
    "txt_name": "",
    "aviso_full": "false",
    "aviso_half": "false",
    "aviso_footer": "false",
    "aviso_robapagina": "false",
    "aviso_nombre": "",
    "tapa_foto": "false",
    "tapa_titulo": "false",
    "listo_para_armar": "false",
    "editando": "false",
    "editando_por": "",
    "mono_extra": "",
    "by": "",
    "ts": "",
    "link": "",
    "seccion": "",
    "estado": "",
    "maqueta": "",
    # Historial de trabajo (#1): se appendea una entrada por cada acción, ';'-separado.
    "historial_by": "",
    "historial_ts": "",
    "historial_accion": "",
}



# services/file_service.py
# ...

class FileService:
    def __init__(self, paths: Dict[str, Path]):
        self.material: Path = Path(paths.get("material", Config.MATERIAL_DIR))
        self.rutas: Dict[str, str] = {"material": str(self.material)}
        self._cache_avisos: dict[tuple[int,str], Path] = {}  # (pagina_num, aviso_nombre) -> Path
        try:
            self.material.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise FileServiceError(
                "No se pudo preparar la carpeta de 'material':\n"
                f"{self.material}\nVerificá permisos o conexión a red.", e
            )
        
        # --- Caché para snapshots ---
        self._cache_qxp = {"mtimes": {}, "result": None}
        self._cache_pdf = {"mtimes": {}, "result": None}
    


    def _maybe_invalidate_aviso_cache(self, avisos_dir: Optional[Path]):
        """
        Invalida la caché de avisos si cambió el mtime de avisos_dir o de la raíz de Base.
        """
        base = Path(self.rutas.get("quark_output_dir") or "")
        mtimes = self._folder_mtimes(Path(avisos_dir) if avisos_dir else None, base)
        if mtimes != getattr(self, "_cache_avisos_mtimes", {}):
            self._cache_avisos.clear()
            self._cache_avisos_mtimes = mtimes    



    #########-----helpers de avisos---------#########
    def _buscar_candidato_aviso(
        self,
        carpeta: Path,
        nombre_excel: str,
        tipo_aviso: Optional[str] = None
    ) -> Optional[Path]:
        """
        Busca un archivo de aviso dentro de 'carpeta' cuyo nombre contenga
        literalmente todas las palabras del aviso del Excel (nombre_excel),
        y opcionalmente también el tipo (pagina, media, pie, robapagina).

        No usa heurística ni similitud: solo coincidencia literal.
        Prioridad:
            1) contiene <nombre_excel + tipo>
            2) contiene <nombre_excel>
        Si hay varios en el mismo nivel, devuelve None (ambigüedad).
        """
        if not carpeta or not carpeta.exists():
            return None

        # --- Normalización mínima ---
        def norm(s: str) -> str:
            s = s.casefold()
            s = unicodedata.normalize("NFD", s)
            s = "".join(ch for ch in s if not unicodedata.combining(ch))
            s = s.replace("_", " ").replace("-", " ")
            s = re.sub(r"\s+", " ", s.strip())
            return s

        nombre_norm = norm(nombre_excel)
        tipo_norm = norm(tipo_aviso or "")
        if not nombre_norm:
            _log.debug("buscar_aviso: cadena vacía (sin nombre_excel) en %s", carpeta)
            return None

        # Alias de tipo (COMPLETA → PAGINA)
        alias_tipo = {
            "completa": "pagina",
            "pagina": "pagina",
            "media": "media pagina",
            "media pagina": "media pagina",
            "pie": "pie",
            "robapagina": "robapagina",
        }
        tipo_equivalente = alias_tipo.get(tipo_norm, tipo_norm)

        cadena_tipo = f"{nombre_norm} {tipo_equivalente}".strip() if tipo_equivalente else ""
        lista_archivos = sorted(
            [f for f in carpeta.iterdir() if f.is_file() and f.suffix.lower() in IMG_EXTS],
            key=lambda p: p.name.casefold()
        )

        match_tipo = []
        match_base = []

        for f in lista_archivos:
            stem_norm = norm(f.stem)
            if cadena_tipo and cadena_tipo in stem_norm:
                match_tipo.append(f)
            elif nombre_norm in stem_norm:
                match_base.append(f)

        # --- Logs y resolución jerárquica ---
        if len(match_tipo) == 1:
            _log.debug("Aviso match '%s' + tipo (%s) → %s", nombre_excel, tipo_equivalente or "sin tipo", match_tipo[0].name)
            return match_tipo[0]
        elif len(match_tipo) > 1:
            _log.warning("Aviso ambiguo '%s' + tipo (%s) → %d coincidencias en %s: %s",
                         nombre_excel, tipo_equivalente, len(match_tipo), carpeta,
                         ", ".join(f.name for f in match_tipo))
            return None
        elif len(match_base) == 1:
            _log.debug("Aviso match '%s' → %s", nombre_excel, match_base[0].name)
            return match_base[0]
        elif len(match_base) > 1:
            con_tipo = [f for f in match_base if tipo_equivalente and tipo_equivalente in norm(f.stem)]
            if len(con_tipo) == 1:
                _log.debug("Aviso match '%s' (resuelto por tipo %s) → %s", nombre_excel, tipo_equivalente, con_tipo[0].name)
                return con_tipo[0]
            _log.warning("Aviso ambiguo '%s' → %d coincidencias en %s: %s",
                         nombre_excel, len(match_base), carpeta, ", ".join(f.name for f in match_base))
            return None

        _log.debug("Aviso no encontrado: '%s' (%s) en %s", nombre_excel, tipo_equivalente or "sin tipo", carpeta)
        return None

    def importar_aviso_inicial(
        self,
        numero: int,
        nombre_aviso_grilla: str,
        carpeta_a: Optional[Path],
        carpeta_b: Optional[Path],
    ) -> Optional[Path]:
        """
        Importa un aviso desde la carpeta de avisos principal (self.rutas.avisos_root)
        hacia materiales/Pxx/. Si el archivo ya existe, no lo copia de nuevo.
        Mantiene compatibilidad de firma (carpeta_b se ignora).
        """
        if not nombre_aviso_grilla:
            return None

        carpeta = Path(self.rutas.get("avisos_dir") or "")
        if not carpeta or not carpeta.exists():
            _log.warning("Carpeta de avisos no disponible: %s", carpeta)
            return None

        # Determinar tipo desde el INI
        tipo = ""
        try:
            entry = self.read_page_entry(numero)
            if entry.get("aviso_full"):
                tipo = "pagina"
            elif entry.get("aviso_half"):
                tipo = "media"
            elif entry.get("aviso_footer"):
                tipo = "pie"
            elif entry.get("aviso_robapagina"):
                tipo = "robapagina"
        except Exception:
            tipo = ""

        # Buscar mejor coincidencia
        match = self._buscar_candidato_aviso(carpeta, nombre_aviso_grilla, tipo)
        if not match:
            _log.info("Aviso no encontrado: P%02d '%s' tipo=%s", numero, nombre_aviso_grilla, tipo)
            return None

        dest_dir = self.material / f"P{numero:02d}"
        _ensure_dir(dest_dir)
        destino = dest_dir / match.name
        try:
            if destino.exists():
                _log.info("Aviso ya existente: %s, se omite copia.", destino.name)
                return destino
            shutil.copy2(match, destino)
            _log.info("Aviso copiado: %s → %s", match.name, destino)
            return destino
        except Exception as e:
            _log.error("No se pudo copiar aviso %s → %s: %s", match, destino, e)
            return None


    
    



    def find_aviso_file_from_base(
        self,
        numero: int,
        aviso_nombre: str,
        tipo_aviso: Optional[str] = ""
    ) -> Optional[Path]:
        """
        Busca un aviso directamente en la carpeta Base (quark_output_dir)
        y lo mueve a materiales/Pxx/.
        """
        if not aviso_nombre:
            return None

        base = Path(self.rutas.get("quark_output_dir") or "")
        if not base.exists():
            return None

        match = self._buscar_candidato_aviso(base, aviso_nombre, tipo_aviso)
        if not match:
            return None

        dest_dir = self.material / f"P{numero:02d}"
        _ensure_dir(dest_dir)
        dest = self._unique_dest(dest_dir / match.name)
        try:
            shutil.move(str(match), str(dest))
            _log.info("Aviso movido: %s → %s", match.name, dest)
            return dest
        except Exception as e:
            _log.error("No se pudo mover aviso %s → %s: %s", match, dest, e)
            return None
        

    def resolver_aviso_local(
        self,
        numero: int,
        aviso_nombre: str,
        tipo_aviso: Optional[str] = ""
    ) -> Optional[Path]:
        """
        Busca dentro de materiales/Pxx/ una imagen de aviso que coincida
        con el nombre y tipo (si se pasa).
        """
        carpeta = self.material / f"P{numero:02d}"
        if not carpeta.exists():
            return None
        # 1) Si en el INI viene con extensión, probamos match exacto (evita falsos positivos)
        try:
            cand = carpeta / aviso_nombre
            if cand.exists():
                return cand
        except Exception:
            pass

        # 2) Fallback: matching flexible por stem / tipo
        base_name = Path(aviso_nombre).stem if aviso_nombre else aviso_nombre
        return self._buscar_candidato_aviso(carpeta, base_name, tipo_aviso)
    
    
    #--------- PARA MINIATURAS EN LA GRILLA DE PÁGINAS ----------
    def find_aviso_image_for_page(self, numero: int) -> Optional[Path]:
        """
        Devuelve la ruta del archivo de imagen para el aviso de la página dada.
        - Si no hay aviso o aún no existen archivos → None (maqueta naranja).
        - Si el aviso es PDF o EPS → genera miniatura PNG temporal en cache.
        - Si el aviso es JPG/PNG/TIF → devuelve la ruta directamente.
        """

        try:
            entry = self.read_page_entry(numero)
        except Exception:
            return None  # aún no hay INI o la página no existe

        # Nombre del aviso registrado en el ini (puede venir vacío)
        nombre = (entry.get("aviso_nombre") or "").strip()
        if not nombre:
            return None

        # Determinar tipo de aviso según flags del ini
        tipo = None
        if entry.get("aviso_full"):
            tipo = "COMPLETA"
        elif entry.get("aviso_half"):
            tipo = "MEDIA"
        elif entry.get("aviso_footer"):
            tipo = "PIE"
        elif entry.get("aviso_robapagina"):
            tipo = "ROBAPAGINA"

        # Buscar carpeta base de avisos
        avisos_dir = self.rutas.get("avisos_dir") if hasattr(self, "rutas") else None
        avisos2_dir = self.rutas.get("avisos2_dir") if hasattr(self, "rutas") else None

        if not avisos_dir and not avisos2_dir:
            return None  # base recién creada, sin carpetas

        # Intentar resolver el archivo real
        try:
            aviso_path = self.resolver_aviso_local(numero, nombre, tipo_aviso=tipo)
        except FileNotFoundError:
            return None
        except Exception as e:
            _log.warning("resolver_aviso_local falló para P%02d: %s", numero, e)
            return None

        if not aviso_path or not aviso_path.exists():
            return None

        # Si ya es una imagen, la devolvemos directamente
        ext = aviso_path.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
            return aviso_path

        # Si es PDF o EPS → rasterizar a PNG cacheado (sin poppler).
        if ext in (".pdf", ".eps"):
            try:
                cache_dir = Path.home() / "AppData" / "Local" / "ArmadorHuarpe" / "cache_avisos"
                cache_dir.mkdir(parents=True, exist_ok=True)
                out_path = cache_dir / f"aviso_P{numero:02d}.png"
                # Cache por mtime: no rasterizar en cada poll si el aviso no cambió.
                if out_path.exists() and out_path.stat().st_mtime >= aviso_path.stat().st_mtime:
                    return out_path

                if ext == ".pdf":
                    # PyMuPDF (fitz): sin dependencia de poppler.
                    import fitz
                    doc = fitz.open(str(aviso_path))
                    if doc.page_count == 0:
                        return None
                    pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    pix.save(str(out_path))
                else:  # .eps → ghostscript
                    import configparser as _cp
                    cfg = _cp.ConfigParser()
                    cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
                    gs = cfg.get("APPS", "ghostscript", fallback="gswin64c")
                    import subprocess
                    subprocess.run(
                        [gs, "-dEPSCrop", "-sDEVICE=pngalpha", "-r150",
                         "-o", str(out_path), str(aviso_path)],
                        check=True, capture_output=True,
                    )
                if out_path.exists():
                    _log.info("Aviso PDF/EPS rasterizado P%02d → %s", numero, out_path.name)
                    return out_path
            except Exception as e:
                _log.warning("No pude convertir aviso PDF/EPS P%02d: %s", numero, e)
                return None

        # Extensión desconocida → no usamos
        return None


    def _tipo_aliases(self, tipo: str) -> list[str]:
        """Alias conocidos para detectar tipo en nombre de archivo."""
        t = tipo.casefold()
        if t in ("pagina", "pag", "página", "full", "completa"):
            return ["pagina", "pag", "página", "full", "completa"]
        if "media" in t:
            return ["media", "half", "1/2", "medio"]
        if "pie" in t:
            return ["pie"]
        if "roba" in t:
            return ["robapagina", "roba pagina", "roba"]
        return []


    def _strip_accents(self, s: str) -> str:
        s = "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )
        # convertir cualquier espacio unicode (Zs) a ' '
        s = ''.join(' ' if unicodedata.category(ch) == 'Zs' else ch for ch in s)
        return s


    def _norm_aviso(self, s: str) -> str:
        return re.sub(r'\s+', ' ', self._strip_accents(s).casefold()).strip()


    def _norm_simple(self, s: str) -> str:
        """min-normalización: casefold, quitar acentos y colapsar espacios."""
        return re.sub(r'\s+', ' ', self._strip_accents((s or '').casefold())).strip()

    def _split_tokens(self, s: str) -> list[str]:
        """tokens alfanuméricos ya normalizados (sin acentos, casefold)."""
        return re.findall(r'\w+', self._norm_simple(s))

    def _tipo_from_ini_or_arg(self, numero: int, tipo_aviso: Optional[str]) -> tuple[str, set[str]]:
        """
        Devuelve (tipo_norm, alias_set) usando primero el argumento; si está vacío,
        lo deduce del INI de la página.
        Mapas:
        - COMPLETA en INI equivale a buscar 'PAGINA' (también 'FULL', 'PÁGINA').
        """
        # 1) resolver tipo base (arg o INI)
        t = self._norm_simple(tipo_aviso or "")
        if not t:
            entry = self.read_page_entry(numero)
            if entry.get("aviso_footer", False):
                t = "pie"
            elif entry.get("aviso_half", False):
                t = "media"
            elif entry.get("aviso_full", False):
                # COMPLETA → se busca 'pagina'
                t = "pagina"
            elif entry.get("aviso_robapagina", False):
                t = "robapagina"
            else:
                t = ""

        # 2) alias de presencia en nombres de archivos (tokens)
        aliases = {
            "pie": {"pie"},
            "media": {"media", "half", "1", "1_2"},         # por si aparece 1/2 separado en tokens
            "pagina": {"pagina", "página", "full", "pag"},  # COMPLETA ≡ PAGINA
            "robapagina": {"robapagina", "roba", "roba_pagina"},
        }
        alias_set = aliases.get(t, set())
        return t, alias_set

    def _buscar_en_carpeta_simple(
        self,
        carpeta: Optional[Path],
        nombre_aviso: str,
        tipo_norm: str,
        tipo_aliases: set[str]
    ) -> Optional[Path]:
        """
        Estrategia determinística:
        - Normaliza el nombre del aviso.
        - Recorre archivos válidos (IMG_EXTS) por orden alfabético.
        - Prioriza coincidencias que contengan (nombre + tipo); si no hay,
        acepta coincidencias que contengan solo el nombre.
        - Devuelve el primer match (determinista).
        """
        if not carpeta or not Path(carpeta).exists():
            return None

        target_name = self._norm_simple(nombre_aviso)
        if not target_name:
            return None

        typed: list[Path] = []
        name_only: list[Path] = []

        try:
            for f in sorted(Path(carpeta).iterdir(), key=lambda p: p.name.casefold()):
                if not f.is_file() or f.suffix.lower() not in IMG_EXTS:
                    continue

                stem_norm = self._norm_simple(f.stem)
                if target_name and target_name in stem_norm:
                    if tipo_norm:
                        # chequear alias de tipo por tokens
                        tokens = set(self._split_tokens(stem_norm))
                        if tokens & tipo_aliases or (tipo_norm in tokens):
                            typed.append(f)
                        else:
                            name_only.append(f)
                    else:
                        name_only.append(f)
        except OSError:
            return None

        if typed:
            return typed[0]
        if name_only:
            return name_only[0]
        return None

    
    def eliminar_pdf(self, path: Path) -> None:
        """
        Envía a la papelera el PDF indicado por `path`.
        """
        p = Path(path)
        if not p.exists():
            raise FileServiceError(f"No se encontró el PDF a descartar:\n{p}")
        try:
            _eliminar_definitivo(p)
        except Exception as e:
            raise FileServiceError(f"No se pudo eliminar el PDF:\n{p}", e)


    def set_rutas(self, rutas: Dict[str, str]) -> None:
        updated = {k: (str(v) if isinstance(v, Path) else v) for k, v in rutas.items() if v}
        self.rutas.update(updated)
        if "material" in updated and updated["material"]:
            self.material = Path(updated["material"])
            try:
                self.material.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise FileServiceError(
                    "No se pudo preparar la carpeta de 'material':\n"
                    f"{self.material}\nVerificá permisos o conexión a red.", e
                )

    # =========================
    # setear len para un txt puntual
    # =========================
    def _preserve_len_suffix(self, numero: int, new_name: str) -> str:
        """
        Si el nuevo txt_name no tiene (len) pero el INI ya tenía uno,
        conserva el sufijo. Solo se aplica si el nombre base coincide.
        """
        try:
            old_entry = self.read_page_entry(numero)
            old_name = old_entry.get("txt_name", "")
            if not old_name or not new_name:
                return new_name

            # si el viejo tiene len (p. ej. "06a.txt (2345)") y el nuevo no
            if "(" in old_name and old_name.endswith(")") and "(" not in new_name:
                base_old = old_name.split(" (")[0]
                base_new = new_name.strip()
                if base_old == base_new:
                    return old_name  # conserva el sufijo
            return new_name
        except Exception:
            return new_name



    def set_txt_len(self, numero: int, txt_name: str, txt_len: int) -> None:
        """
        En la clave txt_name (que puede tener múltiples nombres separados por ';'),
        busca el que coincide con 'txt_name' (ignorando un posible sufijo '(n)')
        y lo reemplaza por 'txt_name (txt_len)'.
        """
        entry = self.read_page_entry(numero)
        raw = (entry.get("txt_name") or "").strip()
        if not raw:
            # nada para actualizar
            return

        parts = [p.strip() for p in raw.split(";") if p.strip()]
        target = _strip_len_suffix(txt_name)

        new_parts = []
        replaced = False
        for p in parts:
            base = _strip_len_suffix(p)
            if base.lower() == target.lower():
                new_parts.append(_append_len_suffix(base, txt_len))
                replaced = True
            else:
                new_parts.append(p)

        if not replaced:
            # si por algún motivo no estaba, lo agregamos al final
            new_parts.append(_append_len_suffix(target, txt_len))

        self.write_page_entry(numero, txt_name=";".join(new_parts))


    def save_fragment(self, filename: str, content: str) -> Path:
        """
        Guarda un fragmento en materiales/Pxx/, detectando el número desde el nombre si es posible.
        Si no detecta número de página, guarda directamente en la raíz de materiales/.
        """
        match = re.match(r"(?:P)?(\d{1,2})", filename)
        if match:
            numero = int(match.group(1))
            destino = self.material / f"P{numero:02d}" / _sanitize_filename(filename)
        else:
            destino = self.material / _sanitize_filename(filename)

        _write_text(destino, content)
        return destino


    def load_fragment(self, filename: str) -> str:
        origen = self.material / _sanitize_filename(filename)
        return _read_text(origen)

    def list_fragments(self) -> List[Path]:
        """
        Lista todos los archivos .txt dentro de materiales/, incluyendo subcarpetas (P01, P02, ...).
        """
        try:
            return sorted(self.material.rglob("*.txt"))
        except OSError as e:
            raise FileServiceError(
                "No se pudo listar la carpeta de 'material'. "
                "Verificá que la unidad de red esté disponible.", e
            )



    # ---------- TXT ----------
    def get_txt_path(self, numero: int, indice: int = 0) -> Path:
        """
        Devuelve la ruta completa del TXT de la noticia indicada (por índice).
        Si no existe, crea automáticamente la subcarpeta PNN/NN[a,b,c]/.
        Ejemplo: materiales/P02/02a/02a.txt
        """
        dir_noticia = self.get_or_create_noticia_dir(numero, indice)
        return dir_noticia / f"{dir_noticia.name}.txt"


    def obtener_txt(self, numero: int, indice: int = 0) -> Optional[Path]:
        """
        Devuelve el Path del archivo TXT correspondiente a una página y subnoticia (índice).
        Si aún no existen materiales para esa página, devuelve None (no lanza error).
        """
        try:
            # --- Carpeta base de la página ---
            page_dir = self.material / f"P{numero:02d}"
            if not page_dir.exists():
                # No hay carpeta de materiales todavía → página vacía
                return None

            # --- Buscar subcarpetas tipo 02a, 02b... ---
            subdirs = sorted(
                [d for d in page_dir.iterdir() if d.is_dir() and re.match(rf"^{numero:02d}[a-z]$", d.name)],
                key=lambda p: p.name
            )

            # --- Si hay subcarpetas, usar la correspondiente al índice ---
            if subdirs:
                try:
                    subdir = subdirs[indice]
                    txt_path = subdir / f"{subdir.name}.txt"
                    if txt_path.exists():
                        return txt_path
                    else:
                        return None  # subcarpeta creada pero sin txt aún
                except IndexError:
                    return None  # índice fuera de rango

            # --- Si no hay subcarpetas, probar txt raíz ---
            #txts_root = list(page_dir.glob("*.txt"))
            #if txts_root:
            #    return txts_root[0]

            # COMENTADO: ya no se usan txts en la raíz de Pxx

            # Si no hay nada todavía → página vacía
            return None

        except Exception as e:
            raise FileServiceError(f"Error al obtener TXT para P{numero:02d}: {e}")







    def asignar_txt(self, numero: int, origen: Path, indice: Optional[int] = None):
        """
        Copia un .txt desde 'origen' al destino materiales/Pxx/NN[a]/NN[a].txt,
        limpiando HTML y entidades. Usa subcarpetas por noticia.
        Si no se indica 'indice', se elige automáticamente el siguiente libre (a, b, c...).
        """
        if indice is None:
            # Detectar siguiente índice (a, b, c, ...)
            suf = self.next_noticia_suffix(numero)
            indice = ord(suf) - ord("a")

        destino = self.get_txt_path(numero, indice)
        contenido = _read_text(origen)

        # Limpieza mínima (sin HTML)
        contenido = contenido.replace("\r\n", "\n").replace("\r", "\n")
        contenido = re.sub(r"[ \t]+\n", "\n", contenido)
        contenido = re.sub(r"\n[ \t]+", "\n", contenido)
        contenido = re.sub(r"^\n+|\n+$", "", contenido)
        contenido = re.sub(r"<[^>]*>", "", contenido)

        # Entidades HTML comunes
        reemplazos = {
            "&aacute;": "á", "&eacute;": "é", "&iacute;": "í",
            "&oacute;": "ó", "&uacute;": "ú", "&ntilde;": "ñ",
            "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"
        }
        for k, v in reemplazos.items():
            contenido = contenido.replace(k, v)

        _write_text(destino, contenido.strip())

        txt_name = destino.name
        entry = self.read_page_entry(numero)

        # --- Actualización del INI coherente ---
        if entry.get("txt_name"):
            # Ya hay al menos una noticia → concatenar
            self.append_txt_entry(numero, txt_name, by=getpass.getuser())
        else:
            # Primera noticia de la página
            self.write_page_entry(
                numero,
                assigned=True,
                txt_name=txt_name,
                estado="proceso",
                by=getpass.getuser()
            )

        _log.info("TXT asignado a P%02d: %s (%s)", numero, txt_name, destino)
        return destino


    def crear_txt_manual(self, numero: int, indice: Optional[int] = None) -> Path:
        """
        Crea un TXT vacío o con texto por defecto dentro de la subcarpeta
        materiales/Pnn/NN[a]/NN[a].txt y lo registra en el INI.
        Si ya existen noticias previas, se crea la siguiente (b, c...).
        """
        if indice is None:
            suf = self.next_noticia_suffix(numero)
            indice = ord(suf) - ord("a")

        destino = self.get_txt_path(numero, indice)
        if not destino.exists():
            _write_text(destino, f"Página {numero:02d} (texto manual)\n")

        txt_name = destino.name
        entry = self.read_page_entry(numero)

        # --- Si ya hay TXT previos, concatenar ---
        if entry.get("txt_name"):
            self.append_txt_entry(numero, txt_name, by=getpass.getuser())
        else:
            self.write_page_entry(
                numero,
                txt_name=txt_name,
                estado="proceso",
                by=getpass.getuser()
            )

        _log.info("TXT manual creado para P%02d: %s (%s)", numero, txt_name, destino)
        return destino


    def limpiar_txt_entry(self, numero: int, txt_name: str):
        """
        Elimina `txt_name` (ignorando sufijo '(len)') de las listas
        txt_name/link/mono_extra de la página `numero` en su INI local Pnn/Pnn.ini.

        Usa ';' como separador canónico.
        """
        ini_path = self._page_ini_path(numero)
        cfg = configparser.ConfigParser(interpolation=None)

        if not ini_path.exists():
            _log.debug("limpiar_txt_entry: %s no existe", ini_path)
            return

        try:
            cfg.read(ini_path, encoding="utf-8")
        except Exception as e:
            _log.warning("limpiar_txt_entry: error al leer %s: %s", ini_path, e)
            return

        sec = self._ini_section(numero)
        if sec not in cfg:
            return

        s = cfg[sec]

        # Listas separadas por ';'
        txts_raw = (s.get("txt_name", "") or "").strip()
        links_raw = (s.get("link", "") or "").strip()
        extra_raw = (s.get("mono_extra", "") or "").strip()

        txts = [t.strip() for t in txts_raw.split(";") if t.strip()]
        links = [l.strip() for l in links_raw.split(";") if l.strip()]
        extras = [e.strip() for e in extra_raw.split(";") if e.strip()]

        if not txts:
            return

        # Buscar índice a borrar (ignorando sufijo "(len)")
        target = _strip_len_suffix(txt_name)
        idx_to_remove = None
        for i, t in enumerate(txts):
            if _strip_len_suffix(t).lower() == target.lower():
                idx_to_remove = i
                break

        if idx_to_remove is None:
            return

        # Eliminar ese índice alineado en las tres listas
        del txts[idx_to_remove]
        if idx_to_remove < len(links):
            del links[idx_to_remove]
        if idx_to_remove < len(extras):
            del extras[idx_to_remove]

        # Guardar de vuelta usando ';'
        s["txt_name"] = ";".join(txts)
        s["link"] = ";".join(links)
        s["mono_extra"] = ";".join(extras)

        self._save_ini_atomic_to(ini_path, cfg)



    def limpiar_notas(self, numero: int, by: str = ""):
        """
        Borra TODAS las noticias de la página:
        - txt_name → ""
        - link → ""
        - mono_extra → ""
        - assigned → false

        Conserva:
        - avisos (aviso_full, aviso_half, aviso_footer, aviso_robapagina, aviso_nombre)
        - tapa_foto / tapa_titulo
        - cualquier otra clave no relacionada con noticias.

        Se usa cuando se reconstruye una página completa desde el MONO.
        """
        ini_path = self._page_ini_path(numero)
        sec = self._ini_section(numero)

        cfg = configparser.ConfigParser(interpolation=None)

        # Si no existe, se crea con defaults vacíos pero sin noticias
        if not ini_path.exists():
            cfg[sec] = DEFAULT_PAGE_FIELDS.copy()
            s = cfg[sec]
            s["txt_name"] = ""
            s["link"] = ""
            s["mono_extra"] = ""
            s["assigned"] = "false"
            s["by"] = by
            self._save_ini_atomic_to(ini_path, cfg)
            return

        try:
            cfg.read(ini_path, encoding="utf-8")
        except Exception:
            cfg = configparser.ConfigParser(interpolation=None)
            cfg[sec] = DEFAULT_PAGE_FIELDS.copy()

        if sec not in cfg:
            cfg[sec] = DEFAULT_PAGE_FIELDS.copy()

        s = cfg[sec]

        # Limpiar solo campos de noticias
        s["txt_name"] = ""
        s["link"] = ""
        s["mono_extra"] = ""
        s["assigned"] = "false"
        s["by"] = by

        # El resto de claves (avisos, tapa, estado, seccion, etc.) quedan intactas
        self._save_ini_atomic_to(ini_path, cfg)




    def eliminar_txt_asignado(self, numero: int, idx: int | None = None) -> Optional[Path]:
        """
        Elimina el TXT (y su carpeta de subnoticia) y limpia el INI.
        """
        txt_path = self.obtener_txt(numero, idx) if idx is not None else self.obtener_txt(numero)
        if not txt_path or not txt_path.exists():
            _log.warning("No existe TXT para P%02d (idx=%s)", numero, idx)
            return None

        txt_name = txt_path.name  # ← capturamos antes de borrar carpeta

        # Borrar carpeta de la subnoticia (TXT + imágenes)
        folder = txt_path.parent
        try:
            import shutil
            shutil.rmtree(folder)
            _log.info("Carpeta eliminada: %s", folder)
        except Exception as e:
            _log.warning("No se pudo eliminar carpeta %s: %s", folder, e)

        # Limpiar INI (usa helpers internos)
        try:
            self.limpiar_txt_entry(numero, txt_name)
        except Exception as e:
            _log.warning("No se pudo limpiar INI para %s: %s", txt_name, e)

        return txt_path






    # ====== INI COMPARTIDO: helpers ======

    def set_aviso_nombre(self, numero: int, nombre: str, by: str = ""):
        self.write_page_entry(
            numero,
            aviso_nombre=nombre,
            by=(by or "")
        )

        if not nombre:
            return

        avisos_dir = Path(self.rutas.get("avisos_dir") or "")
        if avisos_dir and avisos_dir.exists():
            try:
                self.resolver_aviso_local(numero, nombre)
            except FileServiceError as e:
                _log.warning("No se pudo copiar aviso '%s' para P%02d: %s", nombre, numero, e)


    ############ INI COMPARTIDO ############ ya no es compartido
        # ---------- MONO (texto completo) ----------

    def _mono_ini_path(self) -> Optional[Path]:
        """
        INI específico para el mono:
        materiales/mono.ini
        """
        if not getattr(self, "material", None):
            return None
        return self.material / "mono.ini"


    def read_mono(self) -> dict:
        """
        Lee estado del mono desde materiales/mono.ini sección [MONO].
        """
        ini_path = self._mono_ini_path()
        if not ini_path or not ini_path.exists():
            _log.debug("mono.ini no existe todavía")
            return {}

        cfg = configparser.ConfigParser(interpolation=None)
        try:
            cfg.read(ini_path, encoding="utf-8")
        except Exception as e:
            _log.warning("Error leyendo mono.ini %s: %s", ini_path, e)
            return {}

        if "MONO" not in cfg:
            return {}

        s = cfg["MONO"]

        def _b(key: str) -> bool:
            v = s.get(key, "false").strip().lower()
            return v in ("1", "true", "yes", "y", "si", "sí")

        def _i(key: str, default: int = 0) -> int:
            try:
                return int(s.get(key, default))
            except Exception:
                return default

        return {
            "habilitado": _b("habilitado"),
            "pagina": _i("pagina", 0),
            "tipo": s.get("tipo", "").strip(),   # completa / media / pie / robapagina
            "texto": s.get("texto", "").strip(),
            "seccion": s.get("seccion", "").strip(),
        }

    def clear_mono(self):
        """
        Limpia completamente el mono (borra sección MONO de mono.ini).
        """
        ini_path = self._mono_ini_path()
        if not ini_path or not ini_path.exists():
            return

        cfg = configparser.ConfigParser(interpolation=None)
        try:
            cfg.read(ini_path, encoding="utf-8")
        except Exception as e:
            _log.warning("Error leyendo mono.ini (clear_mono) %s: %s", ini_path, e)
            return

        if "MONO" in cfg:
            cfg.remove_section("MONO")
            self._save_ini_atomic_to(ini_path, cfg)



    ### SECCIÓN DE INI POR PÁGINA ###
    
    def clear_link(self, numero: int):
        """
        Limpia el link de la página (campo 'link' del INI).
        """
        
        try:
            self.write_page_entry(
                numero,
                link="",
                )
            _log.info("Limpiado link de P%02d", numero)
        except Exception as e:
            _log.warning("No se pudo limpiar link de P%02d: %s", numero, e)

    def _page_ini_path(self, numero: int) -> Path:
        """
        Devuelve la ruta del INI de la página, p. ej.:
        materiales/P05/P05.ini
        """
        if not getattr(self, "material", None):
            raise FileServiceError("Ruta 'materiales' no configurada en FileService.")
        return self.material / f"P{numero:02d}" / f"P{numero:02d}.ini"

    def _save_ini_atomic_to(self, path: Path, cfg: configparser.ConfigParser):
        """
        Escribe un INI de forma atómica en `path`.
        """
        if not path:
            return

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")

        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            cfg.write(f)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp, path)

    
    
    
    def _shared_ini_path(self) -> Optional[Path]:
        p = self.rutas.get("shared_ini_path")
        return Path(p) if p else None

    def _ini_section(self, numero: int) -> str:
        return f"page_{numero:02d}"

    def ensure_shared_ini(self):
        """
        Crea el INI si no existe con secciones page_01..page_16 (esquema completo).
        Si ya existe, intenta migrarlo al esquema completo.
        """
        path = self._shared_ini_path()
        if not path:
            return
        if path.exists():
            # Migrar si viene de una implementación anterior
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(path, encoding="utf-8")
            if self._ensure_full_schema(cfg):
                self._save_ini_atomic(cfg)
            return

        # Crear desde cero con esquema completo
        cfg = configparser.ConfigParser()
        for i in range(1, 17):
            sec = self._ini_section(i)
            cfg[sec] = DEFAULT_PAGE_FIELDS.copy()
        self._save_ini_atomic(cfg)


    def _read_ini(self) -> Optional[configparser.ConfigParser]:
        path = self._shared_ini_path()
        if not path or not path.exists():
            return None
        cfg = configparser.ConfigParser(interpolation=None)
        try: 
            cfg.read(path, encoding="utf-8")
        except Exception as e:
            _log.error("No se pudo leer el INI compartido: %s", e)
            return None
        # Asegurar esquema completo en memoria; si falta algo, escribir
        if self._ensure_full_schema(cfg):
            self._save_ini_atomic(cfg)
        return cfg


    def _save_ini_atomic(self, cfg: configparser.ConfigParser):
        """
        Versión legacy: guarda sobre el INI “compartido”.
        La dejamos por compatibilidad, pero ya no se usa
        para páginas (sí podrían usarla funciones legacy).
        """
        ini_path = self._shared_ini_path()
        if not ini_path:
            return
        self._save_ini_atomic_to(ini_path, cfg)




    def _ensure_full_schema(self, cfg: configparser.ConfigParser) -> bool:
        """
        Garantiza que el INI tenga:
        - Secciones page_01..page_16
        - TODAS las claves del esquema completo (DEFAULT_PAGE_FIELDS)
        Devuelve True si hizo cambios.
        """
        changed = False

        # Asegurar secciones page_01..page_16
        for i in range(1, 17):
            sec = self._ini_section(i)
            if sec not in cfg:
                cfg[sec] = DEFAULT_PAGE_FIELDS.copy()
                changed = True

        # Rellenar claves faltantes en cada sección
        for i in range(1, 17):
            sec = self._ini_section(i)
            s = cfg[sec]
            for k, v in DEFAULT_PAGE_FIELDS.items():
                if k not in s:
                    s[k] = v
                    changed = True

        return changed

    def migrate_ini_schema(self) -> None:
        """
        Migra el INI existente al esquema completo si hiciera falta
        (agrega claves que falten y/o secciones). Escritura atómica.
        """
        path = self._shared_ini_path()
        if not path or not path.exists():
            return
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf-8")
        if self._ensure_full_schema(cfg):
            self._save_ini_atomic(cfg)
        

    def read_page_entry(self, numero: int) -> dict:
        """
        Lee INI por página (Pnn.ini) con reparación automática:
        - Si falta el archivo → defaults
        - Si falta la sección → defaults
        - Si faltan claves → se completan con defaults
        - Retorna dict convertido a tipos correctos
        """
        ini_path = self._page_ini_path(numero)
        sec = self._ini_section(numero)

        if not ini_path.exists():
            return self._convert_ini_to_dict(DEFAULT_PAGE_FIELDS)

        cfg = configparser.ConfigParser(interpolation=None)
        try:
            cfg.read(ini_path, encoding="utf-8")
        except Exception:
            return self._convert_ini_to_dict(DEFAULT_PAGE_FIELDS)

        if sec not in cfg:
            return self._convert_ini_to_dict(DEFAULT_PAGE_FIELDS)

        # ====================================================
        # 🔹 Reparar claves faltantes en el archivo
        # ====================================================
        repaired = False
        for key, default_val in DEFAULT_PAGE_FIELDS.items():
            if key not in cfg[sec]:
                cfg[sec][key] = default_val
                repaired = True

        if repaired:
            # guardar reparación
            self._save_ini_atomic_to(ini_path, cfg)

        # ====================================================
        # 🔹 Convertir valores a tipos correctos (Lo que UI espera)
        # ====================================================
        return {
            "assigned": cfg[sec].getboolean("assigned", fallback=False),
            "txt_name": cfg[sec].get("txt_name", "").strip(),
            "aviso_full": cfg[sec].getboolean("aviso_full", fallback=False),
            "aviso_half": cfg[sec].getboolean("aviso_half", fallback=False),
            "aviso_footer": cfg[sec].getboolean("aviso_footer", fallback=False),
            "aviso_robapagina": cfg[sec].getboolean("aviso_robapagina", fallback=False),
            "aviso_nombre": cfg[sec].get("aviso_nombre", "").strip(),
            "tapa_foto": cfg[sec].getboolean("tapa_foto", fallback=False),
            "tapa_titulo": cfg[sec].getboolean("tapa_titulo", fallback=False),
            "listo_para_armar": cfg[sec].getboolean("listo_para_armar", fallback=False),
            "editando": cfg[sec].getboolean("editando", fallback=False),
            "editando_por": cfg[sec].get("editando_por", "").strip(),
            "mono_extra": cfg[sec].get("mono_extra", "").strip(),
            "by": cfg[sec].get("by", "").strip(),
            "ts": cfg[sec].get("ts", "").strip(),
            "link": cfg[sec].get("link", "").strip(),
            "seccion": cfg[sec].get("seccion", "").strip(),
            "estado": cfg[sec].get("estado", "").strip().lower(),
            "maqueta": cfg[sec].get("maqueta", "").strip(),
            "historial_by": cfg[sec].get("historial_by", "").strip(),
            "historial_ts": cfg[sec].get("historial_ts", "").strip(),
            "historial_accion": cfg[sec].get("historial_accion", "").strip(),
        }

    def write_page_entry(self, numero: int, **campos):
        """
        Escribe/actualiza el INI de la página Pnn.ini
        y garantiza que NUNCA falten claves.
        """
        ini_path = self._page_ini_path(numero)
        sec = self._ini_section(numero)

        cfg = configparser.ConfigParser(interpolation=None)

        # Si ya existía, cargarlo
        if ini_path.exists():
            try:
                cfg.read(ini_path, encoding="utf-8")
            except Exception:
                cfg = configparser.ConfigParser(interpolation=None)

        # Si falta sección: crearla
        if sec not in cfg:
            cfg[sec] = DEFAULT_PAGE_FIELDS.copy()
        else:
            # Reparar claves faltantes antes de escribir
            s = cfg[sec]
            for key, default_val in DEFAULT_PAGE_FIELDS.items():
                if key not in s:
                    s[key] = default_val

        s = cfg[sec]

        # Aplicar campos recibidos
        for k, v in campos.items():
            if v is None:
                continue

            # === NUEVO: preservar sufijo (len) en txt_name ===
            if k == "txt_name":
                try:
                    antiguo = s.get("txt_name", "")
                    nuevo = str(v)
                    # Usamos tu propio método interno si existe, o preservamos manualmente.
                    if "(" in antiguo and antiguo.endswith(")") and "(" not in nuevo:
                        # ejemplo: antiguo = "06a.txt (5970)"
                        # nuevo    = "06a.txt"
                        base_antiguo = antiguo.rsplit("(", 1)[0].strip()
                        base_nuevo = nuevo.strip()
                        if base_nuevo == base_antiguo:
                            s[k] = antiguo  # preserva entero: "06a.txt (5970)"
                            continue
                except Exception:
                    pass

            if isinstance(v, bool):
                s[k] = "true" if v else "false"
            else:
                s[k] = str(v)


        # Timestamp automático si no se mandó
        if "ts" not in campos:
            s["ts"] = datetime.datetime.now().isoformat(timespec="seconds")

        # Asegurar "by"
        if "by" not in campos and "by" not in s:
            s["by"] = ""

        # Guardar
        self._save_ini_atomic_to(ini_path, cfg)

    def registrar_trabajo(self, numero: int, usuario: str, accion: str) -> None:
        """#1 — Appendea una entrada de historial (usuario|fecha|acción) a las claves
        historial_*, ';'-separadas. NO toca by/ts/estado (no cambia el color)."""
        usuario = (usuario or "?").strip()
        accion = (accion or "").strip()
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        entry = self.read_page_entry(numero)
        def _append(prev: str, val: str) -> str:
            prev = (prev or "").strip()
            return f"{prev};{val}" if prev else val
        self.write_page_entry(
            numero,
            historial_by=_append(entry.get("historial_by", ""), usuario),
            historial_ts=_append(entry.get("historial_ts", ""), ts),
            historial_accion=_append(entry.get("historial_accion", ""), accion),
            ts=entry.get("ts"),   # preservar ts del dueño (no autogenerar)
        )

    def _convert_ini_to_dict(self, mapping: dict) -> dict:
        """
        Convierte el DEFAULT_PAGE_FIELDS a tipos adecuados
        """
        return {
            "assigned": mapping.get("assigned", "false").lower() == "true",
            "txt_name": mapping.get("txt_name", ""),
            "aviso_full": mapping.get("aviso_full", "false").lower() == "true",
            "aviso_half": mapping.get("aviso_half", "false").lower() == "true",
            "aviso_footer": mapping.get("aviso_footer", "false").lower() == "true",
            "aviso_robapagina": mapping.get("aviso_robapagina", "false").lower() == "true",
            "aviso_nombre": mapping.get("aviso_nombre", ""),
            "tapa_foto": mapping.get("tapa_foto", "false").lower() == "true",
            "tapa_titulo": mapping.get("tapa_titulo", "false").lower() == "true",
            "listo_para_armar": mapping.get("listo_para_armar", "false").lower() == "true",
            "mono_extra": mapping.get("mono_extra", ""),
            "by": mapping.get("by", ""),
            "ts": mapping.get("ts", ""),
            "link": mapping.get("link", ""),
            "seccion": mapping.get("seccion", ""),
            "estado": mapping.get("estado", ""),
            "historial_by": mapping.get("historial_by", ""),
            "historial_ts": mapping.get("historial_ts", ""),
            "historial_accion": mapping.get("historial_accion", ""),
        }



    def append_txt_entry(self, numero: int, txt_name: str, link: str = "", mono_extra: str = "", by: str = "", txt_len: int | None = None):
        """
        Agrega un nuevo TXT/link a la entrada INI de la página, concatenando con ';' si ya existen valores previos.
        Si txt_len se pasa, persiste el nombre como 'nombre.txt (len)'.
        """
        entry = self.read_page_entry(numero)
        old_txt = (entry.get("txt_name") or "").strip()
        old_link = (entry.get("link") or "").strip()
        old_extra = (entry.get("mono_extra") or "").strip()

        # normalizar nombre con len si corresponde
        clean = _append_len_suffix(txt_name, txt_len)

        new_txt = f"{old_txt};{clean}" if old_txt else clean
        new_link = f"{old_link};{link}" if link and old_link else link or old_link
        new_extra = f"{old_extra};{mono_extra}" if mono_extra and old_extra else mono_extra or old_extra

        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            txt_name=new_txt,
            link=new_link,
            mono_extra=new_extra,
            by=(by or entry.get("by") or "")
        )


    
    # ---------- Flags de tapa ----------
    def mark_tapa_foto(self, numero: int, by: Optional[str] = None):
        """
        Marca la página como 'Tapa Foto' en el INI.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            tapa_foto=True,
            tapa_titulo=False,
            by=(by or entry.get("by") or "")
        )

    def mark_tapa_titulo(self, numero: int, by: Optional[str] = None):
        """
        Marca la página como 'Tapa Título' en el INI.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            tapa_foto=False,
            tapa_titulo=True,
            by=(by or entry.get("by") or "")
        )   

    def clear_tapa_flags(self, numero: int, by: Optional[str] = None):
        """
        Limpia los flags de tapa (foto/título).
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            tapa_foto=False,
            tapa_titulo=False,
            by=(by or entry.get("by") or "")
        )

    # ---------- Texto extra MONO ----------
    def set_mono_extra(self, numero: int, texto: str, by: Optional[str] = None):
        """
        Persiste el texto extra del MONO (lo que está después del guion).
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            mono_extra=(texto or ""),
            by=(by or entry.get("by") or "")
        )

    def clear_mono_extra(self, numero: int, by: Optional[str] = None):
        """
        Limpia el texto extra del MONO.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            mono_extra="",
            by=(by or entry.get("by") or "")
        )

    
    
    
    
    def mark_assigned(self, numero: int, txt_name: str, by: Optional[str] = None, apagar_aviso_full: bool = True):
        """
        Asignar TXT localmente y en INI. Si estaba 'completa', la apaga.
        No toca aviso_half/footer si existieran.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            assigned=True,
            txt_name=txt_name,
            aviso_full=False if apagar_aviso_full else entry.get("aviso_full"),
            estado="proceso",
            # Asignar (user o bot) resetea 'listo para armar': el contenido cambió/reasignó.
            listo_para_armar="false",
            by=(by or entry.get("by") or "")
        )
        # Copiar maqueta según aviso/sección
        cfg = configparser.ConfigParser()
        cfg.read(str(Config.CONFIG_FILE), encoding="utf-8") 
        version_quark = cfg.get("quark", "quark_seleccionado", fallback="Quark 8").strip()
        if version_quark == "Quark 2018":
            try:
                self.copiar_maqueta_a_materiales(numero)
            except Exception as e:
                _log.warning("No se pudo copiar maqueta para P%02d: %s", numero, e)





    def mark_aviso_robapagina(self, numero: int, by: Optional[str] = None):
        """
        Robapágina: enciende robapagina, apaga full/half/footer. Compatible con texto (no lo toca). 
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            
            numero,
            aviso_full=False,
            aviso_half=False,
            aviso_footer=False,
            aviso_robapagina=True,
            by=(by or entry.get("by") or "")
        )



    def mark_aviso_full(self, numero: int, by: Optional[str] = None):
        """
        Completa: enciende full, apaga half/footer y limpia texto.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            aviso_full=True,
            aviso_half=False,
            aviso_footer=False,
            assigned=False,
            txt_name="",
            by=(by or entry.get("by") or "")
        )
        # Copiar maqueta según aviso/sección (en completa: completa.qxp → {numero}.qxp)
        cfg = configparser.ConfigParser()
        cfg.read(str(Config.CONFIG_FILE), encoding="utf-8")
        version_quark = cfg.get("quark", "quark_seleccionado", fallback="Quark 8").strip()
        if version_quark == "Quark 2018":
            try:
                self.copiar_maqueta_a_materiales(numero)
            except Exception as e:
                _log.warning("No se pudo copiar maqueta para P%02d: %s", numero, e)

    def mark_aviso_half(self, numero: int, by: Optional[str] = None):
        """
        Media: enciende half, apaga full/footer. Compatible con texto (no lo toca).
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            aviso_full=False,
            aviso_half=True,
            aviso_footer=False,
            by=(by or entry.get("by") or "")
        )

    def mark_aviso_footer(self, numero: int, by: Optional[str] = None):
        """
        Pie: enciende footer, apaga full/half. Compatible con texto (no lo toca).
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            aviso_full=False,
            aviso_half=False,
            aviso_footer=True,
            by=(by or entry.get("by") or "")
        )

    def clear_avisos(self, numero: int, by: Optional[str] = None):
        """
        Quita todos los avisos (full/half/footer) en INI.
        No toca 'assigned' ni 'txt_name'.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            aviso_full=False,
            aviso_half=False,
            aviso_footer=False,
            aviso_robapagina=False,
            aviso_nombre = "",
            by=(by or entry.get("by") or "")
        )

    def set_seccion(self, numero: int, seccion: str, by: Optional[str] = None):
        """
        Persiste la sección textual de la página en el INI (e.g. 'Política', 'Locales').
        No toca avisos ni assigned.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            seccion=(seccion or ""),
            by=(by or entry.get("by") or "")
        )

    def clear_seccion(self, numero: int, by: Optional[str] = None):
        """
        Limpia la sección de la página en el INI.
        """
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            seccion="",
            by=(by or entry.get("by") or "")
        )


    def clear_assignment(self, numero: int, by: Optional[str] = None, borrar_qxp: bool = False):
        """
        Quita la asignación de usuario SIN tocar txt_name ni avisos.
        Si borrar_qxp=True, elimina el QXP de la página en TODAS las ubicaciones
        (materiales, proceso, base, final, mandar, a pdf), con guard de archivo abierto.
        """
        # 1) Borrar QXP (todas las ubicaciones) ANTES de tocar el INI, para que el
        #    guard de archivo abierto aborte sin dejar el INI inconsistente.
        if borrar_qxp:
            self.eliminar_qxp_todas_ubicaciones(numero)   # puede lanzar FileServiceError si está abierto

        # 2) Quitar asignación en el INI
        entry = self.read_page_entry(numero)
        self.write_page_entry(
            numero,
            assigned=False,
            estado="",
            by=(by or entry.get("by") or "")
        )




    # === Localización de QXP ===
    def buscar_qxp_spread(self, numero: int, pareja: int) -> Optional[Path]:
        """
        Busca un archivo spread que contenga ambas páginas, por ejemplo "08 y 09.qxp",
        en las carpetas de trabajo (base, final, mandar).
        """
        rutas = self.rutas or {}
        base_dir = Path(rutas.get("quark_output_dir") or "")
        if not base_dir:
            return None

        final_dir = base_dir / "final"
        mandar_dir = final_dir / "mandar"

        patrones = [
            f"{numero:02d} y {pareja:02d}.qxp",
            f"{pareja:02d} y {numero:02d}.qxp",
            f"{numero:02d}-{pareja:02d}.qxp",
            f"{pareja:02d}-{numero:02d}.qxp",
        ]


        # Prioridad de búsqueda: mandar → final → base
        for carpeta in (mandar_dir, final_dir, base_dir):
            if not carpeta or not carpeta.exists():
                continue
            for patron in patrones:
                cand = carpeta / patron
                if cand.exists():
                    return cand

        return None




    def buscar_qxp_por_numero(self, carpeta: Path, numero: int) -> Optional[Path]:
        """
        Busca el QXP correspondiente a 'numero' en 'carpeta'.

        Reglas por carpeta:
        - Base (quark_output_dir): SOLO nombres que comiencen con 'Pag' o 'Pág'.
        - Final / Mandar (quark_output_dir/final[/mandar]): SOLO nombres numéricos (descarta 'Pag ...').
        - Otras carpetas (p.ej. 'personal'): permisivo (acepta ambos).
        Prioridad: exact match > spread match.

        Además amplía búsqueda para archivos tipo:
        - Pag 09 - Locales.qxp
        - 09 Locales.qxp
        - Pág 09.qxp
        """
        carpeta = Path(carpeta)
        if not carpeta.exists():
            return None

        # --- Determinar contexto por RUTA (no por nombre) ---
        base_dir   = Path(self.rutas.get("quark_output_dir") or "")
        final_dir  = base_dir / "final"
        mandar_dir = final_dir / "mandar"
        apdf_dir = mandar_dir / "a pdf"
        
        def _same(a: Path, b: Path) -> bool:
            try:
                return a.resolve() == b.resolve()
            except Exception:
                return str(a).rstrip("\\/").lower() == str(b).rstrip("\\/").lower()

        is_base   = base_dir.exists()   and _same(carpeta, base_dir)
        is_final  = final_dir.exists()  and _same(carpeta, final_dir)
        is_mandar = mandar_dir.exists() and _same(carpeta, mandar_dir)
        is_apdf = apdf_dir.exists() and _same(carpeta, apdf_dir)
        modo = "base" if is_base else ("final_mandar" if (is_final or is_mandar or is_apdf) else "otro")

        exact_pag = None
        exact_otro = None
        spread_pag = None
        spread_otro = None

        try:
            for f in carpeta.iterdir():
                if not f.is_file() or f.suffix.lower() not in (".qxp", ".pqx"):
                    continue

                stem = f.stem

                # --- Filtrado según modo ---
                if modo == "final_mandar":
                    # En final/mandar ignorar los 'Pag ...'
                    if re.match(r"^p(ag|ág)[\s_-]*", stem, re.IGNORECASE):
                        continue
                    # Debe contener el número de forma tolerante
                    if not re.search(rf"(^|[^0-9])0*{numero}([^\d]|$)", stem):
                        continue

                else:
                    # En BASE u otras carpetas: aceptar Pag NN y NN (y spreads)
                    # (sin el filtro excluyente anterior)
                    pass

                pages = self._extract_qxp_pages(stem)
                if not pages or numero not in pages:
                    continue

                es_pag = bool(re.match(rf"^p(ag|ág)[\s_-]*0*{numero}\b", stem, re.IGNORECASE))

                if len(pages) == 1:
                    if es_pag and exact_pag is None:
                        exact_pag = f
                    elif exact_otro is None:
                        exact_otro = f
                else:
                    if es_pag and spread_pag is None:
                        spread_pag = f
                    elif spread_otro is None:
                        spread_otro = f

        except FileNotFoundError:
            return None

        return exact_pag or exact_otro or spread_pag or spread_otro



    def actualizar_estado_spread(self, numero: int, nuevo_estado: str):
        """
        Actualiza el estado de una página y su pareja solo si:
        - existe un spread físico (NN y NN.qxp)
        - y ambas páginas compartían el mismo estado previo.
        En cualquier otro caso, actualiza solo la individual.
        """
        if not nuevo_estado:
            return

        entry = self.read_page_entry(numero)
        estado_actual = (entry.get("estado") or "").strip().lower()
        pareja = numero + 1 if numero % 2 == 0 else numero - 1
        if not (1 <= pareja <= 16):
            self.write_page_entry(numero, estado=nuevo_estado)
            return

        entry_par = self.read_page_entry(pareja)
        estado_par = (entry_par.get("estado") or "").strip().lower()
        spread = self.buscar_qxp_spread(numero, pareja)

        # 🔹 Solo sincroniza si hay spread físico y los dos estados eran iguales
        if spread and spread.exists() and estado_actual == estado_par:
            self.write_page_entry(numero, estado=nuevo_estado)
            self.write_page_entry(pareja, estado=nuevo_estado)
        else:
            self.write_page_entry(numero, estado=nuevo_estado)


    def _extract_pdf_pages(self, stem: str) -> set[int]:
        """
        Igual que _extract_qxp_pages, pero adaptado para PDFs:
        Detecta números de página en nombres como:
        - '08.pdf' → {8}
        - '08-09.pdf' o '08 y 09.pdf' → {8,9}
        - '08_09m.pdf' → {8,9}
        - '08m.pdf' → {8}
        - También detecta nombres como '08GOB' o '05v1' (sin separador).
        """
        name = self._norm_spaces(stem)
        # Buscar números al inicio o separados por guiones/y/_
        m = re.match(
            r'^(?P<n1>\d{1,2})(?P<suf1>[A-Za-z]*)'
            r'(?:\s*(?:y|e|&|/|_|-+|–|—)\s*(?P<n2>\d{1,2})(?P<suf2>[A-Za-z]*))?',
            name
        )
        if not m:
            return set()

        pages = set()
        for key in ("n1", "n2"):
            val = m.group(key)
            if not val:
                continue
            try:
                n = int(val)
                if 1 <= n <= 16:
                    pages.add(n)
            except ValueError:
                continue
        return pages



    def find_pdf_for_page(self, numero: int) -> Optional[Path]:
        """
        Devuelve la ruta del PDF asociado a una página.
        Ahora detecta PDFs dobles o con sufijos:
        - 08.pdf, 08-09.pdf, 08 y 09.pdf, 08_09m.pdf, 08m.pdf, etc.
        Prioridad: carpeta principal → OK/.
        """
        pdf_dir = Path(self.rutas.get("pdf_output_dir") or "")
        if not pdf_dir.exists():
            return None

        ok_dir = Path(self.rutas.get("pdf_ok_dir") or (pdf_dir / "OK"))

        for carpeta in (pdf_dir, ok_dir):
            if not carpeta.exists():
                continue
            for f in carpeta.iterdir():
                if not f.is_file() or f.suffix.lower() not in (".pdf", ".PDF"):
                    continue

                pages = self._extract_pdf_pages(f.stem)
                if numero in pages:
                    return f
        return None


    # === Localización de QXP según nivel ===
    def find_qxp_apdf(self, numero: int) -> Optional[Path]:
        base = Path(self.rutas.get("quark_output_dir") or "")
        apdf = base / "final" / "mandar" / "a pdf"
        if not apdf.exists():
            return None
        return self.buscar_qxp_por_numero(apdf, numero)

    def find_qxp_pares_maquetacion(self, numero: int) -> list[Path]:
        """
        Devuelve una lista de hasta dos QXP en Base para Maquetación y avisos:
        - Uno que empiece con 'Pag NN -'
        - Otro del mismo número pero que NO empiece con 'Pag NN -'
        """
        base = Path(self.rutas.get("quark_output_dir") or "")
        if not base.exists():
            return []

        patron_pag = re.compile(rf"^p(ag|ág)[\s_-]*0*{numero}\b.*\.qxp$", re.IGNORECASE)
        patron_otro = re.compile(rf"^(?!p(ag|ág)[\s_-]*0*{numero}\b).*0*{numero}\b.*\.qxp$", re.IGNORECASE)

        qxp_pag = None
        qxp_otro = None

        for f in base.iterdir():
            if not f.is_file() or f.suffix.lower() != ".qxp":
                continue
            if patron_pag.match(f.name):
                qxp_pag = f
            elif patron_otro.match(f.name):
                qxp_otro = f

        result = [p for p in (qxp_pag, qxp_otro) if p]
        return result


    def find_qxp_mandar(self, numero: int) -> Optional[Path]:
        base = Path(self.rutas.get("quark_output_dir") or "")
        mandar = base / "final" / "mandar"
        if not mandar.exists():
            return None
        return self.buscar_qxp_por_numero(mandar, numero)


    def find_qxp_final(self, numero: int) -> Optional[Path]:
        base = Path(self.rutas.get("quark_output_dir") or "")
        final = base / "final"
        if not final.exists():
            return None
        return self.buscar_qxp_por_numero(final, numero)


    def find_qxp_base(self, numero: int) -> Optional[Path]:
        base = Path(self.rutas.get("quark_output_dir") or "")
        if not base.exists():
            return None
        return self.buscar_qxp_por_numero(base, numero)


    def mejor_qxp_para_pegar(self, numero: int) -> Optional[Path]:
        """QXP más adelantado por estado (para abrir y pegar). Nunca devuelve PDF/TXT.

        Prioridad: a pdf → mandar → final → base numérico ('NN.qxp', el mismo archivo
        que avanza el Mover) → materiales/Pnn. 'materiales/Pnn' es el control del primer
        armado y es el último recurso: solo se abre si no hay nada más adelantado.
        """
        return (
            self.find_qxp_apdf(numero)
            or self.find_qxp_mandar(numero)
            or self.find_qxp_final(numero)
            or self.find_qxp_base_numerico(numero)
            or self.find_qxp_en_materiales(numero)
        )



    # ---------- Helpers búsqueda ----------
    def _norm_spaces(self, s: str) -> str:
        """
        casefold + convierte cualquier espacio unicode (Zs) a espacio ASCII ' '
        y colapsa múltiples espacios. Quita espacios al inicio/fin.
        """
        s = s.casefold()
        s = ''.join(' ' if unicodedata.category(ch) == 'Zs' else ch for ch in s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    # --- NUEVO: extracción de páginas desde el nombre del QXP (stem) ---
    def _extract_qxp_pages(self, stem: str) -> set[int]:
        """
        Devuelve el conjunto de páginas detectadas en el nombre SIN extensión (stem).
        - Acepta solo números reales al inicio del nombre o luego de 'Pag'/'Pág'.
        - Ignora cualquier dígito suelto dentro del texto o del tema (ej: 'Política').
        - Ejemplos válidos:
            'Pag 08 - Política' → {8}
            '08 y 09' → {8,9}
            'Pag 08-09 – Deportes' → {8,9}
            '09 y 08' → {9,8}
        """
        name = self._norm_spaces(stem)
        # eliminar prefijo 'Pag' o 'Pág'
        name = re.sub(r'^p(ag|ág)\b[\s_-]*', '', name, flags=re.IGNORECASE)

        # buscar números solo al inicio o separados por y/-/–/—/_/
        m = re.match(
            r'^(?P<n1>\d{1,2})(?P<suf1>[A-Za-z]*)'  # ← tolera sufijos alfanuméricos cortos
            r'(?:\s*(?:y|e|&|/|_|-+|–|—)\s*(?P<n2>\d{1,2})(?P<suf2>[A-Za-z]*))?',
            name
        )
        if not m:
            return set()

        pages = set()
        n1 = m.group('n1')
        n2 = m.group('n2')

        try:
            if n1:
                n = int(n1)
                if 1 <= n <= 16:
                    pages.add(n)
        except ValueError:
            pass

        try:
            if n2:
                n = int(n2)
                if 1 <= n <= 16:
                    pages.add(n)
        except ValueError:
            pass

        return pages



    def _match_qxp_number(self, stem: str, numero: int) -> bool:
        """
        True si el nombre (sin extensión) representa a 'numero' ya sea como QXP simple
        (p.ej. '08', 'Pag 08', '08GOB') o como QXP doble que lo incluya
        (p.ej. '08 y 09', '08-09', 'Pag 08–09 ...').
        """
        pages = self._extract_qxp_pages(stem)
        return numero in pages



    def buscar_archivo_insensible(self, carpeta: Path, nombre_objetivo: str) -> Optional[Path]:
        carpeta = Path(carpeta)
        if not carpeta.exists():
            return None
        objetivo = nombre_objetivo.lower()
        for f in carpeta.iterdir():
            if f.is_file() and f.name.lower() == objetivo:
                return f
        return None

    def buscar_archivo_por_prefijo(self, carpeta: Path, prefijo: str, extension: str = ".qxp") -> Optional[Path]:
        """
        Busca archivo con 'prefijo' al inicio del NOMBRE (sin extensión),
        normalizando espacios unicode. Útil para 'Pag 02 ...'
        """
        carpeta = Path(carpeta)
        if not carpeta.exists():
            return None
        ext = extension.lower()
        px_norm = self._norm_spaces(prefijo)
        for f in carpeta.iterdir():
            if not f.is_file() or f.suffix.lower() != ext:
                continue
            stem_norm = self._norm_spaces(f.stem)
            if stem_norm.startswith(px_norm):
                return f
        return None

    def encontrar_qxp_por_prefijo(self, carpeta: Path, prefijo: str) -> Optional[Path]:
        return self.buscar_archivo_por_prefijo(carpeta, prefijo, ".qxp")


    # ---------- Copia de imágenes materiales → Base ----------
    def copy_images_materiales_a_base(self, numero: int, modo: str = "convencion") -> list[Path]:
        """
        Copia imágenes desde materiales/Pxx/ hacia la raíz de Base (quark_output_dir),
        manteniendo el nombre original (sin renombrar). Sin WEBP.
        - modo="convencion": solo copia archivos que cumplan 'principal_XX.*' o 'extraN_XX.*'
        - modo="todas": copia todas las imágenes permitidas.
        Devuelve lista de destinos copiados (best-effort).
        """
        base = Path(self.rutas.get("quark_output_dir") or "")
        if not base.exists():
            return []
        src_dir = self.material / f"P{numero:02d}"
        if not src_dir.exists():
            return []

        copiados: list[Path] = []
        patron_principal = re.compile(rf"^principal[_\s-]*{numero:02d}\.", re.IGNORECASE)
        patron_extra     = re.compile(rf"^extra\d*[_\s-]*{numero:02d}\.", re.IGNORECASE)

        try:
            for f in sorted(src_dir.iterdir()):
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                if ext not in IMG_EXTS:
                    continue  # sin WEBP u otros

                ok = False
                if modo == "todas":
                    ok = True
                else:
                    # Solo convención fuerte (si renombraste manualmente)
                    n = f.name
                    ok = bool(patron_principal.match(n) or patron_extra.match(n))

                if not ok:
                    continue

                dst = base / f.name  # misma carpeta donde está el QXP (raíz de Base)
                dst = self._unique_dest(dst)
                try:
                    _copy_file(f, dst, overwrite=False)
                    copiados.append(dst)
                except FileServiceError as e:
                    _log.warning("No pude copiar imagen '%s' → %s: %s", f.name, dst, e)
                    continue
        except FileNotFoundError:
            pass
        return copiados


    #def find_base_image_for_page(self, numero: int) -> Optional[Path]:
    #    """
    #    Busca en la raíz de Base una imagen para la página:
    #    1) 'principal_XX.*'
    #    2) la primera 'extraN_XX.*'
    #    3) (si no hay convención) la primera imagen *_XX.* (relajada)
    #    """
    #    base = Path(self.rutas.get("quark_output_dir") or "")
    #    if not base.exists():
    #        return None

        # Preferencia: principal_XX
    #    for f in base.iterdir():
    #        if not f.is_file() or f.suffix.lower() not in IMG_EXTS:
    #            continue
    #        if re.match(rf"^principal[_\s-]*{numero:02d}\.", f.name, re.IGNORECASE):
    #            return f

        # Luego: extraN_XX
    #    for f in base.iterdir():
    #        if not f.is_file() or f.suffix.lower() not in IMG_EXTS:
    #            continue
    #        if re.match(rf"^extra\d*[_\s-]*{numero:02d}\.", f.name, re.IGNORECASE):
    #            return f

        # Fallback (relajado): cualquier *_XX.*
    #    suf = f"_{numero:02d}".lower()
    #    for f in base.iterdir():
    #        if not f.is_file() or f.suffix.lower() not in IMG_EXTS:
    #            continue
    #        stem = f.stem.lower()
    #        if stem.endswith(suf):
    #            return f

    #    return None

    # ============================================================
    # 🔹 Noticias múltiples por página
    # ============================================================

    def get_or_create_noticia_dir(self, numero: int, indice: int = 0) -> Path:
        """
        Devuelve la ruta a la carpeta de una noticia específica dentro de materiales/PXX.
        Si no existe, la crea automáticamente.
        Ejemplo: get_or_create_noticia_dir(2, 0) -> /materiales/P02/02a/
        """
        base_material = Path(self.rutas.get("material") or "")
        if not base_material:
            raise FileServiceError("Ruta base de materiales no configurada")

        page_dir = base_material / f"P{numero:02d}"
        suffix = chr(ord("a") + indice)  # 0->a, 1->b, 2->c, ...
        noticia_dir = page_dir / f"{numero:02d}{suffix}"

        noticia_dir.mkdir(parents=True, exist_ok=True)
        return noticia_dir


    def next_noticia_suffix(self, numero: int) -> str:
        """
        Determina el siguiente sufijo disponible para una nueva noticia en la página dada.
        Si existe 02a y 02b, devuelve 'c'.
        """
        base_material = Path(self.rutas.get("material") or "")
        page_dir = base_material / f"P{numero:02d}"

        existentes = []
        if page_dir.exists():
            for sub in page_dir.iterdir():
                if sub.is_dir() and re.match(rf"^{numero:02d}[a-z]$", sub.name):
                    existentes.append(sub.name[-1])

        existentes.sort()
        if not existentes:
            return "a"
        ultimo = existentes[-1]
        siguiente = chr(ord(ultimo) + 1)
        return siguiente


    def get_noticia_dirs(self, numero: int) -> list[Path]:
        """
        Devuelve todas las subcarpetas de noticias dentro de materiales/PXX,
        ordenadas alfabéticamente (a, b, c...).
        """
        base_material = Path(self.rutas.get("material") or "")
        page_dir = base_material / f"P{numero:02d}"
        if not page_dir.exists():
            return []

        subdirs = [d for d in sorted(page_dir.iterdir()) if d.is_dir() and re.match(rf"^{numero:02d}[a-z]$", d.name)]
        return subdirs

    # ──────────────────────────────────────────────────────────────
    # Notas múltiples por ROL — rol↔sufijo determinístico, lista del disco
    #   principal→a · secundaria→b · noticia_3→c · noticia_N→letra[N-1]
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def rol_a_sufijo(rol: str) -> str:
        rol = (rol or "principal").strip().lower()
        if rol == "principal":
            return "a"
        if rol == "secundaria":
            return "b"
        m = re.match(r"noticia_(\d+)$", rol)
        n = int(m.group(1)) if m else 1
        return chr(ord("a") + max(0, n - 1))

    @staticmethod
    def sufijo_a_rol(suf: str) -> str:
        i = ord(suf) - ord("a")
        return {0: "principal", 1: "secundaria"}.get(i, f"noticia_{i + 1}")

    def noticia_dir_de_rol(self, numero: int, rol: str) -> Path:
        """Crea/devuelve la carpeta 02{sufijo} correspondiente al rol."""
        indice = ord(self.rol_a_sufijo(rol)) - ord("a")
        d = self.get_or_create_noticia_dir(numero, indice)
        _log.debug("noticia_dir_de_rol P%02d rol=%s → %s", numero, rol, d.name)
        return d

    def get_notas(self, numero: int) -> list[dict]:
        """
        Lista ordenada de notas de la página, derivada del DISCO (no del INI).
        Cada item: {rol, sufijo, dir, txt_path, json_path}.
        El rol viene del sufijo; si el JSON trae un rol/tipo distinto, se avisa (swap).
        """
        out: list[dict] = []
        for d in self.get_noticia_dirs(numero):
            suf = d.name[-1]
            txt = d / f"{d.name}.txt"
            js = d / f"{d.name}.json"
            rol = self.sufijo_a_rol(suf)
            # Detección de swap de colocación: el rol del JSON no coincide con el sufijo
            if js.exists():
                try:
                    jd = json.loads(js.read_text(encoding="utf-8"))
                    rol_json = (jd.get("rol") or jd.get("tipo") or "").strip().lower()
                    if rol_json and rol_json != rol:
                        _log.warning(
                            "P%02d: carpeta %s tiene rol-JSON '%s' que NO coincide con su sufijo (rol=%s)",
                            numero, d.name, rol_json, rol)
                except Exception:
                    pass
            out.append({
                "rol": rol,
                "sufijo": suf,
                "dir": d,
                "txt_path": txt if txt.exists() else None,
                "json_path": js if js.exists() else None,
            })
        _log.debug("get_notas P%02d → %s", numero, [(n["rol"], n["dir"].name) for n in out])
        return out

    def has_notas(self, numero: int) -> bool:
        return bool(self.get_noticia_dirs(numero))

    @staticmethod
    def nota_len(txt_path: Path) -> int:
        """Longitud del cuerpo de la nota (reemplaza el sufijo '(len)' del INI)."""
        try:
            partes = txt_path.read_text(encoding="utf-8", errors="ignore").split(" /// ")
            return len((partes[5] if len(partes) > 5 else "").strip())
        except Exception:
            return 0


    def _unique_dest(self, path: Path) -> Path:
        """
        Genera una ruta única si el archivo ya existe: foto.jpg → foto (1).jpg, etc.
        """
        if not path.exists():
            return path

        stem, ext = path.stem, path.suffix
        parent = path.parent
        i = 1
        while True:
            candidate = parent / f"{stem} ({i}){ext}"
            if not candidate.exists():
                return candidate
            i += 1

 

    def get_txts_for_page(self, numero: int) -> list[Path]:
        """
        Devuelve una lista de rutas a los archivos TXT de todas las noticias
        dentro de materiales/PXX/, por orden (02a.txt, 02b.txt...).
        """
        txts = []
        for d in self.get_noticia_dirs(numero):
            txt = d / f"{d.name}.txt"
            if txt.exists():
                txts.append(txt)
        return txts



    def find_material_image_for_page(self, numero: int) -> Optional[Path]:
        """
        Devuelve una imagen candidata para la página desde materiales/Pxx/ con esta prioridad:
        1) principal_XX.* (en carpeta raíz o subcarpetas)
        2) extraN_XX.*    (el primero en orden alfabético)
        3) cualquier *_XX.* (fallback relajado)
        4) cualquier imagen permitida (fallback final)

        Donde XX es el número de página con dos dígitos.
        Ahora también busca dentro de subcarpetas de noticias (02a, 02b, etc.).
        """
        src_dir = self.material / f"P{numero:02d}"
        if not src_dir.exists():
            return None

        try:
            # --- Incluir imágenes en raíz y en subcarpetas ---
            files = []
            for f in src_dir.iterdir():
                if f.is_file() and f.suffix.lower() in IMG_EXTS:
                    files.append(f)
                elif f.is_dir():
                    for subf in f.iterdir():
                        if subf.is_file() and subf.suffix.lower() in IMG_EXTS:
                            files.append(subf)
        except FileNotFoundError:
            return None

        if not files:
            return None

        # 1) principal_XX.*
        patron_principal = re.compile(rf"^principal[_\s-]*{numero:02d}\.", re.IGNORECASE)
        for f in files:
            if patron_principal.match(f.name):
                return f

        # 2) extraN_XX.* (tomamos el primero por orden alfabético)
        patron_extra = re.compile(rf"^extra\d*[_\s-]*{numero:02d}\.", re.IGNORECASE)
        extras = [f for f in files if patron_extra.match(f.name)]
        if extras:
            return sorted(extras)[0]

        # 3) fallback relajado: cualquier *_XX.*
        suf = f"_{numero:02d}".lower()
        for f in files:
            if f.stem.lower().endswith(suf):
                return f

        # 4) último recurso: la primera imagen válida
        return sorted(files)[0]

    # --- NUEVO: listar y renombrar imágenes en materiales/Pxx ---

    def list_material_images_for_page(self, numero: int) -> List[Path]:
        folder = self.material / f"P{numero:02d}"
        if not folder.exists():
            return []
        exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]

        def sort_key(p: Path):
            name = p.name.lower()

            # 1) "para la XX"
            if re.search(rf"para[\s_-]*la[\s_-]*0*{numero}\b", name):
                return (0, 0, name)

            # 2) principal_XX.*
            if re.match(rf"^principal[_\s-]*{numero:02d}\.", name):
                return (1, 0, name)

            # 3) extraN_XX.*
            m = re.match(rf"^extra(\d*)[_\s-]*{numero:02d}\.", name)
            if m:
                idx = int(m.group(1) or 0)
                return (2, idx, name)

            # 4) resto
            return (3, 0, name)

        return sorted(files, key=sort_key)


    def rename_material_image(self, numero: int, src: Path, nuevo_nombre: str, overwrite: bool = False) -> Path:
        """
        Renombra la imagen `src` con el nombre escrito por el usuario.
        - Mantiene extensión original.
        - Siempre agrega sufijo ' para la XX' (ej: 'ambulancia para la 07.jpg').
        - Si ya existe y overwrite=False → genera 'nombre (2).ext'.
        """
        if not src.exists():    
            raise FileServiceError(f"No existe el archivo:\n{src}")

        d = src.parent
        ext = src.suffix.lower()

        # Sanitizar y agregar sufijo obligatorio
        base = _sanitize_filename(nuevo_nombre)
        final_name = f"{base} para la {numero:02d}{ext}"
        dest = d / final_name

        if dest.exists() and not overwrite:
            dest = self._unique_dest(dest)

        _move_file(src, dest, overwrite=overwrite)
        return dest



    # ---------- Existencia por área ----------
    def existe_qxp(self, numero: int, carpeta: Path) -> bool:
        carpeta = Path(carpeta)
        if not carpeta.exists():
            return False
        try:
            for f in carpeta.iterdir():
                if not f.is_file() or f.suffix.lower() != ".qxp":
                    continue
                if self._match_qxp_number(f.stem, numero):
                    return True
        except OSError:
            return False
        return False


    def existe_pdf(self, numero: int, carpeta: Path) -> bool:
        carpeta = Path(carpeta)
        return any((carpeta / f"{numero:02}{ext}").exists() for ext in (".PDF", ".pdf"))

    # ---------- Verificaciones masivas ----------

    def _folder_mtimes(self, *carpetas: Path) -> dict[str, float]:
        """
        Devuelve {carpeta: mtime} solo de las carpetas que existen.
        Se usa para cachear snapshots evitando I/O redundante.
        """
        mtimes = {}
        for c in carpetas:
            try:
                if c and c.exists():
                    mtimes[str(c)] = c.stat().st_mtime
            except OSError:
                continue
        return mtimes



    def snapshot_qxp(self) -> dict[int, dict]:
        """
        Devuelve {n: {armado,fotocromia,corregido}} según presencia en:
        base/, base/final/, base/final/mandar/.
        Usa caché en memoria para evitar I/O redundante si no hubo cambios.
        """
        base = Path(self.rutas.get("quark_output_dir") or "")
        final = base / "final"
        mandar = final / "mandar"
        apdf = mandar / "a pdf"

        mtimes = self._folder_mtimes(base, final, mandar)

        # Si no cambió nada desde la última vez → devolvemos caché
        if self._cache_qxp["result"] is not None and mtimes == self._cache_qxp["mtimes"]:
            return self._cache_qxp["result"]

        _log.debug("snapshot_qxp (cache miss): base=%s | final=%s | mandar=%s | apdf=%s",
                   base, final, mandar, apdf)

        estados = {}
        if not base.exists():
            _log.debug("snapshot_qxp: carpeta base no existe (%s) — todo en False", base)
            estados = {i: {"armado": False, "fotocromia": False, "corregido": False, "apdf": False} for i in range(1, 17)}
        else:
            for i in range(1, 17):
                estado = {"armado": False, "fotocromia": False, "corregido": False, "apdf": False}
                if mandar.exists() and self.buscar_qxp_por_numero(mandar, i):
                    estado["corregido"] = True
                elif final.exists() and self.buscar_qxp_por_numero(final, i):
                    estado["fotocromia"] = True
                elif apdf.exists() and self.buscar_qxp_por_numero(apdf, i):
                    estado["apdf"] = True
                elif base.exists() and self.buscar_qxp_por_numero(base, i):
                    estado["armado"] = True
                estados[i] = estado

        # Guardar en caché
        self._cache_qxp = {"mtimes": mtimes, "result": estados}
        return estados

    def _pdf_exists(self, carpeta: Path, numero: int) -> bool:
        return any((carpeta / f"{numero:02}{ext}").exists() for ext in (".PDF", ".pdf"))

    def snapshot_pdf(self) -> dict[int, dict]:
        """
        Devuelve {n: {revisado, impreso}} según presencia en:
        pdf/ y pdf/OK/.
        Usa caché en memoria para evitar I/O redundante si no hubo cambios.
        """
        pdf = Path(self.rutas.get("pdf_output_dir") or "")
        ok = Path(self.rutas.get("pdf_ok_dir") or (pdf / "OK"))
        _ensure_dir(ok)

        mtimes = self._folder_mtimes(pdf, ok)

        # Si no cambió nada desde la última vez → devolvemos caché
        if self._cache_pdf["result"] is not None and mtimes == self._cache_pdf["mtimes"]:
            return self._cache_pdf["result"]

        estados = {}
        for i in range(1, 17):
            revisado = self._pdf_exists(pdf, i)
            impreso = self._pdf_exists(ok, i)
            estados[i] = {"revisado": revisado, "impreso": impreso}

        # Guardar en caché
        self._cache_pdf = {"mtimes": mtimes, "result": estados}
        return estados

    def clear_cache(self):
        """Fuerza el borrado de la caché de snapshots (QXP y PDF)."""
        self._cache_qxp = {"mtimes": {}, "result": None}
        self._cache_pdf = {"mtimes": {}, "result": None}
        
    # ---------- Decisión de mover / devolver (según perfil) ----------

    def _debe_mover_spread(self, numero: int, pareja: int, spread_path: Path) -> bool:
        """
        Decide si debe moverse el spread completo (True) o solo el archivo individual (False)
        según los estados del INI y la página seleccionada.
        """
        orden = {"proceso": 0, "base": 1, "final": 2, "mandar": 3, "ok": 4, "pdf": 4}
        e1 = self.read_page_entry(numero).get("estado", "").lower()
        e2 = self.read_page_entry(pareja).get("estado", "").lower()

        nivel1 = orden.get(e1, -1)
        nivel2 = orden.get(e2, -1)

        # Si alguno no tiene estado → mover solo la página seleccionada
        if nivel1 == -1 or nivel2 == -1:
            return False

        # Si son iguales → mover spread
        if nivel1 == nivel2:
            return True

        # Si la página seleccionada está en estado más alto → mover spread
        return nivel1 > nivel2

    
    def inferir_estado_por_destino(self, dest: Path) -> str:
        """
        Devuelve el estado según la carpeta destino. Comparación tolerante y robusta.
        """
        try:
            rutas = self.rutas or {}
            base_dir = Path(rutas.get("quark_output_dir") or "")
            final_dir = base_dir / "final"
            mandar_dir = final_dir / "mandar"
            personal_dir = Path(rutas.get("personal_folder") or "")
        except Exception:
            return ""

        try:
            dest = dest.resolve()
        except Exception:
            dest = Path(dest)

        def _is_in(child: Path, parent: Path) -> bool:
            """True si 'child' está dentro de 'parent' (o es igual)."""
            try:
                return parent and child and parent.resolve() in [child.resolve(), *child.resolve().parents]
            except Exception:
                return str(parent).lower() in str(child).lower()

        if _is_in(dest, mandar_dir):
            return "mandar"
        if _is_in(dest, final_dir):
            return "final"
        if _is_in(dest, base_dir):
            return "base"
        if _is_in(dest, personal_dir):
            return "proceso"

        # --- fallback por nombre ---
        nombre = str(dest).lower()
        if "mandar" in nombre: return "mandar"
        if "final" in nombre: return "final"
        if "base" in nombre: return "base"
        if "proceso" in nombre or "personal" in nombre: return "proceso"
        return ""



    # --- helpers de nombres QXP para mover archivos ---
    def _stem_es_pag(self, stem: str, numero: int) -> bool:
        """True si el nombre comienza con 'Pag NN' o 'Pág NN' (convención de Base)."""
        return bool(re.match(rf"^p(ag|ág)[\s_-]*0*{numero}\b", stem, re.IGNORECASE))

    def _stem_es_numerico(self, stem: str, numero: int) -> bool:
        """
        True si el nombre comienza por NN (no 'Pag ...') y contiene la página o spread que la incluya.
        """
        if re.match(rf"^0*{numero}\b", stem, re.IGNORECASE) is None:
            return False
        return numero in self._extract_qxp_pages(stem)

    def find_qxp_base_numerico(self, numero: int) -> Optional[Path]:
        """
        En Base, devuelve el QXP cuyo nombre arranca por 'NN' (no 'Pag ...').
        Prioriza exactos (solo la NN) sobre spreads que la incluyan.
        """
        base = Path(self.rutas.get("quark_output_dir") or "")
        if not base.exists():
            return None
        exact = None
        spread = None
        try:
            for f in sorted(base.iterdir(), key=lambda p: p.name.casefold()):
                if not f.is_file() or f.suffix.lower() not in (".qxp", ".pqx"):
                    continue
                stem = f.stem
                if self._stem_es_pag(stem, numero):
                    # En Base NO queremos los 'Pag NN' para avanzar
                    continue
                if self._stem_es_numerico(stem, numero):
                    pages = self._extract_qxp_pages(stem)
                    if len(pages) == 1:
                        exact = f
                        break
                    elif spread is None:
                        spread = f
        except OSError:
            return None
        return exact or spread


    def decidir_mover_y_devolver(self, numero: int):
        """
        Retorna:
        {
            "mover":    {"src": Path|None, "dest": Path|None, "label": str, "enabled": bool},
            "devolver": {"src": Path|None, "dest": Path|None, "label": str, "enabled": bool}
        }

        Sin renombrar archivos:
        - De Proceso a Base: copia el archivo 
        - De Base a Final/Mandar: mueve solo si es numérico 'NN.qxp' o spread 'NN y NN.qxp'
        - Si no cumple la convención, el botón se deshabilita con un aviso.
        - Si la página no tiene estado en el INI, no se permite mover nada.
        """
        p2 = f"{numero:02}"

        personal = Path(self.rutas.get("personal_folder") or "")
        base = Path(self.rutas.get("quark_output_dir") or "")
        final = base / "final"
        mandar = final / "mandar"
        pdf = Path(self.rutas.get("pdf_output_dir") or "")
        pdf_ok = Path(self.rutas.get("pdf_ok_dir") or (pdf / "OK"))

        mover    = {"src": None, "dest": None, "label": "Mover",    "enabled": False}
        devolver = {"src": None, "dest": None, "label": "Devolver", "enabled": False}

        # --- 0) Estado desde el INI ---
        try:
            entry = self.read_page_entry(numero)
            estado = (entry.get("estado") or "").strip().lower()
        except Exception:
            estado = ""

        if not estado:
            # Si la página no tiene estado asignado, bloqueamos todo
            return {
                "mover": {"src": None, "dest": None, "label": "Página no armada", "enabled": False},
                "devolver": {"src": None, "dest": None, "label": "Página no armada", "enabled": False},
            }

        # --- 1) PDFs (prioridad máxima) ---
        if self._pdf_exists(pdf, numero):
            for ext in (".PDF", ".pdf"):
                cand = pdf / f"{p2}{ext}"
                if cand.exists():
                    mover.update(src=cand, dest=pdf_ok / cand.name, label="Mover a\nOK", enabled=True)
                    break

        if self._pdf_exists(pdf_ok, numero):
            for ext in (".PDF", ".pdf"):
                cand_ok = pdf_ok / f"{p2}{ext}"
                if cand_ok.exists():
                    devolver.update(src=cand_ok, dest=pdf / cand_ok.name, label="Devolver a\nPDF", enabled=True)
                    break

        # Si hay PDF ya definido, devolvemos
        if mover["enabled"] or devolver["enabled"]:
            return {"mover": mover, "devolver": devolver}

        # --- 2) QXP (sin perfiles): cadena materiales → base → final → mandar → a pdf ---
        apdf_dir = mandar / "a pdf"
        qxp_apdf     = self.buscar_qxp_por_numero(apdf_dir, numero) if apdf_dir.exists() else None
        qxp_mandar   = self.buscar_qxp_por_numero(mandar, numero)   if mandar.exists()   else None
        qxp_final    = self.buscar_qxp_por_numero(final, numero)    if final.exists()    else None
        qxp_base_pag = self.buscar_qxp_por_numero(base, numero)     if base.exists()     else None
        qxp_base_num = self.find_qxp_base_numerico(numero)          if base.exists()     else None
        # Buscar en materiales/Pnn/ primero (migración JSON 2026-05-06), luego en personal
        qxp_personal = self.find_qxp_en_materiales(numero) or (
            self.buscar_qxp_por_numero(personal, numero) if personal and personal.exists() else None
        )

        # Matices: no permitir saltos no contiguos por spread (según estado del INI).
        if estado == "proceso":
            qxp_final = qxp_mandar = qxp_apdf = None
        elif estado == "base":
            qxp_mandar = qxp_apdf = None
        elif estado == "final":
            qxp_apdf = None

        mat_pnn_dir  = Path(self.rutas.get("material") or "") / f"P{numero:02d}"
        dest_proceso = mat_pnn_dir if mat_pnn_dir.exists() else personal

        # Un solo flujo: Mover avanza un paso, Devolver retrocede uno.
        if qxp_apdf:
            # En 'a pdf': solo retroceder a Mandar (el PDF lo genera un proceso aparte).
            devolver.update(src=qxp_apdf, dest=mandar / qxp_apdf.name,
                            label="Devolver a\nMandar", enabled=True)
        elif qxp_mandar:
            mover.update(src=qxp_mandar, dest=apdf_dir / qxp_mandar.name,
                         label="Mover a\nA PDF", enabled=True)
            devolver.update(src=qxp_mandar, dest=final / qxp_mandar.name,
                            label="Devolver a\nFinal", enabled=True)
        elif qxp_final:
            mover.update(src=qxp_final, dest=mandar / qxp_final.name,
                         label="Mover a\nMandar", enabled=True)
            devolver.update(src=qxp_final, dest=base / qxp_final.name,
                            label="Devolver a\nBase", enabled=True)
        elif qxp_base_num:
            # En base con nombre numérico 'NN.qxp': avanza a Final, retrocede a En proceso.
            mover.update(src=qxp_base_num, dest=final / qxp_base_num.name,
                         label="Mover a\nFinal", enabled=True)
            devolver.update(src=qxp_base_num, dest=dest_proceso / qxp_base_num.name,
                            label="Devolver a\nEn proceso", enabled=True)
        elif qxp_base_pag:
            # En base con nombre 'Pag NN': avanzar requiere renombrar a 'NN.qxp'; sí puede retroceder.
            devolver.update(src=qxp_base_pag, dest=dest_proceso / qxp_base_pag.name,
                            label="Devolver a\nEn proceso", enabled=True)
            mover.update(label="Renombrá a 'NN.qxp' para avanzar a Final", enabled=False)
        elif qxp_personal:
            stem = Path(qxp_personal).stem
            # Aceptar 'Pag NN ...' o 'NN...' en materiales/personal para COPIAR a Base.
            if self._stem_es_pag(stem, numero) or self._stem_es_numerico(stem, numero):
                mover.update(src=qxp_personal, dest=base / Path(qxp_personal).name,
                             label="Mover a\nBase", enabled=True)

        return {"mover": mover, "devolver": devolver}





    # ---------- Ejecutores ----------

    def _update_estado_by_dest(self, dest: Path, numeros: set[int]):
        """Detecta la carpeta destino y actualiza el campo 'estado' según ubicación."""
        if not dest or not numeros:
            return

        dest_str = str(dest).lower()
        if "/final/mandar" in dest_str or "\\final\\mandar" in dest_str:
            estado = "mandar"
        elif "/final" in dest_str or "\\final" in dest_str:
            estado = "final"
        elif "/ok" in dest_str or "\\ok" in dest_str:
            estado = "ok"
        elif "/pdf" in dest_str or "\\pdf" in dest_str:
            estado = "pdf"
        elif "/base" in dest_str or "\\base" in dest_str:
            estado = "base"
        else:
            mat_root_str = str(Path(self.rutas.get("material") or "")).lower().rstrip("/\\")
            if mat_root_str and (
                dest_str.startswith(mat_root_str + "/") or
                dest_str.startswith(mat_root_str + "\\")
            ):
                estado = "proceso"
            elif "/personal" in dest_str or "\\personal" in dest_str:
                estado = "proceso"
            else:
                return  # sin cambios

        for n in numeros:
            self.write_page_entry(n, estado=estado)


    def ejecutar_mover(self, src: Path, dest: Path):
        """
        Copia o mueve el archivo indicado y actualiza SOLO la(s) página(s) realmente afectadas.
        """
        personal = Path(self.rutas.get("personal_folder") or "")
        try:
            src_resolved = Path(src).resolve()
        except Exception:
            src_resolved = Path(src)

        # ---------------------------
        # BLOQUE CRÍTICO (MOVE/COPY)
        # ---------------------------

        try:
            # 1. PERSONAL o MATERIALES/Pnn → BASE = COPIAR (dejar el qxp en materiales)
            mat_root = Path(self.rutas.get("material") or "")

            def _under(root: Path, child: Path) -> bool:
                """True si child está dentro de root, tolerante a rutas mapeadas/UNC
                (compara formas resueltas y sin resolver: en discos de red .resolve()
                puede canonizar a UNC y no coincidir con la raíz mapeada)."""
                if not root or str(root) in ("", "."):
                    return False
                roots = {root}
                childs = {Path(child)}
                try:
                    roots.add(root.resolve())
                except Exception:
                    pass
                try:
                    childs.add(Path(child).resolve())
                except Exception:
                    pass
                for r in roots:
                    for c in childs:
                        try:
                            if r == c or r in c.parents:
                                return True
                        except Exception:
                            pass
                return False

            src_in_proceso = _under(mat_root, src) or _under(personal, src)
            if src_in_proceso:
                _copy_file(src, dest, overwrite=True)

            # 2. BASE → FINAL/MANDAR o FINAL → MANDAR = MOVER
            else:
                _move_file(src, dest, overwrite=True)

        except PermissionError as e:
            if hasattr(e, "winerror") and e.winerror == 32:
                return "locked"
            return False

        except Exception as e:
            _log.error("ejecutar_mover falló: %s", e)
            return False

        # --- Determinar nuevo estado por destino ---
        nuevo_estado = self.inferir_estado_por_destino(dest)
        if not nuevo_estado:
            return True  # la operación de mover/copiar fue exitosa aunque no cambie estado

        # --- Extraer páginas involucradas ---
        paginas = sorted(self._extract_qxp_pages(src.stem))
        if not paginas:
            return True

        # --- Caso spread (doble página) ---
        if len(paginas) == 2:
            n1, n2 = paginas
            spread_file = self.buscar_qxp_spread(n1, n2)
            if spread_file and spread_file.exists():
                numero_sel = n1 if re.search(rf"\b{n1:02d}\b", src.stem) else n2

                if self._debe_mover_spread(numero_sel, n2 if numero_sel == n1 else n1, spread_file):
                    self.write_page_entry(n1, estado=nuevo_estado)
                    self.write_page_entry(n2, estado=nuevo_estado)
                else:
                    self.write_page_entry(numero_sel, estado=nuevo_estado)
                return True

            # Spread no real: actualizar según nombre
            if re.search(rf"\b{n1:02d}\b", src.stem):
                self.write_page_entry(n1, estado=nuevo_estado)
            elif re.search(rf"\b{n2:02d}\b", src.stem):
                self.write_page_entry(n2, estado=nuevo_estado)
            return True

        # --- Caso individual ---
        if len(paginas) == 1:
            self.write_page_entry(paginas[0], estado=nuevo_estado)

        return True





    def ejecutar_devolver(self, src: Path, dest: Path):
        """
        Mueve el archivo indicado y actualiza el estado de las páginas afectadas.
        - Spread real → actualiza ambas si corresponde.
        - Archivo individual → actualiza solo esa página.
        - Nunca borra el estado de la pareja.
        """
        # ---------------------------
        # BLOQUE CRÍTICO (MOVE)
        # ---------------------------
        try:
            _move_file(src, dest, overwrite=True)

        except PermissionError as e:
            # Archivo abierto → WinError 32
            if hasattr(e, "winerror") and e.winerror == 32:
                return "locked"
            return False

        except Exception as e:
            _log.error("ejecutar_devolver falló: %s", e)
            return False

        nuevo_estado = self.inferir_estado_por_destino(dest)
        if not nuevo_estado:
            return True

        paginas = sorted(self._extract_qxp_pages(src.stem))
        if not paginas:
            return True

        # --- Caso spread (doble página) ---
        if len(paginas) == 2:
            n1, n2 = paginas
            spread_file = self.buscar_qxp_spread(n1, n2)

            if spread_file and spread_file.exists():
                # Inferir cuál página se está devolviendo (la que aparece en el nombre)
                numero_sel = n1 if re.search(rf"\b{n1:02d}\b", src.stem) else n2

                # Verificar si corresponde devolver spread o solo el archivo individual
                if self._debe_mover_spread(numero_sel, n2 if numero_sel == n1 else n1, spread_file):
                    # Spread completo → ambas páginas al nuevo estado
                    self.write_page_entry(n1, estado=nuevo_estado)
                    self.write_page_entry(n2, estado=nuevo_estado)
                else:
                    # Solo la seleccionada
                    self.write_page_entry(numero_sel, estado=nuevo_estado)

                return True

            # Si NO hay spread físico, actualizar solo la página que coincida
            if re.search(rf"\b{n1:02d}\b", src.stem):   
                self.write_page_entry(n1, estado=nuevo_estado)
            elif re.search(rf"\b{n2:02d}\b", src.stem):
                self.write_page_entry(n2, estado=nuevo_estado)

            return True

        # --- Caso individual ---
        if len(paginas) == 1:
            self.write_page_entry(paginas[0], estado=nuevo_estado)

        return True



    # ============================================================
    # 🔹 Copia de maqueta automática para página asignada
    # ============================================================

    def copiar_maqueta_para_pagina(self, numero: int) -> Optional[Path]:
        """
        Copia una maqueta .qxp desde maquetas/listas/ según tipo de aviso y sección.
        La deja en personal_folder como '{NN}.qxp' (ej: 14.qxp).
        Usa resolve_maqueta_name() para elegir la plantilla (sección → fallback genérica).
        """
        from services.maqueta_reader_service import resolve_maqueta_name, _get_maquetas_dir
        try:
            rutas = self.rutas or {}
            destino_root = Path(rutas.get("personal_folder") or "")
            if not destino_root.exists():
                _log.warning("No hay carpeta personal_folder definida.")
                return None

            entry = self.read_page_entry(numero)
            if not entry:
                _log.warning("No hay entrada INI para P%02d.", numero)
                return None

            base_maquetas = _get_maquetas_dir(rutas)

            # --- Tipo de aviso ---
            tipo = "vacia"
            if entry.get("aviso_full"):
                tipo = "completa"
            elif entry.get("aviso_footer"):
                tipo = "pie"
            elif entry.get("aviso_half"):
                tipo = "media"
            elif entry.get("aviso_robapagina"):
                tipo = "roba"

            seccion = (entry.get("seccion") or "").strip()

            nombre_maqueta = resolve_maqueta_name(tipo, seccion, base_maquetas)
            if not nombre_maqueta:
                _log.warning("P%02d: no se encontró plantilla para tipo='%s', seccion='%s'", numero, tipo, seccion)
                return None

            _log.info("P%02d: tipo='%s', sección='%s', maqueta='%s'", numero, tipo, seccion, nombre_maqueta)
            origen = base_maquetas / nombre_maqueta

            destino_root.mkdir(parents=True, exist_ok=True)
            destino = destino_root / f"{numero:02d}.qxp"
            if destino.exists():
                i = 1
                while True:
                    cand = destino_root / f"{numero:02d} ({i}).qxp"
                    if not cand.exists():
                        destino = cand
                        break
                    i += 1

            copy2(origen, destino)
            _log.info("Maqueta copiada para P%02d: %s → %s", numero, origen.name, destino.name)
            return destino

        except Exception as e:
            _log.error("copiar_maqueta_para_pagina falló: %s", e)
            return None

    def copiar_maqueta_a_materiales(self, numero: int, nombre_maqueta: str = "") -> Optional[Path]:
        """
        Lee la maqueta elegida del JSON de la primera nota de la página y copia
        esa plantilla a materiales/Pnn/{NN}.qxp.
        Si el JSON no tiene maqueta, usa vaciaGenerica.qxp como fallback.
        No escribe en el INI. (migración JSON 2026-05-06)
        """
        try:
            rutas = self.rutas or {}
            from services.maqueta_reader_service import _get_maquetas_dir
            base_maquetas = _get_maquetas_dir(rutas)
            base_material = Path(rutas.get("material") or "")
            if not base_material:
                _log.error("Ruta de materiales no configurada.")
                return None

            # Leer maqueta del JSON de la primera nota
            nombre_maqueta = ""
            txt_name_raw = (self.read_page_entry(numero).get("txt_name") or "").split(";")[0].strip()
            base_name = txt_name_raw.split(".")[0] if txt_name_raw else ""
            if base_name:
                json_path = base_material / f"P{numero:02d}" / base_name / f"{base_name}.json"
                if json_path.exists():
                    try:
                        data = json.loads(json_path.read_text(encoding="utf-8"))
                        nombre_maqueta = (data.get("maqueta") or "").strip()
                    except Exception:
                        pass

            if not nombre_maqueta:
                from services.maqueta_reader_service import resolve_maqueta_name
                entry = self.read_page_entry(numero)
                if entry.get("aviso_full"):
                    nombre_maqueta = "completa.qxp"
                else:
                    tipo = "vacia"
                    if entry.get("aviso_footer"):
                        tipo = "pie"
                    elif entry.get("aviso_half"):
                        tipo = "media"
                    elif entry.get("aviso_robapagina"):
                        tipo = "roba"
                    seccion = (entry.get("seccion") or "").strip()
                    nombre_maqueta = resolve_maqueta_name(tipo, seccion, base_maquetas) or f"{tipo}Generica.qxp"

            # P02: preferir la variante con sufijo "Dos" (ej. vaciaGenericaDos.qxp);
            # si no existe, queda el nombre original (fallback a {tipo}{Sufijo}.qxp).
            if numero == 2 and nombre_maqueta.lower().endswith(".qxp"):
                cand_dos = nombre_maqueta[:-4] + "Dos.qxp"
                if (base_maquetas / cand_dos).exists():
                    nombre_maqueta = cand_dos

            origen = base_maquetas / nombre_maqueta
            if not origen.exists():
                _log.info("Maqueta '%s' no encontrada, usando vaciaGenerica.qxp", nombre_maqueta)
                origen = base_maquetas / "vaciaGenerica.qxp"
                if not origen.exists():
                    _log.error("No se encontró vaciaGenerica.qxp en %s", base_maquetas)
                    return None

            dest_dir = base_material / f"P{numero:02d}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            destino = dest_dir / f"{numero:02d}.qxp"

            copy2(origen, destino)
            _log.info("Maqueta copiada a materiales para P%02d: %s → %s", numero, origen.name, destino.name)
            return destino

        except Exception as e:
            _log.error("copiar_maqueta_a_materiales falló: %s", e)
            return None

    def sincronizar_maqueta_pagina(self, numero: int) -> Optional[str]:
        """
        Determina la maqueta correcta de la página según el aviso del INI + sección
        (resolve_maqueta) y reescribe el campo "maqueta" de cada nota.json **solo si
        difiere**. Mantiene nota.json en sync con el aviso. Devuelve la maqueta resuelta.
        """
        try:
            from services.maqueta_reader_service import resolve_maqueta
            entry = self.read_page_entry(numero)
            resolved = resolve_maqueta(
                entry.get("aviso_full"), entry.get("aviso_half"),
                entry.get("aviso_footer"), entry.get("aviso_robapagina"),
                entry.get("seccion", ""), self.rutas,
            )
            if not resolved:
                return None
            for d in self.get_noticia_dirs(numero):
                jp = d / f"{d.name}.json"
                if not jp.exists():
                    continue
                try:
                    data = json.loads(jp.read_text(encoding="utf-8"))
                    if data.get("maqueta") != resolved:
                        data["maqueta"] = resolved
                        jp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                        _log.debug("maqueta sync P%02d %s → %s", numero, d.name, resolved)
                except Exception as e:
                    _log.warning("sincronizar_maqueta P%02d %s: %s", numero, d.name, e)
            return resolved
        except Exception as e:
            _log.warning("sincronizar_maqueta_pagina P%02d: %s", numero, e)
            return None

    def find_qxp_en_materiales(self, numero: int) -> Optional[Path]:
        """
        Busca {NN}.qxp dentro de materiales/Pnn/ por búsqueda en disco.
        No usa el INI. (migración JSON 2026-05-06)
        """
        try:
            base_material = Path(self.rutas.get("material") or "")
            if not base_material:
                return None
            qxp_path = base_material / f"P{numero:02d}" / f"{numero:02d}.qxp"
            return qxp_path if qxp_path.exists() else None
        except Exception:
            return None

    def eliminar_qxp_materiales(self, numero: int) -> None:
        qxp = self.find_qxp_en_materiales(numero)
        if not qxp:
            raise FileServiceError(f"No hay QXP en materiales para P{numero:02d}")
        try:
            _eliminar_definitivo(qxp)
        except Exception as e:
            raise FileServiceError(f"No se pudo eliminar el QXP:\n{qxp}", e)

    # ------------------------------------------------------------------
    # QXP: detección de lock + borrado en TODAS las ubicaciones
    # ------------------------------------------------------------------

    def _archivo_bloqueado(self, path) -> bool:
        """
        True si el archivo está abierto/bloqueado por otro proceso (p.ej. QuarkXPress).
        Usa un rename a temporal y vuelta (misma operación que necesita el borrado):
        si está bloqueado, os.replace lanza PermissionError (winerror 32/33/13).
        """
        p = Path(path)
        if not p.exists():
            return False
        tmp = p.with_name("~lock_" + p.name)
        try:
            os.replace(str(p), str(tmp))   # mover a temporal
            os.replace(str(tmp), str(p))   # devolver al lugar
            return False
        except OSError:
            # Cualquier fallo de rename (sharing/access) → tratarlo como bloqueado.
            # Best-effort: si quedó como temporal, intentar devolverlo.
            try:
                if tmp.exists() and not p.exists():
                    os.replace(str(tmp), str(p))
            except Exception:
                pass
            return True

    def listar_qxp_todas_ubicaciones(self, numero: int) -> list[Path]:
        """
        Devuelve todos los .qxp de la página 'numero' en cualquier ubicación:
        materiales/Pnn, proceso (personal_folder), base, final, mandar, a pdf.
        Sin duplicados (por ruta resuelta).
        """
        rutas = self.rutas or {}
        base   = Path(rutas.get("quark_output_dir") or "")
        final  = base / "final"
        mandar = final / "mandar"
        apdf   = mandar / "a pdf"
        personal = Path(rutas.get("personal_folder") or "")

        encontrados: list[Path] = []
        vistos: set = set()

        def _add(p: Optional[Path]):
            if not p:
                return
            try:
                key = p.resolve()
            except Exception:
                key = Path(str(p))
            if key in vistos:
                return
            vistos.add(key)
            encontrados.append(p)

        _add(self.find_qxp_en_materiales(numero))
        for carpeta in (personal, base, final, mandar, apdf):
            try:
                if carpeta and carpeta.exists():
                    _add(self.buscar_qxp_por_numero(carpeta, numero))
            except Exception:
                continue
        return encontrados

    def eliminar_qxp_todas_ubicaciones(self, numero: int) -> int:
        """
        Borra (a papelera) todos los .qxp de la página en cualquier ubicación.
        Si alguno está abierto en Quark → FileServiceError (no borra nada).
        Devuelve la cantidad de archivos borrados.
        """
        qxps = self.listar_qxp_todas_ubicaciones(numero)
        if not qxps:
            return 0
        # 1) Verificar locks ANTES de borrar nada (todo-o-nada).
        for q in qxps:
            if self._archivo_bloqueado(q):
                raise FileServiceError(
                    f"El archivo de Quark está abierto:\n{q}\n\n"
                    f"Cerralo en QuarkXPress e intentá de nuevo."
                )
        # 2) Borrar.
        borrados = 0
        for q in qxps:
            try:
                _eliminar_definitivo(q)
                borrados += 1
                _log.info("QXP descartado P%02d: %s", numero, q)
            except Exception as e:
                raise FileServiceError(f"No se pudo descartar el QXP:\n{q}", e)
        return borrados

    def eliminar_qxp_fuera_de_materiales(self, numero: int) -> int:
        """
        Borra (a papelera) los .qxp de la página que están FUERA de materiales
        (proceso, base, final, mandar, a pdf), dejando intacta la asignación
        (el qxp de materiales). Guard de archivo abierto (todo-o-nada).
        """
        mat = self.find_qxp_en_materiales(numero)
        mat_key = None
        if mat:
            try:
                mat_key = mat.resolve()
            except Exception:
                mat_key = Path(str(mat))
        objetivo = []
        for q in self.listar_qxp_todas_ubicaciones(numero):
            try:
                k = q.resolve()
            except Exception:
                k = Path(str(q))
            if mat_key is not None and k == mat_key:
                continue
            objetivo.append(q)
        if not objetivo:
            return 0
        for q in objetivo:
            if self._archivo_bloqueado(q):
                raise FileServiceError(
                    f"El archivo de Quark está abierto:\n{q}\n\n"
                    f"Cerralo en QuarkXPress e intentá de nuevo.")
        borrados = 0
        for q in objetivo:
            try:
                _eliminar_definitivo(q)
                borrados += 1
                _log.info("QXP descartado (fuera de materiales) P%02d: %s", numero, q)
            except Exception as e:
                raise FileServiceError(f"No se pudo descartar el QXP:\n{q}", e)
        return borrados

    # ==================================================================
    # ENROCAR PÁGINAS — intercambio de contenido entre dos páginas
    # ==================================================================

    _AVISO_FIELDS = {"aviso_full", "aviso_half", "aviso_footer", "aviso_robapagina", "aviso_nombre"}

    def enrocar_paginas(self, x: int, y: int, con_aviso: bool,
                        qxp_mode: str = "ninguno") -> None:
        """
        Intercambia el contenido de las páginas x e y.
        - Editorial (siempre): subcarpetas de notas + campos editoriales del INI.
        - con_aviso=True: además intercambia campos de aviso + el archivo de aviso.
        - qxp_mode: "ninguno" (no hay qxp), "eliminar" (borra los qxp), "enrocar"
          (intercambia los qxp renombrándolos al número de la otra página).
        """
        if x == y:
            raise FileServiceError("No se puede enrocar una página consigo misma.")
        material = Path(self.rutas.get("material") or "")
        if not material:
            raise FileServiceError("Ruta 'materiales' no configurada.")
        px = material / f"P{x:02d}"
        py = material / f"P{y:02d}"
        px.mkdir(parents=True, exist_ok=True)
        py.mkdir(parents=True, exist_ok=True)

        _log.info("Enrocar P%02d ↔ P%02d (con_aviso=%s, qxp_mode=%s)", x, y, con_aviso, qxp_mode)

        # 1) QXP (antes de tocar el material editorial)
        if qxp_mode == "eliminar":
            self.eliminar_qxp_todas_ubicaciones(x)
            self.eliminar_qxp_todas_ubicaciones(y)
        elif qxp_mode == "enrocar":
            self._enrocar_qxp(x, y)

        # 2) Subcarpetas de notas (a/b/c…) con renombrado de prefijo y rewrite de paths
        self._swap_note_dirs(px, py, x, y)

        # 3) Archivos de selección/stats al pie de la página (best-effort)
        self._swap_root_json(px, py, x, y, "stats_fotos.json")
        self._swap_root_json(px, py, x, y, "fotos_seleccionadas.json")

        # 4) Archivo de aviso (solo con_aviso)
        if con_aviso:
            self._swap_aviso_file(px, py, x, y)

        # 5) Campos del INI por página
        self._swap_ini_fields(x, y, con_aviso)

        self.clear_cache()
        _log.info("Enrocar P%02d ↔ P%02d completado.", x, y)

    # ── Helpers de enroque ────────────────────────────────────────────

    def _note_dirs_de(self, page_dir: Path, nn: int) -> list[Path]:
        if not page_dir.exists():
            return []
        return [d for d in sorted(page_dir.iterdir())
                if d.is_dir() and re.match(rf"^{nn:02d}[a-z]$", d.name)]

    def _mover_note_dir_renombrado(self, src_dir: Path, dest_page_dir: Path,
                                   old_num: int, new_num: int) -> None:
        """Mueve src_dir (ej. 15a) a dest_page_dir como 16a, renombrando archivos
        internos {old}{letra}.* → {new}{letra}.* y reescribiendo paths en .json."""
        letra = src_dir.name[-1]
        old_name = f"{old_num:02d}{letra}"
        new_name = f"{new_num:02d}{letra}"
        dest = dest_page_dir / new_name
        shutil.move(str(src_dir), str(dest))
        for f in list(dest.iterdir()):
            if f.is_file() and f.name.startswith(old_name + "."):
                f.rename(dest / (new_name + f.name[len(old_name):]))
        self._rewrite_page_paths_dir(dest, old_num, new_num)

    def _swap_note_dirs(self, px: Path, py: Path, x: int, y: int) -> None:
        x_dirs = self._note_dirs_de(px, x)
        y_dirs = self._note_dirs_de(py, y)
        tmp = px.parent / f"~enroque_{x:02d}_{y:02d}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            # X → temp (sin renombrar todavía)
            for d in x_dirs:
                shutil.move(str(d), str(tmp / d.name))
            # Y → X (renombrando y→x)
            for d in y_dirs:
                self._mover_note_dir_renombrado(d, px, y, x)
            # temp (X originales) → Y (renombrando x→y)
            for d in list(tmp.iterdir()):
                self._mover_note_dir_renombrado(d, py, x, y)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _fix_paths_obj(self, obj, old: int, new: int):
        a, b = f"P{old:02d}\\{old:02d}", f"P{new:02d}\\{new:02d}"
        c, d = f"P{old:02d}/{old:02d}", f"P{new:02d}/{new:02d}"
        def fix(s):
            return s.replace(a, b).replace(c, d) if isinstance(s, str) else s
        if isinstance(obj, dict):
            return {fix(k): self._fix_paths_obj(v, old, new) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._fix_paths_obj(v, old, new) for v in obj]
        return fix(obj)

    def _rewrite_one_json(self, jf: Path, old: int, new: int) -> None:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            return
        fixed = self._fix_paths_obj(data, old, new)
        if fixed != data:
            try:
                jf.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                _log.warning("No se pudo reescribir paths en %s: %s", jf, e)

    def _rewrite_page_paths_dir(self, dir_: Path, old: int, new: int) -> None:
        for jf in dir_.rglob("*.json"):
            self._rewrite_one_json(jf, old, new)

    def _swap_root_json(self, px: Path, py: Path, x: int, y: int, fname: str) -> None:
        fx, fy = px / fname, py / fname
        ex, ey = fx.exists(), fy.exists()
        if not ex and not ey:
            return
        tmp = px / (fname + ".enroquetmp")
        if ex:
            fx.rename(tmp)
        if ey:
            fy.rename(fx)
        if ex:
            tmp.rename(fy)
        # px/fname ahora tiene datos de Y → reescribir y→x; py/fname tiene X → x→y
        if (px / fname).exists():
            self._rewrite_one_json(px / fname, y, x)
        if (py / fname).exists():
            self._rewrite_one_json(py / fname, x, y)

    def _swap_aviso_file(self, px: Path, py: Path, x: int, y: int) -> None:
        av_x = self.find_aviso_image_for_page(x)
        av_y = self.find_aviso_image_for_page(y)
        mov_x = av_x if (av_x and av_x.exists()) else None
        mov_y = av_y if (av_y and av_y.exists()) else None
        tmp = None
        try:
            if mov_x:
                tmp = mov_x.with_name("~enroque_" + mov_x.name)
                shutil.move(str(mov_x), str(tmp))
            if mov_y:
                shutil.move(str(mov_y), str(px / mov_y.name))
            if mov_x and tmp:
                shutil.move(str(tmp), str(py / mov_x.name))
        except Exception as e:
            _log.warning("No se pudo enrocar archivo de aviso P%02d↔P%02d: %s", x, y, e)

    def _read_ini_section_raw(self, numero: int) -> dict:
        ini_path = self._page_ini_path(numero)
        sec = self._ini_section(numero)
        cfg = configparser.ConfigParser(interpolation=None)
        if ini_path.exists():
            try:
                cfg.read(ini_path, encoding="utf-8")
            except Exception:
                pass
        return dict(cfg[sec]) if sec in cfg else {}

    def _write_full_page_entry(self, numero: int, fields: dict) -> None:
        ini_path = self._page_ini_path(numero)
        sec = self._ini_section(numero)
        cfg = configparser.ConfigParser(interpolation=None)
        if ini_path.exists():
            try:
                cfg.read(ini_path, encoding="utf-8")
            except Exception:
                pass
        if sec not in cfg:
            cfg[sec] = {}
        s = cfg[sec]
        for k, v in fields.items():
            if isinstance(v, bool):
                s[k] = "true" if v else "false"
            else:
                s[k] = "" if v is None else str(v)
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        self._save_ini_atomic_to(ini_path, cfg)

    def _swap_ini_fields(self, x: int, y: int, con_aviso: bool) -> None:
        sx = self._read_ini_section_raw(x)
        sy = self._read_ini_section_raw(y)
        keys = set(sx) | set(sy) | set(DEFAULT_PAGE_FIELDS.keys())
        new_x, new_y = {}, {}
        for k in keys:
            vx = sx.get(k, DEFAULT_PAGE_FIELDS.get(k, ""))
            vy = sy.get(k, DEFAULT_PAGE_FIELDS.get(k, ""))
            if (k in self._AVISO_FIELDS) and not con_aviso:
                new_x[k], new_y[k] = vx, vy           # avisos quedan en su lugar
            else:
                new_x[k], new_y[k] = vy, vx           # se intercambian
        self._write_full_page_entry(x, new_x)
        self._write_full_page_entry(y, new_y)

    def _qxp_renombrado(self, path: Path, old: int, new: int) -> Path:
        nuevo_stem = re.sub(rf"(?<!\d)0*{old}(?!\d)", f"{new:02d}", path.stem, count=1)
        return path.with_name(nuevo_stem + path.suffix)

    def _enrocar_qxp(self, x: int, y: int) -> None:
        qx = self.listar_qxp_todas_ubicaciones(x)
        qy = self.listar_qxp_todas_ubicaciones(y)
        for q in qx + qy:
            if self._archivo_bloqueado(q):
                raise FileServiceError(
                    f"El archivo de Quark está abierto:\n{q}\n\nCerralo en QuarkXPress.")
        # Fase 1: renombrar todos los orígenes a temporales (misma carpeta)
        fase: list[tuple[Path, Path]] = []
        for q in qx:
            tmp = q.with_name("~enroque_" + q.name)
            q.rename(tmp)
            fase.append((tmp, self._qxp_renombrado(q, x, y)))
        for q in qy:
            tmp = q.with_name("~enroque_" + q.name)
            q.rename(tmp)
            fase.append((tmp, self._qxp_renombrado(q, y, x)))
        # Fase 2: mover los temporales a su destino renombrado
        for tmp, dest in fase:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.rename(dest)
            _log.info("QXP enrocado: %s → %s", tmp.name, dest.name)


