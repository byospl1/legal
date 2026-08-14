"""Construye la tabla de exhibits y las páginas divisorias "EXHIBIT {letra}"
a partir de fragmentos de XML literal capturados una sola vez del .dotx
original (ver plantillas/i589-tab-cover/fragments/), siguiendo las secciones
9 y 10 de la especificación:

- 5 categorías fijas de contenido, con el XML exacto del original (garantiza
  formato idéntico: negritas, subrayados, numerales romanos como texto).
- Un párrafo vacío entre bloques consecutivos (categorías) para que no
  queden pegados visualmente.
- Página divisoria = 3 piezas exactas del original, una unidad completa por
  Tab: párrafo con salto de página, 12 párrafos vacíos estilo Title (truco
  de centrado vertical), párrafo del título "EXHIBIT {letra}".

Cada categoría puede traer más de un documento de evidencia (ej. Country
Conditions = reporte de país + reporte OSAC; Fee = fee receipt + FBI
fingerprint). Cuando hay evidencia adjunta para AL MENOS UNO de los
documentos de una categoría, solo se incluyen en DESCRIPTION (y en la
columna PAGES, en paralelo) los ítems que sí tienen archivo — si solo se
sube el Fee Receipt, se omite el ítem de FBI Fingerprint, y viceversa. Sin
evidencia adjunta para ninguno de los ítems de la categoría, se incluyen
todos (modo manual, como antes).

Form of Identity es distinto: no tiene un número fijo de documentos, sino
uno POR PERSONA en el caso (el aplicante líder + cada rider), cada uno con
su propio tipo de documento (Passport / Birth Certificate / ID) — ver
build_description_cell_content(identidades=...).
"""

from __future__ import annotations

import re
from pathlib import Path

FRAGMENTS_DIR = Path(__file__).resolve().parent.parent / "plantillas" / "i589-tab-cover" / "fragments"

CATEGORY_FRAGMENTS: dict[str, list[str]] = {
    "i589_application": ["item_i589_application"],
    "country_conditions": ["subtitle_country_conditions", "subitem_country_reports", "subitem_osac"],
    "form_of_identity": ["subtitle_form_of_identity", "item_passport_from"],
    "supplemental_evidence": ["subtitle_supplemental_evidence", "item_declaration"],
    "fee": ["item_fee_receipt", "item_fbi_fingerprint"],
}

# Textos fijos por tipo de documento de Supplemental Evidence. "News" lleva
# título variable (el de la noticia); los demás son fijos.
TIPOS_SUPPLEMENTAL_EVIDENCE = ["Declaration", "Psychological Report", "News"]

_TEXTO_DECLARATION = (
    "Respondent’s Declaration for Support of Asylum Withholding of Removal and Relief Under CAT with English Translation."
)
_TEXTO_PSYCHOLOGICAL_REPORT = "Respondent’s Psychological Report."

CATEGORY_ORDER = ["i589_application", "country_conditions", "form_of_identity", "supplemental_evidence", "fee"]

# Cada categoría puede tener uno o más "documentos" independientes que se
# pueden subir por separado. `frag_index` es la posición dentro de
# CATEGORY_FRAGMENTS[categoria] (y por lo tanto también la posición del
# párrafo correspondiente en la columna PAGES). El orden de esta lista es
# también el orden en el que se concatenan los PDFs subidos dentro de la
# categoría. form_of_identity y supplemental_evidence NO aparecen aquí —
# sus listas de documentos son dinámicas (una por persona del caso, y una
# lista libre de 0-N documentos con tipo variable, respectivamente), ver
# más abajo.
ITEMS_POR_CATEGORIA: dict[str, list[dict]] = {
    "i589_application": [
        {"key": "aplicacion", "label": "I-589 Application", "frag_index": 0},
    ],
    "country_conditions": [
        {"key": "country_reports", "label": "Country Reports on Human Rights Practice", "frag_index": 1},
        {"key": "osac", "label": "OSAC Crime and Safety Report", "frag_index": 2},
    ],
    "fee": [
        {"key": "fee_receipt", "label": "Fee Receipt", "frag_index": 0},
        {"key": "fbi_fingerprint", "label": "FBI Fingerprint", "frag_index": 1},
    ],
}

TIPOS_DOCUMENTO_IDENTIDAD = ["Passport", "Birth Certificate", "ID"]


def _load(name: str) -> str:
    return (FRAGMENTS_DIR / f"{name}.xml").read_text(encoding="utf-8")


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _set_first_t_text(xml: str, new_text: str) -> str:
    """Reemplaza el contenido del primer <w:t>...</w:t> del fragmento."""
    return re.sub(r"(<w:t[^>]*>)[^<]*(</w:t>)", lambda m: m.group(1) + _xml_escape(new_text) + m.group(2), xml, count=1)


def _replace_in_first_t(xml: str, old: str, new: str) -> str:
    """Reemplaza `old` por `new` (una vez) dentro del primer <w:t> del fragmento."""
    return re.sub(
        r"(<w:t[^>]*>)([^<]*)(</w:t>)",
        lambda m: m.group(1) + m.group(2).replace(old, new, 1) + m.group(3),
        xml,
        count=1,
    )


def pluralizar_respondent(xml: str) -> str:
    """"Respondent's" -> "Respondents'" (con las dos variantes de apóstrofe
    que trae el original — ’ y el typo ´). Se usa cuando el caso tiene
    riders (más de un aplicante) y el texto fijo de la plantilla debe
    hablar en plural."""
    xml = xml.replace("Respondent’s ", "Respondents’ ")
    xml = xml.replace("Respondent´s ", "Respondents´ ")
    return xml


def frag_indices_incluidos(categoria: str, evidencias: dict | None) -> set[int]:
    """Índices (dentro de CATEGORY_FRAGMENTS[categoria]) que deben incluirse
    en DESCRIPTION y PAGES. Los subtítulos (índices que no son de ningún
    ítem) siempre se incluyen. Entre los ítems: si NINGUNO de los de esta
    categoría tiene evidencia adjunta, se incluyen todos (modo manual). Si
    AL MENOS UNO la tiene, solo se incluyen los que sí tienen archivo. No
    aplica a form_of_identity (ver _build_form_of_identity_*)."""
    frag_names = CATEGORY_FRAGMENTS[categoria]
    items = ITEMS_POR_CATEGORIA.get(categoria, [])
    item_frag_indices = {item["frag_index"] for item in items}
    subtitle_indices = set(range(len(frag_names))) - item_frag_indices

    if not evidencias:
        return set(range(len(frag_names)))

    incluidos_items = {item["frag_index"] for item in items if item["key"] in evidencias}
    if not incluidos_items:
        return set(range(len(frag_names)))

    return subtitle_indices | incluidos_items


def _identity_line_text(pais: str, persona_nombre: str | None, tipo_doc: str | None) -> str:
    tipo_doc = tipo_doc or "Passport"
    if persona_nombre:
        return f"Rider’s {persona_nombre} {tipo_doc} from {pais}"
    return f"Respondent’s {tipo_doc} from {pais}"


def _build_form_of_identity_description(pais: str, identidades: list[dict]) -> str:
    subtitle = _load("subtitle_form_of_identity")
    item_tpl = _load("item_passport_from")
    lineas = [subtitle]
    for ident in identidades:
        texto = _identity_line_text(pais, ident.get("persona_nombre"), ident.get("tipo_doc"))
        lineas.append(_set_first_t_text(item_tpl, texto))
    return "".join(lineas)


def _build_form_of_identity_pages(identidades: list[dict]) -> str:
    pages_value_tpl = _load("pages_value")
    blank = _set_first_t_text(pages_value_tpl, "")
    lineas = [blank]
    for ident in identidades:
        info = ident.get("evidencia")
        if info and info.get("pagina_inicio") and info.get("num_paginas"):
            inicio = info["pagina_inicio"]
            fin = inicio + info["num_paginas"] - 1
            texto = f"Pgs. {inicio}" if inicio == fin else f"Pgs. {inicio}-{fin}"
            lineas.append(_set_first_t_text(pages_value_tpl, texto))
        else:
            lineas.append(blank)
    return "".join(lineas)


def _identidades_por_defecto() -> list[dict]:
    return [{"persona_nombre": None, "tipo_doc": "Passport"}]


def _supplemental_evidence_line_text(tipo: str | None, titulo: str | None) -> str:
    if tipo == "News":
        titulo = titulo or "…"
        return f"Respondent’s News about {titulo}."
    if tipo == "Psychological Report":
        return _TEXTO_PSYCHOLOGICAL_REPORT
    return _TEXTO_DECLARATION


def _build_supplemental_evidence_description(documentos: list[dict], plural: bool) -> str:
    subtitle = _load("subtitle_supplemental_evidence")
    item_tpl = _load("item_declaration")
    if plural:
        subtitle = pluralizar_respondent(subtitle)
    lineas = [subtitle]
    for doc in documentos:
        texto = _supplemental_evidence_line_text(doc.get("tipo"), doc.get("titulo"))
        linea = _set_first_t_text(item_tpl, texto)
        if plural:
            linea = pluralizar_respondent(linea)
        lineas.append(linea)
    return "".join(lineas)


def _build_supplemental_evidence_pages(documentos: list[dict]) -> str:
    pages_value_tpl = _load("pages_value")
    blank = _set_first_t_text(pages_value_tpl, "")
    lineas = [blank]
    for doc in documentos:
        info = doc.get("evidencia")
        if info and info.get("pagina_inicio") and info.get("num_paginas"):
            inicio = info["pagina_inicio"]
            fin = inicio + info["num_paginas"] - 1
            texto = f"Pgs. {inicio}" if inicio == fin else f"Pgs. {inicio}-{fin}"
            lineas.append(_set_first_t_text(pages_value_tpl, texto))
        else:
            lineas.append(blank)
    return "".join(lineas)


def _documentos_se_por_defecto() -> list[dict]:
    return [{"tipo": "Declaration", "titulo": None}]


def _build_category_xml(
    categoria: str,
    pais: str | None,
    anio_cc: str | None,
    anio_osac: str | None,
    plural: bool = False,
    evidencias: dict | None = None,
    tipo_fee: str | None = None,
    identidades: list[dict] | None = None,
    documentos_se: list[dict] | None = None,
) -> str:
    if categoria == "form_of_identity":
        if not pais:
            raise ValueError("form_of_identity requiere 'pais'")
        return _build_form_of_identity_description(pais, identidades or _identidades_por_defecto())

    if categoria == "supplemental_evidence":
        return _build_supplemental_evidence_description(documentos_se or _documentos_se_por_defecto(), plural)

    frag_names = CATEGORY_FRAGMENTS[categoria]
    parts = [_load(n) for n in frag_names]
    if plural:
        parts = [pluralizar_respondent(p) for p in parts]
    if categoria == "country_conditions":
        if not pais:
            raise ValueError("country_conditions requiere 'pais'")
        if not anio_cc:
            raise ValueError("country_conditions requiere 'anio_cc'")
        if not anio_osac:
            raise ValueError("country_conditions requiere 'anio_osac'")
        # "Country Conditions and Reports," -> "Country Conditions and Reports, {PAIS}"
        parts[0] = _replace_in_first_t(parts[0], "Reports,", f"Reports, {_xml_escape(pais)}")
        # "i. Country Reports on Human Rights Practice," -> "...Practice, {AÑO}"
        parts[1] = _replace_in_first_t(parts[1], "Practice,", f"Practice, {_xml_escape(anio_cc)}")
        # "ii. OSAC Crime and Safety Reports," -> "...Reports, {AÑO}"
        parts[2] = _replace_in_first_t(parts[2], "Reports,", f"Reports, {_xml_escape(anio_osac)}")
    elif categoria == "fee" and tipo_fee:
        # sin subtítulo "FEE" (se quitó) — lo que cambia es el ítem del recibo:
        # "Respondent's Fee Receipt..." -> "Respondent's Initial Fee Receipt..."
        parts[0] = _replace_in_first_t(parts[0], "Fee Receipt", f"{_xml_escape(tipo_fee)} Fee Receipt")

    incluidos = frag_indices_incluidos(categoria, evidencias)
    return "".join(p for i, p in enumerate(parts) if i in incluidos)


def build_description_cell_content(
    categorias: list[str],
    pais: str | None,
    anio_cc: str | None = None,
    anio_osac: str | None = None,
    plural: bool = False,
    evidencias: dict | None = None,
    tipo_fee: str | None = None,
    identidades: list[dict] | None = None,
    documentos_se: list[dict] | None = None,
) -> str:
    spacer = _load("spacer")
    ordered = [c for c in CATEGORY_ORDER if c in categorias]
    blocks = [
        _build_category_xml(c, pais, anio_cc, anio_osac, plural, evidencias, tipo_fee, identidades, documentos_se)
        for c in ordered
    ]
    return spacer.join(blocks)


def build_pages_cell_content(
    categorias: list[str],
    evidencias: dict | None,
    paginas_fallback: str,
    identidades: list[dict] | None = None,
    documentos_se: list[dict] | None = None,
) -> str:
    """Columna PAGES. Con evidencia adjunta (o identidades con documento
    propio), una línea por cada párrafo INCLUIDO de DESCRIPTION (en blanco
    si es subtítulo, con "Pgs. X-Y" si es un ítem con archivo adjunto) —
    así cada documento muestra su rango justo junto a su línea, y los
    ítems omitidos en DESCRIPTION (sin archivo, cuando algún otro ítem de
    la misma categoría sí lo tiene) tampoco aparecen aquí, para que las dos
    columnas sigan alineadas línea a línea. Sin nada de eso, una sola línea
    con el rango completo del Tab, como antes."""
    pages_value_tpl = _load("pages_value")
    hay_identidades_con_datos = identidades and any(i.get("evidencia") for i in identidades)
    hay_documentos_se_con_datos = documentos_se and any(d.get("evidencia") for d in documentos_se)

    if not evidencias and not hay_identidades_con_datos and not hay_documentos_se_con_datos:
        return _set_first_t_text(pages_value_tpl, f"Pgs. {paginas_fallback}")

    blank = _set_first_t_text(pages_value_tpl, "")
    ordered = [c for c in CATEGORY_ORDER if c in categorias]
    blocks = []
    for cat in ordered:
        if cat == "form_of_identity":
            blocks.append(_build_form_of_identity_pages(identidades or _identidades_por_defecto()))
            continue
        if cat == "supplemental_evidence":
            blocks.append(_build_supplemental_evidence_pages(documentos_se or _documentos_se_por_defecto()))
            continue
        frag_names = CATEGORY_FRAGMENTS[cat]
        items_by_frag_index = {item["frag_index"]: item for item in ITEMS_POR_CATEGORIA.get(cat, [])}
        incluidos = frag_indices_incluidos(cat, evidencias)
        paras = []
        for idx in range(len(frag_names)):
            if idx not in incluidos:
                continue
            item = items_by_frag_index.get(idx)
            info = evidencias.get(item["key"]) if item and evidencias else None
            if info and info.get("pagina_inicio") and info.get("num_paginas"):
                inicio = info["pagina_inicio"]
                fin = inicio + info["num_paginas"] - 1
                texto = f"Pgs. {inicio}" if inicio == fin else f"Pgs. {inicio}-{fin}"
                paras.append(_set_first_t_text(pages_value_tpl, texto))
            else:
                paras.append(blank)
        blocks.append("".join(paras))
    return blank.join(blocks)


def build_exhibit_table(tab_groups: list[dict], plural: bool = False) -> str:
    """tab_groups: [{letra, paginas, categorias: [...], pais, anio_cc,
    anio_osac, tipo_fee, evidencias: {item_key: {"pagina_inicio": N, "num_paginas": M}, ...},
    identidades: [{"persona_nombre": str|None, "tipo_doc": str, "evidencia": {...}|None}, ...]}, ...]
    `plural`: True si el caso tiene riders (más de un aplicante) — hace que
    los ítems de exhibits digan "Respondents'" en vez de "Respondent's"
    (excepto Form of Identity, que ya distingue por persona)."""
    tbl_open = _load("tbl_open")
    tab_header = _load("tab_header_label")
    desc_header = _load("description_header_label")
    pages_header = _load("pages_header_label")

    header_row = (
        "<w:tr>"
        f"<w:tc><w:tcPr><w:tcW w:w=\"1265\" w:type=\"dxa\"/></w:tcPr>{tab_header}</w:tc>"
        f"<w:tc><w:tcPr><w:tcW w:w=\"6300\" w:type=\"dxa\"/></w:tcPr>{desc_header}</w:tc>"
        f"<w:tc><w:tcPr><w:tcW w:w=\"1548\" w:type=\"dxa\"/></w:tcPr>{pages_header}</w:tc>"
        "</w:tr>"
    )

    rows = [header_row]
    tab_value_tpl = _load("tab_value")

    for tg in tab_groups:
        letra_xml = _set_first_t_text(tab_value_tpl, tg["letra"])
        desc_xml = build_description_cell_content(
            tg["categorias"],
            tg.get("pais"),
            tg.get("anio_cc"),
            tg.get("anio_osac"),
            plural,
            tg.get("evidencias"),
            tg.get("tipo_fee"),
            tg.get("identidades"),
            tg.get("documentos_se"),
        )
        pages_xml = build_pages_cell_content(
            tg["categorias"], tg.get("evidencias"), tg["paginas"], tg.get("identidades"), tg.get("documentos_se")
        )
        row = (
            "<w:tr>"
            f"<w:tc><w:tcPr><w:tcW w:w=\"1265\" w:type=\"dxa\"/></w:tcPr>{letra_xml}</w:tc>"
            f"<w:tc><w:tcPr><w:tcW w:w=\"6300\" w:type=\"dxa\"/></w:tcPr>{desc_xml}</w:tc>"
            f"<w:tc><w:tcPr><w:tcW w:w=\"1548\" w:type=\"dxa\"/></w:tcPr>{pages_xml}</w:tc>"
            "</w:tr>"
        )
        rows.append(row)

    return tbl_open + "".join(rows) + "</w:tbl>"


def build_dividers(tab_groups: list[dict]) -> str:
    """Una unidad completa (salto de página + 12 párrafos Title vacíos +
    título "EXHIBIT {letra}") por cada Tab del run, en orden. No se agregan
    saltos de página extra entre unidades: cada una ya trae el suyo."""
    pagebreak = _load("divider_pagebreak")
    empty_title = _load("divider_empty_title")
    title_tpl = _load("divider_exhibit_title")

    units = []
    for tg in tab_groups:
        title_xml = re.sub(
            r"(<w:t[^>]*>)[^<]*(</w:t>)",
            lambda m: m.group(1) + f"“EXHIBIT {_xml_escape(tg['letra'])}”" + m.group(2),
            title_tpl,
            count=1,
        )
        unit = pagebreak + (empty_title * 12) + title_xml
        units.append(unit)
    return "".join(units)
