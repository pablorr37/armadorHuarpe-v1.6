"""Diálogo de cuenta regresiva cancelable antes de lanzar el armado automático.

Se muestra sobre la ventana principal justo antes de que el bot tome el control del
mouse/teclado. Da al usuario `segundos` para cancelar (botón Cancelar o Esc). Si el
tiempo llega a 0 sin cancelar, el diálogo se acepta y el pegado continúa.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QDialogButtonBox,
    QPushButton,
)
from PyQt5.QtCore import Qt, QTimer


class CountdownDialog(QDialog):
    """`exec_()` devuelve QDialog.Accepted si expira la cuenta (o el usuario deja seguir),
    o QDialog.Rejected si cancela."""

    def __init__(self, segundos: int, numero=None, parent=None, titulo=None, mensaje=None):
        super().__init__(parent)
        self._restante = max(1, int(segundos))
        self._mensaje = mensaje   # si se pasa, reemplaza el texto por defecto (aviso de inicio)
        self.setWindowTitle(titulo or "Armado automático")
        self.setModal(True)
        # Siempre al frente: si Quark (u otra ventana) intenta robar el foco durante la
        # cuenta, el aviso debe seguir visible por encima.
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)
        encabezado = titulo or "Iniciando pegado automático"
        if titulo is None and numero is not None:
            encabezado += f" (página {int(numero):02d})"
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        lay.addWidget(QLabel(f"<b>{encabezado}</b>", alignment=Qt.AlignCenter))
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
        if self._mensaje:
            self._label.setText(f"{self._mensaje}<br>(continúa en <b>{self._restante}</b> s)")
        else:
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


class AvisoPdfExistenteDialog(QDialog):
    """Aviso SIN cuenta regresiva (mismo look que CountdownDialog): ya existe un PDF para la
    página y reapareció un qxp en Mandar. Tras `exec_()`, `self.eleccion` es 'reemplazar' o
    'descartar' (default seguro: 'descartar', no reexporta)."""

    def __init__(self, folio, parent=None):
        super().__init__(parent)
        self.eleccion = "descartar"
        n = int(folio)
        self.setWindowTitle(f"Exportar PDF — página {n:02d}")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Ya existe un PDF para esta página</b>", alignment=Qt.AlignCenter))
        msg = QLabel(
            f"Aviso: ya hay un archivo PDF para la página {n:02d} y se detectó un archivo "
            "Quark en Mandar.<br>¿Desea reemplazar el PDF o descartar la conversión?"
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        lay.addWidget(msg)

        fila = QHBoxLayout()
        btn_desc = QPushButton("Descartar conversión")
        btn_reemp = QPushButton("Reemplazar PDF")
        btn_desc.clicked.connect(self._descartar)
        btn_reemp.clicked.connect(self._reemplazar)
        fila.addWidget(btn_desc)
        fila.addWidget(btn_reemp)
        lay.addLayout(fila)

    def _reemplazar(self):
        self.eleccion = "reemplazar"
        self.accept()

    def _descartar(self):
        self.eleccion = "descartar"
        self.reject()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.raise_()
        self.activateWindow()
