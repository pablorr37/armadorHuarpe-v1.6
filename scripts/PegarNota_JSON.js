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
    var fechaTexto = "";    // fecha calculada por Python (evita adelantar un día pasada la medianoche)
    var numeroPagina = 0;
    var avisos = [];
    var fotos = [];
    var tiene_texto = false;
    var notas = [];         // migración JSON 2026-05-06
    var maqueta_path = "";  // migración JSON 2026-05-06

    // Leer path exacto al data_pagina.json desde runtime_config.json (escrito por Python al hacer "Pegar en Quark")
    var _appdataDir = "C:/Users/usuario/AppData/Roaming";
    var _appdataScripts = _appdataDir + "/ArmadorHuarpe/scripts/";
    var rutaJSON = "";
    try {
      var _cfgRaw = fs.readFileSync(_appdataScripts + "runtime_config.json", "utf8").trim();
      var _cfg = JSON.parse(_cfgRaw);
      rutaJSON = (_cfg.data_pagina_path || "").replace(/\\/g, "/");
    } catch (e) {
      alert("PegarNota: error leyendo runtime_config.json:\n" + e);
      return;
    }
    if (!rutaJSON) {
      alert("PegarNota: runtime_config.json no contiene data_pagina_path.\nUsá 'Pegar en Quark' desde la app antes de ejecutar este script.");
      return;
    }
    var rutaTXT = _appdataScripts + "nota.txt";

    try {
      if (fs.existsSync(rutaJSON)) {
        var contenido = fs.readFileSync(rutaJSON, "utf8").trim();
        var data = JSON.parse(contenido);
        numeroPagina = parseInt(data.numero_pagina || 0);
        seccion = (data.seccion || "").trim();
        fechaTexto = (data.fecha || "").trim();
        username = (data.usuario || "usuario").trim();
        avisos = data.avisos || [];
        fotos = data.fotos || [];
        tiene_texto = !!data.tiene_texto;
        notas = data.notas || [];          // migración JSON 2026-05-06
        maqueta_path = data.maqueta_path || "";  // migración JSON 2026-05-06
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
        completa: ["Box1911"],
        // Doble media: dos medias páginas apiladas. El box superior es el mismo que
        // el de "completa" (Box1911); el inferior es un box dedicado (Box1932).
        doblemedia: { sup: "Box1911", inf: "Box1932" }
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
var FOTO_BOXES      = ["Box369",  "Box505",  "Box1867"];   // 3 variantes (fix 1687→1867)
var PIE_FOTO_BOXES  = FOTO_BOXES;                            // usado por las rutinas legacy por sección

var UNIVERSAL = {
  principal: [
    { numsec:"Box366",  fecha:"Box1183", volanta:"Box372",  titulo:"Box371",  cuerpo:"Box373",  foto:"Box369"  },
    { numsec:"Box1852", fecha:"Box1850", volanta:"Box507",  titulo:"Box506",  cuerpo:"Box508",  foto:"Box505"  },
    { numsec:"Box1865", fecha:"Box1864", volanta:"Box1870", titulo:"Box1868", cuerpo:"Box1871", foto:"Box1867" }
  ],
  secundaria: [
    { volanta:"Box511",  titulo:"Box499",  cuerpo:"Box500"  },
    { volanta:"Box1875", titulo:"Box1873", cuerpo:"Box1876" }
  ],
  firma: "Box1877",
  epigrafe: "Box1878"
};

var _hits = 0;          // pegados exitosos (cualquier path)
var _faltantes = [];    // box buscados que no existían
var _fotoBoxesOk = 0;   // cajas de FOTO principal que recibieron imagen (src seteado)
var _fotoPathTried = ""; // path de la foto principal que se intentó pegar

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

    if (tipo === "doblemedia") {
      // Superior (Box1911, igual que "completa") + inferior (Box1932).
      var dm = conf.doblemedia || AVISO_TARGETS.default.doblemedia;
      var res1 = setImagenEnBox(dm.sup, path);
      if (res1.ok) okCount++; else fails.push(res1);
      var path2 = (a.path2 || "").trim();
      if (path2) {
        var res2 = setImagenEnBox(dm.inf, path2);
        if (res2.ok) okCount++; else fails.push(res2);
      }
    } else {
      // completa → box propio de la sección; cualquier otro tipo → box universales
      var targets = (tipo === "completa") ? (conf.completa || []) : UNIVERSAL_AVISO;
      for (var j = 0; j < targets.length; j++) {
        var res = setImagenEnBox(targets[j], path);
        if (res.ok) okCount++;
        else fails.push(res);
      }
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

  // Path CRUDO (literal, con espacios reales). Quark resuelve el file:// con el path
  // sin percent-encoding; escapar a %20 rompía todas las rutas (carpetas de edición
  // tienen espacios) y por eso no pegaban fotos ni avisos.

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
  return _picBoxIndex[name]
    || layout.querySelector("qx-box[box-name='" + name + "']")
    || null;
}

function setImagenEnBox(boxName, filePath) {
  if (!filePath) return { ok:false, why:"path vacío", box:boxName };

  var box = getPicBoxByName(boxName);
  if (!box) { _faltantes.push(boxName); return { ok:false, why:"no existe box", box:boxName }; }

  var url = toFileUrl(filePath);

  // Si el box ya tiene qx-img (boxes con imagen en template), usarlo directamente
  var imgs = box.getElementsByTagName("qx-img");
  if (imgs && imgs.length) {
    try {
      // Vaciar primero fuerza el cambio → re-import desde disco aunque el path
      // sea el mismo (el fotocromista re-edita el archivo sin renombrarlo).
      try { imgs[0].setAttribute("src", ""); } catch (e0) {}
      imgs[0].setAttribute("src", url);
      _hits++;
      return { ok:true, why:"", box:boxName, url:url };
    } catch (e) {
      return { ok:false, why:"error en qx-img.src: " + e, box:boxName };
    }
  }

  // Box vacío (sin qx-img): poner src directamente en qx-box
  try {
    try { box.setAttribute("src", ""); } catch (e1) {}
    box.setAttribute("src", url);
    _hits++;
    return { ok:true, why:"", box:boxName, url:url };
  } catch (e2) {
    return { ok:false, why:"error en box.src: " + e2, box:boxName };
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

    function setFecha(boxName) {
      var box = qxBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
      var story = ensureStory(box);
      var p = story.getElementsByTagName("qx-p")[0];
      if (!p) return;
      var span = p.getElementsByTagName("qx-span")[0];
      if (!span) { span = document.createElement("qx-span"); p.appendChild(span); }
      // Preferir la fecha calculada por Python (viaja en data.fecha). Si no vino,
      // fallback al cálculo local new Date()+1 (compatibilidad).
      var texto = fechaTexto;
      if (!texto) {
        var meses = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO","JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"];
        var dias = ["DOMINGO","LUNES","MARTES","MIÉRCOLES","JUEVES","VIERNES","SÁBADO"];
        var hoy = new Date(); hoy.setDate(hoy.getDate() + 1);
        texto = dias[hoy.getDay()] + " " + hoy.getDate() + " DE " + meses[hoy.getMonth()] + " DE " + hoy.getFullYear();
      }
      span.textContent = texto;
    }

    function setSoloBajadaEnBox(boxName, texto) {
      if (!texto) return;
      var box = qxBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
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
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
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

    // Pegado de cuerpo SIN depender del marcador "prensa@diariohuarpe.com".
    // Lo usan las notas secundarias, cuyos box NO traen ese párrafo ancla
    // (a diferencia de la principal). Vuelca el cuerpo en párrafos limpios.
    function pegarCuerpoSimple(boxName, cuerpo) {
      if (!cuerpo) return;
      var box = qxBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
      var story = ensureStory(box);

      // Estilo de párrafo: heredar del primer qx-p existente, o ESTILO_TEXTO.
      var pList = story.getElementsByTagName("qx-p");
      var bodyStyle = ESTILO_TEXTO;
      if (pList.length > 0) {
        var cls0 = pList[0].getAttribute("class");
        if (cls0 && cls0.trim()) bodyStyle = cls0;
      }

      while (story.firstChild) story.removeChild(story.firstChild);

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

    // Seleccionar nota principal y secundarias por ROL (no por índice)
    var notaPrincipal = null;
    var notasSecundarias = [];
    for (var _i = 0; _i < notas.length; _i++) {
      var _rol = (notas[_i].rol || notas[_i].tipo || "").toLowerCase();
      if (_rol === "principal" && !notaPrincipal) notaPrincipal = notas[_i];
      else notasSecundarias.push(notas[_i]);
    }

    if (notaPrincipal) {
      // Leer texto desde JSON estructurado (migración JSON 2026-05-06)
      volanta  = cleanHTML(notaPrincipal.volanta  || "");
      titulo   = cleanHTML(notaPrincipal.titulo   || "");
      bajada   = cleanHTML(notaPrincipal.bajada   || "");
      firma    = cleanHTML(notaPrincipal.firma    || "");
      epigrafe = cleanHTML(notaPrincipal.epigrafe || "");
      cuerpo   = cleanHTML(notaPrincipal.cuerpo   || "");
    } else if (notas.length === 0 && tiene_texto && fs.existsSync(rutaTXT)) {
      // Fallback a nota.txt (compatibilidad con notas sin JSON)
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
    // 🔹 Foto principal
    // =========================================================
    function pegarFotoPrincipal() {
      var foto = null;
      for (var i = 0; i < fotos.length; i++) {
        if (fotos[i].rol === "principal") { foto = fotos[i]; break; }
      }
      if (!foto) return;
      var path = (foto.path || "").trim();
      if (!path) return;
      _fotoPathTried = path;
      // Pegar la principal en las 3 variantes (las que no existan se ignoran)
      for (var b = 0; b < FOTO_BOXES.length; b++) {
        var r = setImagenEnBox(FOTO_BOXES[b], path);
        if (r && r.ok) _fotoBoxesOk++;
      }
    }

    // Sección "Escrache al Bache": pegado DEDICADO. 2 imágenes distintas + sus epígrafes.
    // img1 (orden 0) → Box6357, img2 (orden 1) → Box6429; epi1 → Box6599, epi2 → Box6604.
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
        if (path) setImagenEnBox(IMG_BOXES[i], path);   // si falta el box → va a _faltantes
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
      var sorted = fotos.slice().sort(function(a, b) { return a.orden - b.orden; });
      for (var i = 0; i < sorted.length && i < PIE_FOTO_BOXES.length; i++) {
        var path = (sorted[i].path || "").trim();
        if (path) setImagenEnBox(PIE_FOTO_BOXES[i], path);
      }
    }

    // Extrae frases entre comillas (tipográficas “…” o rectas "…") de un string.
    function _extraerEntreComillas(s) {
      var out = [];
      if (!s) return out;
      var re = /“([^”]+)”|"([^"]+)"/g;
      var m;
      while ((m = re.exec(s)) !== null) {
        var frase = (m[1] || m[2] || "").trim();
        if (frase) out.push(frase);
      }
      return out;
    }

    // Textuales dedicados de Café de la Política: las dos primeras citas auto
    // (notaPrincipal.textuales_auto) van a sus box dedicados. El set depende de si
    // la página lleva aviso de pie (tipo pie) o no (tipo vacía). Cada textual tiene
    // 3 variantes de box; el que exista en la maqueta lo toma.
    function pegarTextualesCafePolitica() {
      var auto = (notaPrincipal && notaPrincipal.textuales_auto) ? notaPrincipal.textuales_auto : [];
      var t1 = cleanHTML(auto[0] || "");
      var t2 = cleanHTML(auto[1] || "");
      // Si no vinieron dos textuales separados, puede que las dos citas vengan unidas
      // en un mismo slot (p.ej. “Frase A”.“Frase B”). Separarlas por pares de comillas.
      if (!t1 || !t2) {
        var fuente = "";
        for (var k = 0; k < auto.length; k++) { if (auto[k]) fuente += " " + auto[k]; }
        var frases = _extraerEntreComillas(fuente);
        if (frases.length >= 2) {
          t1 = cleanHTML(frases[0]);
          t2 = cleanHTML(frases[1]);
        } else if (frases.length === 1 && !t1) {
          t1 = cleanHTML(frases[0]);
        }
      }
      var pie = tienePie();
      var BOXES_T1 = pie ? ["Box2086", "Box2074", "Box2080"] : ["Box2008", "Box2017", "Box2025"];
      var BOXES_T2 = pie ? ["Box2087", "Box2075", "Box2081"] : ["Box2009", "Box2018", "Box2026"];
      for (var i = 0; i < BOXES_T1.length; i++) { if (t1) setTextoEnBox(BOXES_T1[i], t1); }
      for (var j = 0; j < BOXES_T2.length; j++) { if (t2) setTextoEnBox(BOXES_T2[j], t2); }
    }

    // =========================================================
    // 🔹 Textuales, dato y número estructurados
    // =========================================================
    function pegarTextualDatoNumero(nota) {
      var tx = nota.textual;
      if (tx && tx.tipo) {
        var t1 = cleanHTML(tx.texto1 || "");
        var t2 = cleanHTML(tx.texto2 || "");
        var t3 = cleanHTML(tx.texto3 || "");
        var n1 = cleanHTML(tx.nombre1 || "");
        var c1 = cleanHTML(tx.cargo1 || "");
        var n2 = cleanHTML(tx.nombre2 || "");
        var c2 = cleanHTML(tx.cargo2 || "");
        var n3 = cleanHTML(tx.nombre3 || "");
        var c3 = cleanHTML(tx.cargo3 || "");
        var cred1 = [n1, c1].filter(Boolean).join("\n");
        var cred2 = [n2, c2].filter(Boolean).join("\n");
        var cred3 = [n3, c3].filter(Boolean).join("\n");

        if (tx.tipo === "simple") {
          setTextoEnBox("Box427", t1);
          setTextoEnBox("Box425", cred1);
        } else if (tx.tipo === "x2") {
          setTextoEnBox("Box1053", t1);
          setTextoEnBox("Box1056", t2);
          setTextoEnBox("Box1054", cred1);
        } else if (tx.tipo === "x3") {
          setTextoEnBox("Box1166", t1);
          setTextoEnBox("Box1165", cred1);
          setTextoEnBox("Box1167", t2);
          setTextoEnBox("Box1164", cred2);
          setTextoEnBox("Box1169", t3);
          setTextoEnBox("Box1168", cred3);
        } else if (tx.tipo === "con_foto") {
          setTextoEnBox("Box1138", t1);
          setTextoEnBox("Box1137", cred1);
          if (tx.foto) setImagenEnBox("Box1136", tx.foto);
        } else if (tx.tipo === "con_foto_xl") {
          setTextoEnBox("Box417", t1);
          setTextoEnBox("Box416", cred1);
          if (tx.foto) setImagenEnBox("Box415", tx.foto);
        }
      }

      if (nota.dato) {
        setTextoEnBox("Box1126", cleanHTML(nota.dato));
      }

      var num = nota.numero;
      if (num) {
        if (num.cabecera) setTextoEnBox("Box1063", cleanHTML(num.cabecera));
        if (num.texto)    setTextoEnBox("Box1064", cleanHTML(num.texto));
      }

      if (nota.qr_path) {
        setImagenEnBox("Box1657", nota.qr_path);
      }
    }

    // =========================================================
    // 🔹 Pegado universal (box de la maqueta madre)
    // =========================================================
    var seccionNorm = normalizar(seccion);

    function hayBoxesUniversalesTexto() {
      var checks = [UNIVERSAL.firma, UNIVERSAL.epigrafe];
      UNIVERSAL.principal.forEach(function (v) { checks.push(v.volanta, v.titulo, v.cuerpo, v.numsec); });
      UNIVERSAL.secundaria.forEach(function (v) { checks.push(v.volanta, v.titulo, v.cuerpo); });
      for (var i = 0; i < checks.length; i++) { if (qxBoxByName(checks[i])) return true; }
      return false;
    }

    function pegarUniversal() {
      // Noticia principal en las 3 variantes
      UNIVERSAL.principal.forEach(function (m) {
        setTextoEnBox(m.numsec, numeroPagina + " | " + seccion.toUpperCase());
        setFecha(m.fecha);
        setTextoEnBox(m.volanta, volanta);
        setTextoEnBox(m.titulo, titulo);
        pegarCuerpo(m.cuerpo, bajada, cuerpo);
      });

      // Box únicos
      setTextoEnBox(UNIVERSAL.firma, firma.split("\n")[0].split(",")[0].trim());
      setTextoEnBox(UNIVERSAL.epigrafe, epigrafe);

      // Avisos (sistema intacto)
      pegarAvisosEnSeccion(seccionNorm);

      // Noticias secundarias (por rol): cada una en AMBAS variantes
      for (var ni = 0; ni < notasSecundarias.length; ni++) {
        var notaN = notasSecundarias[ni];
        var volanta_n = cleanHTML(notaN.volanta || "");
        var titulo_n  = cleanHTML(notaN.titulo  || "");
        var cuerpo_n  = cleanHTML(notaN.cuerpo  || "");
        UNIVERSAL.secundaria.forEach(function (s) {
          setTextoEnBox(s.volanta, volanta_n);
          setTextoEnBox(s.titulo,  titulo_n);
          pegarCuerpoSimple(s.cuerpo, cuerpo_n);
        });
      }

      // Foto principal en todos los FOTO_BOXES (todas las maquetas comparten box;
      // el que exista la toma). Las fotos de secundarias no se pegan por ahora.
      pegarFotoPrincipal();
      if (notaPrincipal) pegarTextualDatoNumero(notaPrincipal);
    }

    // =========================================================
    // 🔹 Dispatch: universal primero, router por sección como fallback
    // =========================================================
    if (seccionNorm === "escrache al bache") {
      // Maqueta especial: pegado DEDICADO (nunca universal). Imágenes + epígrafes
      // en sus boxes propios (Box6357/6429/6599/6604).
      pegarEscracheAlBache();
    } else if (hayBoxesUniversalesTexto()) {
      pegarUniversal();
    } else {
      // Fallback legacy por sección (rutinas intactas)
      if (seccionNorm === "cultura")               rutinaCultura();
      else if (seccionNorm === "deportes")         rutinaDeportes();
      else if (seccionNorm === "economia")         rutinaEconomia();
      else if (seccionNorm === "cafe de la politica") rutinaCafePolitica();
      else if (seccionNorm === "eco huarpe")       rutinaEcoHuarpe();
    }

    // Café de la Política: la maqueta es universal (texto/foto/aviso se pegan por la
    // rama universal); lo único dedicado son sus dos textuales, que se pegan acá sin
    // importar por qué rama se hizo el pegado.
    if (seccionNorm === "cafe de la politica") pegarTextualesCafePolitica();

    if (_hits === 0) {
      var _uniq = _faltantes.filter(function (v, i) { return _faltantes.indexOf(v) === i; });
      alert("PegarNota: no se encontró ningún box para pegar.\n\nBox buscados sin éxito:\n" + _uniq.join(", "));
    }

    // Diagnóstico: si hubo foto y se pegó texto pero la foto no entró en ninguna caja.
    if (_hits > 0 && fotos && fotos.length > 0 && _fotoBoxesOk === 0 && _fotoPathTried) {
      var _fb = FOTO_BOXES.filter(function (v, i) { return FOTO_BOXES.indexOf(v) === i; });
      alert("PegarNota: el texto se pegó pero la foto principal no entró en ninguna caja.\n\n" +
            "Foto: " + _fotoPathTried + "\n" +
            "Cajas de foto probadas (no existen en esta maqueta): " + _fb.join(", "));
    }



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
      if (tienePie()) { pegarFotosConPie(); } else { pegarFotoPrincipal(); }
      if (notaPrincipal) pegarTextualDatoNumero(notaPrincipal);
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
      if (tienePie()) { pegarFotosConPie(); } else { pegarFotoPrincipal(); }
      if (notaPrincipal) pegarTextualDatoNumero(notaPrincipal);
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
      if (tienePie()) { pegarFotosConPie(); } else { pegarFotoPrincipal(); }
      if (notaPrincipal) pegarTextualDatoNumero(notaPrincipal);
    }

    // =========================================================
    // 🔹 Rutina específica: Café de la Política
    // =========================================================
    function rutinaCafePolitica() {

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

      if (tienePie()) { pegarFotosConPie(); } else { pegarFotoPrincipal(); }
      if (notaPrincipal) pegarTextualDatoNumero(notaPrincipal);
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
      if (tienePie()) { pegarFotosConPie(); } else { pegarFotoPrincipal(); }
      if (notaPrincipal) pegarTextualDatoNumero(notaPrincipal);
    



    }

    
    
    





  } catch (err) {
    alert("Error al pegar:\n" + err);
  }
})();