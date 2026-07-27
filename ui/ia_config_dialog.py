"""
Diálogo de configuración de la IA (OpenAI):
  - API key → se guarda en el vault del SO (Windows Credential Manager).
  - Modelo → config.ini [IA] model.
  - Reescritura automática al guardar/importar → config.ini [IA] auto_enabled.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QCheckBox,
    QDialogButtonBox, QLabel, QPushButton, QHBoxLayout,
)

from config.config import config_global

MODELOS = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini"]


class IAConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar IA (OpenAI)")
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        intro = QLabel(
            "La API key se guarda de forma segura en el Administrador de "
            "credenciales de Windows, nunca en texto plano."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: rgba(255,255,255,0.7);")
        lay.addWidget(intro)

        form = QFormLayout()

        # API key con botón mostrar/ocultar
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-...")
        existing = config_global.openai_api_key
        if existing:
            self.ed_key.setText(existing)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.ed_key, 1)
        self.btn_ver = QPushButton("👁")
        self.btn_ver.setFixedWidth(36)
        self.btn_ver.setCheckable(True)
        self.btn_ver.setCursor(Qt.PointingHandCursor)
        self.btn_ver.toggled.connect(self._toggle_echo)
        key_row.addWidget(self.btn_ver)
        key_wrap = QLabel()  # placeholder no usado
        form.addRow("API key:", self._wrap_row(key_row))

        # Modelo
        self.cb_modelo = QComboBox()
        self.cb_modelo.setEditable(True)
        self.cb_modelo.addItems(MODELOS)
        actual = config_global.ia_model
        idx = self.cb_modelo.findText(actual)
        if idx >= 0:
            self.cb_modelo.setCurrentIndex(idx)
        else:
            self.cb_modelo.setEditText(actual)
        form.addRow("Modelo:", self.cb_modelo)

        lay.addLayout(form)

        # Reescritura automática
        self.chk_auto = QCheckBox(
            "Reescribir automáticamente toda la nota con IA al guardar/importar"
        )
        self.chk_auto.setChecked(config_global.ia_auto_enabled)
        lay.addWidget(self.chk_auto)
        aviso = QLabel(
            "Con esta opción activada, cada nota se reescribe sola al guardarla. "
            "Siempre se conserva el texto original (podés deshacer campo por campo)."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 11px;")
        lay.addWidget(aviso)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._guardar)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _wrap_row(inner_layout):
        from PyQt5.QtWidgets import QWidget
        w = QWidget()
        w.setLayout(inner_layout)
        return w

    def _toggle_echo(self, ver: bool):
        self.ed_key.setEchoMode(QLineEdit.Normal if ver else QLineEdit.Password)

    def _guardar(self):
        key = self.ed_key.text().strip()
        config_global.save_openai_api_key(key)
        config_global.save_ia_model(self.cb_modelo.currentText().strip())
        config_global.save_ia_auto_enabled(self.chk_auto.isChecked())
        self.accept()
