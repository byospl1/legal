let CATALOGOS = null;
let PLANTILLAS = [];
let ITEMS_POR_CATEGORIA = {};
let CURRENT_CASE_ID = null;
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

async function init() {
  const data = await api("/api/init");
  CATALOGOS = data.catalogos;
  PLANTILLAS = data.plantillas;
  ITEMS_POR_CATEGORIA = data.items_por_categoria || {};

  fillDatalist("dlCorteSede", CATALOGOS.corte_sede);
  fillDatalist("dlJuez", CATALOGOS.juez);
  fillDatalist("dlPreparador", CATALOGOS.preparador);
  fillSelect("abogado", CATALOGOS.abogado, "— elegir —");

  $("#plantilla").innerHTML = PLANTILLAS.map(
    (p) => `<option value="${p.template_id}">${escapeHtml(p.nombre)}</option>`
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
      <td><a href="/output/${s.docx}" download>${s.docx}</a></td>
      <td>${s.pdf ? `<a href="/output/${s.pdf}" target="_blank">Ver PDF</a>` : '<span class="muted">no generado</span>'}</td>
      <td>${previewLinks || '<span class="muted">—</span>'}</td>
    `;
    tbody.appendChild(tr);
  }
}

function clearCaseForm() {
  CURRENT_CASE_ID = null;
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

function onPlantillaChange() {
  const templateId = $("#plantilla").value;
  const plantilla = PLANTILLAS.find((p) => p.template_id === templateId);
  const titulos = (CATALOGOS.titulo && CATALOGOS.titulo[templateId]) || [];
  $("#titulo").innerHTML = titulos.map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
  $("#exhibitsSection").style.display = plantilla && plantilla.tiene_tabla_exhibits ? "block" : "none";
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
    <div class="documentos-tab" style="margin-top:10px;"></div>
  `;
  $("#tabsList").appendChild(div);

  const formOfIdentityCheck = div.querySelector('.cat-check[data-cat="form_of_identity"]');
  const countryConditionsCheck = div.querySelector('.cat-check[data-cat="country_conditions"]');
  const paisField = div.querySelector(".pais-field");
  const anioFields = div.querySelector(".anio-fields");
  const actualizarCampos = () => {
    paisField.style.display = formOfIdentityCheck.checked || countryConditionsCheck.checked ? "block" : "none";
    anioFields.style.display = countryConditionsCheck.checked ? "grid" : "none";
    renderDocumentUploads(div);
  };
  for (const chk of div.querySelectorAll(".cat-check")) {
    chk.addEventListener("change", actualizarCampos);
  }

  renderDocumentUploads(div);
  recalcularPaginas();
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

    recalcularPaginas();
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
    input.value = "";
    delete card._evidencias[itemKey];
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
    const categorias = categoriasMarcadas(card);
    const necesitaPais = categorias.includes("form_of_identity") || categorias.includes("country_conditions");
    const pais = necesitaPais ? card.querySelector(".tab-pais").value.trim() : null;
    const necesitaAnios = categorias.includes("country_conditions");
    const anio_cc = necesitaAnios ? card.querySelector(".tab-anio-cc").value.trim() : null;
    const anio_osac = necesitaAnios ? card.querySelector(".tab-anio-osac").value.trim() : null;
    const evidencias = {};
    for (const [key, info] of Object.entries(card._evidencias || {})) {
      evidencias[key] = info.evidencia_id;
    }
    return { letra, paginas, categorias, pais, anio_cc, anio_osac, evidencias };
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

  const templateId = $("#plantilla").value;
  const plantilla = PLANTILLAS.find((p) => p.template_id === templateId);
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
    titulo: $("#titulo").value,
    exhibits,
  };
  const hayEvidencia = exhibits.some((tg) => tg.evidencias && Object.keys(tg.evidencias).length > 0);
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
        <a href="${doc.docx_url}" download>Descargar .docx</a>
        ${doc.pdf_url ? `<a href="${doc.pdf_url}" target="_blank">Ver PDF</a>` : ""}
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
  $("#selCaso").addEventListener("change", (e) => loadCase(e.target.value));
  $("#btnNuevoCaso").addEventListener("click", clearCaseForm);
  $("#btnGuardarCaso").addEventListener("click", guardarCaso);
  $("#plantilla").addEventListener("change", onPlantillaChange);
  $("#btnAgregarTab").addEventListener("click", addTabRow);
  $("#btnAgregarRider").addEventListener("click", () => addRiderRow());
  $("#btnGenerar").addEventListener("click", generarDocumento);
  $("#paginaInicialLote").addEventListener("input", recalcularPaginas);
});
