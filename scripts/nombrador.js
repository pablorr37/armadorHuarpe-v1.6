// =============================================================
//  nombrador.js — QuarkXPress 2018 v14.x (QX.js)
// -------------------------------------------------------------
//  USO MANUAL: ejecutar DIRECTAMENTE desde el palette de scripts de Quark
//  (Item Tool → seleccionar una o más cajas → correr este script). NO está
//  pensado para dispararse por la automatización CDP de ArmadorHuarpe.
//
//  HALLAZGO (jul 2026, confirmado en vivo): Quark solo "registra" el
//  box-name de una caja en el instante en que el nodo se INSERTA en el árbol
//  del documento. Hacer setAttribute('box-name', ...) sobre una caja YA
//  insertada NO se propaga al modelo interno de Quark — el diálogo pedía el
//  nombre, se aceptaba, pero la caja seguía mostrando el nombre viejo. Por
//  eso este script YA NO renombra in-place: clona la caja seleccionada con
//  el nombre nuevo (fijado ANTES de insertar, que es el único momento en que
//  Quark lo toma), la ubica en la MISMA posición/página, y borra la
//  original. Ver también scripts/AplicarModeloRecursos.js (mismo patrón,
//  para renombrado disparado desde Python).
//
//  Si hay varias cajas seleccionadas, pide un nombre POR CAJA (el original
//  aplicaba el mismo nombre a toda la selección, lo cual solo tenía sentido
//  con una caja sola).
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

  // Clona `origen` con `nombreNuevo` fijado ANTES de insertar, preservando su
  // propia geometría/página (heredada por cloneNode), y borra el original.
  function renombrarClonando(origen, nombreNuevo) {
    var nueva = origen.cloneNode(true);
    try { nueva.removeAttribute("box-id"); } catch (e0) {}
    try { nueva.removeAttribute("box-uid"); } catch (e1) {}
    nueva.setAttribute("box-name", nombreNuevo);
    // La geometría/página ya vienen copiadas en el style heredado del clon —
    // no hace falta reescribirlas (a diferencia de AplicarModeloRecursos.js,
    // acá no hay reposicionamiento, es un renombre puro en el mismo lugar).
    if (origen.parentNode) origen.parentNode.appendChild(nueva);
    if (origen.parentNode) origen.parentNode.removeChild(origen);
    return nueva;
  }

  var boxes = app.activeBoxesDOM();
  if (!boxes || boxes.length === 0) {
    app.dialogs.alert("Seleccioná al menos una caja.");
    return;
  }

  app.undo.beginCompoundUndo("Renombrar caja(s)");
  try {
    var renombradas = 0;
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      var nombreActual = box.getAttribute("box-name") || "";
      var nombre = app.dialogs.prompt(
        "Nombre para la caja " + (i + 1) + " de " + boxes.length + ":", nombreActual
      );
      if (nombre === null) continue;   // canceló esta caja, sigue con la próxima
      nombre = nombre.trim();
      if (!nombre || nombre === nombreActual) continue;
      renombrarClonando(box, nombre);
      renombradas++;
    }
    if (renombradas > 0) {
      app.dialogs.alert("Renombradas " + renombradas + " caja(s).");
    }
  } finally {
    app.undo.endCompoundUndo();
  }
})();
