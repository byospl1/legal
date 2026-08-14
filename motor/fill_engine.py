"""Motor genérico de llenado (sección 5.2 de la especificación).

Dado un field_map.json (de analyze_template.py) y los datos capturados
(caso + instancia de documento), llena el .dotx/.docx respetando:
- Content controls a nivel de párrafo vs. inline (conservando <w:p>/<w:pPr>).
- Grupos maestro + mirrors (bookmarks NAME/ANUMBER/TYPE): mismo valor en
  todos los w:id del grupo.
- Campos anidados (ej. juez, SDT dentro de SDT): localizar el
  </w:sdtContent> más interno, no el último del bloque.
- grupos_sync_manual (ej. preparador): mismo valor en todos sus w:id.
- campos_automaticos_no_tocar (DATE, SEQ): nunca se tocan.
- Tabla de exhibits + páginas divisorias "EXHIBIT {letra}": se reconstruyen
  por completo con motor.exhibit_builder.

Verificación obligatoria antes de dar el documento por bueno: validate.py +
conversión a PDF + rasterizado (ver motor.pdf_tools).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from motor.analyze_template import Sdt, extract_top_level_sdts
from motor.exhibit_builder import build_dividers, build_exhibit_table
from motor.ooxml_utils import (
    add_image_relationship,
    build_inline_image_run,
    merge_runs_in_document_xml,
    png_dimensions,
    rezip,
    unpack,
)
from motor.validate import validate_docx

BASE_DIR = Path(__file__).resolve().parent.parent
FIRMAS_DIR = BASE_DIR / "firmas"


class FillEngineError(Exception):
    pass


@dataclass
class FillResult:
    docx_path: Path
    pdf_path: Path | None
    preview_images: list[Path]
    validation_ok: bool
    validation_errors: list[str]


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sanitize_filename_part(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    return re.sub(r"\s+", " ", text).strip()


def _tipo_tab_label(document_instance: dict) -> str:
    exhibits = document_instance.get("exhibits") or []
    if exhibits:
        letras = "-".join(tg["letra"] for tg in exhibits)
        return f"Tab{letras}"
    return document_instance["template_id"]


def _unique_output_path(output_dir: Path, base_name: str, suffix: str = ".docx") -> Path:
    """Nunca sobrescribe: si el nombre ya existe, agrega (2), (3)... en vez
    de pisar un archivo que el usuario pueda tener abierto."""
    candidate = output_dir / f"{base_name}{suffix}"
    n = 2
    while candidate.exists():
        candidate = output_dir / f"{base_name} ({n}){suffix}"
        n += 1
    return candidate


def _sdtpr_run_props(prefix_xml: str) -> str:
    m = re.search(r"<w:sdtPr>.*?<w:rPr>(.*?)</w:rPr>", prefix_xml, re.S)
    return m.group(1) if m else ""


def _build_leaf_replacement(sdt: Sdt, value: str) -> str:
    """Devuelve el XML completo `<w:sdt>...</w:sdt>` con el valor escrito,
    respetando nivel párrafo/inline y quitando showingPlcHdr."""
    prefix = sdt.xml[: sdt.content_start_offset].replace("<w:showingPlcHdr/>", "")
    content_close_idx = sdt.content_start_offset + len(sdt.content_xml)
    remainder = sdt.xml[content_close_idx:]

    rpr_inner = _sdtpr_run_props(prefix)
    run_rpr = f"<w:rPr>{rpr_inner}</w:rPr>" if rpr_inner else ""
    new_run = f'<w:r>{run_rpr}<w:t xml:space="preserve">{_xml_escape(value)}</w:t></w:r>'

    if sdt.nivel == "parrafo":
        content = sdt.content_xml
        ppr_end = content.find("</w:pPr>")
        if ppr_end != -1:
            ppr_end += len("</w:pPr>")
            new_content = content[:ppr_end] + new_run + "</w:p>"
        else:
            popen_end = content.find(">") + 1
            new_content = content[:popen_end] + new_run + "</w:p>"
    else:
        new_content = new_run

    return prefix + new_content + remainder


def _apply_field_values(document_xml: str, field_map: dict, values: dict[str, str]) -> str:
    top_level = extract_top_level_sdts(document_xml)
    by_id = {s.id: s for s in top_level}

    # id -> nombre de campo a escribir (o None si no aplica en este run)
    id_to_name: dict[str, str] = {}

    for campo in field_map.get("campos_simples", []):
        if campo["nombre"] and campo["nombre"] in values:
            id_to_name[campo["w_id"]] = campo["nombre"]

    for grupo in field_map.get("grupos_bookmark", []):
        if grupo["nombre"] in values:
            id_to_name[grupo["maestro"]] = grupo["nombre"]
            for mirror_id in grupo["mirrors"]:
                id_to_name[mirror_id] = grupo["nombre"]

    for grupo in field_map.get("grupos_sync_manual", []):
        if grupo["nombre"] and grupo["nombre"] in values:
            for fid in grupo["ids"]:
                id_to_name[fid] = grupo["nombre"]

    nested_by_exterior: dict[str, list[tuple[str, str]]] = {}
    for campo in field_map.get("campos_anidados", []):
        if campo["nombre"] and campo["nombre"] in values:
            nested_by_exterior.setdefault(campo["w_id_exterior"], []).append(
                (campo["w_id_interior"], campo["nombre"])
            )

    replacements: list[tuple[int, int, str]] = []

    for sdt in top_level:
        changed = False
        new_xml = sdt.xml

        if sdt.id in id_to_name:
            new_xml = _build_leaf_replacement(sdt, values[id_to_name[sdt.id]])
            changed = True
        elif sdt.id in nested_by_exterior:
            for interior_id, nombre in nested_by_exterior[sdt.id]:
                child = next((c for c in sdt.children if c.id == interior_id), None)
                if child is None:
                    raise FillEngineError(
                        f"No se encontró el campo anidado interior {interior_id} dentro de {sdt.id}"
                    )
                new_child_xml = _build_leaf_replacement(child, values[nombre])
                if child.xml not in new_xml:
                    raise FillEngineError(f"No se pudo localizar el SDT interior {interior_id} para reemplazarlo")
                new_xml = new_xml.replace(child.xml, new_child_xml, 1)
                changed = True

        if changed:
            replacements.append((sdt.start, sdt.end, new_xml))

    if not replacements:
        return document_xml

    replacements.sort(key=lambda r: r[0])
    out = []
    cursor = 0
    for start, end, new_xml in replacements:
        out.append(document_xml[cursor:start])
        out.append(new_xml)
        cursor = end
    out.append(document_xml[cursor:])
    return "".join(out)


def _firma_lookup_nombre(categoria: str, case: dict) -> str | None:
    """Nombre de archivo (sin extensión) bajo el que debe estar guardada la
    firma de esta persona en firmas/{categoria}/ — ver _apply_firmas_imagen."""
    if categoria == "abogados":
        abogado = case.get("abogado")
        return abogado.split(",")[0].strip() if abogado else None
    if categoria == "preparadores":
        return case.get("preparador") or None
    return None


def _apply_firmas_imagen(document_xml: str, tmp_path: Path, field_map: dict, case: dict) -> str:
    """Para cada entrada de field_map["firmas_imagen"], si existe un PNG en
    firmas/{categoria}/{nombre}.png para la persona resuelta, sustituye la
    línea de firma (subrayado en blanco) por la imagen escaneada. Si no hay
    PNG para esa persona, deja la línea tal cual — nunca bloquea la
    generación por una firma faltante."""
    entries = field_map.get("firmas_imagen") or []
    if not entries:
        return document_xml

    top_level = extract_top_level_sdts(document_xml)
    by_id = {s.id: s for s in top_level}

    replacements: list[tuple[int, int, str]] = []
    doc_pr_id = 900100000

    for entry in entries:
        nombre = _firma_lookup_nombre(entry["categoria"], case)
        if not nombre:
            continue
        image_path = FIRMAS_DIR / entry["categoria"] / f"{_sanitize_filename_part(nombre)}.png"
        if not image_path.exists():
            continue
        width_px, height_px = png_dimensions(image_path)
        media_name = f"firma_{entry['categoria']}_{'_'.join(entry['ids'])}.png"
        rel_id = add_image_relationship(tmp_path, image_path, media_name)

        for sid in entry["ids"]:
            sdt = by_id.get(sid)
            if sdt is None:
                continue
            doc_pr_id += 1
            image_run = build_inline_image_run(rel_id, width_px, height_px, doc_pr_id)

            # Los campos de firma se arman como inline (ver
            # plantillas/webex-motion): el prefijo literal (ej. los tabs que
            # empujan la línea a su posición) queda FUERA del SDT y nunca se
            # toca; aquí solo se reemplaza el contenido del propio SDT por
            # la imagen, igual que el resto de los campos inline.
            prefix = sdt.xml[: sdt.content_start_offset]
            content_close_idx = sdt.content_start_offset + len(sdt.content_xml)
            remainder = sdt.xml[content_close_idx:]
            replacements.append((sdt.start, sdt.end, prefix + image_run + remainder))

    if not replacements:
        return document_xml

    replacements.sort(key=lambda r: r[0])
    out = []
    cursor = 0
    for start, end, new_xml in replacements:
        out.append(document_xml[cursor:start])
        out.append(new_xml)
        cursor = end
    out.append(document_xml[cursor:])
    return "".join(out)


def _locate_tbl_by_markers(document_xml: str, markers: list[str]) -> tuple[int, int]:
    for m in re.finditer(r"<w:tbl>", document_xml):
        start = m.start()
        end = document_xml.find("</w:tbl>", start)
        if end == -1:
            continue
        end += len("</w:tbl>")
        block = document_xml[start:end]
        if all(f">{marker}<" in block for marker in markers):
            return start, end
    raise FillEngineError(f"No se encontró la tabla con los marcadores {markers}")


def _locate_divider_block(document_xml: str) -> tuple[int, int]:
    m = re.search(r'<w:p [^>]*>(?:(?!</w:p>).)*?>[^<]*EXHIBIT [A-Za-z][^<]*<(?:(?!</w:p>).)*?</w:p>', document_xml, re.S)
    if not m:
        raise FillEngineError("No se encontró la página divisoria 'EXHIBIT X' original en la plantilla")
    title_start, title_end = m.start(), m.end()

    pos = title_start
    for _ in range(12):
        prev_start = document_xml.rfind("<w:p ", 0, pos)
        if prev_start == -1:
            raise FillEngineError("Estructura de la página divisoria inesperada (faltan párrafos vacíos Title)")
        pos = prev_start

    pagebreak_start = document_xml.rfind("<w:p ", 0, pos)
    if pagebreak_start == -1:
        raise FillEngineError("No se encontró el párrafo con el salto de página antes de la divisoria")
    pagebreak_block_end = document_xml.find("</w:p>", pagebreak_start) + len("</w:p>")
    pagebreak_block = document_xml[pagebreak_start:pagebreak_block_end]
    if 'w:type="page"' not in pagebreak_block:
        raise FillEngineError(
            "El párrafo inmediatamente anterior a los 12 párrafos vacíos no trae el salto de página esperado "
            "— la estructura de la plantilla cambió, revisa manualmente."
        )

    return pagebreak_start, title_end


def _apply_exhibits(document_xml: str, tab_groups: list[dict], plural: bool = False) -> str:
    tbl_start, tbl_end = _locate_tbl_by_markers(document_xml, ["TAB", "DESCRIPTION", "PAGES"])
    new_table = build_exhibit_table(tab_groups, plural=plural)
    document_xml = document_xml[:tbl_start] + new_table + document_xml[tbl_end:]

    div_start, div_end = _locate_divider_block(document_xml)
    new_dividers = build_dividers(tab_groups)
    document_xml = document_xml[:div_start] + new_dividers + document_xml[div_end:]

    return document_xml


def _apply_plural_respondents(document_xml: str) -> str:
    """Textos fijos de la plantilla FUERA de la tabla de exhibits:
    "Respondent" standalone antes de "In Removal Proceedings", y
    "Respondent's" en el párrafo de Proof of Service. Deben decir
    "Respondents"/"Respondents'" cuando el caso tiene riders.

    Los ítems de la tabla de exhibits ya se pluralizan (o no, en el caso
    de Form of Identity, que distingue por persona con "Respondent's" /
    "Rider's {nombre}" y nunca debe pluralizarse) al construirse — ver
    _apply_exhibits/build_exhibit_table. Por eso aquí se usa un reemplazo
    puntual por frase exacta, no un reemplazo genérico de "Respondent's "
    en todo el documento, que le pisaría el singular correcto a Form of
    Identity."""
    document_xml = document_xml.replace(">Respondent<", ">Respondents<")
    document_xml = document_xml.replace(
        "A True Copy of the Respondent’s ", "A True Copy of the Respondents’ "
    )
    return document_xml


def _abogado_firma(abogado: str | None) -> str | None:
    """Forma corta del abogado para bloques de firma (ej. "John Negron,
    Esq. (SBN 21806)" -> "John Negron Esq.") — se usa en plantillas como
    Motion for Webex, donde la firma no lleva ni la coma ni el SBN."""
    if not abogado:
        return None
    nombre = abogado.split(",")[0].strip()
    return f"{nombre} Esq."


def _abogado_nombre(abogado: str | None) -> str | None:
    """Nombre solo del abogado, sin "Esq." ni SBN (ej. "John Negron,
    Esq. (SBN 21806)" -> "John Negron") — se usa en párrafos como "I,
    {nombre}, declare..." o "DECLARATION OF {NOMBRE}"."""
    if not abogado:
        return None
    return abogado.split(",")[0].strip()


def _abogado_firma_coma(abogado: str | None) -> str | None:
    """Forma corta CON coma (ej. "Michael Quiroga, Esq.") — a diferencia de
    _abogado_firma (sin coma), es la convención usada en Motion to Withdraw."""
    nombre = _abogado_nombre(abogado)
    return f"{nombre}, Esq." if nombre else None


def _juez_apellido_mayus(juez: str | None) -> str | None:
    """Apellido del juez en mayúsculas (ej. "Diaz, Irma" -> "DIAZ") — se usa
    en la línea "TO ALL PARTIES AND THE HONORABLE IMMIGRATION JUDGE {...},"
    de Motion to Withdraw - Cancelation of Services."""
    if not juez:
        return None
    apellido = juez.split(",")[0].strip()
    return apellido.upper() or None


def _resolve_values(case: dict, document_instance: dict) -> dict[str, str]:
    from motor.case_store import a_number_para_documento, nombre_para_documento

    preparador = case.get("preparador")
    values = {
        "cliente_nombre": nombre_para_documento(case),
        "a_number": a_number_para_documento(case),
        "corte_sede": case["corte_sede"],
        "juez": case["juez"],
        "juez_apellido_mayus": _juez_apellido_mayus(case["juez"]),
        "proxima_audiencia": case["proxima_audiencia"],
        "abogado": case["abogado"],
        "abogado_firma": _abogado_firma(case["abogado"]),
        "abogado_firma_coma": _abogado_firma_coma(case["abogado"]),
        "abogado_nombre": _abogado_nombre(case["abogado"]),
        "abogado_nombre_mayus": (_abogado_nombre(case["abogado"]) or "").upper() or None,
        "preparador": preparador,
        "preparador_mayus": preparador.upper() if preparador else None,
        "titulo": document_instance.get("titulo"),
        # campos propios de esta corrida (no del caso): específicos de la
        # narrativa de esta moción en particular, se capturan cada vez que
        # se genera este documento, no se guardan en el caso.
        "direccion_conocida": document_instance.get("direccion_conocida"),
        "telefono_conocido": document_instance.get("telefono_conocido"),
        "direccion_anterior": document_instance.get("direccion_anterior"),
        "direccion_actual": document_instance.get("direccion_actual"),
        "fecha_cancelacion": document_instance.get("fecha_cancelacion"),
    }
    return {k: v for k, v in values.items() if v is not None}


def generar_documento(
    case: dict,
    document_instance: dict,
    plantillas_dir: Path | str = BASE_DIR / "plantillas",
    output_dir: Path | str = BASE_DIR / "output",
    verificar_pdf: bool = True,
) -> FillResult:
    plantillas_dir = Path(plantillas_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    template_id = document_instance["template_id"]
    template_dir = plantillas_dir / template_id
    field_map = json.loads((template_dir / "field_map.json").read_text(encoding="utf-8"))
    dotx_path = template_dir / field_map["archivo"]
    if not dotx_path.exists():
        raise FillEngineError(f"No se encontró la plantilla: {dotx_path}")

    values = _resolve_values(case, document_instance)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        unpack(dotx_path, tmp_path)
        doc_path = tmp_path / "word" / "document.xml"
        merge_runs_in_document_xml(doc_path)

        tiene_riders = bool(case.get("riders"))

        document_xml = doc_path.read_text(encoding="utf-8")
        document_xml = _apply_field_values(document_xml, field_map, values)

        if field_map.get("tiene_tabla_exhibits") and document_instance.get("exhibits"):
            document_xml = _apply_exhibits(document_xml, document_instance["exhibits"], plural=tiene_riders)

        document_xml = _apply_firmas_imagen(document_xml, tmp_path, field_map, case)

        # _apply_plural_respondents busca frases EXACTAS fijas de la
        # plantilla i589-tab-cover (">Respondent<", "A True Copy of the
        # Respondent's ") -- no aplica a otras plantillas, cada una tiene su
        # propia convención de singular/plural que aún no se automatiza.
        if tiene_riders and template_id == "i589-tab-cover":
            document_xml = _apply_plural_respondents(document_xml)

        doc_path.write_text(document_xml, encoding="utf-8")

        # el .dotx original es una plantilla; el resultado debe ser un .docx normal
        content_types_path = tmp_path / "[Content_Types].xml"
        ct = content_types_path.read_text(encoding="utf-8")
        ct = ct.replace(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        )
        content_types_path.write_text(ct, encoding="utf-8")

        cliente = _sanitize_filename_part(case["cliente_nombre"])
        a_num = _sanitize_filename_part(case["a_number"]).replace(" ", "")
        tipo = _sanitize_filename_part(_tipo_tab_label(document_instance))
        base_name = f"{cliente}_{a_num}_{tipo}"
        # nunca sobrescribe una corrida anterior (ver _unique_output_path) —
        # en Windows, sobrescribir un archivo que sigue abierto en Word
        # falla además con "Access is denied".
        docx_out = _unique_output_path(output_dir, base_name)
        rezip(tmp_path, docx_out)

    ok, errors = validate_docx(docx_out)
    if not ok:
        from motor.validate import ValidationError

        raise ValidationError(f"El documento generado no pasó validate_docx: {'; '.join(errors)}")

    pdf_path = None
    preview_images: list[Path] = []
    if verificar_pdf:
        from motor.pdf_tools import PdfToolsError, convert_to_pdf, rasterize

        try:
            pdf_path = convert_to_pdf(docx_out, output_dir)
            preview_images = rasterize(pdf_path, output_dir / "_preview" / docx_out.stem)
        except PdfToolsError as e:
            # No bloquea la generación del .docx, pero se reporta: sin esto
            # nadie revisó el documento página por página.
            preview_images = []
            pdf_path = None
            print(f"Aviso: no se pudo generar el PDF de verificación: {e}")

    return FillResult(
        docx_path=docx_out,
        pdf_path=pdf_path,
        preview_images=preview_images,
        validation_ok=ok,
        validation_errors=errors,
    )


def generar_lote(
    case: dict,
    document_instance: dict,
    plantillas_dir: Path | str = BASE_DIR / "plantillas",
    output_dir: Path | str = BASE_DIR / "output",
    verificar_pdf: bool = True,
    separar_por_tab: bool = True,
) -> list[FillResult]:
    """Genera uno o varios documentos a partir de la misma captura.

    Si `separar_por_tab` es True y hay más de un Tab en `document_instance
    ["exhibits"]`, genera UN ARCHIVO POR TAB (cada uno con su propia fila en
    la tabla de exhibits y su propia página divisoria) en vez de un solo
    documento combinado — útil cuando de una corrida salen varios Tabs
    distintos (A, B, C...) y cada uno necesita imprimirse/archivarse por
    separado. Si `separar_por_tab` es False, o solo hay un Tab (o ninguno),
    genera un único documento con todos los Tabs juntos, como antes.
    """
    exhibits = document_instance.get("exhibits") or []
    if not separar_por_tab or len(exhibits) <= 1:
        return [generar_documento(case, document_instance, plantillas_dir, output_dir, verificar_pdf)]

    resultados = []
    for tab_group in exhibits:
        instancia_tab = dict(document_instance)
        instancia_tab["exhibits"] = [tab_group]
        resultados.append(generar_documento(case, instancia_tab, plantillas_dir, output_dir, verificar_pdf))
    return resultados
