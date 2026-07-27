// =============================================================
//  AplicarModeloRecursos.js
//  QuarkXPress 2018 v14.x (QX.js) — director de diferencias (SOLO recursos)
// -------------------------------------------------------------
//  Aplica una lista de operaciones de GEOMETRÍA/CANTIDAD de recursos (mover,
//  redimensionar, clonar, eliminar, renombrar) calculada en Python
//  (model/recurso_plan.calcular_diferencias). Usa EXCLUSIVAMENTE primitivos
//  confirmados como seguros en producción (ver "PegarNota v6.js"):
//    mover/redimensionar → reescribe --qx-left/top/right/bottom en mm
//    clonar              → cloneNode(true) + limpiar box-id/box-uid +
//                           fijar box-name ANTES de insertar + appendChild
//    eliminar            → removeChild
//
//  HALLAZGO (jul 2026): Quark solo "registra" el box-name de una caja en el
//  instante en que el nodo se INSERTA en el árbol (appendChild). Mutar el
//  atributo box-name de una caja YA insertada (setAttribute posterior) NO se
//  propaga al modelo interno de Quark — confirmado en vivo (ver nombrador.js).
//  Por eso NO existe un primitivo "renombrar in-place": renombrar una caja
//  existente se implementa como CLONAR-CON-EL-NOMBRE-NUEVO (en la misma
//  posición/página que el original) + ELIMINAR el original — reusa únicamente
//  los primitivos que sí funcionan.
//
//  NO crea contenido de texto ni toca el pegado de PegarNota_JSON.js — es un
//  subsistema aislado para geometría/cantidad de recursos (fotos, cajas de
//  aviso, etc.). Envuelto en UN solo compound-undo (deshacer revierte todo).
//
//  Entrada: plan_recursos.json en la carpeta de scripts de la app:
//    {"operaciones": [ {tipo, box_name, origen_box, nuevo_box_name,
//                        left_mm, top_mm, width_mm, height_mm, page}, ... ]}
//  Salida: expresión que DEVUELVE (returnByValue) {ok, resultados[], error}.
// =============================================================
(function () {
  function num(style, key) {
    var m = (style || "").match(new RegExp("--qx-" + key + ":(-?[0-9.]+)mm"));
    return m ? parseFloat(m[1]) : null;
  }
  function setVar(style, key, valMM) {
    var re = new RegExp("--qx-" + key + ":-?[0-9.]+mm");
    var nuevo = "--qx-" + key + ":" + valMM.toFixed(4) + "mm";
    return re.test(style) ? style.replace(re, nuevo) : (nuevo + ";" + style);
  }
  function setPagina(style, pag) {
    if (!pag) return style;
    if (/--qx-page:[^;]+;/.test(style)) return style.replace(/--qx-page:[^;]+;/, "--qx-page:" + pag + ";");
    return style + "--qx-page:" + pag + ";";
  }

  var out = { ok: true, resultados: [], error: null };
  try {
    var layout = app.activeLayoutDOM();
    if (!layout) {
      out.ok = false;
      out.error = "No hay una maqueta activa en QuarkXPress. Abrí la maqueta y dejala como documento activo.";
      return out;
    }

    var appData = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/";
    var plan;
    try {
      plan = JSON.parse(fs.readFileSync(appData + "plan_recursos.json", "utf8"));
    } catch (e) {
      out.ok = false;
      out.error = "No se pudo leer plan_recursos.json: " + e;
      return out;
    }

    function porNombre(nombre) {
      if (!nombre) return null;
      var all = layout.getElementsByTagName("qx-box");
      for (var i = 0; i < all.length; i++) {
        if (all[i].getAttribute("box-name") === nombre) return all[i];
      }
      return null;
    }

    // Clona `origen`, fija box-name ANTES de insertar (único momento en que
    // Quark lo registra), aplica geometría (la de `geom` si se pasa, o si no
    // la que ya tenía `origen`) y lo inserta en el mismo parentNode. Devuelve
    // el nodo clon ya insertado. Reusado por "clonar" y por el renombrado
    // (clonar-con-nombre-nuevo + eliminar original).
    function clonarConNombre(origen, nombreNuevo, geom) {
      var nueva = origen.cloneNode(true);
      // cloneNode del box entero no lo registra Quark tal cual: hay que
      // quitar box-id/box-uid (los genera Quark) para que no la descarte
      // por ID duplicado (mismo patrón que PegarNota v6.js crearCajaDesde).
      try { nueva.removeAttribute("box-id"); } catch (e0) {}
      try { nueva.removeAttribute("box-uid"); } catch (e1) {}
      try { nueva.setAttribute("box-name", nombreNuevo); } catch (e2) {}
      var st = nueva.getAttribute("style") || "";
      var g = geom || {};
      var leftBase = (g.left_mm != null) ? g.left_mm : num(st, "left");
      var topBase  = (g.top_mm  != null) ? g.top_mm  : num(st, "top");
      var widthBase  = (g.width_mm  != null) ? g.width_mm  : (num(st, "right")  - num(st, "left"));
      var heightBase = (g.height_mm != null) ? g.height_mm : (num(st, "bottom") - num(st, "top"));
      if (leftBase != null) st = setVar(st, "left", leftBase);
      if (topBase != null)  st = setVar(st, "top", topBase);
      if (leftBase != null && widthBase != null)  st = setVar(st, "right", leftBase + widthBase);
      if (topBase != null && heightBase != null)  st = setVar(st, "bottom", topBase + heightBase);
      if (g.page) st = setPagina(st, g.page);
      nueva.setAttribute("style", st);
      if (origen.parentNode) origen.parentNode.appendChild(nueva);
      return nueva;
    }

    var ops = plan.operaciones || [];
    var undoOk = false;
    try { app.undo.beginCompoundUndo("Aplicar modelo de recursos"); undoOk = true; } catch (e) {}

    try {
      for (var i = 0; i < ops.length; i++) {
        var op = ops[i];
        var r = { tipo: op.tipo, ok: true, error: null };
        try {
          if (op.tipo === "mover" || op.tipo === "redimensionar") {
            var box = porNombre(op.box_name);
            if (!box) throw "caja '" + op.box_name + "' no encontrada";
            var style = box.getAttribute("style") || "";
            if (op.left_mm != null) style = setVar(style, "left", op.left_mm);
            if (op.top_mm != null)  style = setVar(style, "top", op.top_mm);
            if (op.left_mm != null && op.width_mm != null)  style = setVar(style, "right", op.left_mm + op.width_mm);
            if (op.top_mm != null && op.height_mm != null)  style = setVar(style, "bottom", op.top_mm + op.height_mm);
            if (op.page) style = setPagina(style, op.page);
            box.setAttribute("style", style);
            r.box_name = op.box_name;

          } else if (op.tipo === "clonar") {
            // Requiere una caja YA EXISTENTE del mismo rol (origen_box) — QX.js
            // no puede crear una caja desde la nada. Ver docs/maquetador_arquitectura.md.
            var origen = porNombre(op.origen_box);
            if (!origen) throw "caja origen '" + op.origen_box + "' no encontrada";
            var nombreFinal = op.nuevo_box_name || (op.origen_box + "_clon" + i);
            var nueva = clonarConNombre(origen, nombreFinal, {
              left_mm: op.left_mm, top_mm: op.top_mm,
              width_mm: op.width_mm, height_mm: op.height_mm, page: op.page,
            });
            r.box_name = nueva.getAttribute("box-name");

          } else if (op.tipo === "eliminar") {
            var b2 = porNombre(op.box_name);
            if (!b2) throw "caja '" + op.box_name + "' no encontrada";
            if (!b2.parentNode) throw "caja '" + op.box_name + "' sin parentNode";
            b2.parentNode.removeChild(b2);
            r.box_name = op.box_name;

          } else if (op.tipo === "renombrar") {
            // NO existe renombrado in-place (ver hallazgo en la cabecera): se
            // clona la caja existente con el nombre nuevo, en la MISMA
            // posición/página (sin geom override → clonarConNombre copia la
            // geometría del original), y se elimina el original.
            var b3 = porNombre(op.box_name);
            if (!b3) throw "caja '" + op.box_name + "' no encontrada";
            if (!op.nuevo_box_name) throw "falta nuevo_box_name";
            var clon = clonarConNombre(b3, op.nuevo_box_name, null);
            if (b3.parentNode) b3.parentNode.removeChild(b3);
            r.box_name = clon.getAttribute("box-name");

          } else {
            throw "tipo de operación desconocido: " + op.tipo;
          }
        } catch (errOp) {
          r.ok = false;
          r.error = String(errOp);
        }
        out.resultados.push(r);
      }
    } finally {
      if (undoOk) { try { app.undo.endCompoundUndo(); } catch (e) {} }
    }

    out.ok = out.resultados.length > 0 && out.resultados.every(function (r) { return r.ok; });
  } catch (err) {
    out.ok = false;
    out.error = String(err);
  }
  return out;
})();
