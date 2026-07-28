# Maquetador interno — arquitectura y roadmap

Documento de diseño del "maquetador" de ArmadorHuarpe: leer maquetas reales desde
QuarkXPress (con o sin recursos), derivar los límites de cada campo **sin rellenar
a mano**, y exponer un **modelo manipulable de recursos** (posición, tamaño,
cantidad) que se vuelca de vuelta a Quark.

Contexto: los límites de campo se calibraban **a mano** en `config.ini`
(`LeerMaqueta.js` no dio resultados usables). Se aprovecha el canal CDP
(QuarkXPress expone Chrome DevTools en el puerto 8087) para leer geometría real.

## Restricción de diseño confirmada (condiciona todo lo que sigue)

Investigación técnica confirmó que **QX.js no puede crear cajas desde la nada**
— no existe una API de "content creation" nativa (`newBox`/`addBox`/`insertBox`).
La única vía de creación válida y probada en producción es **clonar una caja
YA EXISTENTE** (`orig.cloneNode(true)` + quitar `box-id`/`box-uid` generados por
Quark + reposicionar + `appendChild`), con la limitación aceptada de que el
formato de párrafo (alineación/itálica) no siempre se hereda en clones de texto
(ver `scripts/PegarNota v6.js:635-670`, función `crearCajaDesde`).

**Decisión de producto (confirmada):** el maquetador **no inventa cajas**. Sigue
trabajando con las plantillas que YA existen en cada maqueta — solo **modifica o
clona** lo que ya está (mover, redimensionar, clonar para poner más instancias de
un recurso, eliminar). Fuente, tamaño de letra y diseño gráfico quedan del lado de
Quark; **Python solo asiste con cantidad de caracteres y con posición/tamaño/
cantidad de recursos**.

Los otros primitivos confirmados y en uso en producción:
- **Eliminar**: `box.parentNode.removeChild(box)`.
- **Mover/redimensionar**: reescribir `--qx-left/top/right/bottom` en mm (o los
  setters `box.style.qxLeft` etc., patrón preferido — "pasa por el motor de
  estilo de Quark").
- Los **grupos (Ctrl+G) no existen en el DOM** (plano) — mover un grupo requiere
  mover cada caja miembro por el mismo delta.

## Renombrado de cajas: NO existe in-place (corrección jul 2026)

Se creía que `setAttribute('box-name', ...)` sobre una caja cualquiera era un
primitivo confirmado en producción (junto con eliminar y mover/redimensionar).
**Es incorrecto.** Confirmado en vivo con `scripts/nombrador.js` (ejecución
manual, diálogo real, caja suelta no agrupada): tipear un nombre nuevo y
aceptar el diálogo **no cambiaba el nombre de la caja**.

**Causa raíz:** comparando contra `crearCajaDesde` en `scripts/PegarNota v6.js:641-651`
(que sí funciona), la diferencia es el momento en que se fija el nombre:

```js
// SÍ funciona — el nombre se fija ANTES de insertar el nodo en el árbol:
var nueva = orig.cloneNode(true);
nueva.setAttribute("box-name", nuevoNombre);
...
destino.appendChild(nueva);

// NO funciona — la caja ya está insertada, mutar el atributo después no se
// propaga al modelo interno de Quark:
box.setAttribute('box-name', nombre);   // box ya existía en el documento
```

**Quark solo "registra" el `box-name` en el instante de `appendChild`.** Por
eso NO hay primitivo de renombrado in-place. Renombrar una caja EXISTENTE se
implementa como **clonar-con-el-nombre-nuevo (en la misma posición/página) +
eliminar el original** — reusa únicamente los primitivos que sí funcionan.
Implementado en `scripts/AplicarModeloRecursos.js` (función interna
`clonarConNombre`, compartida por las operaciones `clonar` y `renombrar`) y en
`scripts/nombrador.js` (uso manual, un nombre por caja si hay selección
múltiple).

El flujo del maquetador (`model/recurso_plan.py::calcular_diferencias` →
operación `clonar` para recursos nuevos) ya seguía el patrón correcto (fija el
nombre antes de insertar) — no necesitó cambios.

## El problema de las "claves" (resuelto para el nuevo modelo — F1.5)

Antes de este ciclo convivían **4 mapas de nombres de caja hardcodeados y
desconectados**, sin una clave semántica común:
1. `scripts/maqueta_roles.json` (límites de caracteres, por sección).
2. `UNIVERSAL`/`AVISO_TARGETS`/rutinas por sección en `scripts/PegarNota_JSON.js`
   (dónde pegar texto).
3. El switch de textual/dato/número (otro mapa aparte, en el mismo JS).
4. `config.ini [MAQUETA:<nombre>]` (calibración numérica por archivo).

Cada maqueta nueva exigía editar los 4 a mano; los fallos eran silenciosos
(caían a defaults sin avisar). **Este ciclo NO migra los mapas 2-4** (arriesgaría
el pegado que funciona en producción) — construye un **manifest semántico nuevo**
(`services/maqueta_manifest.py`) que reemplaza la necesidad de esos mapas
específicamente para el **modelo de recursos** del maquetador, usando
`maqueta_roles.json` como referencia de solo lectura + `config.maqueta_config_for()`
para la foto principal.

## Cómo se lee una maqueta (F1 — implementado)

- **JS** `scripts/LeerMaquetaCDP.js`: expresión que **devuelve** un objeto
  (`Runtime.evaluate({returnByValue:true})`, sin `fs`/`alert`). Por cada `qx-box`
  con nombre: geometría en mm (`--qx-left/top/right/bottom`), `box-content-type`,
  y para texto `font_family`/`font_size`/`leading`/`text_align`/clase de estilo.
  Guard: si `activeLayoutDOM()` es `null` (sin maqueta activa), devuelve
  `{ok:false, error:"..."}` en vez de `TypeError`.
- **Python** `services/maqueta_introspect.py`:
  - `leer_maqueta_cdp()` — lectura puntual de la maqueta activa.
  - `actualizar_maqueta_abierta()` — la cachea (caso: el user la modificó y la
    tiene abierta).
  - `leer_todas_las_maquetas(progress, cancel)` — trabajo previo: abre/lee/cierra
    cada `.qxp` de la carpeta de maquetas automáticamente (usa
    `quark_auto.lanzar_quark_sin_robar_foco` + `quark_cdp.esperar_proyecto_listo` +
    `scripts/CerrarProyecto.js`), cachea todas en `maquetas_cache.json`
    (`Config.RUNTIME_SCRIPTS_DIR`). Herramienta en la ventana principal:
    **Maquetas → Leer maquetas (capacidades)…** (`ui/maquetas_reader_dialog.py`).

## Cómo se estiman los límites SIN rellenar (F1 — implementado y calibrado)

Fórmula geométrica en `services/maqueta_introspect.estimar_capacidad()`:

```
em_mm          = font_size_pt * 25.4/72
avg_char_mm    = (averageCharWidth/em, por familia) * em_mm
line_h_mm      = leading_pt*25.4/72  ó  (height/em)*em_mm
chars_por_lin  = floor((width_mm  - 2*inset) / avg_char_mm)
lineas         = floor((height_mm - 2*inset) / line_h_mm)
capacidad      = chars_por_lin * lineas * factor_calibracion
```

- **Fuente por clase, auto-aprendida entre maquetas.** Las cajas vacías (sin
  placeholder) no traen `--qx-font-size` inline, solo la clase de párrafo
  (`pr-A-%20VOLANTA`). `_aprender_fuentes_por_clase()` agrega, de TODA la caché,
  la fuente/tamaño/interlineado más frecuente por clase normalizada
  (`_normalizar_clase`: unquote + sin prefijo `pr-`/`ch-` + sin acentos +
  minúsculas), con un **umbral de confianza** (`_MIN_MUESTRAS`, `_MIN_ACUERDO`)
  para no aplicar un valor cuando las muestras son demasiado dispersas. Las
  clases GENÉRICAS de Quark (`Normal`, `No Style`) se excluyen del aprendizaje
  — se reusan para roles muy distintos entre sí y su "moda" no es un predictor
  confiable (se detectó en producción: aplicarla daba capacidades absurdas,
  ej. 2 caracteres, para un epígrafe real). Override editable en
  `scripts/estilos_fuente.json` para clases que nunca aparecen inline en
  ninguna maqueta.
- **`recalcular_capacidades_cache()`** — segunda pasada que recalcula TODAS las
  entradas cacheadas con el aprendizaje agregado completo (una maqueta leída al
  principio del batch se beneficia de clases aprendidas en una leída después).
  Se llama al final de `leer_todas_las_maquetas()` y tras
  `actualizar_maqueta_abierta()`.
- **Límites por rol desacoplados** — `services/maqueta_reader_service.
  map_to_editor_limits()` resuelve volanta/cuerpo/epígrafe cada uno de forma
  independiente contra las "variantes" de `maqueta_roles.json` (antes: si la
  volanta de una variante no tenía capacidad, se descartaba también el cuerpo
  de esa misma variante aunque sí la tuviera).
- **Lienzo (canvas)** — si el JS no logra leerlo, `_resolver_canvas()` lo deriva
  por **bounding box** de las cajas realmente en página (excluye las parqueadas
  en el pasteboard, `page` con sufijo `*`), marcado `aproximado: true`.
- **Factor de calibración recalibrado con datos reales**: `DEFAULT_FACTOR = 1.28`
  (antes 0.98), derivado con `calibrar_factor()` contra 45 maquetas de
  producción (mediana 1.286, desvío 0.064) — la fórmula geométrica cruda
  subestimaba la capacidad real en ~27%. Re-derivar si se agregan muchas
  maquetas nuevas.
- El editor consume todo esto vía `EditorNotaWindow._merge_cache_limits()` →
  `maqueta_reader_service.limits_from_cache()`.

## Manifest semántico de recursos (F1.5 — implementado)

`services/maqueta_manifest.py::construir_manifest(data, stem)` clasifica cada
caja de texto/foto en un **rol editorial** con un **id semántico y estable**
(`cuerpo`, `foto_principal`, `foto_secundaria_2`...) — no depende de que el
nombre de caja de Quark no cambie; el `box_name` es un puntero que se
re-resuelve en cada lectura. Cajas sin rol conocido quedan igual en el manifest
(`rol: null`) — nunca se descartan en silencio.

**Limitación conocida y documentada:** un mismo `.qxp` suele contener varias
"páginas" internas que son VARIANTES alternativas del mismo rol para distintos
escenarios editoriales (layout de 1 noticia vs 2 noticias), no recursos
simultáneos. `recursos_de_pagina(manifest, page)` / `paginas_disponibles(manifest)`
permiten acotar el manifest a UN escenario concreto antes de planificar sobre él.

## Director de diferencias — solo recursos, no texto (F2 — implementado, spike pendiente de validar en vivo)

`model/recurso_plan.py`:
- `RecursoObjetivo(id, rol, left_mm, top_mm, width_mm, height_mm, page)` — estado
  DESEADO de un recurso.
- `calcular_diferencias(manifest, objetivos, eliminar_ids)` → `PlanDiferencias`
  (operaciones + errores). Reglas:
  - Si el `id` objetivo ya existe → `mover`/`redimensionar` si cambió más que
    la tolerancia (0.05mm).
  - Si no existe → busca `clonable_desde` del mismo rol en el manifest; si no
    hay ninguna caja de ese rol para clonar, **reporta error** (nunca inventa
    una operación imposible).
  - **Borrado SIEMPRE explícito** vía `eliminar_ids` — un recurso que
    simplemente no está en `objetivos` NO se borra (decisión de seguridad:
    omitir un rol no debe destruirlo en Quark).
- `planificar_grilla_fotos(...)` — asistente simple para "poner tantas imágenes
  como pueda": calcula cuántos slots de tamaño fijo entran en un área
  disponible (grilla fila por fila, no es un bin-packer óptimo).
- `aplicar_plan_recursos(plan)` — escribe `plan_recursos.json` (mismo canal IPC
  que el resto de los scripts, en AppData/Roaming) y ejecuta
  `scripts/AplicarModeloRecursos.js` por CDP.

`scripts/AplicarModeloRecursos.js` — aplica la lista de operaciones (mover,
redimensionar, clonar, eliminar, renombrar — este último vía clonar-con-nombre-
nuevo + eliminar el original, ver sección de renombrado arriba) envueltas en UN
solo `app.undo.beginCompoundUndo`/`endCompoundUndo` (deshacer revierte todo de
una). **No toca** `PegarNota_JSON.js` ni el pegado de texto — subsistema aislado.

**Pendiente de validar en vivo**: correr un plan real contra una maqueta de
prueba abierta en Quark y confirmar antes/después (mover una foto, redimensionarla,
clonar una segunda desde `clonable_desde`, eliminar un recurso sobrante, y que
el undo revierta todo en un paso). No se hizo en este ciclo por prudencia: la
instancia de Quark disponible durante el desarrollo estaba en uso real, sin
maqueta de prueba activa para no arriesgar una mutación no solicitada.

## Roadmap por fases

- **F1 — Lector CDP + límites reales** ✅: `LeerMaquetaCDP.js`, `maqueta_introspect`
  (lectura + capacidad + calibración + caché), herramienta de lectura batch.
- **F1.5 — Manifest semántico + director de diferencias (motor de recursos)** ✅
  este ciclo: `maqueta_manifest.py`, `recurso_plan.py`, `AplicarModeloRecursos.js`.
  Spike de escritura **pendiente de validar en vivo** (ver arriba).
- **F2 — Spike de escritura de geometría (base)** ✅: `scripts/MoverCajaMM_spike.js`
  confirma el mecanismo de mover una caja seleccionada; `AplicarModeloRecursos.js`
  lo generaliza a mover/redimensionar/clonar/eliminar/renombrar por lote.
- **F3+F4 — Editor visual (visor + edición)** ✅ jul 2026: `model/maquetador_state.py`
  (`RecursoEditable`/`MaquetadorDocumento`, conserva el manifest original
  íntegro para no perder `clonable_desde` del pasteboard), `services/maquetador_io.py`
  (cargar desde `maquetas_cache.json`/lienzo en blanco, guardar en el pool),
  `ui/maquetador/` (canvas `QGraphicsView`/`QGraphicsScene` EN MM — no píxeles,
  el zoom es pura transformación de vista igual que `ZoomableGraphicsView` de
  `ui/maqueta_widget.py` — + panel de roles anclable + panel de propiedades) y
  `ui/maquetador_window.py`. Arrastrar/redimensionar/clonar/marcar-eliminar
  recursos sobre el canvas; recalcula capacidad en vivo (`estimar_capacidad`,
  sin reimplementar la fórmula); "Ver plan de cambios" corre
  `calcular_diferencias` como preview de solo lectura. Trabaja 100% en
  memoria/JSON — **no llama a Quark en ningún punto**, ni siquiera para aplicar
  el plan (`aplicar_plan_recursos` queda deshabilitado en la UI, pendiente de
  autorización explícita y de la validación en vivo de F1.5). Alcance de este
  ciclo: solo geometría/cantidad de recursos y guardado en el pool — el
  concepto de "noticia"/"aviso" (agrupación con asignación de contenido) y la
  futura extensión de Chrome quedaron fuera, a definir en un ciclo posterior.
  Tests headless en `tests/test_maquetador_state.py` (fixture de manifest, sin
  depender de Quark ni de la caché real).
- **F3+F4 (ampliación) — márgenes, undo/redo real y nomenclatura semántica** ✅
  jul 2026: (1) Márgenes de página editables — lectura best-effort por CDP en
  `LeerMaquetaCDP.js` (`margin_top/bottom/left/right_mm`, **pendiente de
  validar en vivo**, default 0mm si Quark no expone el dato), 4 campos nuevos
  en `Maqueta`, acción "Márgenes…" en `MaquetadorWindow` + rect guía azul en
  el canvas (`actualizar_margenes`, sin recargar la escena). (2) Undo/redo real
  con `QUndoStack`/`QUndoCommand` (`ui/maquetador/undo_commands.py` — primera
  vez que se usa en el repo; `story_panel.py` tiene un patrón custom de listas
  pero es para edición de texto, no para operaciones estructuradas) — Ctrl+Z/
  Ctrl+Y, y Supr elimina un recurso DIRECTAMENTE (se quitó el soft-delete
  `marcado_eliminar`). Simplificación resultante: `MaquetadorDocumento.a_objetivos()`
  infiere el borrado por diferencia de conjuntos (`ids del manifest_original`
  − `ids actuales en doc.recursos`), sin ningún flag. El drag se captura como
  UN solo comando por arrastre (señales `recurso_movido_fin`/
  `recurso_redimensionado_fin` en `mouseReleaseEvent`, separadas de las señales
  en vivo que siguen actualizando capacidad/posición en cada micro-paso). (3)
  Nomenclatura semántica determinística `rol_N`/`textual_N_campo`
  (`services/maquetador_nomenclatura.py`) — SOLO para maquetas construidas
  desde cero con el maquetador (ej. `maquetas/listas/vaciaGenerica_test.qxp`),
  fallback puro en `construir_manifest` cuando `maqueta_roles.json` no
  resuelve nada (nunca reemplaza el mapeo estático de producción). "textual"/
  "dato"/"numero"/"qr" son recursos-grupo rígidos (mismo mecanismo que
  `RECURSO_GRUPO`/`moverGrupo` de `PegarNota v6.js`): sus cajas se clonan y se
  mueven siempre juntas (`RecursoEditable.grupo_id`/`grupo_campo`,
  `MaquetadorDocumento.clonar_recurso_compuesto`/`mover` propaga el delta a
  todo el grupo). Nombres de campo de dato/numero/qr son **placeholders
  genéricos** (`campo_1..N`) — pendiente de que el usuario confirme los reales.
- **F5 — Migración gradual de PegarNota_JSON.js** (fuera de alcance de este
  ciclo, alto riesgo): reemplazar `UNIVERSAL`/`AVISO_TARGETS`/rutinas por
  sección por el manifest único, sección por sección, con la producción
  actual como fallback durante la transición.

## Modelo Python original (`model/maqueta_model.py`, F1)

`Caja`/`Maqueta` (dataclasses, geometría + `to_dict`/`from_dict` + `from_cdp`)
siguen vigentes como representación general de una maqueta; `maqueta_manifest.py`
es una capa **adicional** con clasificación semántica de roles + ids estables,
específica para el modelo de recursos del maquetador.
