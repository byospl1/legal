let CATALOGOS = null;
let PLANTILLAS = [];
let CURRENT_CASE_ID = null;
let tabCounter = 0;

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

  fillDatalist("dlCorteSede", CATALOGOS.corte_sede);
  fillDatalist("dlJuez", CATALOGOS.juez);
  fillDatalist("dlPreparador", CATALOGOS.preparador);
  fillSelect("abogado", CATALOGOS.abogado, "— elegir —");

  fillSelect(
    "plantilla",
    PLANTILLAS.map((p) => p.template_id),
    null
  );
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
  $("#casoStatus").textContent = "Caso cargado.";
  $("#panelDocumento").style.display = "block";
  tabCounter = 0;
  $("#tabsList").innerHTML = "";
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
  div.innerHTML = `
    <div class="tab-head">
      <strong>Tab</strong>
      <button type="button" class="danger" onclick="this.closest('.tab-card').remove()">Quitar</button>
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
      <label>País (para "Respondent's Passport from ___,")</label>
      <input type="text" class="tab-pais" placeholder="ej. Mexico">
    </div>
  `;
  $("#tabsList").appendChild(div);

  const formOfIdentityCheck = div.querySelector('.cat-check[data-cat="form_of_identity"]');
  const paisField = div.querySelector(".pais-field");
  formOfIdentityCheck.addEventListener("change", () => {
    paisField.style.display = formOfIdentityCheck.checked ? "block" : "none";
  });
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
    const categorias = [...card.querySelectorAll(".cat-check")]
      .filter((c) => c.checked)
      .map((c) => c.dataset.cat);
    const pais = categorias.includes("form_of_identity") ? card.querySelector(".tab-pais").value.trim() : null;
    return { letra, paginas, categorias, pais };
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
    if (tg.categorias.includes("form_of_identity") && !tg.pais) {
      resultado.innerHTML = `<div class="status err">Falta el país para el Tab ${tg.letra} (categoría "Form of Identity").</div>`;
      return;
    }
  }

  const document_instance = {
    template_id: templateId,
    titulo: $("#titulo").value,
    exhibits,
  };

  btn.disabled = true;
  spinner.style.display = "inline-block";
  try {
    const r = await api("/api/generar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: CURRENT_CASE_ID, document_instance }),
    });

    let html = "";
    if (r.validation_ok) {
      html += `<div class="status ok">Documento generado y validado correctamente.</div>`;
    } else {
      html += `<div class="status err">El documento se generó pero no pasó la validación:\n${r.validation_errors.join("\n")}</div>`;
    }
    if (!r.pdf_generado) {
      html += `<div class="status warn">No se pudo generar el PDF de verificación (revisa que LibreOffice esté instalado). El .docx sí se generó — ábrelo en Word y revísalo antes de usarlo.</div>`;
    }
    html += `<div class="result-links">
      <a href="${r.docx_url}" download>Descargar .docx</a>
      ${r.pdf_url ? `<a href="${r.pdf_url}" target="_blank">Ver PDF</a>` : ""}
    </div>`;
    if (r.preview_urls && r.preview_urls.length) {
      html += `<div class="previews">` + r.preview_urls.map((u) => `<a href="${u}" target="_blank"><img src="${u}"></a>`).join("") + `</div>`;
    }
    resultado.innerHTML = html;

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
  $("#btnGenerar").addEventListener("click", generarDocumento);
});
