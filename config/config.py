from pathlib import Path
import sys, os, re, unicodedata, json
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

    # ----------------------------------------------------------
    # API key de IA — guardada en el vault del SO (Windows Credential
    # Manager vía keyring), NUNCA en texto plano en config.ini.
    # ----------------------------------------------------------
    KEYRING_SERVICE = "ArmadorHuarpe"
    KEYRING_USER = "openai_api_key"

    @property
    def openai_api_key(self) -> str:
        """Devuelve la API key de OpenAI desde el vault del SO.
        Migración transparente: si no hay valor en el vault pero sí en el
        viejo [IA] api_key de config.ini, lo mueve al vault y lo borra del ini."""
        try:
            import keyring
            key = keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_USER)
            if key:
                return key
        except Exception:
            key = None

        # Migración desde config.ini (una sola vez)
        legacy = self.config.get("IA", "api_key", fallback="")
        if legacy:
            try:
                import keyring
                keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USER, legacy)
                self._borrar_api_key_ini()
                return legacy
            except Exception:
                # keyring no disponible: seguir sirviendo el valor legacy
                return legacy
        return ""

    def save_openai_api_key(self, key: str) -> None:
        """Guarda (o borra si viene vacía) la API key en el vault del SO."""
        import keyring
        key = (key or "").strip()
        if key:
            keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USER, key)
        else:
            try:
                keyring.delete_password(self.KEYRING_SERVICE, self.KEYRING_USER)
            except Exception:
                pass
        # Nunca dejar la key en texto plano en el ini
        self._borrar_api_key_ini()

    def _borrar_api_key_ini(self) -> None:
        """Elimina la clave api_key de la sección [IA] de config.ini si existe."""
        try:
            cfg = configparser.ConfigParser()
            cfg.read(self.CONFIG_FILE, encoding="utf-8")
            if cfg.has_option("IA", "api_key"):
                cfg.remove_option("IA", "api_key")
                with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                    cfg.write(f)
            # Reflejar en la copia en memoria
            if self.config.has_option("IA", "api_key"):
                self.config.remove_option("IA", "api_key")
        except Exception:
            pass

    @property
    def ia_model(self) -> str:
        """Modelo de OpenAI para la reescritura. Default gpt-4.1-mini."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        return cfg.get("IA", "model", fallback="gpt-4.1-mini").strip() or "gpt-4.1-mini"

    def save_ia_model(self, model: str) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "IA" not in cfg:
            cfg["IA"] = {}
        cfg["IA"]["model"] = (model or "gpt-4.1-mini").strip()
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def ia_auto_enabled(self) -> bool:
        """Si True, la reescritura completa por IA corre automáticamente al
        guardar/importar una nota."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        return cfg.getboolean("IA", "auto_enabled", fallback=False)

    def save_ia_auto_enabled(self, enabled: bool) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "IA" not in cfg:
            cfg["IA"] = {}
        cfg["IA"]["auto_enabled"] = "true" if enabled else "false"
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

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
            # Cuerpo de la principal cuando la página lleva DOS noticias: la principal ocupa
            # una caja más chica (la 2ª noticia toma parte del box). Vacío → usa cuerpo_limit
            # (retrocompatible). Calibrable por maqueta en [MAQUETA:<nombre>].
            "cuerpo_principal_dobles_limit": "",
            # Noticia secundaria (breve): cuerpo según maqueta con pie / vacía y
            # titulador de una sola línea contando sin espacios.
            "cuerpo_secundaria_pie_limit":   "630",
            "cuerpo_secundaria_vacia_limit": "1050",
            "titulo_breve_lineas":           "1",
            "titulo_breve_chars":            "44",
            "bajada_limit":             "220",
            "epigrafe_principal_limit": "120",
            "cuerpo_warning_margin":    "50",
            "intertitulo_deduccion":    "35",
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
            "foto_4col_deduccion":      "1600",  # costo unificado (incluye epígrafe más grande)
            "sin_foto_bonus":           "945",   # chars liberados sin foto (foto 2 col + epígrafe)
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

    @property
    def secciones_textuales(self) -> list:
        """Secciones ESPECIALES cuyos textuales se extraen del bloque 'Textuales' de la nota
        (hoy Café de la Política). Nombres tal cual los escribe el usuario (display)."""
        cfg = configparser.ConfigParser()
        if not cfg.read(self.CONFIG_FILE, encoding="utf-8-sig"):
            cfg.read(self.CONFIG_FILE, encoding="cp1252")
        raw = cfg.get("SECCIONES", "secciones_textuales", fallback="")
        items = [s.strip() for s in raw.split(",") if s.strip()]
        return [self._fix_mojibake(s) for s in items]

    def save_secciones_textuales(self, lista: list) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8-sig")
        if "SECCIONES" not in cfg:
            cfg["SECCIONES"] = {}
        cfg["SECCIONES"]["secciones_textuales"] = ", ".join(lista)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def secciones_textuales_deduccion(self) -> dict:
        """{seccion_normalizada: {"base": int, "umbral": int}} — cuánto descuentan del
        cupo del cuerpo los textuales de cada sección especial (ver es_seccion_textual/
        _secciones_textuales_norm en controller.py para la normalización)."""
        cfg = configparser.ConfigParser()
        if not cfg.read(self.CONFIG_FILE, encoding="utf-8-sig"):
            cfg.read(self.CONFIG_FILE, encoding="cp1252")
        raw = cfg.get("SECCIONES", "secciones_textuales_deduccion", fallback="{}")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def save_secciones_textuales_deduccion(self, data: dict) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8-sig")
        if "SECCIONES" not in cfg:
            cfg["SECCIONES"] = {}
        cfg["SECCIONES"]["secciones_textuales_deduccion"] = json.dumps(data, ensure_ascii=False)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def qr_overlay_pos(self):
        """(x, y) guardado de la columna de íconos del overlay QR, o None."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        try:
            return (cfg.getint("GENERAL", "qr_overlay_x"),
                    cfg.getint("GENERAL", "qr_overlay_y"))
        except Exception:
            return None

    def save_qr_overlay_pos(self, x: int, y: int) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "GENERAL" not in cfg:
            cfg["GENERAL"] = {}
        cfg["GENERAL"]["qr_overlay_x"] = str(int(x))
        cfg["GENERAL"]["qr_overlay_y"] = str(int(y))
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def maqueta_overlay_size(self):
        """(w, h) guardado del widget de maqueta del overlay de pegado, o None."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        try:
            return (cfg.getint("GENERAL", "maqueta_overlay_w"),
                    cfg.getint("GENERAL", "maqueta_overlay_h"))
        except Exception:
            return None

    def save_maqueta_overlay_size(self, w: int, h: int) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "GENERAL" not in cfg:
            cfg["GENERAL"] = {}
        cfg["GENERAL"]["maqueta_overlay_w"] = str(int(w))
        cfg["GENERAL"]["maqueta_overlay_h"] = str(int(h))
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    # ----------------------------------------------------------
    # Modo automático (armado autónomo en Quark)
    # ----------------------------------------------------------
    @property
    def auto_mode_enabled(self) -> bool:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        return cfg.getboolean("AUTO", "enabled", fallback=False)

    def save_auto_mode_enabled(self, enabled: bool) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        cfg["AUTO"]["enabled"] = "true" if enabled else "false"
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def auto_coord(self, clave: str):
        """(x, y) calibrada de un clickable del palette JS (p.ej. 'play', 'script'), o None."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        try:
            return (cfg.getint("AUTO", f"{clave}_x"), cfg.getint("AUTO", f"{clave}_y"))
        except Exception:
            return None

    def save_auto_coord(self, clave: str, x: int, y: int) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        cfg["AUTO"][f"{clave}_x"] = str(int(x))
        cfg["AUTO"][f"{clave}_y"] = str(int(y))
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def auto_mode_simular(self) -> bool:
        """Si True, el Armado automático corre en simulación (loguea, no toca mouse/teclado)."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        return cfg.getboolean("AUTO", "simular", fallback=False)

    def save_auto_mode_simular(self, valor: bool) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        cfg["AUTO"]["simular"] = "true" if valor else "false"
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def pdf_export_modo(self) -> str:
        """'bot' (pyautogui, default) o 'script' (ExportarPDF.js) — modo del bot de export a PDF."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        valor = cfg.get("AUTO", "pdf_export_modo", fallback="bot").strip().lower()
        return valor if valor in ("bot", "script") else "bot"

    def save_pdf_export_modo(self, valor: str) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        cfg["AUTO"]["pdf_export_modo"] = valor if valor in ("bot", "script") else "bot"
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    # Opciones válidas de espera (segundos) antes de lanzar el armado automático.
    AUTO_DELAY_OPCIONES = (5, 10, 15, 20)

    @property
    def auto_delay_segundos(self) -> int:
        """Segundos de cuenta regresiva (diálogo cancelable) antes de que el bot tome
        el control del mouse/teclado. Acotado a AUTO_DELAY_OPCIONES; default 5."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        val = cfg.getint("AUTO", "delay_segundos", fallback=5)
        return val if val in self.AUTO_DELAY_OPCIONES else 5

    def save_auto_delay_segundos(self, segundos: int) -> None:
        try:
            segundos = int(segundos)
        except Exception:
            segundos = 5
        if segundos not in self.AUTO_DELAY_OPCIONES:
            segundos = 5
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        cfg["AUTO"]["delay_segundos"] = str(segundos)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def auto_especiales(self) -> list:
        """Secciones con maqueta especial (calibración propia). Lista normalizada."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        raw = cfg.get("AUTO", "especiales", fallback="")
        return [s.strip().lower() for s in raw.split(",") if s.strip()]

    def save_auto_especiales(self, secciones: list) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        limpio = sorted({(s or "").strip().lower() for s in secciones if (s or "").strip()})
        cfg["AUTO"]["especiales"] = ",".join(limpio)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def auto_excluidas(self) -> list:
        """Secciones que el Armado automático NO arma (las saltea). Lista normalizada."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        raw = cfg.get("AUTO", "excluidas", fallback="")
        return [s.strip().lower() for s in raw.split(",") if s.strip()]

    def save_auto_excluidas(self, secciones: list) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        limpio = sorted({(s or "").strip().lower() for s in secciones if (s or "").strip()})
        cfg["AUTO"]["excluidas"] = ",".join(limpio)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def perfil_colores(self) -> str:
        """Perfil de colores de estado de la grilla: 'armado' | 'maquetacion' | 'editor'."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        val = cfg.get("UI", "perfil_colores", fallback="editor").strip().lower()
        return val if val in ("armado", "maquetacion", "editor") else "editor"

    def save_perfil_colores(self, valor: str) -> None:
        valor = (valor or "editor").strip().lower()
        if valor not in ("armado", "maquetacion", "editor"):
            valor = "editor"
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "UI" not in cfg:
            cfg["UI"] = {}
        cfg["UI"]["perfil_colores"] = valor
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def auto_area(self, clave: str):
        """(x, y, w, h) calibrada de un recurso del Armado automático, o None.
        Se guarda como {clave}_x/_y/_w/_h en [AUTO]."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        try:
            return (cfg.getint("AUTO", f"{clave}_x"),
                    cfg.getint("AUTO", f"{clave}_y"),
                    cfg.getint("AUTO", f"{clave}_w"),
                    cfg.getint("AUTO", f"{clave}_h"))
        except Exception:
            return None

    def save_auto_area(self, clave: str, x: int, y: int, w: int, h: int) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        cfg["AUTO"][f"{clave}_x"] = str(int(x))
        cfg["AUTO"][f"{clave}_y"] = str(int(y))
        cfg["AUTO"][f"{clave}_w"] = str(int(w))
        cfg["AUTO"][f"{clave}_h"] = str(int(h))
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def auto_valor(self, clave: str):
        """Valor numérico (string mm, p. ej. '129,574') que el bot escribe en el panel de medidas,
        o None si no está calibrado. Se guarda como {clave}_valor en [AUTO]."""
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        v = cfg.get("AUTO", f"{clave}_valor", fallback=None)
        return v.strip() if isinstance(v, str) and v.strip() else None

    def save_auto_valor(self, clave: str, valor: str) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(self.CONFIG_FILE, encoding="utf-8")
        if "AUTO" not in cfg:
            cfg["AUTO"] = {}
        cfg["AUTO"][f"{clave}_valor"] = str(valor if valor is not None else "").strip()
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def auto_centro(self, clave: str):
        """Centro (x, y) del área calibrada `clave`, o None. Útil para clics."""
        a = self.auto_area(clave)
        if not a:
            return None
        x, y, w, h = a
        return (int(x + w / 2), int(y + h / 2))

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
