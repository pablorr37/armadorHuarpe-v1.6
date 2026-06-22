from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QMessageBox, QHBoxLayout
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
import logging
_log = logging.getLogger(__name__)



class DialogoMono(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("MONO de edición")
        self.setMinimumSize(800, 600)

        layout = QVBoxLayout()

        self.instrucciones = QLabel(
            "Podés consultar o editar el contenido del MONO.\n"
            "Usá 'Procesar' solo si querés aplicar los cambios a la grilla."
        )
        self.instrucciones.setWordWrap(True)
        layout.addWidget(self.instrucciones)

        self.text_edit = QPlainTextEdit()
        fuente = QFont("Arial", 12)
        self.text_edit.setFont(fuente)
        self.text_edit.setPlaceholderText(
            "MONO MIÉRCOLES 15 DE OCTUBRE (VACÍA)\nP2. (VACÍA)\nP3. (MEDIA)\n..."
        )

        # -------------------------------------------
        # MOSTRAR EL MONO ACTUAL GENERADO DESDE Pnn.ini
        # -------------------------------------------
        try:
            mono_generado = self.controller.generar_mono()
            if mono_generado:
                self.text_edit.setPlainText(mono_generado)
        except Exception as e:
            _log.info("[MONO] Error al generar mono:", e)

        layout.addWidget(self.text_edit)

        # Botones inferiores
        botones_layout = QHBoxLayout()
        self.boton_procesar = QPushButton("Procesar")
        self.boton_procesar.clicked.connect(self.procesar_mono)
        self.boton_salir = QPushButton("Salir")
        self.boton_salir.clicked.connect(self.salir_sin_procesar)

        botones_layout.addWidget(self.boton_procesar)
        botones_layout.addWidget(self.boton_salir)
        layout.addLayout(botones_layout)

        self.setLayout(layout)

    # -------------------------
    #   Acciones de botones
    # -------------------------
    def procesar_mono(self):
        """
        Procesa el texto del MONO ingresado por el usuario.
        Si está vacío, pregunta si debe limpiarse la grilla completa.
        Si no está vacío, aplica los cambios página por página.
        """
        texto = self.text_edit.toPlainText().strip()

        # ============================================================
        #   CASO ESPECIAL: MONO VACÍO → LIMPIAR TODAS LAS PÁGINAS
        # ============================================================
        if not texto:
            resp = QMessageBox.question(
                self,
                "Limpiar MONO",
                "El texto del MONO está vacío.\n\n"
                "Se limpiarán TODOS los datos de las 16 páginas:\n"
                " • Sección\n"
                " • Avisos\n"
                " • Notas (txt_name/link)\n"
                " • mono_extra\n\n"
                "¿Desea continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if resp == QMessageBox.Yes:
                fs = self.controller.file_service

                for n in range(1, 17):
                    try:
                        # Borrar notas
                        fs.limpiar_notas(n, by="")

                        # Borrar avisos
                        fs.clear_avisos(n, by="")

                        # Borrar secciones
                        fs.clear_seccion(n, by="")

                    except Exception as e:
                        _log.info(f"[MONO] Error limpiando P{n:02d}: {e}")

                # Refrescar UI
                parent = self.parent()
                if parent:
                    parent.controller.refrescar_avisos_desde_ini()
                    parent.colorear_paginas()
                    parent.actualizar_botonera_mover_devolver()

                QMessageBox.information(
                    self,
                    "Listo",
                    "El MONO y la grilla de páginas fueron limpiados correctamente."
                )

                self.accept()
            return

        # ============================================================
        #        PROCESAMIENTO NORMAL DEL MONO (NO vacío)
        # ============================================================
        # Guardar en configuración como histórico
        #self.controller.guardar_mono(texto)

        # Procesar y obtener errores
        errores = self.controller.procesar_grilla_mono(texto)

        # Si hubo errores → notificarlos
        if errores:
            QMessageBox.warning(self, "Líneas con error", "\n".join(errores))
        else:
            QMessageBox.information(self, "Éxito", "El MONO se aplicó correctamente.")

        # Refrescar UI
        parent = self.parent()
        if parent:
            parent.controller.refrescar_avisos_desde_ini()
            parent.colorear_paginas()
            parent.actualizar_botonera_mover_devolver()

        self.accept()

    def salir_sin_procesar(self):
        self.accept()
