// =============================================================
//  PegarFoto_JSON.js  —  destilado de PegarNota_JSON.js
//  QuarkXPress 2018 v14.2 (QX.js)
// -------------------------------------------------------------
//  • SOLO pega las imágenes de página (foto principal / pie / Escrache al Bache).
//  • NO toca texto, textuales, avisos ni QR.
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
    var fotos = [];

    var _appdataDir = "C:/Users/usuario/AppData/Roaming";
    var _appdataScripts = _appdataDir + "/ArmadorHuarpe/scripts/";
    var rutaJSON = "";
    try {
      var _cfgRaw = fs.readFileSync(_appdataScripts + "runtime_config.json", "utf8").trim();
      var _cfg = JSON.parse(_cfgRaw);
      rutaJSON = (_cfg.data_pagina_path || "").replace(/\\/g, "/");
    } catch (e) {
      alert("PegarFoto: error leyendo runtime_config.json:\n" + e);
      return;
    }
    if (!rutaJSON) {
      alert("PegarFoto: runtime_config.json no contiene data_pagina_path.\nUsá 'Pegar en Quark' desde la app antes de ejecutar este script.");
      return;
    }

    try {
      if (fs.existsSync(rutaJSON)) {
        var contenido = fs.readFileSync(rutaJSON, "utf8").trim();
        var data = JSON.parse(contenido);
        seccion = (data.seccion || "").trim();
        avisos = data.avisos || [];
        fotos = data.fotos || [];
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
    var _fotoBoxesOk = 0;
    var _fotoPathTried = "";

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

    // --- Helpers de texto (solo para los epígrafes de Escrache al Bache) ---
    function qxBoxByName(name) {
      return layout.querySelector("qx-box[box-name='" + name + "'][box-content-type='text']");
    }

    function ensureStory(box) {
      if (!box) return null;
      var story = box.getElementsByTagName("qx-story")[0];
      if (!story) {
        story = document.createElement("qx-story");
        box.appendChild(story);
      }
      return story;
    }

    function cleanHTML(str) {
      if (!str) return "";
      return str
        .replace(/<\/?[^>]+>/g, "")
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&quot;/gi, "\"")
        .replace(/&#39;/gi, "'")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/\s+\n/g, "\n")
        .replace(/\n\s+/g, "\n")
        .trim();
    }

    function setTextoEnBox(boxName, texto) {
      var box = qxBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
      var story = ensureStory(box);
      var p0 = story.getElementsByTagName("qx-p")[0];
      if (!p0) return;
      var clone = p0.cloneNode(true);
      var span = clone.getElementsByTagName("qx-span")[0];
      if (!span) { span = document.createElement("qx-span"); clone.appendChild(span); }
      span.textContent = texto;
      while (story.firstChild) story.removeChild(story.firstChild);
      story.appendChild(clone);
    }

    // =========================================================
    // 🔹 Constantes y rutinas de imagen
    // =========================================================
    var FOTO_BOXES     = ["Box369", "Box505", "Box1867"];
    var PIE_FOTO_BOXES = FOTO_BOXES;

    function pegarFotoPrincipal() {
      var foto = null;
      for (var i = 0; i < fotos.length; i++) {
        if (fotos[i].rol === "principal") { foto = fotos[i]; break; }
      }
      if (!foto) return;
      var path = (foto.path || "").trim();
      if (!path) return;
      _fotoPathTried = path;
      for (var b = 0; b < FOTO_BOXES.length; b++) {
        var r = setImagenEnBox(FOTO_BOXES[b], path);
        if (r && r.ok) _fotoBoxesOk++;
      }
    }

    // Sección "Escrache al Bache": 2 imágenes distintas + sus epígrafes.
    function pegarEscracheAlBache() {
      var sorted = fotos.slice().sort(function (a, b) {
        return (a.orden || 0) - (b.orden || 0);
      });
      if (sorted.length === 0) {
        alert("Escrache al Bache: no llegaron fotos en data.fotos.\n\n" +
              "Seleccioná las 2 fotos (principal y secundaria) en el editor y\n" +
              "pegá eligiendo 'Sí, pegar todo'.");
        return;
      }
      var IMG_BOXES = ["Box6357", "Box6429"];
      var EPI_BOXES = ["Box6599", "Box6604"];
      for (var i = 0; i < sorted.length && i < IMG_BOXES.length; i++) {
        var f = sorted[i] || {};
        var path = (f.path || "").trim();
        if (path) setImagenEnBox(IMG_BOXES[i], path);
        var epi = cleanHTML(f.epigrafe || "");
        if (epi) setTextoEnBox(EPI_BOXES[i], epi);
      }
    }

    function tienePie() {
      for (var i = 0; i < avisos.length; i++) {
        if (normalizar(avisos[i].tipo || "") === "pie") return true;
      }
      return false;
    }

    function pegarFotosConPie() {
      var sorted = fotos.slice().sort(function (a, b) { return a.orden - b.orden; });
      for (var i = 0; i < sorted.length && i < PIE_FOTO_BOXES.length; i++) {
        var path = (sorted[i].path || "").trim();
        if (path) setImagenEnBox(PIE_FOTO_BOXES[i], path);
      }
    }

    // =========================================================
    // 🔹 Dispatch (mismo criterio que el script madre)
    // =========================================================
    var seccionNorm = normalizar(seccion);
    if (seccionNorm === "escrache al bache") {
      pegarEscracheAlBache();
    } else if (tienePie()) {
      pegarFotosConPie();
    } else {
      pegarFotoPrincipal();
    }

    if (_hits === 0) {
      var _uniq = _faltantes.filter(function (v, i) { return _faltantes.indexOf(v) === i; });
      alert("PegarFoto: no se pegó ninguna imagen.\n\nBox buscados sin éxito:\n" + _uniq.join(", "));
    }

    // Diagnóstico: hubo foto pero no entró en ninguna caja de foto principal.
    if (fotos && fotos.length > 0 && _fotoBoxesOk === 0 && _fotoPathTried) {
      var _fb = FOTO_BOXES.filter(function (v, i) { return FOTO_BOXES.indexOf(v) === i; });
      alert("PegarFoto: la foto principal no entró en ninguna caja.\n\n" +
            "Foto: " + _fotoPathTried + "\n" +
            "Cajas de foto probadas (no existen en esta maqueta): " + _fb.join(", "));
    }

  } catch (err) {
    alert("Error al pegar foto:\n" + err);
  }
})();
