"""
ChromeWatcher — detecta descargas de la extensión Chrome y las copia
a materiales/Pnn/, replicando exactamente lo que hace _scrape_core.
"""
import io
import json
import logging
import os
import re
import shutil
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

_log = logging.getLogger(__name__)

_QR_LINK_RE = re.compile(r"Link para el QR:\s*(https?://\S+)", re.IGNORECASE)


def _convertir_webp_a_jpg(path: Path) -> None:
    """Convierte WebP a JPG en el lugar; no hace nada si el archivo no es WebP."""
    try:
        data = path.read_bytes()
        if data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
            return
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        jpg_path = path.with_suffix(".jpg")
        img.save(jpg_path, "JPEG", quality=100, subsampling=0)
        if jpg_path != path:
            path.unlink()
        _log.debug("WebP convertido a JPG: %s", jpg_path.name)
    except Exception as exc:
        _log.warning("No se pudo convertir WebP %s: %s", path.name, exc)


def generar_qr_png(url: str, dest_path) -> bool:
    """Genera un PNG de QR para `url` en dest_path (mismo formato que la descarga).
    Reutilizable desde la UI (#11). Devuelve True si se generó."""
    try:
        import qrcode
        import qrcode.constants
    except ImportError:
        _log.warning("qrcode no disponible; se omite generación de QR")
        return False
    try:
        if "youtube.com/embed/" in url:
            url = url.replace("youtube.com/embed/", "youtube.com/watch?v=")
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("L")
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(dest_path))
        _log.debug("QR generado: %s → %s", url, dest_path.name)
        return True
    except Exception as exc:
        _log.warning("No se pudo generar QR para %s: %s", url, exc)
        return False


def _generar_qrs_desde_cuerpo(cuerpo: str, dest_dir: Path) -> None:
    """Genera archivos QR_NN.png para cada 'Link para el QR:' encontrado en el cuerpo."""
    links = _QR_LINK_RE.findall(cuerpo)
    if not links:
        return
    for idx, url in enumerate(links, 1):
        generar_qr_png(url, dest_dir / f"QR_{idx:02d}.png")


class ChromeWatcher(QObject):
    """
    Escanea ~/Downloads/armadorHuarpe/ cada N segundos buscando carpetas
    con un _pending.json cuyo campo 'copiado' sea false.
    Cuando encuentra uno, copia los archivos a materiales/Pnn/NNa/ y
    actualiza el INI igual que lo hace _scrape_core (sin mark_assigned).
    """

    nota_descargada = pyqtSignal(int)   # número de página procesada
    error_proceso   = pyqtSignal(str)   # mensaje de error
    secciones_actualizadas = pyqtSignal(list)   # lista adoptada desde otra estación
    maqueta_limits_actualizados = pyqtSignal()  # límites de maqueta adoptados de otra estación

    _WATCH_DIR      = Path.home() / "Downloads" / "armadorHuarpe"
    _SECCIONES_JSON = _WATCH_DIR / "secciones.json"
    _PAGINAS_SECCIONES_JSON = _WATCH_DIR / "paginas_secciones.json"

    def __init__(self, file_service, by: str = ""):
        super().__init__()
        self._fs = file_service
        self._by = by
        self._sec_mtime = 0.0   # mtime del secciones.json compartido visto por última vez
        self._skip_logged: set[str] = set()   # descargas ya copiadas ya logueadas (evita spam)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scan)

    def start(self, interval_ms: int = 5000):
        self._sync_compartido()
        self._write_secciones_json()
        self._write_paginas_secciones_json()
        self._timer.start(interval_ms)
        # Banner de identidad: PID + archivo del módulo realmente cargado.
        # Sirve para detectar código viejo en memoria / procesos zombie.
        _log.info("ChromeWatcher start: PID=%d módulo=%s", os.getpid(), __file__)
        _log.info(
            "ChromeWatcher activo — escaneando %s cada %ds",
            self._WATCH_DIR,
            interval_ms // 1000,
        )

    def stop(self):
        self._timer.stop()

    # ── secciones.json (extensión) ────────────────────────────

    def _write_secciones_json(self) -> None:
        from config.config import config_global
        try:
            self._WATCH_DIR.mkdir(parents=True, exist_ok=True)
            data = {"secciones": config_global.secciones}
            self._SECCIONES_JSON.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _log.debug("secciones.json actualizado (%d secciones)", len(data["secciones"]))
        except Exception as exc:
            _log.warning("No se pudo escribir secciones.json: %s", exc)

    def _write_paginas_secciones_json(self) -> None:
        """#6 — mapa {pagina: seccion} con las secciones configuradas en Python,
        para que la extensión autoseleccione la sección al colocar la página.
        Lee de los INI (uso en start, cuando aún no hay datos en memoria)."""
        mapa = {}
        for n in range(1, 17):
            try:
                entry = self._fs.read_page_entry(n)
                sec = (entry.get("seccion") or "").strip()
                if sec:
                    mapa[str(n)] = sec
            except Exception:
                continue
        self.escribir_paginas_secciones(mapa)

    def escribir_paginas_secciones(self, mapa: dict) -> None:
        """Escribe el mapa pagina→sección (recibe el dict ya armado, p.ej. desde
        gestor_paginas en memoria, para mantenerlo fresco tras cada poll/cambio)."""
        try:
            self._WATCH_DIR.mkdir(parents=True, exist_ok=True)
            self._PAGINAS_SECCIONES_JSON.write_text(
                json.dumps({"paginas": mapa or {}}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as exc:
            _log.warning("No se pudo escribir paginas_secciones.json: %s", exc)

    # ── config compartido (materiales/config.json): secciones + límites maqueta ──

    def _shared_config_path(self):
        """Ruta del config.json compartido entre estaciones (en materiales/)."""
        try:
            mat = getattr(self._fs, "material", None)
            if mat:
                return Path(mat) / "config.json"
        except Exception:
            pass
        return None

    def _legacy_secciones_path(self):
        """Viejo materiales/secciones.json (para migración inicial a config.json)."""
        try:
            mat = getattr(self._fs, "material", None)
            if mat:
                return Path(mat) / "secciones.json"
        except Exception:
            pass
        return None

    def _sync_compartido(self) -> None:
        """Adopta el config.json compartido (secciones + límites de maqueta) si otra
        estación lo cambió (mtime check barato). Lecturas sin lock (snapshot atómico)."""
        from config.config import config_global
        from services.shared_config_service import read_shared
        shared = self._shared_config_path()
        if shared is None:
            return
        try:
            if not shared.exists():
                # No existe aún: sembrar desde lo local (migrando del viejo secciones.json).
                self._sembrar_config_compartido()
                return
            mtime = shared.stat().st_mtime
            if mtime <= self._sec_mtime:
                return
            data = read_shared(shared)
            if data is None:
                return
            self._sec_mtime = mtime

            # --- Secciones ---
            lista = [s for s in (data.get("secciones") or []) if str(s).strip()]
            if lista and lista != config_global.secciones:
                config_global.save_secciones(lista)
                self._write_secciones_json()
                self.secciones_actualizadas.emit(lista)
                _log.info("Secciones adoptadas de %s (%d)", shared, len(lista))

            # --- Límites de maqueta ---
            limites = data.get("maqueta_limits")
            if isinstance(limites, dict) and limites != config_global.export_maqueta_limits():
                config_global.apply_maqueta_limits(limites)
                self.maqueta_limits_actualizados.emit()
                _log.info("Límites de maqueta adoptados de %s", shared)
        except Exception as exc:
            _log.warning("No se pudo sincronizar config compartido: %s", exc)

    def _sembrar_config_compartido(self) -> None:
        """Crea config.json desde la config local, migrando el viejo secciones.json si existe."""
        from config.config import config_global
        from services.shared_config_service import update_shared
        shared = self._shared_config_path()
        if shared is None:
            return
        # Secciones: preferir las del viejo compartido si existía (migración).
        secciones = list(config_global.secciones)
        legacy = self._legacy_secciones_path()
        try:
            if legacy and legacy.exists():
                old = json.loads(legacy.read_text(encoding="utf-8"))
                old_lista = [s for s in (old.get("secciones") or []) if str(s).strip()]
                if old_lista:
                    secciones = old_lista
                    if old_lista != config_global.secciones:
                        config_global.save_secciones(old_lista)
        except Exception:
            pass
        try:
            nuevo = update_shared(shared, lambda d: {
                **d,
                "version": d.get("version", 1),
                "secciones": secciones,
                "maqueta_limits": config_global.export_maqueta_limits(),
            })
            if nuevo is not None and shared.exists():
                self._sec_mtime = shared.stat().st_mtime
            self._write_secciones_json()
        except Exception as exc:
            _log.warning("No se pudo sembrar config compartido: %s", exc)

    def publicar_secciones(self, lista: list) -> None:
        """Reemplazo total de la lista de secciones: guarda local, mergea al config.json
        compartido (bajo lock) y refresca el secciones.json de la extensión."""
        from config.config import config_global
        from services.shared_config_service import update_shared
        config_global.save_secciones(lista)
        shared = self._shared_config_path()
        if shared is not None:
            nuevo = update_shared(shared, lambda d: {**d, "version": d.get("version", 1),
                                                     "secciones": list(lista)})
            try:
                if nuevo is not None and shared.exists():
                    self._sec_mtime = shared.stat().st_mtime
            except Exception:
                pass
        self._write_secciones_json()

    def publicar_maqueta_limits(self) -> None:
        """Publica los límites de maqueta locales al config.json compartido (merge bajo lock)."""
        from config.config import config_global
        from services.shared_config_service import update_shared
        shared = self._shared_config_path()
        if shared is None:
            return
        limites = config_global.export_maqueta_limits()
        nuevo = update_shared(shared, lambda d: {**d, "version": d.get("version", 1),
                                                 "maqueta_limits": limites})
        try:
            if nuevo is not None and shared.exists():
                self._sec_mtime = shared.stat().st_mtime
        except Exception:
            pass

    def reload_secciones(self, lista: list) -> None:
        """Llamado por el dialog de secciones cuando el usuario guarda."""
        self.publicar_secciones(lista)

    # ── Escaneo ──────────────────────────────────────────────

    def _scan(self):
        # #10 — adoptar config compartido (secciones + límites) si otra estación lo cambió.
        self._sync_compartido()
        if not self._WATCH_DIR.exists() or not self._SECCIONES_JSON.exists():
            self._write_secciones_json()
        if not self._WATCH_DIR.exists():
            return
        for subdir in sorted(self._WATCH_DIR.iterdir()):
            if not subdir.is_dir():
                continue
            pending_path = subdir / "_pending.json"
            if not pending_path.exists():
                continue
            try:
                data = json.loads(pending_path.read_text(encoding="utf-8"))
            except Exception as exc:
                _log.warning("Error leyendo %s: %s", pending_path, exc)
                continue
            if data.get("copiado"):
                if subdir.name not in self._skip_logged:
                    _log.debug("skip %s (ya copiado por otro proceso/sesión)", subdir.name)
                    self._skip_logged.add(subdir.name)
                continue
            try:
                self._process(subdir, data, pending_path)
            except Exception as exc:
                _log.error("Error procesando %s: %s", subdir.name, exc)
                self.error_proceso.emit(f"Error al procesar {subdir.name}: {exc}")

    # ── Procesamiento de una descarga ─────────────────────────

    def _process(self, subdir: Path, data: dict, pending_path: Path) -> None:
        pagina   = int(data["pagina"])
        seccion  = (data.get("seccion") or "").strip()
        link     = (data.get("link") or "").strip()
        archivos = data.get("archivos") or []
        rol      = (data.get("rol") or "principal").strip()

        # Rol → sufijo determinístico (principal→a, secundaria→b, noticia_N→letra)
        sufijo   = self._fs.rol_a_sufijo(rol)
        dest_dir = self._fs.noticia_dir_de_rol(pagina, rol)
        nn       = f"{pagina:02d}"
        _log.info("Chrome _process P%02d: rol=%s → sufijo=%s → %s", pagina, rol, sufijo, dest_dir.name)

        # Sobrescribir el slot: limpiar contenido previo de esa carpeta
        for old in list(dest_dir.iterdir()):
            try:
                if old.is_file():
                    old.unlink()
                else:
                    shutil.rmtree(old)
            except Exception:
                pass

        # Copiar archivos — nota.txt → NNa.txt, nota.json → NNa.json
        # Se escanea el directorio completo (no solo la lista 'archivos') para
        # capturar imágenes cuyo nombre en disco difiera del registrado en _pending.json
        _SKIP = {"_pending.json"}
        txt_name = ""
        for src in sorted(subdir.iterdir()):
            if src.name in _SKIP or not src.is_file():
                continue
            if src.name == "nota.txt":
                dest_name = f"{nn}{sufijo}.txt"
                txt_name = dest_name
            elif src.name == "nota.json":
                dest_name = f"{nn}{sufijo}.json"
            else:
                dest_name = src.name
            dest_path = dest_dir / dest_name
            shutil.copy2(src, dest_path)
            # Convertir WebP a JPG en imágenes
            if src.name not in ("nota.txt", "nota.json"):
                _convertir_webp_a_jpg(dest_path)

        # Generar QR PNGs desde los links del cuerpo (igual que _scrape_core)
        try:
            nota_json_path = dest_dir / f"{nn}{sufijo}.json"
            if nota_json_path.exists():
                nota_data = json.loads(nota_json_path.read_text(encoding="utf-8"))
                cuerpo_nota = nota_data.get("cuerpo", "")
                _generar_qrs_desde_cuerpo(cuerpo_nota, dest_dir)
        except Exception as exc:
            _log.warning("No se pudieron generar QRs para P%02d: %s", pagina, exc)

        # INI: solo flags de página (la lista de notas se deriva del disco).
        # 'asignado' se calcula del disco en refrescar_avisos_desde_ini.
        extra: dict = {"by": self._by}
        if seccion:
            extra["seccion"] = seccion
        self._fs.write_page_entry(pagina, **extra)

        # #10 — si la sección vino de la extensión y es nueva, propagarla a todas las estaciones.
        if seccion:
            try:
                from config.config import config_global
                actuales = config_global.secciones
                if seccion not in actuales:
                    self.publicar_secciones(list(actuales) + [seccion])
                    self.secciones_actualizadas.emit(config_global.secciones)
            except Exception as exc:
                _log.warning("No se pudo propagar sección nueva '%s': %s", seccion, exc)

        # #6 — refrescar el mapa pagina→sección para la extensión.
        self._write_paginas_secciones_json()

        # Determinar la maqueta (aviso del INI + sección) y escribirla en nota.json,
        # reemplazando el default hardcodeado. Queda establecida al momento de bajar.
        try:
            self._fs.sincronizar_maqueta_pagina(pagina)
        except Exception as exc:
            _log.warning("No se pudo sincronizar maqueta P%02d: %s", pagina, exc)

        # Marcar como copiado en el _pending.json
        data["copiado"] = True
        pending_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _log.info("P%02d guardada como '%s' en %s (sección='%s')", pagina, rol, dest_dir.name, seccion)
        self.nota_descargada.emit(pagina)
