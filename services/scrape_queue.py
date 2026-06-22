# services/scrape_queue.py
from __future__ import annotations
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QMutex, QWaitCondition
from pathlib import Path
from typing import List
from collections import deque

from services.manager_scraper import ManagerScraper
from services.file_service import FileService
from utils.app_logger import get_logger

_log = get_logger(__name__)

class ScrapeQueueWorker(QObject):
    # Señales hacia la UI/controlador
    item_ok = pyqtSignal(int, Path, list, int)  # n, txt_path, imgs, txt_len
    item_err = pyqtSignal(int, str)           # (numero, error)
    idle = pyqtSignal()                        # cola vacía

    def __init__(self, scraper: ManagerScraper, fs: FileService):
        super().__init__()
        self.scraper = scraper
        self.fs = fs
        self._q = deque()        # cola de (numero, link)
        self._stop = False
        self._mx = QMutex()
        self._cv = QWaitCondition()

    def enqueue(self, numero: int, link: str):
        self._mx.lock()
        self._q.append((numero, link))
        self._cv.wakeAll()
        self._mx.unlock()

    def stop(self):
        self._mx.lock()
        self._stop = True
        self._cv.wakeAll()
        self._mx.unlock()

    def run(self):
        while True:
            self._mx.lock()
            while not self._q and not self._stop:
                self.idle.emit()
                self._cv.wait(self._mx, 5000)
            if self._stop:
                self._mx.unlock()
                break
            numero, link = self._q.popleft()
            self._mx.unlock()

            try:
                txt_path, imgs = self.scraper.scrape_to_materiales(numero, link, self.fs)

                # --- NUEVO: calcular longitud del cuerpo ---
                txt_len = 0
                try:
                    if txt_path and txt_path.exists():
                        contenido = txt_path.read_text(encoding="utf-8", errors="ignore")
                        txt_len = len(contenido.strip())
                        _log.debug("Scraper len cuerpo P%02d: %d chars", numero, txt_len)
                except Exception as e:
                    _log.warning("No se pudo calcular len del cuerpo para P%02d: %s", numero, e)

                # Emitir con longitud
                self.item_ok.emit(numero, txt_path, imgs, txt_len)
                _log.info("Scraper OK P%02d → %s (%d caracteres)", numero, txt_path, txt_len)

            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                _log.error("Scraper P%02d: %s", numero, msg)
                self.item_err.emit(numero, msg)


