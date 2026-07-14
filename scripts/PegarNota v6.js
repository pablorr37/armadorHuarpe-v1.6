// =============================================================
//  PegarNota_JSON_V6.js  ·  QuarkXPress 2018 v14.2 (QX.js)
// -------------------------------------------------------------
//  Basado en PegarNota_JSON.js (V1) con arquitectura limpia.
//  · Todas las maquetas son universales — rutinas específicas
//    por sección eliminadas (deprecadas).
//  · Casos especiales que se mantienen:
//      - Escrache al Bache (pegado dedicado de 2 imágenes)
//      - Café de la Política (textuales auto adicionales)
//  · Preserva TODO el comportamiento de pegarUniversal():
//      folio, fecha, volanta, título, bajada/cuerpo, firma,
//      epígrafe, avisos, notas secundarias, fotos,
//      textuales/dato/número/QR.
// =============================================================
(function () {
  try {

    // =========================================================
    // 🔹 CONSTANTES
    // =========================================================
    var ESTILO_BAJADA = "pr-C-%20BAJADA";
    var ESTILO_TEXTO  = "pr-C-%20TEXTO";

    var AVISO_TARGETS = {
      "default": {
        pie:        ["Box1889", "Box1890", "Box1896"],
        media:      ["Box1894", "Box1897", "Box1899"],
        robapagina: ["Box1897", "Box1903", "Box1904"],
        completa:   ["Box1911"],
        doblemedia: { sup: "Box1911", inf: "Box1932" }
      },
      "cultura": {
        pie:        ["Box1561", "Box1568"],
        media:      ["Box1566", "Box1570"],
        robapagina: ["Box1566", "Box1573"]
      },
      "deportes": {
        pie:        ["Box1645", "Box1647", "Box1649"],
        media:      ["Box1645", "Box1647", "Box1649"],
        robapagina: ["Box1652", "Box1650"]
      },
      "economia": {
        pie:        ["Box1965", "Box1966", "Box1967"],
        media:      ["Box1965", "Box1966", "Box1967"],
        robapagina: ["Box1966", "Box1967"]
      },
      "cafe de la politica": {
        pie:        ["Box2091"],
        media:      ["Box2091"],
        robapagina: ["Box2091", "Box2131"]
      },
      "eco huarpe": {
        pie:        ["Box6776"],
        media:      ["Box6776"],
        robapagina: ["Box6776"]
      },
      "yo te invito": {
        pie:        ["Box2561"],
        media:      ["Box2566"],
        robapagina: ["Box2568"]
      },
      "yo cocino": {
        pie:        ["Box3561"],
        media:      ["Box3566"],
        robapagina: ["Box3568"]
      },
      "yo emprendo": {
        pie:        ["Box4561"],
        media:      ["Box4566"],
        robapagina: ["Box4568"]
      }
    };

    var UNIVERSAL_AVISO = ["Box1988", "Box1995", "Box1999"];
    var FOTO_BOXES      = ["Box369", "Box505", "Box1867"];
    var PIE_FOTO_BOXES  = FOTO_BOXES;

    // Estructura de boxes de la maqueta universal
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
      firma:    "Box1877",
      epigrafe: "Box1878"
    };

    // Membresía COMPLETA de cada grupo de recurso (el DOM de Quark es plano y no expone
    // los grupos Ctrl+G). Derivado por proximidad del volcado de todas las cajas: incluye
    // texto, crédito, foto, fondo y líneas de decoración. moverGrupo() desplaza todas juntas.
    var RECURSO_GRUPO = {
      "textual_simple":      ["Box425", "Box426", "Box427", "Box428"],
      "textual_x2":          ["Box1052", "Box1053", "Box1054", "Box1055", "Box1056", "Box1057"],
      "textual_x3":          ["Box1161", "Box1162", "Box1163", "Box1164", "Box1165",
                              "Box1166", "Box1167", "Box1168", "Box1169", "Box1170"],
      "textual_con_foto":    ["Box1136", "Box1137", "Box1138", "Box1140"],
      "textual_con_foto_xl": ["Box415", "Box416", "Box417", "Box418"],
      "dato":                ["Box1123", "Box1124", "Box1125", "Box1126", "Box1127"],
      "numero":              ["Box1061", "Box1062", "Box1063", "Box1064", "Box1065"],
      "qr":                  ["Box1656", "Box1657", "Box1658", "Box1659"]
    };

    // Compensación del pasteboard: al mover un recurso parkeado (1*/1**) a la página, Quark
    // renderiza su X con un offset global (render = attr - COMP_X). Medido empíricamente.
    // El clon a otra plantilla es una caja FRESCA en la página (no pasteboard) → se le RESTA
    // esta compensación para caer en la posición page-relative real.
    var COMP_X = 194.733;
    var COMP_Y = 11.289;

    // =========================================================
    // 🔹 SETUP
    // =========================================================
    var layout = app.activeLayoutDOM();

    // Índice rápido de todos los boxes por box-name
    var _boxIndex = (function () {
      var idx = {};
      var all = layout.getElementsByTagName("qx-box");
      for (var i = 0; i < all.length; i++) {
        var name = all[i].getAttribute("box-name");
        if (name) idx[name] = all[i];
      }
      return idx;
    })();

    var _hits          = 0;
    var _faltantes     = [];
    var _fotoBoxesOk   = 0;
    var _fotoPathTried = "";
    var _geoDiag       = [];   // diagnóstico de geometría (foto + grupos)
    var _clonesAgregados = 0;  // cuántas cajas nuevas (clones a plantillas 2/3) se agregaron

    // =========================================================
    // 🔹 HELPERS GENERALES
    // =========================================================
    function normalizar(str) {
      return (str || "").toLowerCase().normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "").trim();
    }

    function normalizeWinPath(p) {
      return (p || "").trim().replace(/\\/g, "/");
    }

    function toFileUrl(p) {
      p = normalizeWinPath(p);
      if (/^[A-Za-z]:\//.test(p))        return "file:///" + p;
      if (/^\/\/[^\/]+\/[^\/]+/.test(p)) return "file:////" + p.replace(/^\/\//, "");
      if (/^file:\/\//i.test(p))          return p;
      return "file://" + p;
    }

    function cleanHTML(str) {
      // Coerción robusta: los campos pueden venir como número (p.ej. un 'numero'/'dato'
      // numérico en el JSON) y str.replace fallaría. Convertir siempre a string.
      str = (str === null || typeof str === "undefined") ? "" : ("" + str);
      return str
        .replace(/<\/?[^>]+>/g, "")
        .replace(/&nbsp;/gi,  " ")
        .replace(/&amp;/gi,   "&")
        .replace(/&quot;/gi,  "\"")
        .replace(/&#39;/gi,   "'")
        .replace(/&lt;/gi,    "<")
        .replace(/&gt;/gi,    ">")
        .replace(/\s+\n/g,    "\n")
        .replace(/\n\s+/g,    "\n")
        .trim();
    }

    function qxBoxByName(name) {
      return _boxIndex[name]
        || layout.querySelector("qx-box[box-name='" + name + "'][box-content-type='text']")
        || null;
    }

    function getPicBoxByName(name) {
      return _boxIndex[name]
        || layout.querySelector("qx-box[box-name='" + name + "']")
        || null;
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

    // =========================================================
    // 🔹 HELPERS DE TEXTO
    // =========================================================

    // Texto simple (volanta, título, epígrafe, folio, firma):
    // clona el párrafo existente para preservar estilos.
    function setTextoEnBox(boxName, texto) {
      if (!texto && texto !== 0) return;
      var box = qxBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
      var story = ensureStory(box);
      var p0 = story.getElementsByTagName("qx-p")[0];
      if (!p0) return;
      var clone = p0.cloneNode(true);
      var span  = clone.getElementsByTagName("qx-span")[0];
      if (!span) { span = document.createElement("qx-span"); clone.appendChild(span); }
      span.textContent = texto;
      while (story.firstChild) story.removeChild(story.firstChild);
      story.appendChild(clone);
    }

    // Fecha: usa fechaTexto de Python; fallback a fecha local +1 día.
    function setFecha(boxName) {
      var box = qxBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
      var story = ensureStory(box);
      var p = story.getElementsByTagName("qx-p")[0];
      if (!p) return;
      var span = p.getElementsByTagName("qx-span")[0];
      if (!span) { span = document.createElement("qx-span"); p.appendChild(span); }
      var texto = fechaTexto;
      if (!texto) {
        var meses = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO","JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"];
        var dias  = ["DOMINGO","LUNES","MARTES","MIÉRCOLES","JUEVES","VIERNES","SÁBADO"];
        var hoy = new Date(); hoy.setDate(hoy.getDate() + 1);
        texto = dias[hoy.getDay()] + " " + hoy.getDate() + " DE " + meses[hoy.getMonth()] + " DE " + hoy.getFullYear();
      }
      span.textContent = texto;
    }

    // Cuerpo con bajada integrada:
    // · p[0] → bajada con clase BAJADA
    // · detecta marcador "prensa@diariohuarpe.com"
    // · extrae estilo TEXTO del párrafo plantilla siguiente al separador vacío
    // · pega cuerpo con ese estilo
    function pegarCuerpo(boxName, bajada, cuerpo) {
      if (!cuerpo) return;
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
        if (/^prensa@diariohuarpe\.com/i.test((pList[i].textContent || "").trim())) {
          mailIndex = i; break;
        }
      }
      if (mailIndex === null) return;

      var startBodyIdx = null;
      for (var j = mailIndex + 1; j < pList.length; j++) {
        if ((pList[j].textContent || "").trim() === "") { startBodyIdx = j; break; }
      }
      if (startBodyIdx === null) startBodyIdx = mailIndex + 1;

      var bodyStyle = ESTILO_TEXTO;
      if (startBodyIdx + 1 < pList.length) {
        var cls = pList[startBodyIdx + 1].getAttribute("class");
        if (cls && cls.trim()) bodyStyle = cls;
      }

      while (story.childNodes.length > startBodyIdx + 1) story.removeChild(story.lastChild);

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

    // Cuerpo simple (notas secundarias: sin bajada, sin marcador de email).
    function pegarCuerpoSimple(boxName, cuerpo) {
      if (!cuerpo) return;
      var box = qxBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return; }
      _hits++;
      var story = ensureStory(box);
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
    // 🔹 HELPERS DE IMAGEN
    // =========================================================
    // Lee una variable de borde --qx-<lado> (en mm) del style inline de la caja.
    function _bordeMM(style, lado) {
      var m = (style || "").match(new RegExp("--qx-" + lado + ":(-?[0-9.]+)mm"));
      return m ? parseFloat(m[1]) : null;
    }

    // Reemplaza (o deja igual si no existe) una variable de borde --qx-<lado>.
    function _setBordeMM(style, lado, valorMM) {
      if (typeof style !== "string") return style;
      return style.replace(
        new RegExp("--qx-" + lado + ":-?[0-9.]+mm"),
        "--qx-" + lado + ":" + valorMM.toFixed(4) + "mm"
      );
    }

    // Lee/setea --qx-page (la página/pasteboard a la que pertenece la caja: "1", "1*", "1**"…).
    function _pagina(style) {
      var m = (style || "").match(/--qx-page:([^;]+);/);
      return m ? m[1] : null;
    }
    function _setPagina(style, pag) {
      if (typeof style !== "string") return style;
      if (!/--qx-page:[^;]+;/.test(style)) return style;
      return style.replace(/--qx-page:[^;]+;/, "--qx-page:" + pag + ";");
    }

    // Rect renderizado (px) de una caja, para diagnóstico (mide lo que Quark muestra,
    // no sólo el atributo). getBoundingClientRect ya se usa en LeerMaqueta.js.
    function _rectStr(box) {
      try {
        var r = box.getBoundingClientRect();
        return "x=" + Math.round(r.left) + " y=" + Math.round(r.top) +
               " w=" + Math.round(r.width) + " h=" + Math.round(r.height);
      } catch (e) { return "(sin rect: " + e + ")"; }
    }

    // Redimensiona una caja fijando su tamaño en mm, manteniendo el borde
    // izquierdo/superior. ancho = right - left, alto = bottom - top. Ambas
    // dimensiones son opcionales: se aplica sólo la que venga (número > 0).
    function redimensionarCaja(boxName, anchoMM, altoMM) {
      try {
        var box = getPicBoxByName(boxName);
        if (!box) return;
        var style = box.getAttribute("style");
        if (!style) return;
        var left = _bordeMM(style, "left");
        var top  = _bordeMM(style, "top");
        if (anchoMM && left !== null) style = _setBordeMM(style, "right",  left + anchoMM);
        if (altoMM  && top  !== null) style = _setBordeMM(style, "bottom", top  + altoMM);
        box.setAttribute("style", style);
      } catch (e) { _geoDiag.push("redimensionarCaja ERROR [" + boxName + "]: " + e); }
    }

    // Mueve una caja a la posición (xMM, yMM) preservando su tamaño: recalcula
    // right/bottom con el ancho/alto actuales.
    function moverCaja(boxName, xMM, yMM) {
      if (xMM === null || yMM === null || typeof xMM === "undefined" || typeof yMM === "undefined") return;
      var box = getPicBoxByName(boxName);
      if (!box) return;
      var style = box.getAttribute("style");
      if (!style) return;
      var left   = _bordeMM(style, "left");
      var top    = _bordeMM(style, "top");
      var right  = _bordeMM(style, "right");
      var bottom = _bordeMM(style, "bottom");
      if (left === null || top === null || right === null || bottom === null) return;
      var w = right - left;
      var h = bottom - top;
      style = _setBordeMM(style, "left",   xMM);
      style = _setBordeMM(style, "top",    yMM);
      style = _setBordeMM(style, "right",  xMM + w);
      style = _setBordeMM(style, "bottom", yMM + h);
      box.setAttribute("style", style);
    }

    // Mueve un GRUPO completo (lista de box-name) de modo que la esquina sup-izq del
    // bounding-box del grupo quede en (xMM, yMM) — igual que el panel de medidas de Quark
    // con el grupo seleccionado. El DOM es plano y no expone grupos, así que se desplaza
    // cada caja miembro por el mismo delta. Preserva tamaños y posiciones relativas.
    function moverGrupo(boxNames, xMM, yMM, pagDestino) {
     try {
      pagDestino = pagDestino || "1";  // los recursos parkeados en 1*/1** van a la página 1
      var _tag = (boxNames && boxNames.length) ? boxNames.join(",") : "(vacío)";
      if (!boxNames || !boxNames.length) { _geoDiag.push("moverGrupo SKIP sin boxNames"); return; }
      if (xMM === null || yMM === null || typeof xMM === "undefined" || typeof yMM === "undefined") {
        _geoDiag.push("moverGrupo SKIP xMM/yMM inválidos [" + _tag + "] x=" + xMM + " y=" + yMM);
        return;
      }

      // 1) Recolectar cajas existentes y su geometría; calcular bbox del grupo.
      var miembros = [];
      var encontradas = [];
      var minLeft = null, minTop = null;
      for (var i = 0; i < boxNames.length; i++) {
        var box = getPicBoxByName(boxNames[i]);
        if (!box) continue;
        var style = box.getAttribute("style");
        if (!style) continue;
        var left = _bordeMM(style, "left");
        var top  = _bordeMM(style, "top");
        if (left === null || top === null) continue;
        miembros.push(box);
        encontradas.push(boxNames[i] + "(L=" + left + ",T=" + top + ")");
        if (minLeft === null || left < minLeft) minLeft = left;
        if (minTop  === null || top  < minTop)  minTop  = top;
      }
      if (!miembros.length || minLeft === null || minTop === null) {
        _geoDiag.push("moverGrupo SIN MIEMBROS [" + _tag + "] pedidas=" + boxNames.length);
        return;
      }

      // 2) Delta hasta el destino calibrado + compensación del marco del PASTEBOARD.
      //    Los recursos están parkeados en el pasteboard (1* izq / 1** der); Quark renderiza
      //    su posición con un offset constante respecto de la página. Medido empíricamente:
      //    pasteboard izquierdo (1*): X +194.733, Y +11.289. Derecho (1**): X -194.733 (a confirmar).
      //    El offset de render es GLOBAL (render_X = attr - COMP_X), no depende del lado del
      //    pasteboard: 1* y 1** usan la misma compensación.
      var _pgOrig = _pagina(miembros[0].getAttribute("style")) || "";
      var _cx = 0, _cy = 0;
      if (_pgOrig.indexOf("*") >= 0) { _cx = COMP_X; _cy = COMP_Y; } // cualquier pasteboard (1* o 1**)
      var xEfectivo = xMM + _cx;
      var yEfectivo = yMM + _cy;
      var dx = xEfectivo - minLeft;
      var dy = yEfectivo - minTop;
      _geoDiag.push("moverGrupo [" + boxNames[0] + "...] miembros=" + miembros.length +
                    "/" + boxNames.length + " pg=" + _pgOrig + " minLeft=" + minLeft + " minTop=" + minTop +
                    " xMM=" + xMM + "+CX(" + _cx + ")=" + xEfectivo.toFixed(3) +
                    " yMM=" + yMM + "+CY(" + _cy + ")=" + yEfectivo.toFixed(3) +
                    " dx=" + dx.toFixed(3) + " dy=" + dy.toFixed(3) +
                    "\n    " + encontradas.join(" "));
      // Rect RENDERIZADO de la 1ª caja ANTES de tocar nada (para ver si Quark aplica el cambio).
      var _pagAntes = _pagina(miembros[0].getAttribute("style"));
      var _rectAntes = _rectStr(miembros[0]);

      // 3) Desplazar los 4 bordes de cada miembro por el mismo delta Y fijar la página destino.
      //    Se escribe con los SETTERS de propiedad (box.style.qxLeft = "..mm"), que es la API
      //    documentada y pasa por el motor de estilo de Quark (re-layout que respeta el grupo).
      //    Fallback: reconstruir el atributo style si .style no está disponible.
      for (var m = 0; m < miembros.length; m++) {
        var stR = miembros[m].getAttribute("style");
        var l = _bordeMM(stR, "left"),  t = _bordeMM(stR, "top");
        var r = _bordeMM(stR, "right"), b = _bordeMM(stR, "bottom");
        try {
          if (l !== null) miembros[m].style.qxLeft   = (l + dx).toFixed(4) + "mm";
          if (r !== null) miembros[m].style.qxRight  = (r + dx).toFixed(4) + "mm";
          if (t !== null) miembros[m].style.qxTop    = (t + dy).toFixed(4) + "mm";
          if (b !== null) miembros[m].style.qxBottom = (b + dy).toFixed(4) + "mm";
          try { miembros[m].style.qxPage = pagDestino; } catch (eP) {}
        } catch (eStyle) {
          var st = stR;
          if (l !== null) st = _setBordeMM(st, "left",   l + dx);
          if (r !== null) st = _setBordeMM(st, "right",  r + dx);
          if (t !== null) st = _setBordeMM(st, "top",    t + dy);
          if (b !== null) st = _setBordeMM(st, "bottom", b + dy);
          st = _setPagina(st, pagDestino);
          miembros[m].setAttribute("style", st);
        }
      }

      // Verificación: releer la 1ª caja por atributo Y por .style para ver qué método "prendió".
      try {
        var chk = miembros[0].getAttribute("style");
        var viaStyle = "(sin .style)";
        try {
          viaStyle = "style.qxLeft=" + miembros[0].style.qxLeft +
                     " qxTop=" + miembros[0].style.qxTop +
                     " qxPage=" + miembros[0].style.qxPage;
        } catch (eR) {}
        _geoDiag.push("    page(attr): " + _pagAntes + " -> " + _pagina(chk) +
                      " | attr L=" + _bordeMM(chk, "left") + " T=" + _bordeMM(chk, "top") +
                      "\n    " + viaStyle +
                      "\n    rect antes: " + _rectAntes + " | rect desp: " + _rectStr(miembros[0]));
      } catch (eChk) {}
     } catch (eGrp) {
       _geoDiag.push("moverGrupo ERROR [" + (boxNames && boxNames[0]) + "]: " + eGrp);
     }
    }

    // Clona un grupo de recurso (ya lleno y posicionado en la plantilla 1) a otras plantillas
    // (páginas), agregando cajas nuevas. Las plantillas 2/3 NO tienen cajas de recurso propias;
    // el clon hereda la posición page-relative de la plantilla 1 y sólo cambia --qx-page.
    // Crea una caja NUEVA (via createElement, la vía que Quark reconoce) copiando los
    // atributos de `orig` (menos box-name), fijando la página, y clonando adentro sólo el
    // CONTENIDO (qx-story / qx-img). cloneNode del box entero no lo registra Quark.
    function crearCajaDesde(orig, pag, shiftX, shiftY) {
      // cloneNode(true) copia FIELMENTE contenido + estilos (alineación, fuente, formato).
      // Sólo hay que quitar los identificadores (box-id/uid los genera Quark; box-name debe ser
      // único) para que Quark no descarte el clon por ID duplicado.
      var nueva = orig.cloneNode(true);
      try { nueva.removeAttribute("box-id"); }   catch (e0) {}
      try { nueva.removeAttribute("box-uid"); }  catch (e1) {}
      try { nueva.removeAttribute("box-name"); } catch (e2) {}
      var st = nueva.getAttribute("style");
      if (st) {
        st = _setPagina(st, pag);
        // Des-compensar: el clon es una caja fresca en la página (no pasteboard), así que no
        // recibe el offset del pasteboard → se le resta lo que se le había sumado a la P1.
        if (shiftX) {
          var l = _bordeMM(st, "left"), r = _bordeMM(st, "right");
          if (l !== null) st = _setBordeMM(st, "left",  l + shiftX);
          if (r !== null) st = _setBordeMM(st, "right", r + shiftX);
        }
        if (shiftY) {
          var t = _bordeMM(st, "top"), b = _bordeMM(st, "bottom");
          if (t !== null) st = _setBordeMM(st, "top",    t + shiftY);
          if (b !== null) st = _setBordeMM(st, "bottom", b + shiftY);
        }
        nueva.setAttribute("style", st);
      }
      return nueva;
    }

    // Caja de referencia YA presente en cada plantilla (la foto), para tomar el spread destino.
    var REF_PLANTILLA = { "1": "Box369", "2": "Box505", "3": "Box1867" };

    function clonarRecursoAPaginas(boxNames, paginas) {
      if (!boxNames || !boxNames.length || !paginas || !paginas.length) return;
      // Recolectar las cajas del grupo y ordenarlas por ORDEN DE DOCUMENTO. Esto preserva el
      // z-order original (fondo atrás, texto adelante). Si se clonara en el orden del array,
      // el fondo (agregado último) quedaría al frente y taparía el texto.
      var origs = [];
      for (var g = 0; g < boxNames.length; g++) {
        var b = getPicBoxByName(boxNames[g]);
        if (b) origs.push(b);
      }
      origs.sort(function (a, b) {
        try {
          var pos = a.compareDocumentPosition(b);
          if (pos & 4) return -1;   // b sigue a a  → a primero (más atrás)
          if (pos & 2) return 1;    // b precede a a → b primero
        } catch (e) {}
        return 0;
      });
      for (var p = 0; p < paginas.length; p++) {
        var pag = paginas[p];
        var _diagHecho = false;
        // Spread destino: el de una caja que ya vive en esa plantilla (no el de la P1).
        var _ref = getPicBoxByName(REF_PLANTILLA[pag]);
        var _destino = (_ref && _ref.parentNode) ? _ref.parentNode : null;
        for (var i = 0; i < origs.length; i++) {
          var orig = origs[i];
          if (!orig) continue;
          var _bn = orig.getAttribute("box-name") || "(?)";
          try {
            // Des-compensar el pasteboard (la P1 tenía +COMP; el clon en página va sin él).
            var nueva = crearCajaDesde(orig, pag, -COMP_X, -COMP_Y);
            var destino = _destino || orig.parentNode || layout;
            destino.appendChild(nueva);
            _clonesAgregados++;
            // Diagnóstico de contenido por caja: ¿se copió el texto/imagen?
            var _oTxt = "", _cTxt = "";
            try { _oTxt = (orig.textContent || "").replace(/\s+/g, " ").substring(0, 30); } catch (e0) {}
            try { _cTxt = (nueva.textContent || "").replace(/\s+/g, " ").substring(0, 30); } catch (e1) {}
            var _oImg = orig.getElementsByTagName("qx-img").length;
            var _cImg = nueva.getElementsByTagName("qx-img").length;
            _geoDiag.push("  contenido [" + _bn + "] tipo=" +
                          (orig.getAttribute("box-content-type") || "?") +
                          " origTxt='" + _oTxt + "' clonTxt='" + _cTxt + "'" +
                          " origImg=" + _oImg + " clonImg=" + _cImg + " hijos=" + orig.childNodes.length);
            if (!_diagHecho) {
              var os = orig.getAttribute("style");
              var cs = nueva.getAttribute("style");
              var _mismoSpread = (destino === (orig.parentNode));
              _geoDiag.push("clon [" + _bn + "] -> pg=" + pag +
                            " origL=" + _bordeMM(os, "left") + " -> clonL=" + _bordeMM(cs, "left") +
                            " origT=" + _bordeMM(os, "top") + " -> clonT=" + _bordeMM(cs, "top") +
                            " spread_destino=" + (_ref ? REF_PLANTILLA[pag] : "(sin ref)") +
                            " mismoSpreadQueP1=" + _mismoSpread + " hijos=" + orig.childNodes.length);
              _diagHecho = true;
            }
          } catch (eC) {
            _geoDiag.push("clon ERROR [" + _bn + "] pg=" + pag + ": " + eC);
          }
        }
      }
    }


    function setImagenEnBox(boxName, filePath) {
      if (!filePath) return { ok: false, why: "path vacío", box: boxName };
      var box = getPicBoxByName(boxName);
      if (!box) { _faltantes.push(boxName); return { ok: false, why: "no existe box", box: boxName }; }
      var url  = toFileUrl(filePath);
      var imgs = box.getElementsByTagName("qx-img");
      if (imgs && imgs.length) {
        try {
          try { imgs[0].setAttribute("src", ""); } catch (e0) {}
          imgs[0].setAttribute("src", url);
          _hits++;
          return { ok: true, why: "", box: boxName, url: url };
        } catch (e) { return { ok: false, why: "error en qx-img.src: " + e, box: boxName }; }
      }
      try {
        try { box.setAttribute("src", ""); } catch (e1) {}
        box.setAttribute("src", url);
        _hits++;
        return { ok: true, why: "", box: boxName, url: url };
      } catch (e2) { return { ok: false, why: "error en box.src: " + e2, box: boxName }; }
    }

    // =========================================================
    // 🔹 LEER DATA
    // =========================================================
    var seccion      = "SIN SECCIÓN";
    var username     = "usuario";
    var fechaTexto   = "";
    var numeroPagina = 0;
    var avisos       = [];
    var fotos        = [];
    var tiene_texto  = false;
    var notas        = [];
    var maqueta_path = "";
    var geometria    = {};

    var _appdataScripts = "C:/Users/usuario/AppData/Roaming/ArmadorHuarpe/scripts/";
    var rutaJSON = "";
    try {
      var _cfg = JSON.parse(fs.readFileSync(_appdataScripts + "runtime_config.json", "utf8").trim());
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
        var data = JSON.parse(fs.readFileSync(rutaJSON, "utf8").trim());
        numeroPagina = parseInt(data.numero_pagina || 0);
        seccion      = (data.seccion    || "").trim();
        fechaTexto   = (data.fecha      || "").trim();
        username     = (data.usuario    || "usuario").trim();
        avisos       = data.avisos      || [];
        fotos        = data.fotos       || [];
        tiene_texto  = !!data.tiene_texto;
        notas        = data.notas       || [];
        maqueta_path = data.maqueta_path || "";
        geometria    = data.geometria   || {};
        try { _geoDiag.push("geometria recibida: " + JSON.stringify(geometria)); }
        catch (eG) { _geoDiag.push("geometria recibida (no serializable)"); }
        _geoDiag.push("rutaJSON=" + rutaJSON);
      }
    } catch (e) { alert("Error leyendo data_pagina.json: " + e); }

    // Separar nota principal y secundarias por rol
    var notaPrincipal    = null;
    var notasSecundarias = [];
    for (var _i = 0; _i < notas.length; _i++) {
      var _rol = (notas[_i].rol || notas[_i].tipo || "").toLowerCase();
      if (_rol === "principal" && !notaPrincipal) notaPrincipal = notas[_i];
      else notasSecundarias.push(notas[_i]);
    }

    // Extraer campos de la nota principal
    var volanta  = "";
    var titulo   = "";
    var bajada   = "";
    var firma    = "";
    var epigrafe = "";
    var cuerpo   = "";

    if (notaPrincipal) {
      volanta  = cleanHTML(notaPrincipal.volanta  || "");
      titulo   = cleanHTML(notaPrincipal.titulo   || "");
      bajada   = cleanHTML(notaPrincipal.bajada   || "");
      firma    = cleanHTML(notaPrincipal.firma    || "");
      epigrafe = cleanHTML(notaPrincipal.epigrafe || "");
      cuerpo   = cleanHTML(notaPrincipal.cuerpo   || "");
    } else if (notas.length === 0 && tiene_texto && fs.existsSync(rutaTXT)) {
      // Fallback a nota.txt (compatibilidad legacy)
      var raw    = fs.readFileSync(rutaTXT, "utf8");
      var partes = raw.replace(/\r\n?/g, "\n").trim().split("///")
                      .map(function (p) { return cleanHTML(p || "").trim(); });
      volanta  = partes[0] || "";
      titulo   = partes[1] || "";
      bajada   = partes[2] || "";
      firma    = partes[3] || "";
      epigrafe = partes[4] || "";
      cuerpo   = partes[5] || "";
    }

    var seccionNorm = normalizar(seccion);
    var firmaCorta  = firma.split("\n")[0].split(",")[0].trim();

    // =========================================================
    // 🔹 AVISOS
    // =========================================================
    function tienePie() {
      for (var i = 0; i < avisos.length; i++)
        if (normalizar(avisos[i].tipo || "") === "pie") return true;
      return false;
    }

    function pegarAvisosEnSeccion(snorm) {
      if (!avisos || avisos.length === 0) return;
      var conf    = AVISO_TARGETS[snorm] || AVISO_TARGETS["default"];
      var okCount = 0;
      var fails   = [];

      for (var i = 0; i < avisos.length; i++) {
        var a    = avisos[i] || {};
        var tipo = normalizar(a.tipo || "");
        var path = (a.path || "").trim();

        if (tipo === "doblemedia") {
          var dm = conf.doblemedia || AVISO_TARGETS["default"].doblemedia;
          var r1 = setImagenEnBox(dm.sup, path);
          if (r1.ok) okCount++; else fails.push(r1);
          var path2 = (a.path2 || "").trim();
          if (path2) {
            var r2 = setImagenEnBox(dm.inf, path2);
            if (r2.ok) okCount++; else fails.push(r2);
          }
        } else {
          var targets = (tipo === "completa") ? (conf.completa || []) : UNIVERSAL_AVISO;
          for (var j = 0; j < targets.length; j++) {
            var r = setImagenEnBox(targets[j], path);
            if (r.ok) okCount++; else fails.push(r);
          }
        }
      }

      if (fails.length > 0) {
        var msg = "AVISOS: OK=" + okCount + " FAIL=" + fails.length + "\n\n";
        for (var k = 0; k < Math.min(6, fails.length); k++)
          msg += "- " + fails[k].box + ": " + fails[k].why + "\n";
        alert(msg);
      }
    }

    // =========================================================
    // 🔹 FOTOS
    // =========================================================
    function pegarFotoPrincipal() {
      // Redimensionar la foto según la calibración (sólo si viene geometría de foto:
      // se emite cuando la nota es a 3 col / 3 ancha / 4 col). Delta sobre el borde
      // izquierdo/superior → no depende del origen de coordenadas.
      if (geometria.foto) {
        for (var g = 0; g < FOTO_BOXES.length; g++) {
          redimensionarCaja(FOTO_BOXES[g], geometria.foto.ancho_mm, geometria.foto.alto_mm);
        }
      }

      var foto = null;
      for (var i = 0; i < fotos.length; i++)
        if (fotos[i].rol === "principal") { foto = fotos[i]; break; }
      if (!foto) return;
      var path = (foto.path || "").trim();
      if (!path) return;
      _fotoPathTried = path;
      for (var b = 0; b < FOTO_BOXES.length; b++) {
        var r = setImagenEnBox(FOTO_BOXES[b], path);
        if (r && r.ok) _fotoBoxesOk++;
      }
    }

    function pegarFotosConPie() {
      var sorted = fotos.slice().sort(function (a, b) { return (a.orden || 0) - (b.orden || 0); });
      for (var i = 0; i < sorted.length && i < PIE_FOTO_BOXES.length; i++) {
        var path = (sorted[i].path || "").trim();
        if (path) setImagenEnBox(PIE_FOTO_BOXES[i], path);
      }
    }

    // =========================================================
    // 🔹 ESCRACHE AL BACHE (caso especial: maqueta dedicada)
    // =========================================================
    function pegarEscracheAlBache() {
      var sorted = fotos.slice().sort(function (a, b) { return (a.orden || 0) - (b.orden || 0); });
      if (sorted.length === 0) {
        alert("Escrache al Bache: no llegaron fotos en data.fotos.\n\n" +
              "Seleccioná las 2 fotos en el editor y pegá eligiendo 'Sí, pegar todo'.");
        return;
      }
      var IMG_BOXES = ["Box6357", "Box6429"];
      var EPI_BOXES = ["Box6599", "Box6604"];
      for (var i = 0; i < sorted.length && i < IMG_BOXES.length; i++) {
        var path = (sorted[i].path || "").trim();
        if (path) setImagenEnBox(IMG_BOXES[i], path);
        var epi = cleanHTML(sorted[i].epigrafe || "");
        if (epi)  setTextoEnBox(EPI_BOXES[i], epi);
      }
    }

    // =========================================================
    // 🔹 TEXTUALES / DATO / NÚMERO / QR
    // =========================================================
    function _extraerEntreComillas(s) {
      var out = [];
      if (!s) return out;
      var re = /\u201c([^\u201d]+)\u201d|"([^"]+)"/g;
      var m;
      while ((m = re.exec(s)) !== null) {
        var frase = (m[1] || m[2] || "").trim();
        if (frase) out.push(frase);
      }
      return out;
    }

    // Textuales dedicados de Café de la Política (siempre se ejecuta para esa sección)
    function pegarTextualesCafePolitica() {
      var auto = (notaPrincipal && notaPrincipal.textuales_auto) ? notaPrincipal.textuales_auto : [];
      var t1 = cleanHTML(auto[0] || "");
      var t2 = cleanHTML(auto[1] || "");
      if (!t1 || !t2) {
        var fuente = "";
        for (var k = 0; k < auto.length; k++) { if (auto[k]) fuente += " " + auto[k]; }
        var frases = _extraerEntreComillas(fuente);
        if (frases.length >= 2)       { t1 = cleanHTML(frases[0]); t2 = cleanHTML(frases[1]); }
        else if (frases.length === 1) { t1 = cleanHTML(frases[0]); }
      }
      var pie = tienePie();
      var BOXES_T1 = pie ? ["Box2086","Box2074","Box2080"] : ["Box2008","Box2017","Box2025"];
      var BOXES_T2 = pie ? ["Box2087","Box2075","Box2081"] : ["Box2009","Box2018","Box2026"];
      for (var i = 0; i < BOXES_T1.length; i++) { if (t1) setTextoEnBox(BOXES_T1[i], t1); }
      for (var j = 0; j < BOXES_T2.length; j++) { if (t2) setTextoEnBox(BOXES_T2[j], t2); }
    }

    // Textual estructurado, dato, número y QR (aplica a todas las secciones)
    function pegarTextualDatoNumero(nota) {
      var tx = nota.textual;
      if (tx && tx.tipo) {
        var t1    = cleanHTML(tx.texto1  || "");
        var t2    = cleanHTML(tx.texto2  || "");
        var t3    = cleanHTML(tx.texto3  || "");
        var cred1 = [cleanHTML(tx.nombre1 || ""), cleanHTML(tx.cargo1 || "")].filter(Boolean).join("\n");
        var cred2 = [cleanHTML(tx.nombre2 || ""), cleanHTML(tx.cargo2 || "")].filter(Boolean).join("\n");
        var cred3 = [cleanHTML(tx.nombre3 || ""), cleanHTML(tx.cargo3 || "")].filter(Boolean).join("\n");

        if (tx.tipo === "simple") {
          if (t1)    setTextoEnBox("Box427",  t1);
          if (cred1) setTextoEnBox("Box425",  cred1);
        } else if (tx.tipo === "x2") {
          if (t1)    setTextoEnBox("Box1053", t1);
          if (t2)    setTextoEnBox("Box1056", t2);
          if (cred1) setTextoEnBox("Box1054", cred1);
        } else if (tx.tipo === "x3") {
          if (t1)    setTextoEnBox("Box1166", t1);
          if (cred1) setTextoEnBox("Box1165", cred1);
          if (t2)    setTextoEnBox("Box1167", t2);
          if (cred2) setTextoEnBox("Box1164", cred2);
          if (t3)    setTextoEnBox("Box1169", t3);
          if (cred3) setTextoEnBox("Box1168", cred3);
        } else if (tx.tipo === "con_foto") {
          if (t1)      setTextoEnBox("Box1138",   t1);
          if (cred1)   setTextoEnBox("Box1137",   cred1);
          if (tx.foto) setImagenEnBox("Box1136",  tx.foto);
        } else if (tx.tipo === "con_foto_xl") {
          if (t1)      setTextoEnBox("Box417",    t1);
          if (cred1)   setTextoEnBox("Box416",    cred1);
          if (tx.foto) setImagenEnBox("Box415",   tx.foto);
        }
      }

      if (nota.dato) {
        if (typeof nota.dato === "string") {
          setTextoEnBox("Box1126", cleanHTML(nota.dato));
        } else {
          if (nota.dato.titulo) setTextoEnBox("Box1125", cleanHTML(nota.dato.titulo));
          if (nota.dato.texto)  setTextoEnBox("Box1126", cleanHTML(nota.dato.texto));
        }
      }

      var num = nota.numero;
      if (num) {
        if (num.cabecera) setTextoEnBox("Box1063", cleanHTML(num.cabecera));
        if (num.texto)    setTextoEnBox("Box1064", cleanHTML(num.texto));
      }

      if (nota.qr_path) setImagenEnBox("Box1657", nota.qr_path);

      // Reposicionar cada recurso activo (GRUPO completo) según la calibración (mm de
      // página). Python emite X/Y por rol; el grupo de cajas se resuelve en RECURSO_GRUPO.
      // Plantillas destino a clonar (además de la 1, donde se llena y posiciona el recurso).
      var PLANTILLAS_CLON = ["2", "3"];
      var recPos = geometria.recursos || {};
      if (recPos.textual && tx && tx.tipo) {
        var grpTx = RECURSO_GRUPO["textual_" + tx.tipo];
        if (grpTx) {
          moverGrupo(grpTx, recPos.textual.x_mm, recPos.textual.y_mm);
          clonarRecursoAPaginas(grpTx, PLANTILLAS_CLON);
        }
      }
      if (recPos.dato) {
        moverGrupo(RECURSO_GRUPO["dato"], recPos.dato.x_mm, recPos.dato.y_mm);
        clonarRecursoAPaginas(RECURSO_GRUPO["dato"], PLANTILLAS_CLON);
      }
      if (recPos.numero) {
        moverGrupo(RECURSO_GRUPO["numero"], recPos.numero.x_mm, recPos.numero.y_mm);
        clonarRecursoAPaginas(RECURSO_GRUPO["numero"], PLANTILLAS_CLON);
      }
      if (recPos.qr) {
        moverGrupo(RECURSO_GRUPO["qr"], recPos.qr.x_mm, recPos.qr.y_mm);
        clonarRecursoAPaginas(RECURSO_GRUPO["qr"], PLANTILLAS_CLON);
      }
    }

    // =========================================================
    // 🔹 PEGADO UNIVERSAL
    // =========================================================
    function pegarUniversal() {
      var folioTexto = numeroPagina + " | " + seccion.toUpperCase();

      // Nota principal en las 3 variantes de la maqueta
      UNIVERSAL.principal.forEach(function (m) {
        setTextoEnBox(m.numsec,  folioTexto);
        setFecha(m.fecha);
        setTextoEnBox(m.volanta, volanta);
        setTextoEnBox(m.titulo,  titulo);
        pegarCuerpo(m.cuerpo,   bajada, cuerpo);
      });

      // Firma y epígrafe
      setTextoEnBox(UNIVERSAL.firma,    firmaCorta);
      setTextoEnBox(UNIVERSAL.epigrafe, epigrafe);

      // Avisos
      pegarAvisosEnSeccion(seccionNorm);

      // Notas secundarias en ambas variantes
      for (var ni = 0; ni < notasSecundarias.length; ni++) {
        var notaN = notasSecundarias[ni];
        var vol_n = cleanHTML(notaN.volanta || "");
        var tit_n = cleanHTML(notaN.titulo  || "");
        var cue_n = cleanHTML(notaN.cuerpo  || "");
        UNIVERSAL.secundaria.forEach(function (s) {
          setTextoEnBox(s.volanta, vol_n);
          setTextoEnBox(s.titulo,  tit_n);
          pegarCuerpoSimple(s.cuerpo, cue_n);
        });
      }

      // Fotos (principal; con pie si hay aviso de pie)
      pegarFotoPrincipal();

      // Textuales / dato / número / QR
      if (notaPrincipal) pegarTextualDatoNumero(notaPrincipal);
    }

    // =========================================================
    // 🔹 DISPATCH
    // =========================================================
    if (seccionNorm === "escrache al bache") {
      // Maqueta especial: dos imágenes dedicadas + epígrafes propios.
      pegarEscracheAlBache();
    } else {
      // Todas las demás secciones usan la maqueta universal.
      pegarUniversal();
    }

    // Café de la Política: el texto/foto/aviso se pegan por la rama universal;
    // los textuales auto son un complemento dedicado que siempre se ejecuta.
    if (seccionNorm === "cafe de la politica") pegarTextualesCafePolitica();

    // =========================================================
    // 🔹 DIAGNÓSTICO
    // =========================================================
    if (_hits === 0) {
      var _uniq = _faltantes.filter(function (v, i) { return _faltantes.indexOf(v) === i; });
      alert("PegarNota: no se encontró ningún box para pegar.\n\nBox buscados sin éxito:\n" + _uniq.join(", "));
    }
    if (_hits > 0 && fotos && fotos.length > 0 && _fotoBoxesOk === 0 && _fotoPathTried) {
      alert("PegarNota: el texto se pegó pero la foto principal no entró en ninguna caja.\n\n" +
            "Foto: " + _fotoPathTried + "\n" +
            "Cajas probadas: " + FOTO_BOXES.join(", "));
    }

    // Estado del DOM EDITADO: usar el objeto `layout` ORIGINAL (el que editamos), no un
    // activeLayoutDOM() fresco (que devuelve un snapshot viejo, engañoso). Así el tally
    // refleja los clones agregados: total debería subir de 131 a 135 con 4 clones en pg=2.
    try {
      _geoDiag.push("\n=== DOM EDITADO (layout original) ===");
      var _all2 = layout.getElementsByTagName("qx-box");
      // Tally por página (los clones no tienen box-name; así vemos si aterrizaron en pg=2).
      var _porPag = {};
      var _cloneCount = 0;
      for (var _t = 0; _t < _all2.length; _t++) {
        var _st = _all2[_t].getAttribute("style");
        var _pp = _pagina(_st) || "?";
        _porPag[_pp] = (_porPag[_pp] || 0) + 1;
        if (!_all2[_t].getAttribute("box-name")) {   // sin box-name = clon creado por nosotros
          _cloneCount++;
          if (_cloneCount <= 6) {
            _geoDiag.push("  clon sin-nombre: page=" + _pp +
                          " tipo=" + (_all2[_t].getAttribute("box-content-type") || "?") +
                          " L=" + _bordeMM(_st, "left") + " T=" + _bordeMM(_st, "top"));
          }
        }
      }
      var _tallyStr = "total qx-box=" + _all2.length + " | clones sin-nombre=" + _cloneCount +
                      " | por página: ";
      for (var _k in _porPag) { if (_porPag.hasOwnProperty(_k)) _tallyStr += _k + "=" + _porPag[_k] + " "; }
      _geoDiag.push("  " + _tallyStr);
    } catch (eCom) { _geoDiag.push("estado comiteado ERROR: " + eCom); }

    // Diagnóstico de geometría → archivo (revisar cómo se movieron foto/recursos).
    try {
      var _diagTxt = "=== Geo diag " + new Date() + " ===\n" + _geoDiag.join("\n");
      fs.writeFileSync(_appdataScripts + "geo_diag.txt", _diagTxt, "utf8");
    } catch (eD) {}

    // Commit SOLO si se agregaron cajas nuevas (clones a plantillas 2/3). Las operaciones
    // DOM son asíncronas: el saveProject se difiere con Promise para que el appendChild se
    // aplique ANTES de guardar (el guardado síncrono corría antes de que el clon se registrara).
    if (_clonesAgregados > 0) {
      try {
        Promise.resolve().then(function () {
          try { app.activeProject().saveProject(); } catch (e2) {}
        });
      } catch (eP) {}
    }

  } catch (err) {
    alert("Error al pegar:\n" + err);
  }
})();

