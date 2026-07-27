# Maquetador interno — arquitectura y roadmap

Documento de diseño del "maquetador" de ArmadorHuarpe: leer maquetas reales desde
QuarkXPress, derivar los límites de cada campo **sin rellenar a mano**, y (a
futuro) permitir ubicar noticias, mover/redimensionar cajas y replicar todo a
Quark por DOM/JS.

Contexto: los límites de campo se calibraban **a mano** en `config.ini`
(`LeerMaqueta.js` no dio resultados usables). Ahora se aprovecha el canal CDP
(QuarkXPress expone Chrome DevTools en el puerto 8087) para leer geometría real.

## Cómo se lee una maqueta (implementado — F1)

- **JS** `scripts/LeerMaquetaCDP.js`: es una *expresión* que **devuelve** un objeto
  (no escribe archivos ni usa `alert`), pensada para `Runtime.evaluate({returnByValue:true})`.
  Por cada `qx-box` con nombre reporta:
  - geometría en **mm** parseando `--qx-left/top/right/bottom` del `style` inline
    (más `width_mm`/`height_mm` derivados y `--qx-page`),
  - `box-content-type`,
  - para texto: `font_family`, `font_size` (pt), `leading`, `text_align` y la clase
    de estilo de párrafo (`pr-C-…`), leídos del `style` del primer `qx-p`/`qx-span`,
  - `chars` del placeholder (si hay).
  - Además el tamaño del **lienzo** (para maquetas vacías).
- **Python** `services/maqueta_introspect.py`:
  - `leer_maqueta_cdp()` descubre el target `JSServiceUI`, corre el JS por
    `quark_cdp.evaluar` y devuelve el dict directo (sin copiar a mano).
  - `probar_escritura_geometria()` corre el spike de escritura (ver F2).

## Cómo se estiman los límites SIN rellenar (implementado — F1)

Respuesta a "¿cuántos caracteres entran en una caja con una fuente/tamaño dados?":
se calcula analíticamente con `QFontMetrics` a partir de la geometría (mm) y la
fuente/tamaño (pt), en `services/maqueta_introspect.estimar_capacidad()`:

```
em_mm          = font_size_pt * 25.4/72
avg_char_mm    = (averageCharWidth/em, por familia) * em_mm
line_h_mm      = leading_pt*25.4/72  ó  (height/em)*em_mm
chars_por_lin  = floor((width_mm  - 2*inset) / avg_char_mm)
lineas         = floor((height_mm - 2*inset) / line_h_mm)
capacidad      = chars_por_lin * lineas * factor_calibracion
```

- `averageCharWidth/em` y `height/em` se obtienen con la fuente a `pixelSize=1000`
  (adimensional, independiente del DPI) y se cachean por familia.
- `calibrar_factor(data)` deriva el factor comparando la capacidad geométrica
  (factor=1) contra los `chars` reales de las cajas que tienen placeholder.
- Es **estimación** (justificación/kerning/partición varían); el factor y los
  overrides manuales `[MAQUETA:<nombre>]` en `config.ini` permiten ajuste fino.

## Escritura de geometría a Quark (spike — F2, unknown gate)

`scripts/MoverCajaMM_spike.js`: expresión que mueve la **primera caja seleccionada**
(`app.activeBoxesDOM()`) +10 mm en X/Y escribiendo `--qx-left/top/right/bottom` en
el `style` inline (el mismo sistema que se lee), envuelto en compound-undo, y
devuelve `{antes, despues, movio, metodo}`.

- **Resultado a confirmar en Quark**: si `movio === true`, la escritura de
  geometría por variables mm es viable y habilita el maquetador con réplica real.
  Si no, el maquetador queda como **visor/planificador** (F3) y la réplica usa el
  flujo existente de `PegarNota_JSON.js` (que ya posiciona por otros medios).

## Modelo Python (implementado — base de F3+)

`model/maqueta_model.py`:
- `Caja(nombre, tipo, left/top/width/height_mm, page, rol, limite, font_*, style_class)`
  con `right_mm`/`bottom_mm` y `estimar_limite()`.
- `Maqueta(nombre, canvas_*_mm, origen, source, cajas[])` con `to_dict`/`from_dict`
  (round-trip JSON) y `from_cdp(data)` para construir desde el lector CDP.
- Tres orígenes: `prearmada` (plantillas de `maquetas/`), `real` (CDP), `dibujar`
  (lienzo en blanco).

## Roadmap por fases

- **F1 — Lector CDP + límites reales** ✅ (este ciclo): `LeerMaquetaCDP.js`,
  `maqueta_introspect` (lectura + capacidad + calibración), `maqueta_model`.
- **F2 — Spike de escritura de geometría** ✅ entregado el spike; falta **verificar
  en Quark** con una caja seleccionada (`probar_escritura_geometria()`).
- **F3 — Visor read-only**: canvas `QGraphicsView`/`QGraphicsScene` en mm que dibuja
  `Maqueta` (real/prearmada); selección de caja muestra rol + límite estimado.
  Reusar patrón de `ui/maqueta_widget.py`.
- **F4 — Editor**: mover/redimensionar cajas y ubicar noticias sobre el canvas;
  recalcular límites en vivo; elegir/combinar maquetas prearmadas/reales/dibujar.
- **F5 — Réplica a Quark**: escritor JS que aplica la geometría del modelo a las
  cajas por el método probado en F2 (o el flujo de pegado existente), con el patrón
  file-based JSON + `quark_cdp.ejecutar_script`.

## Integración con los límites del editor (pendiente de cableado)

`services/maqueta_reader_service.map_to_editor_limits` / `map_limits_for_story` hoy
cruzan `box_chars` con `scripts/maqueta_roles.json`. El próximo paso es que
consuman `capacidades_por_caja()` (medida real por geometría+fuente) en lugar de
(o además de) los valores calibrados a mano, manteniendo `[MAQUETA:<nombre>]` como
ajuste fino.
