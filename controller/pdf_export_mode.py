"""
PdfExportOrchestrator — Bot de exportación automática qxp→PDF.

INDEPENDIENTE del Armado automático (controller/auto_mode.py): no toca asignación ni
pegado. Recorre los qxp que ya están en 'mandar' (listos para prensa), abre cada uno en
Quark, exporta a PDF (Ctrl+Alt+P + nombre + Enter) a la raíz de Imprenta temporal, y lo
deja: el poll `services/pdf_mover_watcher.PdfMoverWatcher` es quien mueve el PDF a su
carpeta del día y avanza el qxp de 'mandar' a 'a pdf' — este orquestador NO mueve archivos.

Mismo patrón de _PaginaWorker/AutoModeOrchestrator (kill-switch Esc×5, QThread por página,
reintentos de foco), simplificado porque no hay pasos de asignar/pegar/colocar recursos.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from collections import deque
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from services.quark_auto import QuarkAutomator, CanceladoError

_log = logging.getLogger(__name__)

# Estados de fin de página
OK = "ok"
ERROR = "error"
REINTENTAR_FOCO = "reintentar_foco"
CANCELADO = "cancelado"

MAX_REINTENTOS_FOCO = 3
MAX_PAGINAS_FALLO_FOCO = 2

ESC_N = 5
ESC_LAPSO = 1.0

ESPERA_APERTURA = 6.0
TIMEOUT_PDF = 90.0   # s esperando que el PDF exportado aparezca en disco


class _EscWatcherPdf(QThread):
    """Kill-switch Esc×5 propio de este bot (independiente del del Armado automático:
    ambos pueden calzar sin interferirse porque cada uno corre solo mientras SU worker
    está activo)."""
    disparado = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._run = True

    def stop(self):
        self._run = False

    def run(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
        except Exception as e:
            _log.warning("_EscWatcherPdf: sin GetAsyncKeyState (%s); kill-switch inactivo.", e)
            return
        VK_ESCAPE = 0x1B
        prev_down = False
        marcas = deque()
        while self._run:
            try:
                estado = user32.GetAsyncKeyState(VK_ESCAPE)
                down = bool(estado & 0x8000)
                if down and not prev_down:
                    ahora = time.time()
                    marcas.append(ahora)
                    while marcas and (ahora - marcas[0]) > ESC_LAPSO:
                        marcas.popleft()
                    if len(marcas) >= ESC_N:
                        self.disparado.emit()
                        return
                prev_down = down
            except Exception:
                pass
            time.sleep(0.035)


class _ExportWorker(QThread):
    """Exporta UN qxp a PDF: abrir → enfocar → Ctrl+Alt+P + nombre + Enter → esperar el PDF
    en la raíz de Imprenta temporal → cerrar el documento → minimizar Quark."""
    terminado = pyqtSignal(int, str)    # (folio, estado)
    paso = pyqtSignal(str)

    def __init__(self, folio: int, qxp_path: Path, quark_exe: str, automator: QuarkAutomator,
                 pdf_root: Path, parent=None):
        super().__init__(parent)
        self.folio = int(folio)
        self.qxp_path = Path(qxp_path)
        self.quark_exe = quark_exe
        self.automator = automator
        self.pdf_root = Path(pdf_root)

    def run(self):
        a = self.automator
        n = self.folio
        try:
            self.paso.emit(f"P{n:02d}: abriendo {self.qxp_path.name}…")
            if not a.simular:
                try:
                    subprocess.Popen([self.quark_exe, str(self.qxp_path)], shell=False)
                except Exception as e:
                    _log.warning("Export P%02d: no se pudo abrir Quark: %s", n, e)
                    self.terminado.emit(n, ERROR)
                    return

            if not a.focus_quark(timeout=ESPERA_APERTURA + 20.0):
                self.paso.emit(f"P{n:02d}: Quark no quedó al frente → reintento.")
                self.terminado.emit(n, REINTENTAR_FOCO)
                return

            a.esperar_y_cerrar_dialogo_fuentes(timeout=4.0)
            a.esperar(0.4)

            nombre = f"{n:02d}"
            self.paso.emit(f"P{n:02d}: exportando a PDF ({nombre})…")
            if not a.exportar_pdf(nombre):
                self.terminado.emit(n, ERROR)
                return

            # Esperar a que el PDF exportado aparezca en la raíz de Imprenta temporal.
            self.paso.emit(f"P{n:02d}: esperando el PDF en Imprenta temporal…")
            t0 = time.time()
            ok = False
            while time.time() - t0 < TIMEOUT_PDF:
                a.esperar_y_cerrar_dialogo_fuentes(timeout=0.5)
                if a.simular or (self.pdf_root / f"{nombre}.pdf").exists() \
                        or (self.pdf_root / f"{nombre}.PDF").exists():
                    ok = True
                    break
                a.esperar(0.5)
            if not ok:
                _log.warning("P%02d: timeout esperando el PDF exportado.", n)
                self.terminado.emit(n, ERROR)
                return

            a.cerrar()             # cierra el qxp (deja Quark limpio para la próxima página)
            a.minimizar_quark()
            self.terminado.emit(n, OK)
        except CanceladoError:
            _log.info("Export worker P%02d cancelado (Esc×5).", n)
            self.terminado.emit(n, CANCELADO)
        except Exception as e:
            _log.warning("Export worker P%02d falló: %s", n, e)
            self.terminado.emit(n, ERROR)


class PdfExportOrchestrator(QObject):
    """Orquesta el bot de export a PDF. main_window inyecta cómo listar los candidatos
    (qxp en 'mandar'), la ruta de Quark y la raíz de Imprenta temporal."""

    estado = pyqtSignal(str)
    log = pyqtSignal(str)
    procesada = pyqtSignal(int, bool)
    apagado_auto = pyqtSignal(str)

    def __init__(self, fn_listar_mandar, fn_quark_exe, fn_pdf_root,
                 fn_finalizado_ok=None, simular=False, parent=None):
        """
        fn_listar_mandar() -> list[(folio, Path)]   (qxp candidatos en 'mandar')
        fn_quark_exe() -> str                        (ejecutable de Quark configurado)
        fn_pdf_root() -> Path                        (raíz de Imprenta temporal)
        fn_finalizado_ok(folio) -> None               (post-OK en hilo GUI, opcional)
        """
        super().__init__(parent)
        self._fn_listar_mandar = fn_listar_mandar
        self._fn_quark_exe = fn_quark_exe
        self._fn_pdf_root = fn_pdf_root
        self._fn_finalizado_ok = fn_finalizado_ok or (lambda _n: None)
        self._enabled = False
        self._cancel_event = threading.Event()
        self._automator = QuarkAutomator(simular=simular)
        self._automator.set_cancel_event(self._cancel_event)
        self._procesadas: set = set()
        self._pospuestas: set = set()
        self._reintentos_foco: dict = {}
        self._fallos_foco: set = set()
        self._activa = None
        self._worker = None
        self._esc_watcher = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, valor: bool):
        self._enabled = bool(valor)
        self.estado.emit("Exportar PDF ON" if self._enabled else "Exportar PDF OFF")
        if not self._enabled:
            self._procesadas.clear()
            self._pospuestas.clear()
            self._reintentos_foco.clear()
            self._fallos_foco.clear()
            self._detener_watcher()
        else:
            self._cancel_event.clear()
            self._intentar_siguiente()

    def set_simular(self, valor: bool):
        valor = bool(valor)
        if self._activa is not None:
            _log.info("set_simular ignorado: hay una página en proceso.")
            return
        self._automator = QuarkAutomator(simular=valor)
        self._automator.set_cancel_event(self._cancel_event)

    @property
    def simular(self) -> bool:
        return bool(getattr(self._automator, "simular", False))

    def reset_pagina(self, folio: int):
        n = int(folio)
        self._procesadas.discard(n)
        self._pospuestas.discard(n)
        self._fallos_foco.discard(n)
        self._reintentos_foco.pop(n, None)

    def poll(self):
        """Refresca la cola desde 'mandar' e intenta procesar la próxima, si está activo."""
        self._pospuestas.clear()
        if self._enabled:
            self._intentar_siguiente()

    # ── Kill-switch Esc×5 ─────────────────────────────────────
    def _iniciar_watcher(self):
        if self._esc_watcher is not None:
            return
        w = _EscWatcherPdf(self)
        w.disparado.connect(self._on_cancel_esc)
        self._esc_watcher = w
        w.start()

    def _detener_watcher(self):
        w = self._esc_watcher
        self._esc_watcher = None
        if w is not None:
            try:
                w.stop()
                w.wait(500)
            except Exception:
                pass

    def _on_cancel_esc(self):
        _log.info("Kill-switch: Esc×5 → cancelando y apagando Exportar PDF.")
        self._cancel_event.set()
        self._apagar("Exportar PDF cancelado por el usuario (Esc×5).")

    def _apagar(self, motivo: str):
        self.set_enabled(False)
        self.estado.emit(motivo)
        self.apagado_auto.emit(motivo)

    # ── Motor ─────────────────────────────────────────────────
    def _intentar_siguiente(self):
        if not self._enabled or self._activa is not None:
            return
        try:
            candidatos = self._fn_listar_mandar() or []
        except Exception as e:
            _log.warning("listar_mandar falló: %s", e)
            candidatos = []
        for folio, qxp_path in candidatos:
            if folio not in self._procesadas and folio not in self._pospuestas:
                self._procesar(folio, qxp_path)
                return

    def _procesar(self, folio: int, qxp_path: Path):
        try:
            quark_exe = self._fn_quark_exe()
        except Exception as e:
            _log.warning("quark_exe falló: %s", e)
            quark_exe = None
        if not quark_exe:
            self.estado.emit("Exportar PDF: no se encontró el ejecutable de Quark.")
            return
        try:
            pdf_root = self._fn_pdf_root()
        except Exception as e:
            _log.warning("pdf_root falló: %s", e)
            pdf_root = None
        if not pdf_root:
            self.estado.emit("Exportar PDF: falta configurar la raíz de Imprenta temporal.")
            return

        self._activa = folio
        self._cancel_event.clear()
        self._iniciar_watcher()

        self._worker = _ExportWorker(folio, qxp_path, quark_exe, self._automator,
                                     Path(pdf_root), parent=self)
        self._worker.paso.connect(self.log.emit)
        self._worker.terminado.connect(self._finalizar)
        self._worker.start()

    def _finalizar(self, folio: int, estado: str):
        self._activa = None
        self._worker = None
        self._detener_watcher()

        if estado == CANCELADO:
            self.log.emit(f"P{folio:02d}: cancelada (Esc×5).")
            return

        if estado == REINTENTAR_FOCO:
            c = self._reintentos_foco.get(folio, 0) + 1
            self._reintentos_foco[folio] = c
            if c < MAX_REINTENTOS_FOCO:
                self._pospuestas.add(folio)
                self.log.emit(f"P{folio:02d}: Quark sin foco, reintento {c}/{MAX_REINTENTOS_FOCO}.")
                self._intentar_siguiente()
                return
            self._procesadas.add(folio)
            self._fallos_foco.add(folio)
            self.log.emit(f"P{folio:02d}: Quark no respondió tras {c} intentos.")
            if len(self._fallos_foco) >= MAX_PAGINAS_FALLO_FOCO:
                self._apagar(
                    f"Exportar PDF apagado: Quark no respondió en {len(self._fallos_foco)} páginas.")
                return
            self._intentar_siguiente()
            return

        # OK / ERROR
        self._procesadas.add(folio)
        ok = (estado == OK)
        self.procesada.emit(folio, ok)
        self.log.emit(f"P{folio:02d}: {'OK' if ok else 'con error'} (Exportar PDF).")
        if ok:
            try:
                self._fn_finalizado_ok(folio)
            except Exception as e:
                _log.warning("fn_finalizado_ok P%02d falló: %s", folio, e)
        self._intentar_siguiente()
