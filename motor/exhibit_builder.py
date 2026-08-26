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
build_description_cell_content(identidades=...). Biometrics Compliance
(dentro de la categoría "fee") sigue el mismo patrón por persona — ver
build_description_cell_content(biometricos=...) y
_build_biometrics_compliance_description.
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

# Subtítulos que solo deben incluirse junto con UN ítem específico de la
# misma categoría (a diferencia del comportamiento genérico de
# frag_indices_incluidos, donde un subtítulo acompaña a CUALQUIER ítem
# incluido de la categoría — correcto para country_conditions, donde el
# subtítulo es de toda la categoría). Ninguna categoría lo necesita hoy
# ("Biometrics Compliance" se volvió una sección dinámica por persona, ver
# _build_biometrics_compliance_description — ya no vive en CATEGORY_FRAGMENTS
# ni usa este mecanismo). Se deja el dict vacío por si otra categoría futura
# lo necesita.
SUBTITULOS_ATADOS_A_ITEM: dict[str, dict[int, int]] = {}

# Textos fijos por tipo de documento de Supplemental Evidence. "News" lleva
# título variable (el de la noticia); los demás son fijos. Lista libre (sin
# persona asociada) — para documentos por persona (líder/rider), ver
# TIPOS_DOCUMENTO_PERSONA_SE y `declaraciones` más abajo.
TIPOS_SUPPLEMENTAL_EVIDENCE = ["Declaration", "Psychological Report", "News"]

# Mismos 3 tipos, pero para el selector POR PERSONA (2026-08-26, a pedido
# explícito del usuario: "dejame elegir qué tipo de documento estoy
# cargando, si es declaracion o evidencia") — cada persona del caso
# (líder/rider) puede subir más de un documento, cada uno con su propio
# tipo, igual patrón que Form of Identity (`identidades`/`tipo_doc`). El
# texto generado nombra a la persona ("Rider's {NOMBRE} ...") igual que ya
# hacía Declaration antes de este cambio — ver `_declaration_line_text`.
TIPOS_DOCUMENTO_PERSONA_SE = ["Declaration", "Psychological Report", "News"]

_TEXTO_DECLARATION = (
    "Respondent’s Declaration for Support of Asylum Withholding of Removal and Relief Under CAT."
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


def frag_indices_incluidos(
    categoria: str, evidencias: dict | None, hay_evidencia_dinamica: bool = False
) -> set[int]:
    """Índices (dentro de CATEGORY_FRAGMENTS[categoria]) que deben incluirse
    en DESCRIPTION y PAGES. Los subtítulos (índices que no son de ningún
    ítem) siempre se incluyen junto con cualquier ítem incluido de la
    categoría — salvo que estén atados a un ítem puntual vía
    SUBTITULOS_ATADOS_A_ITEM. Entre los ítems: si NINGUNO de los de esta
    categoría tiene evidencia adjunta, se incluyen todos (modo manual). Si
    AL MENOS UNO la tiene, solo se incluyen los que sí tienen archivo. No
    aplica a form_of_identity (ver _build_form_of_identity_*).

    `hay_evidencia_dinamica`: True cuando la categoría tiene evidencia
    adjunta en una sección dinámica que vive FUERA de este mecanismo (hoy:
    Biometrics Compliance dentro de "fee", ver `biometricos` en
    _build_category_xml/build_pages_cell_content) — evita que, con
    evidencia SOLO en esa sección dinámica y ninguna en los ítems fijos
    (evidencias vacío), esta función caiga en "modo manual: incluir todo" e
    incluya de más ítems fijos sin evidencia (ej. Fee Receipt/FBI
    Fingerprint cuando solo se subió Biometrics Compliance)."""
    frag_names = CATEGORY_FRAGMENTS[categoria]
    items = ITEMS_POR_CATEGORIA.get(categoria, [])
    item_frag_indices = {item["frag_index"] for item in items}
    subtitle_indices = set(range(len(frag_names))) - item_frag_indices
    atados = SUBTITULOS_ATADOS_A_ITEM.get(categoria, {})

    if not evidencias and not hay_evidencia_dinamica:
        return set(range(len(frag_names)))

    incluidos_items = {item["frag_index"] for item in items if evidencias and item["key"] in evidencias}
    if not incluidos_items and not hay_evidencia_dinamica:
        return set(range(len(frag_names)))

    incluidos_subtitulos = {
        idx
        for idx in subtitle_indices
        if idx not in atados or atados[idx] in incluidos_items
    }
    return incluidos_subtitulos | incluidos_items


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


def _biometrics_line_text(persona_nombre: str | None, fecha: str) -> str:
    if persona_nombre:
        return f"Rider’s {persona_nombre} Fingerprint Notification Biometric Processing Stamp ({fecha})."
    return f"Respondent’s Fingerprint Notification Biometric Processing Stamp ({fecha})."


def _fee_tiene_evidencia_en_items_fijos(evidencias: dict | None) -> bool:
    """True si `evidencias` trae archivo para fee_receipt y/o fbi_fingerprint
    — se usa junto con `hay_evidencia_dinamica` (evidencia en biometricos)
    para decidir si la categoría "fee" está en "modo evidencia" a efectos
    de qué personas de Biometrics Compliance incluir/exigir (ver
    _build_biometrics_compliance_description)."""
    if not evidencias:
        return False
    fee_keys = {item["key"] for item in ITEMS_POR_CATEGORIA.get("fee", [])}
    return any(k in evidencias for k in fee_keys)


def _build_biometrics_compliance_description(biometricos: list[dict], modo_evidencia: bool = False) -> str:
    """A diferencia de Form of Identity (un subtítulo COMPARTIDO seguido de
    un renglón por persona), Biometrics Compliance repite el subtítulo
    "Biometrics Compliance." ANTES de cada persona — cada persona es su
    propio bloque tipo "categoría", separado del siguiente por el mismo
    `spacer` (párrafo vacío) que separa categorías distintas en la tabla.
    Se decidió así (2026-08-25, a pedido explícito del usuario) porque cada
    ítem de este renglón es texto largo que casi siempre ocupa 2 líneas
    visuales al renderizarse en Word — con un solo subtítulo compartido
    para varias personas, la columna PAGES (ver
    _build_biometrics_compliance_pages) se desalineaba con el renglón de
    cada persona a partir de la segunda (el "Pgs. X-Y" de la 2da persona
    caía junto a la línea envuelta de la 1ra persona, no junto a su propio
    renglón) — repetir el subtítulo por persona reinicia la alineación en
    cada bloque.

    `modo_evidencia` (2026-08-26, a pedido explícito del usuario): cuando
    la categoría "fee" tiene evidencia adjunta EN ALGUNA PARTE (fee_receipt,
    fbi_fingerprint, o Biometrics Compliance de otra persona), una persona
    SIN su propio archivo de Biometrics Compliance se omite por completo
    (ni renglón ni fecha obligatoria) — mismo criterio "modo evidencia" que
    ya aplica a fee_receipt/fbi_fingerprint y a Country Conditions. Sin
    evidencia adjunta en NINGUNA parte de la categoría (modo manual), se
    incluyen todas las personas y se exige fecha para todas, como antes."""
    subtitle = _load("subtitle_biometrics_compliance")
    item_tpl = _load("item_biometrics_compliance")
    spacer = _load("spacer")
    bloques = []
    for bio in biometricos:
        if modo_evidencia and not (bio.get("evidencia") or bio.get("evidencia_id")):
            continue
        fecha = bio.get("fecha")
        if not fecha:
            raise ValueError("fee requiere 'fecha' para cada persona en Biometrics Compliance")
        texto = _biometrics_line_text(bio.get("persona_nombre"), fecha)
        bloques.append(subtitle + _set_first_t_text(item_tpl, texto))
    return spacer.join(bloques)


def _build_biometrics_compliance_pages(biometricos: list[dict], modo_evidencia: bool = False) -> str:
    """Un bloque [blank, valor] por persona (blank alineado con el
    subtítulo repetido, valor alineado con la primera línea del renglón de
    esa persona), separados por `blank` — el mismo patrón 1 a 1 que usa
    _build_biometrics_compliance_description, ver su docstring (incluyendo
    el mismo criterio `modo_evidencia` para qué personas se omiten)."""
    pages_value_tpl = _load("pages_value")
    blank = _set_first_t_text(pages_value_tpl, "")
    bloques = []
    for bio in biometricos:
        if modo_evidencia and not (bio.get("evidencia") or bio.get("evidencia_id")):
            continue
        info = bio.get("evidencia")
        if info and info.get("pagina_inicio") and info.get("num_paginas"):
            inicio = info["pagina_inicio"]
            fin = inicio + info["num_paginas"] - 1
            texto = f"Pgs. {inicio}" if inicio == fin else f"Pgs. {inicio}-{fin}"
            valor = _set_first_t_text(pages_value_tpl, texto)
        else:
            valor = blank
        bloques.append(blank + valor)
    return blank.join(bloques)


def _biometricos_por_defecto() -> list[dict]:
    return [{"persona_nombre": None, "fecha": None}]


def _supplemental_evidence_line_text(tipo: str | None, titulo: str | None) -> str:
    if tipo == "News":
        titulo = titulo or "…"
        return f"Respondent’s News about {titulo}."
    if tipo == "Psychological Report":
        return _TEXTO_PSYCHOLOGICAL_REPORT
    return _TEXTO_DECLARATION


def _declaration_line_text(persona_nombre: str | None, tipo: str | None, titulo: str | None) -> str:
    """Texto por persona para un documento de Supplemental Evidence — a
    diferencia de `_supplemental_evidence_line_text` (lista libre, sin
    persona), este SIEMPRE nombra a quién pertenece ("Respondent's" o
    "Rider's {NOMBRE}"), sin importar el tipo elegido."""
    quien = f"Rider’s {persona_nombre} " if persona_nombre else "Respondent’s "
    if tipo == "News":
        titulo = titulo or "…"
        return f"{quien}News about {titulo}."
    if tipo == "Psychological Report":
        return f"{quien}Psychological Report."
    return f"{quien}Declaration for Support of Asylum Withholding of Removal and Relief Under CAT."


def _declaraciones_por_defecto() -> list[dict]:
    return [{"persona_nombre": None, "tipo": "Declaration", "titulo": None, "evidencia": None}]


def _supplemental_evidence_en_modo_evidencia(documentos: list[dict], declaraciones: list[dict]) -> bool:
    """Mismo criterio "modo evidencia" que ya usan Fee/Biometrics y CC/OSAC:
    si hay evidencia adjunta EN ALGUNA PARTE de "supplemental_evidence"
    (una declaración de alguna persona, o alguno de los documentos libres
    de Psychological Report/News), una persona SIN su propia declaración
    adjunta se omite por completo (no se incluye una línea "Respondent's/
    Rider's ... Declaration..." vacía). Sin NADA subido en ninguna parte de
    la categoría (modo manual puro), se incluyen las declaraciones de TODAS
    las personas del caso (líder + cada rider) — mismo comportamiento que
    tenía el único ítem genérico "Respondent's Declaration..." de antes."""
    if any(d.get("evidencia") for d in documentos):
        return True
    return any(d.get("evidencia") or d.get("evidencia_id") for d in declaraciones)


def _build_supplemental_evidence_description(
    documentos: list[dict], plural: bool, declaraciones: list[dict] | None = None
) -> str:
    """Un `spacer` (párrafo vacío) entre cada documento incluido — igual que
    entre categorías distintas de la tabla y que entre personas de
    Biometrics Compliance (ver su docstring). Necesario porque el texto de
    cada declaración/documento es largo y casi siempre envuelve a 2+ líneas
    visuales en Word: sin un separador, la columna PAGES (ver
    _build_supplemental_evidence_pages) se desalinea a partir del segundo
    documento — el "Pgs. X-Y" del segundo caía junto a la línea envuelta del
    primero en vez de junto a su propio renglón (reportado por el usuario
    2026-08-26 con captura de Tab D: líder + 1 rider)."""
    declaraciones = declaraciones if declaraciones is not None else _declaraciones_por_defecto()
    modo_evidencia = _supplemental_evidence_en_modo_evidencia(documentos, declaraciones)
    item_tpl = _load("item_declaration")
    spacer = _load("spacer")
    bloques = []
    for decl in declaraciones:
        if modo_evidencia and not (decl.get("evidencia") or decl.get("evidencia_id")):
            continue
        texto = _declaration_line_text(decl.get("persona_nombre"), decl.get("tipo"), decl.get("titulo"))
        # Las declaraciones ya distinguen por persona ("Respondent's" vs
        # "Rider's {NOMBRE}") igual que Form of Identity/Biometrics — no se
        # pluralizan aunque el Tab sea plural, mismo criterio que esas dos.
        bloques.append(_set_first_t_text(item_tpl, texto))
    for doc in documentos:
        texto = _supplemental_evidence_line_text(doc.get("tipo"), doc.get("titulo"))
        linea = _set_first_t_text(item_tpl, texto)
        if plural:
            linea = pluralizar_respondent(linea)
        bloques.append(linea)
    return spacer.join(bloques)


def _build_supplemental_evidence_pages(documentos: list[dict], declaraciones: list[dict] | None = None) -> str:
    """Debe seguir el mismo conteo de párrafos que
    _build_supplemental_evidence_description, incluyendo el `blank` que
    corresponde al `spacer` entre documentos (ver su docstring) — de lo
    contrario las dos columnas se desalinean."""
    declaraciones = declaraciones if declaraciones is not None else _declaraciones_por_defecto()
    modo_evidencia = _supplemental_evidence_en_modo_evidencia(documentos, declaraciones)
    pages_value_tpl = _load("pages_value")
    blank = _set_first_t_text(pages_value_tpl, "")
    bloques = []
    for decl in declaraciones:
        if modo_evidencia and not (decl.get("evidencia") or decl.get("evidencia_id")):
            continue
        info = decl.get("evidencia")
        if info and info.get("pagina_inicio") and info.get("num_paginas"):
            inicio = info["pagina_inicio"]
            fin = inicio + info["num_paginas"] - 1
            texto = f"Pgs. {inicio}" if inicio == fin else f"Pgs. {inicio}-{fin}"
            bloques.append(_set_first_t_text(pages_value_tpl, texto))
        else:
            bloques.append(blank)
    for doc in documentos:
        info = doc.get("evidencia")
        if info and info.get("pagina_inicio") and info.get("num_paginas"):
            inicio = info["pagina_inicio"]
            fin = inicio + info["num_paginas"] - 1
            texto = f"Pgs. {inicio}" if inicio == fin else f"Pgs. {inicio}-{fin}"
            bloques.append(_set_first_t_text(pages_value_tpl, texto))
        else:
            bloques.append(blank)
    return blank.join(bloques)


def _documentos_se_por_defecto() -> list[dict]:
    return []


def _build_category_xml(
    categoria: str,
    pais: str | None,
    anio_cc: str | None,
    anio_osac: str | None,
    plural: bool = False,
    evidencias: dict | None = None,
    tipo_fee: str | None = None,
    biometricos: list[dict] | None = None,
    identidades: list[dict] | None = None,
    documentos_se: list[dict] | None = None,
    declaraciones: list[dict] | None = None,
) -> str:
    if categoria == "form_of_identity":
        if not pais:
            raise ValueError("form_of_identity requiere 'pais'")
        return _build_form_of_identity_description(pais, identidades or _identidades_por_defecto())

    if categoria == "supplemental_evidence":
        return _build_supplemental_evidence_description(
            documentos_se or _documentos_se_por_defecto(), plural, declaraciones
        )

    frag_names = CATEGORY_FRAGMENTS[categoria]
    parts = [_load(n) for n in frag_names]
    if plural:
        parts = [pluralizar_respondent(p) for p in parts]
    if categoria == "country_conditions":
        if not pais:
            raise ValueError("country_conditions requiere 'pais'")
        # Los años solo son obligatorios para el subitem que realmente va a
        # quedar incluido (ver frag_indices_incluidos): si solo se subió
        # evidencia de Country Reports, el subitem de OSAC se descarta más
        # abajo y no debe bloquear la generación pidiendo un año que no se
        # va a usar — y viceversa.
        incluidos_preview = frag_indices_incluidos(categoria, evidencias)
        # "Country Conditions and Reports," -> "Country Conditions and Reports, {PAIS}"
        parts[0] = _replace_in_first_t(parts[0], "Reports,", f"Reports, {_xml_escape(pais)}")
        if 1 in incluidos_preview:
            if not anio_cc:
                raise ValueError("country_conditions requiere 'anio_cc'")
            # "i. Country Reports on Human Rights Practice," -> "...Practice, {AÑO}"
            parts[1] = _replace_in_first_t(parts[1], "Practice,", f"Practice, {_xml_escape(anio_cc)}")
        if 2 in incluidos_preview:
            if not anio_osac:
                raise ValueError("country_conditions requiere 'anio_osac'")
            # "ii. OSAC Crime and Safety Reports," -> "...Reports, {AÑO}"
            parts[2] = _replace_in_first_t(parts[2], "Reports,", f"Reports, {_xml_escape(anio_osac)}")
    elif categoria == "fee":
        # sin subtítulo "FEE" (se quitó) — lo que cambia es el ítem del recibo:
        # "Respondent's Fee Receipt..." -> "Respondent's Initial Fee Receipt..."
        if tipo_fee:
            parts[0] = _replace_in_first_t(parts[0], "Fee Receipt", f"{_xml_escape(tipo_fee)} Fee Receipt")

    biometricos = biometricos or _biometricos_por_defecto()
    hay_evidencia_dinamica = categoria == "fee" and any(b.get("evidencia") or b.get("evidencia_id") for b in biometricos)
    incluidos = frag_indices_incluidos(categoria, evidencias, hay_evidencia_dinamica)
    resultado = "".join(p for i, p in enumerate(parts) if i in incluidos)
    if categoria == "fee":
        # Biometrics Compliance ya no es un ítem fijo de CATEGORY_FRAGMENTS —
        # es una sección dinámica con un renglón por persona del caso (líder +
        # cada rider), agregada al final de la categoría "fee" cuando está
        # marcada. Con evidencia adjunta en ALGUNA parte de "fee" (modo
        # evidencia), solo se incluyen/exigen las personas que sí tienen su
        # propio archivo de Biometrics Compliance — ver
        # _build_biometrics_compliance_description.
        modo_evidencia_fee = _fee_tiene_evidencia_en_items_fijos(evidencias) or hay_evidencia_dinamica
        resultado += _build_biometrics_compliance_description(biometricos, modo_evidencia_fee)
    return resultado


def build_description_cell_content(
    categorias: list[str],
    pais: str | None,
    anio_cc: str | None = None,
    anio_osac: str | None = None,
    plural: bool = False,
    evidencias: dict | None = None,
    tipo_fee: str | None = None,
    biometricos: list[dict] | None = None,
    identidades: list[dict] | None = None,
    documentos_se: list[dict] | None = None,
    declaraciones: list[dict] | None = None,
) -> str:
    spacer = _load("spacer")
    ordered = [c for c in CATEGORY_ORDER if c in categorias]
    blocks = [
        _build_category_xml(
            c, pais, anio_cc, anio_osac, plural, evidencias, tipo_fee, biometricos, identidades, documentos_se, declaraciones
        )
        for c in ordered
    ]
    return spacer.join(blocks)


def build_pages_cell_content(
    categorias: list[str],
    evidencias: dict | None,
    paginas_fallback: str,
    identidades: list[dict] | None = None,
    documentos_se: list[dict] | None = None,
    biometricos: list[dict] | None = None,
    declaraciones: list[dict] | None = None,
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
    hay_biometricos_con_datos = biometricos and any(b.get("evidencia") for b in biometricos)
    hay_declaraciones_con_datos = declaraciones and any(d.get("evidencia") for d in declaraciones)

    if (
        not evidencias
        and not hay_identidades_con_datos
        and not hay_documentos_se_con_datos
        and not hay_biometricos_con_datos
        and not hay_declaraciones_con_datos
    ):
        return _set_first_t_text(pages_value_tpl, f"Pgs. {paginas_fallback}")

    blank = _set_first_t_text(pages_value_tpl, "")
    ordered = [c for c in CATEGORY_ORDER if c in categorias]
    blocks = []
    for cat in ordered:
        if cat == "form_of_identity":
            blocks.append(_build_form_of_identity_pages(identidades or _identidades_por_defecto()))
            continue
        if cat == "supplemental_evidence":
            blocks.append(_build_supplemental_evidence_pages(documentos_se or _documentos_se_por_defecto(), declaraciones))
            continue
        frag_names = CATEGORY_FRAGMENTS[cat]
        items_by_frag_index = {item["frag_index"]: item for item in ITEMS_POR_CATEGORIA.get(cat, [])}
        hay_evidencia_dinamica = cat == "fee" and bool(hay_biometricos_con_datos)
        incluidos = frag_indices_incluidos(cat, evidencias, hay_evidencia_dinamica)
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
        bloque = "".join(paras)
        if cat == "fee":
            modo_evidencia_fee = _fee_tiene_evidencia_en_items_fijos(evidencias) or hay_evidencia_dinamica
            bloque += _build_biometrics_compliance_pages(biometricos or _biometricos_por_defecto(), modo_evidencia_fee)
        blocks.append(bloque)
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
            tg.get("biometricos"),
            tg.get("identidades"),
            tg.get("documentos_se"),
            tg.get("declaraciones"),
        )
        pages_xml = build_pages_cell_content(
            tg["categorias"],
            tg.get("evidencias"),
            tg["paginas"],
            tg.get("identidades"),
            tg.get("documentos_se"),
            tg.get("biometricos"),
            tg.get("declaraciones"),
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
