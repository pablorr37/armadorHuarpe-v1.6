// =============================================================
//  ExportarPDF.js  ·  QuarkXPress 2018 v14.2 (QX.js)
// -------------------------------------------------------------
//  Bot de exportación automática qxp→PDF (independiente del armador).
//  Exporta el layout activo a PDF con el estilo de salida "Huarpe",
//  100% headless (sin diálogos, vía kOutputUI_SuppressAll).
//
//  Contrato (igual patrón que PegarNota v6.js, con sus PROPIOS
//  archivos — no toca runtime_config.json/armado_status.json del
//  armador, para no interferir con ese bot):
//    Input  (Python→JS): %APPDATA%/ArmadorHuarpe/scripts/export_pdf_config.json
//                         { "folio": N, "output_path": "<ruta .pdf>", "style": "Huarpe" }
//    Output (JS→Python): %APPDATA%/ArmadorHuarpe/scripts/export_pdf_status.json
//                         { "exportado": true,  "folio": N }
//                         { "exportado": false, "folio": N, "error": "<detalle>" }
//
//  El cierre del documento lo hace Python (QuarkAutomator.cerrar) igual que en
//  el modo pyautogui: este script SOLO exporta y deja el flag de resultado.
// =============================================================
(function () {
  var _appdataScripts = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/";

  function _escribirStatus(status) {
    try {
      fs.writeFileSync(_appdataScripts + "export_pdf_status.json",
        JSON.stringify(status), "utf8");
    } catch (eW) {
      alert("ExportarPDF: no se pudo escribir export_pdf_status.json:\n" + eW);
    }
  }

  var folio = null;
  try {
    var cfg = JSON.parse(
      fs.readFileSync(_appdataScripts + "export_pdf_config.json", "utf8").trim()
    );
    folio = cfg.folio;
    var outputPath = cfg.output_path;
    var style = cfg.style || "Huarpe";

    if (!outputPath) {
      _escribirStatus({ exportado: false, folio: folio, error: "export_pdf_config.json sin output_path" });
      return;
    }

    var layout = app.activeLayout();
    if (layout instanceof app.APIError) {
      _escribirStatus({ exportado: false, folio: folio, error: "activeLayout(): " + layout });
      return;
    }

    var resultado = layout.exportLayoutAsPDF(
      outputPath,
      app.constants.outputSuppressUIFlags.kOutputUI_SuppressAll,
      style
    );

    if (resultado instanceof app.APIError) {
      _escribirStatus({ exportado: false, folio: folio, error: "exportLayoutAsPDF: " + resultado });
      return;
    }

    _escribirStatus({ exportado: true, folio: folio });
  } catch (err) {
    _escribirStatus({ exportado: false, folio: folio, error: String(err) });
  }
})();
