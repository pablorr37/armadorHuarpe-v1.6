from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QKeySequence, QColor, QBrush
from services.shortcut_manager import ShortcutManager
import configparser
from config.config import Config


class ShortcutConfigDialog(QDialog):
    """
    Cuadro de configuración de atajos de teclado.
    Permite ver, editar, validar y guardar combinaciones personalizadas.
    Resalta conflictos de atajos duplicados.
    Lee las etiquetas de acciones desde config.ini ([SHORTCUT_LABELS]).
    """
    shortcuts_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de atajos de teclado")
        self.resize(540, 420)

        self.manager = ShortcutManager()
        self._editing_row = None
        self._pressed_mods = set()
        self._single_key_timer = None  # para la tolerancia de teclas únicas

        self.labels = self._load_labels_from_config()
        self._build_ui()
        self._load_shortcuts()

    # ------------------------------------------------------------
    # Cargar etiquetas desde config.ini
    # ------------------------------------------------------------
    def _load_labels_from_config(self) -> dict:
        path = Config.CONFIG_FILE
        cfg = configparser.ConfigParser()
        if path.exists():
            cfg.read(str(path), encoding="utf-8")

        if cfg.has_section("SHORTCUT_LABELS"):
            return dict(cfg.items("SHORTCUT_LABELS"))
        return {}

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Acción", "Atajo"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.table.cellDoubleClicked.connect(self._on_cell_double_click)

        btn_layout = QHBoxLayout()
        self.btn_assign = QPushButton("Asignar")
        self.btn_reset = QPushButton("Restablecer por defecto")
        self.btn_save = QPushButton("Guardar cambios")
        self.btn_close = QPushButton("Cerrar")

        btn_layout.addWidget(self.btn_assign)
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self.btn_assign.clicked.connect(self._start_assignment)
        self.btn_reset.clicked.connect(self._reset_defaults)
        self.btn_save.clicked.connect(self._save)
        self.btn_close.clicked.connect(self.close)

    # ------------------------------------------------------------
    # Carga inicial
    # ------------------------------------------------------------
    def _load_shortcuts(self):
        shortcuts = self.manager.all()
        self.table.setRowCount(len(shortcuts))
        for i, (key, seq) in enumerate(shortcuts.items()):
            action_label = self.labels.get(key, key)
            item_action = QTableWidgetItem(action_label)
            item_action.setData(Qt.UserRole, key)
            item_seq = QTableWidgetItem(seq)
            self.table.setItem(i, 0, item_action)
            self.table.setItem(i, 1, item_seq)
        self._validate_duplicates()

    # ------------------------------------------------------------
    # Captura de atajos
    # ------------------------------------------------------------
    def _on_cell_double_click(self, row: int, column: int):
        if column == 1:
            self.table.selectRow(row)
            self._start_assignment()

    def _start_assignment(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atajo", "Seleccioná una acción para asignar.")
            return

        self._editing_row = row
        self._pressed_mods.clear()
        self.table.setItem(row, 1, QTableWidgetItem("Presioná la nueva combinación..."))
        self.grabKeyboard()

    def keyPressEvent(self, event):
        if self._editing_row is None:
            return super().keyPressEvent(event)

        key = event.key()
        mods = event.modifiers()

        # Ignorar teclas solas (Ctrl, Shift, Alt, Meta)
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return

        seq = QKeySequence(mods | key).toString()

        # --- NUEVO: manejo de teclas únicas con 5 s de tolerancia ---
        if not mods and not (Qt.Key_F1 <= key <= Qt.Key_F35):
            # Mostrar advertencia temporal
            self.table.setItem(
                self._editing_row, 1,
                QTableWidgetItem(f"Tecla '{seq}' detectada. Esperando 5 s para confirmar...")
            )

            # Cancelar si ya había uno pendiente
            if self._single_key_timer:
                self._single_key_timer.stop()

            # Crear un temporizador para confirmar
            self._single_key_timer = QTimer(self)
            self._single_key_timer.setSingleShot(True)
            self._single_key_timer.timeout.connect(lambda: self._confirm_single_key(seq))
            self._single_key_timer.start(5000)  # 5 segundos
            return

        # --- Combinaciones normales ---
        self.table.setItem(self._editing_row, 1, QTableWidgetItem(seq))
        self._validate_duplicates()
        self._editing_row = None
        self.releaseKeyboard()

    def _confirm_single_key(self, seq: str):
        """Confirma una tecla única después del tiempo de espera."""
        if self._editing_row is None:
            return
        self.table.setItem(self._editing_row, 1, QTableWidgetItem(seq))
        self._validate_duplicates()
        self._editing_row = None
        self.releaseKeyboard()

    # ------------------------------------------------------------
    # Validación de duplicados
    # ------------------------------------------------------------
    def _validate_duplicates(self):
        seen = {}
        duplicates = set()
        for i in range(self.table.rowCount()):
            seq = self.table.item(i, 1).text().strip()
            if seq in seen:
                duplicates.add(seq)
            else:
                seen[seq] = i

        for i in range(self.table.rowCount()):
            item = self.table.item(i, 1)
            seq = item.text().strip()
            if seq in duplicates:
                item.setBackground(QBrush(QColor(255, 180, 180)))
            else:
                item.setBackground(QBrush(Qt.white))

    # ------------------------------------------------------------
    # Guardado y restauración
    # ------------------------------------------------------------
    def _save(self):
        duplicates = self._find_duplicates()
        if duplicates:
            QMessageBox.warning(
                self, "Conflictos",
                "No podés guardar mientras existan atajos duplicados.\n\nDuplicados:\n" +
                "\n".join(sorted(duplicates))
            )
            return

        for i in range(self.table.rowCount()):
            key = self.table.item(i, 0).data(Qt.UserRole)
            seq = self.table.item(i, 1).text().strip()
            self.manager.save_shortcut(key, seq)

        self.shortcuts_changed.emit()
        QMessageBox.information(self, "Atajos", "Cambios guardados correctamente.")

    def _find_duplicates(self):
        seen = set()
        duplicates = set()
        for i in range(self.table.rowCount()):
            seq = self.table.item(i, 1).text().strip()
            if seq in seen:
                duplicates.add(seq)
            seen.add(seq)
        return duplicates

    def _reset_defaults(self):
        resp = QMessageBox.question(
            self,
            "Restablecer",
            "¿Querés restablecer todos los atajos a los valores por defecto?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if resp == QMessageBox.Yes:
            self.manager.reset_to_defaults()
            self._load_shortcuts()
