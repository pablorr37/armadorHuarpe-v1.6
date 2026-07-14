// =============================================================
//  InspeccionarTodo.js  ·  QuarkXPress 2018 (QX.js)
// -------------------------------------------------------------
//  Vuelca TODAS las cajas (qx-box) del layout con su geometría,
//  SIN necesidad de seleccionar nada. El DOM de Quark es plano y
//  no expone los grupos; con las coordenadas de todas las cajas
//  se puede reconstruir la membresía de cada grupo por proximidad.
//
//  USO: con la maqueta abierta, corré este script. Escribe el
//  reporte y muestra la ruta en un alert.
//
//  Abrí y pegá en el chat:
//    C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_todo.txt
// =============================================================
(function () {
  try {
    var layout = app.activeLayoutDOM();
    if (!layout) { alert("InspeccionarTodo: no hay layout activo."); return; }

    var all = layout.getElementsByTagName("qx-box");

    function borde(el, lado) {
      var s = "";
      try { s = el.getAttribute("style") || ""; } catch (e) {}
      var m = s.match(new RegExp("--qx-" + lado + ":(-?[0-9.]+)mm"));
      return m ? m[1] : "?";
    }
    function pagina(el) {
      var s = "";
      try { s = el.getAttribute("style") || ""; } catch (e) {}
      var m = s.match(/--qx-page:([^;]+);/);
      return m ? m[1] : "?";
    }

    var lineas = [];
    lineas.push("=== InspeccionarTodo — " + new Date() + " ===");
    lineas.push("Total qx-box: " + all.length);
    lineas.push("Formato: box-name | tipo | page | left top right bottom (mm)");
    lineas.push("");

    for (var i = 0; i < all.length; i++) {
      var b = all[i];
      var nm = "(sin nombre)", ct = "";
      try { nm = b.getAttribute("box-name") || "(sin nombre)"; } catch (e) {}
      try { ct = b.getAttribute("box-content-type") || ""; } catch (e) {}
      lineas.push(
        nm + " | " + ct + " | pg=" + pagina(b) + " | " +
        borde(b, "left") + " " + borde(b, "top") + " " +
        borde(b, "right") + " " + borde(b, "bottom")
      );
    }

    var texto = lineas.join("\n");
    var ruta = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/inspeccion_todo.txt";
    var escrito = false;
    try { fs.writeFileSync(ruta, texto, "utf8"); escrito = true; } catch (eW) { escrito = false; }

    if (escrito) {
      alert("InspeccionarTodo: " + all.length + " cajas volcadas.\n\n" +
            "Abrí y pegá este archivo:\n" + ruta);
    } else {
      alert("No se pudo escribir el archivo. Copiá el texto:\n\n" + texto.substring(0, 3000));
    }

  } catch (err) {
    alert("InspeccionarTodo: error:\n" + err);
  }
})();
