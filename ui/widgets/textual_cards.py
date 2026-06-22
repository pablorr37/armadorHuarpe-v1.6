from __future__ import annotations
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame


class TextualCard(QFrame):
    remove_requested = pyqtSignal()
    edit_requested = pyqtSignal()
    selected_changed = pyqtSignal(bool)
    con_foto_changed = pyqtSignal(bool)

    def __init__(self, preview_text: str, counter_text: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Text preview
        self.lbl_text = QLabel(preview_text)
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setStyleSheet("border: none; background: transparent;")
        lay.addWidget(self.lbl_text)

        # Bottom row: remove | counter | foto toggle
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        _btn_style = (
            "QPushButton { font-size: 10px; padding: 0 6px;"
            " background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);"
            " border-radius: 4px; color: rgba(255,255,255,0.5); }"
            " QPushButton:hover { background: rgba(255,255,255,0.12); color: #e2e8f0; }"
        )

        self.btn_x = QPushButton("× Quitar")
        self.btn_x.setFixedHeight(22)
        self.btn_x.setToolTip("Quitar este candidato de la lista")
        self.btn_x.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 0 6px;"
            " background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);"
            " border-radius: 4px; color: rgba(255,255,255,0.5); }"
            " QPushButton:hover { background: rgba(255,80,80,0.18); color: #ff8080; border-color: rgba(255,80,80,0.4); }"
        )

        self.btn_edit = QPushButton("✎ Editar")
        self.btn_edit.setFixedHeight(22)
        self.btn_edit.setToolTip("Editar este textual")
        self.btn_edit.setStyleSheet(_btn_style)

        self.lbl_counter = QLabel(counter_text)
        self.lbl_counter.setStyleSheet(
            "color: rgba(255,255,255,0.40); font-size: 10px; border: none; background: transparent;"
        )

        self.btn_foto = QPushButton("📷 Con foto")
        self.btn_foto.setCheckable(True)
        self.btn_foto.setFixedHeight(22)
        self.btn_foto.setToolTip("Incluir foto con este textual")
        self.btn_foto.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 0 8px;"
            " background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);"
            " border-radius: 4px; color: rgba(255,255,255,0.5); }"
            " QPushButton:hover { background: rgba(255,255,255,0.12); color: #e2e8f0; }"
            " QPushButton:checked { background: rgba(100,180,255,0.22); border-color: rgba(100,180,255,0.6);"
            " color: #82b4ff; font-weight: bold; }"
        )

        bottom.addWidget(self.btn_x)
        bottom.addWidget(self.btn_edit)
        bottom.addStretch(1)
        bottom.addWidget(self.lbl_counter)
        bottom.addWidget(self.btn_foto)
        lay.addLayout(bottom)

        self.btn_x.clicked.connect(self.remove_requested.emit)
        self.btn_edit.clicked.connect(self.edit_requested.emit)
        self.btn_foto.toggled.connect(self.con_foto_changed.emit)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._selected = not self._selected
            self.selected_changed.emit(self._selected)
        super().mousePressEvent(e)

    def set_counter(self, s: str):
        self.lbl_counter.setText(s)

    def set_selected(self, sel: bool):
        self._selected = sel
        self.setProperty("selected", sel)
        self.style().unpolish(self)
        self.style().polish(self)
