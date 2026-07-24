import unicodedata

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QLabel,
    QPushButton, QInputDialog, QDialogButtonBox,
)
from PyQt5.QtCore import pyqtSignal

from config.config import config_global


def _normalizar(s: str) -> str:
    """Mismo criterio que controller._secciones_textuales_norm / es_seccion_textual."""
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


class SeccionesTextualesDialog(QDialog):
    """Secciones ESPECIALES: aquellas cuyos textuales se extraen del bloque 'Textuales' de la
    nota del manager (hoy Café de la Política), en vez de tomar todos los blockquotes.
    Escalable: agregar el nombre de la sección tal cual aparece en el manager, con su propia
    deducción de caracteres (base/umbral) para los dos textuales."""

    secciones_guardadas = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Secciones especiales (textuales)")
        self.setMinimumWidth(420)
        self._deducciones: dict = {}  # nombre tal cual lo escribió el usuario -> {"base","umbral"}
        self._build_ui()
        self._cargar(config_global.secciones_textuales)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Secciones cuyos textuales se toman del bloque «Textuales» de la nota\n"
            "(el resto usa la detección general de citas). \"Base\"/\"Umbral\" definen cuánto\n"
            "descuentan del cuerpo los dos textuales de esa sección (misma fórmula que un\n"
            "textual x2: base + exceso sobre el umbral de cada uno)."))

        self._lista = QListWidget()
        self._lista.itemDoubleClicked.connect(lambda _: self._editar_deduccion())
        lay.addWidget(self._lista)

        btns = QHBoxLayout()
        for label, slot in [
            ("Agregar", self._agregar),
            ("Eliminar", self._eliminar),
            ("Editar deducción", self._editar_deduccion),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        lay.addLayout(btns)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._guardar)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _cargar(self, items: list):
        self._lista.clear()
        self._lista.addItems(sorted(items, key=str.casefold))
        guardado = config_global.secciones_textuales_deduccion
        self._deducciones = {}
        for nombre in items:
            cfg = guardado.get(_normalizar(nombre)) or {}
            self._deducciones[nombre] = {
                "base": int(cfg.get("base", 0)),
                "umbral": int(cfg.get("umbral", 0)),
            }

    def _pedir_deduccion(self, nombre: str, base_default: int, umbral_default: int):
        base, ok = QInputDialog.getInt(
            self, f"Deducción — {nombre}",
            "Caracteres base (ambos textuales exactos al umbral):",
            base_default, 0, 9999,
        )
        if not ok:
            return None
        umbral, ok = QInputDialog.getInt(
            self, f"Deducción — {nombre}",
            "Umbral por textual (a partir de acá penaliza por caracter extra):",
            umbral_default, 0, 999,
        )
        if not ok:
            return None
        return {"base": base, "umbral": umbral}

    def _agregar(self):
        txt, ok = QInputDialog.getText(self, "Nueva sección especial", "Nombre (como en el manager):")
        if not (ok and txt.strip()):
            return
        nombre = txt.strip()
        existing = [self._lista.item(i).text() for i in range(self._lista.count())]
        if nombre in existing:
            return
        # Café de la Política, si es la primera vez que se agrega, sugiere el valor ya
        # conocido (586/95) como punto de partida del formulario -- sigue siendo un dato
        # tipeado/confirmado acá, no una constante hardcodeada en el cálculo.
        es_cafe = _normalizar(nombre) == "cafe de la politica"
        ded = self._pedir_deduccion(nombre, 586 if es_cafe else 0, 95 if es_cafe else 0)
        if ded is None:
            return
        existing.append(nombre)
        self._deducciones[nombre] = ded
        self._cargar(existing)
        self._deducciones[nombre] = ded  # _cargar puede haber releído desde config; reafirmar

    def _eliminar(self):
        for item in self._lista.selectedItems():
            self._deducciones.pop(item.text(), None)
            self._lista.takeItem(self._lista.row(item))

    def _editar_deduccion(self):
        item = self._lista.currentItem()
        if item is None:
            return
        nombre = item.text()
        actual = self._deducciones.get(nombre) or {"base": 0, "umbral": 0}
        ded = self._pedir_deduccion(nombre, actual["base"], actual["umbral"])
        if ded is not None:
            self._deducciones[nombre] = ded

    def _guardar(self):
        lista = sorted(
            (self._lista.item(i).text() for i in range(self._lista.count())),
            key=str.casefold,
        )
        config_global.save_secciones_textuales(lista)
        dedupe_norm = {
            _normalizar(nombre): self._deducciones.get(nombre) or {"base": 0, "umbral": 0}
            for nombre in lista
        }
        config_global.save_secciones_textuales_deduccion(dedupe_norm)
        self.secciones_guardadas.emit(lista)
        self.accept()
