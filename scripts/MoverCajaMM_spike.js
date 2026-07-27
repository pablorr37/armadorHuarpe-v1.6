// =============================================================
//  MoverCajaMM_spike.js  —  SPIKE de ESCRITURA de geometría (mm)
//  QuarkXPress 2018 v14.x (QX.js) — pensado para correr por CDP
// -------------------------------------------------------------
//  Objetivo (F2 del maquetador): confirmar si se puede MOVER/REDIMENSIONAR
//  una caja escribiendo las variables --qx-left/top/right/bottom (en mm) del
//  style inline — el MISMO sistema que ya leemos con LeerMaquetaCDP.js.
//
//  Es una EXPRESIÓN que devuelve un objeto con el antes/después para que
//  Python capture el resultado (returnByValue). Mueve la PRIMERA caja
//  seleccionada (app.activeBoxesDOM()) +DELTA_MM en X e Y, preservando el
//  tamaño. Envuelto en compound-undo para poder revertir con Ctrl+Z.
//
//  Uso: seleccionar UNA caja en Quark y ejecutar. Revisar out.movio.
// =============================================================
(function () {
  var DELTA_MM = 10.0;
  function num(style, key) {
    var m = (style || "").match(new RegExp("--qx-" + key + ":(-?[0-9.]+)mm"));
    return m ? parseFloat(m[1]) : null;
  }
  function setVar(style, key, valMM) {
    var re = new RegExp("--qx-" + key + ":-?[0-9.]+mm");
    var nuevo = "--qx-" + key + ":" + valMM.toFixed(4) + "mm";
    if (re.test(style)) return style.replace(re, nuevo);
    return nuevo + ";" + style;
  }
  function leerGeom(box) {
    var s = "";
    try { s = box.getAttribute("style") || ""; } catch (e) {}
    return { left: num(s, "left"), top: num(s, "top"),
             right: num(s, "right"), bottom: num(s, "bottom") };
  }

  var out = { ok: true, movio: false, antes: null, despues: null, metodo: null, error: null };
  try {
    var sel = app.activeBoxesDOM();
    if (!sel || !sel.length) {
      out.ok = false; out.error = "No hay caja seleccionada.";
      return out;
    }
    var box = sel[0];
    var a = leerGeom(box);
    out.antes = a;
    if (a.left == null || a.top == null) {
      out.ok = false; out.error = "La caja no expone --qx-left/top en mm.";
      return out;
    }

    var undoOk = false;
    try { app.undo.beginCompoundUndo("Spike mover caja mm"); undoOk = true; } catch (e) {}
    try {
      var style = box.getAttribute("style") || "";
      style = setVar(style, "left",   a.left + DELTA_MM);
      style = setVar(style, "top",    a.top + DELTA_MM);
      if (a.right != null)  style = setVar(style, "right",  a.right + DELTA_MM);
      if (a.bottom != null) style = setVar(style, "bottom", a.bottom + DELTA_MM);
      box.setAttribute("style", style);
      out.metodo = "setAttribute(style, --qx-*mm)";
    } finally {
      if (undoOk) { try { app.undo.endCompoundUndo(); } catch (e) {} }
    }

    var b = leerGeom(box);
    out.despues = b;
    out.movio = (b.left != null && a.left != null &&
                 Math.abs((b.left - a.left) - DELTA_MM) < 0.5);
  } catch (err) {
    out.ok = false;
    out.error = String(err);
  }
  return out;
})();
