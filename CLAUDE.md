# CLAUDE.md — contexto persistente del proyecto

Sistema interno (Kostiv Cardinal International Law Group Corp.) para llenar
plantillas EOIR (Tabs de exhibits, Motions, EOIR-33) a partir de datos de
caso capturados en una interfaz web local (Flask + JS plano, sin build
step). Este archivo es la referencia que **siempre** debe leerse/tenerse en
cuenta al iterar sobre tabs o motions — evita releer código para reconstruir
reglas que ya están decididas, y evita repetir errores ya corregidos.

## Plantillas registradas (`plantillas/registro.json`)

Fuente de verdad de qué plantillas existen. Hoy son 5:

| template_id | tipo | tiene_tabla_exhibits |
|---|---|---|
| `i589-tab-cover` | Tab de exhibits (I-589) | sí |
| `webex-motion` | MOTION | no |
| `eoir-33-change-address` | PDF form fijo (AcroForm) | no |
| `motion-withdraw-no-cooperation` | MOTION (variante de `motion-withdraw`) | no |
| `motion-withdraw-cancelation` | MOTION (variante de `motion-withdraw`) | no |

Para agregar una plantilla nueva, seguir el procedimiento del `README.md`
("Agregar una plantilla `.dotx` nueva"): `analyze_template.py` → revisar
`field_map.json` a mano → si tiene tabla de exhibits, fragments +
`exhibit_builder.py` → registrar en `registro.json`.

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
  punto de inserción, antes de "PROOF OF SERVICE") y
  `combinar_portada_y_evidencia_exhibits()` (un punto de inserción por letra
  de Exhibit, para los Tabs de I-589).
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
