"""Diálogo de cuenta regresiva cancelable antes de lanzar el armado automático.

Se muestra sobre la ventana principal justo antes de que el bot tome el control del
mouse/teclado. Da al usuario `segundos` para cancelar (botón Cancelar o Esc). Si el
tiempo llega a 0 sin cancelar, el diálogo se acepta y el pegado continúa.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QTimer


class CountdownDialog(QDialog):
    """`exec_()` devuelve QDialog.Accepted si expira la cuenta (o el usuario deja seguir),
    o QDialog.Rejected si cancela."""

    def __init__(self, segundos: int, numero=None, parent=None):
        super().__init__(parent)
        self._restante = max(1, int(segundos))
        self.setWindowTitle("Armado automático")
        self.setModal(True)
        # Siempre al frente: si Quark (u otra ventana) intenta robar el foco durante la
        # cuenta, el aviso debe seguir visible por encima.
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)
        titulo = "Iniciando pegado automático"
        if numero is not None:
            titulo += f" (página {int(numero):02d})"
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        lay.addWidget(QLabel(f"<b>{titulo}</b>", alignment=Qt.AlignCenter))
        lay.addWidget(self._label)

        self._barra = QProgressBar()
        self._barra.setRange(0, self._restante)
        self._barra.setTextVisible(False)
        lay.addWidget(self._barra)

        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.rejected.connect(self._cancelar)
        lay.addWidget(bb)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._actualizar_texto()
        self._timer.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        # Traer al frente de forma explícita al mostrarse.
        self.raise_()
        self.activateWindow()

    def _actualizar_texto(self):
        self._label.setText(
            f"El bot tomará el control del mouse y el teclado en "
            f"<b>{self._restante}</b> segundo(s).<br>Cancelá si necesitás usar el equipo."
        )
        self._barra.setValue(self._restante)

    def _tick(self):
        self._restante -= 1
        if self._restante <= 0:
            self._timer.stop()
            self.accept()
            return
        self._actualizar_texto()

    def _cancelar(self):
        self._timer.stop()
        self.reject()

    # Esc / cierre por la [X] cuentan como cancelar.
    def reject(self):
        self._timer.stop()
        super().reject()
