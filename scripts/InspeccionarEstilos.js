// =============================================================
//  InspeccionarEstilos.js  ·  QuarkXPress 2018 (QX.js)
// -------------------------------------------------------------
//  Diagnóstico de 1 uso. Con la maqueta abierta, corré este script.
//  Vuelca las HOJAS DE ESTILO del proyecto (carácter y párrafo) y los `class`
//  de los qx-span/qx-p que mencionan "E-", "INTERT" o "NEGRITA", para obtener
//  los strings EXACTOS de las clases "E- NEGRITA" y "E- INTERTÍTULO".
//
//  Abrí y pegá:
//    C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_estilos.txt
// =============================================================
(function () {
  try {
    var out = [];
    out.push("=== InspeccionarEstilos — " + new Date() + " ===");

    // --- Hojas de estilo del proyecto vía getAssets ---
    function volcarAssets(nombreTipo, tipoConst) {
      out.push("\n--- getAssets(" + nombreTipo + ") ---");
      try {
        var proj = (typeof app.activeProject === "function") ? app.activeProject() : app.activeProject;
        var assets = proj.getAssets(tipoConst);
        // El formato puede variar; volcamos crudo + intento de listar nombres.
        try { out.push("  raw: " + JSON.stringify(assets)); } catch (eJ) { out.push("  (no serializable)"); }
        if (assets && assets.length) {
          for (var i = 0; i < assets.length; i++) {
            var a = assets[i];
            var nom = (a && (a.name || a.Name || a.styleName)) || a;
            out.push("  [" + i + "] " + nom);
          }
        }
      } catch (e) { out.push("  ERROR: " + e); }
    }
    try {
      var AT = app.constants && app.constants.assetTypes;
      out.push("assetTypes disponibles: " + (AT ? JSON.stringify(Object.keys(AT)) : "(no hay app.constants.assetTypes)"));
      if (AT) {
        if (AT.kAssetCharStyle !== undefined) volcarAssets("kAssetCharStyle", AT.kAssetCharStyle);
        if (AT.kAssetParaStyle !== undefined) volcarAssets("kAssetParaStyle", AT.kAssetParaStyle);
      }
    } catch (eA) { out.push("assetTypes ERROR: " + eA); }

    // --- class de qx-span y qx-p que mencionen E-/INTERT/NEGRITA (en el DOM) ---
    var layout = app.activeLayoutDOM();
    function dumpClasses(tag) {
      out.push("\n--- " + tag + " con class que mencione E-/INTERT/NEGRITA/BAJADA/TEXTO ---");
      var els = layout.getElementsByTagName(tag);
      var vistos = {};
      for (var i = 0; i < els.length; i++) {
        var c = els[i].getAttribute("class");
        if (!c) continue;
        var up = c.toUpperCase();
        if (up.indexOf("E-") >= 0 || up.indexOf("INTERT") >= 0 || up.indexOf("NEGRIT") >= 0 ||
            up.indexOf("BAJADA") >= 0 || up.indexOf("TEXTO") >= 0) {
          if (!vistos[c]) { vistos[c] = 1; out.push("  class='" + c + "'"); }
        }
      }
      if (out[out.length - 1].indexOf("---") >= 0) out.push("  (ninguno)");
    }
    dumpClasses("qx-span");
    dumpClasses("qx-p");

    var texto = out.join("\n");
    var ruta = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_estilos.txt";
    var escrito = false;
    try { fs.writeFileSync(ruta, texto, "utf8"); escrito = true; } catch (eW) {}
    alert(escrito ? ("Volcado OK. Abrí y pegá:\n" + ruta)
                  : ("No se pudo escribir. Texto:\n\n" + texto.substring(0, 3000)));

  } catch (err) {
    alert("InspeccionarEstilos: error:\n" + err);
  }
})();
