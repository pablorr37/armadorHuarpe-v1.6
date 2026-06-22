# utils/app_logger.py
"""
Configuración centralizada de logging para ArmadorHuarpe.

Uso en cada módulo:
    from utils.app_logger import get_logger
    _log = get_logger(__name__)
    _log.info("Mensaje informativo")
    _log.warning("Advertencia")
    _log.error("Error: %s", exc)

Llamar setup_logging() UNA sola vez desde main.py antes de cualquier
import de módulos de la aplicación.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured = False


def setup_logging(log_dir: Path, level: int = logging.DEBUG) -> None:
    """
    Inicializa el sistema de logging.

    - RotatingFileHandler: 5 MB por archivo, 5 copias de respaldo.
    - StreamHandler: consola (útil en desarrollo; sin color para simplicidad).
    - Formato: '%(asctime)s [%(levelname)s] %(name)s: %(message)s'

    Es idempotente: si ya fue llamada, no agrega handlers duplicados.
    """
    global _configured
    if _configured:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "armadorHuarpe.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] PID%(process)d %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    # En Windows la consola puede no soportar UTF-8; usamos errors='replace'
    # para evitar UnicodeEncodeError con caracteres especiales en mensajes de log.
    import io
    _stdout_safe = io.TextIOWrapper(
        sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout,
        encoding="utf-8",
        errors="replace",
        line_buffering=True,
    ) if hasattr(sys.stdout, "buffer") else sys.stdout
    console_handler = logging.StreamHandler(_stdout_safe)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Suprimir loggers verbosos de Selenium/urllib3 que spamean HTML completo
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("selenium.webdriver.remote.remote_connection").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Shorthand: get_logger(__name__) en cada módulo."""
    return logging.getLogger(name)
