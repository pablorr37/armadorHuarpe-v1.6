// =============================================================
//  CerrarProyecto.js  —  cierra el proyecto activo (sin guardar)
//  QuarkXPress 2018 v14.x (QX.js) — para el lector batch de maquetas
// -------------------------------------------------------------
//  Expresión que devuelve {ok, error}. La lectura de maqueta NO modifica el
//  documento, así que se cierra sin guardar (mismo patrón que ExportarPDF.js).
// =============================================================
(function () {
  var out = { ok: true, error: null };
  try {
    var proj = app.activeProject();
    if (proj && proj.projectID >= 0) {
      proj.closeProject();
    }
  } catch (err) {
    out.ok = false;
    out.error = String(err);
  }
  return out;
})();
