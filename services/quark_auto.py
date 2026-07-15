"""
QuarkAutomator — primitivas de automatización de GUI para el Modo automático.

Enfoca la ventana de QuarkXPress (ctypes/user32), hace clics en coordenadas
calibradas (el ítem del script y el botón "Play" del palette JavaScript), y
guarda/cierra el documento con atajos de teclado (pyautogui).

Modo simulación (`simular=True`): NO toca el mouse/teclado ni la ventana; solo
loguea la secuencia. Sirve para validar el orquestador sin riesgo.

Automatización canónica en Python:
- pyautogui: click / moveTo / dragTo / hotkey / press.
- foco de ventana: ctypes user32 (EnumWindows + SetForegroundWindow), igual que
  MainWindow._maximizar_quark.
"""
from __future__ import annotations

import time
import re
import logging

_log = logging.getLogger(__name__)

_TITLE_PREFIX = "QuarkXPress (R)"
_CLASS_NAMES = {"QXMainWinClass", "QXMainWindow"}


class CanceladoError(Exception):
    """Se lanza para abortar la secuencia del automático (kill-switch Esc×5)."""
    pass

# Al duplicar (Ctrl+D), el clon aparece desplazado abajo-derecha unos px. Para "agarrarlo"
# con el mouse hay que apuntar corrido en ese sentido respecto del centro del original.
CLON_OFFSET_X = 14
CLON_OFFSET_Y = 14

# Velocidad de los pasos POSTERIORES al pegado (d–g): 15% más rápido → esperas × 0.85.
FACTOR_POST_PEGADO = 0.85

# pyautogui.hotkey() por defecto usa interval=0.0 (sin pausa entre keyDown/keyUp de cada tecla).
# Con SendInput sintético eso puede hacer que Quark reciba la tecla principal (p. ej. F4) ANTES
# de registrar el modificador (Ctrl) como sostenido → llega "F4 solo" en vez de "Ctrl+F4" (bug
# confirmado: abre 'Estilos OpenType' y el cierre nunca ocurre). 60 ms evita esa carrera.
HOTKEY_INTERVAL = 0.06


def encontrar_hwnd_quark():
    """Devuelve el HWND de la ventana principal de Quark, o None (solo Windows)."""
    try:
        import ctypes
        import ctypes.wintypes as wintypes
    except Exception:
        return None
    user32 = ctypes.windll.user32
    found = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            if (buff.value or "").startswith(_TITLE_PREFIX):
                found.append(hwnd)
                return False
        class_buff = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buff, 256)
        if (class_buff.value or "") in _CLASS_NAMES:
            found.append(hwnd)
            return False
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception as e:
        _log.warning("EnumWindows falló: %s", e)
        return None
    return found[0] if found else None


def encontrar_hwnd_quark_principal():
    """Devuelve el HWND de la ventana PRINCIPAL de Quark buscando por CLASE
    (QXMainWinClass/QXMainWindow), para no confundirla con la ventana de un cartel/diálogo
    que podría compartir el prefijo de título 'QuarkXPress (R)'. None si no la encuentra."""
    try:
        import ctypes
        import ctypes.wintypes as wintypes
    except Exception:
        return None
    user32 = ctypes.windll.user32
    found = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        class_buff = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buff, 256)
        if (class_buff.value or "") in _CLASS_NAMES:
            found.append(hwnd)
            return False
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception as e:
        _log.warning("EnumWindows (principal) falló: %s", e)
        return None
    return found[0] if found else None


class QuarkAutomator:
    def __init__(self, simular: bool = False):
        self.simular = bool(simular)
        self._pyautogui = None
        self._cancel_event = None
        if not self.simular:
            try:
                import pyautogui
                pyautogui.FAILSAFE = True
                self._pyautogui = pyautogui
            except Exception as e:
                _log.warning("pyautogui no disponible; forzando simulación: %s", e)
                self.simular = True

    # ── Cancelación (kill-switch Esc×5) ───────────────────────
    def set_cancel_event(self, ev):
        """Inyecta un threading.Event; cuando se setea, la secuencia se aborta."""
        self._cancel_event = ev

    def _cancelado(self) -> bool:
        return bool(self._cancel_event is not None and self._cancel_event.is_set())

    def _check_cancel(self):
        if self._cancelado():
            raise CanceladoError()

    # ── Ventana ───────────────────────────────────────────────
    def quark_presente(self) -> bool:
        if self.simular:
            return True
        return encontrar_hwnd_quark() is not None

    def _foco_es_quark(self) -> bool:
        """True si la ventana en primer plano pertenece al proceso de Quark (ventana
        principal o un diálogo suyo). Compara PIDs."""
        if self.simular:
            return True
        try:
            import ctypes
            import ctypes.wintypes as wintypes
            user32 = ctypes.windll.user32
            fg = user32.GetForegroundWindow()
            if not fg:
                return False
            hwnd = encontrar_hwnd_quark_principal() or encontrar_hwnd_quark()
            if not hwnd:
                return False
            pid_fg = wintypes.DWORD()
            pid_q = wintypes.DWORD()
            user32.GetWindowThreadProcessId(fg, ctypes.byref(pid_fg))
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_q))
            return pid_q.value != 0 and pid_fg.value == pid_q.value
        except Exception:
            return False

    def focus_quark(self, timeout: float = 25.0) -> bool:
        """Espera a que Quark exista y quede realmente EN PRIMER PLANO, hasta `timeout`.
        Devuelve True solo cuando el foreground es Quark; False si se agota (no abrió/enfocó).
        Reintenta traerlo al frente; respeta la cancelación."""
        if self.simular:
            _log.info("[SIM] focus_quark()")
            return True
        import time as _t
        t0 = _t.time()
        while _t.time() - t0 < timeout:
            self._check_cancel()
            try:
                import ctypes
                hwnd = encontrar_hwnd_quark_principal() or encontrar_hwnd_quark()
                if hwnd:
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(hwnd, 3)          # SW_MAXIMIZE
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                    self.esperar(0.3)
                    if self._foco_es_quark():
                        return True
            except Exception as e:
                _log.warning("focus_quark intento falló: %s", e)
            self.esperar(0.4)
        _log.warning("focus_quark: Quark no quedó en primer plano tras %.1fs.", timeout)
        return False

    def asegurar_foco(self, timeout: float = 8.0) -> bool:
        """Rápido: True al instante si Quark ya está en foco; si no, intenta traerlo."""
        if self.simular:
            return True
        self._check_cancel()
        if self._foco_es_quark():
            return True
        return self.focus_quark(timeout=timeout)

    # ── Diálogos modales de Quark (por Win32, independiente de la posición) ──
    def _rect_boton_por_texto(self, textos):
        """Rect (l,t,r,b) en pantalla del primer control 'Button' cuyo texto coincida
        con alguno de `textos` (sin '&', case-insensitive), o None. Recorre todas las
        ventanas top-level y sus hijos, así funcione el diálogo esté donde esté."""
        try:
            import ctypes
            import ctypes.wintypes as w
        except Exception:
            return None
        user32 = ctypes.windll.user32
        objetivo = {t.replace("&", "").strip().lower() for t in textos}
        encontrado = {"rect": None}

        EnumChildProc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def _child(hwnd, _l):
            cb = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cb, 64)
            if (cb.value or "").lower() != "button":
                return True
            tl = user32.GetWindowTextLengthW(hwnd)
            tb = ctypes.create_unicode_buffer(tl + 1)
            user32.GetWindowTextW(hwnd, tb, tl + 1)
            txt = (tb.value or "").replace("&", "").strip().lower()
            if txt in objetivo:
                r = w.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                encontrado["rect"] = (r.left, r.top, r.right, r.bottom)
                return False
            return True

        _child_c = EnumChildProc(_child)
        EnumWindowsProc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def _top(hwnd, _l):
            if not user32.IsWindowVisible(hwnd):
                return True
            user32.EnumChildWindows(hwnd, _child_c, 0)
            return encontrado["rect"] is None   # cortar al hallarlo

        try:
            user32.EnumWindows(EnumWindowsProc(_top), 0)
        except Exception as e:
            _log.warning("EnumWindows (botón) falló: %s", e)
            return None
        return encontrado["rect"]

    def _hay_dialogo_con_texto(self, textos) -> bool:
        """True si alguna ventana visible (o alguno de sus controles hijos, de cualquier clase)
        contiene alguno de `textos` como SUBSTRING (case-insensitive). Sirve para detectar el
        cartel 'Pegado finalizado' (su texto es un Static, no un Button)."""
        if self.simular:
            return False
        try:
            import ctypes
            import ctypes.wintypes as w
        except Exception:
            return False
        user32 = ctypes.windll.user32
        objetivo = [t.strip().lower() for t in textos if t and t.strip()]
        hallado = {"ok": False}

        def _texto_de(hwnd) -> str:
            tl = user32.GetWindowTextLengthW(hwnd)
            if tl <= 0:
                return ""
            tb = ctypes.create_unicode_buffer(tl + 1)
            user32.GetWindowTextW(hwnd, tb, tl + 1)
            return (tb.value or "").strip().lower()

        EnumChildProc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def _child(hwnd, _l):
            txt = _texto_de(hwnd)
            if txt and any(o in txt for o in objetivo):
                hallado["ok"] = True
                return False
            return True

        _child_c = EnumChildProc(_child)
        EnumWindowsProc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def _top(hwnd, _l):
            if not user32.IsWindowVisible(hwnd):
                return True
            txt = _texto_de(hwnd)
            if txt and any(o in txt for o in objetivo):
                hallado["ok"] = True
                return False
            user32.EnumChildWindows(hwnd, _child_c, 0)
            return not hallado["ok"]

        try:
            user32.EnumWindows(EnumWindowsProc(_top), 0)
        except Exception as e:
            _log.warning("EnumWindows (texto) falló: %s", e)
        return hallado["ok"]

    def esperar_cartel_pegado(self, punto_ok, timeout: float = 60.0) -> bool:
        """Espera el cartel 'Pegado finalizado' (handshake con el JS). Si aparece, hace clic en el
        OK calibrado (o Enter si no hay calibración) y devuelve True. Mientras tanto cierra el cartel
        de fuentes si aparece. Devuelve False si no aparece dentro de `timeout` segundos."""
        if self.simular:
            _log.info("[SIM] esperar_cartel_pegado → OK (simulado)")
            return True
        import time as _t
        t0 = _t.time()
        while _t.time() - t0 < timeout:
            self._check_cancel()
            if self._hay_dialogo_con_texto(["Pegado finalizado"]):
                if punto_ok:
                    self.click(int(punto_ok[0]), int(punto_ok[1]))
                else:
                    self._pyautogui.press("enter")
                self.esperar(0.4)
                # Esperar a que el modal cierre (ventana principal re-habilitada), hasta ~3s.
                t1 = _t.time()
                while _t.time() - t1 < 3.0 and self._hay_modal_quark():
                    self.esperar(0.2)
                _log.info("Cartel 'Pegado finalizado' detectado → OK y continúo.")
                return True
            # Cartel de fuentes (u otro modal que NO sea el de éxito) → cerrarlo y seguir esperando.
            if self._rect_boton_por_texto(["Listar fuentes", "Continuar", "Continue"]) or \
                    self._hay_modal_quark():
                self._pyautogui.press("right")
                self.esperar(0.2)
                self._pyautogui.press("enter")
                self.esperar(0.4)
            self.esperar(0.5)
        _log.warning("No apareció el cartel 'Pegado finalizado' tras %.0fs.", timeout)
        return False

    def _hay_modal_quark(self) -> bool:
        """True si hay un diálogo MODAL bloqueando Quark (ventana principal deshabilitada).
        Es la forma robusta de detectar el cartel de fuentes (custom/pantalla completa), que
        no expone botones nativos. False en simulación o si no se encuentra la ventana."""
        if self.simular:
            return False
        try:
            import ctypes
            hwnd = encontrar_hwnd_quark_principal()
            if not hwnd:
                return False
            return not bool(ctypes.windll.user32.IsWindowEnabled(hwnd))
        except Exception:
            return False

    def esperar_y_cerrar_dialogo_fuentes(self, timeout: float = 4.0) -> bool:
        """Si aparece el cartel de 'fuentes que faltan' (modal), lo cierra por teclado.
        Su botón DEFAULT es 'Listar fuentes' (no 'Continuar') y suele abrirse a pantalla
        completa sin botones nativos; por eso se detecta con IsWindowEnabled (ventana
        principal deshabilitada = hay modal) y se cierra con 'flecha derecha' (selecciona
        'Continuar') + 'Enter'. Como respaldo, también intenta detectar un botón nativo.
        Devuelve True si lo detectó/cerró; False si no apareció dentro del timeout."""
        if self.simular:
            _log.info("[SIM] esperar_y_cerrar_dialogo_fuentes → flecha derecha + Enter (si hubiera)")
            return False
        import time as _t
        t0 = _t.time()
        while _t.time() - t0 < timeout:
            detectado = self._hay_modal_quark() or bool(
                self._rect_boton_por_texto(["Listar fuentes", "Continuar", "Continue"]))
            if detectado:
                self._pyautogui.press("right")
                self.esperar(0.2)
                self._pyautogui.press("enter")
                self.esperar(0.4)
                # Esperar a que el modal cierre (ventana principal re-habilitada), hasta ~2s.
                t1 = _t.time()
                while _t.time() - t1 < 2.0 and self._hay_modal_quark():
                    self.esperar(0.2)
                _log.info("Cartel de fuentes cerrado (flecha derecha + Enter).")
                return True
            self.esperar(0.4)
        return False

    def minimizar_quark(self) -> bool:
        """Minimiza la ventana de Quark (SW_MINIMIZE). True si la encontró."""
        if self.simular:
            _log.info("[SIM] minimizar_quark()")
            return True
        try:
            import ctypes
            hwnd = encontrar_hwnd_quark()
            if not hwnd:
                _log.warning("minimizar_quark: no se encontró la ventana de Quark.")
                return False
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return True
        except Exception as e:
            _log.warning("minimizar_quark falló: %s", e)
            return False

    def _leer_zoom(self, punto):
        """Lee el número del campo de zoom bajo `punto` (WindowFromPoint + GetWindowText).
        Devuelve int o None si no se puede leer (campo custom sobre el canvas, o error).
        Guarda anti-falso-positivo: si el control es la ventana PRINCIPAL (campo dibujado,
        no un control hijo), devuelve None para no parsear el título ('...2018...')."""
        if self.simular or not punto:
            return None
        try:
            import ctypes
            import ctypes.wintypes as wintypes
            import re
            user32 = ctypes.windll.user32

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            user32.WindowFromPoint.restype = wintypes.HWND
            user32.WindowFromPoint.argtypes = [POINT]
            hwnd = user32.WindowFromPoint(POINT(int(punto[0]), int(punto[1])))
            if not hwnd:
                return None
            # Si es la ventana principal (campo custom), no es un control legible.
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            if (class_buff.value or "") in _CLASS_NAMES:
                return None
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            m = re.search(r"\d+", buff.value or "")
            return int(m.group()) if m else None
        except Exception:
            return None

    def set_zoom(self, punto, valor: str = "11") -> bool:
        """Fija el zoom en el campo numérico calibrado y lo VERIFICA leyendo el campo.
        Deja el documento al zoom con el que se calibró (los arrastres dependen de eso).
        Devuelve True si quedó en `valor` (o no se pudo leer → best-effort), False si se
        pudo leer y NO coincide tras varios intentos (el worker omite d–g)."""
        if not punto:
            _log.info("set_zoom: sin área de zoom calibrada; se omite.")
            return False
        if self.simular:
            _log.info("[SIM] set_zoom(%s) en %s", valor, punto)
            return True
        try:
            objetivo = int(re.search(r"\d+", str(valor)).group())
        except Exception:
            objetivo = None

        try:
            for intento in range(1, 4):
                # Confirmar foco en Quark ANTES de tocar el campo (evita clickear sobre AH).
                if not self.asegurar_foco():
                    _log.warning("set_zoom abortado: Quark no está en primer plano.")
                    return False
                # Limpiar cualquier modal y salir de edición/selección antes de tocar el campo.
                self.esperar_y_cerrar_dialogo_fuentes(timeout=1.0)
                self._pyautogui.press("esc")
                self.esperar(0.1)
                # Doble-clic: selecciona el valor del campo de forma fiable (evita Ctrl+A global).
                self._pyautogui.click(int(punto[0]), int(punto[1]), clicks=2, interval=0.08)
                self.esperar(0.2)
                self._pyautogui.typewrite(str(valor), interval=0.05)
                self.esperar(0.2)
                # Si apareció un cartel de fuentes, cerrarlo y reintentar (no mandar Enter suelto).
                if self._hay_modal_quark():
                    self.esperar_y_cerrar_dialogo_fuentes(timeout=1.5)
                    continue
                self._pyautogui.press("enter")         # SIEMPRE confirmar
                self.esperar(0.35)
                self.esperar_y_cerrar_dialogo_fuentes(timeout=1.0)

                leido = self._leer_zoom(punto)
                if leido is None:
                    # Campo no legible → best-effort: aceptar tras un par de intentos.
                    if intento >= 2:
                        _log.info("Zoom: campo no legible; best-effort tras %d intento(s).", intento)
                        return True
                    continue
                if objetivo is not None and leido == objetivo:
                    _log.info("Zoom confirmado en %s%%.", valor)
                    return True
                _log.warning("Zoom leído=%s%% (esperado %s%%); reintento %d.", leido, valor, intento)

            _log.error("No se pudo confirmar el zoom en %s%% tras 3 intentos.", valor)
            return False
        except Exception as e:
            _log.warning("set_zoom falló: %s", e)
            return False

    def esperar_y_cerrar_dialogo_bloqueado(self, timeout: float = 2.0) -> bool:
        """Si aparece el cartel 'Este proyecto está bloqueado… [315]' (documento abierto
        en otra estación), clickea 'Aceptar' y devuelve True (señal de ABORTAR la página).
        Si no aparece dentro del timeout, devuelve False y el flujo sigue.

        Nota: 'Aceptar' también puede ser el botón de otros diálogos; por eso el timeout es
        corto y se llama solo en la ventana de apertura, antes del pegado."""
        if self.simular:
            _log.info("[SIM] esperar_y_cerrar_dialogo_bloqueado → (sin bloqueo)")
            return False
        import time as _t
        t0 = _t.time()
        while _t.time() - t0 < timeout:
            rect = self._rect_boton_por_texto(["Aceptar"])
            if rect:
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                self._pyautogui.click(cx, cy)
                self.esperar(0.5)
                _log.info("Cartel 'bloqueado [315]' cerrado (Aceptar en %d,%d) → abortar página.",
                          cx, cy)
                return True
            self.esperar(0.3)
        return False

    # ── Acciones ──────────────────────────────────────────────
    def esperar(self, seg: float):
        self._check_cancel()
        if self.simular:
            _log.info("[SIM] esperar(%.2f)", seg)
            return
        # Dormir en tramos chicos para poder abortar rápido ante la cancelación.
        restante = max(0.0, seg)
        while restante > 0:
            self._check_cancel()
            paso = 0.05 if restante > 0.05 else restante
            time.sleep(paso)
            restante -= paso

    def click(self, x: int, y: int, dobles: bool = False):
        if self.simular:
            _log.info("[SIM] click(%d, %d)%s", x, y, " x2" if dobles else "")
            return
        if not self.asegurar_foco():
            _log.warning("click abortado: Quark no está en primer plano.")
            return
        self._pyautogui.click(x, y, clicks=2 if dobles else 1, interval=0.08)

    def click_script_y_play(self, coord_script, coord_play, espera: float = 8.0) -> bool:
        """Selecciona el script dedicado en el palette y presiona Play. Espera a que
        el pegado termine (delay heurístico). Devuelve False si faltan coordenadas."""
        if not coord_play:
            _log.warning("click_script_y_play: falta calibrar 'play'.")
            return False
        if not self.asegurar_foco():
            _log.warning("click_script_y_play abortado: Quark no está en primer plano.")
            return False
        if coord_script:
            self.click(int(coord_script[0]), int(coord_script[1]))
            self.esperar(0.4)
        self.click(int(coord_play[0]), int(coord_play[1]))
        self.esperar(espera)
        return True

    # ── Manipulación de cajas (Armado automático, pasos d–g) ──────────
    def clonar(self, espera: float = 0.4):
        """Duplica la caja seleccionada (Ctrl+D)."""
        if self.simular:
            _log.info("[SIM] clonar (Ctrl+D)")
            return
        if not self.asegurar_foco():
            _log.warning("clonar abortado: Quark no está en primer plano.")
            return
        self._pyautogui.hotkey("ctrl", "d", interval=HOTKEY_INTERVAL)
        self.esperar(espera * FACTOR_POST_PEGADO)

    def deshacer(self, veces: int = 1, espera: float = 0.4):
        """Ctrl+Z `veces` (p.ej. para revertir el clon+arrastre tras una medición de
        calibración de agarre y dejar la maqueta como estaba)."""
        if self.simular:
            _log.info("[SIM] deshacer ×%d (Ctrl+Z)", veces)
            return
        if not self.asegurar_foco():
            _log.warning("deshacer abortado: Quark no está en primer plano.")
            return
        for _ in range(max(1, int(veces))):
            self._pyautogui.hotkey("ctrl", "z", interval=HOTKEY_INTERVAL)
            self.esperar(espera * FACTOR_POST_PEGADO)

    def escribir_en_campo(self, punto, valor, enter: bool = True, espera: float = 0.25,
                          deletes: int = 0) -> bool:
        """Doble-clic en el campo `punto` (selecciona su contenido), presiona `deletes` veces
        Backspace (⌫, 'borrado') y escribe `valor`. El Backspace borra hacia atrás: primero la
        selección y luego el signo '-' residual del src negativo (recursos=2, fotos=0). NO presiona
        Esc: el ítem seleccionado debe seguir seleccionado para aplicarle la geometría."""
        if not punto:
            _log.warning("escribir_en_campo: sin punto calibrado (valor=%r).", valor)
            return False
        sval = str(valor).strip()
        if self.simular:
            _log.info("[SIM] escribir_en_campo %s = %r (bksp=%d)%s", punto, sval, deletes,
                      " + Enter" if enter else "")
            return True
        if not self.asegurar_foco():
            _log.warning("escribir_en_campo abortado: Quark no está en primer plano.")
            return False
        pg = self._pyautogui
        # Doble-clic selecciona el contenido del campo (mismo patrón que set_zoom).
        pg.click(int(punto[0]), int(punto[1]), clicks=2, interval=0.08)
        self.esperar(0.2 * FACTOR_POST_PEGADO)
        for _ in range(max(0, int(deletes))):
            pg.press("backspace")
            self.esperar(0.05 * FACTOR_POST_PEGADO)
        pg.typewrite(sval, interval=0.05)
        self.esperar(0.1 * FACTOR_POST_PEGADO)
        if enter:
            pg.press("enter")
        self.esperar(espera * FACTOR_POST_PEGADO)
        return True

    def seleccionar_plantilla(self, punto, n) -> bool:
        """Escribe n (1/2/3) en el selector de plantilla para cambiar la plantilla activa."""
        return self.escribir_en_campo(punto, str(n))

    def cortar(self, espera: float = 0.4):
        """Corta el ítem seleccionado (Ctrl+X)."""
        if self.simular:
            _log.info("[SIM] cortar (Ctrl+X)")
            return
        if not self.asegurar_foco():
            _log.warning("cortar abortado: Quark no está en primer plano.")
            return
        self._pyautogui.hotkey("ctrl", "x", interval=HOTKEY_INTERVAL)
        self.esperar(espera * FACTOR_POST_PEGADO)

    def pegar(self, espera: float = 0.4):
        """Pega el ítem del portapapeles (Ctrl+V) en la plantilla/vista activa."""
        if self.simular:
            _log.info("[SIM] pegar (Ctrl+V)")
            return
        if not self.asegurar_foco():
            _log.warning("pegar abortado: Quark no está en primer plano.")
            return
        self._pyautogui.hotkey("ctrl", "v", interval=HOTKEY_INTERVAL)
        self.esperar(espera * FACTOR_POST_PEGADO)

    def redimensionar_foto(self, sel, campo_a, campo_al, a_val, al_val) -> bool:
        """Selecciona la foto (clic) y escribe A (Ancho) y Al (Alto) en el panel de medidas."""
        if not sel:
            return False
        if self.simular:
            _log.info("[SIM] redimensionar_foto sel=%s A=%r Al=%r", sel, a_val, al_val)
            return True
        if not self.asegurar_foco():
            _log.warning("redimensionar_foto abortado: Quark no está en primer plano.")
            return False
        self.click(int(sel[0]), int(sel[1]))          # seleccionar la foto
        self.esperar(0.2 * FACTOR_POST_PEGADO)
        if a_val:
            self.escribir_en_campo(campo_a, a_val)
        if al_val:
            self.escribir_en_campo(campo_al, al_val)
        return True

    def seleccionar_todo_y_copiar(self, espera: float = 0.3):
        """Selecciona todo el texto del box activo y lo copia (Ctrl+A, Ctrl+C)."""
        if self.simular:
            _log.info("[SIM] seleccionar_todo_y_copiar (Ctrl+A, Ctrl+C)")
            return
        self._pyautogui.hotkey("ctrl", "a", interval=HOTKEY_INTERVAL)
        self.esperar(0.15 * FACTOR_POST_PEGADO)
        self._pyautogui.hotkey("ctrl", "c", interval=HOTKEY_INTERVAL)
        self.esperar(espera * FACTOR_POST_PEGADO)

    def arrastrar(self, p_src, p_dst, duracion: float = 0.6):
        """Arrastra desde p_src hasta p_dst (mouseDown en src → mueve → mouseUp en dst)."""
        if not p_src or not p_dst:
            _log.warning("arrastrar: faltan coordenadas (src=%s, dst=%s).", p_src, p_dst)
            return False
        if self.simular:
            _log.info("[SIM] arrastrar %s → %s", p_src, p_dst)
            return True
        if not self.asegurar_foco():
            _log.warning("arrastrar abortado: Quark no está en primer plano.")
            return False
        pg = self._pyautogui
        pg.moveTo(int(p_src[0]), int(p_src[1]))
        self.esperar(0.1 * FACTOR_POST_PEGADO)
        pg.mouseDown()
        pg.moveTo(int(p_dst[0]), int(p_dst[1]), duration=max(0.1, duracion * FACTOR_POST_PEGADO))
        pg.mouseUp()
        self.esperar(0.3 * FACTOR_POST_PEGADO)
        return True

    def copiar_desde(self, p_src, espera: float = 0.3):
        """Click en el box de origen y copia todo su texto (para firma/epígrafe)."""
        if self.simular:
            _log.info("[SIM] copiar_desde %s", p_src)
            return
        if not self.asegurar_foco():
            _log.warning("copiar_desde abortado: Quark no está en primer plano.")
            return
        self.click(int(p_src[0]), int(p_src[1]), dobles=True)  # entrar al box en modo texto
        self.esperar(0.2 * FACTOR_POST_PEGADO)
        self.seleccionar_todo_y_copiar(espera)

    def reemplazar_con_atajo(self, p_dst):
        """Click en el texto destino, lo selecciona y aplica el atajo de reemplazo (Ctrl+Alt+U)."""
        if not p_dst:
            return False
        if self.simular:
            _log.info("[SIM] reemplazar_con_atajo %s (Ctrl+Alt+U)", p_dst)
            return True
        if not self.asegurar_foco():
            _log.warning("reemplazar_con_atajo abortado: Quark no está en primer plano.")
            return False
        self.click(int(p_dst[0]), int(p_dst[1]), dobles=True)  # entrar al texto
        self.esperar(0.15 * FACTOR_POST_PEGADO)
        self._pyautogui.hotkey("ctrl", "a", interval=HOTKEY_INTERVAL)   # seleccionar el texto
        self.esperar(0.15 * FACTOR_POST_PEGADO)
        self._pyautogui.hotkey("ctrl", "alt", "u", interval=HOTKEY_INTERVAL)
        self.esperar(0.3 * FACTOR_POST_PEGADO)
        return True

    def arrastrar_con_correccion(self, p_src, p_dst, leer_pos_fn=None,
                                 tol: int = 6, max_iter: int = 4, duracion: float = 0.6) -> bool:
        """Arrastra p_src→p_dst y, si hay lector de posición (leer_pos_fn()->(x,y)|None),
        corrige iterativamente (P6b): mide dónde quedó la caja, calcula el delta vs p_dst y
        re-arrastra por ese delta hasta caer dentro de `tol` px o agotar `max_iter`. Sin lector,
        hace un solo arrastre (comportamiento actual)."""
        if not self.arrastrar(p_src, p_dst, duracion=duracion):
            return False
        if leer_pos_fn is None:
            return True
        for _ in range(max_iter):
            try:
                pos = leer_pos_fn()
            except Exception:
                pos = None
            if not pos:
                return True   # sin lectura → best-effort
            dx = int(p_dst[0]) - int(pos[0])
            dy = int(p_dst[1]) - int(pos[1])
            if abs(dx) <= tol and abs(dy) <= tol:
                return True
            _log.info("Corrección de posición: delta=(%d,%d) → re-arrastro.", dx, dy)
            self.arrastrar((int(pos[0]), int(pos[1])),
                           (int(pos[0]) + dx, int(pos[1]) + dy), duracion=duracion)
        return True

    def clonar_y_arrastrar(self, p_src, p_dst, p_grab=None, duracion: float = 0.6,
                           leer_pos_fn=None):
        """Selecciona la caja de origen, la clona (Ctrl+D) y arrastra el clon al destino.
        `p_grab` (x, y) es el punto donde queda el clon (calibrado: origen del clon B); si es
        None se cae al viejo `p_src + CLON_OFFSET`. Si se pasa `leer_pos_fn`, afina la posición
        con corrección iterativa (P6b)."""
        if not p_src or not p_dst:
            return False
        if not self.asegurar_foco():
            _log.warning("clonar_y_arrastrar abortado: Quark no está en primer plano.")
            return False
        self.click(int(p_src[0]), int(p_src[1]))   # seleccionar la caja original
        self.esperar(0.2 * FACTOR_POST_PEGADO)
        self.clonar()
        # Punto de agarre del clon: el calibrado (B) o, si falta, el fijo respecto del original.
        if p_grab:
            pg = (int(p_grab[0]), int(p_grab[1]))
        else:
            pg = (int(p_src[0]) + CLON_OFFSET_X, int(p_src[1]) + CLON_OFFSET_Y)
        return self.arrastrar_con_correccion(pg, p_dst, leer_pos_fn=leer_pos_fn,
                                             duracion=duracion)

    def ensanchar_caja(self, p_edge, p_rlimit, duracion: float = 0.6):
        """Ensancha la caja seleccionada arrastrando su borde derecho hasta el límite derecho."""
        return self.arrastrar(p_edge, p_rlimit, duracion=duracion)

    def guardar(self):
        """Ctrl+S + Enter (por si aparece el diálogo de guardar)."""
        if self.simular:
            _log.info("[SIM] guardar (Ctrl+S + Enter)")
            return
        if not self.asegurar_foco():
            _log.warning("guardar abortado: Quark no está en primer plano.")
            return
        self._pyautogui.hotkey("ctrl", "s", interval=HOTKEY_INTERVAL)
        self.esperar(0.8)
        self._pyautogui.press("enter")
        self.esperar(0.6)

    def cerrar(self):
        """Cierra el documento (Ctrl+F4) + Enter (si pregunta por cambios)."""
        if self.simular:
            _log.info("[SIM] cerrar (Ctrl+F4 + Enter)")
            return
        if not self.asegurar_foco():
            _log.warning("cerrar abortado: Quark no está en primer plano.")
            return
        self._pyautogui.hotkey("ctrl", "f4", interval=HOTKEY_INTERVAL)
        self.esperar(0.8)
        self._pyautogui.press("enter")
        self.esperar(0.6)

    def exportar_pdf(self, nombre: str, espera_dialogo: float = 1.0,
                     espera_export: float = 2.0) -> bool:
        """Exporta el layout activo a PDF: Ctrl+Alt+P abre el diálogo de exportación con el
        campo de nombre ya seleccionado (comportamiento por defecto de Quark); escribe
        `nombre` (sin extensión) y confirma con Enter. No espera a que el PDF aparezca en
        disco — eso lo hace el poll del orquestador de export (services/pdf_mover_watcher.py)."""
        if self.simular:
            _log.info("[SIM] exportar_pdf(%r) (Ctrl+Alt+P + nombre + Enter)", nombre)
            return True
        if not self.asegurar_foco():
            _log.warning("exportar_pdf abortado: Quark no está en primer plano.")
            return False
        self._pyautogui.hotkey("ctrl", "alt", "p", interval=HOTKEY_INTERVAL)
        self.esperar(espera_dialogo)
        # Si un cartel de fuentes se coló justo antes del diálogo de export, limpiarlo.
        self.esperar_y_cerrar_dialogo_fuentes(timeout=1.0)
        self._pyautogui.typewrite(str(nombre), interval=0.03)
        self.esperar(0.2)
        self._pyautogui.press("enter")
        self.esperar(espera_export)
        return True

    def posicion_mouse(self):
        """(x, y) actual del mouse (para calibrar). None en simulación."""
        if self.simular or self._pyautogui is None:
            return None
        p = self._pyautogui.position()
        return (int(p.x), int(p.y))
