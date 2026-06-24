"""
shared_config_service — utilidades para compartir configuración entre estaciones
mediante un archivo JSON en una carpeta de red (p.ej. materiales/config.json).

Provee:
- Escritura ATÓMICA (temp único por proceso + os.replace) → el lector nunca ve un
  archivo a medio escribir.
- Lectura ROBUSTA con reintentos (defensa extra para FS de red / SMB).
- Lock ENTRE PROCESOS/ESTACIONES (_FileLock) para coordinar el read-modify-write,
  de modo que dos PC que editan a la vez se serialicen y mergeen en lugar de pisarse.

Pensado para reutilizarse con cualquier archivo compartido, no solo config.json.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from utils.app_logger import get_logger

_log = get_logger(__name__)

# Claves de [MAQUETA] que son TEMA de visualización local (no se sincronizan).
MAQUETA_LOCAL_KEYS = {
    "cuerpo_font_family",
    "cuerpo_text_color",
    "cuerpo_bg_color",
    "cuerpo_line_spacing",
    "editor_font_size",
    "cuerpo_font_size",
    "volanta_font_size",
    "bajada_font_size",
    "epigrafe_font_size",
    "titulo_font_size",
    "counter_font_size",
}

# Antigüedad (s) a partir de la cual un lock se considera abandonado y se roba.
_LOCK_STALE_SECS = 30.0


class _FileLock:
    """Lock cooperativo entre procesos/estaciones basado en un archivo `.lock`
    creado con O_EXCL (creación atómica, también en SMB2). Context manager."""

    def __init__(self, target: Path, timeout: float = 10.0, poll: float = 0.15):
        self._lock_path = Path(str(target) + ".lock")
        self._timeout = float(timeout)
        self._poll = float(poll)
        self._acquired = False

    def acquire(self) -> bool:
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                try:
                    os.write(fd, f"{socket.gethostname()}:{os.getpid()}".encode("utf-8", "replace"))
                finally:
                    os.close(fd)
                self._acquired = True
                return True
            except FileExistsError:
                # ¿Lock abandonado? Robarlo si es viejo.
                try:
                    age = time.time() - self._lock_path.stat().st_mtime
                    if age > _LOCK_STALE_SECS:
                        _log.warning("Lock stale (%.0fs) robado: %s", age, self._lock_path)
                        try:
                            os.unlink(str(self._lock_path))
                        except OSError:
                            pass
                        continue
                except OSError:
                    # El lock desapareció entre el open y el stat → reintentar.
                    pass
                if time.monotonic() >= deadline:
                    _log.warning("Timeout esperando lock %s", self._lock_path)
                    return False
                time.sleep(self._poll)

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            os.unlink(str(self._lock_path))
        except OSError:
            pass
        self._acquired = False

    def __enter__(self) -> "_FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def read_shared(path: Path, retries: int = 3, backoff: float = 0.1) -> Optional[dict]:
    """Lee y parsea un JSON compartido. Reintenta ante archivo a medio escribir
    (JSONDecodeError) o errores transitorios de red. Devuelve None si no existe o
    no se pudo leer tras los reintentos."""
    path = Path(path)
    for intento in range(max(1, retries)):
        try:
            if not path.exists():
                return None
            txt = path.read_text(encoding="utf-8")
            return json.loads(txt)
        except (json.JSONDecodeError, OSError) as exc:
            if intento == retries - 1:
                _log.warning("read_shared(%s) falló tras %d intentos: %s", path, retries, exc)
                return None
            time.sleep(backoff)
    return None


def write_shared_atomic(path: Path, data: dict) -> bool:
    """Escribe `data` como JSON de forma atómica (temp único por proceso + os.replace)."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except OSError as exc:
        _log.warning("write_shared_atomic(%s) falló: %s", path, exc)
        try:
            if 'tmp' in locals() and Path(tmp).exists():
                os.unlink(str(tmp))
        except OSError:
            pass
        return False


def update_shared(path: Path, mutate_fn: Callable[[dict], dict],
                  timeout: float = 10.0) -> Optional[dict]:
    """Read-modify-write bajo lock entre estaciones. Lee el estado actual (o {}),
    aplica `mutate_fn(data) -> data` y lo escribe atómico. Devuelve el dict escrito,
    o None si no se pudo adquirir el lock / escribir."""
    path = Path(path)
    lock = _FileLock(path, timeout=timeout)
    if not lock.acquire():
        return None
    try:
        actual = read_shared(path) or {}
        nuevo = mutate_fn(dict(actual))
        if write_shared_atomic(path, nuevo):
            return nuevo
        return None
    finally:
        lock.release()
