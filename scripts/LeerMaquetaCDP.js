// =============================================================
//  LeerMaquetaCDP.js
//  QuarkXPress 2018 v14.x (QX.js) — lectura por CDP (returnByValue)
// -------------------------------------------------------------
//  A diferencia de LeerMaqueta.js (que escribe un archivo y avisa),
//  este script es una EXPRESIÓN que DEVUELVE el objeto con toda la
//  info de la maqueta, para que Python lo capture con
//  Runtime.evaluate({returnByValue:true}) — sin fs ni copiar a mano.
//
//  Por cada caja: nombre, tipo, geometría en mm (izq/arriba/der/abajo,
//  ancho/alto, página) y, para texto, la fuente/tamaño/interlineado/
//  alineación y la clase de estilo del primer párrafo. Además el
//  tamaño del lienzo (para maquetas vacías).
// =============================================================
(function () {
  function num(style, key) {
    var m = (style || "").match(new RegExp("--qx-" + key + ":(-?[0-9.]+)mm"));
    return m ? parseFloat(m[1]) : null;
  }
  function raw(style, key) {
    var m = (style || "").match(new RegExp("--qx-" + key + ":([^;]+);"));
    return m ? m[1].trim() : null;
  }
  function fontInfo(box) {
    // Busca el primer qx-p / qx-span con --qx-font-family en su style inline.
    var info = { font_family: null, font_size: null, leading: null,
                 text_align: null, style_class: null };
    var nodos = [];
    try { nodos = nodos.concat([].slice.call(box.getElementsByTagName("qx-p"))); } catch (e) {}
    try { nodos = nodos.concat([].slice.call(box.getElementsByTagName("qx-span"))); } catch (e) {}
    for (var i = 0; i < nodos.length; i++) {
      var st = "";
      try { st = nodos[i].getAttribute("style") || ""; } catch (e) { continue; }
      if (st.indexOf("--qx-font-family") >= 0) {
        info.font_family = raw(st, "font-family");
        var fs = raw(st, "font-size");
        info.font_size = fs ? parseFloat(fs) : null;
        var ld = raw(st, "leading");
        info.leading = ld ? parseFloat(ld) : null;
        info.text_align = raw(st, "text-align");
        try { info.style_class = nodos[i].getAttribute("class"); } catch (e) {}
        break;
      }
    }
    // Si no había font en spans, tomar la clase del primer qx-p igual (para roles).
    if (!info.style_class) {
      try {
        var p0 = box.getElementsByTagName("qx-p")[0];
        if (p0) info.style_class = p0.getAttribute("class");
      } catch (e) {}
    }
    return info;
  }

  var out = { ok: true, source: "", boxes: [], canvas: null, error: null };
  try {
    var layout = app.activeLayoutDOM();
    if (!layout) {
      // Fallback: intentar el layout del proyecto activo antes de rendirse.
      try {
        var proj = app.activeProject();
        if (proj && proj.projectID >= 0 && proj.activeLayout) {
          layout = (typeof proj.activeLayout.DOM === "function")
                   ? proj.activeLayout.DOM() : null;
        }
      } catch (e) {}
    }
    if (!layout) {
      out.ok = false;
      out.error = "No hay una maqueta activa en QuarkXPress. Abrí la maqueta (.qxp) y dejala como documento activo.";
      return out;
    }
    try { out.source = app.activeProject().getLocation().sourceFilePath || ""; } catch (e) {}
    try { if (!out.source) out.source = app.activeDocument.name || ""; } catch (e) {}

    var all = layout.getElementsByTagName("qx-box");
    for (var i = 0; i < all.length; i++) {
      var b = all[i];
      var name = null;
      try { name = b.getAttribute("box-name"); } catch (e) {}
      if (!name) continue;
      var style = "";
      try { style = b.getAttribute("style") || ""; } catch (e) {}
      var ctype = null;
      try { ctype = b.getAttribute("box-content-type"); } catch (e) {}

      var left = num(style, "left"), top = num(style, "top");
      var right = num(style, "right"), bottom = num(style, "bottom");
      var w = (left != null && right != null) ? (right - left) : null;
      var h = (top != null && bottom != null) ? (bottom - top) : null;

      var box = {
        name: name,
        type: ctype,
        left_mm: left, top_mm: top, right_mm: right, bottom_mm: bottom,
        width_mm: w, height_mm: h,
        page: raw(style, "page"),
        chars: 0
      };

      if (ctype === "text") {
        var story = null;
        try { story = b.getElementsByTagName("qx-story")[0]; } catch (e) {}
        try { box.chars = story ? (story.textContent || "").trim().length : 0; } catch (e) {}
        var fi = fontInfo(b);
        box.font_family = fi.font_family;
        box.font_size = fi.font_size;
        box.leading = fi.leading;
        box.text_align = fi.text_align;
        box.style_class = fi.style_class;
      }
      out.boxes.push(box);
    }

    // Tamaño del lienzo (página). Intentos varios; el que exista.
    try {
      var pageEl = layout.getElementsByTagName("qx-page")[0]
                || layout.querySelector("qx-page");
      if (pageEl) {
        var ps = pageEl.getAttribute("style") || "";
        out.canvas = {
          width_mm: num(ps, "page-width") || num(ps, "width"),
          height_mm: num(ps, "page-height") || num(ps, "height")
        };
      }
    } catch (e) {}
    if (!out.canvas) {
      try {
        var lay = app.activeLayout();
        out.canvas = { width_mm: lay.pageWidth || null, height_mm: lay.pageHeight || null };
      } catch (e) {}
    }
  } catch (err) {
    out.ok = false;
    out.error = String(err);
  }
  return out;
})();
