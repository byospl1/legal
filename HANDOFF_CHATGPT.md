# Traspaso del proyecto — Sistema de llenado de plantillas EOIR (Kostiv Cardinal International Law Group)

> Documento de transferencia para retomar el proyecto en otro asistente (ChatGPT).
> Escrito 2026-08-26. La referencia viva y exhaustiva del proyecto es
> **`CLAUDE.md`** en la raíz del repo — este documento es un resumen curado
> para ponerte al día rápido; cuando necesites el detalle exacto de un bug o
> decisión, ese archivo tiene el historial completo párrafo por párrafo.

---

## 0. Lo más importante primero: lo que TÚ (con Word) puedes hacer que el entorno anterior NO

El asistente anterior (Claude Code) trabajó en un sandbox donde
**LibreOffice/`soffice` está roto** para convertir `.docx`→PDF (falla incluso
con un docx trivial). Consecuencia: **nunca se pudo verificar el render visual
real de ningún documento generado** — toda la verificación fue por inspección
de la estructura XML del `.docx` (unzip + revisar `word/document.xml`) y por
lo que el usuario reportaba viendo en su Word.

Si tú tienes Word (o una conversión docx→PDF confiable), tu mayor aporte es
**cerrar ese hueco de verificación visual**. Hay varias cosas marcadas como
"no verificadas visualmente" a lo largo de este documento y de `CLAUDE.md` —
son candidatas directas a que las abras en Word y confirmes/corrijas. Las tres
más importantes:

1. **Alineación de la columna PAGES con la columna DESCRIPTION en la tabla de
   exhibits** (Table of Contents del Tab I-589). Es la fuente de casi todos los
   bugs recientes. Ver §6 y §7.
2. **Saltos de página entre secciones** en `written-pleadings` y `webex-motion`.
   Ver §5 (plantillas) y `CLAUDE.md`.
3. **Firmas dinámicas** (imagen `wp:inline`) — que aparezcan una sola vez, sin
   sobreponerse ni flotar.

**Flujo sugerido para verificar visualmente:** genera un documento con el
sistema (`/api/generar` o `motor.fill_engine.generar_documento`), abre el
`.docx` en Word, y compáralo contra el resultado esperado. Si algo no cuadra,
el detalle exacto (qué texto, en qué línea cayó vs. dónde debía) es lo que
permite un arreglo quirúrgico en vez de adivinar.

---

## 1. Qué es el proyecto

Sistema interno del despacho **Kostiv Cardinal International Law Group Corp.**
para llenar plantillas de la corte de inmigración (EOIR) a partir de datos de
caso capturados en una interfaz web local. Genera:

- **Tabs de exhibits** (I-589) — portada + tabla de contenidos (exhibits) +
  páginas divisorias + Proof of Service, con evidencia PDF adjunta y numerada.
- **Motions** (webex, motion to withdraw en 3 variantes).
- **EOIR-33** (cambio de dirección — formulario federal AcroForm).
- **Written Pleadings** (+ Declaration + Certificate of Translation).

Es una herramienta **local, monousuario**, sin build step: Flask (Python) +
JavaScript plano + HTML. Corre en la máquina del despacho (Windows, con Word y
LibreOffice instalados vía `instalar.bat`).

**Idioma:** el usuario (Hugo, paralegal del despacho) habla español. Todo el
contenido de los documentos generados es en inglés (son escritos legales de EE.
UU.); la UI y la comunicación son en español.

---

## 2. Cómo correr / estructura de archivos

```
python3 app.py            # levanta el servidor Flask (UI en el navegador)
python3 tests/run_tests.py # suite de tests (sin pytest, salida != 0 si falla)
```

- `app.py` — servidor Flask. Endpoints de caso (`/api/casos`), subida de
  evidencia (`/api/evidencia`), generación (`/api/generar`), init
  (`/api/init`).
- `motor/fill_engine.py` — el motor: llena el `.docx`/`.dotx` reemplazando
  SDT/campos según `field_map.json`, arma tabla de exhibits y dividers vía
  `exhibit_builder.py`, inserta firmas como imagen.
- `motor/exhibit_builder.py` — construye el XML fijo de la tabla de exhibits y
  los dividers por categoría, usando fragmentos literales en
  `plantillas/<id>/fragments/`. **Es el archivo con más lógica delicada** (ver
  §6, §7).
- `motor/pdf_merge.py` — inserta y numera las páginas de evidencia dentro del
  PDF de portada ya convertido. También heurísticas de sugerencia (año, país)
  leyendo texto de las primeras páginas del PDF subido.
- `motor/pdf_form_fill.py` — llena el AcroForm de `EOIR_33.pdf` directo.
- `motor/pdf_tools.py` — conversión a PDF (Word/LibreOffice) y rasterización a
  imágenes para verificación visual en la UI. **← Esto es lo que estaba roto en
  el sandbox anterior; en tu entorno con Word debería funcionar.**
- `motor/ooxml_utils.py` — helpers de bajo nivel para manipular paquetes OOXML
  (unpack/rezip, relationships, content types, merge de runs). Usar estos en
  vez de reinventar manipulación de zip/XML.
- `motor/case_store.py` — persistencia de casos en JSON, numeración de página
  siguiente por caso, next tab letra.
- `static/index.html` + `static/app.js` — UI de una sola página, sin framework.
- `plantillas/registro.json` — fuente de verdad de qué plantillas existen.
- `plantillas/<id>/field_map.json` — mapeo de campos SDT → valores para cada
  plantilla.
- `plantillas/i589-tab-cover/fragments/*.xml` — fragmentos de XML literal
  extraídos una sola vez del `.dotx` original, usados para armar la tabla de
  exhibits con formato idéntico.
- `case_store/*.json` — **datos reales de clientes, NO se suben a git**
  (gitignored). Nunca dejar ahí archivos de prueba.

---

## 3. Reglas de negocio decididas explícitamente por el despacho (NO cambiar sin pedir)

Estas son decisiones del usuario/abogados, no preferencias de implementación.
Respétalas:

### Numeración de páginas
- **Solo se numeran las páginas de evidencia / PDFs adjuntos.** El número va al
  pie, esquina inferior derecha (reportlab, Times-Roman 11).
- **Las páginas propias de las plantillas NUNCA llevan número** (portada, tabla
  de exhibits, dividers, Proof of Service, el `.dotx` en sí). No agregar
  footer/PAGE field a ninguna plantilla — ya se intentó una vez y se revirtió.
- **Excepción:** Motion to Withdraw NO numera su evidencia (decisión del
  usuario). `combinar_portada_y_evidencia_exhibits(numerar=False)`.
- Bug ya corregido: PDFs escaneados con `/Rotate ≠ 0` hacían caer el número en
  la esquina visual equivocada. Fix: `page.transfer_rotation_to_content()`
  (pypdf) antes de calcular width/height. **No quitar esa llamada.**

### Firmas
- **Ninguna plantilla debe llevar firma quemada/anclada** (`wp:anchor` con
  imagen). Se eliminaron 4 firmas quemadas de las plantillas (i589-tab-cover,
  webex-motion ×2, written-pleadings — esta última del traductor, escondida en
  un cuadro de texto flotante).
- Las firmas se insertan dinámicamente como imagen `wp:inline` (nunca flota, no
  se sobrepone) vía el mecanismo `firmas_imagen` en `field_map.json` (SDT +
  archivo PNG en `firmas/<categoria>/<Nombre>.png`).
- Si no hay PNG para esa persona, cae al texto de línea de firma
  (`_______________________`), sin romper nada.

### Pluralización con riders (`plural_riders`)
- Cuando un caso tiene riders (varios respondents → nombre "NOMBRE et al"), los
  textos FIJOS de la plantilla que dicen "Respondent"/"Respondent's" se
  pluralizan.
- Se hace con una **lista curada de frases exactas** en
  `field_map["plural_riders"]`, NO con un `replace` genérico de "Respondent"
  (hay apariciones que nunca deben pluralizarse — placeholder del caption,
  tabla Form of Identity).

### "Modo evidencia" (patrón transversal, clave para entender exhibit_builder)
- Si una categoría tiene evidencia adjunta EN ALGUNA PARTE, los ítems/personas
  SIN su propio archivo se **omiten por completo** del documento (ni renglón,
  ni campo obligatorio).
- Sin NINGÚN archivo en toda la categoría ("modo manual"), se incluye TODO y
  todos los campos normalmente obligatorios se siguen exigiendo.
- Aplica a: Country Conditions (CC/OSAC), Fee (fee receipt/FBI fingerprint),
  Biometrics Compliance (por persona), Supplemental Evidence (por persona).

### Motion to Withdraw: exhibit sin evidencia se elimina
- Si solo se sube evidencia para algunos Exhibits, los Exhibits sin evidencia
  se eliminan por completo (página divisoria + mención en el párrafo NOTICE).
  Lógica en `motor/fill_engine._apply_missing_exhibit_dividers` y
  `_apply_notice_exhibits`, corriendo ANTES de `merge_runs_in_document_xml`.

---

## 4. Cómo funciona la tabla de exhibits (contexto para el bug recurrente)

La tabla "PROPOSED EXHIBITS FILED IN SUPPORT OF APPLICATION / TABLE OF CONTENTS"
tiene 3 columnas en una sola fila de Word por cada letra de Tab:

| TAB | DESCRIPTION | PAGES |
|-----|-------------|-------|
| D | Respondent's Declaration for Support of... | Pgs. 46-52 |

- **DESCRIPTION** (celda ancho 6300 twips): un párrafo `<w:p>` por ítem/documento.
- **PAGES** (celda ancho 1548 twips): párrafos paralelos con "Pgs. X-Y" o vacío.

**Regla física fundamental (causa de casi todos los bugs de esta tabla):**
Word alinea verticalmente las celdas de una fila por **altura acumulada real**,
NO por índice/conteo de párrafos. Si un párrafo de DESCRIPTION envuelve a 2+
líneas visuales pero PAGES solo reserva 1 párrafo para él, todo lo que sigue en
PAGES queda desplazado hacia arriba respecto a su renglón en DESCRIPTION.

Categorías (orden en `CATEGORY_ORDER`): `i589_application`,
`country_conditions`, `form_of_identity`, `supplemental_evidence`, `fee`.

Dos categorías son **dinámicas por persona** (líder + cada rider del caso):
- **Form of Identity** (`identidades`): uno o más documentos de identidad por
  persona (pasaporte, ID, etc.). Texto: "Respondent's/Rider's {NOMBRE} Passport
  from {país}".
- **Biometrics Compliance** (dentro de `fee`, lista `biometricos`): un renglón
  por persona con fecha de captura de huella.
- **Supplemental Evidence** (`declaraciones` + `documentos_se`): declaraciones/
  documentos por persona (Declaration/Psychological Report/News), más una lista
  libre de documentos sin persona asociada.

**Puntos de sincronización** (al agregar cualquier lista dinámica nueva, hay que
tocar TODOS estos, o las columnas se desalinean / la evidencia no se fusiona —
lección aprendida a golpes, ver el historial de bugs):
1. `_build_category_xml` / builder de DESCRIPTION.
2. `build_pages_cell_content` / builder de PAGES.
3. `build_exhibit_table` (call sites).
4. `app.py._resolver_paginas_evidencia` (resolución de páginas — el ORDEN de
   inserción debe coincidir con el orden en que DESCRIPTION/PAGES emiten).
5. `app.py` gate `tiene_evidencia` en `api_generar`.
6. `app.py` construcción de `docs_con_pagina` (lista de PDFs a fusionar).
7. frontend `collectExhibits()`.
8. frontend `recalcularPaginas()`.
9. frontend función de render + handler de subida.
10. cualquier early-return "fallback a un solo rango Pgs" (debe incluir la lista
    nueva en su condición "¿hay algo?").

---

## 5. Plantillas registradas (`plantillas/registro.json`)

| template_id | tipo | tabla exhibits |
|---|---|---|
| `i589-tab-cover` | Tab de exhibits (I-589) | sí |
| `webex-motion` | MOTION | no |
| `eoir-33-change-address` | PDF AcroForm fijo | no |
| `motion-withdraw-no-cooperation` | MOTION | no |
| `motion-withdraw-cancelation` | MOTION | no |
| `motion-withdraw-location-known` | MOTION — **BORRADOR, revisar con abogado** | no |
| `written-pleadings` | Written Pleadings + Declaration + Certificate of Translation | no |

Notas por plantilla:
- **`motion-withdraw-location-known`**: el texto narrativo lo redactó el
  asistente como borrador, NO está validado por abogado. El `nombre` en el
  registro incluye "(BORRADOR — revisar con abogado antes de usar)" — no quitar
  esa advertencia sin confirmación del despacho.
- **`written-pleadings`**: la plantilla más compleja. Se construyó desde un
  documento YA LLENADO (sin SDT de fábrica) — 32 campos SDT agregados a mano
  (rango de IDs `920000001`-`920000032`, ver `field_map.json["_notas"]`).
  Detalles críticos:
  - `cliente_nombre` NO es un solo campo, son **tres**:
    - `cliente_nombre_titulo` (Title Case, + "et al") — encabezado "Attorney for
      Respondent(s)" y caja "In the Matter of".
    - `cliente_nombre_mayus` (MAYÚSCULAS + "ET AL") — firmas y sello.
    - `cliente_nombre_lead_mayus` (MAYÚSCULAS, **NUNCA** "et al") — el "I, ___,"
      de las Declarations (es declaración personal de UNA persona).
  - Nombre del despacho: se fijó "KOSTIV CARDINAL INTERNATIONAL LAW GROUP" en
    esta plantilla (4 ocurrencias). NO tocar `webex-motion` (tiene su propia
    variante).
  - Tiene 3 saltos de página reales (`<w:pageBreakBefore/>`) agregados en 2
    pasos + recorte de relleno de párrafos vacíos redundante. **No verificado
    visualmente en el sandbox** — candidato a que confirmes en Word.

Para agregar una plantilla nueva: `analyze_template.py` → revisar `field_map.json`
a mano → si tiene tabla de exhibits, fragments + `exhibit_builder.py` →
registrar en `registro.json`. **Al analizar un `.docx` ya llenado, revisar
también `<w:txbxContent>` (cuadros de texto flotantes)** — `python-docx`
`.paragraphs` NO los recorre, y pueden esconder texto con datos reales o firmas
quemadas.

---

## 6. Historial de bugs corregidos (checklist — NO repetir)

Resumen de los problemas reales que se presentaron y su fix. El detalle
completo de cada uno está en `CLAUDE.md`. Los listo para que no reintroduzcas
ninguno:

1. Footer/numeración en portada de plantilla → revertido. Solo se numera
   evidencia.
2. Número de página en esquina equivocada en PDFs con `/Rotate` → fix con
   `transfer_rotation_to_content()`.
3. `_find_preceding_run` matcheaba `<w:rPr` por substring → usar patrones
   `<w:r>` y `<w:r `.
4. Punto final "invisible" al recortar párrafo NOTICE → insertar DENTRO del
   `<w:t>`.
5. Firma de Lorenzo quemada en i589-tab-cover → eliminada, reemplazada por
   mecanismo dinámico.
6. Firma duplicada en webex-motion (2 firmas ancladas) → eliminadas.
7. Pluralización "Respondent(s)" hardcodeada → generalizada a
   `field_map["plural_riders"]`.
8. Nombre largo rompía la firma en webex-motion → sangría real (`w:ind w:left`)
   en vez de tabs/espacios.
9. Saltos de página reales en webex-motion (intento de UN paso) → REVERTIDO. En
   written-pleadings la misma técnica funcionó en DOS pasos. La técnica es
   reutilizable (ver §8).
10. CC/OSAC exigía los dos años aunque solo se subiera uno → ambas validaciones
    (Python + JS) consultan qué subitem queda incluido.
11. Campo "Próxima audiencia" → autoformato MM/DD/AAAA → texto en palabras
    (frontend, evento `blur`).
12. Biometrics Compliance no anexaba PDFs y dejaba Fee/FBI sin evidencia → dos
    bugs por vivir FUERA del dict `evidencias`; fix en gate `tiene_evidencia` +
    `hay_evidencia_dinamica` en `frag_indices_incluidos`.
13. `next_tab_letra` pegado en "AA" tras la Z → incremento base-26 bijectivo con
    acarreo (Python + JS).
14. `_ANIO_RE` dejaba de reconocer años ≥2040 → `19[89]\d|20\d\d`.
15. Errores de datos en tabla de exhibits daban 500 en vez de 400 → `ValueError`
    agregado a la tupla del 400.
16. Body no-JSON → 500 con traceback → `get_json(force=True, silent=True)` +
    check `isinstance dict`.
17. `campos_extra` no se validaban como obligatorios → validación genérica en
    `static/app.js` (`generarDocumento`). Protege contra filtrar datos de otro
    caso (el placeholder grabado en el `.docx`).
18. Firma quemada #4 (del traductor, en cuadro de texto flotante de
    written-pleadings) → eliminada.
19. `cliente_nombre` en written-pleadings son 3 campos distintos (ver §5).
20. **"Pgs." de la 2da persona en Supplemental Evidence caía en la línea
    envuelta de la 1ra.** Es el fix MÁS RECIENTE — ver §7 completo.

---

## 7. El fix más reciente en detalle: alineación de PAGES estimando líneas visuales

**Este es el estado en el que quedó el proyecto. Es importante que lo entiendas
porque toca la lógica más delicada y porque es candidato a verificación visual
en tu Word.**

### El problema (confirmado con captura real del usuario)
En un Tab de Supplemental Evidence con líder + 1 rider, ambos con declaración:
- El texto del líder ("Respondent's Declaration for Support of Asylum
  Withholding of Removal and Relief Under CAT.") es **fijo** y siempre envuelve
  a **2 líneas visuales** en Word.
- "Pgs. 46-52" caía bien junto a la 1ra línea del líder, pero "Pgs. 53-59" (del
  rider) caía junto a la 2da línea envuelta del líder, no junto al renglón del
  rider.

### Intento fallido (revertido): spacer entre documentos
Se metió un párrafo vacío (`spacer`) entre cada documento en ambas columnas.
Estuvo MAL: (1) agregaba una línea en blanco visible no deseada en DESCRIPTION,
y (2) 1 spacer aporta 1 línea de compensación, pero el líder envuelve a 2 líneas
→ seguía desalineado. **No reintentar con un separador fijo.**

### Fix correcto (el que quedó)
Estimar cuántas líneas visuales envuelve el texto de CADA documento, y en PAGES
poner el valor ("Pgs. X-Y") seguido de `(líneas_visuales - 1)` párrafos `blank`
de relleno. DESCRIPTION queda SIN separadores (documentos consecutivos).

- Nuevo `_estimar_lineas_visuales(texto)` en `motor/exhibit_builder.py`: simula
  el corte de línea greedy de Word usando las métricas Times-Roman de
  **reportlab** (`pdfmetrics.stringWidth`, dependencia que ya existe), contra el
  ancho útil de la celda DESCRIPTION `_DESC_CELL_ANCHO_UTIL_PTS` (6300 twips −
  108 twips de margen por lado = 6084 twips ≈ 304.2 pt).
- **Calibrado contra la captura real:** da exactamente 2 líneas para el líder y
  3 para el rider "MORALES-ZUNIGA, YORLENY SARAHI", cortando en los mismos
  puntos que Word. Resultado para ese caso: PAGES = `[Pgs. 46-52, blank, Pgs.
  53-59, blank, blank]`.
- Helper compartido `_supplemental_evidence_items()` para que DESCRIPTION y
  PAGES nunca divergan en qué documentos incluyen, en qué orden, ni con qué
  texto.

### ⚠️ Lo que TÚ (con Word) deberías verificar y potencialmente mejorar
- `_estimar_lineas_visuales` es una **ESTIMACIÓN** de métricas de fuente. Se
  calibró para reproducir una captura concreta, pero **nunca se vio el render
  real de Word**. Ábrelo en Word con casos variados (nombres de rider largos,
  títulos de News largos) y confirma que cada "Pgs." cae junto a la primera
  línea de su renglón. Si algún caso se corre, ajusta el ancho de celda asumido
  o revisa el margen real de la celda.
- **La MISMA técnica es aplicable a Biometrics Compliance**, que hoy sigue con
  el enfoque viejo (1 párrafo por persona + subtítulo repetido) y tiene la misma
  limitación sin resolver. NO se tocó porque el usuario no reportó que esté mal.
  Si al verificar en Word ves que Biometrics también se desalinea cuando un
  renglón envuelve, reusar `_estimar_lineas_visuales` ahí con el mismo patrón
  (valor + `(líneas-1)` blanks por renglón).

### Tests
`tests/run_tests.py` (sin pytest, `python3 tests/run_tests.py`, 15/15 en verde).
El viejo invariante "DESCRIPTION y PAGES con igual número de párrafos" ya NO
aplica a supplemental_evidence (PAGES tiene más párrafos: los blanks de
compensación). Se reemplazó por `_assert_supplemental_alineado`, que verifica la
invariante REAL: cada "Pgs." cae en una línea visual donde EMPIEZA un renglón de
DESCRIPTION, nunca en una línea envuelta. **Correr esta suite antes de commitear
cambios a `exhibit_builder`/`case_store`/`pdf_merge`.**

---

## 8. Técnica general: saltos de página reales reemplazando relleno de párrafos vacíos

Varias plantillas fingen saltos de página entre secciones con runs largos de
párrafos vacíos (en vez de `<w:pageBreakBefore/>` real). Eso hace que una línea
se desborde y quede huérfana. Al arreglarlo:

- **webex-motion (un solo paso: agregar salto Y quitar relleno a la vez):
  "se arruinó el formato", REVERTIDO.** No reintentar en webex-motion sin pedido
  explícito y verificación visual real.
- **written-pleadings (dos pasos separados): funcionó.**
  1. Agregar `<w:pageBreakBefore/>` real, SIN tocar el relleno todavía.
  2. Solo tras confirmar que sobran páginas en blanco, quitar el relleno
     redundante inmediatamente anterior a cada salto.
- Cuidado con cuadros de texto flotantes: usar un tokenizer con profundidad real
  de `<w:p>` (ignorar `<w:p .../>` autocontenido), no un regex no-greedy que
  confunde párrafos internos del cuadro con párrafos del cuerpo.

Con Word tienes ventaja aquí: puedes ver el resultado y hacer el paso 2 con
confianza en vez de a ciegas.

---

## 9. Archivos que NO se deben modificar sin instrucción explícita

- `plantillas/*/*.dotx` y `plantillas/*/*.docx` — plantillas originales del
  despacho. Cambios de layout/footer/margen requieren confirmar primero.
- `plantillas/eoir-33-change-address/EOIR_33.pdf` — formulario federal fijo.
- `case_store/*.json` — datos reales de clientes, gitignored. No crear/dejar
  archivos de prueba ahí; si un test los genera, borrarlos antes de terminar.

---

## 10. Convenciones de trabajo (del entorno anterior — adáptalas a tu setup)

- **Git:** rama de desarrollo `claude/eoir-tabs-fill-system-yohzk1`. Siempre
  crear commits nuevos, nunca amend sin pedido. En el entorno anterior `git
  push` fallaba con 403 (sin acceso GitHub) y la entrega se hacía empaquetando
  los archivos modificados en un zip. En tu entorno probablemente puedas pushear
  normal — confírmalo.
- **No hay pytest** en la máquina del despacho — solo lo de `requirements.txt`.
  La suite se corre con `python3 tests/run_tests.py`.
- **Verificación:** históricamente por inspección de XML (unzip del `.docx`) por
  el sandbox roto. **Tú deberías poder verificar visualmente en Word — úsalo.**

---

## 11. Estado actual / punto de retomada

- Última entrega: fix de alineación de PAGES en Supplemental Evidence estimando
  líneas visuales (§7). 15/15 tests en verde.
- Features recientes completas: selector de tipo por documento/persona en
  Supplemental Evidence (Declaration/Psychological Report/News); Form of Identity
  con más de un documento por persona; Biometrics Compliance por persona con
  "modo evidencia".
- **Pendiente natural (para ti, con Word):** verificación visual de todo lo
  marcado "no verificado visualmente" en este documento y en `CLAUDE.md` —
  especialmente la alineación PAGES/DESCRIPTION en casos con textos que
  envuelven, los saltos de página de written-pleadings, y las firmas dinámicas.
  Si encuentras un desalineamiento, el detalle exacto (texto + línea observada
  vs. esperada) es lo que permite el arreglo preciso.

> Para el detalle exhaustivo de cualquier punto, `CLAUDE.md` en la raíz del repo
> es la referencia completa. Este documento es el mapa; ese archivo es el
> territorio.
