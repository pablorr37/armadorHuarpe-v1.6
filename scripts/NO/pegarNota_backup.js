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
    // 🔹 Leer datos de página y sección desde data_pagina.json
    // =========================================================
    var seccion = "SIN SECCIÓN";
    var username = "usuario";
    var numeroPagina = 0;

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
    // 🔹 Leer nota.txt y dividir secciones
    // =========================================================
    if (!fs.existsSync(rutaTXT)) {
      alert("No se encontró el archivo nota.txt en:\n" + rutaBase);
      return;
    }
    var raw = fs.readFileSync(rutaTXT, "utf8");
    var plain = raw.replace(/\r\n?/g, "\n").trim();
    var partes = plain.split("///").map(function (p) { return cleanHTML(p || "").trim(); });
    var volanta  = partes[0] || "";
    var titulo   = partes[1] || "";
    var bajada   = partes[2] || "";
    var firma    = partes[3] || "";
    var epigrafe = partes[4] || "";
    var cuerpo   = partes[5] || "";

    // =========================================================
    // 🔹 Router de secciones
    // =========================================================
    var seccionNorm = normalizar(seccion);
    var seccionesEspeciales = [
      "economia", "cafe de la politica", "eco huarpe",
      "cultura", "yo te invito", "yo cocino",
      "yo emprendo", "yo construyo", "deporte"
    ];

    if (seccionesEspeciales.indexOf(seccionNorm) !== -1) {
      if (seccionNorm === "cultura") {
        rutinaCultura();
        return;
      } else if (seccionNorm === "deporte") {
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
    



    }

    
    
    





  } catch (err) {
    alert("Error al pegar:\n" + err);
  }
})();
