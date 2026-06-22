// =============================================================
//  PegarNota_Auto_Huarpe_FromTXT_MultiMaqueta_Router.js
//  QuarkXPress 2018 v14.2 (QX.js)
// -------------------------------------------------------------
//  • Inserta volanta, título, bajada, epígrafe y cuerpo según sección.
//  • Rutina general por defecto (actual).
//  • Rutinas específicas: Cultura y Deportes (otras se agregarán).
//  • Lee archivos reales generados por Armador Huarpe:
//      - data_pagina.json → sección y usuario
//      - nota.txt → texto de la nota
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
        if (b.getAttribute("box-content-type") !== "picture") continue;
        var name = b.getAttribute("box-name");
        if (name) idx[name] = b;
      }
      return idx;
    })();


    // =========================================================
    // 🔹 Leer datos de página y sección desde data_pagina.json
    // =========================================================
    var seccion = "SIN SECCIÓN";
    var username = "usuario";
    var numeroPagina = 0;
    var avisos = [];
    var tiene_texto = false;

    //DESARROLLO var rutaBase = "C:/Pablo/ArmadorHuarpe v0.1/_devdata/scripts/";
    var rutaBase = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/";
    var rutaJSON = rutaBase + "data_pagina.json";
    var rutaTXT  = rutaBase + "nota.txt";

    try {
      if (fs.existsSync(rutaJSON)) {
        var contenido = fs.readFileSync(rutaJSON, "utf8").trim();
        var data = JSON.parse(contenido);
        numeroPagina = parseInt(data.numero_pagina || 0);
        seccion = (data.seccion || "").trim();
        username = (data.usuario || "usuario").trim();
        avisos = data.avisos || [];
        tiene_texto = !!data.tiene_texto;
      }
    } catch (e) {
      alert("Error leyendo data_pagina.json: " + e);
    }

    // =========================================================
    // 🔹 Helpers generales
    // =========================================================
    function normalizar(str) {
      return (str || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .trim();
    }

    // =========================================================
    // 🔹 Helpers para manipular cajas de imágenes
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

function pegarAvisosEnSeccion(seccionNorm) {
  if (!avisos || avisos.length === 0) return;

  var conf = AVISO_TARGETS[seccionNorm] || AVISO_TARGETS.default;
  if (!conf) return;

  var okCount = 0;
  var fails = [];

  for (var i = 0; i < avisos.length; i++) {
    var a = avisos[i] || {};
    var tipo = normalizar(a.tipo || "");
    var path = (a.path || "").trim();
    var targets = conf[tipo] || [];

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

    
    


function normalizeWinPath(p) {
  return (p || "").trim().replace(/\\/g, "/");
}

function toFileUrl(p) {
  p = normalizeWinPath(p);

  // Drive-letter: Z:/... -> file:///Z:/...
  if (/^[A-Za-z]:\//.test(p)) {
    return "file:///" + p;
  }

  // UNC: //server/share/a.eps -> file:////server/share/a.eps
  if (/^\/\/[^\/]+\/[^\/]+/.test(p)) {
    return "file:////" + p.replace(/^\/\//, "");
  }

  // Si ya viene file://...
  if (/^file:\/\//i.test(p)) return p;

  return "file://" + p;
}


function getPicBoxByName(name) {
  return _picBoxIndex[name] || null;
}

function setImagenEnBox(boxName, filePath) {
  if (!filePath) return { ok:false, why:"path vacío", box:boxName };

  var box = getPicBoxByName(boxName);
  if (!box) return { ok:false, why:"no existe box picture", box:boxName };

  var url = toFileUrl(filePath);

  // Buscar qx-img
  var imgs = box.getElementsByTagName("qx-img");
  var img = (imgs && imgs.length) ? imgs[0] : null;

  // Si no existe, crear con el DOM del layout (no con document.createElement)
  if (!img) {
    try {
      img = layout.createElement("qx-img");
      box.appendChild(img);
    } catch (e) {
      return { ok:false, why:"no pudo crear qx-img: " + e, box:boxName };
    }
  }

  try {
    img.setAttribute("src", url);
    return { ok:true, why:"", box:boxName, url:url };
  } catch (e2) {
    return { ok:false, why:"error seteando src: " + e2, box:boxName, url:url };
  }
}




    // =========================================================
    // 🔹 Helpers para manipular cajas y textos
    // =========================================================
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
      if (!box) return;
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

    function setFecha(boxName) {
      var box = qxBoxByName(boxName);
      if (!box) return;
      var story = ensureStory(box);
      var p = story.getElementsByTagName("qx-p")[0];
      if (!p) return;
      var span = p.getElementsByTagName("qx-span")[0];
      if (!span) { span = document.createElement("qx-span"); p.appendChild(span); }
      var meses = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO","JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"];
      var dias = ["DOMINGO","LUNES","MARTES","MIÉRCOLES","JUEVES","VIERNES","SÁBADO"];
      var hoy = new Date(); hoy.setDate(hoy.getDate() + 1);
      var fechaTexto = dias[hoy.getDay()] + " " + hoy.getDate() + " DE " + meses[hoy.getMonth()] + " DE " + hoy.getFullYear();
      span.textContent = fechaTexto;
    }

    function setSoloBajadaEnBox(boxName, texto) {
      if (!texto) return;
      var box = qxBoxByName(boxName);
      if (!box) return;
      var story = ensureStory(box);

      var p0 = story.getElementsByTagName("qx-p")[0];
      var clone = p0 ? p0.cloneNode(true) : document.createElement("qx-p");

      var span = clone.getElementsByTagName("qx-span")[0];
      if (!span) {
        span = document.createElement("qx-span");
        clone.appendChild(span);
      }

      span.textContent = texto;

      while (story.firstChild) story.removeChild(story.firstChild);
      story.appendChild(clone);
    }

    // =========================================================
    // 🔹 Función genérica para pegar cuerpo
    // =========================================================
    var ESTILO_BAJADA = "pr-C-%20BAJADA";
    var ESTILO_TEXTO  = "pr-C-%20TEXTO";

    function pegarCuerpo(boxName, bajada, cuerpo) {
      var box = qxBoxByName(boxName);
      if (!box) return;
      var story = ensureStory(box);
      var pList = story.getElementsByTagName("qx-p");

      if (pList.length > 0 && bajada) {
        var p0 = pList[0];
        while (p0.firstChild) p0.removeChild(p0.firstChild);
        var span0 = document.createElement("qx-span");
        span0.textContent = bajada;
        p0.appendChild(span0);
        p0.setAttribute("class", ESTILO_BAJADA);
      }

      var mailIndex = null;
      for (var i = 0; i < pList.length; i++) {
        var t = (pList[i].textContent || "").trim();
        if (/^prensa@diariohuarpe\.com/i.test(t)) { mailIndex = i; break; }
      }
      if (mailIndex === null) { return; }

      var startBodyIdx = null;
      for (var j = mailIndex + 1; j < pList.length; j++) {
        var texto = (pList[j].textContent || "").trim();
        if (texto === "") { startBodyIdx = j; break; }
      }
      if (startBodyIdx === null) { startBodyIdx = mailIndex + 1; }

      var bodyStyle = ESTILO_TEXTO;
      if (startBodyIdx + 1 < pList.length) {
        var dummy = pList[startBodyIdx + 1];
        var cls = dummy.getAttribute("class");
        if (cls && cls.trim()) bodyStyle = cls;
      }

      while (story.childNodes.length > startBodyIdx + 1) { story.removeChild(story.lastChild); }

      var bloques = cuerpo.split(/\n{2,}/).map(function (b) { return b.trim(); }).filter(Boolean);
      for (var b = 0; b < bloques.length; b++) {
        var parrafos = bloques[b].split(/\n+/).map(function (p) { return p.trim(); }).filter(Boolean);
        for (var k = 0; k < parrafos.length; k++) {
          var p = document.createElement("qx-p");
          p.setAttribute("class", bodyStyle);
          var span = document.createElement("qx-span");
          span.textContent = parrafos[k];
          p.appendChild(span);
          story.appendChild(p);
        }
      }
    }


    // =========================================================
    // 🔹 Detección de textuales para Café de la Política
    function extractTextuales(cuerpoOriginal) {
    if (!cuerpoOriginal) return [];

    var texto = cuerpoOriginal.replace(/\r\n?/g, "\n");

    // Buscar “Textuales” (insensible a mayúsculas, también si tiene espacios)
    var idx = texto.toLowerCase().lastIndexOf("textuales");
    if (idx === -1) return [];

    // Tomar todo desde "Textuales" hasta el final
    var bloque = texto.substring(idx);

    // Detectar frases entre comillas tipográficas o rectas
    var regex = /“([^”]+)”|"([^"]+)"/g;
    var textuales = [];
    var m;
    while ((m = regex.exec(bloque)) !== null) {
      var frase = m[1] || m[2];
      if (frase) textuales.push(frase.trim());
    }

    return textuales;
  }



    // =========================================================
    // 🔹 Leer nota.txt y dividir secciones (OPCIONAL)
    // =========================================================
    var volanta  = "";
    var titulo   = "";
    var bajada   = "";
    var firma    = "";
    var epigrafe = "";
    var cuerpo   = "";

    if (tiene_texto && fs.existsSync(rutaTXT)) {
      var raw = fs.readFileSync(rutaTXT, "utf8");
      var plain = raw.replace(/\r\n?/g, "\n").trim();
      var partes = plain.split("///").map(function (p) { return cleanHTML(p || "").trim(); });

      volanta  = partes[0] || "";
      titulo   = partes[1] || "";
      bajada   = partes[2] || "";
      firma    = partes[3] || "";
      epigrafe = partes[4] || "";
      cuerpo   = partes[5] || "";
    }

    // =========================================================
    // 🔹 Router de secciones
    // =========================================================
    var seccionNorm = normalizar(seccion);
    var seccionesEspeciales = [
      "economia", "cafe de la politica", "eco huarpe",
      "cultura", "yo te invito", "yo cocino",
      "yo emprendo", "yo construyo", "deportes"
    ];

    if (seccionesEspeciales.indexOf(seccionNorm) !== -1) {
      if (seccionNorm === "cultura") {
        rutinaCultura();
        return;
      } else if (seccionNorm === "deportes") {
        rutinaDeportes();
        return;
      } else if (seccionNorm === "economia") {
        rutinaEconomia();
        return;
      } else if (seccionNorm === "cafe de la politica") {
        rutinaCafePolitica();
        return;
        } else if (seccionNorm === "eco huarpe") {
        rutinaEcoHuarpe();
        return;
      } else {
        alert("Sección con maqueta especial aún no implementada: " + seccion);
        return;
      }
    }

    // =========================================================
    // 🔹 Rutina general (por defecto)
    // =========================================================
    var maquetasDefault = [
      { numsec: "Box366", fecha: "Box1183", volanta: "Box372", titulo: "Box371", cuerpo: "Box373" },
      { numsec: "Box1852", fecha: "Box1850", volanta: "Box507", titulo: "Box506", cuerpo: "Box508" },
      { numsec: "Box1865", fecha: "Box1864", volanta: "Box1870", titulo: "Box1868", cuerpo: "Box1871" }
    ];

    maquetasDefault.forEach(function (m) {
      setTextoEnBox(m.numsec, numeroPagina + " | " + seccion.toUpperCase());
      setFecha(m.fecha);
      setTextoEnBox(m.volanta, volanta);
      setTextoEnBox(m.titulo, titulo);
      pegarCuerpo(m.cuerpo, bajada, cuerpo);
    });

    setTextoEnBox("Box1877", firma.split("\n")[0].split(",")[0].trim());
    setTextoEnBox("Box1878", epigrafe);
    //avisos
    pegarAvisosEnSeccion(seccionNorm);

    

    // =========================================================
    // 🔹 Rutina específica: Cultura
    // =========================================================
    function rutinaCultura() {
      setTextoEnBox("Box1302", numeroPagina + " | " + seccion.toUpperCase());
      setFecha("Box1331");
      setTextoEnBox("Box1286", volanta);
      setTextoEnBox("Box1289", titulo);
      setSoloBajadaEnBox("Box1282", bajada);
      pegarCuerpo("Box1290", "", cuerpo);
      setTextoEnBox("Box1287", epigrafe);

      setFecha("Box1377");
      setTextoEnBox("Box1380", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1382", volanta);
      setTextoEnBox("Box1381", titulo);
      pegarCuerpo("Box1376", bajada, cuerpo);

      setFecha("Box1311");
      setTextoEnBox("Box1326", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1321", volanta);
      setTextoEnBox("Box1324", titulo);
      pegarCuerpo("Box1325", bajada, cuerpo);
      setTextoEnBox("Box1322", epigrafe);

      setTextoEnBox("Box1475", firma.split("\n")[0].split(",")[0].trim());
      setTextoEnBox("Box1474", epigrafe);
      //avisos
      pegarAvisosEnSeccion(seccionNorm);
    }

    // =========================================================
    // 🔹 Rutina específica: Deportes
    // =========================================================
    function rutinaDeportes() {
      // --- Página 1 ---
      setFecha("Box548");
      setTextoEnBox("Box549", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box751", volanta);
      setTextoEnBox("Box541", titulo);
      pegarCuerpo("Box545", bajada, cuerpo);

      // --- Página 2 ---
      setFecha("Box904");
      setTextoEnBox("Box898", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box911", volanta);
      setTextoEnBox("Box908", titulo);
      pegarCuerpo("Box910", bajada, cuerpo);

      // --- Página 3 ---
      setFecha("Box829");
      setTextoEnBox("Box885", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box830", volanta);
      setTextoEnBox("Box825", titulo);
      pegarCuerpo("Box827", bajada, cuerpo);

      // --- Comunes ---
      setTextoEnBox("Box1644", firma.split("\n")[0].split(",")[0].trim());
      setTextoEnBox("Box1643", epigrafe);
      //avisos
      pegarAvisosEnSeccion(seccionNorm);
    }

    // =========================================================
    // 🔹 Rutina específica: Economía
    // =========================================================
    function rutinaEconomia() {

      // --- Página 1 ---
      setFecha("Box1200");
      setTextoEnBox("Box1203", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box873", volanta);
      setTextoEnBox("Box872", titulo);
      pegarCuerpo("Box871", bajada, cuerpo);

      // --- Página 2 ---
      setFecha("Box1908");
      setTextoEnBox("Box1909", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1913", volanta);
      setTextoEnBox("Box1912", titulo);
      pegarCuerpo("Box1914", bajada, cuerpo);

      // --- Página 3 ---
      setFecha("Box1890");
      setTextoEnBox("Box1891", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1896", volanta);
      setTextoEnBox("Box1894", titulo);
      pegarCuerpo("Box1897", bajada, cuerpo);

      // --- Página 4 ---
      setFecha("Box1883");
      setTextoEnBox("Box1884", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1888", volanta);
      setTextoEnBox("Box1887", titulo);
      pegarCuerpo("Box1889", bajada, cuerpo);

      // --- Comunes ---
      setTextoEnBox("Box1920", firma.split("\n")[0].split(",")[0].trim());
      setTextoEnBox("Box1919", epigrafe);
      //avisos
      pegarAvisosEnSeccion(seccionNorm);
    }
    
    // =========================================================
    // 🔹 Rutina específica: Café de la Política
    // =========================================================
    function rutinaCafePolitica() {

      // ===== Capturar textuales sin tocar el cuerpo =====
      var listaTextuales = extractTextuales(cuerpo) || [];
      var textual1 = listaTextuales.length > 0 ? listaTextuales[0] : "";
      var textual2 = listaTextuales.length > 1 ? listaTextuales[1] : "";

      // --- Página 1 ---
      setFecha("Box366");
      setTextoEnBox("Box1679", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1850", volanta);
      setTextoEnBox("Box1849", titulo);
      pegarCuerpo("Box1851", bajada, cuerpo);

      // --- Página 2 ---
      setFecha("Box1925");
      setTextoEnBox("Box1924", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1923", volanta);
      setTextoEnBox("Box1922", titulo);
      pegarCuerpo("Box1927", bajada, cuerpo);

      // --- Página 3 ---
      setFecha("Box1944");
      setTextoEnBox("Box1943", numeroPagina + " | " + seccion.toUpperCase());
      setTextoEnBox("Box1942", volanta);
      setTextoEnBox("Box1941", titulo);
      pegarCuerpo("Box1946", bajada, cuerpo);

      // --- Comunes ---
      setTextoEnBox("Box2069", firma.split("\n")[0].split(",")[0].trim());
      setTextoEnBox("Box2068", epigrafe);
      
      //avisos
      pegarAvisosEnSeccion(seccionNorm);
    
      // --- Textuales ---
      setTextoEnBox("Box1866", textual1);
      setTextoEnBox("Box1867", textual2);
    }
    // =========================================================
    // 🔹 Rutina específica: Eco Huarpe
    // =========================================================
    function rutinaEcoHuarpe() {

      // --- Fecha ---
      setFecha("Box6095");

      // --- Número de página (sin sección) ---
      // Va solo el número, sin “| SECCION”
      setTextoEnBox("Box6390", numeroPagina.toString());

      // --- Volanta ---
      setTextoEnBox("Box6587", volanta);

      // --- Título ---
      setTextoEnBox("Box6582", titulo);

      // --- Cuerpo ---
      // Usa la misma lógica genérica: bajada + cuerpo
      pegarCuerpo("Box6584", bajada, cuerpo);

      // --- Firma ---
      setTextoEnBox("Box6705", firma.split("\n")[0].split(",")[0].trim());

      // --- Epígrafe ---
      setTextoEnBox("Box6706", epigrafe);

      //avisos
      pegarAvisosEnSeccion(seccionNorm);
    



    }

    
    
    





  } catch (err) {
    alert("Error al pegar:\n" + err);
  }
})();
