// =============================================================
//  InspeccionarElementos.js  ·  QuarkXPress 2018 (QX.js)
// -------------------------------------------------------------
//  Busca cómo se representan los GRUPOS en el DOM del layout:
//    1) cuenta todos los tipos de elemento (tagName) presentes,
//    2) vuelca CUALQUIER elemento cuyo tag contenga "group" con
//       todos sus atributos + los box-name que contiene,
//    3) vuelca los atributos COMPLETOS (sin truncar) de Box427 y
//       de su spread/layout, por si hay una referencia de grupo.
//
//  USO: con la maqueta abierta, corré este script.
//  Abrí y pegá:
//    C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_elementos.txt
// =============================================================
(function () {
  try {
    var layout = app.activeLayoutDOM();
    if (!layout) { alert("InspeccionarElementos: no hay layout activo."); return; }

    var out = [];
    out.push("=== InspeccionarElementos — " + new Date() + " ===");

    // 1) Conteo de tags.
    var todos = layout.getElementsByTagName("*");
    var conteo = {};
    for (var i = 0; i < todos.length; i++) {
      var t = "";
      try { t = (todos[i].tagName || "").toLowerCase(); } catch (e) {}
      if (!t) continue;
      conteo[t] = (conteo[t] || 0) + 1;
    }
    out.push("\n--- Tipos de elemento (tag: cantidad) ---");
    for (var k in conteo) { if (conteo.hasOwnProperty(k)) out.push("  " + k + ": " + conteo[k]); }

    function dumpAttrsFull(el, indent) {
      var res = [];
      indent = indent || "";
      try {
        if (el.attributes && el.attributes.length) {
          for (var a = 0; a < el.attributes.length; a++) {
            res.push(indent + el.attributes[a].name + " = " + el.attributes[a].value);
          }
        } else if (typeof el.getAttributeNames === "function") {
          var names = el.getAttributeNames();
          for (var n = 0; n < names.length; n++) {
            res.push(indent + names[n] + " = " + el.getAttribute(names[n]));
          }
        }
      } catch (e) { res.push(indent + "(error: " + e + ")"); }
      return res.join("\n");
    }

    // 2) Elementos tipo "group".
    out.push("\n--- Elementos con 'group' en el tag ---");
    var hayGroup = false;
    for (var g = 0; g < todos.length; g++) {
      var tg = "";
      try { tg = (todos[g].tagName || "").toLowerCase(); } catch (e) {}
      if (tg.indexOf("group") === -1) continue;
      hayGroup = true;
      out.push("<" + tg + ">");
      out.push(dumpAttrsFull(todos[g], "  "));
      // box-name de las cajas que contiene
      try {
        var hijos = todos[g].getElementsByTagName("qx-box");
        var nombres = [];
        for (var h = 0; h < hijos.length; h++) nombres.push(hijos[h].getAttribute("box-name"));
        out.push("  cajas dentro: " + (nombres.length ? nombres.join(", ") : "(ninguna)"));
      } catch (e) {}
      out.push("");
    }
    if (!hayGroup) out.push("  (NINGÚN elemento con 'group' en el tag)");

    // 3) Atributos COMPLETOS de Box427 + su cadena de ancestros con TODOS sus atributos.
    out.push("\n--- Box427: atributos completos + ancestros ---");
    var idx = {};
    var all = layout.getElementsByTagName("qx-box");
    for (var b = 0; b < all.length; b++) {
      var nm = all[b].getAttribute("box-name");
      if (nm) idx[nm] = all[b];
    }
    var box = idx["Box427"];
    if (box) {
      var cur = box, lvl = 0, guard = 0;
      while (cur && guard < 30) {
        var tag = "";
        try { tag = (cur.tagName || cur.nodeName || "").toLowerCase(); } catch (e) {}
        out.push("[" + lvl + "] <" + tag + ">");
        out.push(dumpAttrsFull(cur, "    "));
        if (tag === "qx-layout" || tag === "#document") break;
        cur = cur.parentNode || null;
        lvl++; guard++;
      }
    } else {
      out.push("  Box427 no encontrado.");
    }

    var texto = out.join("\n");
    var ruta = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_elementos.txt";
    var escrito = false;
    try { fs.writeFileSync(ruta, texto, "utf8"); escrito = true; } catch (eW) {}
    alert(escrito
      ? ("Volcado OK. Abrí y pegá:\n" + ruta)
      : ("No se pudo escribir. Texto:\n\n" + texto.substring(0, 3000)));

  } catch (err) {
    alert("InspeccionarElementos: error:\n" + err);
  }
})();
