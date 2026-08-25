# CLAUDE.md — contexto persistente del proyecto

Sistema interno (Kostiv Cardinal International Law Group Corp.) para llenar
plantillas EOIR (Tabs de exhibits, Motions, EOIR-33) a partir de datos de
caso capturados en una interfaz web local (Flask + JS plano, sin build
step). Este archivo es la referencia que **siempre** debe leerse/tenerse en
cuenta al iterar sobre tabs o motions — evita releer código para reconstruir
reglas que ya están decididas, y evita repetir errores ya corregidos.

## Errores ya corregidos — checklist rápido (NO repetir)

Resumen de cada problema real que se presentó, su causa y el fix aplicado.
Es el primer lugar a revisar antes de tocar código relacionado — cada ítem
tiene su sección con el detalle completo más abajo en este mismo archivo.

1. **Numeración de páginas propias de la plantilla.** Se agregó un footer/
   PAGE field a `i589-tab-cover` → el usuario lo pidió revertir
   explícitamente. Regla: **solo se numera evidencia/PDFs adjuntos**, nunca
   portada/tabla de exhibits/dividers/Proof of Service. No volver a agregar
   footer a ningún `.dotx`. → ver "Regla de numeración de páginas".
2. **Número de página en la esquina equivocada en PDFs escaneados.** PDFs
   con `/Rotate` ≠ 0 hacían que el número "abajo a la derecha" cayera en otra
   esquina visual. Fix: `page.transfer_rotation_to_content()` (pypdf) antes
   de calcular `width`/`height` en `motor/pdf_merge.py`. Si se toca ese
   archivo, no quitar esa llamada. → ver "Regla de numeración de páginas".
3. **XML mal formado al recortar runs en Motion to Withdraw.**
   `_find_preceding_run` usaba `rfind("<w:r")`, que también matchea
   `<w:rPr`/`<w:rFonts` (substring) y agarraba el tag equivocado. Fix: buscar
   con dos patrones (`<w:r>` y `<w:r `), igual que `_find_enclosing_run`. →
   ver "Motion to Withdraw: un Exhibit sin evidencia se elimina".
4. **Punto final "invisible" al recortar el párrafo NOTICE.** Insertarlo en
   el borde del `<w:r>` lo dejaba como texto suelto fuera de `<w:t>`, que
   Word ignora. Fix: insertar el punto DENTRO del `<w:t>`, justo antes de
   `</w:t>`. → misma sección que el ítem 3.
5. **Firma de Lorenzo quemada/anclada en `i589-tab-cover`.** Imagen flotante
   (`wp:anchor`, `allowOverlap="1"`) fija en la plantilla se podía sobreponer
   al texto del Proof of Service. Se eliminó del `.dotx` (run + relationship
   + `word/media/`) y se reemplazó por el mecanismo dinámico
   (`firmas_imagen` + SDT), que inserta `wp:inline` y nunca flota. → ver
   "Firma default de Lorenzo hardcodeada".
6. **Firma duplicada/sobrepuesta en `webex-motion`.** La plantilla traía DOS
   firmas ancladas quemadas (abogado + preparador) que quedaban dibujadas
   ENCIMA de la firma dinámica nueva → salía la firma dos veces. Se
   eliminaron ambas del `.docx`. **Regla general: ninguna plantilla debe
   llevar firma quemada/anclada** — al agregar una plantilla nueva, revisar
   que no traiga `wp:anchor` con imagen de firma antes de registrarla. → ver
   "`webex-motion` traía DOS firmas ancladas quemadas".
7. **Pluralización de "Respondent(s)" hardcodeada solo para una plantilla.**
   Existía `_apply_plural_respondents` atada a `i589-tab-cover`. Se
   generalizó a `field_map["plural_riders"]` (lista curada de frases
   exactas). **No usar un `replace` genérico de "Respondent"** — hay
   apariciones que nunca deben pluralizarse (placeholder del SDT del
   caption, tabla Form of Identity). → ver "Pluralización 'Respondent(s)'
   con riders".
8. **Nombre de cliente largo rompía la firma en `webex-motion`.**
   Alineación con `<w:tab/>` + espacios literales + `jc="both"` solo
   funcionaba con nombres cortos de una línea; con "NOMBRE et al" la segunda
   línea caía al margen izquierdo. Fix: sangría real de párrafo
   (`w:ind w:left`) en vez de tabs/espacios. Si se retoca ese bloque de
   firma a mano en Word, no reintroducir alineación manual con
   espacios/tabs para campos de longitud variable. → ver "`webex-motion`: el
   nombre del cliente en la firma se rompía".
9. **Saltos de página reales rompieron el formato de `webex-motion` —
   REVERTIDO.** Se intentó cambiar los rellenos de párrafos vacíos por
   `<w:pageBreakBefore/>` reales para arreglar una línea huérfana. El
   usuario lo revirtió ("se arruinó el formato"). **No repetir ese cambio**
   sin pedirlo explícitamente y validar el render real en Word (no se puede
   verificar visualmente en este sandbox, LibreOffice está roto acá). → ver
   "`webex-motion`: saltos de página por sección".
10. **CC/OSAC exigía los dos años aunque solo se subiera evidencia de uno.**
    Dos validaciones independientes (`_build_category_xml` en Python y
    `generarDocumento()` en JS) exigían ambos años sin consultar cuál
    subitem iba a quedar incluido. Fix: ambas consultan
    `frag_indices_incluidos`/`tg.evidencias` antes de exigir el año. **Si se
    toca esta lógica, mantener sincronizados frontend y backend** — son dos
    checks independientes que deben llegar a la misma conclusión. → ver "Tab
    de Country Conditions (CC/OSAC)".
11. **Campo "Próxima audiencia" solo aceptaba texto ya escrito en
    palabras.** Se agregó autoformato en frontend (`blur`, no `input`) que
    convierte `MM/DD/AAAA HH:MM AM/PM` a `Month D, AAAA at H:MM AM/PM` si el
    texto empieza con ese patrón numérico, dejando intacto el resto
    (tipo/modalidad) y sin tocar nada si ya viene en palabras. → ver "Campo
    'Próxima audiencia'".
12. **Biometrics Compliance (por persona) recién agregado: no anexaba los
    PDFs y dejaba Fee Receipt/FBI Fingerprint sin evidencia.** Dos bugs
    reales, ambos porque `biometricos` vive FUERA del dict genérico
    `evidencias`: (a) `app.py`, el gate `tiene_evidencia` que decide si se
    llama a `_resolver_paginas_evidencia` (la función que resuelve páginas
    Y arma la lista de PDFs a fusionar) no miraba `tg["biometricos"]` — si
    la ÚNICA evidencia del Tab era de Biometrics Compliance, nunca se
    fusionaba nada aunque el usuario sí hubiera subido el archivo. (b)
    `motor/exhibit_builder.frag_indices_incluidos("fee", evidencias)` solo
    mira el dict `evidencias` (fee_receipt/fbi_fingerprint) para decidir si
    está en "modo manual" (incluir todo) o "modo evidencia" (incluir solo
    lo que tiene archivo) — sin evidencia de esos dos ítems fijos, caía
    siempre en modo manual e incluía Fee Receipt/FBI Fingerprint aunque no
    tuvieran nada adjunto. Fix: nuevo parámetro
    `hay_evidencia_dinamica: bool` en `frag_indices_incluidos`, que el
    llamador setea a `True` para "fee" cuando algún `biometricos` tiene
    evidencia — fuerza el modo evidencia (excluye los ítems fijos sin
    archivo) aunque `evidencias` esté vacío. → ver "Bug: Biometrics
    Compliance no anexaba evidencia".
13. **`next_tab_letra` se quedaba pegado en "AA" después de la Z.** Faltaba
    el acarreo del incremento base-26 (Z→AA, pero de ahí AA→AA en vez de
    AA→AB). Fix: incremento base-26 bijectivo con acarreo real, replicado
    en `case_store.py` y `static/app.js` (`nextTabLetra`). Solo afectaba
    casos con 27+ exhibits. → ver "Auditoría 2026-08-25".
14. **`_ANIO_RE` de la sugerencia de año dejaba de reconocer años ≥2040.**
    Rango original `19[9]\d|20[0-3]\d` (1990-2039). Fix: `19[89]\d|20\d\d`
    (1980-2099). → ver "Auditoría 2026-08-25".
15. **Errores de datos en la tabla de exhibits (país/año/fecha faltante)
    daban 500 genérico en vez de 400 con mensaje claro.** `api_generar` solo
    atrapaba `FillEngineError`/`ValidationError`, no el `ValueError` que
    lanza `exhibit_builder`. Fix: `ValueError` agregado a la tupla del 400.
    No repetir: cualquier `raise ValueError` nuevo en `exhibit_builder` para
    validar datos de exhibits debe llegar como 400, no como 500. → ver
    "Auditoría 2026-08-25".
16. **Body no-JSON en `api_save_caso`/`api_generar` tiraba 500 con
    traceback.** Fix: `request.get_json(force=True, silent=True)` +
    chequeo `isinstance(..., dict)` → 400 "El cuerpo de la petición no es
    JSON válido". → ver "Auditoría 2026-08-25".
17. **`campos_extra` de ninguna plantilla se validaban como obligatorios
    antes de generar.** Dejar uno vacío no tiraba error — se quedaba con
    el placeholder que haya quedado grabado en el `.docx` al construir la
    plantilla (texto real de OTRO caso). Se detectó al construir
    `written-pleadings` (10 `campos_extra` nuevos, alto riesgo de mezclar
    datos entre clientes). Fix genérico en `static/app.js`
    (`generarDocumento`): valida que todo `campos_extra` de la plantilla
    activa tenga valor antes de armar `document_instance` — protege
    también a `motion-withdraw-*`, que ya tenía este mismo hueco. No
    volver a quitar esa validación. → ver "Plantilla `written-pleadings`".
18. **Firma quemada/anclada #4 encontrada: no era del cliente, era del
    traductor.** `written-pleadings` traía, en un cuadro de texto flotante
    ("Certificate of Translation") que `python-docx`'s `.paragraphs` NO
    recorre, la firma escaneada real de Bruno Briz (preparador/traductor),
    quemada dos veces (rama moderna + rama legacy VML del mismo cuadro).
    Un primer diagnóstico por posición aproximada del offset la atribuyó
    al cliente — el atributo correcto se confirmó ubicando el párrafo
    exacto que contiene cada `r:embed`. Eliminada igual que las otras 3
    (i589-tab-cover, webex-motion x2). **Si se analiza una plantilla
    nueva a partir de un `.docx` YA LLENADO, revisar también
    `<w:txbxContent>` (cuadros de texto) además de `document.paragraphs`
    — un cuadro de texto flotante puede esconder tanto texto con datos
    reales como una firma quemada que `.paragraphs` nunca muestra.** → ver
    "Plantilla `written-pleadings`".
19. **`cliente_nombre` en `written-pleadings` no es un solo campo — son
    tres.** Con el primer ejemplo (sin riders) los tres coincidían, así que
    parecía un solo campo; un segundo ejemplo real CON riders reveló que
    hace falta `cliente_nombre` (verbatim+"et al"), `cliente_nombre_mayus`
    (MAYÚSCULAS+"ET AL") y `cliente_nombre_lead_mayus` (MAYÚSCULAS, nunca
    "et al" — es la declaración personal de un solo respondent). **No
    volver a asumir que un campo de nombre se comporta igual en todos los
    lugares del documento solo porque un ejemplo sin riders no mostró
    diferencia** — antes de dar por buena una plantilla nueva con
    riders/pluralización, pedir o construir un caso de prueba CON riders.
    → ver "`written-pleadings`: corregido contra un SEGUNDO ejemplo real
    con riders".

**Nota**: los fixes 13-16 (más limpieza de evidencia huérfana en
`output/_evidencia` al arrancar y código muerto) están detallados con más
contexto en "## Auditoría 2026-08-25: fixes de robustez + primera suite de
tests" más abajo en este archivo. Esa sección también documenta qué NO se
tocó a propósito (numeración no idempotente, alineación de Biometrics con
wrap, condición de carrera teórica) — revisar ahí antes de "arreglar" esos
tres puntos de nuevo.

## Plantillas registradas (`plantillas/registro.json`)

Fuente de verdad de qué plantillas existen. Hoy son 7 (3 de ellas variantes
del grupo `motion-withdraw`):

| template_id | tipo | tiene_tabla_exhibits |
|---|---|---|
| `i589-tab-cover` | Tab de exhibits (I-589) | sí |
| `webex-motion` | MOTION | no |
| `eoir-33-change-address` | PDF form fijo (AcroForm) | no |
| `motion-withdraw-no-cooperation` | MOTION (variante de `motion-withdraw`) | no |
| `motion-withdraw-cancelation` | MOTION (variante de `motion-withdraw`) | no |
| `motion-withdraw-location-known` | MOTION (variante de `motion-withdraw`) — **BORRADOR**, ver abajo | no |
| `written-pleadings` | Respondent's Written Pleadings (+ Declaration + Certificate of Translation) | no |

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
- **Actualización (2026-08-19): sí tiene `firmas_imagen` de preparador,
  agregado a pedido del usuario** (reportó que su firma en
  `firmas/preparadores/Lorenzo Bracamontes.png` nunca aparecía en el
  documento generado — la plantilla solo escribía el nombre como texto).
  Se agregó siguiendo el mismo patrón que `webex-motion`: en
  `word/document.xml` hay una línea de firma escrita como texto literal
  (`_______________________`, un solo `<w:r>` que es todo el contenido de
  su propio `<w:p>`, justo antes del párrafo con el SDT del nombre del
  preparador en el bloque final de "Respectfully submitted") — se envolvió
  ese `<w:r>` en un `<w:sdt>` nuevo (`<w:id w:val="930000001"/>`, mismo
  `rPr` copiado al `sdtPr` que ya traía el run) y se registró en
  `field_map.json` → `"firmas_imagen": [{"nombre": "preparador",
  "categoria": "preparadores", "ids": ["930000001"]}]`. Edición hecha con
  `motor.ooxml_utils.unpack`/`rezip` directo sobre el `.dotx` (no hay UI
  para esto, es cirugía de plantilla). Verificado con
  `generar_documento` real: con PNG presente inserta la imagen `wp:inline`
  (relationship + `word/media/`, nunca ancla flotante — no repetir el
  patrón de imagen fija anclada de la sección de arriba); sin PNG cae al
  mismo texto `_______________________` de siempre, sin romper nada.
  `webex-motion` y las dos `motion-withdraw-*` ya tenían este mecanismo
  desde antes — con esto las cuatro plantillas que llevan firma de
  preparador (todas menos `eoir-33-change-address`, que es un AcroForm fijo)
  lo tienen.
- **No volver a incrustar una imagen fija/anclada de firma en ningún
  `.dotx`** — si se necesita una firma en una plantilla nueva, usar el
  mecanismo dinámico existente (SDT + `firmas_imagen` en `field_map.json`),
  que inserta la imagen como `wp:inline` (no flota, no se sobrepone).

## `webex-motion` traía DOS firmas ancladas quemadas — eliminadas (2026-08-19)

- Mismo problema que `i589-tab-cover` de arriba, pero en `MOTION_FOR_WEBEX.docx`
  y por partida doble: la plantilla traía **dos** imágenes flotantes
  (`<w:drawing><wp:anchor ... allowOverlap="1">`) quemadas — `word/media/image1.png`
  (firma escaneada del abogado, `rId9`) y `word/media/image2.png` (firma del
  preparador, `rId11`)— justo encima de las líneas de firma. Como la plantilla
  YA tiene el mecanismo dinámico `firmas_imagen` (SDT `900000025` abogado,
  `900000026` preparador), al generar con PNG presente se dibujaba la firma
  nueva ENCIMA de la vieja anclada: **la firma salía dos veces, sobrepuesta**
  (reportado por el usuario con screenshot). Fix: se quitaron los dos `<w:r>`
  con `<w:drawing>` de `word/document.xml`, sus relationships `rId9`/`rId11`, y
  los dos `word/media/image*.png`, con `ooxml_utils.unpack`/`rezip` directo
  sobre el `.docx` (cada drawing estaba solo en su propio `<w:p>`; quitar el
  run deja un párrafo vacío inocuo). Ahora la única firma es la dinámica
  `wp:inline` de `firmas_imagen`.
- **Regla general confirmada por el usuario (2026-08-19): NINGUNA plantilla
  debe llevar una firma quemada/anclada** — cuando se coloca la firma nueva
  (dinámica) no se debe sobreponer a una vieja. Ya revisadas las 5 plantillas
  editables: `i589-tab-cover` y `webex-motion` limpias; las 3 `motion-withdraw-*`
  solo tienen un Text Box vacío (una forma, sin imagen ni firma) — no hay más
  firmas quemadas que quitar. Si se agrega una plantilla nueva, verificar que
  no traiga `wp:anchor` con imagen de firma antes de registrarla.

## Pluralización "Respondent(s)" con riders — `field_map["plural_riders"]`

- **Regla del usuario (2026-08-19)**: cuando un caso tiene riders (varios
  respondents → el nombre sale como "NOMBRE et al", ver
  `case_store.nombre_para_documento`), los textos FIJOS de la plantilla que
  dicen "Respondent"/"Respondent's" y su concordancia de verbo deben
  pluralizarse ("moves"→"move", "does not oppose"→"do not oppose",
  "Respondent's counsel"→"Respondents' counsel", etc.). El disparador es
  `bool(case.get("riders"))`.
- Mecanismo genérico en `motor/fill_engine._apply_plural_riders(document_xml,
  field_map)`: aplica una lista CURADA de frases exactas
  `field_map["plural_riders"]` (cada ítem `{"buscar": <singular literal>,
  "reemplazar": <plural>}`) como reemplazo literal sobre el XML ya con campos
  resueltos. Corre para CUALQUIER plantilla que tenga la clave, cuando hay
  riders. Antes existía `_apply_plural_respondents` hardcodeada solo para
  `i589-tab-cover`; se generalizó y sus dos reemplazos se migraron a
  `field_map["plural_riders"]` de esa plantilla (`>Respondent<`→`>Respondents<`
  y `A True Copy of the Respondent's `→`...Respondents' `).
- **Por qué frases curadas y NO un `replace` genérico de "Respondent"**: hay
  "Respondent" que NO se deben tocar — el placeholder del SDT del caption "In
  the Matter of: {nombre}" es literalmente la palabra "Respondent" (se
  reemplaza por el nombre vía `_apply_field_values`), y la tabla Form of
  Identity del I-589 distingue por persona ("Respondent's"/"Rider's {nombre}")
  y nunca se pluraliza. Por eso cada regla es una frase larga inequívoca (o
  con delimitadores `>...<`) que solo matchea donde debe. Cada `buscar` debe
  aparecer 1 sola vez; si una regla no encuentra su `buscar` (plantilla
  editada a mano) se avisa por consola pero NO se aborta —la concordancia es
  cosmética y nunca debe bloquear un escrito—. `webex-motion` tiene 11 reglas
  (incluye la sección ORDER: "The Respondents do not oppose", "must comply").
- Si se agregan riders a otra plantilla (`motion-withdraw-*` aún no tienen
  `plural_riders`), agregar sus frases al `field_map` correspondiente tras
  revisar su texto — el mecanismo ya es genérico, no hay que tocar código.

## `webex-motion`: el nombre del cliente en la firma se rompía con nombres largos (2026-08-19)

- El párrafo del nombre bajo "Attorney for Respondent(s)," (el que sigue al
  SDT `900000017`) posicionaba el texto con 5 `<w:tab/>` + 24 espacios
  literales en el propio `<w:t>`, más `jc="both"` heredado por copiar el
  párrafo vecino. Eso solo alineaba la PRIMERA línea — con un nombre largo
  (típicamente varios respondents, "NOMBRE et al"), el párrafo envolvía a
  una segunda línea que caía al margen izquierdo de la página (sin
  sangría real que la sostuviera), y `jc="both"` estiraba con espaciado
  raro la primera línea al justificarla.
- Fix: se quitaron los tabs/espacios y el `jc="both"` de ESE párrafo
  puntual, y se agregó `w:ind w:left="5040"` (twips, ≈3.5in — misma
  posición visual que el hack anterior para nombres cortos). Con sangría
  real, si el nombre envuelve, la segunda línea queda alineada bajo
  "Attorney for Respondent(s)," en vez de saltar al margen — se adapta
  solo según la longitud del nombre.
- Las 3 plantillas `motion-withdraw-*` NO repiten el nombre del cliente en
  su bloque de firma (solo dicen "Attorney for Respondent," sin nombre
  debajo), así que este bug no les aplica — revisado y confirmado.
- Si se vuelve a tocar el bloque de firma de `webex-motion` a mano en
  Word, evitar reintroducir alineación con espacios/tabs literales para
  campos de longitud variable (nombre, "et al", etc.) — usar sangría de
  párrafo (`Formato > Párrafo > Sangría izquierda`) en vez de espaciar a
  mano, para que el texto siga viéndose bien sin importar cuánto mida.

## `webex-motion`: saltos de página por sección — INTENTADO Y REVERTIDO (2026-08-19)

- **Contexto**: la plantilla finge los saltos de página entre secciones con
  runs largos de párrafos vacíos (28 tras el TABLE OF CONTENTS, 13 tras el
  bloque de firma). Eso hacía que una línea se desbordara y quedara huérfana
  en una hoja casi vacía (la línea "Date: ___ By: Court Staff" del Certificate
  of Service).
- **Se intentó** reemplazar esos rellenos por `<w:pageBreakBefore/>` reales al
  inicio de cada sección (cuerpo de la moción, ORDER, PROOF OF SERVICE; el TOC
  ya lo traía). **El usuario lo revirtió: "se arruinó el formato".** Se
  restauró la estructura original de la plantilla (solo se mantuvo la
  eliminación de firmas quemadas), volviendo a los rellenos de párrafos
  vacíos y al único `pageBreakBefore` del TOC.
- **No volver a aplicar el enfoque de `pageBreakBefore` por sección a
  `webex-motion`** sin que el usuario lo pida explícitamente y valide el
  render en su Word — no se pudo verificar visualmente en el sandbox
  (LibreOffice roto) y el resultado real rompió el formato. Si se retoma el
  problema del desborde, hay que hacerlo con render real a la vista, no a
  ciegas por estructura.

## Tab de Country Conditions (CC/OSAC): años ya no son obligatorios los dos (2026-08-21)

- **Regla del usuario (2026-08-21)**: en un Tab con categoría "Country
  Conditions" (i589-tab-cover), si el usuario solo sube evidencia de UNO de
  los dos ítems (Country Reports on Human Rights Practice **o** OSAC Crime
  and Safety Report — a veces solo hay actualización de uno de los dos en
  el sistema legal), ya no se le obliga a llenar el año del otro. Solo se
  incluye en el documento el subitem con evidencia adjunta (el otro se
  descarta, mismo mecanismo de `frag_indices_incluidos` que ya existía) y
  solo su año es obligatorio.
- **Sin evidencia subida** (modo manual, los dos subitems se incluyen
  siempre) **se siguen pidiendo los dos años**, como antes — el cambio
  aplica solo cuando hay evidencia adjunta para alguno de los dos.
- Dos lugares tocados, ambos ya usaban `frag_indices_incluidos` para decidir
  qué subitem incluir pero no lo consultaban para decidir qué año exigir:
  - `motor/exhibit_builder._build_category_xml` (rama `country_conditions`):
    ahora llama `frag_indices_incluidos` ANTES de validar/reemplazar, y solo
    exige `anio_cc`/`anio_osac` si el índice correspondiente (1=Country
    Reports, 2=OSAC) va a quedar incluido.
  - `static/app.js` → `generarDocumento()`: la validación previa al submit
    ahora mira `tg.evidencias.country_reports` / `.osac` (ya construido por
    `collectExhibits()`) para saber cuál año es obligatorio, replicando la
    misma regla que el backend (si no hay evidencia de ninguno de los dos,
    exige ambos años igual que antes).
- Si se retoca esta lógica, mantener sincronizados el frontend y
  `_build_category_xml` — son dos validaciones independientes que deben
  llegar a la misma conclusión sobre qué año es obligatorio, si no el
  frontend puede bloquear con un error que el backend ya no exigiría (o
  viceversa, dejar pasar algo que el backend igual rechaza).

## Campo "Próxima audiencia": autoformato de fecha MM/DD/AAAA → texto (2026-08-24)

- **Regla del usuario (2026-08-24)**: el campo de Paso 1 (Caso) "Próxima
  audiencia" es texto libre (siempre lo fue — se inserta literal en el
  documento, sin parseo de fecha real en el backend). El usuario pidió poder
  escribir la fecha/hora en formato numérico `MM/DD/AAAA HH:MM AM/PM` y que
  el sistema la convierta sola al formato en palabras que usa el documento,
  sin dejar de aceptar también el formato ya escrito en palabras (pegado tal
  cual del portal EOIR).
- Implementado 100% en frontend, `static/app.js`:
  `formatProximaAudiencia(raw)` usa un regex que solo matchea si el texto
  **empieza** con `D/D/AAAA` (1-2 dígitos día/mes, 4 dígitos año), con hora
  `H:MM AM/PM` opcional a continuación, y cualquier resto de texto después
  (tipo de audiencia, modalidad) que se preserva tal cual, reconectado con
  coma. Si el texto no matchea ese patrón inicial (ej. ya viene en palabras,
  "September 10, 2026, ..."), la función lo devuelve sin tocar — así se
  aceptan ambos formatos en el mismo campo, sin un toggle ni dos inputs.
  Ejemplo: `"08/26/2026 08:30 AM, Master Calendar Hearing, In Person"` →
  `"August 26, 2026 at 8:30 AM, Master Calendar Hearing, In Person"`.
- `attachProximaAudienciaFormatter` lo ata al evento `blur` del input (no a
  `input`) — a propósito, para no reescribir la fecha en pantalla mientras
  el usuario todavía está tecleando los dígitos (a diferencia de
  `attachANumberFormatter` del A#, que sí formatea en cada tecla porque ahí
  solo se insertan guiones, no se reescribe texto).
- El formato de salida usa `"Month D, AAAA at H:MM AM/PM"` (con la palabra
  "at" antes de la hora) — así lo pidió el usuario explícitamente en su
  ejemplo, aunque el resto del campo (tipo/modalidad) sigue separado por
  comas como ya se hacía. No es el mismo formato exacto que trae el
  placeholder viejo del campo (que no usaba "at") — si el despacho prefiere
  quitar el "at" y usar coma en su lugar ahí también, es un cambio de una
  sola línea en `formatProximaAudiencia`.
- No hay validación de que el día exista de verdad para ese mes (ej. no
  rechaza "02/30/2026") — es solo reformateo de texto, no parseo real de
  fecha; tampoco hace falta un objeto `Date` porque el string se inserta
  literal en el documento.

## Tab de FEE: nuevo ítem "Biometrics Compliance" (2026-08-24)

- **Pedido del usuario (2026-08-24)**: agregar un tercer ítem dentro de la
  categoría `fee` (antes solo Fee Receipt + FBI Fingerprint) — "Biometrics
  Compliance", con subitem "i. Respondent's Fingerprint Notification
  Biometric Processing Stamp ({FECHA})" — y un campo en la UI para capturar
  la fecha de captura de huella por Tab.
- Fragmentos nuevos en `plantillas/i589-tab-cover/fragments/`:
  `subtitle_biometrics_compliance.xml` (encabezado "Biometrics Compliance."
  en negrita/subrayado, mismo estilo que `subtitle_form_of_identity.xml`) e
  `item_biometrics_compliance.xml` ("i. Respondent's Fingerprint
  Notification Biometric Processing Stamp (DATE)." con el placeholder
  literal `(DATE)` que se reemplaza por la fecha real). Ambos autoría de
  Claude en esta sesión (no extraídos del `.dotx` original con
  `analyze_template.py`, porque no existían en la plantilla) — mismo
  `rFonts`/`sz`/`spacing` que los fragmentos vecinos, `paraId`/`textId`
  inventados sin colisión con los existentes.
- `motor/exhibit_builder.py`: `CATEGORY_FRAGMENTS["fee"]` pasó de 2 a 4
  fragmentos (`item_fee_receipt`, `item_fbi_fingerprint`,
  `subtitle_biometrics_compliance`, `item_biometrics_compliance` — índices
  0-3) y `ITEMS_POR_CATEGORIA["fee"]` ganó `{"key":
  "biometrics_compliance", "label": "Biometrics Compliance", "frag_index":
  3}`. Con eso, TODO el mecanismo existente de subida de evidencia/paginado
  (`app.py._resolver_paginas_evidencia`, `build_pages_cell_content`) ya
  funcionaba solo, sin tocar nada más — es genérico sobre
  `ITEMS_POR_CATEGORIA` desde que se construyó (ver ítems previos de este
  changelog).
- **Problema encontrado y corregido en el camino**: el subtítulo
  "Biometrics Compliance" NO debe comportarse como el de
  `country_conditions` (que es de TODA la categoría y acompaña a
  cualquiera de sus ítems) — es un encabezado que pertenece SOLO a su
  propio ítem. Con la regla genérica vieja de `frag_indices_incluidos`
  ("un subtítulo siempre acompaña a cualquier ítem incluido de la
  categoría"), subir evidencia SOLO de Fee Receipt (sin Biometrics
  Compliance) dejaba el encabezado "Biometrics Compliance" huérfano, sin su
  ítem debajo. Fix: nuevo dict `SUBTITULOS_ATADOS_A_ITEM = {"fee": {2: 3}}`
  (frag_index del subtítulo → frag_index del ítem del que depende);
  `frag_indices_incluidos` solo incluye ese subtítulo si su ítem atado
  también quedó incluido. Categorías sin entrada en ese dict (todas las
  demás) mantienen el comportamiento viejo sin cambios — verificado con
  `country_conditions` (regresión).
- **Por qué subtítulo e ítem son DOS fragmentos separados y no uno solo**:
  se probó primero combinarlos en un único fragmento (un solo frag_index,
  dos `<w:p>` adentro) para evitar el problema del huérfano — funciona para
  DESCRIPTION, pero rompe la alineación línea a línea con la columna PAGES
  (`build_pages_cell_content` genera una línea de PAGES por frag_index
  incluido, no por párrafo de XML; con un solo frag_index de dos párrafos,
  DESCRIPTION mostraba 2 líneas para ese ítem pero PAGES solo 1, y el
  "Pgs. X-Y" quedaba pegado a la línea equivocada). Se revirtió a dos
  fragmentos separados (mismo patrón que `subtitle_country_conditions` +
  `subitem_country_reports`/`subitem_osac`) — verificado que con evidencia
  adjunta la columna PAGES saca una línea en blanco para el subtítulo y
  "Pgs. X-Y" alineado con la línea del ítem, igual que en Country
  Conditions.
- La fecha (`fecha_huella`) es **obligatoria cuando el ítem Biometrics
  Compliance vaya a quedar incluido** — mismo patrón que `anio_cc`/
  `anio_osac` de Country Conditions: sin evidencia adjunta en la categoría
  `fee` (modo manual) los 3 ítems se incluyen siempre y la fecha siempre se
  pide; con evidencia adjunta, solo se pide si justo se subió evidencia
  para `biometrics_compliance`. Threading completo: `static/app.js`
  (`collectExhibits` → `tg.fecha_huella`, validado en `generarDocumento()`
  antes del submit) → `app.py` (pasa `document_instance` sin tocar) →
  `motor/fill_engine._apply_exhibits` → `build_exhibit_table` →
  `build_description_cell_content` → `_build_category_xml`, que lanza
  `ValueError("fee requiere 'fecha_huella' para Biometrics Compliance")` si
  falta (la validación del frontend debería atajarlo antes, este es el
  respaldo del backend, igual que con `anio_cc`/`anio_osac`). **Si se toca
  esta lógica, mantener sincronizados frontend y backend** — mismo aviso
  que el ítem de CC/OSAC del checklist de arriba.
- UI: `static/app.js` agrega `.fecha-huella-field` (input de texto libre,
  ej. "09/22/2023") a la tarjeta de cada Tab, visible solo cuando la
  categoría `fee` está marcada — mismo patrón que `.tipo-fee-field`. No
  lleva autoformato de fecha (a diferencia de "Próxima audiencia") — es
  texto libre que se inserta literal entre paréntesis, igual que la fecha
  ya hardcodeada de `item_fbi_fingerprint.xml`.
- `catalogos.json` → `exhibit_categorias.fee.etiqueta` actualizada a "FEE
  (fee receipt + FBI fingerprint + Biometrics Compliance)" para que el
  checkbox de categoría en la UI refleje los tres ítems.
- No se tocó `field_map.json` — este mecanismo vive enteramente en
  `exhibit_builder.py`/fragments (como `tipo_fee`, que tampoco es un campo
  SDT), no en el sistema de SDT/campos simples de la plantilla.

## Biometrics Compliance pasó a ser 1 documento POR PERSONA (líder + riders) (2026-08-24)

- **Pedido del usuario (mismo día que se creó el ítem)**: en vez de un solo
  campo `fecha_huella` por Tab, dejar subir **más de un documento, uno por
  rider**, y que el nombre del rider aparezca en el propio renglón — "ya
  tienes una referencia de cómo se ponen los riders", en referencia al
  mecanismo que ya existía para Form of Identity (un documento por persona
  del caso, ver `identidades`/`personasDelCaso()`).
- **Se reemplazó el campo único `fecha_huella` por una lista `biometricos`**
  (uno por persona: líder + cada rider del caso), clonando exactamente el
  patrón de Form of Identity en vez de inventar uno nuevo:
  - `motor/exhibit_builder.py`: "Biometrics Compliance" dejó de vivir en
    `CATEGORY_FRAGMENTS["fee"]`/`ITEMS_POR_CATEGORIA["fee"]` (que ahora solo
    tienen `item_fee_receipt`/`item_fbi_fingerprint`, índices 0-1) — pasó a
    ser una sección dinámica igual que `_build_form_of_identity_description`/
    `_build_form_of_identity_pages`: nuevas funciones
    `_build_biometrics_compliance_description(biometricos)` y
    `_build_biometrics_compliance_pages(biometricos)`, que `_build_category_xml`
    y `build_pages_cell_content` **agregan siempre al final** de la categoría
    "fee" cuando está marcada (no depende de `frag_indices_incluidos`, no
    hay forma de omitirla — mismo comportamiento que Form of Identity, que
    tampoco es "opcional" una vez marcada la categoría). Por esto se pudo
    **borrar `SUBTITULOS_ATADOS_A_ITEM["fee"]`** (el mecanismo del huérfano
    de la sección anterior de este archivo) — ya no aplica porque el
    subtítulo y sus ítems viven juntos en su propia función, nunca
    desalineados.
  - Cada entrada de `biometricos` es `{persona_nombre, fecha, evidencia}`
    (mismo shape que `identidades`, cambiando `tipo_doc` por `fecha`). Texto
    por persona (`_biometrics_line_text`): sin `persona_nombre` →
    "Respondent's Fingerprint Notification Biometric Processing Stamp
    (FECHA)."; con `persona_nombre` → "Rider's {NOMBRE} Fingerprint
    Notification Biometric Processing Stamp (FECHA)." — **se quitó el "i. "**
    que tenía el ítem original (`item_biometrics_compliance.xml`): con un
    renglón por persona ya no tiene sentido un numeral romano fijo de un
    solo ítem; queda sin numerar, igual que los renglones de Form of
    Identity.
  - `fecha` es obligatoria por persona (`_build_biometrics_compliance_description`
    tira `ValueError` si falta) — es el mismo requisito que antes tenía el
    `fecha_huella` único, generalizado a cada entrada.
  - `app.py._resolver_paginas_evidencia`: mismo tratamiento que
    `identidades`/`documentos_se` — nuevo bloque `if categoria == "fee":`
    que resuelve `evidencia_id` → `evidencia` (pagina_inicio/num_paginas/path)
    por cada entrada de `biometricos`, en el mismo lugar del loop de
    categorías donde ya se resuelven `fee_receipt`/`fbi_fingerprint` (por
    eso el orden de páginas queda: fee_receipt, fbi_fingerprint, luego
    biometrics del líder, luego de cada rider — coincide con el orden en que
    `_build_biometrics_compliance_description` los agrega al final). También
    se sumó `biometricos_resueltos` a la lista `docs_con_pagina` que arma el
    merge del PDF de evidencia (mismo bloque que ya sumaba
    `identidades_resueltos`/`documentos_se_resueltos`).
  - `static/app.js`: se quitó el único campo `.fecha-huella-field`/
    `.tab-fecha-huella`. Nuevo `renderBiometricosUploads(card)` — clon
    literal de `renderIdentidadesUploads`, un renglón por
    `personasDelCaso()` con input de fecha (texto libre) + upload de PDF
    opcional; estado en `card._biometricosEvidencia` (archivos, mismo patrón
    que `_identidadesEvidencia`) y `card._biometricosFecha` (fechas
    tipeadas, para no perderlas cuando `actualizarCampos()` vuelve a
    regenerar el HTML del bloque al tocar otra categoría — Form of Identity
    no necesita este dict paralelo porque su `<select>` de tipo de
    documento no pierde nada crítico al resetear a su default, pero perder
    una fecha tipeada a mano sí sería molesto). `recalcularPaginas()` y
    `collectExhibits()` tienen el mismo tratamiento por-persona que ya
    tenían para `identidades`. La validación previa al submit en
    `generarDocumento()` ahora exige fecha en cada entrada de
    `tg.biometricos` (reemplaza el chequeo viejo de `evFee.biometrics_compliance`,
    que ya no existe como key de `evidencias` — Biometrics Compliance no
    vive más en el diccionario `evidencias` genérico de items fijos).
- **Por qué no se mantuvo el chequeo "si solo subís Fee Receipt se omite
  Biometrics Compliance completo" de la sección anterior**: con evidencia
  por persona ya no aplica esa lógica de todo-o-nada por categoría — cada
  persona tiene su propio renglón, obligatorio, igual que ya pasaba con
  Form of Identity (que tampoco se puede "omitir" una vez marcada la
  categoría). Si en el futuro se pide poder omitir Biometrics Compliance
  para un caso sin riders, es un cambio deliberado aparte, no algo que
  quedó pendiente de este cambio.
- Verificado con pruebas manuales (no hay test suite automatizada en este
  proyecto): alineación PAGES/DESCRIPTION 4/4 con evidencia parcial (fee_receipt
  con archivo, fbi_fingerprint sin archivo, biometrics de 2 personas, una con
  archivo y otra sin), y pipeline completo `_resolver_paginas_evidencia` →
  `build_exhibit_table` con líder + 1 rider, ambos con archivo — páginas
  encadenadas correctamente (1-2 fee_receipt, 3 biometrics líder, 4
  biometrics rider).

## Bug: Biometrics Compliance no anexaba evidencia (2026-08-25)

- **Reporte del usuario**: comparó un documento generado real (Tab D, caso
  con líder + 1 rider, evidencia de Biometrics Compliance subida para
  ambos) contra un ejemplo de cómo debía verse. Dos problemas visibles: (1)
  Fee Receipt y FBI Fingerprint aparecían en la tabla sin evidencia
  adjunta (nunca se subió nada para esos dos ítems en ese Tab — no debían
  aparecer), y (2) el PDF final no traía anexadas las páginas de evidencia
  de Biometrics Compliance en absoluto (el documento se quedaba en 4
  páginas: portada, tabla de exhibits, divisoria "EXHIBIT D", Proof of
  Service — sin las páginas reales del I-797C subido), aunque la columna
  PAGES sí mostraba un rango "Pgs. 51-54" (calculado del lado del
  navegador, nunca verificado contra lo que el backend realmente fusionó).
- **Causa raíz, dos bugs independientes** — ambos por la misma razón de
  fondo: `biometricos` (la lista por-persona agregada en la sesión
  anterior, ver sección de arriba) vive FUERA del dict genérico
  `evidencias` que ya usaban `fee_receipt`/`fbi_fingerprint`, y dos piezas
  de código que ya existían antes de `biometricos` nunca se actualizaron
  para saber de su existencia:
  1. `app.py`, el gate `tiene_evidencia` (justo antes de decidir si se
     llama a `_resolver_paginas_evidencia` — la función que calcula
     páginas Y arma la lista de PDFs que después se fusionan al PDF de
     portada) solo miraba `tg["evidencias"]`/`identidades`/
     `documentos_se`, nunca `tg["biometricos"]`. Si en un Tab la ÚNICA
     evidencia subida era de Biometrics Compliance (como en el caso
     reportado), `tiene_evidencia` daba `False` y **todo el mecanismo de
     resolución de páginas y fusión de PDFs se saltaba por completo** —
     `bio["evidencia"]` nunca se poblaba, y por lo tanto tampoco se
     agregaba nada a `docs_con_pagina` más abajo en el mismo archivo (el
     bloque que arma la lista de rutas a fusionar con
     `combinar_portada_y_evidencia`). El "Pgs. 51-54" que sí se veía en el
     documento venía del cálculo hecho en el navegador
     (`recalcularPaginas()` en `static/app.js`, que sí sabe sumar páginas
     de `card._biometricosEvidencia` para mostrarle un preview al
     usuario) y se usaba tal cual como texto de fallback — sin que el
     backend hubiera resuelto ni fusionado nada real. Fix: agregar
     `or any(b.get("evidencia_id") for b in (tg.get("biometricos") or
     []))` a la condición de `tiene_evidencia`.
  2. `motor/exhibit_builder.frag_indices_incluidos(categoria, evidencias)`
     decide si una categoría con ítems fijos (ej. "fee") está en "modo
     manual" (nada subido → incluir todos los ítems fijos) o "modo
     evidencia" (algo subido → incluir solo los ítems fijos que sí tienen
     archivo) mirando ÚNICAMENTE el dict `evidencias`
     (`fee_receipt`/`fbi_fingerprint`). Nunca sabía que `biometricos`
     pudiera tener evidencia — así que con evidencia SOLO en
     `biometricos` (y nada en `evidencias` para esos dos ítems fijos),
     `evidencias` llegaba vacío y la función cae en "modo manual",
     incluyendo Fee Receipt y FBI Fingerprint sin archivo, en vez de
     omitirlos (que es lo correcto: hay evidencia en la categoría, solo
     que vive en la sección dinámica). Fix: nuevo parámetro
     `hay_evidencia_dinamica: bool = False` en `frag_indices_incluidos` —
     cuando es `True`, la función NO cae en modo manual aunque
     `evidencias` esté vacío (los ítems fijos sin evidencia simplemente no
     se incluyen). Los dos llamadores que arman la tabla
     (`_build_category_xml` para DESCRIPTION, y el loop por categoría
     dentro de `build_pages_cell_content` para PAGES) lo setean a `True`
     solo para `categoria == "fee"` y solo si algún `biometricos` trae
     `evidencia`/`evidencia_id` — **hay que pasarlo en AMBOS lugares**, no
     alcanza con uno solo, porque DESCRIPTION y PAGES cada uno vuelve a
     llamar `frag_indices_incluidos` por su cuenta; si solo se arregla uno
     de los dos, las columnas quedan desalineadas (se detectó exactamente
     así al probar: 3 párrafos en DESCRIPTION vs 5 en PAGES antes de
     corregir el segundo llamador).
- **Por qué no se detectó en la sesión anterior**: las pruebas de esa
  sesión (alineación PAGES/DESCRIPTION, pipeline `_resolver_paginas_evidencia`
  → `build_exhibit_table`) siempre incluyeron evidencia de `fee_receipt`
  *junto con* la de `biometricos` en el mismo caso de prueba — nunca se
  probó el caso real reportado por el usuario, evidencia SOLO en
  `biometricos` y nada en los ítems fijos de "fee". Si se agrega evidencia
  dinámica a otra categoría con ítems fijos en el futuro, probar
  explícitamente el caso "evidencia SOLO en la sección dinámica, nada en
  los ítems fijos" — es el caso que expone este tipo de bug.
- Verificado con pruebas manuales tras el fix (no hay test suite
  automatizada en este proyecto): reproducido el escenario exacto
  reportado (líder + 1 rider, evidencia solo en `biometricos`) — Fee
  Receipt/FBI Fingerprint ya no aparecen, DESCRIPTION y PAGES quedan en 3
  párrafos alineados 1 a 1 ("Pgs. 51-52"/"Pgs. 53-54" en las líneas
  correctas), y `_resolver_paginas_evidencia` + el gate `tiene_evidencia`
  corregido sí resuelven y dejan lista la fusión real de los PDFs. También
  se corrieron 3 escenarios de regresión (fee_receipt con evidencia y
  biometricos sin ella; ambos con evidencia; líder+2 riders con evidencia
  mixta) sin romper el comportamiento ya existente.

### Ajuste (mismo día): subtítulo "Biometrics Compliance." repetido por persona, no compartido

- El fix de arriba corrigió que se incluyera/anexara la evidencia
  correcta, pero el usuario mandó captura de pantalla del documento real
  generado: con el subtítulo "Biometrics Compliance." compartido UNA vez
  para las 2 personas (líder + rider), la columna PAGES se desalineaba a
  partir de la 2da persona — "Pgs. 53-54" (el rango del rider) caía junto
  a la línea envuelta del renglón del líder, no junto al renglón del
  rider. Causa: el texto de cada renglón ("Respondent's/Rider's ... Fingerprint
  Notification Biometric Processing Stamp (FECHA).") es largo y casi
  siempre ocupa 2 líneas visuales al renderizar en Word, pero
  `_build_biometrics_compliance_pages` solo reservaba 1 párrafo de PAGES
  por persona (alineado 1 a 1 con los PÁRRAFOS XML de DESCRIPTION, no con
  las LÍNEAS VISUALES ya envueltas) — Word alinea columnas de una tabla por
  altura acumulada real, no por conteo de párrafos, así que un renglón que
  envuelve a 2 líneas visuales sin su columna PAGES compensando esa altura
  desalinea todo lo que sigue.
- El usuario pidió explícitamente tratar cada persona como su propia
  "categoría" (con su propio subtítulo), en vez de un subtítulo compartido
  para todas. Fix en `motor/exhibit_builder.py`: tanto
  `_build_biometrics_compliance_description` como
  `_build_biometrics_compliance_pages` ahora arman un bloque
  `[subtítulo, renglón]` (o `[blank, valor]` en PAGES) POR PERSONA, y unen
  los bloques de distintas personas con el mismo `spacer`/`blank` (párrafo
  vacío) que ya se usa para separar categorías distintas en la tabla — cada
  persona reinicia su propio bloque de 2 párrafos en ambas columnas
  (verificado que los conteos siguen coincidiendo 1 a 1: 5 párrafos con
  líder+1 rider, 8 con líder+2 riders, siempre `n_desc == n_pages`).
- **Importante — esto NO garantiza matemáticamente que "Pgs. X-Y" caiga en
  la línea visual exacta del renglón de esa persona si su propio texto
  envuelve a 2 líneas** (el subtítulo repetido resetea la alineación ENTRE
  personas, pero dentro del bloque de una misma persona, si su renglón
  ocupa 2 líneas y su valor de PAGES solo reserva 1, ese "Pgs. X-Y" queda
  bien alineado con la PRIMERA línea de su propio renglón — que es lo que
  importa — pero no hay una línea de PAGES extra reservada para la 2da
  línea envuelta; no debería hacer falta porque el bloque de la SIGUIENTE
  persona ya arranca de cero con su propio subtítulo). Como
  LibreOffice está roto en este sandbox (ver "Limitaciones conocidas" más
  abajo), este ajuste **no se pudo verificar visualmente en Word real** —
  solo se verificó la estructura XML (conteo de párrafos, orden). Si al
  generar un documento real en Word el "Pgs." de alguna persona sigue sin
  caer en la línea correcta, avisar con el detalle exacto (qué texto/fecha
  tenía esa persona, en qué línea cayó vs. en cuál debía cuál) para ajustar
  con precisión en vez de adivinar.

## Plantilla `written-pleadings` — creada desde un documento YA LLENADO, sin SDT de fábrica (2026-08-25)

- **Punto de partida distinto a todas las demás plantillas**: el usuario
  subió `Template_Written_Pleadings.docx`, que NO era una plantilla en
  blanco sino un documento real ya generado para un caso (Insuasti Ruiz,
  A# 245-870-935) — **cero** `<w:sdt>`, bookmarks o campos MERGEFIELD.
  Instrucción del usuario: "lo que está subrayado [en Word] son los datos
  que debes pedir". Hubo que verificar el subrayado corriendo por
  `r.underline` en cada run (no fiarse de una lectura visual del texto
  denso con marcadores — en un primer barrido se leyó mal un run y se
  reportó "no subrayado" cuando sí lo estaba, ver más abajo).
- **Campos ESTÁNDAR del caso reutilizados tal cual** (no subrayados en el
  ejemplo, porque ya existen en el Paso 1 y se repiten en todas las
  plantillas): `abogado`, `abogado_firma_coma`, `cliente_nombre` (8
  apariciones), `a_number` (2), `corte_sede`, `juez`, `proxima_audiencia`,
  `preparador`, `preparador_mayus`.
- **8 campos nuevos en el cuerpo principal** (subrayados, capturados como
  `campos_extra` de esta plantilla — no se guardan en el caso, se piden en
  cada corrida): `fecha_nta`, `alegaciones_admitidas`,
  `cargo_removibilidad`, `designacion_pais_remocion`, `formas_alivio`,
  `horas_estimadas`, `idioma_interprete`, `dialecto_interprete`.
  **Corrección durante el análisis**: en el primer reporte al usuario se
  dijo que el blanco del dialecto NO estaba subrayado — era un error de
  lectura (`r.underline` daba `True`); se corrigió antes de tocar el
  `.docx` y sí quedó como campo. Los blancos que de verdad NO estaban
  subrayados (denies allegation(s), denies charge(s), segunda forma de
  alivio "(2) ____") se dejaron fijos, confirmado explícitamente por el
  usuario en un `AskUserQuestion` ("solo lo subrayado").
- **Dos falsos positivos de subrayado descartados** (son estilo tipográfico
  de encabezado de sección, no campos): "PROOF OF SERVICE" y "DECLARACIÓN
  DE ALEGATOS DEL DEMANDADO". Confirmado cruzando con
  `motion-withdraw-no-cooperation`, que también subraya "PROOF OF SERVICE"
  sin que sea un campo — es la convención tipográfica del despacho para
  esos títulos, no una instrucción de llenado.
- **Hallazgo importante que casi se pasa por alto**: el documento trae un
  **cuadro de texto flotante** ("CERTIFICATE OF TRANSLATION") que
  `python-docx`'s `Document.paragraphs` **no recorre** (vive dentro de
  `<w:txbxContent>`, anidado en un `<w:drawing><wp:anchor>`) — un primer
  barrido con `d.paragraphs` no lo vio en absoluto. Solo apareció al
  inspeccionar `document.xml` crudo. Si se vuelve a analizar una plantilla
  nueva a partir de un `.docx` de ejemplo, **no asumir que `d.paragraphs`
  cubre todo el documento** — revisar también `<w:txbxContent>` con
  regex/XML crudo.
  - Ese cuadro de texto trae, quemada, la firma escaneada real (JPEG,
    `rId7`) — **del TRADUCTOR (Bruno Briz), no del cliente** como se creyó
    en un primer momento por la posición aproximada del offset en el XML.
    Se verificó con precisión buscando cada aparición de `rId7` y mirando
    el párrafo que la contiene: las dos (una en la rama moderna
    `mc:Choice`/drawingML, otra en la legacy `mc:Fallback`/VML del mismo
    cuadro) caen en la línea de firma "/S/Bruno B. . Bruno Briz
    {fecha}". Se eliminó por completo (imagen + relationship +
    `word/media/image1.jpeg`), siguiendo la regla ya establecida
    "ninguna plantilla lleva firma quemada/anclada".
  - 3 campos nuevos ahí: `traductor` (persona, 2 apariciones dentro de la
    rama Choice), `documento_traducido` (nombre del documento traducido,
    ej. "DECLARATION OF PLEADINGS"), y `traductor_abreviado` — este
    último es **derivado**, no se pide en la UI: `fill_engine.
    _persona_abreviada("Bruno Briz")` → `"Bruno B."` (primer nombre +
    inicial del apellido), mismo patrón que `_abogado_firma`/
    `_abogado_nombre`.
  - **Solo se le hizo cirugía de SDT a la rama moderna (`mc:Choice`)** del
    cuadro de texto. La rama legacy VML (`mc:Fallback`, que Word casi
    nunca renderiza en software actual) se dejó con el texto literal del
    caso de ejemplo (Bruno Briz / DECLARATION OF PLEADINGS) sin convertir
    a campo — no es información sensible de cliente (es el nombre de un
    preparador interno, ya público en `catalogos.json`), pero si el
    despacho quiere consistencia total ahí también, es trabajo pendiente
    documentado en `field_map.json["_notas"]`.
- **Cambio genérico en `motor/fill_engine.py`** para poder poner una firma
  dinámica de una persona que NO es `abogado`/`preparador` del caso: la
  firma de "traductor" es un campo **por corrida** (`document_instance`),
  no del caso. `_firma_lookup_nombre`/`_apply_firmas_imagen` ahora reciben
  `values` (el dict ya resuelto de caso + instancia) en vez de solo
  `case`, y cada entrada de `field_map["firmas_imagen"]` puede traer un
  `"nombre_field"` opcional indicando de qué clave de `values` sacar el
  nombre — sin `nombre_field` el comportamiento es idéntico al de siempre
  (compatibilidad total con las 4 plantillas existentes que ya usaban
  `firmas_imagen`). `written-pleadings` usa `"nombre_field": "traductor"`,
  `"categoria": "preparadores"` (reutiliza `firmas/preparadores/`, ya que
  Bruno Briz está en `catalogos.json` como preparador).
- **Validación genérica nueva en `static/app.js` (`generarDocumento`)**:
  antes de armar `document_instance`, ahora se valida que **todo**
  `campos_extra` de la plantilla activa tenga un valor no vacío (bloquea
  con "Falta el campo {etiqueta}" si no). Antes esto no existía para
  ningún `campos_extra` de ninguna plantilla (ej. `direccion_conocida` de
  Motion to Withdraw tampoco se validaba) — se generalizó al agregar
  `written-pleadings` porque acá el riesgo es más serio: sin esta
  validación, dejar un campo nuevo vacío no tira error, simplemente deja
  el placeholder que quedó grabado en el `.docx` al construir la
  plantilla (texto real del caso Insuasti Ruiz/Bruno Briz) — un documento
  de OTRO cliente podría salir con alegaciones/cargos/fecha de NTA que no
  son las suyas. Con la validación nueva esto ya no puede pasar desde la
  UI. **Si se toca esta lógica, no volver a quitar la validación
  genérica** — protege a `written-pleadings` y de paso a
  `motion-withdraw-*`.
- Cirugía técnica (por si se repite este proceso con otra plantilla sin
  SDT de fábrica): `unpack` → `motor.ooxml_utils.merge_runs_in_document_xml`
  (limpia atributos `rsid` y fusiona runs adyacentes de formato idéntico,
  simplifica mucho encontrar los límites de cada campo) → localizar cada
  campo por su texto exacto (con `occurrence` para desambiguar
  repeticiones, ej. `cliente_nombre` aparece 8 veces) → envolver en
  `<w:sdt><w:sdtPr><w:id w:val="…"/>{rPr copiado del run original}
  </w:sdtPr><w:sdtContent>{run(s) original(es)}</w:sdtContent></w:sdt>` →
  `rezip`. Las líneas de firma que traen tabs+espacios+guiones bajos TODO
  en un mismo `<w:r>` (común después de `merge_runs`) hay que partirlas a
  mano: el prefijo (tabs que posicionan la línea) queda FUERA del SDT, el
  mecanismo `_apply_firmas_imagen` reemplaza el contenido completo del
  SDT y perdería el posicionamiento si el prefijo quedara adentro. IDs
  usados: rango `920000001`-`920000032` (32 campos en total, ver
  `field_map.json["_notas"]` para la lista completa).
- Verificado con `motor.fill_engine.generar_documento` real (caso y
  campos de prueba, no el caso real Insuasti Ruiz): `validation_ok=True`,
  y se contó cada valor de prueba en el XML resultante — las 8
  apariciones de `cliente_nombre`, las 2 de `a_number`, las 2 de
  `traductor`, la forma derivada `traductor_abreviado` correcta, y CERO
  apariciones de `rId7` (la firma quemada del traductor ya no está en
  ningún documento generado). También corrida la suite `tests/run_tests.py`
  completa (10/10) para confirmar que no se rompió nada de lo existente.

## `written-pleadings`: corregido contra un SEGUNDO ejemplo real con riders (2026-08-25)

- El primer ejemplo (Insuasti Ruiz) no tenía riders, así que no dejaba ver
  que `cliente_nombre` necesita TRES formas distintas según el lugar del
  documento. El usuario compartió un segundo documento real ya llenado
  (Mendez Rodriguez, Sheraryn Mileny — caso CON riders) para comparar, y
  confirmó la regla exacta:
  - **`cliente_nombre`** (verbatim tal como está en el caso, + " et al" si
    hay riders) — SOLO en el renglón superior "Attorney for Respondent(s)"
    y en la caja de caption "In the Matter of".
  - **`cliente_nombre_mayus`** (TODO EN MAYÚSCULAS, + " ET AL" si hay
    riders) — en las firmas bajo el abogado, bajo cada Declaration
    (inglés/español) y en el sello antes de "PROOF OF SERVICE".
  - **`cliente_nombre_lead_mayus`** (SOLO el nombre del líder, MAYÚSCULAS,
    **NUNCA** "et al" aunque haya riders) — ÚNICAMENTE en el "I, ___,"/
    "Yo, ___," de las dos Declaration. Es una declaración personal de UNA
    persona, nunca colectiva — por eso no lleva a los riders aunque el
    resto del documento sí. **El ejemplo real de Sheraryn tenía "ET AL" en
    la Declaración en español — es un error de ese documento puntual, no
    la regla; la plantilla NO debe repetirlo** (confirmado explícitamente
    por el usuario).
  - Sin riders, los tres campos coinciden en valor — por eso esta
    distinción no se notó con el primer ejemplo (Insuasti).
  - Los 8 `<w:sdt>` de `cliente_nombre` ya estaban separados uno por
    ocurrencia desde la cirugía original — el fix fue solo reasignar
    `grupos_sync_manual` en `field_map.json` (qué IDs van a cuál de los
    tres nombres) y agregar los dos derivados nuevos a
    `fill_engine._resolve_values` (`nombre_para_documento(case).upper()` y
    `case["cliente_nombre"].upper()`). **No hizo falta tocar el `.docx`.**
- **`traductor_abreviado` dejó de ser un campo derivado.** Se había
  calculado automáticamente ("Bruno Briz" → "Bruno B.", primer nombre +
  inicial del apellido) porque solo había un ejemplo. El segundo ejemplo
  (traductora Roxana Banks) firma "RB." (iniciales de ambos nombres, sin
  espacio) — un formato distinto, que confirma que NO hay una regla fija:
  cada quien abrevia su firma como quiere. Fix: `traductor_abreviado` pasó
  a ser un `campos_extra` de texto libre (se pide junto con `traductor` en
  cada corrida), ya no se calcula. Se borró el helper
  `_persona_abreviada` de `fill_engine.py` (quedó sin uso).
- **Nombre del despacho en el membrete**: se detectó que varía entre
  documentos reales ("KOSTIV & ASSOCIATES, P.C." en Insuasti, "KOSTIV
  CARDINAL INTERNATIONAL LAW GROUP" en Sheraryn, "Kostiv CARDINAL
  INTERNATIONAL LAW GROUP CORP." en `webex-motion`/John Negron, cada uno
  con teléfono distinto). Se le preguntó al usuario — **decisión: dejarlo
  fijo como está** (el de Insuasti, "KOSTIV & ASSOCIATES, P.C."), la
  variación entre documentos es solo cómo se tipeó cada vez, no una regla
  real a replicar. No cambiar esto sin que el usuario lo pida.
- Verificado con `motor.fill_engine.generar_documento` real, caso de
  prueba CON riders (replicando el patrón de Sheraryn): los tres formatos
  de `cliente_nombre` cayeron exactamente en los lugares correctos,
  incluyendo que la Declaración en español NO lleva "ET AL" (a diferencia
  del ejemplo real, que sí lo tenía por error). `traductor_abreviado`
  libre ("RB.") se insertó tal cual. Suite `tests/run_tests.py` sigue en
  10/10.

## `written-pleadings`: resaltado amarillo heredado + nombres largos rotos en 3 firmas (2026-08-25)

- El usuario generó un documento real (Sheraryn, con riders) con la
  plantilla y mandó capturas de pantalla comparándolo contra el documento
  real de referencia. Dos problemas visibles:
  1. **Todo el texto de los campos salía resaltado en amarillo.** El
     `.docx` de ejemplo original (Insuasti) traía `<w:highlight
     w:val="yellow"/>` en 61 lugares (probablemente el abogado resaltó el
     documento para revisarlo) — al copiar el `rPr` de cada run original
     al `sdtPr` de su SDT (para que el valor de reemplazo mantuviera el
     mismo formato), el resaltado se copió también sin querer. Fix:
     `re.sub(r"<w:highlight[^/]*/>", "", xml)` sobre TODO `document.xml`
     (no solo los campos) — el resaltado no debe estar en ningún lado de
     esta plantilla.
  2. **El nombre del cliente + "ET AL" se rompía a 2 líneas cayendo al
     margen izquierdo** en 3 renglones de firma (bajo el abogado, bajo
     cada Declaration en inglés/español) — el mismo bug ya documentado
     para `webex-motion` (ítem 8 del checklist): tabs + espacios literales
     calibrados para el nombre corto de Insuasti ("INSUASTI RUIZ, EDWIN
     ALBERTO", 29 caracteres) se quedan cortos con un nombre más largo
     ("MENDEZ RODRIGUEZ, SHERARYN MILENY ET AL", 40 caracteres). A
     diferencia de `webex-motion` (que se arregló con `w:ind w:left` real),
     acá se comparó directamente contra el `.docx` real de Sheraryn (que
     SÍ se ve bien) y se igualó la cantidad exacta de tabs que usa ese
     documento que funciona: de 5/6/7 tabs (+ hasta 22 espacios sueltos)
     a 4/4/5 tabs respectivamente en los 3 renglones — confirmado que los
     3 `paraId` coinciden exactamente entre ambos `.docx`, así que es la
     misma plantilla, solo con distinto padding. Ver
     `plantillas/written-pleadings/field_map.json` para los IDs exactos
     (`920000005`, `920000007`, `920000009`).
- **`dialecto_interprete` pasó a ser opcional.** Antes la validación
  genérica de `campos_extra` (ver ítem 17 del checklist) lo exigía como
  cualquier otro campo — pero el usuario aclaró que si no se especifica
  dialecto, debe quedar la línea en blanco original ("___________"), no
  bloquear la generación. Fix: nueva clave `"opcional": true` en su
  entrada de `registro.json` → `static/app.js` (`generarDocumento`) la
  respeta (`if (!c.opcional && !valor)`) → `fill_engine._resolve_values`
  convierte string vacío a `None` con `... or None` (si no, un string
  vacío SÍ es distinto de `None` y igual pisaría el placeholder con nada).
  Es el ÚNICO campo de esta plantilla con este tratamiento — los demás
  (`fecha_nta`, `cargo_removibilidad`, etc.) siguen siendo obligatorios
  porque su placeholder de fábrica es texto real del caso Insuasti (dejar
  uno vacío filtraría datos de ese caso a otro cliente), mientras que el
  placeholder de `dialecto_interprete` siempre fue un blanco genérico
  ("___________"), seguro de dejar como está.
- Las líneas de firma (imagen dinámica de abogado/preparador/traductor)
  YA se comportan así desde que se creó la plantilla — sin PNG cargado
  para esa persona, cae al texto de blanco de siempre (mismo mecanismo
  `_apply_firmas_imagen` de las demás plantillas). No hizo falta tocar
  nada ahí, solo confirmar que seguía intacto tras estos cambios.
- Verificado con `motor.fill_engine.generar_documento` real (caso con
  riders, replicando Sheraryn): `<w:highlight` = 0 ocurrencias en el
  documento generado, los 4 renglones con "MENDEZ RODRIGUEZ..." muestran
  4/4/5/0 tabs (coincide exacto con el documento real de referencia), y
  con `dialecto_interprete=""` el placeholder "___________" sigue
  presente en el XML. Suite `tests/run_tests.py` sigue en 10/10.

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

## Auditoría 2026-08-25: fixes de robustez + primera suite de tests

Auditoría completa a pedido del usuario ("hazle una auditoría... corrige
todo"). No se tocó layout de plantillas ni comportamiento de documentos; son
correcciones de robustez, código muerto y una suite de tests. Lo corregido:

- **`case_store.next_tab_letra` — incremento base-26 biyectivo.** Antes solo
  llegaba a "AA" (Z→AA) y de ahí se quedaba pegado (AA→AA). Ahora incrementa
  con acarreo: A..Z, AA, AB, ... AZ, BA, ... ZZ, AAA. Se replicó la misma
  lógica en `static/app.js` (`nextTabLetra`, usada por
  `nextLetterFromLastRow`) para que frontend y backend coincidan. Solo
  afectaba casos con 27+ exhibits.
- **`pdf_merge._ANIO_RE` — rango de años de la sugerencia.** Era
  `19[9]\d|20[0-3]\d` (1990-2039), dejaba de sugerir el año de reportes de
  país a partir de 2040. Ahora `19[89]\d|20\d\d` (1980-2099).
- **`app.py` — errores de datos de la tabla de exhibits ahora dan 400, no
  500.** `motor.exhibit_builder` lanza `ValueError` cuando falta país / año
  de Country Reports u OSAC / fecha de Biometrics Compliance. `api_generar`
  no lo atrapaba (solo `FillEngineError`/`ValidationError`) y caía al
  `except Exception` genérico → 500 "Error inesperado" sin pista. Se agregó
  `ValueError` a la tupla del 400, así el mensaje claro del builder llega al
  usuario. (Cubre también la trampa latente del default
  `_biometricos_por_defecto` con `fecha=None`: si alguna vez llega, ahora es
  un 400 legible en vez de un 500.)
- **`app.py` — `request.get_json(force=True)` sin body válido.** En
  `api_save_caso` y `api_generar` un body vacío/no-JSON hacía `None.get(...)`
  → 500 con traceback. Ahora `force=True, silent=True` + chequeo `isinstance
  dict` → 400 "El cuerpo de la petición no es JSON válido".
- **`app.py` — limpieza de evidencia huérfana al arrancar.** Los PDFs subidos
  viven en `output/_evidencia` indexados SOLO en memoria (`_EVIDENCIAS`).
  Tras reiniciar el servidor ese índice queda vacío, así que los archivos
  viejos son inalcanzables y solo ocupaban disco (se acumulaban sin límite).
  `_limpiar_evidencia_huerfana()` los borra en el bloque `if __name__ ==
  "__main__"` (NO al importar — los tests importan `app` sin borrar nada).
  **Nunca toca `output/` (los .docx/.pdf finales son entregables que el
  usuario puede no haber descargado todavía).**
- **Código muerto**: `by_id` sin usar en `fill_engine._apply_field_values`;
  doble asignación de `ultima_pagina` en `pdf_merge.combinar_portada_y_evidencia`.
- **Primera suite de tests: `tests/run_tests.py`.** Sin pytest (el entorno
  del despacho solo tiene requirements.txt) — se corre con `python3
  tests/run_tests.py`, sale con código ≠0 si algo falla. Cubre la clase de
  bug que ya se repitió varias veces: invariante de conteo de párrafos
  DESCRIPTION==PAGES en modo evidencia (fee+biometrics, biometrics-solo,
  country_conditions parcial, form_of_identity, supplemental, multi-
  categoría), subtítulo de Biometrics repetido por persona, fecha
  obligatoria, `next_tab_letra` base-26, y el rango de `_ANIO_RE`. 10 tests,
  todos en verde. **Correr esta suite antes de commitear cambios a
  `exhibit_builder`/`case_store`/`pdf_merge` — es la red que faltaba.**

### Puntos de la auditoría que NO se cambiaron (a propósito)

- **Numeración de páginas no idempotente.** Regenerar un Tab vuelve a avanzar
  `case["siguiente_pagina"]`. NO se cambió: es parte del diseño de
  "paginación continua por caso", y alterar cómo persisten los números de
  página es comportamiento que afecta el documento — el usuario controla
  "página inicial del lote" a mano y el frontend re-lee `siguiente_pagina`
  tras generar. Cambiarlo requeriría una decisión de producto explícita, no
  es un bug.
- **Alineación de Biometrics cuando un renglón envuelve a 2 líneas visuales.**
  Ya documentado arriba como no verificable en este sandbox (LibreOffice
  roto). No es corregible a ciegas por estructura XML.
- **Estado global + Flask multihilo.** Condición de carrera solo teórica con
  dos pestañas simultáneas; es una herramienta local monousuario. Un lock
  agregaría complejidad para ~cero beneficio real. Se deja anotado.
