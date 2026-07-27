"""
Worker reutilizable para correr llamadas a la IA fuera del hilo de UI.

La reescritura por IA es una llamada HTTP bloqueante; correrla en el hilo
principal congela la interfaz. `IAWorker` ejecuta cualquier callable en un
QThread y emite el resultado (o el error) de vuelta al hilo de UI.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QThread, pyqtSignal


class IAWorker(QThread):
    done = pyqtSignal(object)   # resultado del callable
    failed = pyqtSignal(str)    # mensaje de error

    def __init__(self, fn: Callable[..., Any], *args, parent=None, **kwargs):
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            resultado = self._fn(*self._args, **self._kwargs)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return
        self.done.emit(resultado)
