// =============================================================
//  AplicarModeloRecursos.js
//  QuarkXPress 2018 v14.x (QX.js) — director de diferencias (SOLO recursos)
// -------------------------------------------------------------
//  Aplica una lista de operaciones de GEOMETRÍA/CANTIDAD de recursos (mover,
//  redimensionar, clonar, eliminar, renombrar) calculada en Python
//  (model/recurso_plan.calcular_diferencias). Usa EXCLUSIVAMENTE los 5
//  primitivos confirmados como seguros en producción (ver "PegarNota v6.js"):
//    mover/redimensionar → reescribe --qx-left/top/right/bottom en mm
//    clonar              → cloneNode(true) + limpiar box-id/box-uid +
//                           reposicionar + renombrar + appendChild
//    eliminar            → removeChild
//    renombrar           → setAttribute('box-name', ...)
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
            var nueva = origen.cloneNode(true);
            // cloneNode del box entero no lo registra Quark tal cual: hay que
            // quitar box-id/box-uid (los genera Quark) para que no la descarte
            // por ID duplicado (mismo patrón que PegarNota v6.js crearCajaDesde).
            try { nueva.removeAttribute("box-id"); } catch (e0) {}
            try { nueva.removeAttribute("box-uid"); } catch (e1) {}
            var nombreFinal = op.nuevo_box_name || (op.origen_box + "_clon" + i);
            try { nueva.setAttribute("box-name", nombreFinal); } catch (e2) {}
            var st = nueva.getAttribute("style") || "";
            if (op.left_mm != null) st = setVar(st, "left", op.left_mm);
            if (op.top_mm != null)  st = setVar(st, "top", op.top_mm);
            if (op.left_mm != null && op.width_mm != null)  st = setVar(st, "right", op.left_mm + op.width_mm);
            if (op.top_mm != null && op.height_mm != null)  st = setVar(st, "bottom", op.top_mm + op.height_mm);
            if (op.page) st = setPagina(st, op.page);
            nueva.setAttribute("style", st);
            if (origen.parentNode) origen.parentNode.appendChild(nueva);
            r.box_name = nombreFinal;

          } else if (op.tipo === "eliminar") {
            var b2 = porNombre(op.box_name);
            if (!b2) throw "caja '" + op.box_name + "' no encontrada";
            if (!b2.parentNode) throw "caja '" + op.box_name + "' sin parentNode";
            b2.parentNode.removeChild(b2);
            r.box_name = op.box_name;

          } else if (op.tipo === "renombrar") {
            var b3 = porNombre(op.box_name);
            if (!b3) throw "caja '" + op.box_name + "' no encontrada";
            b3.setAttribute("box-name", op.nuevo_box_name);
            r.box_name = op.nuevo_box_name;

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
