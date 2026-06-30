// =============================================================
//  PegarAviso_JSON.js  —  destilado de PegarNota_JSON.js
//  QuarkXPress 2018 v14.2 (QX.js)
// -------------------------------------------------------------
//  • SOLO pega los avisos (pie / media / robapágina / completa).
//  • NO toca texto, textuales, fotos ni QR.
//  • Lee el mismo data_pagina.json que escribe "Pegar en Quark".
// =============================================================
(function () {
  try {
    var layout = app.activeLayoutDOM();

    // =========================================================
    // 🔹 Índice rápido de picture boxes por box-name
    // =========================================================
    var _picBoxIndex = (function buildPicIndex() {
      var idx = {};
      var all = layout.getElementsByTagName("qx-box");
      for (var i = 0; i < all.length; i++) {
        var b = all[i];
        var name = b.getAttribute("box-name");
        if (name) idx[name] = b;
      }
      return idx;
    })();

    // =========================================================
    // 🔹 Leer datos de página desde data_pagina.json
    // =========================================================
    var seccion = "SIN SECCIÓN";
    var avisos = [];

    var _appdataDir = "C:/Users/usuario/AppData/Roaming";
    var _appdataScripts = _appdataDir + "/ArmadorHuarpe/scripts/";
    var rutaJSON = "";
    try {
      var _cfgRaw = fs.readFileSync(_appdataScripts + "runtime_config.json", "utf8").trim();
      var _cfg = JSON.parse(_cfgRaw);
      rutaJSON = (_cfg.data_pagina_path || "").replace(/\\/g, "/");
    } catch (e) {
      alert("PegarAviso: error leyendo runtime_config.json:\n" + e);
      return;
    }
    if (!rutaJSON) {
      alert("PegarAviso: runtime_config.json no contiene data_pagina_path.\nUsá 'Pegar en Quark' desde la app antes de ejecutar este script.");
      return;
    }

    try {
      if (fs.existsSync(rutaJSON)) {
        var contenido = fs.readFileSync(rutaJSON, "utf8").trim();
        var data = JSON.parse(contenido);
        seccion = (data.seccion || "").trim();
        avisos = data.avisos || [];
      }
    } catch (e2) {
      alert("Error leyendo data_pagina.json: " + e2);
    }

    // =========================================================
    // 🔹 Helpers
    // =========================================================
    function normalizar(str) {
      return (str || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .trim();
    }

    function normalizeWinPath(p) {
      return (p || "").trim().replace(/\\/g, "/");
    }

    // Path CRUDO (literal, con espacios reales): Quark resuelve el file:// sin
    // percent-encoding; escapar a %20 rompe las rutas con espacios.
    function toFileUrl(p) {
      p = normalizeWinPath(p);
      if (/^[A-Za-z]:\//.test(p)) return "file:///" + p;
      if (/^\/\/[^\/]+\/[^\/]+/.test(p)) return "file:////" + p.replace(/^\/\//, "");
      if (/^file:\/\//i.test(p)) return p;
      return "file://" + p;
    }

    var _hits = 0;
    var _faltantes = [];

    function getPicBoxByName(name) {
      return _picBoxIndex[name]
        || layout.querySelector("qx-box[box-name='" + name + "']")
        || null;
    }

    function setImagenEnBox(boxName, filePath) {
      if (!filePath) return { ok:false, why:"path vacío", box:boxName };
      var box = getPicBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return { ok:false, why:"no existe box", box:boxName }; }
      var url = toFileUrl(filePath);
      var imgs = box.getElementsByTagName("qx-img");
      if (imgs && imgs.length) {
        try {
          imgs[0].setAttribute("src", url);
          _hits++;
          return { ok:true, why:"", box:boxName, url:url };
        } catch (e) {
          return { ok:false, why:"error en qx-img.src: " + e, box:boxName };
        }
      }
      try {
        box.setAttribute("src", url);
        _hits++;
        return { ok:true, why:"", box:boxName, url:url };
      } catch (e2) {
        return { ok:false, why:"error en box.src: " + e2, box:boxName };
      }
    }

    // =========================================================
    // 🔹 Targets de aviso por sección + box universales
    // =========================================================
    var AVISO_TARGETS = {
      default: {
        pie: ["Box1889", "Box1890", "Box1896"],
        media: ["Box1894", "Box1897", "Box1899"],
        robapagina: ["Box1897", "Box1903", "Box1904"],
        completa: ["Box1911"]
      },
      "cultura": {
        pie: ["Box1561", "Box1568"],
        media: ["Box1566", "Box1570"],
        robapagina: ["Box1566", "Box1573"]
      },
      "deportes": {
        pie: ["Box1645", "Box1647", "Box1649"],
        media: ["Box1645", "Box1647", "Box1649"],
        robapagina: ["Box1652", "Box1650"]
      },
      "economia": {
        pie: ["Box1965", "Box1966", "Box1967"],
        media: ["Box1965", "Box1966", "Box1967"],
        robapagina: ["Box1966", "Box1967"]
      },
      "cafe de la politica": {
        pie: ["Box2091"],
        media: ["Box2091"],
        robapagina: ["Box2091", "Box2131"]
      },
      "eco huarpe": {
        pie: ["Box6776"],
        media: ["Box6776"],
        robapagina: ["Box6776"]
      },
      "yo te invito": {
        pie: ["Box2561"],
        media: ["Box2566"],
        robapagina: ["Box2568"]
      },
      "yo cocino": {
        pie: ["Box3561"],
        media: ["Box3566"],
        robapagina: ["Box3568"]
      },
      "yo emprendo": {
        pie: ["Box4561"],
        media: ["Box4566"],
        robapagina: ["Box4568"]
      }
    };

    // Box de aviso universales: pie/media/robapágina van SIEMPRE a estos box en toda maqueta.
    // "completa" mantiene su box propio (AVISO_TARGETS[...].completa).
    var UNIVERSAL_AVISO = ["Box1988", "Box1995", "Box1999"];

    function pegarAvisosEnSeccion(seccionNorm) {
      if (!avisos || avisos.length === 0) {
        alert("PegarAviso: no hay avisos en data.fotos/avisos para esta página.");
        return;
      }

      var conf = AVISO_TARGETS[seccionNorm] || AVISO_TARGETS.default;
      if (!conf) return;

      var okCount = 0;
      var fails = [];

      for (var i = 0; i < avisos.length; i++) {
        var a = avisos[i] || {};
        var tipo = normalizar(a.tipo || "");
        var path = (a.path || "").trim();
        var targets = (tipo === "completa") ? (conf.completa || []) : UNIVERSAL_AVISO;

        for (var j = 0; j < targets.length; j++) {
          var res = setImagenEnBox(targets[j], path);
          if (res.ok) okCount++;
          else fails.push(res);
        }
      }

      if (fails.length > 0) {
        var msg = "AVISOS: OK=" + okCount + " FAIL=" + fails.length + "\n\n";
        for (var k = 0; k < Math.min(6, fails.length); k++) {
          msg += "- " + fails[k].box + ": " + fails[k].why + (fails[k].url ? ("\n  " + fails[k].url) : "") + "\n";
        }
        alert(msg);
      }
    }

    // =========================================================
    // 🔹 Dispatch
    // =========================================================
    var seccionNorm = normalizar(seccion);
    pegarAvisosEnSeccion(seccionNorm);

    if (_hits === 0 && _faltantes.length > 0) {
      var _uniq = _faltantes.filter(function (v, i) { return _faltantes.indexOf(v) === i; });
      alert("PegarAviso: no se pegó ningún aviso.\n\nBox buscados sin éxito:\n" + _uniq.join(", "));
    }

  } catch (err) {
    alert("Error al pegar aviso:\n" + err);
  }
})();
