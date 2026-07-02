"""
AutoModeOrchestrator — Armado automático (pasos a–g).

Cuando está habilitado y el polling detecta páginas "listas para armar", las
procesa de a una, con prioridad del dorso editorial (2,3,6,7,10,11,14,15) y luego
orden numérico. Por página:
  asigna → pega (abre Quark) → [b] si el proyecto está bloqueado ([315]) aborta y
  reintenta en el próximo poll → [a] cierra cartel de fuentes → enfoca Quark →
  [c] corre el script dedicado (clic ítem + Play) → [d] firma → [e] epígrafe →
  [f] clona+arrastra textual/dato/número/QR (×3 plantillas) → [g] foto 3 col ancha
  (×3) → guarda → cierra.

Qué pasos corren se decide con la composición de la página (`fn_comp`), y dónde
están/van los recursos con la calibración por áreas (`fn_calibracion`).

La preparación en disco (asignar + pegar + abrir Quark) corre en el hilo GUI
(rápida, sin bloqueo); la parte lenta con pyautogui corre en un QThread.
"""
from __future__ import annotations

import time
import logging
import threading
from collections import deque
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from services.quark_auto import QuarkAutomator, CanceladoError
from services.armado_auto_schema import (
    PLANTILLAS, RECURSOS_MOVIBLES, recurso_activo, ZOOM_ARMADO, normalizar_seccion,
)
from config.config import config_global

_log = logging.getLogger(__name__)

PRIORIDAD_DORSO = [2, 3, 6, 7, 10, 11, 14, 15]

# Estados de fin de página
OK = "ok"
ERROR = "error"
REINTENTAR = "reintentar"          # bloqueado [315]: reintentar próximo poll
REINTENTAR_FOCO = "reintentar_foco"  # Quark no llegó al frente: reintentar (hasta 3) próximo poll
CANCELADO = "cancelado"            # kill-switch Esc×5: abortar y apagar

# Kill-switch: cuántos Esc en cuánto tiempo.
ESC_N = 5
ESC_LAPSO = 1.0   # s
MAX_REINTENTOS_FOCO = 3   # por página
MAX_PAGINAS_FALLO_FOCO = 2  # si 2 páginas distintas fallan el foco → apagar


class _EscWatcher(QThread):
    """Listener global: si se aprietan ESC_N Escapes en ≤ ESC_LAPSO s, emite `disparado`.
    Usa GetAsyncKeyState (funciona aunque el foreground sea Quark)."""
    disparado = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._run = True

    def stop(self):
        self._run = False

    def run(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
        except Exception as e:
            _log.warning("_EscWatcher: sin GetAsyncKeyState (%s); kill-switch inactivo.", e)
            return
        VK_ESCAPE = 0x1B
        prev_down = False
        marcas = deque()
        while self._run:
            try:
                estado = user32.GetAsyncKeyState(VK_ESCAPE)
                down = bool(estado & 0x8000)
                if down and not prev_down:   # flanco de pulsación
                    ahora = time.time()
                    marcas.append(ahora)
                    while marcas and (ahora - marcas[0]) > ESC_LAPSO:
                        marcas.popleft()
                    if len(marcas) >= ESC_N:
                        self.disparado.emit()
                        return
                prev_down = down
            except Exception:
                pass
            time.sleep(0.035)


def orden_prioridad(numeros) -> list:
    """Ordena las páginas listas: primero el dorso editorial (en ese orden), luego
    el resto en orden numérico. Sin duplicados."""
    s = set(int(n) for n in numeros)
    pri = [n for n in PRIORIDAD_DORSO if n in s]
    resto = sorted(n for n in s if n not in PRIORIDAD_DORSO)
    return pri + resto


class _PaginaWorker(QThread):
    """Corre la secuencia pyautogui de una página (Quark ya abierto con el qxp)."""
    terminado = pyqtSignal(int, str)    # (numero, estado: OK|ERROR|REINTENTAR)
    paso = pyqtSignal(str)

    def __init__(self, numero, automator: QuarkAutomator, coord_script, coord_play,
                 comp: dict, calib: dict, espera_apertura: float, espera_pegado: float,
                 grab_pref: str = "", parent=None):
        super().__init__(parent)
        self.numero = int(numero)
        self.automator = automator
        self.coord_script = coord_script
        self.coord_play = coord_play
        self.comp = comp or {}
        self.calib = calib or {}
        self.espera_apertura = espera_apertura
        self.espera_pegado = espera_pegado
        # Prefijo de sección para las claves de offset de agarre (autocalibración B↔C).
        self.grab_pref = grab_pref or ""

    def run(self):
        a = self.automator
        n = self.numero
        try:
            # ANTES de cualquier clic/Enter/movimiento: confirmar que Quark está al frente.
            # Espera a que abra (PC lenta / Quark cerrado); si no llega → REINTENTAR_FOCO.
            self.paso.emit(f"P{n:02d}: esperando a que Quark esté en primer plano…")
            if not a.focus_quark(timeout=self.espera_apertura + 20.0):
                self.paso.emit(f"P{n:02d}: Quark no quedó al frente → reintento en el próximo poll.")
                self.terminado.emit(n, REINTENTAR_FOCO)
                return

            # b) Proyecto bloqueado ([315], documento abierto en otra estación).
            if a.esperar_y_cerrar_dialogo_bloqueado(timeout=2.0):
                self.paso.emit(f"P{n:02d}: bloqueado [315] → reintento en el próximo poll.")
                a.cerrar()  # cerrar el qxp que abrimos, para no dejarlo colgado
                self.terminado.emit(n, REINTENTAR)
                return

            # a) Cartel de fuentes no instaladas → 'Continuar' (opcional).
            a.esperar_y_cerrar_dialogo_fuentes(timeout=4.0)
            a.esperar(0.4)

            # Zoom: dejar el documento al zoom con el que se calibró (arrastres d–g).
            # Si NO se pudo confirmar, se omiten d–g para no mover elementos equivocados.
            zoom_ok = a.set_zoom(self.calib.get("zoom"), ZOOM_ARMADO)

            # c) Pegado base con el script dedicado.
            self.paso.emit(f"P{n:02d}: corriendo el pegado…")
            if not a.click_script_y_play(self.coord_script, self.coord_play,
                                         espera=self.espera_pegado):
                self.terminado.emit(n, ERROR)
                return

            # El Play es un evento lanzado desde Python: puede disparar el cartel de fuentes.
            a.esperar_y_cerrar_dialogo_fuentes(timeout=3.0)

            # Guard: sin zoom confirmado, los arrastres calibrados caerían en el lugar
            # equivocado → se OMITEN los movimientos (la página queda pegada para terminar a mano).
            if not zoom_ok:
                self.paso.emit(f"P{n:02d}: zoom sin confirmar → se omite mover recursos (manual).")
                _log.warning("P%02d: zoom sin confirmar → se omite mover recursos (manual).", n)
            else:
                # El bot NO pega firma ni epígrafe: solo corre el script y MUEVE recursos.
                # f) Recursos movibles: clonar + arrastrar, ×3 plantillas.
                for rec in RECURSOS_MOVIBLES:
                    if recurso_activo(self.comp, rec):
                        self.paso.emit(f"P{n:02d}: colocando {rec}…")
                        self._clonar_arrastrar(a, f"{rec}_src", f"{rec}_dst", rec)

                # g) Foto a 3 columnas ancha — TEMPORALMENTE DESHABILITADO.
                #    Para reactivar: descomentar y restaurar los pasos foto* en el schema.
                # if recurso_activo(self.comp, "foto3"):
                #     self.paso.emit(f"P{n:02d}: colocando foto a 3 columnas…")
                #     self._colocar_foto3(a)

            self.paso.emit(f"P{n:02d}: guardando y cerrando…")
            a.esperar_y_cerrar_dialogo_fuentes(timeout=1.5)  # limpiar cartel antes de guardar
            a.guardar()
            a.esperar_y_cerrar_dialogo_fuentes(timeout=2.0)  # el guardado también puede dispararlo
            a.cerrar()
            a.minimizar_quark()
            self.terminado.emit(n, OK)
        except CanceladoError:
            _log.info("Worker P%02d cancelado por el usuario (Esc×5).", n)
            self.terminado.emit(n, CANCELADO)
        except Exception as e:
            _log.warning("Worker P%02d falló: %s", n, e)
            self.terminado.emit(n, ERROR)

    # ── helpers de colocación ─────────────────────────────────
    def _reemplazo_por_plantilla(self, a, clave_src: str, base_dst: str):
        """Copia el texto del box de origen y lo reemplaza (Ctrl+Alt+U) en cada plantilla."""
        src = self.calib.get(clave_src)
        if not src:
            return
        a.copiar_desde(src)
        for i in range(1, PLANTILLAS + 1):
            dst = self.calib.get(f"{base_dst}_{i}")
            if dst:
                a.reemplazar_con_atajo(dst)

    def _clonar_arrastrar(self, a, clave_src: str, base_dst: str, rec: str):
        src = self.calib.get(clave_src)
        if not src:
            return
        # Offset de agarre aprendido (autocalibración B↔C). Si el recurso ya convergió o
        # no hay plantilla, no se re-mide durante el pegado real (memoria/aprendizaje).
        off_key = f"{self.grab_pref}{rec}"
        offset = None
        medir = False
        tpl = None
        cv = None
        try:
            import services.calib_visual as cv
            offset = cv.offset_agarre(off_key)
            medir = (not a.simular) and (not cv.convergido(off_key))
            tpl = cv.cargar_template(off_key) if medir else None
        except Exception as e:
            _log.debug("calib_visual no disponible (%s): uso offset fijo.", e)
        for i in range(1, PLANTILLAS + 1):
            dst = self.calib.get(f"{base_dst}_{i}")
            if not dst:
                continue
            a.clonar_y_arrastrar(src, dst, offset_agarre=offset)
            # Medir dónde quedó (B) vs dónde debía (C=dst) y refinar el agarre. No mueve nada.
            if medir and tpl is not None:
                try:
                    b = cv.localizar(tpl, centro_esperado=dst)
                    if b:
                        cv.actualizar_agarre(off_key, (b[0], b[1]), dst, offset_usado=offset)
                except Exception as e:
                    _log.debug("medición de agarre '%s' falló: %s", off_key, e)

    def _colocar_foto3(self, a):
        src = self.calib.get("foto_src")
        if not src:
            return
        for i in range(1, PLANTILLAS + 1):
            dst = self.calib.get(f"foto_dst_{i}")
            edge = self.calib.get(f"foto_edge_{i}")
            rlim = self.calib.get(f"foto_rlimit_{i}")
            if dst:
                a.clonar_y_arrastrar(src, dst)
            if edge and rlim:
                a.ensanchar_caja(edge, rlim)


class AutoModeOrchestrator(QObject):
    """
    Orquesta el modo automático. main_window inyecta las funciones que saben hacer
    la asignación, el pegado+apertura, la composición (gating) y la calibración; y
    le notifica las páginas listas tras cada poll.
    """
    estado = pyqtSignal(str)       # texto de estado para la UI
    log = pyqtSignal(str)
    procesada = pyqtSignal(int, bool)
    apagado_auto = pyqtSignal(str)   # el auto se apagó solo (Esc×5 / fallo de foco): motivo

    ESPERA_APERTURA = 6.0          # s tras abrir Quark antes de enfocar
    ESPERA_PEGADO = 8.0            # s tras Play antes de continuar

    def __init__(self, fn_asignar, fn_pegar_y_abrir, fn_coords,
                 fn_comp=None, fn_calibracion=None, fn_finalizado_ok=None,
                 fn_confirmar_inicio=None, simular=False, parent=None):
        """
        fn_asignar(numero) -> bool
        fn_pegar_y_abrir(numero) -> bool   (pegar_en_quark + abrir el qxp)
        fn_coords() -> (coord_script, coord_play)   (calibración de puntos del palette)
        fn_comp(numero) -> dict            (composicion_pagina: gating d–g)
        fn_calibracion() -> dict           (clave -> punto (x,y) para clics/arrastres)
        fn_finalizado_ok(numero) -> None   (post-OK en hilo GUI: mover a Base + traer Armador)
        fn_confirmar_inicio(numero) -> bool (gate en hilo GUI: cuenta regresiva cancelable
                                             antes de que el worker tome el mouse/teclado)
        """
        super().__init__(parent)
        self._fn_asignar = fn_asignar
        self._fn_pegar = fn_pegar_y_abrir
        self._fn_coords = fn_coords
        self._fn_comp = fn_comp or (lambda _n: {})
        self._fn_calibracion = fn_calibracion or (lambda _s=None: {})
        self._fn_finalizado_ok = fn_finalizado_ok or (lambda _n: None)
        self._fn_confirmar_inicio = fn_confirmar_inicio or (lambda _n: True)
        self._enabled = False
        self._cancel_event = threading.Event()
        self._automator = QuarkAutomator(simular=simular)
        self._automator.set_cancel_event(self._cancel_event)
        self._procesadas: set = set()
        self._pospuestas: set = set()   # bloqueadas [315]: reintentar en el próximo poll
        self._reintentos_foco: dict = {}   # numero -> intentos por fallo de foco
        self._fallos_foco: set = set()     # páginas que agotaron los reintentos de foco
        self._activa = None
        self._worker = None
        self._cola = []
        self._esc_watcher = None

    # ── API ───────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, valor: bool):
        self._enabled = bool(valor)
        self.estado.emit("Armado automático ON" if self._enabled else "Armado automático OFF")
        if not self._enabled:
            self._procesadas.clear()
            self._pospuestas.clear()
            self._reintentos_foco.clear()
            self._fallos_foco.clear()
            self._detener_watcher()
        else:
            self._cancel_event.clear()
            self._intentar_siguiente_desde_cola()

    def set_simular(self, valor: bool):
        """Cambia el modo simulación (recrea el automator). Solo en reposo."""
        valor = bool(valor)
        if self._activa is not None:
            _log.info("set_simular ignorado: hay una página en proceso.")
            return
        self._automator = QuarkAutomator(simular=valor)
        self._automator.set_cancel_event(self._cancel_event)
        self.estado.emit("Armado automático: simulación ON" if valor
                         else "Armado automático: simulación OFF")

    # ── Kill-switch Esc×5 ─────────────────────────────────────
    def _iniciar_watcher(self):
        if self._esc_watcher is not None:
            return
        w = _EscWatcher(self)
        w.disparado.connect(self._on_cancel_esc)
        self._esc_watcher = w
        w.start()

    def _detener_watcher(self):
        w = self._esc_watcher
        self._esc_watcher = None
        if w is not None:
            try:
                w.stop()
                w.wait(500)
            except Exception:
                pass

    def _on_cancel_esc(self):
        _log.info("Kill-switch: Esc×5 → cancelando y apagando el Armado automático.")
        self._cancel_event.set()   # el worker en curso aborta cuanto antes
        self._apagar_auto("Armado automático cancelado por el usuario (Esc×5).")

    def _apagar_auto(self, motivo: str):
        """Apaga el modo automático por una condición interna (Esc×5 / fallo de foco)."""
        self._cola = []
        self.set_enabled(False)
        self.estado.emit(motivo)
        self.apagado_auto.emit(motivo)

    @property
    def simular(self) -> bool:
        return bool(getattr(self._automator, "simular", False))

    def calibrado(self) -> bool:
        """True si al menos el botón Play está calibrado."""
        _script, play = self._fn_coords()
        return bool(play)

    def notificar_listas(self, numeros):
        """main_window llama esto tras cada poll con las páginas listo_para_armar."""
        self._cola = orden_prioridad(numeros)
        # Nuevo poll → dar otra oportunidad a las pospuestas (p.ej. dejó de estar bloqueada).
        self._pospuestas.clear()
        if self._enabled:
            self._intentar_siguiente_desde_cola()

    # ── Motor ─────────────────────────────────────────────────
    def _intentar_siguiente_desde_cola(self):
        if not self._enabled or self._activa is not None:
            return
        for numero in self._cola:
            if numero not in self._procesadas and numero not in self._pospuestas:
                self._procesar(numero)
                return

    def _procesar(self, numero: int):
        if not self.calibrado():
            self.estado.emit("Armado automático: falta calibrar el botón Play.")
            return

        # Composición (para gating y sección). Se obtiene ANTES de asignar/pegar para poder
        # saltear las secciones excluidas sin abrir Quark.
        try:
            comp = self._fn_comp(numero) or {}
        except Exception as e:
            _log.warning("comp P%02d falló: %s", numero, e)
            comp = {}
        seccion = normalizar_seccion(comp.get("seccion"))
        try:
            excluidas = set(config_global.auto_excluidas())
        except Exception:
            excluidas = set()
        if seccion and seccion in excluidas:
            self._activa = numero
            self.log.emit(f"P{numero:02d}: sección '{seccion}' excluida → se saltea.")
            self._finalizar(numero, ERROR)   # marca procesada, no arma; sigue con la próxima
            return

        self._activa = numero
        self.log.emit(f"P{numero:02d}: asignando…")
        try:
            if not self._fn_asignar(numero):
                self._finalizar(numero, ERROR)
                return
            self.log.emit(f"P{numero:02d}: pegando y abriendo Quark…")
            if not self._fn_pegar(numero):
                self._finalizar(numero, ERROR)
                return
        except Exception as e:
            _log.warning("Prep P%02d falló: %s", numero, e)
            self._finalizar(numero, ERROR)
            return

        coord_script, coord_play = self._fn_coords()
        try:
            calib = self._fn_calibracion(seccion) or {}
        except Exception as e:
            _log.warning("calibración P%02d falló: %s", numero, e)
            calib = {}

        # Aviso con cuenta regresiva cancelable ANTES de que el worker tome el control del
        # mouse/teclado. La callback (hilo GUI) devuelve False si el usuario cancela.
        try:
            confirmado = self._fn_confirmar_inicio(numero)
        except Exception as e:
            _log.warning("confirmar_inicio P%02d falló: %s", numero, e)
            confirmado = True
        if not confirmado:
            self.log.emit(f"P{numero:02d}: inicio cancelado por el usuario (se reintentará).")
            self._finalizar(numero, REINTENTAR)
            return

        # Arrancar el kill-switch (Esc×5) mientras se procesa/pega esta página.
        self._cancel_event.clear()
        self._iniciar_watcher()

        # Prefijo de sección para el offset de agarre (mismas reglas que la calibración por áreas).
        try:
            especiales = set(config_global.auto_especiales())
        except Exception:
            especiales = set()
        grab_pref = f"{seccion}__" if (seccion and seccion in especiales) else ""

        self._worker = _PaginaWorker(numero, self._automator, coord_script, coord_play,
                                     comp, calib, self.ESPERA_APERTURA, self.ESPERA_PEGADO,
                                     grab_pref=grab_pref, parent=self)
        self._worker.paso.connect(self.log.emit)
        self._worker.terminado.connect(self._finalizar)
        self._worker.start()

    def _finalizar(self, numero: int, estado: str):
        self._activa = None
        self._worker = None
        self._detener_watcher()

        if estado == CANCELADO:
            # Kill-switch: el auto ya se apagó en _on_cancel_esc. No encadenar.
            self.log.emit(f"P{numero:02d}: cancelada (Esc×5).")
            return

        if estado == REINTENTAR:
            # [315] bloqueado: no marcar procesada; se reintenta al limpiar _pospuestas.
            self._pospuestas.add(numero)
            self.log.emit(f"P{numero:02d}: bloqueada, se reintentará (Armado automático).")
            self._intentar_siguiente_desde_cola()
            return

        if estado == REINTENTAR_FOCO:
            c = self._reintentos_foco.get(numero, 0) + 1
            self._reintentos_foco[numero] = c
            if c < MAX_REINTENTOS_FOCO:
                self._pospuestas.add(numero)
                self.log.emit(f"P{numero:02d}: Quark sin foco, reintento {c}/{MAX_REINTENTOS_FOCO}.")
                self._intentar_siguiente_desde_cola()
                return
            # Agotó los reintentos en esta página → fallo confirmado de foco.
            self._procesadas.add(numero)
            self._fallos_foco.add(numero)
            self.log.emit(f"P{numero:02d}: Quark no respondió tras {c} intentos.")
            if len(self._fallos_foco) >= MAX_PAGINAS_FALLO_FOCO:
                self._apagar_auto(
                    "Armado automático apagado: Quark no respondió en "
                    f"{len(self._fallos_foco)} páginas.")
                return
            self._intentar_siguiente_desde_cola()
            return

        # OK / ERROR
        self._procesadas.add(numero)
        ok = (estado == OK)
        self.procesada.emit(numero, ok)
        self.log.emit(f"P{numero:02d}: {'OK' if ok else 'con error'} (Armado automático).")
        if ok:
            # Post-OK en hilo GUI (el orquestador vive en GUI): mover a Base + traer Armador.
            try:
                self._fn_finalizado_ok(numero)
            except Exception as e:
                _log.warning("fn_finalizado_ok P%02d falló: %s", numero, e)
        self._intentar_siguiente_desde_cola()
