// =============================================================
//  MoverCajas_test.js  —  SPIKE experimental (P6a)
//  QuarkXPress 2018 v14.2 (QX.js)
// -------------------------------------------------------------
//  Objetivo: descubrir si QX.js puede SETEAR la posición de una caja.
//  Lee data_pagina.json -> box_positions (coords de PANTALLA calibradas en Python)
//  y prueba varias estrategias para mover Box427 (textual solo). Reporta por alert()
//  qué estrategia (si alguna) cambió la geometría, leída con getBoundingClientRect.
//
//  NOTA: las coords vienen en píxeles de PANTALLA; el DOM del layout usa su propio
//  sistema. Este test sirve para ver (a) si alguna API mueve la caja y (b) qué unidades
//  usa, para después calcular la conversión pantalla<->layout.
// =============================================================
(function () {
  try {
    var layout = app.activeLayoutDOM();

    // --- Leer data_pagina.json (via runtime_config.json) ---
    var _appdataScripts = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/";
    var rutaJSON = "";
    try {
      var _cfg = JSON.parse(fs.readFileSync(_appdataScripts + "runtime_config.json", "utf8").trim());
      rutaJSON = (_cfg.data_pagina_path || "").replace(/\\/g, "/");
    } catch (e) {
      alert("MoverCajas_test: error leyendo runtime_config.json:\n" + e);
      return;
    }
    var boxPositions = {};
    try {
      var data = JSON.parse(fs.readFileSync(rutaJSON, "utf8").trim());
      boxPositions = data.box_positions || {};
    } catch (e) {
      alert("MoverCajas_test: error leyendo data_pagina.json:\n" + e);
      return;
    }

    var BOX = "Box427";
    var destino = boxPositions[BOX];
    if (!destino) {
      alert("MoverCajas_test: no hay box_positions['" + BOX + "'] en data_pagina.json.\n" +
            "Calibrá 'textual_dst_1' y volvé a hacer 'Pegar en Quark'.");
      return;
    }

    function getBox(name) {
      var all = layout.getElementsByTagName("qx-box");
      for (var i = 0; i < all.length; i++) {
        if (all[i].getAttribute("box-name") === name) return all[i];
      }
      return null;
    }

    var box = getBox(BOX);
    if (!box) {
      alert("MoverCajas_test: no se encontró " + BOX + " en la maqueta activa.");
      return;
    }

    function rectStr(b) {
      try {
        var r = b.getBoundingClientRect();
        return "x=" + Math.round(r.left) + " y=" + Math.round(r.top) +
               " w=" + Math.round(r.width) + " h=" + Math.round(r.height);
      } catch (e) { return "(sin getBoundingClientRect: " + e + ")"; }
    }

    var antes = rectStr(box);
    var tx = destino.x, ty = destino.y;
    var intentos = [];

    // Estrategia 1: atributos box-x / box-y
    try { box.setAttribute("box-x", tx); box.setAttribute("box-y", ty); intentos.push("box-x/box-y"); } catch (e) {}
    // Estrategia 2: atributos x / y
    try { box.setAttribute("x", tx); box.setAttribute("y", ty); intentos.push("x/y"); } catch (e) {}
    // Estrategia 3: atributos left / top
    try { box.setAttribute("left", tx); box.setAttribute("top", ty); intentos.push("left/top"); } catch (e) {}
    // Estrategia 4: propiedades directas
    try { box.x = tx; box.y = ty; intentos.push("box.x/box.y"); } catch (e) {}
    // Estrategia 5: style inline
    try { box.style.left = tx + "px"; box.style.top = ty + "px"; intentos.push("style.left/top"); } catch (e) {}
    // Estrategia 6: API de geometría (si existiera)
    try { if (typeof box.setBounds === "function") { box.setBounds(tx, ty); intentos.push("setBounds()"); } } catch (e) {}
    try { if (typeof box.move === "function") { box.move(tx, ty); intentos.push("move()"); } } catch (e) {}

    var despues = rectStr(box);
    alert("MoverCajas_test (" + BOX + ")\n" +
          "destino (pantalla): x=" + tx + " y=" + ty + "\n\n" +
          "ANTES:   " + antes + "\n" +
          "DESPUÉS: " + despues + "\n\n" +
          "Estrategias aplicadas sin excepción:\n" + (intentos.join(", ") || "(ninguna)") + "\n\n" +
          (antes === despues ? "→ La caja NO se movió (ninguna API funcionó)."
                             : "→ La caja SE MOVIÓ: alguna API sirve. Ver cuál cambió la geometría."));
  } catch (err) {
    alert("MoverCajas_test error:\n" + err);
  }
})();
