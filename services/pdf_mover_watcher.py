"""
PdfMoverWatcher — poll que vigila la RAÍZ de Imprenta temporal (pdf_root) por los PDF que
el bot de export (controller/pdf_export_mode.py) deja ahí, y por cada uno:
  1) valida la página (aviso/fecha/folio — método de control `validar_pdf`);
  2) lo mueve a su carpeta del día (`pdf_output_dir`);
  3) avanza el qxp correspondiente de 'mandar' a 'a pdf'.

Mismo patrón que services/chrome_watcher.py (QObject + QTimer + _scan + señal), pero para
la raíz de PDF en vez de la carpeta de descargas de la extensión Chrome.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

_log = logging.getLogger(__name__)

_NOMBRE_PDF_RE = re.compile(r"^(\d{1,2})\.pdf$", re.IGNORECASE)


class PdfMoverWatcher(QObject):
    """Escanea la raíz de Imprenta temporal cada N segundos buscando 'NN.pdf' recién
    exportados por el bot de export a PDF. Al encontrar uno válido: lo mueve a la carpeta
    del día y avanza el qxp de 'mandar' a 'a pdf'."""

    pdf_movido = pyqtSignal(int)        # folio movido con éxito
    error_proceso = pyqtSignal(str)

    def __init__(self, file_service, fn_comp=None):
        super().__init__()
        self._fs = file_service
        self._fn_comp = fn_comp or (lambda _n: {})
        self._procesados_recientes: set[str] = set()  # nombres ya movidos (evita relogueo)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scan)

    def start(self, interval_ms: int = 5000):
        self._timer.start(interval_ms)
        _log.info("PdfMoverWatcher activo — escaneando la raíz de Imprenta temporal cada %ds",
                  interval_ms // 1000)

    def stop(self):
        self._timer.stop()

    # ── Control ───────────────────────────────────────────────
    def validar_pdf(self, folio: int) -> tuple[bool, str]:
        """Método de control: confirma aviso/fecha/folio antes de mover el PDF exportado.
        - folio: el número de página tal cual viene en el nombre del archivo.
        - estado: la página debe tener un estado asignado en el INI (no es un PDF huérfano).
        - origen: debe existir (o haber existido) un qxp en 'mandar'/'a pdf' para ese folio
          — es la ruta que siguió el bot de export, así que un PDF sin ese origen es sospechoso."""
        try:
            entry = self._fs.read_page_entry(folio)
        except Exception as e:
            return False, f"P{folio:02d}: no se pudo leer el INI de la página ({e})."
        estado = (entry.get("estado") or "").strip().lower()
        if not estado:
            return False, f"P{folio:02d}: sin estado en el INI (página no armada) → no se mueve."

        qxp = None
        try:
            qxp = self._fs.find_qxp_mandar(folio) or self._fs.find_qxp_apdf(folio)
        except Exception:
            pass
        if not qxp:
            return False, f"P{folio:02d}: no hay qxp en 'mandar'/'a pdf' → sin origen esperado."

        try:
            comp = self._fn_comp(folio) or {}
        except Exception:
            comp = {}
        _log.info("P%02d validado para mover PDF: estado=%s aviso=%s fecha=%s",
                  folio, estado, comp.get("aviso") or "—", comp.get("fecha") or "—")
        return True, ""

    # ── Poll ──────────────────────────────────────────────────
    def _scan(self):
        try:
            pdf_root = Path(self._fs.rutas.get("pdf_root") or "")
        except Exception:
            pdf_root = None
        if not pdf_root or not pdf_root.exists():
            return
        try:
            archivos = sorted(pdf_root.iterdir())
        except Exception as e:
            _log.warning("PdfMoverWatcher: no se pudo listar %s: %s", pdf_root, e)
            return

        for f in archivos:
            if not f.is_file():
                continue
            m = _NOMBRE_PDF_RE.match(f.name)
            if not m:
                continue
            if f.name in self._procesados_recientes:
                continue
            folio = int(m.group(1))
            try:
                self._procesar(folio, f)
            except Exception as e:
                _log.error("PdfMoverWatcher: error procesando %s: %s", f.name, e)
                self.error_proceso.emit(f"Error al procesar {f.name}: {e}")

    def _procesar(self, folio: int, pdf_path: Path) -> None:
        ok, motivo = self.validar_pdf(folio)
        if not ok:
            _log.warning("PdfMoverWatcher: %s", motivo)
            self.error_proceso.emit(motivo)
            # No lo vuelve a intentar en cada poll (evita spam); igual queda en disco para
            # revisión manual — solo se descarta del reintento inmediato.
            self._procesados_recientes.add(pdf_path.name)
            return

        if not self._fs.mover_pdf_a_carpeta_dia(pdf_path):
            _log.warning("PdfMoverWatcher: no se pudo mover %s a la carpeta del día.", pdf_path.name)
            return   # reintentar en el próximo poll (p.ej. archivo aún en uso)

        # Avanzar el qxp de 'mandar' a 'a pdf' (mismo mover que usa el botón manual).
        try:
            dec = self._fs.decidir_mover_y_devolver(folio) or {}
            mover = dec.get("mover") or {}
            if mover.get("enabled") and "a pdf" in (mover.get("label") or "").lower():
                self._fs.ejecutar_mover(mover["src"], mover["dest"])
        except Exception as e:
            _log.warning("PdfMoverWatcher: no se pudo mover el qxp P%02d a 'a pdf': %s", folio, e)

        self._procesados_recientes.add(pdf_path.name)
        _log.info("P%02d: PDF movido a la carpeta del día y qxp avanzado a 'a pdf'.", folio)
        self.pdf_movido.emit(folio)
