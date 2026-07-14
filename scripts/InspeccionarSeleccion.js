// =============================================================
//  InspeccionarSeleccion.js  ·  QuarkXPress 2018 (QX.js)
// -------------------------------------------------------------
//  Enumera TODAS las cajas de la selección actual (un grupo).
//  El DOM de Quark es PLANO y no expone los grupos (Ctrl+G),
//  así que la única forma de conocer la membresía completa de un
//  grupo (incluidas cajas de decoración) es seleccionarlo y leer
//  app.activeBoxesDOM().
//
//  USO (repetir por cada recurso):
//    1) Con la herramienta Item (flecha), hacé UN clic sobre el
//       recurso para seleccionar el GRUPO COMPLETO.
//    2) Corré este script.
//    3) Escribí la etiqueta del recurso cuando la pida, exactamente:
//         textual_simple | textual_x2 | textual_x3 |
//         textual_con_foto | textual_con_foto_xl |
//         dato | numero | qr
//    4) Repetí con el siguiente recurso. Todo se acumula en un archivo.
//
//  Al terminar, abrí y pegá en el chat:
//    C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_seleccion.txt
// =============================================================
(function () {
  try {
    var boxes = app.activeBoxesDOM();
    if (!boxes || boxes.length === 0) {
      app.dialogs.alert("Seleccioná primero el GRUPO del recurso con la herramienta Item (un clic).");
      return;
    }

    var etiqueta = app.dialogs.prompt(
      "Etiqueta del recurso seleccionado (" + boxes.length + " caja/s):\n" +
      "textual_simple | textual_x2 | textual_x3 | textual_con_foto | " +
      "textual_con_foto_xl | dato | numero | qr", "");
    if (etiqueta === null) return;           // cancelado
    etiqueta = ("" + etiqueta).trim() || "(sin etiqueta)";

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

    var lineas = [];
    lineas.push("### RECURSO: " + etiqueta + "   (cajas: " + boxes.length + ")");
    for (var i = 0; i < boxes.length; i++) {
      var nm = "(sin nombre)";
      var ct = "";
      try { nm = boxes[i].getAttribute("box-name") || "(sin nombre)"; } catch (e) {}
      try { ct = boxes[i].getAttribute("box-content-type") || ""; } catch (e) {}
      lineas.push("  · " + nm + " [" + ct + "]  " + bordes(boxes[i]));
    }
    lineas.push("");
    var bloque = lineas.join("\n");

    // Acumular en un único archivo (append manual: leer + concatenar + escribir).
    var ruta = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_seleccion.txt";
    var previo = "";
    try { if (fs.existsSync(ruta)) previo = fs.readFileSync(ruta, "utf8"); } catch (e) {}
    if (!previo) {
      previo = "=== InspeccionarSeleccion — " + new Date() + " ===\n\n";
    }
    try {
      fs.writeFileSync(ruta, previo + bloque, "utf8");
      app.dialogs.alert("Guardado '" + etiqueta + "' (" + boxes.length + " cajas).\n\n" +
                        "Seguí con el próximo recurso, o abrí y pegá:\n" + ruta);
    } catch (eW) {
      app.dialogs.alert("No se pudo escribir el archivo. Copiá esto:\n\n" + bloque);
    }

  } catch (err) {
    app.dialogs.alert("InspeccionarSeleccion: error:\n" + err);
  }
})();
