# services/scrape_worker.py
from __future__ import annotations
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from pathlib import Path
from typing import List, Tuple

from services.manager_scraper import ManagerScraper, ScraperError
from services.file_service import FileService

class ScrapeWorker(QObject):
    finished = pyqtSignal(int, object, list)  # (numero, txt_path: Path, img_paths: List[Path])
    error = pyqtSignal(int, str)              # (numero, mensaje)

    def __init__(self, numero: int, link: str, scraper: ManagerScraper, fs: FileService):
        super().__init__()
        self.numero = numero
        self.link = link
        self.scraper = scraper
        self.fs = fs

    def run(self):
        try:
            txt_path, imgs = self.scraper.scrape_to_materiales(self.numero, self.link, self.fs)
            self.finished.emit(self.numero, txt_path, imgs)
        except Exception as e:
            self.error.emit(self.numero, str(e))
