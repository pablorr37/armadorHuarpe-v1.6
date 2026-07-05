"""
CalibradorOverlay — asistente de calibración por áreas para el Armado automático.

Modelo de dos piezas, pensado para VER Quark y marcar coordenadas SIN interactuar
realmente con Quark:

  * `_CaptureLayer`: capa a pantalla completa **casi invisible** (alpha 1 → no oscurece,
    Quark se ve tal cual) que permanece activa durante toda la calibración. Captura el
    clic/arrastre y guarda la coordenada; el clic NO llega a Quark (no hay interacción
    real). Mientras arrastrás, solo se pinta el rectángulo de selección (naranja); el
    resto de la pantalla queda transparente.

  * `_PanelCalib`: panel flotante chico (bottom-center, arrastrable) que NO roba foco
    (WA_ShowWithoutActivating + WindowDoesNotAcceptFocus). Muestra el paso actual y los
    botones Atrás / Saltar / Cancelar. Se apila por encima de la capa.

Pasos desde `services.armado_auto_schema.pasos_expandidos()`. Guarda en config.ini [AUTO]
(punto → un clic → save_auto_coord; área → un arrastre → save_auto_area).
"""
from __future__ import annotations

import logging
from PyQt5.QtCore import Qt, QRect, QPoint, QObject
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QApplication,
    QInputDialog, QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QComboBox,
)

from config.config import config_global
from services.armado_auto_schema import (
    pasos_expandidos, normalizar_seccion, RECURSOS_MOVIBLES, AVISO_TIPOS, token_aviso,
)
from services.quark_auto import QuarkAutomator


def _secciones_disponibles():
    """Lista de secciones normalizadas del config del usuario ([SECCIONES] en config.ini)."""
    try:
        secs = {normalizar_seccion(s) for s in config_global.secciones if s and s.strip()}
    except Exception:
        secs = set()
    return sorted(secs)


def _elegir_secciones(parent, titulo, seleccionadas):
    """Diálogo con checklist de secciones. Devuelve lista (normalizada) o None si cancela."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(titulo)
    lay = QVBoxLayout(dlg)
    lista = QListWidget(dlg)
    sel = set(seleccionadas or [])
    for s in _secciones_disponibles():
        it = QListWidgetItem(s)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if s in sel else Qt.Unchecked)
        lista.addItem(it)
    lay.addWidget(lista)
    botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
    botones.accepted.connect(dlg.accept)
    botones.rejected.connect(dlg.reject)
    lay.addWidget(botones)
    if dlg.exec_() != QDialog.Accepted:
        return None
    return [lista.item(i).text() for i in range(lista.count())
            if lista.item(i).checkState() == Qt.Checked]

_log = logging.getLogger(__name__)

_ACENTO = "#e7885f"
_PANEL_BG = "#1e293b"
_TEXTO = "#e2e8f0"
_UMBRAL_DRAG = 6   # px: por debajo de esto un movimiento cuenta como "clic" (punto)


class _CaptureLayer(QWidget):
    """Capa transparente a pantalla completa que captura clic/arrastre (no toca Quark)."""

    def __init__(self, on_mark, on_key):
        super().__init__(None)
        self._on_mark = on_mark      # (grect: QRect, gpt: QPoint, fue_drag: bool)
        self._on_key = on_key        # (key)
        self._origin = None
        self._rect = None
        self._selecting = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self._geo = QApplication.desktop().screenGeometry()
        self.setGeometry(self._geo)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        self._selecting = True
        self._origin = ev.pos()
        self._rect = QRect(self._origin, self._origin)
        self.update()

    def mouseMoveEvent(self, ev):
        if self._selecting and (ev.buttons() & Qt.LeftButton):
            self._rect = QRect(self._origin, ev.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, ev):
        if not self._selecting:
            return
        self._selecting = False
        rect = QRect(self._origin, ev.pos()).normalized()
        fue_drag = (abs(ev.pos().x() - self._origin.x()) > _UMBRAL_DRAG or
                    abs(ev.pos().y() - self._origin.y()) > _UMBRAL_DRAG)
        gtl = self.mapToGlobal(rect.topLeft())
        gpt = self.mapToGlobal(ev.pos())
        grect = QRect(gtl.x(), gtl.y(), max(rect.width(), 8), max(rect.height(), 8))
        self._rect = None
        self.update()
        if callable(self._on_mark):
            self._on_mark(grect, gpt, fue_drag)

    def keyPressEvent(self, ev):
        if callable(self._on_key):
            self._on_key(ev.key())

    def paintEvent(self, _ev):
        p = QPainter(self)
        # Fondo con alpha=1: imperceptible, pero hace que TODA la pantalla capture el clic
        # (con alpha 0, Windows dejaría pasar el clic a Quark). No oscurece la vista.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        if self._rect:
            p.fillRect(self._rect, QColor(231, 136, 95, 55))
            pen = QPen(QColor(_ACENTO))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(self._rect)
        p.end()


class _PanelCalib(QWidget):
    """Panel flotante que NO roba el foco (Quark se ve; el clic lo captura la capa)."""

    def __init__(self, on_atras, on_saltar, on_cancelar, on_config=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            f"QWidget{{background:{_PANEL_BG};border:1px solid rgba(255,255,255,0.15);"
            "border-radius:12px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        self._lbl_paso = QLabel(self)
        self._lbl_paso.setStyleSheet(f"QLabel{{color:{_ACENTO};font-weight:bold;font-size:12px;border:none;}}")
        self._lbl_desc = QLabel(self)
        self._lbl_desc.setWordWrap(True)
        self._lbl_desc.setStyleSheet(f"QLabel{{color:{_TEXTO};font-size:14px;border:none;}}")
        self._lbl_hint = QLabel(
            "Hacé un CLIC (punto) o ARRASTRÁ (área) sobre Quark. El clic no afecta a Quark: "
            "solo guarda la posición. El panel se puede mover.", self)
        self._lbl_hint.setWordWrap(True)
        self._lbl_hint.setStyleSheet("QLabel{color:#94a3b8;font-size:11px;border:none;}")

        self._btn_atras = QPushButton("Atrás", self)
        self._btn_saltar = QPushButton("Saltar", self)
        self._btn_cancelar = QPushButton("Cancelar", self)
        for b in (self._btn_atras, self._btn_saltar, self._btn_cancelar):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:#334155;color:#f1f5f9;border:none;border-radius:8px;"
                "padding:7px 14px;font-size:12px;}QPushButton:hover{background:#475569;}"
            )
        self._btn_atras.clicked.connect(on_atras)
        self._btn_saltar.clicked.connect(on_saltar)
        self._btn_cancelar.clicked.connect(on_cancelar)

        # Configuración de maquetas (sección + tipo de aviso + excluidas).
        self._btn_config = QPushButton("Configuración de maquetas", self)
        self._btn_config.setCursor(Qt.PointingHandCursor)
        self._btn_config.setStyleSheet(
            f"QPushButton{{background:transparent;color:{_ACENTO};border:1px solid {_ACENTO};"
            "border-radius:8px;padding:6px 12px;font-size:12px;}"
            "QPushButton:hover{background:rgba(231,136,95,0.15);}"
        )
        if on_config:
            self._btn_config.clicked.connect(on_config)
        fila_maq = QHBoxLayout()
        fila_maq.setSpacing(8)
        fila_maq.addWidget(self._btn_config)
        fila_maq.addStretch(1)

        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(self._btn_atras)
        fila.addStretch(1)
        fila.addWidget(self._btn_saltar)
        fila.addWidget(self._btn_cancelar)

        lay.addWidget(self._lbl_paso)
        lay.addWidget(self._lbl_desc)
        lay.addWidget(self._lbl_hint)
        lay.addLayout(fila_maq)
        lay.addLayout(fila)

        self.setFixedWidth(480)
        self.adjustSize()
        self._instalar_drag()

    def set_texto(self, paso_txt: str, desc_txt: str):
        self._lbl_paso.setText(paso_txt)
        self._lbl_desc.setText(desc_txt)
        self.adjustSize()

    def posicionar_inicial(self):
        geo = QApplication.desktop().screenGeometry()
        pw, ph = self.width(), self.height()
        saved = config_global.auto_coord("calib_panel")
        if saved:
            x, y = saved
        else:
            x = geo.width() // 2 - pw // 2
            y = geo.height() - ph - 60
        x = max(8, min(int(x), geo.width() - pw - 8))
        y = max(8, min(int(y), geo.height() - ph - 8))
        self.move(x, y)

    def _instalar_drag(self):
        geo = QApplication.desktop().screenGeometry()
        drag = {"activo": False, "moved": False, "g0": None, "p0": None}

        def press(ev):
            if ev.button() == Qt.LeftButton:
                drag.update(activo=True, moved=False, g0=ev.globalPos(), p0=self.pos())

        def move(ev):
            if drag["activo"] and (ev.buttons() & Qt.LeftButton):
                delta = ev.globalPos() - drag["g0"]
                if delta.manhattanLength() > 4:
                    drag["moved"] = True
                nx = max(8, min(drag["p0"].x() + delta.x(), geo.width() - self.width() - 8))
                ny = max(8, min(drag["p0"].y() + delta.y(), geo.height() - self.height() - 8))
                self.move(nx, ny)

        def release(ev):
            if drag["activo"]:
                drag["activo"] = False
                if drag["moved"]:
                    config_global.save_auto_coord("calib_panel", self.x(), self.y())

        for w in (self, self._lbl_paso, self._lbl_desc, self._lbl_hint):
            w.mousePressEvent = press
            w.mouseMoveEvent = move
            w.mouseReleaseEvent = release


class CalibradorController(QObject):
    """Orquesta capa de captura (siempre activa) + panel, recorriendo los pasos."""

    def __init__(self, pasos=None, on_finish=None, parent=None, seccion=None, aviso=None):
        super().__init__(parent)
        self._pasos = pasos if pasos is not None else pasos_expandidos()
        self._on_finish = on_finish
        self._parent = parent
        self._seccion = normalizar_seccion(seccion) if seccion else None
        self._aviso = aviso   # None (sin scope) o valor de AVISO_TIPOS ("" = sin aviso)
        self._idx = 0
        self._guardados = 0
        # Automatizador para clonar/arrastrar en Quark durante la calibración de recursos
        # movibles (A=origen → clon B → verificación B→C). None hasta que se necesite.
        self._auto = QuarkAutomator(simular=False)
        self._clon_recurso = None   # recurso con un clon vivo en la maqueta (para verificar)

        self._capture = _CaptureLayer(self._on_mark, self._on_key)
        self._panel = _PanelCalib(self._atras, self._saltar, self._cancelar,
                                  on_config=self._on_config_maquetas)
        self._panel.posicionar_inicial()

        # Capa primero, panel encima (para que sus botones reciban el clic).
        self._capture.show()
        self._capture.raise_()
        self._panel.show()
        self._panel.raise_()
        self._capture.setFocus()
        self._mostrar_paso()

    # ── flujo ─────────────────────────────────────────────────
    def _mostrar_paso(self):
        if self._idx >= len(self._pasos):
            self._finalizar()
            return
        if self._idx < 0:
            self._idx = 0
        paso = self._pasos[self._idx]
        total = len(self._pasos)
        if self._aviso is None:
            scope = ""   # calibración universal general
        else:
            av_label = dict(AVISO_TIPOS).get(self._aviso, token_aviso(self._aviso))
            sec_label = self._seccion if self._seccion else "Todas"
            scope = f"  ·  [{sec_label} · {av_label}]"
        self._panel.set_texto(
            f"Paso {self._idx + 1} / {total}  ·  {paso['clave']}{scope}",
            ("Hacé un CLIC sobre: " if paso["tipo"] == "punto" else "ARRASTRÁ el área de: ")
            + paso["desc"],
        )
        self._panel.raise_()

    def _clave(self, clave: str) -> str:
        """Prefija la clave según el scope. Debe coincidir con claves_cascada() del pegador:
          - aviso None            → 'clave'                 (universal general, menú "Calibrar")
          - aviso set, sin sección→ '{aviso}__clave'         (universal por aviso, "Todas")
          - aviso set, con sección→ '{sec}__{aviso}__clave'  (override sección + aviso)"""
        if self._aviso is None:
            return clave
        av = token_aviso(self._aviso)
        if self._seccion:
            return f"{self._seccion}__{av}__{clave}"
        return f"{av}__{clave}"

    def _on_mark(self, grect: QRect, gpt: QPoint, fue_drag: bool):
        if self._idx >= len(self._pasos):
            return
        paso = self._pasos[self._idx]
        clave_raw = paso["clave"]
        clave = self._clave(clave_raw)
        recurso = paso.get("recurso")
        es_movible = recurso in RECURSOS_MOVIBLES

        avanzar = True
        if paso["tipo"] == "punto":
            config_global.save_auto_coord(clave, gpt.x(), gpt.y())
        else:
            if not fue_drag:
                return  # un clic suelto en un paso de área se ignora (evita marcas accidentales)
            config_global.save_auto_area(
                clave, grect.x(), grect.y(), grect.width(), grect.height())
            # Recursos movibles: al marcar el origen se clona en Quark (para marcar B);
            # al marcar cada destino se arrastra el clon B→C para verificar.
            if es_movible and clave_raw.endswith("_src"):
                self._clonar_en_quark(recurso, clave)
            elif es_movible and "_dst_" in clave_raw:
                avanzar = self._verificar_destino(recurso, clave)

        if avanzar:
            self._guardados += 1
            self._idx += 1
        self._mostrar_paso()

    # ── acciones sobre Quark (calibración de recursos movibles) ──
    def _con_quark(self, fn):
        """Oculta las capas del calibrador, enfoca Quark, corre `fn` (pyautogui) y restaura
        las capas. Sin ocultar, la capa de captura (pantalla completa) recibiría los clics."""
        self._capture.hide()
        self._panel.hide()
        QApplication.processEvents()
        try:
            if self._auto.focus_quark(timeout=8.0):
                fn()
        except Exception as e:
            _log.warning("Acción de Quark en calibración falló: %s", e)
        finally:
            self._capture.show()
            self._capture.raise_()
            self._panel.show()
            self._panel.raise_()
            self._capture.setFocus()
            QApplication.processEvents()

    def _clonar_en_quark(self, recurso: str, clave_src: str):
        """Selecciona la caja de origen (centro del área recién marcada) y la clona (Ctrl+D)
        para que el usuario pueda marcar dónde quedó el clon (B)."""
        self._clon_recurso = None
        centro = config_global.auto_centro(clave_src)
        if not centro:
            return

        def _accion():
            # Dejar asentar el mouse-up físico del arrastre con el que se marcó el área: si el
            # clic sintético de selección llega demasiado pronto, Windows lo fusiona en un DOBLE
            # clic y, en un recurso agrupado, entra al grupo y clona solo un box hijo.
            self._auto.esperar(0.6)
            self._auto.click(int(centro[0]), int(centro[1]))  # un solo clic: selecciona el grupo
            self._auto.esperar(0.2)
            self._auto.clonar()

        self._con_quark(_accion)
        self._clon_recurso = recurso

    def _verificar_destino(self, recurso: str, clave_dst: str) -> bool:
        """Arrastra el clon de B al destino C recién marcado para que el usuario verifique,
        y hace UN Ctrl+Z (el clon vuelve a B). Devuelve True para avanzar, False para repetir
        el mismo destino. El clon se borra manualmente al terminar el recurso."""
        if self._clon_recurso != recurso:
            return True   # no hay clon vivo de este recurso (se saltó el origen) → solo guardar
        b = config_global.auto_centro(self._clave(f"{recurso}_clon"))
        c = config_global.auto_centro(clave_dst)
        if not (b and c):
            return True

        self._capture.hide()
        self._panel.hide()
        QApplication.processEvents()
        avanzar = True
        try:
            if self._auto.focus_quark(timeout=8.0):
                self._auto.arrastrar((int(b[0]), int(b[1])), (int(c[0]), int(c[1])))
            from PyQt5.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self._parent, "Verificar posición",
                f"¿El {recurso} quedó en su lugar?\n\nSí = seguir · No = repetir este destino.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if self._auto.focus_quark(timeout=8.0):
                self._auto.deshacer(1)   # un solo Ctrl+Z: deshace el arrastre; el clon vuelve a B
            avanzar = (r == QMessageBox.Yes)
        except Exception as e:
            _log.warning("Verificación de destino falló: %s", e)
        finally:
            self._capture.show()
            self._capture.raise_()
            self._panel.show()
            self._panel.raise_()
            self._capture.setFocus()
            QApplication.processEvents()
        return avanzar

    def _on_config_maquetas(self):
        """Dialog con dos desplegables (sección + tipo de aviso) para scopear la calibración a
        una maqueta concreta, más acceso a 'Maquetas excluidas'. Al aceptar, relanza el
        calibrador scopeado a (sección, aviso)."""
        secs = _secciones_disponibles()
        if not secs:
            return
        # La capa de captura (pantalla completa, always-on-top) se traga los clics del dialog:
        # ocultar capa + panel mientras el dialog está abierto (se restauran si se cancela).
        self._capture.hide()
        self._panel.hide()
        QApplication.processEvents()

        dlg = QDialog(self._parent)
        dlg.setWindowTitle("Configuración de maquetas")
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)

        lay.addWidget(QLabel("Sección de la maqueta abierta en Quark:"))
        cbo_sec = QComboBox(dlg)
        # Opción por defecto: universal para el aviso elegido (cualquier sección). Elegí una
        # sección real solo para un override puntual de esa sección + aviso.
        TODAS = "Todas las secciones (universal)"
        cbo_sec.addItem(TODAS)
        cbo_sec.addItems(secs)
        if self._seccion and self._seccion in secs:
            cbo_sec.setCurrentText(self._seccion)
        lay.addWidget(cbo_sec)

        lay.addWidget(QLabel("Tipo de aviso de la maqueta:"))
        cbo_av = QComboBox(dlg)
        for val, label in AVISO_TIPOS:
            cbo_av.addItem(label, val)
        if self._aviso is not None:
            i = cbo_av.findData(self._aviso)
            if i >= 0:
                cbo_av.setCurrentIndex(i)
        lay.addWidget(cbo_av)

        btn_excl = QPushButton("Maquetas excluidas…", dlg)
        btn_excl.clicked.connect(self._on_excluidas)
        lay.addWidget(btn_excl)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)

        if dlg.exec_() != QDialog.Accepted:
            # Cancelado: restaurar las capas del calibrador y seguir donde estábamos.
            self._capture.show()
            self._capture.raise_()
            self._panel.show()
            self._panel.raise_()
            self._capture.setFocus()
            QApplication.processEvents()
            return
        sec_text = cbo_sec.currentText()
        sec = None if sec_text == TODAS else normalizar_seccion(sec_text)
        aviso = cbo_av.currentData()
        av_label = dict(AVISO_TIPOS).get(aviso, aviso)
        sec_label = sec if sec else "Todas las secciones"
        alcance = (f"la sección «{sec_label}» con aviso «{av_label}»" if sec
                   else f"TODAS las secciones con aviso «{av_label}»")
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(
            self._parent, "Configuración de maquetas",
            f"Abrí en Quark la maqueta «{sec_label} · {av_label}» (maximizada y al zoom correcto) "
            f"antes de calibrar. Se calibrará para {alcance}.")
        # Reiniciar el asistente scopeado a esa maqueta (sección + aviso).
        self._cerrar()
        lanzar_calibrador(parent=self._parent, on_finish=self._on_finish,
                          seccion=sec, aviso=aviso)

    def _on_excluidas(self):
        actuales = config_global.auto_excluidas()
        elegidas = _elegir_secciones(self._parent, "Maquetas excluidas (no se automatizan)", actuales)
        if elegidas is None:
            return
        config_global.save_auto_excluidas([normalizar_seccion(s) for s in elegidas])
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(
            self._parent, "Maquetas excluidas",
            "Guardado. El Armado automático saltará las secciones marcadas.")

    def _on_key(self, key):
        if key == Qt.Key_Escape:
            self._cancelar()

    def _atras(self):
        if self._idx > 0:
            self._idx -= 1
        self._mostrar_paso()

    def _saltar(self):
        self._idx += 1
        self._mostrar_paso()

    def _cancelar(self):
        self._cerrar()

    def _finalizar(self):
        # Cerrar las capas ANTES del callback: si muestra un QMessageBox, la capa de captura
        # (pantalla completa, always-on-top) lo dejaría inaccesible.
        self._cerrar()
        if callable(self._on_finish):
            self._on_finish(self._guardados)

    def _cerrar(self):
        for w in (self._capture, self._panel):
            try:
                w.close()
            except Exception:
                pass


_ctrl_ref = None


def lanzar_calibrador(parent=None, pasos=None, on_finish=None, seccion=None, aviso=None):
    """Crea (cerrando el anterior si existiera) y muestra el asistente de calibración."""
    global _ctrl_ref
    if _ctrl_ref is not None:
        try:
            _ctrl_ref._cerrar()
        except Exception:
            pass
    _ctrl_ref = CalibradorController(pasos=pasos, on_finish=on_finish, parent=parent,
                                     seccion=seccion, aviso=aviso)
    return _ctrl_ref
