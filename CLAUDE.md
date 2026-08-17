# CLAUDE.md — contexto persistente del proyecto

Sistema interno (Kostiv Cardinal International Law Group Corp.) para llenar
plantillas EOIR (Tabs de exhibits, Motions, EOIR-33) a partir de datos de
caso capturados en una interfaz web local (Flask + JS plano, sin build
step). Este archivo es la referencia que **siempre** debe leerse/tenerse en
cuenta al iterar sobre tabs o motions — evita releer código para reconstruir
reglas que ya están decididas, y evita repetir errores ya corregidos.

## Plantillas registradas (`plantillas/registro.json`)

Fuente de verdad de qué plantillas existen. Hoy son 6 (3 de ellas variantes
del grupo `motion-withdraw`):

| template_id | tipo | tiene_tabla_exhibits |
|---|---|---|
| `i589-tab-cover` | Tab de exhibits (I-589) | sí |
| `webex-motion` | MOTION | no |
| `eoir-33-change-address` | PDF form fijo (AcroForm) | no |
| `motion-withdraw-no-cooperation` | MOTION (variante de `motion-withdraw`) | no |
| `motion-withdraw-cancelation` | MOTION (variante de `motion-withdraw`) | no |
| `motion-withdraw-location-known` | MOTION (variante de `motion-withdraw`) — **BORRADOR**, ver abajo | no |

Para agregar una plantilla nueva, seguir el procedimiento del `README.md`
("Agregar una plantilla `.dotx` nueva"): `analyze_template.py` → revisar
`field_map.json` a mano → si tiene tabla de exhibits, fragments +
`exhibit_builder.py` → registrar en `registro.json`.

### `motion-withdraw-location-known` — plantilla BORRADOR, pendiente de revisión del abogado

Creada 2026-08-17 a pedido explícito del usuario, para el escenario en que
**solo se conoce la dirección del cliente** (a diferencia de
`motion-withdraw-no-cooperation`, que también pide un teléfono conocido). El
texto narrativo del NOTICE (el párrafo que reemplaza "We are completely
unaware of the whereabouts..." + el párrafo del teléfono) **lo redactó
Claude como borrador**, no es texto validado por un abogado del despacho —
el propio usuario pidió explícitamente "redacta tú un borrador... con la
advertencia de que es un borrador mío, no texto validado por un abogado".
Antes de usarla en un caso real, un abogado debe revisar/aprobar la
redacción exacta. El `nombre` en `registro.json` incluye "(BORRADOR —
revisar con abogado antes de usar)" a propósito — no quitar esa advertencia
del selector sin que el despacho confirme que ya revisó el texto.
Estructuralmente es un clon de `motion-withdraw-no-cooperation` (mismo
patrón de Exhibits A/B/C/D, mismo mecanismo de firmas/campos), solo cambia
el párrafo narrativo, la descripción del Exhibit B, y se quitó el campo
`telefono_conocido` (aquí no aplica, solo hay dirección).

## Regla de numeración de páginas (decidida explícitamente por el despacho)

- **Solo se numeran las páginas de evidencia / PDFs adjuntos** (lo que el
  usuario sube para Exhibits o para una Motion). El número va **al pie de
  página, esquina inferior derecha**.
- **Las páginas propias de las plantillas (portada, tabla de exhibits,
  dividers, Proof of Service, el `.dotx` en sí) NUNCA llevan número
  nuestro.** No agregar footer/PAGE field a ninguna plantilla `.dotx`. Esto
  ya se intentó una vez (footer en `i589-tab-cover`) y se revirtió por
  instrucción explícita del usuario — no repetir ese enfoque.
- `eoir-33-change-address` es un formulario federal fijo (AcroForm PDF
  oficial de EOIR/DOJ) — no se modifica su estructura ni se le agrega
  numeración propia; ya trae su propia paginación/instrucciones.
- La numeración de evidencia vive en `motor/pdf_merge.py`,
  `_pagina_numero_overlay(width, height, numero)` (reportlab,
  `drawRightString`, Times-Roman 11, `margen_derecho=40`,
  `margen_inferior=28`), usada por `combinar_portada_y_evidencia()` (un solo
  punto de inserción, antes de "PROOF OF SERVICE" — usada por los Tabs de
  I-589 y `webex-motion`) y `combinar_portada_y_evidencia_exhibits()` (un
  punto de inserción por letra de Exhibit con nombre — usada por las
  variantes de `motion-withdraw`).
- **Excepción explícita (2026-08-17): Motion to Withdraw NO numera sus
  páginas de evidencia**, a diferencia de la regla general de arriba —
  decisión del usuario. `combinar_portada_y_evidencia_exhibits()` recibe un
  parámetro `numerar: bool = True`; `app.py` lo llama con `numerar=False`
  para el flujo de `exhibits_evidencia` (el único que usa esta función hoy,
  que es exclusivo de las 3 variantes de `motion-withdraw`). El default
  sigue en `True` por si otra plantilla futura reutiliza este mismo
  mecanismo de "exhibits con nombre" y sí quiere numeración.
- **Bug ya corregido**: PDFs de evidencia escaneados a veces traen `/Rotate`
  ≠ 0 (la página se ve derecha porque el visor la rota al mostrarla, pero
  sus coordenadas de contenido siguen siendo las de antes de rotar). Sin
  corregir esto, el número dibujado en "abajo a la derecha" en coordenadas
  crudas terminaba en otra esquina visual (ej. arriba a la derecha) una vez
  aplicada la rotación. Fix: `page.transfer_rotation_to_content()` (pypdf)
  antes de calcular `width`/`height`, en ambas funciones de merge. Si se
  toca `pdf_merge.py`, mantener esa llamada — es la razón por la que el
  número siempre cae en la esquina visual correcta sin importar cómo venga
  guardado el PDF de origen.

## Motion to Withdraw: un Exhibit sin evidencia se elimina del documento (decidido explícitamente)

- **Regla del usuario (2026-08-17)**: si en una corrida de `motion-withdraw-*`
  solo se sube evidencia para algunos de los Exhibits declarados (ej. solo
  Exhibit A de A/B/C), los Exhibits SIN evidencia se eliminan por completo
  del documento generado — ni página divisoria huérfana, ni mención en el
  párrafo NOTICE. No es opcional/configurable desde la UI, es el
  comportamiento por defecto de `motor/fill_engine.generar_documento` para
  cualquier plantilla con `field_map["evidencia_exhibits"]`.
- Dos piezas, ambas en `motor/fill_engine.py`, ambas corren **antes** de
  `merge_runs_in_document_xml` (¡importante! ver más abajo por qué):
  - `_apply_missing_exhibit_dividers`: quita la página divisoria completa
    "EXHIBIT {letra}" (vía `_locate_exhibit_divider_page`, que ubica el
    párrafo `<w:pageBreakBefore/>` que la empieza y corta hasta el
    siguiente `<w:pageBreakBefore/>` del documento — cada página de estas
    es autocontenida, así que esto nunca rompe el salto de página de lo que
    viene después).
  - `_apply_notice_exhibits`: recorta la mención de ese Exhibit en el
    párrafo NOTICE del cuerpo de la moción (que cita cada Exhibit por
    nombre en una sola oración, ej. "...Declaration...(Exhibit A), Proof of
    no contact...(Exhibit B), the attached Disengagement Letter (Exhibit C)
    and a Pro bono List (Exhibit D)."), incluyendo: quitarle el conector al
    ítem que quede primero si el que originalmente era primero se eliminó,
    y ponerle punto final al que quede último si el que originalmente
    cerraba la oración (con su propio punto, ej. "(Exhibit D)." en
    `motion-withdraw-no-cooperation`) se eliminó. Toda la configuración
    (qué texto literal marca cada ítem, dónde está el conector, cuál cierra
    la oración) vive en `field_map["notice_exhibits"]` de cada plantilla —
    ver los comentarios largos en la propia función para el detalle de cada
    clave.
- **Por qué corren ANTES de `merge_runs_in_document_xml`**: esta función
  fusiona runs de Word adyacentes con formato idéntico — exactamente el
  tipo de run que `_apply_notice_exhibits` necesita que sigan SEPARADOS
  para poder cortar solo el pedazo de un Exhibit sin tocar sus vecinos. Si
  se llamara después, se arriesga a que la plantilla ya llegue "fusionada"
  y los puntos de corte ya no existan. `motion-withdraw-no-cooperation` ya
  traía sus runs separados de fábrica (los marcadores "(Exhibit X)" son
  itálicos, formato distinto al texto de alrededor, así que nunca se
  fusionan); `motion-withdraw-cancelation` **no** los traía separados —
  se le hizo una edición quirúrgica one-time al `.docx` (dividir 3 runs en
  9, mismo `rPr`, mismo texto renderizado, solo se movieron los límites de
  `<w:r>`) para poder aplicarle el mismo mecanismo. Si se vuelve a tocar el
  párrafo NOTICE de cualquier plantilla `motion-withdraw-*` a mano en Word,
  hay que revisar que los runs de cada Exhibit sigan separados de los de
  sus vecinos o esta función dejará de encontrar los cortes correctos (tira
  `FillEngineError` con un mensaje claro si no encuentra un ancla — nunca
  falla en silencio produciendo un documento a medio recortar).
- Bug ya corregido en el camino: `_find_preceding_run` originalmente
  buscaba `<w:r` con `rfind`, que también hace match parcial con `<w:rPr`
  y `<w:rFonts` (substring) — encontraba el tag equivocado y dejaba XML mal
  formado. Ahora usa el mismo patrón de dos búsquedas (`<w:r>` y `<w:r `)
  que ya usaba `_find_enclosing_run`.
- Otro bug ya corregido: insertar el punto final directo en la posición
  "fin del `<w:r>`" lo deja como texto suelto entre elementos (fuera de
  cualquier `<w:t>`), que Word/la extracción de texto ignora. Hay que
  insertarlo DENTRO del `<w:t>` del marcador que queda último (justo antes
  de su `</w:t>`) — ver `ultimo_marker_text_end` en `_apply_notice_exhibits`.

## Firma default de Lorenzo hardcodeada en `i589-tab-cover` — eliminada

- El `.dotx` de `i589-tab-cover` (`00_TABS_TEAM_4.dotx`) traía, **quemada
  directamente en el documento** (no vía `field_map.json` ni el mecanismo
  `firmas_imagen` de `motor/fill_engine.py`), una imagen flotante
  (`<w:drawing><wp:anchor ... allowOverlap="1">`) con la firma escaneada de
  Lorenzo, posicionada de forma absoluta justo después del párrafo "...no
  separate service was completed." del Proof of Service. Por ser un
  `wp:anchor` con posición absoluta y `allowOverlap="1"` (no `wp:inline`),
  se podía sobreponer con el texto de alrededor según cuánto ocupara ese
  párrafo — de ahí el problema reportado por el usuario.
- **Se eliminó por instrucción explícita del usuario** (2026-08-17): se
  quitó el `<w:r>` con el `<w:drawing>` de `word/document.xml`, su
  relationship (`rId9`) de `word/_rels/document.xml.rels`, y el archivo
  `word/media/image1.png` — usando `motor.ooxml_utils.unpack`/`rezip`
  directo sobre el `.dotx` (no hay mecanismo de campo para esto porque
  nunca fue un campo, era una imagen fija de la plantilla).
- Esta plantilla **no** usa `firmas_imagen`/`categoria: preparadores` (a
  diferencia de `webex-motion` y las dos `motion-withdraw-*`, que sí tienen
  ese mecanismo dinámico intacto — ver la sección de arriba). Si en algún
  momento se quiere una firma de preparador dinámica en `i589-tab-cover`,
  habría que agregarla como SDT + entrada en `firmas_imagen`, no repetir el
  patrón de imagen fija anclada.
- **No volver a incrustar una imagen fija/anclada de firma en ningún
  `.dotx`** — si se necesita una firma en una plantilla nueva, usar el
  mecanismo dinámico existente (SDT + `firmas_imagen` en `field_map.json`),
  que inserta la imagen como `wp:inline` (no flota, no se sobrepone).

## Archivos que NO se deben modificar sin instrucción explícita

- `plantillas/*/*.dotx` y `plantillas/*/*.docx` — plantillas originales del
  despacho. Cualquier cambio de layout/footer/margen a nivel de plantilla
  requiere pedir confirmación primero (ver el caso del footer revertido).
- `plantillas/eoir-33-change-address/EOIR_33.pdf` — formulario oficial
  fijo, no se toca.
- `case_store/*.json` — datos reales de clientes, no se sube a git
  (`.gitignore`). No crear/dejar ahí archivos de prueba; si un test los
  genera, borrarlos antes de commitear.

## Limitaciones conocidas de este entorno (sandbox de esta sesión)

- **LibreOffice/`soffice` está roto en este sandbox** para conversión
  docx→PDF (falla con `Error: source file could not be loaded` incluso en
  un docx trivial recién creado). No es un bug del código del proyecto.
  Verificación visual del resultado (`motor/pdf_tools.convert_to_pdf` +
  `rasterize`) no es confiable aquí — la verificación debe hacerse por
  inspección estructural directa (unzip + XML del `.docx`, atributos de
  pypdf del `.pdf`) en vez de render visual. En la máquina real del
  despacho (Windows, con LibreOffice/Word instalados vía `instalar.bat`)
  esto sí funciona normalmente.
- **`git push` falla siempre con 403** ("Resource not accessible by
  integration") en esta sesión. Workaround establecido: entregar los
  cambios vía `git archive --format=zip HEAD` + `SendUserFile`, además del
  commit local normal.

## Arquitectura rápida (para no releer todo cada vez)

- `app.py` — servidor Flask, endpoints de caso/generación/output.
- `motor/fill_engine.py` — llena el `.docx`/`.dotx` reemplazando SDT/campos
  según `field_map.json`, arma tabla de exhibits y dividers vía
  `exhibit_builder.py`, maneja firmas como imagen.
- `motor/exhibit_builder.py` — construye el XML fijo de la tabla de
  exhibits y los dividers por categoría (Country Conditions, Form of
  Identity, etc.), usando fragments literales en `plantillas/<id>/fragments/`.
- `motor/pdf_merge.py` — inserta y numera las páginas de evidencia/adjuntos
  dentro del PDF de portada ya convertido (ver regla de numeración arriba).
  También trae heurísticas de sugerencia (`sugerir_anio`, `sugerir_pais`,
  etc.) que leen texto de las primeras páginas del PDF subido.
- `motor/pdf_form_fill.py` — llena el AcroForm de `EOIR_33.pdf` directo
  (sin pasar por Word), con overlays puntuales para iniciales/firma.
- `motor/pdf_tools.py` — conversión a PDF (Word/LibreOffice) y
  rasterización a imágenes para la verificación visual en la UI.
- `motor/ooxml_utils.py` — helpers genéricos de bajo nivel para manipular
  paquetes OOXML (unpack/rezip, relationships, content types, merge de
  runs) — usarlos en vez de reinventar manipulación de zip/XML.
- `motor/case_store.py` — persistencia simple de casos en JSON
  (`case_store/<id>.json`), numeración de página siguiente por caso, next
  tab letra, etc.
- `static/index.html` + `static/app.js` — UI de una sola página, sin
  framework ni build step.
