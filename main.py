# main.py
import os
import sys

# Fuerza a requests a no usar simplejson bajo ninguna circunstancia
sys.modules["simplejson"] = None

from config.config import Config
from utils.app_logger import setup_logging, get_logger

# === Inicializar logging antes de cualquier import de módulos app ===
setup_logging(Config.DATA_DIR / "logs")
_log = get_logger("main")
_log.info("Aplicación iniciada.")

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import QSharedMemory
from controller.controller import ArmadorController
from ui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # === Instancia única (bloqueo duro) ===
    # Evita que un proceso anterior colgado (zombie con su ChromeWatcher aún
    # escaneando Downloads) coexista con una instancia nueva e intercepte las
    # descargas con código viejo. Windows libera el segmento al morir el proceso.
    _single = QSharedMemory("ArmadorHuarpe_SingleInstance_v1")
    if not _single.create(1):
        _log.error("Otra instancia ya está corriendo. Abortando (PID=%d).", os.getpid())
        QMessageBox.critical(
            None,
            "ArmadorHuarpe ya está abierto",
            "Ya hay una instancia de ArmadorHuarpe en ejecución (o quedó un proceso "
            "python.exe colgado de un cierre anterior).\n\nCerrala / matá ese proceso "
            "antes de abrir una nueva las descargas.",
        )
        sys.exit(1)
    # Mantener _single referenciado mientras viva la app (que no lo recoja el GC).

    app.aboutToQuit.connect(lambda: _log.info("aboutToQuit (PID=%d)", os.getpid()))

    QApplication.setStyle("Fusion")
    palette = QPalette()

    # Fondo y textos
    palette.setColor(QPalette.Window, QColor("#101820"))
    palette.setColor(QPalette.WindowText, QColor("#e2e8f0"))
    palette.setColor(QPalette.Base, QColor("#0f172a"))
    palette.setColor(QPalette.AlternateBase, QColor("#1e293b"))
    palette.setColor(QPalette.ToolTipBase, QColor("#1e293b"))
    palette.setColor(QPalette.ToolTipText, QColor("#e2e8f0"))
    palette.setColor(QPalette.Text, QColor("#e2e8f0"))
    palette.setColor(QPalette.Button, QColor("#101820"))
    palette.setColor(QPalette.ButtonText, QColor("#e2e8f0"))
    palette.setColor(QPalette.Highlight, QColor("#e7885f"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))

    QApplication.setPalette(palette)

    app.setStyleSheet(
        "QToolTip {"
        "  background-color: #1e293b;"
        "  color: #e2e8f0;"
        "  border: 1px solid #475569;"
        "  border-radius: 4px;"
        "  padding: 4px 8px;"
        "  font-size: 12px;"
        "}"
    )


   

    controller = ArmadorController()
    ventana = MainWindow(controller)
    #screen_geometry = QApplication.desktop().availableGeometry()
    #ventana.resize(screen_geometry.width(), screen_geometry.height())
    #ventana.show()
    
    ventana.showMaximized()
    sys.exit(app.exec_())
