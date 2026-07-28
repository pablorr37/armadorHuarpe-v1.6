"""Panel anclable con las propiedades (mm + capacidad en vivo) del recurso
seleccionado en el canvas."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDockWidget, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from model.maquetador_state import RecursoEditable


class PropiedadesPanelDock(QDockWidget):
    geometria_cambiada = pyqtSignal(str, float, float, float, float)  # id, left, top, width, height
    solicitud_clonar = pyqtSignal(str)             # id origen
    solicitud_eliminar = pyqtSignal(str)           # id — elimina directo, sin marcar/desmarcar

    def __init__(self, parent=None):
        super().__init__("Propiedades", parent)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self._recurso_id: str | None = None
        self._actualizando = False  # evita reemitir geometria_cambiada al poblar

        cont = QWidget(self)
        lay = QVBoxLayout(cont)

        self.lbl_id = QLabel("(sin selección)")
        self.lbl_id.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.lbl_id)

        form = QFormLayout()
        self.spin_left = self._spin()
        self.spin_top = self._spin()
        self.spin_width = self._spin()
        self.spin_height = self._spin()
        form.addRow("Izquierda (mm)", self.spin_left)
        form.addRow("Arriba (mm)", self.spin_top)
        form.addRow("Ancho (mm)", self.spin_width)
        form.addRow("Alto (mm)", self.spin_height)
        lay.addLayout(form)

        self.lbl_capacidad = QLabel("")
        lay.addWidget(self.lbl_capacidad)

        botones = QHBoxLayout()
        self.btn_clonar = QPushButton("Clonar otra instancia")
        self.btn_eliminar = QPushButton("Eliminar recurso")
        botones.addWidget(self.btn_clonar)
        botones.addWidget(self.btn_eliminar)
        lay.addLayout(botones)
        lay.addStretch(1)

        self.setWidget(cont)

        for spin in (self.spin_left, self.spin_top, self.spin_width, self.spin_height):
            spin.valueChanged.connect(self._on_spin_changed)
        self.btn_clonar.clicked.connect(self._on_clonar)
        self.btn_eliminar.clicked.connect(self._on_eliminar_clicked)

        self._set_habilitado(False)

    @property
    def recurso_actual_id(self) -> str | None:
        return self._recurso_id

    def _spin(self) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(0.0, 2000.0)
        s.setDecimals(2)
        s.setSuffix(" mm")
        return s

    def _set_habilitado(self, habilitado: bool) -> None:
        for w in (self.spin_left, self.spin_top, self.spin_width, self.spin_height,
                  self.btn_clonar, self.btn_eliminar):
            w.setEnabled(habilitado)

    def mostrar_recurso(self, recurso: RecursoEditable | None) -> None:
        self._recurso_id = recurso.id if recurso else None
        if recurso is None:
            self.lbl_id.setText("(sin selección)")
            self.lbl_capacidad.setText("")
            self._set_habilitado(False)
            return
        self._set_habilitado(True)
        self.lbl_id.setText(f"{recurso.id}  ({recurso.rol or 'sin rol'})")
        self._actualizando = True
        try:
            self.spin_left.setValue(recurso.left_mm)
            self.spin_top.setValue(recurso.top_mm)
            self.spin_width.setValue(recurso.width_mm)
            self.spin_height.setValue(recurso.height_mm)
        finally:
            self._actualizando = False
        if recurso.tipo == "text":
            self.lbl_capacidad.setText(f"Capacidad estimada: {recurso.capacidad or 0} caracteres")
        else:
            self.lbl_capacidad.setText("Recurso de imagen")

    def _on_spin_changed(self, _valor: float) -> None:
        if self._actualizando or self._recurso_id is None:
            return
        self.geometria_cambiada.emit(
            self._recurso_id, self.spin_left.value(), self.spin_top.value(),
            self.spin_width.value(), self.spin_height.value(),
        )

    def _on_clonar(self) -> None:
        if self._recurso_id is not None:
            self.solicitud_clonar.emit(self._recurso_id)

    def _on_eliminar_clicked(self) -> None:
        if self._recurso_id is not None:
            self.solicitud_eliminar.emit(self._recurso_id)
