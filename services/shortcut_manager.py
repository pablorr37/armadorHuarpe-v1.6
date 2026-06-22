import configparser
from pathlib import Path
from config.config import Config


class ShortcutManager:
    """
    Gestiona la carga y guardado de atajos de teclado.
    Lee directamente desde config.ini (sección [SHORTCUTS]).
    No usa valores hardcodeados: todos los atajos provienen del config.
    """

    def __init__(self):
        self.cfg = configparser.ConfigParser()
        self.path = Path(Config.CONFIG_FILE)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists():
            self.cfg.read(self.path, encoding="utf-8")
        else:
            # Si no existe, crear archivo vacío con sección SHORTCUTS
            self.cfg.add_section("SHORTCUTS")
            with self.path.open("w", encoding="utf-8") as f:
                self.cfg.write(f)

        # Si el archivo existe pero no tiene sección SHORTCUTS, crearla
        if not self.cfg.has_section("SHORTCUTS"):
            self.cfg.add_section("SHORTCUTS")

        # Cargar todos los atajos desde el config
        self.shortcuts = self._load_shortcuts()

    # ------------------------------------------------------------
    # LECTURA
    # ------------------------------------------------------------
    def _load_shortcuts(self) -> dict:
        """Carga todos los atajos definidos en [SHORTCUTS]."""
        if not self.cfg.has_section("SHORTCUTS"):
            return {}
        return {k: v for k, v in self.cfg.items("SHORTCUTS")}

    def get(self, action_key: str) -> str:
        """Devuelve la combinación de teclas de una acción."""
        return self.shortcuts.get(action_key, "")

    def all(self) -> dict:
        """Devuelve todos los atajos actuales (clave → combinación)."""
        return dict(self.shortcuts)

    # ------------------------------------------------------------
    # ESCRITURA
    # ------------------------------------------------------------
    def save_shortcut(self, action_key: str, keyseq: str):
        """Guarda un solo atajo en el archivo config.ini."""
        if not self.cfg.has_section("SHORTCUTS"):
            self.cfg.add_section("SHORTCUTS")

        self.cfg.set("SHORTCUTS", action_key, keyseq)
        with self.path.open("w", encoding="utf-8") as f:
            self.cfg.write(f)

        # Actualizar en memoria
        self.shortcuts[action_key] = keyseq

    # ------------------------------------------------------------
    # UTILIDAD
    # ------------------------------------------------------------
    def reset_to_defaults(self):
        """
        Restablece los atajos a los valores del config original de fábrica.
        (Solo vuelve a leer desde el archivo actual, sin fallback hardcodeado)
        """
        self.cfg.read(self.path, encoding="utf-8")
        self.shortcuts = self._load_shortcuts()
