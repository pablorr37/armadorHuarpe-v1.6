"""
Herramienta de lectura de maquetas (trabajo previo). Vive en la ventana principal.

- "Leer todas": abre cada .qxp de la carpeta de maquetas en Quark, la lee por CDP
  (geometría + fuente → capacidades sin rellenar) y la cachea. MANEJA QUARK SOLO.
- "Actualizar la maqueta abierta": lee la maqueta que el usuario tenga activa en
  Quark ahora (caso: la modificó) y actualiza su entrada de caché.

El editor consume la caché sin necesidad de tener Quark abierto.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QPlainTextEdit, QMessageBox,
)


class _BatchWorker(QThread):
    progress = pyqtSignal(int, int, str)   # i, total, nombre
    done = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancelar(self):
        self._cancel = True

    def run(self):
        from services.maqueta_introspect import leer_todas_las_maquetas
        res = leer_todas_las_maquetas(
            progress=lambda i, t, n: self.progress.emit(i, t, n),
            cancel=lambda: self._cancel,
        )
        self.done.emit(res)


class _UpdateWorker(QThread):
    done = pyqtSignal(object)

    def run(self):
        from services.maqueta_introspect import actualizar_maqueta_abierta
        try:
            self.done.emit(actualizar_maqueta_abierta())
        except Exception as e:  # noqa: BLE001
            self.done.emit({"ok": False, "error": str(e)})


class MaquetasReaderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Leer maquetas (capacidades)")
        self.setMinimumWidth(560)
        self._batch: _BatchWorker | None = None
        self._upd: _UpdateWorker | None = None

        lay = QVBoxLayout(self)
        intro = QLabel(
            "Lee la geometría y la fuente de cada maqueta desde QuarkXPress y calcula "
            "la capacidad de caracteres de cada caja (sin rellenar). El resultado se "
            "cachea y el editor lo usa aunque Quark esté cerrado."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        btns = QHBoxLayout()
        self.btn_todas = QPushButton("Leer todas")
        self.btn_todas.setToolTip(
            "Abre y cierra cada maqueta en Quark automáticamente. No uses Quark mientras corre."
        )
        self.btn_abierta = QPushButton("Actualizar la maqueta abierta")
        self.btn_abierta.setToolTip(
            "Lee la maqueta que tengas activa en Quark ahora (para cuando la modificaste)."
        )
        btns.addWidget(self.btn_todas)
        btns.addWidget(self.btn_abierta)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        lay.addWidget(self.log)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setVisible(False)
        self.btn_cerrar = QPushButton("Cerrar")
        bottom.addWidget(self.btn_cancelar)
        bottom.addWidget(self.btn_cerrar)
        lay.addLayout(bottom)

        self.btn_todas.clicked.connect(self._on_todas)
        self.btn_abierta.clicked.connect(self._on_abierta)
        self.btn_cancelar.clicked.connect(self._on_cancelar)
        self.btn_cerrar.clicked.connect(self.reject)

    # ── acciones ──

    def _log(self, msg: str):
        self.log.appendPlainText(msg)

    def _set_busy(self, busy: bool):
        self.btn_todas.setEnabled(not busy)
        self.btn_abierta.setEnabled(not busy)
        self.btn_cerrar.setEnabled(not busy)
        self.btn_cancelar.setVisible(busy and self._batch is not None)

    def _on_todas(self):
        resp = QMessageBox.question(
            self, "Leer todas las maquetas",
            "Se abrirá y cerrará cada maqueta en QuarkXPress automáticamente.\n"
            "NO uses Quark mientras el proceso corre.\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self.log.clear()
        self._log("Iniciando lectura de todas las maquetas…")
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self._batch = _BatchWorker(self)
        self._batch.progress.connect(self._on_progress)
        self._batch.done.connect(self._on_batch_done)
        self._set_busy(True)
        self._batch.start()

    def _on_progress(self, i: int, total: int, nombre: str):
        if total:
            self.bar.setMaximum(total)
            self.bar.setValue(i)
        if nombre:
            self._log(f"[{i + 1}/{total}] {nombre}…")

    def _on_batch_done(self, res: dict):
        leidas = res.get("leidas", [])
        vacias = res.get("vacias", [])
        errores = res.get("errores", {})
        self._log("")
        self._log(f"Listo. Leídas: {len(leidas)} · Vacías (a diseñar): {len(vacias)} · "
                  f"Errores: {len(errores)}")
        if vacias:
            self._log("Vacías (solo lienzo): " + ", ".join(vacias))
        for nombre, msg in errores.items():
            self._log(f"  ⚠ {nombre}: {msg}")
        self.bar.setValue(self.bar.maximum())
        self._batch = None
        self._set_busy(False)

    def _on_abierta(self):
        self.log.clear()
        self._log("Leyendo la maqueta activa en Quark…")
        self._upd = _UpdateWorker(self)
        self._upd.done.connect(self._on_abierta_done)
        self._set_busy(True)
        self._upd.start()

    def _on_abierta_done(self, res):
        self._upd = None
        self._set_busy(False)
        if not res or not res.get("ok"):
            self._log("No se pudo leer: " + (res or {}).get(
                "error", "¿Está la maqueta abierta y activa en Quark?"))
            return
        caps = res.get("capacidades", {})
        self._log(f"Maqueta '{res.get('stem')}' actualizada. "
                  f"{len(caps)} cajas de texto con capacidad."
                  + ("  (maqueta vacía: a diseñar con el maquetador)" if res.get("empty") else ""))
        for nombre, cap in sorted(caps.items()):
            self._log(f"  • {nombre}: {cap}")

    def _on_cancelar(self):
        if self._batch is not None:
            self._batch.cancelar()
            self._log("Cancelando… (termina la maqueta en curso)")

    def closeEvent(self, e):
        if self._batch is not None:
            self._batch.cancelar()
            self._batch.wait(3000)
        if self._upd is not None:
            self._upd.wait(3000)
        super().closeEvent(e)
