// ============================================================
//  Armador Huarpe — Chrome Extension  popup.js
//  Descarga materiales del manager a Downloads/armadorHuarpe/
//  El watcher Python los detecta y los copia a materiales/Pnn/
// ============================================================

// ── Secciones ────────────────────────────────────────────────

var FALLBACK_SECCIONES = ['Cultura','Deportes','Economía','Locales','Política','Policiales'];

function buildSeccionSelect(lista) {
  var sel = document.getElementById('seccion');
  sel.innerHTML = '<option value="">— Sin sección —</option>';
  lista.forEach(function(s) {
    var opt = document.createElement('option');
    opt.textContent = s;
    opt.value = s;
    sel.appendChild(opt);
  });
  var manual = document.createElement('option');
  manual.value = '__manual__';
  manual.textContent = 'Sección manual...';
  sel.appendChild(manual);
}

function loadSecciones() {
  chrome.downloads.search({ orderBy: ['-startTime'], limit: 50 }, function(items) {
    var match = null;
    for (var i = 0; i < items.length; i++) {
      if (items[i].filename && /armadorhuarpe/i.test(items[i].filename)) {
        match = items[i];
        break;
      }
    }
    if (match) {
      var normalized = match.filename.replace(/\\/g, '/');
      var m = normalized.match(/^(.+?armadorhuarpe\/)/i);
      if (!m) { usarCache(); return; }
      var url = 'file:///' + m[1].replace(/^\//, '') + 'secciones.json';
      fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(d) {
          var lista = d.secciones || FALLBACK_SECCIONES;
          chrome.storage.local.set({ secciones_cache: lista });
          buildSeccionSelect(lista);
        })
        .catch(usarCache);
    } else {
      usarCache();
    }
  });
}

function usarCache() {
  chrome.storage.local.get('secciones_cache', function(r) {
    buildSeccionSelect(r.secciones_cache || FALLBACK_SECCIONES);
  });
}

document.getElementById('seccion').addEventListener('change', function() {
  var manual = document.getElementById('seccionManual');
  if (this.value === '__manual__') {
    manual.classList.remove('hidden');
    manual.focus();
  } else {
    manual.classList.add('hidden');
    manual.value = '';
  }
});

loadSecciones();

// ── Sección por página (la define Python) ────────────────────
// Cuando el usuario coloca la página, autoselecciona la sección configurada en
// Python (paginas_secciones.json). Si la página no tiene sección, queda la
// elección manual del usuario.
function loadPaginaSeccion() {
  var pag = parseInt(document.getElementById('pagina').value, 10);
  if (!pag) return;
  chrome.downloads.search({ orderBy: ['-startTime'], limit: 50 }, function(items) {
    var match = null;
    for (var i = 0; i < items.length; i++) {
      if (items[i].filename && /armadorhuarpe/i.test(items[i].filename)) { match = items[i]; break; }
    }
    if (!match) return;
    var normalized = match.filename.replace(/\\/g, '/');
    var m = normalized.match(/^(.+?armadorhuarpe\/)/i);
    if (!m) return;
    var url = 'file:///' + m[1].replace(/^\//, '') + 'paginas_secciones.json';
    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var mapa = (d && d.paginas) || {};
        var sec = mapa[String(pag)];
        if (!sec) return;
        var sel = document.getElementById('seccion');
        var found = false;
        for (var i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value === sec) { sel.value = sec; found = true; break; }
        }
        if (!found) {
          var opt = document.createElement('option');
          opt.value = sec; opt.textContent = sec;
          sel.insertBefore(opt, sel.options[1] || null);
          sel.value = sec;
        }
        document.getElementById('seccionManual').classList.add('hidden');
      })
      .catch(function() {});
  });
}
document.getElementById('pagina').addEventListener('change', loadPaginaSeccion);
document.getElementById('pagina').addEventListener('input', loadPaginaSeccion);

// ── Toggle de rol (Principal / Secundaria / Otra) ────────────
Array.prototype.forEach.call(document.querySelectorAll('.role-btn'), function(btn) {
  btn.addEventListener('click', function() {
    Array.prototype.forEach.call(document.querySelectorAll('.role-btn'), function(b) {
      b.classList.remove('active');
    });
    btn.classList.add('active');
    var otra = document.getElementById('rolOtra');
    if (btn.getAttribute('data-rol') === 'otra') {
      otra.classList.remove('hidden');
      otra.focus();
    } else {
      otra.classList.add('hidden');
    }
  });
});

function getRol() {
  var active = document.querySelector('.role-btn.active');
  var rol = active ? active.getAttribute('data-rol') : 'principal';
  if (rol === 'otra') {
    var n = parseInt(document.getElementById('rolOtra').value, 10);
    if (!n || n < 3) n = 3;
    return 'noticia_' + n;
  }
  return rol;   // "principal" | "secundaria"
}

// ── UI helpers ───────────────────────────────────────────────

function setProgreso(msg, tipo) {
  var el = document.getElementById('progreso');
  el.textContent = msg;
  el.className = 'progreso' + (tipo ? ' ' + tipo : '');
  el.classList.remove('hidden');
}

function extractExt(url) {
  var base = (url || '').split('?')[0].split('#')[0];
  var m = base.match(/\.([a-zA-Z0-9]{2,4})$/);
  return m ? '.' + m[1].toLowerCase() : '.jpg';
}

// ── Download helpers ─────────────────────────────────────────

function downloadUrlAndWait(url, filename) {
  return new Promise(function(resolve, reject) {
    chrome.downloads.download(
      { url: url, filename: filename, conflictAction: 'overwrite', saveAs: false },
      function(id) {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        function listener(delta) {
          if (delta.id !== id || !delta.state) return;
          if (delta.state.current === 'complete') {
            chrome.downloads.onChanged.removeListener(listener);
            resolve();
          } else if (delta.state.current === 'interrupted') {
            chrome.downloads.onChanged.removeListener(listener);
            reject(new Error('Download interrupted: ' + filename));
          }
        }
        chrome.downloads.onChanged.addListener(listener);
      }
    );
  });
}

function downloadBlob(content, filename, type) {
  var blob = new Blob([content], { type: type });
  var url = URL.createObjectURL(blob);
  return downloadUrlAndWait(url, filename).finally(function() {
    URL.revokeObjectURL(url);
  });
}

function downloadImage(imageUrl, filename) {
  // Usar chrome.downloads directamente evita restricciones CORS del fetch
  // y preserva las cookies de sesión del navegador para el CDN
  return downloadUrlAndWait(imageUrl, filename);
}

// ── Extracción de datos (se serializa y ejecuta en la pestaña) ──
// IMPORTANTE: Esta función se ejecuta en el contexto de la página del manager.
// No puede referenciar variables externas del popup.
// Todos los helpers deben estar definidos dentro de ella.

function extractNoteData() {

  function decodeHTML(str) {
    if (!str) return '';
    var tmp = document.createElement('textarea');
    tmp.innerHTML = str;
    return tmp.value.replace(/ /g, ' ').trim();
  }

  function stripTags(str) {
    return (str || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }

  // Transliteración 1:1 de _render_body_and_qr_links (manager_scraper.py:310)
  function htmlToCuerpo(html) {
    var tmp = document.createElement('div');
    tmp.innerHTML = html;

    var HEADER_TAGS = {H1:1, H2:1, H3:1, H4:1, H5:1, H6:1};
    var BLOCK_TAGS  = {P:1, LI:1, BLOCKQUOTE:1, DIV:1};
    var SOCIAL_RE   = /instagram\.com|youtu\.be|youtube\.com/i;
    var tokens        = [];
    var qrLinks       = [];
    var textualesAuto = [];

    function cleanText(s) {
      if (!s) return '';
      s = s.replace(/ /g, ' ');
      s = s.replace(/[ \t]+/g, ' ');
      return s.trim();
    }

    function normalizeHttp(u) {
      u = (u || '').trim();
      if (!u || u.indexOf('http') !== 0) return '';
      u = u.replace(/^https?:\/\/manager\.diariohuarpe\.com\/(https?:\/\/)/, '$1');
      return u;
    }

    function maybeAddQr(url) {
      var u = normalizeHttp(url);
      if (u && SOCIAL_RE.test(u)) qrLinks.push(u);
    }

    function iframeAnySrc(el) {
      var v = (el.getAttribute('src') || '').trim();
      if (v && v.indexOf('http') === 0) return v;
      var attrs = ['data-src', 'data-original', 'data-lazy-src', 'data-url', 'data-href'];
      for (var i = 0; i < attrs.length; i++) {
        v = (el.getAttribute(attrs[i]) || '').trim();
        if (v) return v;
      }
      return '';
    }

    function scanNestedMedia(container) {
      var iframes = container.querySelectorAll('iframe');
      for (var i = 0; i < iframes.length; i++) {
        var src = (iframes[i].getAttribute('src') || '').trim() || iframeAnySrc(iframes[i]);
        if (src) maybeAddQr(src);
      }
      var anchors = container.querySelectorAll('a[href]');
      for (var i = 0; i < anchors.length; i++) {
        maybeAddQr((anchors[i].getAttribute('href') || '').trim());
      }
    }

    function walk(node) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var el = node.childNodes[i];
        if (el.nodeType !== 1) continue;
        var tag = el.tagName;

        if (tag === 'IFRAME') {
          var src = (el.getAttribute('src') || '').trim() || iframeAnySrc(el);
          if (src) maybeAddQr(src);

        } else if (HEADER_TAGS[tag]) {
          var t = cleanText(el.textContent);
          if (t) tokens.push({kind: 'h', text: t});

        } else if (BLOCK_TAGS[tag]) {
          var t = cleanText(el.textContent);
          if (t) {
            tokens.push({kind: 'p', text: t});
            if (tag === 'BLOCKQUOTE') textualesAuto.push(t);
          }
          scanNestedMedia(el);
          if (tag === 'BLOCKQUOTE') {
            var perma = (el.getAttribute('data-instgrm-permalink') || '').trim();
            if (perma) maybeAddQr(perma);
          }

        } else {
          walk(el);
        }
      }
    }

    walk(tmp);

    var seenQr = {};
    var uniqQr = [];
    for (var i = 0; i < qrLinks.length; i++) {
      if (qrLinks[i] && !seenQr[qrLinks[i]]) {
        seenQr[qrLinks[i]] = 1;
        uniqQr.push(qrLinks[i]);
      }
    }

    var body;
    if (!tokens.length) {
      body = cleanText(tmp.textContent);
    } else {
      var parts = [];
      for (var i = 0; i < tokens.length; i++) {
        parts.push(tokens[i].kind === 'h' ? '## ' + tokens[i].text : tokens[i].text);
      }
      body = parts.join('\n\n');
    }

    if (uniqQr.length) {
      body += '\n\n' + uniqQr.map(function(u) { return 'Link para el QR: ' + u; }).join('\n');
    }

    return { body: body, textualesAuto: textualesAuto };
  }

  // Volanta
  var volanta = decodeHTML(
    (document.querySelector('#volanta') || {}).value || ''
  );

  // Título — preferir edición impresa
  var titulo = decodeHTML(
    (document.querySelector('#tituloEdicionImpresa') || {}).value ||
    (document.querySelector('#tituloNota') || {}).value || ''
  );

  // Bajada (intro)
  var introEl = document.querySelector('#introHTML');
  var bajada = introEl ? decodeHTML(stripTags(introEl.value)) : '';

  // Firma — items visibles del multi-select
  var firma = '';
  var firmaCtn = document.getElementById('firmanteInput');
  if (firmaCtn) {
    var visibles = Array.from(firmaCtn.querySelectorAll('.ms-sel-item'))
      .map(function(el) { return el.textContent.replace(/\s*×?\s*$/, '').trim(); })
      .filter(Boolean);
    if (visibles.length) {
      firma = visibles.join(', ');
    } else {
      var hiddens = Array.from(firmaCtn.querySelectorAll('input[name="firmante[]"]'))
        .map(function(i) { return (i.value || '').trim(); })
        .filter(Boolean);
      firma = hiddens.join(', ');
    }
  }

  // Epígrafe — preferir CKEditor del campo, luego data-plain, luego value
  var epigrafe = '';
  var epigEl = document.querySelector('#imagenTapaDesc');
  if (epigEl) {
    var epigIframe = document.querySelector('#cke_imagenTapaDesc iframe');
    if (epigIframe) {
      var epigDoc = epigIframe.contentDocument || (epigIframe.contentWindow && epigIframe.contentWindow.document);
      if (epigDoc) {
        epigrafe = decodeHTML((epigDoc.body.innerText || ''));
      }
    }
    if (!epigrafe) {
      epigrafe = decodeHTML(epigEl.getAttribute('data-plain') || epigEl.value || '');
    }
  }
  if (!epigrafe) epigrafe = 'NO HAY EPIGRAFE';

  // Cuerpo — desde CKEditor (lógica del scraper Selenium)
  var cuerpo = '';
  var textualesAuto = [];
  var _ckeDoc = null;
  try {
    var ckeIframe = document.querySelector('#cke_textoHTML iframe');
    if (ckeIframe) {
      _ckeDoc = ckeIframe.contentDocument || (ckeIframe.contentWindow && ckeIframe.contentWindow.document);
      if (_ckeDoc) {
        var cuerpoResult = htmlToCuerpo(_ckeDoc.body.innerHTML || '');
        cuerpo = cuerpoResult.body;
        textualesAuto = cuerpoResult.textualesAuto;
      }
    }
  } catch (e) {}
  if (!cuerpo) {
    var txArea = document.querySelector('#textoHTML');
    if (txArea) cuerpo = decodeHTML(stripTags(txArea.value));
  }

  // QR links — el plugin showprotected de CKEditor convierte los <iframe> de YouTube
  // en spans con base64, así que _ckeDoc.body.innerHTML NO tiene las URLs visibles.
  // #textoHTML.value tiene el HTML crudo original con src="https://youtube.com/..."
  // como texto literal que el regex sí puede encontrar.
  var _qrDebug = { source: '', qrLinks: [], error: '' };
  try {
    var SOCIAL_URL_RE = /(?:https?:)?\/\/[^\s"'<>&]*(?:youtube\.com|youtu\.be|instagram\.com\/)[^\s"'<>&]*/gi;
    var qrSeen = {};
    var qrLinks = [];

    function addQrMatches(html) {
      (html.match(SOCIAL_URL_RE) || []).forEach(function(u) {
        if (u.indexOf('//') === 0) u = 'https:' + u;
        u = u.replace(/[&"'<>].*$/, '').trim();
        if (u && !qrSeen[u]) { qrSeen[u] = 1; qrLinks.push(u); }
      });
    }

    // Fuente principal: #textoHTML.value — HTML crudo sin transformaciones de CKEditor
    var txEl2 = document.querySelector('#textoHTML');
    if (txEl2 && txEl2.value) {
      _qrDebug.source = 'textoHTML.value (' + txEl2.value.length + ' chars)';
      addQrMatches(txEl2.value);
    } else if (_ckeDoc && _ckeDoc.body) {
      // Fallback: CKEditor body innerHTML
      _qrDebug.source = 'ckeDoc.innerHTML';
      addQrMatches(_ckeDoc.body.innerHTML || '');
    }

    // También #urlvideo (campo Multimedia, independiente del cuerpo)
    var uvEl = document.querySelector('#urlvideo');
    if (uvEl) {
      var uvVal = (uvEl.getAttribute('value') || uvEl.value || uvEl.textContent || '').trim();
      if (uvVal && /youtube\.com|youtu\.be|instagram\.com/i.test(uvVal) && !qrSeen[uvVal]) {
        qrSeen[uvVal] = 1; qrLinks.push(uvVal);
      }
    }

    _qrDebug.qrLinks = qrLinks;
    if (qrLinks.length && cuerpo.indexOf('Link para el QR:') === -1) {
      cuerpo = (cuerpo ? cuerpo + '\n\n' : '') +
        qrLinks.map(function(u) { return 'Link para el QR: ' + u; }).join('\n');
    }
  } catch (e) { _qrDebug.error = String(e); }

  // Imágenes de la galería
  var imagenes = [];
  var rows = Array.from(document.querySelectorAll('tbody.listado_container tr'));
  rows.forEach(function(tr, idx) {
    var urlLabel = tr.querySelector('td label');
    var url = urlLabel ? urlLabel.textContent.trim() : '';
    if (!url || url.indexOf('http') !== 0) return;

    var tieneHome = rows.some(function(r) {
      return !!r.querySelector('input[name="imagen_home"]:checked');
    });
    var esPrincipal = !!(
      tr.querySelector('input[name="imagen_home"]:checked') ||
      (!tieneHome && idx === 0 && imagenes.length === 0)
    );
    var epigrafeImg = (tr.querySelector('input[name="epigrafe_galeria"]') || {}).value || '';
    var nombreBase = url.split('/').pop().split('?')[0].replace(/\.[^.]+$/, '');

    imagenes.push({ url: url, principal: esPrincipal, epigrafe: epigrafeImg, nombre: nombreBase });
  });

  // Garantizar al menos una imagen principal
  if (imagenes.length > 0 && !imagenes.some(function(i) { return i.principal; })) {
    imagenes[0].principal = true;
  }

  // Estado de publicación
  var estadoPub = 'NP';
  var estadoEl = document.querySelector('#estado_pub_nota, .estado_pub_nota, [id*="estado_pub"]');
  if (estadoEl) {
    var et = estadoEl.textContent.trim().toUpperCase();
    if (et === 'P' || et.includes('PUBLICAD')) estadoPub = 'P';
  }

  return { volanta: volanta, titulo: titulo, bajada: bajada, firma: firma,
           epigrafe: epigrafe, cuerpo: cuerpo, imagenes: imagenes,
           textualesAuto: textualesAuto, estadoPub: estadoPub,
           _qrDebug: _qrDebug };
}

// ── Handler del botón Descargar ──────────────────────────────

document.getElementById('descargarBtn').addEventListener('click', async function() {
  var paginaVal = parseInt(document.getElementById('pagina').value);
  var seccionRaw = document.getElementById('seccion').value;
  var seccion = seccionRaw === '__manual__'
    ? document.getElementById('seccionManual').value.trim()
    : seccionRaw.trim();
  var btn = document.getElementById('descargarBtn');

  if (!paginaVal || paginaVal < 1 || paginaVal > 16) {
    setProgreso('Ingresá un número de página válido (1–16)', 'error');
    return;
  }

  if (!seccion) {
    setProgreso('Seleccioná o escribí una sección antes de descargar', 'error');
    return;
  }

  btn.disabled = true;
  setProgreso('Extrayendo datos de la nota...');

  try {
    var tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    var tab = tabs[0];

    if (!tab || !tab.url || tab.url.indexOf('diariohuarpe.com') === -1) {
      setProgreso('Abrí una nota del manager de Diario Huarpe primero', 'error');
      btn.disabled = false;
      return;
    }

    // Inyectar extractNoteData en la pestaña activa
    var injected = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractNoteData,
    });

    var result = injected[0] && injected[0].result;
    if (!result) {
      setProgreso('No se pudo extraer datos de la nota', 'error');
      btn.disabled = false;
      return;
    }

    setProgreso('Preparando descarga...');

    // Carpeta destino: armadorHuarpe/YYYYMMDDHHMMSS_PNN/
    var now = new Date();
    var ts = now.toISOString().replace(/[^0-9]/g, '').slice(0, 14);
    var nnPag = String(paginaVal).padStart(2, '0');
    var folder = 'armadorHuarpe/' + ts + '_P' + nnPag;

    var rol = getRol();   // "principal" | "secundaria" | "noticia_N"

    // nota.txt: 6 campos con " /// "
    var txtContent = [
      result.volanta, result.titulo, result.bajada,
      result.firma, result.epigrafe, result.cuerpo
    ].join(' /// ');

    // nota.json: estructura igual al scraper Python
    var notaJson = {
      version: 1,
      tipo: rol,
      rol: rol,
      seccion: seccion,
      link: tab.url,
      estado_pub: result.estadoPub || 'NP',
      volanta: result.volanta,
      titulo: result.titulo,
      bajada: result.bajada,
      firma: result.firma,
      epigrafe: result.epigrafe,
      cuerpo: result.cuerpo,
      textuales_auto: result.textualesAuto || [],
      imagenes: result.imagenes.map(function(img, i) {
        return {
          archivo: (img.principal ? 'principal_' : '') + img.nombre + extractExt(img.url),
          url_origen: img.url,
          epigrafe: img.epigrafe,
          orden: i + 1,
          es_principal: img.principal,
        };
      }),
      _debug_qr: result._qrDebug || null,
    };

    // Descargar archivos en paralelo (excepto _pending.json)
    var archivos = [];
    var tasks = [];

    tasks.push(
      downloadBlob(txtContent, folder + '/nota.txt', 'text/plain; charset=utf-8')
        .then(function() { archivos.push('nota.txt'); })
    );

    tasks.push(
      downloadBlob(JSON.stringify(notaJson, null, 2), folder + '/nota.json', 'application/json')
        .then(function() { archivos.push('nota.json'); })
    );

    result.imagenes.forEach(function(img) {
      var ext = extractExt(img.url);
      var nombre = (img.principal ? 'principal_' : '') + img.nombre + ext;
      tasks.push(
        downloadImage(img.url, folder + '/' + nombre)
          .then(function() { archivos.push(nombre); })
          .catch(function(err) {
            console.warn('Imagen no descargada:', img.url, err.message);
            // Imagen fallida no bloquea la descarga del resto
          })
      );
    });

    setProgreso('Descargando ' + tasks.length + ' archivos...');
    await Promise.all(tasks);

    // _pending.json se escribe AL FINAL — es la señal para el watcher Python
    var pending = {
      pagina: paginaVal,
      seccion: seccion,
      rol: rol,
      copiado: false,
      ts: now.toISOString(),
      archivos: archivos,
      link: tab.url,
    };

    await downloadBlob(
      JSON.stringify(pending, null, 2),
      folder + '/_pending.json',
      'application/json'
    );

    setProgreso(
      'Página ' + paginaVal + ' descargada\n' +
      archivos.length + ' archivos → ' + folder + '/',
      'ok'
    );

  } catch (err) {
    console.error('Error en descarga:', err);
    setProgreso('Error: ' + err.message, 'error');
  }

  btn.disabled = false;
});
