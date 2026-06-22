// =============================================================
//  LeerMaqueta.js
//  QuarkXPress 2018 v14.x (QX.js)
// -------------------------------------------------------------
//  Lee todas las cajas de texto y foto del documento activo.
//  Por cada caja de texto anota el nombre y la cantidad de
//  caracteres del contenido actual (placeholder editorial).
//  Escribe maqueta_info.json en la carpeta de scripts de la app.
//
//  Instrucciones:
//    1. Abrir la maqueta (.qxp) en QuarkXPress.
//    2. Ejecutar este script.
//    3. En la app Python, hacer clic en "↺ Actualizar desde Quark".
// =============================================================
(function () {
  try {
    var layout = app.activeLayoutDOM();
    var appData = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/";

    // Nombre del documento activo
    var docName = "";
    try { docName = app.activeDocument.name || ""; } catch (e) {}

    var textBoxes = [];
    var pictureBoxes = [];
    var all = layout.getElementsByTagName("qx-box");

    for (var i = 0; i < all.length; i++) {
      var b = all[i];
      var name = b.getAttribute("box-name");
      if (!name) continue;
      var ctype = b.getAttribute("box-content-type");

      if (ctype === "text") {
        var story = b.getElementsByTagName("qx-story")[0];
        var chars = story ? (story.textContent || "").trim().length : 0;

        // Intentar leer geometría (puede no estar disponible en todas las versiones)
        var w = 0, h = 0;
        try {
          var rect = b.getBoundingClientRect();
          w = Math.round(rect.width);
          h = Math.round(rect.height);
        } catch (e) {}

        // Registrar TODOS los boxes con nombre (chars=0 si no tiene placeholder)
        textBoxes.push({ name: name, chars: chars, width: w, height: h });

      } else if (ctype === "picture") {
        pictureBoxes.push(name);
      }
    }

    // Índice plano nombre→chars para lookup rápido desde Python
    var boxChars = {};
    var conContenido = 0;
    for (var j = 0; j < textBoxes.length; j++) {
      boxChars[textBoxes[j].name] = textBoxes[j].chars;
      if (textBoxes[j].chars > 0) conContenido++;
    }

    var output = JSON.stringify({
      source: docName,
      timestamp: new Date().toISOString(),
      text_boxes: textBoxes,
      box_chars: boxChars,
      picture_boxes: pictureBoxes,
      picture_count: pictureBoxes.length
    }, null, 2);

    fs.writeFileSync(appData + "maqueta_info.json", output, "utf8");
    alert(
      "LeerMaqueta: " + textBoxes.length + " cajas de texto (" + conContenido + " con placeholder), " +
      pictureBoxes.length + " cajas de foto.\n" +
      "JSON guardado en:\n" + appData + "maqueta_info.json"
    );

  } catch (err) {
    alert("Error en LeerMaqueta.js:\n" + err);
  }
})();
