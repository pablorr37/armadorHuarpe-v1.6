"""Panel anclable con el catálogo de roles del maquetador (punto b del pedido)."""
from __future__ import annotations

from PyQt5.QtCore import QMimeData, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QDockWidget, QInputDialog, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

# (rol, etiqueta) por defecto, en el orden pedido.
ROLES_POR_DEFECTO = [
    ("folio_seccion", "Folio + sección"),
    ("fecha", "Fecha"),
    ("volanta", "Volanta"),
    ("titulo", "Título"),
    ("bajada", "Bajada"),
    ("firma", "Firma"),
    ("cuerpo", "Cuerpo"),
    ("epigrafe", "Epígrafe"),
    ("foto", "Foto"),
    ("textuales", "Textuales"),
    ("dato", "Dato"),
    ("numero", "Número"),
    ("qr", "QR"),
]


class _RecursosList(QListWidget):
    """Lista con drag nativo de Qt, transportando el rol en un mime type propio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def mimeData(self, items):  # noqa: N802 (override Qt)
        mime = QMimeData()
        if items:
            rol = items[0].data(Qt.UserRole)
            mime.setData("application/x-armadorhuarpe-rol", str(rol).encode("utf-8"))
        return mime


class RecursosPanelDock(QDockWidget):
    solicitud_agregar_custom = pyqtSignal(str, str, str)  # nombre, rol, tipo

    def __init__(self, parent=None):
        super().__init__("Recursos", parent)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)

        cont = QWidget(self)
        lay = QVBoxLayout(cont)
        self.lista = _RecursosList(cont)
        for rol, etiqueta in ROLES_POR_DEFECTO:
            item = QListWidgetItem(etiqueta)
            item.setData(Qt.UserRole, rol)
            self.lista.addItem(item)
        lay.addWidget(self.lista)

        self.btn_custom = QPushButton("Agregar recurso custom…")
        self.btn_custom.clicked.connect(self._on_agregar_custom)
        lay.addWidget(self.btn_custom)

        self.setWidget(cont)

    def _on_agregar_custom(self):
        nombre, ok = QInputDialog.getText(self, "Recurso custom", "Nombre del recurso:")
        if not ok or not nombre.strip():
            return
        rol, ok = QInputDialog.getText(self, "Recurso custom", "Rol (id interno, sin espacios):",
                                        text=nombre.strip().lower().replace(" ", "_"))
        if not ok or not rol.strip():
            return
        tipo, ok = QInputDialog.getItem(self, "Recurso custom", "Tipo:", ["text", "picture"], 0, False)
        if not ok:
            return
        item = QListWidgetItem(nombre.strip())
        item.setData(Qt.UserRole, rol.strip())
        self.lista.addItem(item)
        self.solicitud_agregar_custom.emit(nombre.strip(), rol.strip(), tipo)

    def sincronizar_disponibilidad(self, roles_con_repuesto: set[str]) -> None:
        """Deshabilita (gris) los roles sin ninguna caja existente de la que
        clonar — Quark no puede crear cajas desde cero (ver restricción dura
        en docs/maquetador_arquitectura.md): nunca se promete una operación
        imposible."""
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            rol = item.data(Qt.UserRole)
            disponible = rol in roles_con_repuesto
            item.setFlags(
                (item.flags() | Qt.ItemIsEnabled) if disponible
                else (item.flags() & ~Qt.ItemIsEnabled)
            )
            item.setToolTip(
                "" if disponible else
                "No hay ninguna caja existente de este rol en esta maqueta para clonar "
                "— QuarkXPress no puede crear cajas nuevas desde cero."
            )
