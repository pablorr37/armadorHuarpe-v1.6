// =============================================================
// AutoLoader_pegarNota.js
// Ejecuta el script pegarNota.js automáticamente al abrir un QXP
// con delay de 500ms para que el layout cargue completamente.
// QuarkXPress 2018 v14.x
// =============================================================

(function () {

    // Prevenir doble registro (QX suele recargar scripts)
    if (app.__huarpe_pegarNota_autoload_registered)
        return;
    app.__huarpe_pegarNota_autoload_registered = true;

    // Ruta absoluta al script principal
    var RUTA_SCRIPT_PEGARNOTA = "C:/Pablo/ArmadorHuarpe v0.1/_devdata/scripts/pegarNota.js";

    // Evento: después de abrir un layout
    app.addEventListener("afterOpen", function (evt) {

        try {
            // Esperar 500 ms antes de ejecutar el script de pegado
            setTimeout(function () {

                try {
                    app.doScript(RUTA_SCRIPT_PEGARNOTA);
                } catch (err2) {
                    alert("Error ejecutando pegarNota.js:\n" + err2);
                }

            }, 500); // 500 ms

        } catch (err) {
            alert("Error en AutoLoader_pegarNota.js:\n" + err);
        }

    });

})();
