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
Conditions = reporte de país + reporte OSAC, cada uno su propio PDF). Cuando
un Tab tiene más de un documento adjunto en total, cada ítem con archivo
muestra su propia página de inicio en el texto ("..., Pg. 13,") — así queda
claro dónde empieza cada documento dentro del rango de páginas del Tab.
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
    "fee": ["subtitle_fee", "item_fee_receipt", "item_fbi_fingerprint"],
}

CATEGORY_ORDER = ["i589_application", "country_conditions", "form_of_identity", "supplemental_evidence", "fee"]

# Cada categoría puede tener uno o más "documentos" independientes que se
# pueden subir por separado. `frag_index` es la posición dentro de
# CATEGORY_FRAGMENTS[categoria] cuyo texto se anota con "Pg. N" cuando hay
# más de un documento en el Tab. El orden de esta lista es también el orden
# en el que se concatenan los PDFs subidos dentro de la categoría.
ITEMS_POR_CATEGORIA: dict[str, list[dict]] = {
    "i589_application": [
        {"key": "aplicacion", "label": "I-589 Application", "frag_index": 0},
    ],
    "country_conditions": [
        {"key": "country_reports", "label": "Country Reports on Human Rights Practice", "frag_index": 1},
        {"key": "osac", "label": "OSAC Crime and Safety Report", "frag_index": 2},
    ],
    "form_of_identity": [
        {"key": "pasaporte", "label": "Pasaporte del cliente", "frag_index": 1},
    ],
    "supplemental_evidence": [
        {"key": "declaracion", "label": "Declaración + traducción", "frag_index": 1},
    ],
    "fee": [
        {"key": "fee_receipt", "label": "Fee Receipt", "frag_index": 1},
        {"key": "fbi_fingerprint", "label": "FBI Fingerprint", "frag_index": 2},
    ],
}


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


def _append_pagina_ref(xml: str, numero: int) -> str:
    """Agrega ' Pg. {numero}' al final del texto del fragmento, antes de la
    puntuación final (coma o punto) si la trae."""

    def repl(m: re.Match) -> str:
        prefix, text, suffix = m.group(1), m.group(2), m.group(3)
        stripped = text.rstrip()
        if stripped.endswith(",") or stripped.endswith("."):
            nuevo = stripped[:-1] + f", Pg. {numero}" + stripped[-1]
        else:
            nuevo = stripped + f", Pg. {numero}"
        return prefix + nuevo + suffix

    return re.sub(r"(<w:t[^>]*>)([^<]*)(</w:t>)", repl, xml, count=1)


def _build_category_xml(
    categoria: str,
    pais: str | None,
    anio_cc: str | None,
    anio_osac: str | None,
    evidencias: dict | None,
    anotar_paginas: bool,
) -> str:
    frag_names = CATEGORY_FRAGMENTS[categoria]
    parts = [_load(n) for n in frag_names]
    if categoria == "form_of_identity":
        if not pais:
            raise ValueError("form_of_identity requiere 'pais'")
        # el fragmento original dice "Respondent's Passport from,"; se inserta
        # el país antes de la coma.
        parts[1] = _replace_in_first_t(parts[1], "from,", f"from {_xml_escape(pais)},")
    elif categoria == "country_conditions":
        if not pais:
            raise ValueError("country_conditions requiere 'pais'")
        if not anio_cc:
            raise ValueError("country_conditions requiere 'anio_cc'")
        if not anio_osac:
            raise ValueError("country_conditions requiere 'anio_osac'")
        # "Country Conditions and Reports," -> "Country Conditions and Reports, {PAIS},"
        parts[0] = _replace_in_first_t(parts[0], "Reports,", f"Reports, {_xml_escape(pais)},")
        # "i. Country Reports on Human Rights Practice," -> "...Practice, {AÑO},"
        parts[1] = _replace_in_first_t(parts[1], "Practice,", f"Practice, {_xml_escape(anio_cc)},")
        # "ii. OSAC Crime and Safety Reports," -> "...Reports, {AÑO},"
        parts[2] = _replace_in_first_t(parts[2], "Reports,", f"Reports, {_xml_escape(anio_osac)},")

    if anotar_paginas and evidencias:
        for item in ITEMS_POR_CATEGORIA.get(categoria, []):
            info = evidencias.get(item["key"])
            if info and info.get("pagina_inicio"):
                idx = item["frag_index"]
                parts[idx] = _append_pagina_ref(parts[idx], info["pagina_inicio"])

    return "".join(parts)


def build_description_cell_content(
    categorias: list[str],
    pais: str | None,
    anio_cc: str | None = None,
    anio_osac: str | None = None,
    evidencias: dict | None = None,
) -> str:
    spacer = _load("spacer")
    ordered = [c for c in CATEGORY_ORDER if c in categorias]
    anotar_paginas = bool(evidencias) and len(evidencias) > 1
    blocks = [_build_category_xml(c, pais, anio_cc, anio_osac, evidencias, anotar_paginas) for c in ordered]
    return spacer.join(blocks)


def build_exhibit_table(tab_groups: list[dict]) -> str:
    """tab_groups: [{letra, paginas, categorias: [...], pais, anio_cc,
    anio_osac, evidencias: {item_key: {"pagina_inicio": N}, ...}}, ...]"""
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
    pages_value_tpl = _load("pages_value")

    for tg in tab_groups:
        letra_xml = _set_first_t_text(tab_value_tpl, tg["letra"])
        pages_xml = _set_first_t_text(pages_value_tpl, f"Pgs. {tg['paginas']}")
        desc_xml = build_description_cell_content(
            tg["categorias"], tg.get("pais"), tg.get("anio_cc"), tg.get("anio_osac"), tg.get("evidencias")
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
