// =============================================================
// startup.js — DIAGNÓSTICO del mecanismo afterOpen (QuarkXPress 2018)
// -------------------------------------------------------------
// Primero verificamos qué APIs están disponibles y si el evento 'afterOpen'
// realmente se dispara al abrir un proyecto. Todo envuelto en try/catch con
// alert, para que la cruz roja no oculte el error real.
// =============================================================
(function () {
  try {
    var diag = "APIs disponibles:\n" +
               " app.addEventListener = " + (typeof (app && app.addEventListener)) + "\n" +
               " setTimeout           = " + (typeof setTimeout) + "\n" +
               " fs                   = " + (typeof fs) + "\n" +
               " app.doScript         = " + (typeof (app && app.doScript)) + "\n" +
               " app.activeProject    = " + (typeof (app && app.activeProject));

    if (typeof app.addEventListener !== "function") {
      alert("startup.js: app.addEventListener NO existe.\n\n" + diag);
      return;
    }

    // Registrar el listener (guard anti-doble-registro).
    if (!app.__huarpe_autoload_registered) {
      app.__huarpe_autoload_registered = true;
      app.addEventListener("afterOpen", function (evt) {
        try {
          // Aviso inmediato: confirma que el evento SÍ se dispara al abrir.
          alert("afterOpen DISPARADO ✔  (a los 5 s se auto-ejecutaría PegarNota)");
        } catch (e) {}
      });
      alert("startup.js: listener 'afterOpen' REGISTRADO OK.\n\n" + diag +
            "\n\nAhora ABRÍ un proyecto .qxp NUEVO y fijate si aparece el aviso 'afterOpen DISPARADO'.");
    } else {
      alert("startup.js: ya estaba registrado.\n\n" + diag);
    }

  } catch (err) {
    alert("startup.js ERROR: " + err);
  }
})();
