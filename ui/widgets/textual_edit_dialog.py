from __future__ import annotations
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QLineEdit,
    QCheckBox, QPushButton, QFileDialog
)


class TextualEditDialog(QDialog):
    def __init__(
        self,
        parent=None,
        texto: str = "",
        nombre: str = "",
        cargo: str = "",
        con_foto: bool = False,
        foto_path: str = "",
        foto_epigrafe: str = "",
        textual_limit: int = 220,
        epigrafe_limit: int = 90
    ):
        super().__init__(parent)
        self.setWindowTitle("Editar textual")
        self.setModal(True)
        self.resize(640, 420)
        self.textual_limit = textual_limit
        self.epigrafe_limit = epigrafe_limit

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.lbl_info = QLabel("")
        root.addWidget(self.lbl_info)

        root.addWidget(QLabel("Textual"))
        self.ed_texto = QPlainTextEdit()
        self.ed_texto.setPlainText(texto)
        root.addWidget(self.ed_texto, 2)

        row = QHBoxLayout()
        self.ed_nombre = QLineEdit()
        self.ed_nombre.setPlaceholderText("Nombre del orador")
        self.ed_nombre.setText(nombre)
        self.ed_cargo = QLineEdit()
        self.ed_cargo.setPlaceholderText("Cargo")
        self.ed_cargo.setText(cargo)
        row.addWidget(self.ed_nombre, 1)
        row.addWidget(self.ed_cargo, 1)
        root.addLayout(row)

        row2 = QHBoxLayout()
        self.chk_foto = QCheckBox("Con foto")
        self.chk_foto.setChecked(con_foto)
        row2.addWidget(self.chk_foto)
        row2.addStretch(1)
        root.addLayout(row2)

        foto_row = QHBoxLayout()
        self.btn_pick = QPushButton("Elegir foto...")
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.ed_foto_path = QLineEdit()
        self.ed_foto_path.setReadOnly(True)
        self.ed_foto_path.setText(foto_path)
        foto_row.addWidget(self.btn_pick, 0)
        foto_row.addWidget(self.ed_foto_path, 1)
        root.addLayout(foto_row)

        self.ed_foto_epigrafe = QLineEdit()
        self.ed_foto_epigrafe.setPlaceholderText(f"Epígrafe foto (máx {epigrafe_limit})")
        self.ed_foto_epigrafe.setText(foto_epigrafe)
        root.addWidget(self.ed_foto_epigrafe)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)

        self.btn_pick.clicked.connect(self._pick_photo)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)
        self.ed_texto.textChanged.connect(self._refresh_info)
        self.chk_foto.toggled.connect(self._refresh_info)
        self._refresh_info()

    def _apply_enabled_state(self):
        enabled = self.chk_foto.isChecked()
        self.btn_pick.setEnabled(enabled)
        self.ed_foto_epigrafe.setEnabled(enabled)
        if not enabled:
            self.ed_foto_path.setText("")
            self.ed_foto_epigrafe.setText("")

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar foto", "",
            "Imágenes (*.png *.jpg *.jpeg *.webp);;Todos (*.*)"
        )
        if path:
            self.ed_foto_path.setText(path)
            self._refresh_info()

    def _refresh_info(self):
        self._apply_enabled_state()
        txt = self.ed_texto.toPlainText().strip()
        cc = len(txt)
        over = cc - self.textual_limit
        if over > 0:
            self.lbl_info.setText(f"Caracteres: {cc} / {self.textual_limit}  (+{over} excede)")
            self.lbl_info.setStyleSheet("color: #ff6b6b;")
        else:
            self.lbl_info.setText(f"Caracteres: {cc} / {self.textual_limit}")
            self.lbl_info.setStyleSheet("color: rgba(255,255,255,0.7);")

    def get_result(self) -> dict:
        txt = self.ed_texto.toPlainText().strip()
        con_foto = self.chk_foto.isChecked()
        foto = None
        if con_foto:
            p = self.ed_foto_path.text().strip()
            if p:
                foto = {"path": p, "epigrafe": self.ed_foto_epigrafe.text().strip()}
        return {
            "texto": txt,
            "orador_nombre": self.ed_nombre.text().strip(),
            "orador_cargo": self.ed_cargo.text().strip(),
            "con_foto": con_foto,
            "foto": foto,
        }
