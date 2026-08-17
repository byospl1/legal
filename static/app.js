let CATALOGOS = null;
let PLANTILLAS = [];
let ITEMS_POR_CATEGORIA = {};
let TIPOS_DOCUMENTO_IDENTIDAD = ["Passport", "Birth Certificate", "ID"];
let TIPOS_SUPPLEMENTAL_EVIDENCE = ["Declaration", "Psychological Report", "News"];
let CURRENT_CASE_ID = null;
let CURRENT_CASE_RIDERS = [];
let tabCounter = 0;

const CATEGORIA_ORDEN = ["i589_application", "country_conditions", "form_of_identity", "supplemental_evidence", "fee"];

const $ = (sel) => document.querySelector(sel);

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
  return data;
}

function fillDatalist(id, values) {
  const dl = document.getElementById(id);
  dl.innerHTML = values.map((v) => `<option value="${escapeHtml(v)}">`).join("");
}

function fillSelect(id, values, placeholder) {
  const sel = document.getElementById(id);
  sel.innerHTML =
    (placeholder ? `<option value="">${escapeHtml(placeholder)}</option>` : "") +
    values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Formatea un A# insertando "-" cada 3 dígitos (ej. "333999888" ->
 * "333-999-888"), preservando el prefijo "A" si el usuario lo escribió. */
function formatANumber(raw) {
  const trimmed = raw.trimStart();
  const hasPrefix = /^A/i.test(trimmed);
  const resto = hasPrefix ? trimmed.slice(1) : trimmed;
  const digitos = resto.replace(/\D/g, "").slice(0, 9);
  const agrupado = digitos.match(/.{1,3}/g)?.join("-") || "";
  if (!hasPrefix) return agrupado;
  return agrupado ? `A ${agrupado}` : "A";
}

/** Ata el formateo automático de A# a un <input>, preservando la posición
 * del cursor cuando el usuario edita en medio del texto (no solo al final). */
function attachANumberFormatter(input) {
  input.addEventListener("input", () => {
    const before = input.value;
    const cursorBefore = input.selectionStart ?? before.length;
    const digitsBeforeCursor = before.slice(0, cursorBefore).replace(/\D/g, "").length;
    const formatted = formatANumber(before);
    input.value = formatted;
    let seen = 0;
    let pos = formatted.length;
    for (let i = 0; i < formatted.length; i++) {
      if (/\d/.test(formatted[i])) {
        seen++;
        if (seen === digitsBeforeCursor) {
          pos = i + 1;
          break;
        }
      }
    }
    if (digitsBeforeCursor === 0) pos = /^A/i.test(formatted) ? Math.min(2, formatted.length) : 0;
    input.setSelectionRange(pos, pos);
  });
}

async function init() {
  const data = await api("/api/init");
  CATALOGOS = data.catalogos;
  PLANTILLAS = data.plantillas;
  ITEMS_POR_CATEGORIA = data.items_por_categoria || {};
  TIPOS_DOCUMENTO_IDENTIDAD = data.tipos_documento_identidad || TIPOS_DOCUMENTO_IDENTIDAD;
  TIPOS_SUPPLEMENTAL_EVIDENCE = data.tipos_supplemental_evidence || TIPOS_SUPPLEMENTAL_EVIDENCE;

  fillDatalist("dlCorteSede", CATALOGOS.corte_sede);
  fillDatalist("dlJuez", CATALOGOS.juez);
  fillDatalist("dlPreparador", CATALOGOS.preparador);
  fillSelect("abogado", CATALOGOS.abogado, "— elegir —");

  $("#plantilla").innerHTML = PLANTILLAS.map(
    (p) => `<option value="${p.template_id || p.grupo_id}">${escapeHtml(p.nombre)}</option>`
  ).join("");
  onPlantillaChange();

  const selCaso = $("#selCaso");
  selCaso.innerHTML =
    `<option value="">— Nuevo caso —</option>` +
    data.casos.map((c) => `<option value="${c.id}">${escapeHtml(c.cliente_nombre)} — ${escapeHtml(c.a_number)}</option>`).join("");

  renderSalidas(data.salidas);
}

function renderSalidas(salidas) {
  const tbody = $("#tablaSalidas tbody");
  tbody.innerHTML = "";
  $("#sinSalidas").style.display = salidas.length ? "none" : "block";
  for (const s of salidas) {
    const tr = document.createElement("tr");
    const previewLinks = s.previews
      .map((p, i) => `<a href="/output/_preview/${s.preview_dir}/${p}" target="_blank">pág. ${i + 1}</a>`)
      .join(" · ");
    tr.innerHTML = `
      <td>${s.docx ? `<a href="/output/${s.docx}" download>${s.docx}</a>` : '<span class="muted">—</span>'}</td>
      <td>${s.pdf ? `<a href="/output/${s.pdf}" download>${s.pdf}</a>` : '<span class="muted">no generado</span>'}</td>
      <td>${previewLinks || '<span class="muted">—</span>'}</td>
    `;
    tbody.appendChild(tr);
  }
}

function clearCaseForm() {
  CURRENT_CASE_ID = null;
  CURRENT_CASE_RIDERS = [];
  for (const id of ["cliente_nombre", "a_number", "corte_sede", "juez", "proxima_audiencia", "preparador"]) {
    $("#" + id).value = "";
  }
  $("#abogado").value = "";
  $("#selCaso").value = "";
  $("#casoStatus").textContent = "";
  $("#panelDocumento").style.display = "none";
  $("#ridersList").innerHTML = "";
}

function addRiderRow(rider) {
  const div = document.createElement("div");
  div.className = "row rider-row";
  div.style.marginTop = "6px";
  div.innerHTML = `
    <input type="text" class="rider-nombre" placeholder="Nombre del rider" style="flex:2; padding:8px 10px; border:1px solid var(--border); border-radius:6px;" value="${escapeHtml(rider?.nombre || "")}">
    <input type="text" class="rider-a-number" placeholder="A# del rider" style="flex:1; padding:8px 10px; border:1px solid var(--border); border-radius:6px;" value="${escapeHtml(rider?.a_number || "")}">
    <button type="button" class="danger" onclick="this.closest('.rider-row').remove()">Quitar</button>
  `;
  $("#ridersList").appendChild(div);
  attachANumberFormatter(div.querySelector(".rider-a-number"));
}

function collectRiders() {
  return [...document.querySelectorAll("#ridersList .rider-row")]
    .map((row) => ({
      nombre: row.querySelector(".rider-nombre").value.trim(),
      a_number: row.querySelector(".rider-a-number").value.trim(),
    }))
    .filter((r) => r.nombre || r.a_number);
}

async function loadCase(caseId) {
  if (!caseId) {
    clearCaseForm();
    return;
  }
  const c = await api(`/api/casos/${caseId}`);
  CURRENT_CASE_ID = c.id;
  CURRENT_CASE_RIDERS = c.riders || [];
  $("#cliente_nombre").value = c.cliente_nombre || "";
  $("#a_number").value = c.a_number || "";
  $("#corte_sede").value = c.corte_sede || "";
  $("#juez").value = c.juez || "";
  $("#proxima_audiencia").value = c.proxima_audiencia || "";
  $("#abogado").value = c.abogado || "";
  $("#preparador").value = c.preparador || "";
  $("#ridersList").innerHTML = "";
  for (const rider of c.riders || []) addRiderRow(rider);
  $("#casoStatus").textContent = "Caso cargado.";
  $("#panelDocumento").style.display = "block";
  tabCounter = 0;
  $("#tabsList").innerHTML = "";
  try {
    const p = await api(`/api/casos/${caseId}/siguiente-pagina`);
    $("#paginaInicialLote").value = p.siguiente_pagina;
  } catch {
    $("#paginaInicialLote").value = 1;
  }
  await addTabRow();
}

function collectCaseForm() {
  return {
    id: CURRENT_CASE_ID,
    cliente_nombre: $("#cliente_nombre").value.trim(),
    a_number: $("#a_number").value.trim(),
    corte_sede: $("#corte_sede").value.trim(),
    juez: $("#juez").value.trim(),
    proxima_audiencia: $("#proxima_audiencia").value.trim(),
    abogado: $("#abogado").value,
    preparador: $("#preparador").value.trim(),
    riders: collectRiders(),
  };
}

async function guardarCaso() {
  const status = $("#casoStatus");
  try {
    const caso = collectCaseForm();
    const saved = await api("/api/casos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(caso),
    });
    CURRENT_CASE_ID = saved.id;
    CURRENT_CASE_RIDERS = saved.riders || [];
    for (const card of document.querySelectorAll("#tabsList .tab-card")) renderIdentidadesUploads(card);
    status.textContent = `Caso guardado (${saved.id}).`;
    status.className = "muted";
    $("#panelDocumento").style.display = "block";
    if ($("#tabsList").children.length === 0) await addTabRow();

    const selCaso = $("#selCaso");
    if (![...selCaso.options].some((o) => o.value === saved.id)) {
      const opt = document.createElement("option");
      opt.value = saved.id;
      opt.textContent = `${saved.cliente_nombre} — ${saved.a_number}`;
      selCaso.appendChild(opt);
    }
    selCaso.value = saved.id;
  } catch (e) {
    status.textContent = "Error: " + e.message;
    status.className = "muted";
    status.style.color = "var(--err)";
  }
}

/** La plantilla elegida en #plantilla puede ser una plantilla "plana"
 * (template_id propio) o un GRUPO con varias variantes (ej. "Motion to
 * Withdraw" -> No Cooperation / Cancelation of Services) — devuelve la
 * entrada de nivel superior tal cual está en PLANTILLAS. */
function getPlantillaSeleccionada() {
  const value = $("#plantilla").value;
  return PLANTILLAS.find((p) => (p.template_id || p.grupo_id) === value);
}

/** La plantilla "efectiva" es la que realmente se usa para generar el
 * documento: si la seleccionada es un grupo, es la variante elegida en
 * #plantillaVariante (o la primera, por defecto); si no, es ella misma. */
function getPlantillaEfectiva() {
  const seleccionada = getPlantillaSeleccionada();
  if (!seleccionada) return null;
  if (seleccionada.variantes) {
    const varianteId = $("#plantillaVariante").value;
    return seleccionada.variantes.find((v) => v.template_id === varianteId) || seleccionada.variantes[0];
  }
  return seleccionada;
}

function onPlantillaChange() {
  const seleccionada = getPlantillaSeleccionada();
  const varianteField = $("#varianteField");
  const varianteSelect = $("#plantillaVariante");

  if (seleccionada && seleccionada.variantes) {
    varianteField.style.display = "block";
    varianteSelect.innerHTML = seleccionada.variantes
      .map((v) => `<option value="${escapeHtml(v.template_id)}">${escapeHtml(v.nombre)}</option>`)
      .join("");
  } else {
    varianteField.style.display = "none";
    varianteSelect.innerHTML = "";
  }

  actualizarUIPlantillaEfectiva();
}

function tituloOptionsFor(templateId) {
  return (CATALOGOS.titulo && CATALOGOS.titulo[templateId]) || [];
}

function actualizarUIPlantillaEfectiva() {
  const plantilla = getPlantillaEfectiva();
  const templateId = plantilla ? plantilla.template_id : null;
  const titulos = tituloOptionsFor(templateId);
  $("#titulo").innerHTML = titulos.map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
  const tieneExhibits = plantilla && plantilla.tiene_tabla_exhibits;
  $("#exhibitsSection").style.display = tieneExhibits ? "block" : "none";
  // con Tabs de exhibits, el título se elige por Tab (no todos son de la
  // misma categoría), así que el selector global se oculta para no
  // confundir — sigue poblado por debajo, se usa como respaldo.
  $("#tituloGlobalField").style.display = tieneExhibits ? "none" : "block";

  const camposExtra = (plantilla && plantilla.campos_extra) || [];
  const cont = $("#camposExtraSection");
  cont.style.display = camposExtra.length ? "grid" : "none";
  cont.innerHTML = camposExtra
    .map(
      (c) => `
    <div class="field">
      <label>${escapeHtml(c.etiqueta)}</label>
      <input type="text" class="campo-extra" data-nombre="${escapeHtml(c.nombre)}" placeholder="${escapeHtml(c.placeholder || "")}">
    </div>`
    )
    .join("");

  renderMotionExhibitsSection(plantilla);
}

function collectCamposExtra() {
  const out = {};
  for (const input of document.querySelectorAll("#camposExtraSection .campo-extra")) {
    out[input.dataset.nombre] = input.value.trim();
  }
  return out;
}

// { letra: [{evidencia_id, num_paginas, nombre}, ...] }
let MOTION_EXHIBITS_EVIDENCIA = {};

/** Reconstruye la sección "Evidencia de los Exhibits" (un uploader por
 * letra, ej. A/B/C) para plantillas que declaran evidencia_exhibits en su
 * field_map (Motion to Withdraw) — sin tabla de exhibits dinámica como los
 * Tabs, cada Exhibit ya tiene letra y descripción fijas. */
function renderMotionExhibitsSection(plantilla) {
  const exhibits = (plantilla && plantilla.evidencia_exhibits) || [];
  const section = $("#motionExhibitsSection");
  const cont = $("#motionExhibitsList");

  if (exhibits.length === 0) {
    section.style.display = "none";
    cont.innerHTML = "";
    MOTION_EXHIBITS_EVIDENCIA = {};
    return;
  }

  section.style.display = "block";
  const letrasActivas = new Set(exhibits.map((e) => e.letra));
  for (const letra of Object.keys(MOTION_EXHIBITS_EVIDENCIA)) {
    if (!letrasActivas.has(letra)) delete MOTION_EXHIBITS_EVIDENCIA[letra];
  }

  cont.innerHTML = exhibits
    .map(
      (e) => `
    <div class="field" style="margin-top:6px;">
      <label style="font-weight:400;">Exhibit ${escapeHtml(e.letra)} — ${escapeHtml(e.descripcion)}</label>
      <input type="file" class="motion-exhibit-upload-input" data-letra="${escapeHtml(e.letra)}" accept="application/pdf" multiple>
      <span class="muted motion-exhibit-upload-status" data-letra="${escapeHtml(e.letra)}"></span>
    </div>`
    )
    .join("");

  for (const input of cont.querySelectorAll(".motion-exhibit-upload-input")) {
    input.addEventListener("change", () => onMotionExhibitUpload(input));
  }
}

async function onMotionExhibitUpload(input) {
  const letra = input.dataset.letra;
  const statusEl = $(`.motion-exhibit-upload-status[data-letra="${letra}"]`);
  const files = [...input.files];
  if (files.length === 0) {
    delete MOTION_EXHIBITS_EVIDENCIA[letra];
    statusEl.textContent = "";
    return;
  }
  statusEl.textContent = "Subiendo…";
  const subidos = [];
  try {
    for (const file of files) {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/evidencia", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Error al subir ${file.name}`);
      subidos.push({ evidencia_id: data.evidencia_id, num_paginas: data.num_paginas, nombre: data.nombre });
    }
    MOTION_EXHIBITS_EVIDENCIA[letra] = subidos;
    const totalPaginas = subidos.reduce((sum, s) => sum + s.num_paginas, 0);
    statusEl.textContent = `${subidos.length} archivo(s), ${totalPaginas} página(s) en total.`;
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
    input.value = "";
    delete MOTION_EXHIBITS_EVIDENCIA[letra];
  }
}

function collectMotionExhibitsEvidencia() {
  const out = {};
  for (const [letra, subidos] of Object.entries(MOTION_EXHIBITS_EVIDENCIA)) {
    out[letra] = subidos.map((s) => s.evidencia_id);
  }
  return out;
}

const CATEGORIA_KEYS = ["i589_application", "country_conditions", "form_of_identity", "supplemental_evidence", "fee"];

async function siguienteLetra() {
  if (!CURRENT_CASE_ID) return "A";
  try {
    const r = await api(`/api/casos/${CURRENT_CASE_ID}/siguiente-letra`);
    return r.siguiente_letra;
  } catch {
    return "A";
  }
}

async function addTabRow() {
  tabCounter += 1;
  const n = tabCounter;
  const letraSugerida = $("#tabsList").children.length === 0 ? await siguienteLetra() : nextLetterFromLastRow();

  const plantilla = getPlantillaEfectiva();
  const templateId = plantilla ? plantilla.template_id : null;
  const titulos = tituloOptionsFor(templateId);
  const tituloActual = $("#titulo").value;
  const tituloOptionsHtml = titulos
    .map((t) => `<option value="${escapeHtml(t)}"${t === tituloActual ? " selected" : ""}>${escapeHtml(t)}</option>`)
    .join("");

  const div = document.createElement("div");
  div.className = "tab-card";
  div.dataset.n = n;
  div._evidencias = {}; // { itemKey: {evidencia_id, num_paginas, nombre} }
  div.innerHTML = `
    <div class="tab-head">
      <strong>Tab</strong>
      <button type="button" class="danger" onclick="this.closest('.tab-card').remove(); recalcularPaginas();">Quitar</button>
    </div>
    <div class="grid">
      <div class="field">
        <label>Letra del Tab</label>
        <input type="text" class="tab-letra" maxlength="2" value="${letraSugerida}">
      </div>
      <div class="field">
        <label>Páginas (ej. 15-29)</label>
        <input type="text" class="tab-paginas" placeholder="1-12">
      </div>
      <div class="field">
        <label>Título del documento de este Tab</label>
        <select class="tab-titulo">${tituloOptionsHtml}</select>
      </div>
    </div>
    <div class="categorias">
      ${CATEGORIA_KEYS.map((key) => {
        const cat = CATALOGOS.exhibit_categorias[key];
        return `
        <label class="categoria-opt">
          <input type="checkbox" class="cat-check" data-cat="${key}">
          <span>${escapeHtml(cat.etiqueta)}</span>
        </label>`;
      }).join("")}
    </div>
    <div class="pais-field field" style="display:none;">
      <label>País de origen del cliente</label>
      <input type="text" class="tab-pais" placeholder="ej. Mexico">
    </div>
    <div class="anio-fields grid" style="display:none; margin-top:6px; margin-left:24px;">
      <div class="field">
        <label>Año del Country Reports (Human Rights Practice)</label>
        <input type="text" class="tab-anio-cc" placeholder="ej. 2025">
      </div>
      <div class="field">
        <label>Año del OSAC Crime and Safety Report</label>
        <input type="text" class="tab-anio-osac" placeholder="ej. 2025">
      </div>
    </div>
    <div class="tipo-fee-field field" style="display:none; margin-top:6px; margin-left:24px; max-width:220px;">
      <label>Tipo de FEE (el ítem dirá "...Initial Fee Receipt..." o "...Annual Fee Receipt...")</label>
      <select class="tab-tipo-fee">
        <option value="">— sin especificar —</option>
        <option value="Initial">Initial</option>
        <option value="Annual">Annual</option>
      </select>
    </div>
    <div class="identidades-tab" style="margin-top:10px;"></div>
    <div class="documentos-tab" style="margin-top:10px;"></div>
    <div class="documentos-se-tab" style="margin-top:10px;"></div>
  `;
  $("#tabsList").appendChild(div);
  div._identidadesEvidencia = {};
  div._documentosSE = []; // [{ id, tipo, titulo, evidencia_id, num_paginas }]
  div._documentosSECounter = 0;

  const formOfIdentityCheck = div.querySelector('.cat-check[data-cat="form_of_identity"]');
  const countryConditionsCheck = div.querySelector('.cat-check[data-cat="country_conditions"]');
  const feeCheck = div.querySelector('.cat-check[data-cat="fee"]');
  const supplementalEvidenceCheck = div.querySelector('.cat-check[data-cat="supplemental_evidence"]');
  const paisField = div.querySelector(".pais-field");
  const anioFields = div.querySelector(".anio-fields");
  const tipoFeeField = div.querySelector(".tipo-fee-field");
  const actualizarCampos = () => {
    paisField.style.display = formOfIdentityCheck.checked || countryConditionsCheck.checked ? "block" : "none";
    anioFields.style.display = countryConditionsCheck.checked ? "grid" : "none";
    tipoFeeField.style.display = feeCheck.checked ? "block" : "none";
    renderIdentidadesUploads(div);
    renderDocumentUploads(div);
    renderDocumentosSE(div);
  };
  for (const chk of div.querySelectorAll(".cat-check")) {
    chk.addEventListener("change", actualizarCampos);
  }

  renderIdentidadesUploads(div);
  renderDocumentUploads(div);
  renderDocumentosSE(div);
  recalcularPaginas();
}

function personasDelCaso() {
  return [
    { key: "lead", nombre: null, label: "Respondent (líder del caso)" },
    ...CURRENT_CASE_RIDERS.map((r, i) => ({ key: `rider_${i}`, nombre: r.nombre, label: `Rider: ${r.nombre || "(sin nombre)"}` })),
  ];
}

/** Reconstruye las filas "tipo de documento + archivo" de Form of
 * Identity, una por persona del caso (líder + cada rider) — sin perder
 * los archivos ya subidos para personas que sigan en la lista. */
function renderIdentidadesUploads(card) {
  const cont = card.querySelector(".identidades-tab");
  const categorias = categoriasMarcadas(card);
  card._identidadesEvidencia = card._identidadesEvidencia || {};

  if (!categorias.includes("form_of_identity")) {
    cont.innerHTML = "";
    return;
  }

  const personas = personasDelCaso();
  const keysActivos = new Set(personas.map((p) => p.key));
  for (const key of Object.keys(card._identidadesEvidencia)) {
    if (!keysActivos.has(key)) delete card._identidadesEvidencia[key];
  }

  cont.innerHTML =
    `<label style="font-size:13px; font-weight:600; color:var(--text-dim);">Documento de identidad por persona (pasaporte, certificado de nacimiento o ID — uno por cada aplicante del caso)</label>` +
    personas
      .map(
        (p) => `
      <div class="grid" style="margin-top:6px;">
        <div class="field">
          <label style="font-weight:400;">${escapeHtml(p.label)} — tipo de documento</label>
          <select class="identidad-tipo-doc" data-persona-key="${p.key}">
            ${TIPOS_DOCUMENTO_IDENTIDAD.map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label style="font-weight:400;">Archivo (PDF)</label>
          <input type="file" class="identidad-upload-input" data-persona-key="${p.key}" accept="application/pdf">
          <span class="muted identidad-upload-status" data-persona-key="${p.key}"></span>
        </div>
      </div>`
      )
      .join("");

  for (const input of cont.querySelectorAll(".identidad-upload-input")) {
    input.addEventListener("change", () => onIdentidadUpload(card, input));
  }
}

async function onIdentidadUpload(card, input) {
  const key = input.dataset.personaKey;
  const statusEl = card.querySelector(`.identidad-upload-status[data-persona-key="${key}"]`);
  const file = input.files[0];
  card._identidadesEvidencia = card._identidadesEvidencia || {};
  if (!file) {
    delete card._identidadesEvidencia[key];
    statusEl.textContent = "";
    recalcularPaginas();
    return;
  }
  statusEl.textContent = "Subiendo…";
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("tipo", "identidad");
    const res = await fetch("/api/evidencia", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al subir el archivo");
    card._identidadesEvidencia[key] = { evidencia_id: data.evidencia_id, num_paginas: data.num_paginas };
    statusEl.textContent = `${data.num_paginas} página(s).`;
    recalcularPaginas();
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
    input.value = "";
    delete card._identidadesEvidencia[key];
  }
}

function categoriasMarcadas(card) {
  return [...card.querySelectorAll(".cat-check")].filter((c) => c.checked).map((c) => c.dataset.cat);
}

/** Reconstruye la lista de casillas "sube el PDF de este documento" según
 * las categorías marcadas en el Tab — sin perder los archivos que ya
 * estaban subidos si la categoría sigue marcada. */
function renderDocumentUploads(card) {
  const cont = card.querySelector(".documentos-tab");
  const categorias = categoriasMarcadas(card);
  const itemsActivos = [];
  for (const cat of CATEGORIA_ORDEN) {
    if (!categorias.includes(cat)) continue;
    for (const item of ITEMS_POR_CATEGORIA[cat] || []) {
      itemsActivos.push({ cat, ...item });
    }
  }

  // quita del estado los ítems que ya no aplican (categoría desmarcada)
  const keysActivos = new Set(itemsActivos.map((it) => it.key));
  for (const key of Object.keys(card._evidencias)) {
    if (!keysActivos.has(key)) delete card._evidencias[key];
  }

  if (itemsActivos.length === 0) {
    cont.innerHTML = "";
    return;
  }

  cont.innerHTML =
    `<label style="font-size:13px; font-weight:600; color:var(--text-dim);">Documentos de evidencia de este Tab (PDF, opcional — se insertan después de "EXHIBIT {letra}" y se numeran solos)</label>` +
    itemsActivos
      .map(
        (it) => `
      <div class="field" style="margin-top:6px;">
        <label style="font-weight:400;">${escapeHtml(it.label)}</label>
        <input type="file" class="doc-upload-input" data-item-key="${it.key}" accept="application/pdf">
        <span class="muted doc-upload-status" data-item-key="${it.key}"></span>
      </div>`
      )
      .join("");

  for (const input of cont.querySelectorAll(".doc-upload-input")) {
    input.addEventListener("change", () => onDocumentUpload(card, input));
  }
}

async function onDocumentUpload(card, input) {
  const itemKey = input.dataset.itemKey;
  const statusEl = card.querySelector(`.doc-upload-status[data-item-key="${itemKey}"]`);
  const file = input.files[0];
  if (!file) {
    delete card._evidencias[itemKey];
    statusEl.textContent = "";
    recalcularPaginas();
    return;
  }
  statusEl.textContent = "Subiendo…";
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("tipo", itemKey);
    const res = await fetch("/api/evidencia", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al subir el archivo");
    card._evidencias[itemKey] = { evidencia_id: data.evidencia_id, num_paginas: data.num_paginas };
    statusEl.textContent = `${data.num_paginas} página(s).`;

    if (itemKey === "country_reports" || itemKey === "osac") {
      const paisInput = card.querySelector(".tab-pais");
      const anioInput = card.querySelector(itemKey === "country_reports" ? ".tab-anio-cc" : ".tab-anio-osac");
      if (data.pais_sugerido && paisInput && !paisInput.value) paisInput.value = data.pais_sugerido;
      if (data.anio_sugerido && anioInput && !anioInput.value) anioInput.value = data.anio_sugerido;
    }
    if (itemKey === "fee_receipt") {
      const tipoFeeInput = card.querySelector(".tab-tipo-fee");
      if (data.tipo_fee_sugerido && tipoFeeInput && !tipoFeeInput.value) tipoFeeInput.value = data.tipo_fee_sugerido;
    }

    recalcularPaginas();
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
    input.value = "";
    delete card._evidencias[itemKey];
  }
}

/** Reconstruye la lista libre de documentos de Supplemental Evidence (0 a
 * N, típicamente 5-10): cada uno con su tipo (Declaration / Psychological
 * Report / News), su archivo, y — si es News — el título de la noticia
 * (se sugiere solo al subir el archivo, pero siempre editable). */
function renderDocumentosSE(card) {
  const cont = card.querySelector(".documentos-se-tab");
  const categorias = categoriasMarcadas(card);
  card._documentosSE = card._documentosSE || [];

  if (!categorias.includes("supplemental_evidence")) {
    cont.innerHTML = "";
    return;
  }

  if (card._documentosSE.length === 0) {
    agregarDocumentoSE(card, false);
  }

  cont.innerHTML =
    `<div class="row" style="justify-content:space-between;">
      <label style="font-size:13px; font-weight:600; color:var(--text-dim);">Documentos de Supplemental Evidence (normalmente entre 5 y 10)</label>
      <button type="button" class="btn-agregar-doc-se">+ Agregar documento</button>
    </div>` +
    card._documentosSE
      .map(
        (doc) => `
      <div class="tab-card doc-se-row" data-doc-id="${doc.id}" style="margin-top:8px;">
        <div class="grid">
          <div class="field">
            <label style="font-weight:400;">Tipo de documento</label>
            <select class="doc-se-tipo" data-doc-id="${doc.id}">
              ${TIPOS_SUPPLEMENTAL_EVIDENCE.map(
                (t) => `<option value="${escapeHtml(t)}" ${t === doc.tipo ? "selected" : ""}>${escapeHtml(t)}</option>`
              ).join("")}
            </select>
          </div>
          <div class="field">
            <label style="font-weight:400;">Archivo (PDF)</label>
            <input type="file" class="doc-se-upload-input" data-doc-id="${doc.id}" accept="application/pdf">
            <span class="muted doc-se-upload-status" data-doc-id="${doc.id}"></span>
          </div>
        </div>
        <div class="field doc-se-titulo-field" data-doc-id="${doc.id}" style="display:${doc.tipo === "News" ? "block" : "none"}; margin-top:6px;">
          <label style="font-weight:400;">Título de la noticia</label>
          <input type="text" class="doc-se-titulo" data-doc-id="${doc.id}" value="${escapeHtml(doc.titulo || "")}" placeholder="ej. extortionists caught">
        </div>
        <button type="button" class="danger doc-se-quitar" data-doc-id="${doc.id}" style="margin-top:6px;">Quitar documento</button>
      </div>`
      )
      .join("");

  cont.querySelector(".btn-agregar-doc-se").addEventListener("click", () => {
    agregarDocumentoSE(card, true);
    renderDocumentosSE(card);
    recalcularPaginas();
  });

  for (const sel of cont.querySelectorAll(".doc-se-tipo")) {
    sel.addEventListener("change", () => {
      const doc = card._documentosSE.find((d) => d.id === sel.dataset.docId);
      if (doc) doc.tipo = sel.value;
      const tituloField = cont.querySelector(`.doc-se-titulo-field[data-doc-id="${sel.dataset.docId}"]`);
      if (tituloField) tituloField.style.display = sel.value === "News" ? "block" : "none";
    });
  }
  for (const inp of cont.querySelectorAll(".doc-se-titulo")) {
    inp.addEventListener("input", () => {
      const doc = card._documentosSE.find((d) => d.id === inp.dataset.docId);
      if (doc) doc.titulo = inp.value;
    });
  }
  for (const input of cont.querySelectorAll(".doc-se-upload-input")) {
    input.addEventListener("change", () => onDocumentoSEUpload(card, input));
  }
  for (const btn of cont.querySelectorAll(".doc-se-quitar")) {
    btn.addEventListener("click", () => {
      card._documentosSE = card._documentosSE.filter((d) => d.id !== btn.dataset.docId);
      renderDocumentosSE(card);
      recalcularPaginas();
    });
  }
}

function agregarDocumentoSE(card, conRender) {
  card._documentosSECounter = (card._documentosSECounter || 0) + 1;
  card._documentosSE.push({
    id: `se_${card.dataset.n}_${card._documentosSECounter}`,
    tipo: "Declaration",
    titulo: "",
    evidencia_id: null,
    num_paginas: null,
  });
  if (conRender) renderDocumentosSE(card);
}

async function onDocumentoSEUpload(card, input) {
  const docId = input.dataset.docId;
  const doc = card._documentosSE.find((d) => d.id === docId);
  const statusEl = card.querySelector(`.doc-se-upload-status[data-doc-id="${docId}"]`);
  const file = input.files[0];
  if (!doc) return;
  if (!file) {
    doc.evidencia_id = null;
    doc.num_paginas = null;
    statusEl.textContent = "";
    recalcularPaginas();
    return;
  }
  statusEl.textContent = "Subiendo…";
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("tipo", doc.tipo === "News" ? "news" : "supplemental_evidence");
    const res = await fetch("/api/evidencia", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al subir el archivo");
    doc.evidencia_id = data.evidencia_id;
    doc.num_paginas = data.num_paginas;
    statusEl.textContent = `${data.num_paginas} página(s).`;
    if (doc.tipo === "News" && data.titulo_sugerido && !doc.titulo) {
      doc.titulo = data.titulo_sugerido;
      const tituloInput = card.querySelector(`.doc-se-titulo[data-doc-id="${docId}"]`);
      if (tituloInput) tituloInput.value = data.titulo_sugerido;
    }
    recalcularPaginas();
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
    input.value = "";
    doc.evidencia_id = null;
    doc.num_paginas = null;
  }
}

/** Recalcula, en orden (Tab por Tab, categoría por categoría, documento por
 * documento), la página de inicio de cada documento subido — encadenado
 * desde la "página inicial de este lote" que confirma el usuario. Actualiza
 * el campo "Páginas" de cada Tab (de solo lectura si tiene algún documento
 * adjunto) y el texto de cada casilla de subida. */
function recalcularPaginas() {
  let pagina = parseInt($("#paginaInicialLote")?.value, 10) || 1;
  for (const card of document.querySelectorAll("#tabsList .tab-card")) {
    const paginasInput = card.querySelector(".tab-paginas");
    const categorias = categoriasMarcadas(card);
    let inicioTab = null;
    let huboDocumento = false;

    for (const cat of CATEGORIA_ORDEN) {
      if (!categorias.includes(cat)) continue;
      if (cat === "form_of_identity") {
        for (const persona of personasDelCaso()) {
          const info = (card._identidadesEvidencia || {})[persona.key];
          const statusEl = card.querySelector(`.identidad-upload-status[data-persona-key="${persona.key}"]`);
          if (!info) continue;
          huboDocumento = true;
          if (inicioTab === null) inicioTab = pagina;
          const inicioDoc = pagina;
          pagina += info.num_paginas;
          if (statusEl) statusEl.textContent = `${info.num_paginas} página(s) — empieza en la página ${inicioDoc}.`;
        }
        continue;
      }
      if (cat === "supplemental_evidence") {
        for (const doc of card._documentosSE || []) {
          const statusEl = card.querySelector(`.doc-se-upload-status[data-doc-id="${doc.id}"]`);
          if (!doc.evidencia_id) continue;
          huboDocumento = true;
          if (inicioTab === null) inicioTab = pagina;
          const inicioDoc = pagina;
          pagina += doc.num_paginas;
          if (statusEl) statusEl.textContent = `${doc.num_paginas} página(s) — empieza en la página ${inicioDoc}.`;
        }
        continue;
      }
      for (const item of ITEMS_POR_CATEGORIA[cat] || []) {
        const info = card._evidencias[item.key];
        const statusEl = card.querySelector(`.doc-upload-status[data-item-key="${item.key}"]`);
        if (!info) continue;
        huboDocumento = true;
        if (inicioTab === null) inicioTab = pagina;
        const inicioDoc = pagina;
        pagina += info.num_paginas;
        if (statusEl) statusEl.textContent = `${info.num_paginas} página(s) — empieza en la página ${inicioDoc}.`;
      }
    }

    if (huboDocumento) {
      const finTab = pagina - 1;
      paginasInput.value = inicioTab === finTab ? String(inicioTab) : `${inicioTab}-${finTab}`;
      paginasInput.readOnly = true;
    } else {
      paginasInput.readOnly = false;
    }
  }
}

function nextLetterFromLastRow() {
  const rows = $("#tabsList").querySelectorAll(".tab-card .tab-letra");
  if (!rows.length) return "A";
  const last = rows[rows.length - 1].value.trim().toUpperCase();
  if (last.length === 1 && last >= "A" && last < "Z") return String.fromCharCode(last.charCodeAt(0) + 1);
  return "";
}

function collectExhibits() {
  const cards = [...document.querySelectorAll("#tabsList .tab-card")];
  return cards.map((card) => {
    const letra = card.querySelector(".tab-letra").value.trim();
    const paginas = card.querySelector(".tab-paginas").value.trim();
    const tituloSel = card.querySelector(".tab-titulo");
    const titulo = tituloSel ? tituloSel.value : null;
    const categorias = categoriasMarcadas(card);
    const necesitaPais = categorias.includes("form_of_identity") || categorias.includes("country_conditions");
    const pais = necesitaPais ? card.querySelector(".tab-pais").value.trim() : null;
    const necesitaAnios = categorias.includes("country_conditions");
    const anio_cc = necesitaAnios ? card.querySelector(".tab-anio-cc").value.trim() : null;
    const anio_osac = necesitaAnios ? card.querySelector(".tab-anio-osac").value.trim() : null;
    const tipo_fee = categorias.includes("fee") ? card.querySelector(".tab-tipo-fee").value.trim() || null : null;
    const evidencias = {};
    for (const [key, info] of Object.entries(card._evidencias || {})) {
      evidencias[key] = info.evidencia_id;
    }
    const identidades = categorias.includes("form_of_identity")
      ? personasDelCaso().map((p) => {
          const tipoDocSel = card.querySelector(`.identidad-tipo-doc[data-persona-key="${p.key}"]`);
          const info = (card._identidadesEvidencia || {})[p.key];
          return {
            persona_nombre: p.nombre,
            tipo_doc: tipoDocSel ? tipoDocSel.value : "Passport",
            evidencia_id: info ? info.evidencia_id : null,
          };
        })
      : [];
    const documentos_se = categorias.includes("supplemental_evidence")
      ? (card._documentosSE || []).map((doc) => ({
          tipo: doc.tipo,
          titulo: doc.titulo || null,
          evidencia_id: doc.evidencia_id,
        }))
      : [];
    return { letra, paginas, titulo, categorias, pais, anio_cc, anio_osac, tipo_fee, evidencias, identidades, documentos_se };
  });
}

async function generarDocumento() {
  const resultado = $("#resultado");
  const spinner = $("#generarSpinner");
  const btn = $("#btnGenerar");
  resultado.innerHTML = "";

  if (!CURRENT_CASE_ID) {
    resultado.innerHTML = `<div class="status err">Primero guarda el caso (paso 1).</div>`;
    return;
  }

  const plantilla = getPlantillaEfectiva();
  const templateId = plantilla ? plantilla.template_id : null;
  const exhibits = plantilla && plantilla.tiene_tabla_exhibits ? collectExhibits() : [];

  for (const tg of exhibits) {
    if (!tg.letra || !tg.paginas || tg.categorias.length === 0) {
      resultado.innerHTML = `<div class="status err">Cada Tab necesita letra, páginas y al menos una categoría seleccionada.</div>`;
      return;
    }
    if ((tg.categorias.includes("form_of_identity") || tg.categorias.includes("country_conditions")) && !tg.pais) {
      resultado.innerHTML = `<div class="status err">Falta el país de origen del cliente para el Tab ${tg.letra}.</div>`;
      return;
    }
    if (tg.categorias.includes("country_conditions") && (!tg.anio_cc || !tg.anio_osac)) {
      resultado.innerHTML = `<div class="status err">Falta el año del Country Reports y/o del OSAC para el Tab ${tg.letra}.</div>`;
      return;
    }
  }

  const document_instance = {
    template_id: templateId,
    titulo: (exhibits[0] && exhibits[0].titulo) || $("#titulo").value,
    exhibits,
    exhibits_evidencia: collectMotionExhibitsEvidencia(),
    pagina_inicial_exhibits: parseInt($("#motionExhibitsPaginaInicial").value, 10) || 1,
    ...collectCamposExtra(),
  };
  const hayEvidencia = exhibits.some(
    (tg) =>
      (tg.evidencias && Object.keys(tg.evidencias).length > 0) ||
      (tg.identidades || []).some((i) => i.evidencia_id) ||
      (tg.documentos_se || []).some((d) => d.evidencia_id)
  );
  const separar_por_tab = hayEvidencia ? true : $("#separarPorTab").checked;
  const generar_pdf = hayEvidencia ? true : $("#generarPdf").checked;
  const pagina_inicial_lote = parseInt($("#paginaInicialLote").value, 10) || 1;

  btn.disabled = true;
  spinner.style.display = "inline-block";
  try {
    const r = await api("/api/generar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: CURRENT_CASE_ID, document_instance, separar_por_tab, generar_pdf, pagina_inicial_lote }),
    });

    let html = "";
    if (r.documentos.length > 1) {
      html += `<div class="status ok">${r.documentos.length} documentos generados (uno por Tab).</div>`;
    }
    for (const doc of r.documentos) {
      html += `<div class="tab-card">`;
      if (doc.validation_ok) {
        html += `<div class="status ok">Documento generado y validado correctamente.</div>`;
      } else {
        html += `<div class="status err">El documento se generó pero no pasó la validación:\n${doc.validation_errors.join("\n")}</div>`;
      }
      if (generar_pdf && !doc.pdf_generado) {
        html += `<div class="status warn">No se pudo generar el PDF (revisa que Word/LibreOffice estén disponibles). El .docx sí se generó — ábrelo y revísalo antes de usarlo.</div>`;
      }
      if (doc.evidencia_fusionada && !doc.evidencia_error) {
        html += `<div class="status ok">Evidencia insertada después de la divisoria y numerada dentro del PDF.</div>`;
      }
      if (doc.evidencia_error) {
        html += `<div class="status err">${escapeHtml(doc.evidencia_error)}</div>`;
      }
      html += `<div class="result-links">
        ${doc.docx_url ? `<a href="${doc.docx_url}" download>Descargar .docx</a>` : ""}
        ${doc.pdf_url ? `<a href="${doc.pdf_url}" target="_blank">Ver PDF</a>` : ""}
        ${doc.pdf_url && !doc.docx_url ? `<a href="${doc.pdf_url}" download>Descargar PDF</a>` : ""}
      </div>`;
      if (doc.preview_urls && doc.preview_urls.length) {
        html += `<div class="previews">` + doc.preview_urls.map((u) => `<a href="${u}" target="_blank"><img src="${u}"></a>`).join("") + `</div>`;
      }
      html += `</div>`;
    }
    resultado.innerHTML = html;

    if (r.siguiente_pagina) $("#paginaInicialLote").value = r.siguiente_pagina;

    const data = await api("/api/init");
    renderSalidas(data.salidas);
  } catch (e) {
    resultado.innerHTML = `<div class="status err">Error: ${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    spinner.style.display = "none";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  init();
  attachANumberFormatter($("#a_number"));
  $("#selCaso").addEventListener("change", (e) => loadCase(e.target.value));
  $("#btnNuevoCaso").addEventListener("click", clearCaseForm);
  $("#btnGuardarCaso").addEventListener("click", guardarCaso);
  $("#plantilla").addEventListener("change", onPlantillaChange);
  $("#plantillaVariante").addEventListener("change", actualizarUIPlantillaEfectiva);
  $("#btnAgregarTab").addEventListener("click", addTabRow);
  $("#btnAgregarRider").addEventListener("click", () => addRiderRow());
  $("#btnGenerar").addEventListener("click", generarDocumento);
  $("#paginaInicialLote").addEventListener("input", recalcularPaginas);
});
