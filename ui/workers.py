# ui/workers.py
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PyQt5 import QtCore
import logging
_log = logging.getLogger(__name__)



def _tlog(msg: str) -> None:
    """
    Escribe `msg` al stdout actual (puede ser el log file redirigido en main.py)
    de forma thread-safe: flush inmediato para no perder mensajes ante un crash.
    """
    try:
        _log.info(msg)
    except Exception:
        pass


class PoolScrapeWorker(QtCore.QObject):
    """
    Worker que corre scan_manager_and_update_pool en un QThread dedicado.

    Ciclo de vida seguro (evita "QThread: Destroyed while thread is still running"):
      - Emite finished/stopped/error → el hilo hace quit().
      - El cleanup de objetos Qt ocurre solo desde QThread.finished
        (ver MainWindow._cleanup_pool_thread), nunca desde los slots de señales
        del worker, que se ejecutan mientras el hilo todavía está vivo.
    """

    item_ready = QtCore.pyqtSignal(object)   # una PoolNota lista
    finished   = QtCore.pyqtSignal()          # completó normalmente
    stopped    = QtCore.pyqtSignal()          # detenido por el usuario
    error      = QtCore.pyqtSignal(str)       # excepción no recuperable

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._stop_requested = False

    def stop(self) -> None:
        """Solicita detención. El worker para en la próxima iteración del generador."""
        self._stop_requested = True

    @QtCore.pyqtSlot()
    def run(self) -> None:
        _tlog("[POOL WORKER] Iniciando scraping…")
        try:
            for nota in self.controller.scan_manager_and_update_pool(incremental=True):
                if self._stop_requested:
                    _tlog("[POOL WORKER] Detenido por solicitud del usuario.")
                    self.stopped.emit()
                    return
                self.item_ready.emit(nota)

            _tlog("[POOL WORKER] Scraping completado normalmente.")
            self.finished.emit()

        except Exception:
            msg = traceback.format_exc()
            _tlog(f"[POOL WORKER] Error:\n{msg}")
            self.error.emit(msg)
