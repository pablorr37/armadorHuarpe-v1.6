# services/foto_pagina_service.py
"""
Servicio puro (sin dependencias Qt) que gestiona la selección ordenada de
fotos por página/subnoticia y los stats de descarga para detección de edición.

Toda la persistencia es JSON en:
  - material/Pnn/fotos_seleccionadas.json      (single-story)
  - material/Pnn/nna/fotos_seleccionadas.json  (multi-story)
  - material/Pnn/stats_fotos.json              (siempre en raíz de página)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from utils.app_logger import get_logger

_log = get_logger(__name__)

_FILENAME       = "fotos_seleccionadas.json"
_STATS_FILENAME = "stats_fotos.json"


class FotoPaginaService:
    """
    Gestiona la selección ordenada de fotos por página/subnoticia.

    Nunca importa ni usa PyQt5. Todos los métodos reciben y devuelven
    estructuras Python simples (dict/list/Path/str).
    """

    # ── Resolución de directorio base ─────────────────────────────────────────

    def _base_dir(self, pagina: int, subfolder: Optional[str],
                  material: Path) -> Path:
        """
        Carpeta donde vive fotos_seleccionadas.json para esta página/subfolder.

        Single-story : material/P06/
        Multi-story  : material/P06/06a/
        """
        page_dir = material / f"P{pagina:02d}"
        return page_dir / subfolder if subfolder else page_dir

    # ── fotos_seleccionadas.json ──────────────────────────────────────────────

    def cargar(self, pagina: int, subfolder: Optional[str],
               material: Path) -> dict:
        """
        Carga fotos_seleccionadas.json. Si no existe devuelve estructura vacía.

        Estructura devuelta:
            {
                "pagina":      int,
                "subfolder":   str | None,
                "fotos":       list[dict],
                "estado_hash": str,
                "texto_hash":  str,
                "pegadas_at":  str | None,
            }
        """
        path = self._base_dir(pagina, subfolder, material) / _FILENAME
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                _log.debug("fotos_seleccionadas cargado: %s (%d fotos)",
                           path, len(data.get("fotos", [])))
                return data
            except Exception as e:
                _log.warning("No se pudo leer %s: %s — se devuelve estado vacío.", path, e)
        return {
            "pagina":      pagina,
            "subfolder":   subfolder,
            "fotos":       [],
            "estado_hash": "",
            "texto_hash":  "",
            "pegadas_at":  None,
        }

    def guardar(self, estado: dict, pagina: int, subfolder: Optional[str],
                material: Path) -> None:
        """
        Persiste fotos_seleccionadas.json.
        Recalcula estado_hash antes de escribir (no recalcula texto_hash).
        """
        estado["estado_hash"] = self._calcular_hash(estado.get("fotos", []))
        path = self._base_dir(pagina, subfolder, material) / _FILENAME
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _log.debug("fotos_seleccionadas guardado: %s", path)
        except Exception as e:
            _log.error("No se pudo guardar %s: %s", path, e)

    # ── Operaciones de selección ──────────────────────────────────────────────

    def seleccionar(self, estado: dict, path: Path, nombre: str) -> dict:
        """
        Agrega `path` al final de la lista si no estaba ya.
        Slot 0 → rol='principal'; resto → rol='secundaria'.
        Resetea pegadas_at.
        """
        path_str = str(path)
        if any(f["path"] == path_str for f in estado.get("fotos", [])):
            _log.debug("Foto ya seleccionada, ignorada: %s", path.name)
            return estado
        orden = len(estado.get("fotos", []))
        rol = "principal" if orden == 0 else "secundaria"
        estado.setdefault("fotos", []).append({
            "path":   path_str,
            "nombre": nombre,
            "orden":  orden,
            "rol":    rol,
        })
        estado["pegadas_at"] = None
        _log.info("Foto seleccionada [orden=%d]: %s", orden, path.name)
        return estado

    def deseleccionar(self, estado: dict, path: Path) -> dict:
        """
        Quita path de la lista y renumera. Resetea pegadas_at.
        """
        path_str = str(path)
        antes = len(estado.get("fotos", []))
        estado["fotos"] = [f for f in estado.get("fotos", []) if f["path"] != path_str]
        if len(estado["fotos"]) < antes:
            self._renumerar(estado["fotos"])
            estado["pegadas_at"] = None
            _log.info("Foto deseleccionada: %s", path.name)
        return estado

    def mover_arriba(self, estado: dict, path: Path) -> dict:
        """Mueve un item un slot hacia arriba (menor índice)."""
        idx = self._find_idx(estado.get("fotos", []), path)
        if idx is None or idx == 0:
            return estado
        fotos = estado["fotos"]
        fotos[idx - 1], fotos[idx] = fotos[idx], fotos[idx - 1]
        self._renumerar(fotos)
        estado["pegadas_at"] = None
        _log.debug("Foto movida arriba: %s → orden %d", path.name, idx - 1)
        return estado

    def mover_abajo(self, estado: dict, path: Path) -> dict:
        """Mueve un item un slot hacia abajo (mayor índice)."""
        idx = self._find_idx(estado.get("fotos", []), path)
        if idx is None or idx >= len(estado.get("fotos", [])) - 1:
            return estado
        fotos = estado["fotos"]
        fotos[idx], fotos[idx + 1] = fotos[idx + 1], fotos[idx]
        self._renumerar(fotos)
        estado["pegadas_at"] = None
        _log.debug("Foto movida abajo: %s → orden %d", path.name, idx + 1)
        return estado

    def set_epigrafe(self, estado: dict, path: Path, texto: str) -> dict:
        """Guarda el epígrafe elegido para una foto ya seleccionada."""
        path_str = str(path)
        for f in estado.get("fotos", []):
            if f["path"] == path_str:
                f["epigrafe"] = texto
                break
        return estado

    def renombrar(self, estado: dict, path: Path, nuevo_nombre: str) -> dict:
        """Actualiza el nombre de una foto ya seleccionada."""
        path_str = str(path)
        for f in estado.get("fotos", []):
            if f["path"] == path_str:
                f["nombre"] = nuevo_nombre
                estado["pegadas_at"] = None
                _log.debug("Nombre de foto actualizado: %s → '%s'", path.name, nuevo_nombre)
                break
        return estado

    def actualizar_path(self, estado: dict, src: Path, dest: Path) -> dict:
        """Actualiza el path de una foto tras renombrarla en disco."""
        src_str  = str(src)
        dest_str = str(dest)
        for f in estado.get("fotos", []):
            if f["path"] == src_str:
                f["path"] = dest_str
                estado["pegadas_at"] = None
                _log.debug("Path de foto actualizado: %s → %s", src.name, dest.name)
                break
        return estado

    def marcar_pegadas(self, estado: dict,
                       texto: Optional[str] = None) -> dict:
        """
        Sella pegadas_at con timestamp ISO y recalcula hashes.
        Si se pasa texto, también guarda texto_hash.
        """
        import datetime
        estado["pegadas_at"]  = datetime.datetime.now().isoformat()
        estado["estado_hash"] = self._calcular_hash(estado.get("fotos", []))
        if texto is not None:
            estado["texto_hash"] = self._hash_texto(texto)
        _log.info("Fotos marcadas como pegadas (pagina=%s, subfolder=%s)",
                  estado.get("pagina"), estado.get("subfolder"))
        return estado

    # ── Consultas de estado ───────────────────────────────────────────────────

    def esta_seleccionada(self, estado: dict, path: Path) -> bool:
        path_str = str(path)
        return any(f["path"] == path_str for f in estado.get("fotos", []))

    def orden_de(self, estado: dict, path: Path) -> Optional[int]:
        """Devuelve el orden 0-based de la foto o None si no está."""
        path_str = str(path)
        for f in estado.get("fotos", []):
            if f["path"] == path_str:
                return f["orden"]
        return None

    def ya_fue_pegado(self, estado: dict, texto_actual: Optional[str] = None) -> bool:
        """
        True si pegadas_at no es None Y hash de fotos no cambió
        Y (si se pasa texto) el hash de texto no cambió.
        """
        if not estado.get("pegadas_at"):
            return False
        hash_actual = self._calcular_hash(estado.get("fotos", []))
        if hash_actual != estado.get("estado_hash", ""):
            return False
        if texto_actual is not None and estado.get("texto_hash"):
            if self._hash_texto(texto_actual) != estado["texto_hash"]:
                return False
        return True

    # ── Detección de edición ──────────────────────────────────────────────────

    def cargar_stats(self, pagina: int, material: Path) -> dict:
        """Carga stats_fotos.json desde la raíz de la página."""
        path = material / f"P{pagina:02d}" / _STATS_FILENAME
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                _log.warning("No se pudo leer stats_fotos %s: %s", path, e)
        return {}

    def registrar_foto_descargada(self, pagina: int, img_path: Path,
                                   material: Path) -> None:
        """
        Registra size + mtime + sha256 de una imagen recién descargada.
        Llamado por el scraper justo después de guardar el archivo.
        """
        if not img_path.exists():
            return
        stats = self.cargar_stats(pagina, material)
        try:
            sha = self._sha256_file(img_path)
            stats[str(img_path)] = {
                "size":   img_path.stat().st_size,
                "mtime":  img_path.stat().st_mtime,
                "sha256": sha,
            }
            dest = material / f"P{pagina:02d}" / _STATS_FILENAME
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(
                json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _log.debug("Stats registradas para: %s", img_path.name)
        except Exception as e:
            _log.warning("No se pudo registrar stats de %s: %s", img_path.name, e)

    def fotos_no_editadas(self, fotos: list, pagina: int,
                           material: Path) -> list[str]:
        """
        Devuelve una lista de paths (strings) de fotos seleccionadas cuyas
        stats (size + sha256) coinciden con las registradas al momento de descarga.
        Una foto que no está en stats se considera editada (no se alerta).
        """
        stats = self.cargar_stats(pagina, material)
        sin_editar: list[str] = []
        for f in fotos:
            p = f["path"]
            if p not in stats:
                continue          # sin stats → asumimos que fue editada
            try:
                img = Path(p)
                if not img.exists():
                    continue
                current_sha = self._sha256_file(img)
                s = stats[p]
                if (img.stat().st_size == s.get("size")
                        and current_sha == s.get("sha256")):
                    sin_editar.append(p)
            except Exception as e:
                _log.debug("Error al verificar stats de %s: %s", p, e)
        if sin_editar:
            _log.info("%d foto(s) sin editar detectadas.", len(sin_editar))
        return sin_editar

    # ── Helpers de auto-nombre ────────────────────────────────────────────────

    def auto_nombre(self, orden: int, pagina: int) -> str:
        """Genera p.ej. 'foto_01 para la 06'."""
        return f"foto_{orden + 1:02d} para la {pagina:02d}"

    def nombre_personalizado(self, stem: str, pagina: int) -> str:
        """Genera p.ej. 'ambulancia para la 06'."""
        return f"{stem} para la {pagina:02d}"

    # ── Utilidades internas ───────────────────────────────────────────────────

    def _calcular_hash(self, fotos: list) -> str:
        """SHA-256 del JSON canónico de la lista (path + orden + nombre)."""
        canonical = [
            {"path": f["path"], "orden": f["orden"], "nombre": f["nombre"]}
            for f in fotos
        ]
        raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _hash_texto(self, texto: str) -> str:
        return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()

    def _renumerar(self, fotos: list) -> None:
        """Reasigna orden (0-based) y rol después de una modificación."""
        for i, f in enumerate(fotos):
            f["orden"] = i
            f["rol"]   = "principal" if i == 0 else "secundaria"

    def _find_idx(self, fotos: list, path: Path) -> Optional[int]:
        path_str = str(path)
        for i, f in enumerate(fotos):
            if f["path"] == path_str:
                return i
        return None

    def _sha256_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


def epigrafes_por_archivo_real(noticia_dir, imagenes) -> dict:
    """Mapea epigrafe -> nombre de archivo REAL en disco, matcheando por *stem*
    (sin extension, case-insensitive). Resuelve el desfasaje de extension cuando
    las imagenes se convirtieron (p.ej. .jpeg del JSON -> .jpg en disco).
    Devuelve {nombre_archivo_real: epigrafe}."""
    import unicodedata as _ud
    def _noacc(s):
        return _ud.normalize("NFD", s or "").encode("ascii", "ignore").decode().upper().strip()
    reales = {}
    try:
        for f in Path(noticia_dir).iterdir():
            if f.is_file():
                reales.setdefault(f.stem.lower(), f.name)
    except Exception:
        pass
    out = {}
    for img in (imagenes or []):
        archivo = (img.get("archivo") or "").strip()
        epi = (img.get("epigrafe") or "").strip()
        if not (archivo and epi) or _noacc(epi) == "NO HAY EPIGRAFE":
            continue
        real = reales.get(Path(archivo).stem.lower(), archivo)
        out[real] = epi
    return out
