"""
quark_cdp — Disparo de scripts QX.js sin pyautogui, vía Chrome DevTools Protocol (CDP).

QuarkXPress 2018 embebe CEF (Chromium Embedded Framework) para su motor de JavaScript
(QX.js) y lo arranca con `--remote-debugging-port=8087` (ver
`XTensions/JSServices/CEF.configuration` dentro de la instalación de Quark). Eso expone
un WebSocket de depuración Chrome estándar sobre el contexto JS real de la aplicación
(la page "JSServiceUI"): se le puede mandar `Runtime.evaluate` con el código fuente de
un script .js y Quark lo ejecuta exactamente como si se hubiese seleccionado ese script
en el palette de JavaScript y apretado Play — sin clics, sin coordenadas calibradas, sin
necesidad de que la ventana de Quark esté en primer plano.

Verificado en vivo (QuarkXPress 2018.exe, puerto 8087): `app`, `fs`, `app.evalScript`,
`app.activeProject`, `app.activeLayout`, `app.activeLayoutDOM`, `app.importScript` y
`setTimeout` están disponibles en ese contexto. `app.addEventListener` y `app.doScript`
NO existen en esta build — por eso el disparo sigue viniendo de afuera (Python), no de
un listener registrado dentro de Quark.

Esto NO es una API oficial ni soportada por Quark: depende de que ese archivo de
configuración de la instalación siga trayendo el puerto habilitado, y podría cambiar en
una actualización futura. Por eso todo el árbol de llamadas de este módulo está pensado
para fallar rápido y en silencio (`disponible()` / excepciones capturadas) y dejar que el
llamador caiga de vuelta al mecanismo pyautogui existente (`QuarkAutomator.click_script_y_play`).

Riesgo conocido: los scripts (p.ej. PegarNota v6.js) usan `alert()` en sus caminos de
error. Un `alert()` es un diálogo nativo bloqueante del motor CEF: si se dispara durante
una corrida sin operador presente, se quedaría colgado para siempre. Por eso `evaluar()`
habilita `Page` y auto-descarta cualquier diálogo JS que aparezca mientras se espera el
resultado, devolviendo igualmente el error original del script.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import requests

_log = logging.getLogger(__name__)

PUERTO_DEFAULT = 8087
TITULO_TARGET = "JSServiceUI"


class CDPError(Exception):
    pass


def _listar_targets(puerto: int, timeout: float) -> list:
    r = requests.get(f"http://127.0.0.1:{puerto}/json", timeout=timeout)
    r.raise_for_status()
    return r.json()


def descubrir_target(puerto: int = PUERTO_DEFAULT, timeout: float = 2.0) -> Optional[str]:
    """URL de WebSocket de depuración de la page JSServiceUI (contexto real de app/fs de
    QuarkXPress), o None si Quark no está corriendo o el puerto no responde."""
    try:
        targets = _listar_targets(puerto, timeout)
    except Exception as e:
        _log.info("quark_cdp: puerto %d no disponible (%s).", puerto, e)
        return None
    for t in targets:
        if t.get("title") == TITULO_TARGET and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    _log.info("quark_cdp: no se encontró el target '%s' entre %d targets.",
               TITULO_TARGET, len(targets))
    return None


def disponible(puerto: int = PUERTO_DEFAULT, timeout: float = 1.5) -> bool:
    """Chequeo rápido: True si Quark está corriendo y el canal CDP responde."""
    return descubrir_target(puerto, timeout) is not None


def evaluar(ws_url: str, expression: str, timeout: float = 60.0) -> dict:
    """Manda Runtime.evaluate por WebSocket y devuelve el 'result' de CDP. Mientras espera,
    auto-descarta cualquier diálogo JS (alert/confirm/prompt) que el script dispare, para
    que un error interno del script no deje a Quark colgado esperando un clic humano.

    Lanza CDPError si la conexión falla, hay timeout, o QX.js reporta una excepción."""
    import websocket  # websocket-client; import diferido: solo hace falta si se usa CDP.

    ws = websocket.create_connection(ws_url, timeout=timeout)
    eval_id = 2
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        ws.send(json.dumps({
            "id": eval_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }))
        ws.settimeout(timeout)
        msg = None
        while True:
            raw = ws.recv()
            evt = json.loads(raw)
            if evt.get("method") == "Page.javascriptDialogOpening":
                _log.warning("quark_cdp: el script abrió un diálogo (%s); se descarta.",
                             evt.get("params", {}).get("message", ""))
                ws.send(json.dumps({
                    "id": 99,
                    "method": "Page.handleJavaScriptDialog",
                    "params": {"accept": True},
                }))
                continue
            if evt.get("id") == eval_id:
                msg = evt
                break
    finally:
        try:
            ws.close()
        except Exception:
            pass

    if msg is None:
        raise CDPError("Sin respuesta de Runtime.evaluate.")
    if "error" in msg:
        raise CDPError(f"CDP error: {msg['error']}")
    result = msg.get("result", {})
    if result.get("exceptionDetails"):
        raise CDPError(f"Excepción JS: {result['exceptionDetails']}")
    return result.get("result", {})


def info_app(puerto: int = PUERTO_DEFAULT, timeout: float = 5.0) -> Optional[dict]:
    """Introspección de la instancia de Quark corriendo: {"version", "name"} (p.ej.
    {"version": "14.0.0", "name": "QuarkXPress"} en QuarkXPress 2018) más qué métodos de
    automatización expone `app` en esta build. Pensado para, con el tiempo, armar un
    script de pegado único que despache por versión/feature-detection en vez de mantener
    un .js paralelo por versión de Quark — ver services/quark_cdp.py y el plan de
    investigación de automatización. None si Quark no está corriendo o no responde."""
    ws_url = descubrir_target(puerto, timeout)
    if not ws_url:
        return None
    expr = (
        "(function(){"
        "var out = {version: app.version, name: app.name, apis: {}};"
        "['evalScript','doScript','addEventListener','importScript',"
        " 'activeLayoutDOM','activeBoxesDOM'].forEach(function(k){"
        "  out.apis[k] = typeof app[k];"
        "});"
        "return JSON.stringify(out);"
        "})()"
    )
    try:
        result = evaluar(ws_url, expr, timeout=timeout)
        return json.loads(result.get("value", "{}"))
    except Exception as e:
        _log.warning("quark_cdp.info_app: falló (%s).", e)
        return None


def ejecutar_script(ruta_js, puerto: int = PUERTO_DEFAULT, timeout: float = 60.0) -> bool:
    """Lee `ruta_js` y lo ejecuta dentro de QuarkXPress vía CDP, como si se hubiese
    apretado Play sobre ese script en el palette de JavaScript. Devuelve True/False y
    nunca lanza (para que el llamador pueda caer de vuelta a pyautogui sin try/except)."""
    ws_url = descubrir_target(puerto)
    if not ws_url:
        return False
    try:
        codigo = Path(ruta_js).read_text(encoding="utf-8")
    except Exception as e:
        _log.warning("quark_cdp.ejecutar_script: no se pudo leer %s (%s).", ruta_js, e)
        return False
    try:
        evaluar(ws_url, codigo, timeout=timeout)
        return True
    except Exception as e:
        _log.warning("quark_cdp.ejecutar_script: falló ejecutando %s (%s).", ruta_js, e)
        return False
