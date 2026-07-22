"""
AutoModeOrchestrator — Armado automático (pasos a–g).

Cuando está habilitado y el polling detecta páginas "listas para armar", las
procesa de a una, con prioridad del dorso editorial (2,3,6,7,10,11,14,15) y luego
orden numérico. Por página:
  asigna → pega (abre Quark) → [b] si el proyecto está bloqueado ([315]) aborta y
  reintenta en el próximo poll → [a] cierra cartel de fuentes → enfoca Quark →
  [c] dispara PegarNota v6.js (vía CDP, o clic ítem+Play si el CDP no está
  disponible — ver `_disparar_pegado`) → el JS hace TODO: pega, geometría de foto y
  recursos (moverGrupo/PegarNota v6), guarda y cierra.

Qué pasos corren se decide con la composición de la página (`fn_comp`), y dónde
están/van los recursos con la calibración por áreas (`fn_calibracion`), que el JS
lee de `data_pagina.json`/`runtime_config.json`.

La preparación en disco (asignar + pegar + abrir Quark) corre en el hilo GUI
(rápida, sin bloqueo); el disparo y la espera del resultado corren en un QThread.
"""
from __future__ import annotations

import os
import json
import time
import logging
import threading
from pathlib import Path
from collections import deque
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from services.quark_auto import QuarkAutomator, CanceladoError
from services import quark_cdp
from services.armado_auto_schema import (
    PLANTILLAS, RECURSOS_MOVIBLES, recurso_activo, ZOOM_ARMADO, normalizar_seccion,
    foto3_variante, textual_src_key,
)
from config.config import config_global, Config

PEGAR_NOTA_JS = Config.SCRIPTS_DIR / "PegarNota v6.js"

_log = logging.getLogger(__name__)

PRIORIDAD_DORSO = [2, 3, 6, 7, 10, 11, 14, 15]

# Estados de fin de página
OK = "ok"
ERROR = "error"
REINTENTAR = "reintentar"          # bloqueado [315]: reintentar próximo poll
REINTENTAR_FOCO = "reintentar_foco"  # Quark no llegó al frente: reintentar (hasta 3) próximo poll
REINTENTAR_PEGADO = "reintentar_pegado"  # no apareció el cartel 'Pegado finalizado': reintentar (3)
CANCELADO = "cancelado"            # kill-switch Esc×5: abortar y apagar

# Kill-switch: cuántos Esc en cuánto tiempo.
ESC_N = 5
ESC_LAPSO = 1.0   # s

# ── Flags de auto-pegado por JS (archivos en %APPDATA%/ArmadorHuarpe/scripts/) ──
# Entrada  (Python→JS): runtime_config.json {"auto": true, "numero": N}.
# Salida   (JS→Python): armado_status.json  {"armado_auto": true, "numero": N} tras guardar+cerrar.
def _prod_scripts_dir() -> Path:
    return Path(os.getenv("APPDATA", "")) / "ArmadorHuarpe" / "scripts"


def marcar_auto_pendiente(numero: int) -> None:
    """Antes de abrir Quark: setea auto=true+numero en runtime_config.json y borra un
    armado_status.json viejo, para que PegarNota v6 (al dispararlo el bot) guarde y cierre."""
    d = _prod_scripts_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        cfg_p = d / "runtime_config.json"
        try:
            cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
        except Exception:
            cfg = {}
        cfg["auto"] = True
        cfg["numero"] = int(numero)
        cfg_p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        _limpiar_armado_status()
    except Exception as e:
        _log.warning("marcar_auto_pendiente P%02d: %s", numero, e)


def _leer_armado_status(numero: int) -> bool:
    """True si el JS ya escribió armado_status.json para esta página (guardó y cerró)."""
    p = _prod_scripts_dir() / "armado_status.json"
    try:
        if p.exists():
            st = json.loads(p.read_text(encoding="utf-8"))
            return bool(st.get("armado_auto")) and int(st.get("numero", -1)) == int(numero)
    except Exception:
        pass
    return False


def _limpiar_armado_status() -> None:
    try:
        (_prod_scripts_dir() / "armado_status.json").unlink()
    except Exception:
        pass
MAX_REINTENTOS_FOCO = 3   # por página
MAX_PAGINAS_FALLO_FOCO = 2  # si 2 páginas distintas fallan el foco → apagar
MAX_REINTENTOS_PEGADO = 3   # por página: si no se detecta el pegado 3 veces → error


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
    """Corre la secuencia de una página: 100% CDP, sin pyautogui y sin robarle el foco a
    quien esté usando la PC (ver services/quark_cdp.py). Quark puede quedar minimizado o
    detrás de otra ventana durante todo el proceso."""
    terminado = pyqtSignal(int, str)    # (numero, estado: OK|ERROR|REINTENTAR)
    paso = pyqtSignal(str)

    def __init__(self, numero, automator: QuarkAutomator, nombre_qxp: str,
                 comp: dict, calib: dict, espera_apertura: float, espera_pegado: float,
                 parent=None):
        super().__init__(parent)
        self.numero = int(numero)
        self.automator = automator
        self.nombre_qxp = nombre_qxp or ""
        self.comp = comp or {}
        self.calib = calib or {}
        self.espera_apertura = espera_apertura
        self.espera_pegado = espera_pegado

    def run(self):
        a = self.automator
        n = self.numero
        try:
            # Esperar (sin foco, sin clics) a que Quark tenga el proyecto de esta página
            # como activo. Si queda bloqueado por un diálogo nativo (proyecto bloqueado
            # [315], fuentes faltantes) o Quark no abre a tiempo, esto simplemente agota
            # el timeout — no se intenta cerrar el cartel por pyautogui (ver docstring de
            # quark_cdp.esperar_proyecto_listo). Timeout generoso (arranque en frío de
            # Quark 2018 completo puede tardar bastante en tener el motor CEF/JS listo
            # para responder por CDP, más que en solo mostrar la ventana).
            _log.info("P%02d: esperando que Quark abra '%s' (activeProject por CDP)…",
                      n, self.nombre_qxp)
            self.paso.emit(f"P{n:02d}: esperando que Quark abra el proyecto…")
            if not quark_cdp.esperar_proyecto_listo(self.nombre_qxp,
                                                     timeout=self.espera_apertura + 80.0):
                _log.warning("P%02d: Quark no respondió por CDP → reintento en el próximo poll.", n)
                self.paso.emit(f"P{n:02d}: Quark no respondió → reintento en el próximo poll.")
                self.terminado.emit(n, REINTENTAR_FOCO)
                return
            _log.info("P%02d: proyecto activo confirmado por CDP.", n)

            # IMPORTANTE: mostrar (no minimizar) la ventana antes de disparar el script.
            # PegarNota v6 mueve recursos desde el pasteboard a la página (plantilla 1)
            # con una compensación (COMP_X/COMP_Y) que solo funciona si Quark está
            # renderizando de verdad — confirmado en vivo (geo_diag.txt): con la ventana
            # minimizada, los recursos quedan en la coordenada cruda del pasteboard, fuera
            # de la maqueta. "Mostrar" no es "activar": SW_SHOWNOACTIVATE no le roba el
            # foco a quien esté usando la PC (ver services.quark_auto.mostrar_quark_sin_activar).
            from services.quark_auto import mostrar_quark_sin_activar
            mostrar_quark_sin_activar()

            # Disparo del script (PegarNota v6) vía CDP — sin clics, sin foco (pero con la
            # ventana visible, por lo de arriba). A partir de acá el JS hace TODO: pega,
            # geometría (foto/recursos/clones/epígrafes) y, en modo auto, GUARDA y CIERRA
            # el proyecto; luego escribe armado_status.json.
            _limpiar_armado_status()  # descartar un flag viejo
            self.paso.emit(f"P{n:02d}: disparando el pegado (CDP)…")
            if not quark_cdp.ejecutar_script(PEGAR_NOTA_JS, timeout=self.espera_pegado + 60.0):
                _log.warning("P%02d: no se pudo disparar PegarNota v6.js por CDP.", n)
                self.terminado.emit(n, ERROR)
                return

            # Esperar a que el JS termine (guardó + cerró + escribió el flag).
            self.paso.emit(f"P{n:02d}: esperando que el JS guarde y cierre…")
            _t0 = time.time()
            _ok = False
            while time.time() - _t0 < 90.0:
                if _leer_armado_status(n):
                    _ok = True
                    break
                a.esperar(0.5)
            if not _ok:
                _log.warning("P%02d: timeout esperando armado_status.json (el JS no terminó).", n)
                self.terminado.emit(n, ERROR)
                return

            _log.info("P%02d: armado_status.json confirmado — pegado OK.", n)
            a.minimizar_quark()          # ctypes/Win32 (no pyautogui)
            _limpiar_armado_status()
            self.terminado.emit(n, OK)
        except CanceladoError:
            _log.info("Worker P%02d cancelado por el usuario (Esc×5).", n)
            self.terminado.emit(n, CANCELADO)
        except Exception as e:
            _log.warning("Worker P%02d falló: %s", n, e)
            self.terminado.emit(n, ERROR)

    # ── helpers de colocación (no llamados hoy: PegarNota v6 mueve recursos por
    # geometría/DOM; se conservan por si hiciera falta un fallback puntual) ──
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

    def _redimensionar_foto3(self, a):
        """Si la página lleva foto a 3 columnas (3 col/ancha) o 4 columnas: seleccionar cada foto
        (por plantilla) y escribir A (Ancho) y Al (Alto) en el panel de medidas. Se hace ANTES de
        tocar el selector de plantilla (que reacomoda la vista)."""
        var = foto3_variante(self.comp)
        if not var:
            return
        campo_a = self.calib.get("campo_a")
        campo_al = self.calib.get("campo_al")
        if var == "4col":
            a_val = self.calib.get("foto_a_4col")
            al_val = self.calib.get("foto_al_4col")
        else:
            a_val = self.calib.get("foto_a")
            al_val = self.calib.get("foto_al_wide" if var == "wide" else "foto_al_ancha")
        if not (campo_a and campo_al and a_val and al_val):
            _log.info("Foto3 %s: falta calibración (campos A/Al o valores) → se omite.", var)
            return
        self.paso.emit(f"P{self.numero:02d}: redimensionando foto ({var})…")
        for i in range(1, PLANTILLAS + 1):
            sel = self.calib.get(f"foto_sel_{i}")
            if sel:
                a.redimensionar_foto(sel, campo_a, campo_al, a_val, al_val)

    def _colocar_recursos_xy(self, a):
        """Coloca cada recurso activo en las PLANTILLAS mediante la cadena 'carrier' cortar/pegar:
        el clon viaja de plantilla en plantilla y se posiciona escribiendo X/Y en el panel.
        Por recurso: plantilla1 → clic src → clonar → X/Y → clonar; luego, por cada plantilla
        siguiente: cortar → seleccionar plantilla → pegar → X/Y → (clonar salvo la última)."""
        plantilla_sel = self.calib.get("plantilla_sel")
        campo_x = self.calib.get("campo_x")
        campo_y = self.calib.get("campo_y")
        zoom_area = self.calib.get("zoom")
        zoom_base = self.calib.get("zoom_valor") or ZOOM_ARMADO
        zoom_final = self.calib.get("zoom_valor_final") or "60"
        try:
            dels_rec = int(str(self.calib.get("deletes_recurso") or "2").strip())
        except Exception:
            dels_rec = 2
        activos = [rec for rec in RECURSOS_MOVIBLES if recurso_activo(self.comp, rec)]
        if not activos:
            return
        if not (campo_x and campo_y):
            _log.info("Recursos: faltan campos X/Y calibrados → se omite.")
            return
        for rec in activos:
            # El textual usa el src de su variante (x2 / con_foto / con_foto_xl / simple); el X/Y
            # es compartido (textual_x/textual_y). Los demás recursos: {rec}_src.
            src_key = textual_src_key(self.comp) if rec == "textual" else f"{rec}_src"
            src = self.calib.get(src_key)
            x_val = self.calib.get(f"{rec}_x")
            y_val = self.calib.get(f"{rec}_y")
            if not (src and x_val and y_val):
                continue
            self.paso.emit(f"P{self.numero:02d}: colocando {rec} en {PLANTILLAS} plantillas…")
            for t in range(1, PLANTILLAS + 1):
                if t == 1:
                    if plantilla_sel:
                        a.seleccionar_plantilla(plantilla_sel, 1)
                    a.click(int(src[0]), int(src[1]))   # seleccionar el recurso (src)
                    a.esperar(0.2)
                    a.clonar()                          # clon posicionable en la plantilla 1
                else:
                    a.cortar()                          # cortar el carrier del bucle anterior
                    # Última plantilla (contigua): subir el zoom antes de elegirla, si no Quark
                    # pega en la plantilla vecina aunque esté seleccionada la correcta.
                    if t == PLANTILLAS and zoom_area:
                        a.set_zoom(zoom_area, zoom_final)
                    if plantilla_sel:
                        a.seleccionar_plantilla(plantilla_sel, t)
                    a.pegar()                           # pegar en la plantilla activa
                # Backspaces (config 'Borrados ⌫', default 2): limpian el '-' residual del src.
                a.escribir_en_campo(campo_x, x_val, deletes=dels_rec)
                a.escribir_en_campo(campo_y, y_val, deletes=dels_rec)
                if t < PLANTILLAS:
                    a.clonar()                          # carrier para la próxima plantilla
            # Volver al zoom base: el clic del src del próximo recurso está calibrado a ese zoom.
            if zoom_area:
                a.set_zoom(zoom_area, zoom_base)


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
    pegado_fallido = pyqtSignal(int, bool)  # (numero, es_final): no se detectó el pegado

    ESPERA_APERTURA = 6.0          # s tras abrir Quark antes de enfocar
    ESPERA_PEGADO = 8.0            # s tras Play antes de continuar

    def __init__(self, fn_asignar, fn_pegar_y_abrir, fn_nombre_qxp,
                 fn_comp=None, fn_calibracion=None, fn_finalizado_ok=None,
                 fn_confirmar_inicio=None, simular=False, parent=None):
        """
        fn_asignar(numero) -> bool
        fn_pegar_y_abrir(numero) -> bool   (pegar_en_quark + abrir el qxp)
        fn_nombre_qxp(numero) -> str       (nombre/stem del .qxp que se abrió, para que el
                                            worker pueda esperar por CDP a que quede activo
                                            sin necesitar foco — ver quark_cdp.esperar_proyecto_listo)
        fn_comp(numero) -> dict            (composicion_pagina: gating d–g)
        fn_calibracion() -> dict           (clave -> punto (x,y) para clics/arrastres)
        fn_finalizado_ok(numero) -> None   (post-OK en hilo GUI: mover a Base + traer Armador)
        fn_confirmar_inicio(numero) -> bool (gate en hilo GUI: cuenta regresiva cancelable
                                             antes de que el worker tome el mouse/teclado)
        """
        super().__init__(parent)
        self._fn_asignar = fn_asignar
        self._fn_pegar = fn_pegar_y_abrir
        self._fn_nombre_qxp = fn_nombre_qxp or (lambda _n: "")
        self._fn_comp = fn_comp or (lambda _n: {})
        self._fn_calibracion = fn_calibracion or (lambda _s=None, _a=None: {})
        self._fn_finalizado_ok = fn_finalizado_ok or (lambda _n: None)
        self._fn_confirmar_inicio = fn_confirmar_inicio or (lambda _n: True)
        self._enabled = False
        self._cancel_event = threading.Event()
        self._automator = QuarkAutomator(simular=simular)
        self._automator.set_cancel_event(self._cancel_event)
        self._procesadas: set = set()
        self._pospuestas: set = set()   # bloqueadas [315]: reintentar en el próximo poll
        self._reintentos_foco: dict = {}   # numero -> intentos por fallo de foco
        self._reintentos_pegado: dict = {}  # numero -> intentos por pegado no detectado
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
            self._reintentos_pegado.clear()
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
        """True si QuarkXPress está corriendo y responde por CDP (services/quark_cdp) —
        condición para poder disparar el pegado sin pyautogui. El nombre se conserva para
        no romper el llamador en ui/main_window.py."""
        return quark_cdp.disponible()

    def reset_pagina(self, numero: int):
        """Olvida el resultado previo de `numero` para que pueda volver a armarse (p. ej. el
        usuario la re-marcó para armado automático tras rehacerla). El próximo poll la reencola."""
        n = int(numero)
        self._procesadas.discard(n)
        self._pospuestas.discard(n)
        self._fallos_foco.discard(n)
        self._reintentos_foco.pop(n, None)
        self._reintentos_pegado.pop(n, None)

    def notificar_listas(self, numeros):
        """main_window llama esto tras cada poll con las páginas marcadas para armado_bot."""
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
            self.estado.emit(
                "Armado automático: QuarkXPress no está corriendo (o el canal CDP no "
                "responde) — iniciá QuarkXPress 2018 antes de activar el armado automático.")
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

        # Aviso con cuenta regresiva cancelable ANTES de asignar/abrir Quark/pegar: así el
        # diálogo aparece al frente (Quark todavía no abrió) y cancelar no deja Quark abierto.
        try:
            confirmado = self._fn_confirmar_inicio(numero)
        except Exception as e:
            _log.warning("confirmar_inicio P%02d falló: %s", numero, e)
            confirmado = True
        if not confirmado:
            self.log.emit(f"P{numero:02d}: inicio cancelado por el usuario (se reintentará).")
            self._finalizar(numero, REINTENTAR)
            return

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

        try:
            nombre_qxp = self._fn_nombre_qxp(numero) or ""
        except Exception as e:
            _log.warning("nombre_qxp P%02d falló: %s", numero, e)
            nombre_qxp = ""
        try:
            # La maqueta depende de la sección y del tipo de aviso (comp['aviso_tipo']).
            calib = self._fn_calibracion(seccion, comp.get("aviso_tipo")) or {}
        except Exception as e:
            _log.warning("calibración P%02d falló: %s", numero, e)
            calib = {}

        # Arrancar el kill-switch (Esc×5) mientras se procesa/pega esta página.
        self._cancel_event.clear()
        self._iniciar_watcher()

        self._worker = _PaginaWorker(numero, self._automator, nombre_qxp,
                                     comp, calib, self.ESPERA_APERTURA, self.ESPERA_PEGADO,
                                     parent=self)
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

        if estado == REINTENTAR_PEGADO:
            c = self._reintentos_pegado.get(numero, 0) + 1
            self._reintentos_pegado[numero] = c
            if c < MAX_REINTENTOS_PEGADO:
                self._pospuestas.add(numero)
                self.log.emit(f"P{numero:02d}: pegado no detectado, reintento {c}/{MAX_REINTENTOS_PEGADO}.")
                self.pegado_fallido.emit(numero, False)
                self._intentar_siguiente_desde_cola()
                return
            # Agotó los reintentos → error de pegado confirmado.
            self._procesadas.add(numero)
            self.log.emit(f"P{numero:02d}: pegado no detectado tras {c} intentos → error.")
            self.pegado_fallido.emit(numero, True)
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
