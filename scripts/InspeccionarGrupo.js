// =============================================================
//  InspeccionarGrupo.js  ·  QuarkXPress 2018 (QX.js)
// -------------------------------------------------------------
//  Diagnóstico de 1 uso. Con la maqueta abierta, corré este
//  script desde el palette JavaScript de Quark.
//
//  Para cada caja ancla de recurso presente en el layout vuelca:
//    1) la cadena de ancestros (para detectar un contenedor qx-group),
//    2) los atributos propios de la caja (para detectar un atributo de grupo),
//    3) si hay ancestro qx-group: TODAS sus cajas hijas (box-name + bordes)
//       y los atributos/style del propio qx-group.
//
//  Escribe el reporte completo en:
//    C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_grupo.txt
//  y muestra un resumen corto en un alert.
//
//  → Abrí ese .txt y pegá su contenido en el chat.
// =============================================================
(function () {
  try {
    var layout = app.activeLayoutDOM();
    if (!layout) { alert("InspeccionarGrupo: no hay layout activo."); return; }

    // Índice de cajas por box-name (mismo patrón que PegarNota v6).
    var idx = {};
    var all = layout.getElementsByTagName("qx-box");
    for (var i = 0; i < all.length; i++) {
      var nm = all[i].getAttribute("box-name");
      if (nm) idx[nm] = all[i];
    }

    // Cajas ancla de cada recurso (box-name que rellena PegarNota v6).
    var ANCLAS = [
      ["textual simple",   "Box427"],
      ["textual x2",       "Box1053"],
      ["textual x3",       "Box1166"],
      ["textual con_foto", "Box1138"],
      ["textual con_foto_xl", "Box417"],
      ["dato",             "Box1125"],
      ["numero",           "Box1063"],
      ["qr",               "Box1657"]
    ];

    function tag(el) {
      var t = "";
      try { t = el.tagName || (el.nodeName || ""); } catch (e) {}
      return ("" + t).toLowerCase();
    }

    // Lista "name=value" de todos los atributos de un elemento.
    function dumpAttrs(el, indent) {
      var out = [];
      indent = indent || "";
      try {
        if (el.attributes && el.attributes.length) {
          for (var a = 0; a < el.attributes.length; a++) {
            var at = el.attributes[a];
            var val = "" + (at.value != null ? at.value : "");
            if (val.length > 300) val = val.substring(0, 300) + "…";
            out.push(indent + at.name + " = " + val);
          }
        } else if (typeof el.getAttributeNames === "function") {
          var names = el.getAttributeNames();
          for (var n = 0; n < names.length; n++) {
            var v = "" + (el.getAttribute(names[n]) || "");
            if (v.length > 300) v = v.substring(0, 300) + "…";
            out.push(indent + names[n] + " = " + v);
          }
        } else {
          out.push(indent + "(no se pudo enumerar atributos)");
        }
      } catch (e) {
        out.push(indent + "(error leyendo atributos: " + e + ")");
      }
      return out.join("\n");
    }

    // Bordes --qx-* del style de una caja, resumidos en una línea.
    function bordes(el) {
      var s = "";
      try { s = el.getAttribute("style") || ""; } catch (e) {}
      function b(lado) {
        var m = s.match(new RegExp("--qx-" + lado + ":(-?[0-9.]+)mm"));
        return m ? m[1] : "?";
      }
      return "left=" + b("left") + " top=" + b("top") +
             " right=" + b("right") + " bottom=" + b("bottom");
    }

    // Sube por parentNode hasta el tope, devolviendo el primer ancestro qx-group.
    function subirAGrupo(el) {
      var cur = el;
      var guard = 0;
      while (cur && guard < 40) {
        cur = cur.parentNode || null;
        guard++;
        if (!cur) break;
        if (tag(cur) === "qx-group") return cur;
        var t = tag(cur);
        if (t === "qx-layer" || t === "qx-page" || t === "qx-spread" ||
            t === "qx-layout" || t === "#document") break;
      }
      return null;
    }

    var rep = [];
    rep.push("=== InspeccionarGrupo — " + new Date() + " ===");
    rep.push("Total qx-box en el layout: " + all.length);
    rep.push("");

    var encontradas = 0;

    for (var k = 0; k < ANCLAS.length; k++) {
      var rol  = ANCLAS[k][0];
      var name = ANCLAS[k][1];
      var box  = idx[name];
      if (!box) continue;
      encontradas++;

      rep.push("############################################################");
      rep.push("RECURSO: " + rol + "   (ancla " + name + ")");
      rep.push("############################################################");

      // 1) Cadena de ancestros.
      rep.push("--- Cadena de ancestros (de la caja hacia arriba) ---");
      var cur = box, lvl = 0, guard = 0;
      while (cur && guard < 40) {
        var bn = "";
        try { bn = cur.getAttribute ? (cur.getAttribute("box-name") || "") : ""; } catch (e) {}
        rep.push("  [" + lvl + "] <" + tag(cur) + ">" + (bn ? "  box-name=" + bn : ""));
        var t = tag(cur);
        if (t === "qx-layout" || t === "#document") break;
        cur = cur.parentNode || null;
        lvl++; guard++;
      }
      rep.push("");

      // 2) Atributos propios de la caja ancla.
      rep.push("--- Atributos de la caja " + name + " ---");
      rep.push(dumpAttrs(box, "  "));
      rep.push("  BORDES: " + bordes(box));
      rep.push("");

      // 3) Ancestro qx-group + sus cajas hijas.
      var grupo = subirAGrupo(box);
      rep.push("--- ¿Ancestro qx-group? " + (grupo ? "SÍ" : "NO") + " ---");
      if (grupo) {
        rep.push("Atributos del qx-group:");
        rep.push(dumpAttrs(grupo, "  "));
        var hijos = grupo.getElementsByTagName("qx-box");
        rep.push("Cajas del grupo (" + hijos.length + "):");
        for (var h = 0; h < hijos.length; h++) {
          var hn = hijos[h].getAttribute("box-name") || "(sin nombre)";
          var ct = hijos[h].getAttribute("box-content-type") || "";
          rep.push("  · " + hn + " [" + ct + "]  " + bordes(hijos[h]));
        }
      }
      rep.push("");
    }

    if (encontradas === 0) {
      rep.push("No se encontró ninguna caja ancla de recurso en este layout.");
    }

    var texto = rep.join("\n");

    // Escribir a archivo (fs disponible en el runtime de Quark; ver LeerMaqueta.js).
    var rutaOut = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_grupo.txt";
    var escrito = false;
    try {
      fs.writeFileSync(rutaOut, texto, "utf8");
      escrito = true;
    } catch (eW) {
      escrito = false;
    }

    var resumen = "InspeccionarGrupo: " + encontradas + " recurso(s) encontrado(s).\n";
    resumen += escrito
      ? ("Reporte escrito en:\n" + rutaOut + "\n\nAbrí ese archivo y pegá su contenido.")
      : ("No se pudo escribir el archivo. Copiá el texto de este alert:\n\n" +
         texto.substring(0, 3000));
    alert(resumen);

  } catch (err) {
    alert("InspeccionarGrupo: error:\n" + err);
  }
})();
