# ================================================================
# model/rutas.py — versión corregida SMB-safe
# ---------------------------------------------------------------
# • Corrige WinError 5 causado por llamadas redundantes a mkdir()
#   en rutas UNC (\\servidor\...).
# • Crea la estructura base de carpetas de manera segura y atómica.
# • Mantiene compatibilidad con el resto del sistema Armador Huarpe.
# ================================================================

from pathlib import Path
import configparser
import os
import re
import datetime
import unicodedata

from config.config import Config
CONFIG_PATH = Config.CONFIG_FILE


class RutasEstado:
    def __init__(self):
        self.personal_root: Path | None = None
        self.base_root: Path | None = None
        self.pdf_root: Path | None = None

        self.personal_folder: Path | None = None
        self.quark_output_dir: Path | None = None
        self.pdf_output_dir: Path | None = None
        self.pdf_ok_dir: Path | None = None
        self.shared_ini_path: Path | None = None

        self.avisos_root: Path | None = None
        self.avisos2_root: Path | None = None
        self.fecha_edicion: datetime.date | None = None
        self.pool_root: Path | None = None
        self.maquetas_root: Path | None = None


    # -------- Persistencia --------
    def _read_cfg(self):
        cfg = configparser.ConfigParser()
        if CONFIG_PATH.exists():
            cfg.read(str(CONFIG_PATH), encoding="utf-8")
        return cfg

    def try_load(self) -> bool:
        """Carga sin preguntar. Devuelve True si las 3 raíces están presentes."""
        cfg = self._read_cfg()
        rutas = cfg.setdefault("RUTAS", {})
        pr = rutas.get("carpeta_personal")
        br = rutas.get("carpeta_base")
        pdr = rutas.get("carpeta_pdf")
        ar = rutas.get("carpeta_avisos")
        ar2 = rutas.get("carpeta_avisos2")
        po = rutas.get("carpeta_pool")

        if pr:
            self.personal_root = Path(pr)
        if br:
            self.base_root = Path(br)
        if pdr:
            self.pdf_root = Path(pdr)
        if ar:
            self.avisos_root = Path(ar)
        if ar2:
            self.avisos2_root = Path(ar2)
        if po:
            self.pool_root = Path(po)
        mq = rutas.get("carpeta_maquetas")
        if mq:
            self.maquetas_root = Path(mq)

        return bool((self.personal_root or self.avisos_root)
                    and self.base_root and self.pdf_root)

    # --- Utilidades de normalización/match tolerante ---
    @staticmethod
    def _norm(s: str) -> str:
        if not s:
            return ""
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = s.casefold()
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    @staticmethod
    def _month_names():
        return [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]

    @staticmethod
    def _weekday_names():
        return ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

    def _iter_dir(self, p: Path):
        try:
            for x in p.iterdir():
                yield x
        except Exception:
            return

    # -------- Selección y guardado de raíces --------
    def ensure_roots(self, prompt_fn, perfil: str | None = None):
        cfg = self._read_cfg()
        rutas = cfg.setdefault("RUTAS", {})

        def ensure(key: str, title: str, pedir: bool = True):
            """
            - Siempre carga desde INI si existe.
            - Solo llama a prompt_fn si pedir=True y no está en INI.
            """
            val = rutas.get(key)
            if val:
                setattr(self, key.replace("carpeta_", "") + "_root", Path(val))
            elif pedir:
                p = prompt_fn(key, title)
                if not p:
                    raise RuntimeError(f"No se seleccionó {title}")
                rutas[key] = str(p)
                setattr(self, key.replace("carpeta_", "") + "_root", Path(p))
            else:
                setattr(self, key.replace("carpeta_", "") + "_root", None)

        # Estas siempre se piden/cargan
        ensure("carpeta_base", "Seleccionar raíz Z:/PAPEL (BASE)")
        ensure("carpeta_pdf", "Seleccionar raíz Z:/PAPEL/IMPRENTA TEMPORAL (PDF)")
        


        # Avisos (perfil Maquetación)
        pedir_avisos = (perfil == "Maquetación y avisos")
        ensure("carpeta_avisos", "Seleccionar raíz de la carpeta de avisos (Comercial)", pedir=pedir_avisos)
        ensure("carpeta_avisos2", "Seleccionar raíz de la segunda carpeta de avisos (Diseño)", pedir=pedir_avisos)

        # Personal solo si perfil = Armado y corrección
        ensure("carpeta_personal", "Seleccionar raíz de la carpeta En proceso",
               pedir=(perfil == "Armado y corrección"))

        ensure("carpeta_pool", "Seleccionar carpeta Pool de noticias", pedir=True)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)

    # -------- Buscar carpeta de avisos de mañana --------
    def resolve_avisos_maniana(self) -> Path | None:
        if not self.avisos_root or not self.avisos_root.exists():
            return None

        man = datetime.date.today() + datetime.timedelta(days=1)
        year = man.year
        mes_idx = man.month - 1
        dia = man.day

        meses = self._month_names()
        diasem = self._weekday_names()[man.weekday()]
        mes_castellano = meses[mes_idx]
        mes_castellano_norm = self._norm(mes_castellano)
        diasem_norm = self._norm(diasem)

        # 1) Buscar carpeta "Avisos YYYY"
        year_dir = None
        target_norm = self._norm(f"avisos {year}")
        for child in self._iter_dir(self.avisos_root):
            if not child.is_dir():
                continue
            name_norm = self._norm(child.name)
            if target_norm in name_norm or (str(year) in name_norm and "aviso" in name_norm):
                year_dir = child
                break
        if not year_dir:
            return None

        # 2) Buscar carpeta del mes
        mes_dir = None
        for child in self._iter_dir(year_dir):
            if not child.is_dir():
                continue
            if self._norm(child.name) == mes_castellano_norm:
                mes_dir = child
                break
        if not mes_dir:
            return None

        # 3) Buscar carpeta del día ("Martes 22 de septiembre")
        dia_dir = None
        parts_required = [diasem_norm, str(dia), mes_castellano_norm]
        for child in self._iter_dir(mes_dir):
            if not child.is_dir():
                continue
            n = self._norm(child.name)
            if all(p in n for p in parts_required):
                dia_dir = child
                break

        return dia_dir

    # -------- Crear base de mañana (corregido) --------
    def crear_base_maniana(self):
        hoy = datetime.date.today()
        man = hoy + datetime.timedelta(days=1)
        self.fecha_edicion = man
        dias = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
        meses = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                 "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
        dia_sem = dias[man.weekday()]
        mes_str = meses[man.month - 1]

        # 1) Detectar o nombrar carpeta de edición base
        pattern = rf"EDICIÓN Nº \d+ {dia_sem} {man.day} DE {mes_str} DE {man.year}"
        base_dir = None
        for d in self.base_root.iterdir():
            if d.is_dir() and re.fullmatch(pattern, d.name):
                base_dir = d
                break
        if base_dir is None:
            eds = []
            for d in self.base_root.iterdir():
                m = re.match(r'EDICIÓN Nº (\d+)', d.name)
                if m:
                    eds.append(int(m.group(1)))
            next_ed = (max(eds) + 1) if eds else 1
            nombre = f"EDICIÓN Nº {next_ed} {dia_sem} {man.day} DE {mes_str} DE {man.year}"
            base_dir = self.base_root / nombre

            # --- Crear estructura sin llamadas redundantes (SMB-safe) ---
            for subpath in [
                "final/mandar/a pdf",
                "fue",
                "materiales"
            ]:
                (base_dir / subpath).mkdir(parents=True, exist_ok=True)

            # --- Crear carpetas P01–P16 dentro de /materiales ---
            materiales_dir = base_dir / "materiales"
            # ====================================================
            # 🔹 Crear los 16 INI individuales Pnn.ini con todas
            #    las claves por defecto (vacías/false)
            # ====================================================
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
                "mono_extra": "",
                "by": "",
                "ts": "",
                "link": "",
                "seccion": "",
                "estado": "",
                "maqueta": "",
            }

            for n in range(1, 17):
                carpeta_pagina = materiales_dir / f"P{n:02d}"
                carpeta_pagina.mkdir(parents=True, exist_ok=True)

                ini_path = carpeta_pagina / f"P{n:02d}.ini"
                cfg = configparser.ConfigParser(interpolation=None)

                sec = f"page_{n:02d}"
                cfg[sec] = DEFAULT_PAGE_FIELDS.copy()

                with open(ini_path, "w", encoding="utf-8") as f:
                    cfg.write(f)



        # 2) PDF día (en pdf_root/MES/DIA-MES) + OK
        pdf_day = self.pdf_root / mes_str / f"{man.day}-{man.month}"
        pdf_day.mkdir(parents=True, exist_ok=True)
        (pdf_day / "OK").mkdir(exist_ok=True)

        # 3) Personal “En proceso”: {mes} {MesNombre}/{dia-mes}
        mes_folder = None
        for d in self.personal_root.iterdir():
            if d.is_dir() and mes_str.lower() in d.name.lower():
                mes_folder = d
                break
        if mes_folder is None:
            mes_folder = self.personal_root / f"{man.month} {mes_str.capitalize()}"
        mes_folder.mkdir(parents=True, exist_ok=True)
        personal_day = mes_folder / f"{man.day}-{man.month}"
        personal_day.mkdir(exist_ok=True)

        # 4) Actualizar rutas operativas internas
        self.quark_output_dir = base_dir
        self.pdf_output_dir = pdf_day
        self.pdf_ok_dir = pdf_day / "OK"
        self.personal_folder = personal_day

        # 5) INI compartido de páginas
        #self.shared_ini_path = base_dir / "estado_pages.ini"
        #if not self.shared_ini_path.exists():
        #    cfg = configparser.ConfigParser()
        #    for i in range(1, 17):
        #        sec = f"page_{i:02d}"
        #        cfg[sec] = {
        #            "assigned": "false",
        #            "txt_name": "",
        #            "aviso_full": "false",
        #            "aviso_half": "false",
        #            "aviso_footer": "false",
        #            "by": "",
        #            "ts": ""
        #        }
        #    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        #    with open(self.shared_ini_path, "w", encoding="utf-8") as f:
        #        cfg.write(f)

        # 6) Devolver rutas útiles para la UI
        return {
            "base_dir": base_dir,
            "pdf_day": pdf_day,
            "personal_day": personal_day
        }

    def pool_day_folder(self) -> Path | None:
        """
        Devuelve la carpeta del día dentro de POOL, creando DD-MM-YYYY si no existe.
        """
        if not self.pool_root:
            return None

        hoy = datetime.date.today()
        nombre = hoy.strftime("%d-%m-%Y")

        d = self.pool_root / nombre
        d.mkdir(parents=True, exist_ok=True)
        return d
