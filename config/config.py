from pathlib import Path
import sys, os, re, unicodedata
import configparser

class Config:
    # Dónde viven los binarios/recursos del bundle (scripts, iconos, etc.)
    if getattr(sys, "frozen", False):
        APP_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        APP_DIR = Path(__file__).resolve().parent.parent

    # Dónde viven los datos mutables del usuario (config.ini, material, caches, etc.)
    if getattr(sys, "frozen", False):
        _roaming = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        DATA_DIR = _roaming / "ArmadorHuarpe"
    else:
        DATA_DIR = APP_DIR / "_devdata"

    # Rutas derivadas
    CONFIG_DIR  = DATA_DIR
    CONFIG_FILE = CONFIG_DIR / "config.ini"
    MATERIAL_DIR = DATA_DIR / "material"
    SCRIPTS_DIR  = APP_DIR / "scripts"

    RUNTIME_SCRIPTS_DIR = DATA_DIR / "scripts"
    RUNTIME_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    MANAGER_BASE_URL = "https://manager.diariohuarpe.com"
    POOL_ROOT = "pool_root"

    def __init__(self):
        # Cargar config.ini
        self.config = configparser.ConfigParser()
        self.config.read(self.CONFIG_FILE, encoding="utf-8")

    @property
    def manager_debugger_address(self):
        return self.config.get("MANAGER", "debugger_address", fallback=None)

    @property
    def chrome_profile_dir(self):
        return self.config.get("MANAGER", "chrome_profile_dir", fallback=None)

    @property
    def openai_api_key(self):
        return self.config.get("IA", "api_key", fallback="")

    @property
    def maqueta_config(self) -> dict:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        section = dict(cfg["MAQUETA"]) if "MAQUETA" in cfg else {}
        defaults = {
            # Capacidad de campos de texto
            "cuerpo_limit":             "4840",
            "volanta_limit":            "90",
            "titulo_lineas":            "2",
            "titulo_chars_linea":       "38",
            "bajada_limit":             "220",
            "epigrafe_principal_limit": "120",
            "cuerpo_warning_margin":    "50",
            # Límites de recursos
            "textual_sin_foto_limit":   "220",
            "textual_con_foto_limit":   "320",
            "textual_epigrafe_limit":   "90",
            "dato_limit":               "120",
            "editor_font_size":         "13",
            "cuerpo_font_size":         "16",
            "volanta_font_size":        "16",
            "bajada_font_size":         "16",
            "epigrafe_font_size":       "16",
            "titulo_font_size":         "16",
            "counter_font_size":        "11",
            # Visualización del cuerpo (tema de lectura — no afecta lo guardado)
            "cuerpo_font_family":       "Cambria",
            "cuerpo_text_color":        "#2b2b2b",
            "cuerpo_bg_color":          "#f4efe4",
            "cuerpo_line_spacing":      "118",
            # Descuentos fijos al cuerpo
            "firma_deduccion":          "120",
            "qr_deduccion":             "170",
            "foto_3wide_deduccion":     "450",
            "foto_3ancha_deduccion":    "625",
            # Textuales — descuento base + penaliza a partir de N chars
            "textual_simple_base":        "400",
            "textual_simple_umbral":      "100",
            "textual_x2_base":            "675",
            "textual_x2_umbral":          "132",
            "textual_x3_base":            "1225",
            "textual_x3_umbral":          "130",
            "textual_con_foto_base":      "500",
            "textual_con_foto_umbral":    "110",
            "textual_con_foto_xl_base":   "740",
            "textual_con_foto_xl_umbral": "130",
            # Dato y Número — descuento base + penaliza a partir de N chars
            "dato_base":    "300",
            "dato_umbral":  "100",
            "numero_base":  "375",
            "numero_umbral":"100",
            # Cajas de imagen en Quark (nombre exacto del qx-box)
            "foto_box_principal": "Box369",
        }
        defaults.update({k: v for k, v in section.items() if k != "nombre"})

        def _coerce(v):
            try:
                return int(v)
            except (ValueError, TypeError):
                return str(v)

        return {k: _coerce(v) for k, v in defaults.items()}

    @staticmethod
    def _fix_mojibake(s: str) -> str:
        """Corrige texto UTF-8 leído como Latin-1 (patrón CafÃ© → Café)."""
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s

    @property
    def secciones(self) -> list:
        cfg = configparser.ConfigParser()
        # utf-8-sig maneja BOM; si falla prueba con cp1252 (Windows default)
        if not cfg.read(self.CONFIG_FILE, encoding="utf-8-sig"):
            cfg.read(self.CONFIG_FILE, encoding="cp1252")
        raw = cfg.get("SECCIONES", "secciones", fallback="")
        items = [s.strip() for s in raw.split(",") if s.strip()]
        return [self._fix_mojibake(s) for s in items]

    def save_secciones(self, lista: list) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8-sig")
        if "SECCIONES" not in cfg:
            cfg["SECCIONES"] = {}
        cfg["SECCIONES"]["secciones"] = ", ".join(lista)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def save_maqueta_config(self, data: dict):
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "MAQUETA" not in cfg:
            cfg["MAQUETA"] = {}
        for k, v in data.items():
            cfg["MAQUETA"][k] = str(v)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def maqueta_config_for(self, nombre: str) -> dict:
        """Config de límites para una maqueta concreta. Hereda del global [MAQUETA]
        y aplica los overrides de [MAQUETA:<nombre>] si existen."""
        base = self.maqueta_config           # defaults + [MAQUETA] global, ya coercionado
        if not nombre:
            return base
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        sec = f"MAQUETA:{nombre}"
        if cfg.has_section(sec):
            def _coerce(v):
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return str(v)
            for k, v in cfg[sec].items():
                base[k] = _coerce(v)
        return base

    def save_maqueta_config_for(self, nombre: str, data: dict) -> None:
        """Guarda los límites de UNA maqueta en [MAQUETA:<nombre>].
        Sin nombre, cae al global (compat)."""
        if not nombre:
            return self.save_maqueta_config(data)
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        sec = f"MAQUETA:{nombre}"
        if sec not in cfg:
            cfg[sec] = {}
        for k, v in data.items():
            cfg[sec][k] = str(v)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def export_maqueta_limits(self) -> dict:
        """Exporta los LÍMITES de maqueta realmente almacenados en config.ini para
        compartir entre estaciones: `[MAQUETA]` (excluyendo el tema de visualización
        local) → 'global', y cada `[MAQUETA:<nombre>]` → 'por_maqueta[nombre]'.
        Devuelve solo lo guardado (no los defaults)."""
        from services.shared_config_service import MAQUETA_LOCAL_KEYS
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        global_limits = {}
        if cfg.has_section("MAQUETA"):
            for k, v in cfg["MAQUETA"].items():
                if k not in MAQUETA_LOCAL_KEYS:
                    global_limits[k] = v
        por_maqueta = {}
        for sec in cfg.sections():
            if sec.startswith("MAQUETA:"):
                nombre = sec[len("MAQUETA:"):]
                por_maqueta[nombre] = {k: v for k, v in cfg[sec].items()}
        return {"global": global_limits, "por_maqueta": por_maqueta}

    def apply_maqueta_limits(self, data: dict) -> None:
        """Aplica los LÍMITES compartidos a config.ini en un único read-modify-write
        atómico. Preserva las claves locales de tema en `[MAQUETA]`; reescribe cada
        `[MAQUETA:<nombre>]` con los overrides compartidos."""
        from services.shared_config_service import MAQUETA_LOCAL_KEYS
        data = data or {}
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")

        global_limits = data.get("global") or {}
        if global_limits:
            if "MAQUETA" not in cfg:
                cfg["MAQUETA"] = {}
            # Solo límites; nunca tocar las claves locales de tema.
            for k, v in global_limits.items():
                if k not in MAQUETA_LOCAL_KEYS:
                    cfg["MAQUETA"][k] = str(v)

        por_maqueta = data.get("por_maqueta") or {}
        for nombre, limites in por_maqueta.items():
            sec = f"MAQUETA:{nombre}"
            if sec not in cfg:
                cfg[sec] = {}
            for k, v in (limites or {}).items():
                cfg[sec][k] = str(v)

        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def get_story_type(
        self, maqueta: str, seccion: str, story_count: int, story_index: int
    ) -> str:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        key = self._story_type_key(maqueta, seccion, story_count, story_index)
        return cfg.get("STORY_TYPES", key, fallback="")

    def save_story_type(
        self, maqueta: str, seccion: str, story_count: int, story_index: int,
        story_type: str
    ):
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "STORY_TYPES" not in cfg:
            cfg["STORY_TYPES"] = {}
        key = self._story_type_key(maqueta, seccion, story_count, story_index)
        cfg["STORY_TYPES"][key] = story_type
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @staticmethod
    def _story_type_key(
        maqueta: str, seccion: str, story_count: int, story_index: int
    ) -> str:
        def norm(s: str) -> str:
            s = unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()
            return re.sub(r"[^a-z0-9]+", "_", s).strip("_")
        return f"{norm(maqueta.replace('.qxp', ''))}_{norm(seccion)}_{story_count}_{story_index}"

# ----------------------------------------------------------
# Instancia GLOBAL accesible desde cualquier módulo del sistema
# ----------------------------------------------------------
config_global = Config()
