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


def _sanitize_output_name_part(text: str) -> str:
    """Como `_sanitize_filename_part`, pero además sin comas ni espacios
    (convertidos a "_") — para el nombre del ARCHIVO DE SALIDA (el que el
    usuario sube tal cual a portales externos como EOIR ECAS, que rechazan
    cualquier nombre con comas/espacios: "File name must be alphanumeric").
    No usar esto para `_sanitize_filename_part` en general (ej. búsqueda de
    PNG de firma en firmas/) porque esos archivos sí están guardados en
    disco con espacios en el nombre."""
    text = _sanitize_filename_part(text).replace(",", "")
    return re.sub(r"\s+", "_", text.strip())


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
        candidate = output_dir / f"{base_name}_{n}{suffix}"
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


def _firma_lookup_nombre(categoria: str, nombre_field: str | None, values: dict) -> str | None:
    """Nombre de archivo (sin extensión) bajo el que debe estar guardada la
    firma de esta persona en firmas/{categoria}/ — ver _apply_firmas_imagen.

    `nombre_field`, si viene en la entrada de firmas_imagen, indica de qué
    clave de `values` (el dict ya resuelto de caso + instancia de
    documento) sacar el nombre — permite firmas de personas que no son
    "abogado"/"preparador" del caso (ej. "traductor" en written-pleadings,
    que es un campo por corrida, no del caso). Sin `nombre_field` se usa el
    comportamiento de siempre por categoría (compatibilidad con las
    plantillas existentes)."""
    if nombre_field:
        valor = values.get(nombre_field)
        return valor.split(",")[0].strip() if valor else None
    if categoria == "abogados":
        abogado = values.get("abogado")
        return abogado.split(",")[0].strip() if abogado else None
    if categoria == "preparadores":
        return values.get("preparador") or None
    return None


def _apply_firmas_imagen(document_xml: str, tmp_path: Path, field_map: dict, values: dict) -> str:
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
        nombre = _firma_lookup_nombre(entry["categoria"], entry.get("nombre_field"), values)
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


def _find_enclosing_run(document_xml: str, text_pos: int) -> tuple[int, int]:
    """Rango [inicio, fin) del <w:r>...</w:r> que contiene la posición
    `text_pos` (que debe caer dentro de su <w:t>) — mismo criterio usado por
    _apply_firmas_imagen para ubicar el run de una imagen de firma."""
    r_start = document_xml.rfind("<w:r>", 0, text_pos)
    r_start_alt = document_xml.rfind("<w:r ", 0, text_pos)
    r_start = max(r_start, r_start_alt)
    r_end = document_xml.find("</w:r>", text_pos) + len("</w:r>")
    return r_start, r_end


def _find_preceding_run(document_xml: str, pos: int) -> tuple[int, int]:
    """Rango [inicio, fin) del <w:r>...</w:r> inmediatamente ANTERIOR a la
    posición `pos` (que debe ser el inicio de otro <w:r>) — se usa para el
    run del conector cuando está separado del run de contenido, ver
    _apply_notice_exhibits."""
    prev_end = document_xml.rfind("</w:r>", 0, pos) + len("</w:r>")
    prev_start = document_xml.rfind("<w:r>", 0, prev_end)
    prev_start_alt = document_xml.rfind("<w:r ", 0, prev_end)
    prev_start = max(prev_start, prev_start_alt)
    return prev_start, prev_end


def _locate_exhibit_divider_page(document_xml: str, anchor_texto: str) -> tuple[int, int]:
    """Rango [inicio, fin) de la página divisoria "EXHIBIT {letra}" completa
    de un Motion to Withdraw (plantillas con `evidencia_exhibits`, sin tabla
    de exhibits dinámica): desde el párrafo <w:pageBreakBefore/> que empieza
    esa página hasta (sin incluirlo) el siguiente <w:pageBreakBefore/> del
    documento — sea el de la letra siguiente o el de otra sección. Cada
    página de estas es autocontenida (trae su propio salto de página al
    inicio), así que quitarla completa no afecta el salto de página de lo
    que viene después. Ver CLAUDE.md — regla decidida explícitamente por el
    usuario: un Exhibit sin evidencia adjunta no debe dejar una página
    divisoria huérfana en el documento final."""
    marker_idx = document_xml.find(f">{anchor_texto}<")
    if marker_idx == -1:
        raise FillEngineError(f"No se encontró la página divisoria {anchor_texto!r} en la plantilla")
    heading_start = document_xml.rfind("<w:p ", 0, marker_idx)
    heading_end = document_xml.find("</w:p>", marker_idx) + len("</w:p>")
    if heading_start == -1:
        raise FillEngineError(f"Estructura inesperada alrededor de la divisoria {anchor_texto!r}")

    pos = heading_start
    block_start = None
    for _ in range(100):
        prev_start = document_xml.rfind("<w:p ", 0, pos)
        if prev_start == -1:
            break
        prev_end = document_xml.find("</w:p>", prev_start) + len("</w:p>")
        if "<w:pageBreakBefore/>" in document_xml[prev_start:prev_end]:
            block_start = prev_start
            break
        pos = prev_start
    if block_start is None:
        raise FillEngineError(f"No se encontró el salto de página que empieza la divisoria {anchor_texto!r}")

    pos = heading_end
    block_end = len(document_xml)
    for _ in range(100):
        next_start = document_xml.find("<w:p ", pos)
        if next_start == -1:
            break
        next_end = document_xml.find("</w:p>", next_start) + len("</w:p>")
        if "<w:pageBreakBefore/>" in document_xml[next_start:next_end]:
            block_end = next_start
            break
        pos = next_end

    return block_start, block_end


def _apply_missing_exhibit_dividers(document_xml: str, field_map: dict, letras_con_evidencia: set[str]) -> str:
    """Para plantillas con `evidencia_exhibits` (Motion to Withdraw): si un
    Exhibit de la lista NO tiene evidencia adjunta en esta corrida, se
    elimina POR COMPLETO su página divisoria "EXHIBIT {letra}" — decisión
    explícita del usuario (2026-08-17), ver CLAUDE.md. Complementa a
    _apply_notice_exhibits, que recorta la mención de ese Exhibit en el
    párrafo NOTICE del cuerpo de la moción."""
    entries = field_map.get("evidencia_exhibits") or []
    if not entries:
        return document_xml

    replacements: list[tuple[int, int]] = []
    for entry in entries:
        if entry["letra"] in letras_con_evidencia:
            continue
        replacements.append(_locate_exhibit_divider_page(document_xml, entry["anchor_texto"]))

    if not replacements:
        return document_xml

    replacements.sort()
    out = []
    cursor = 0
    for start, end in replacements:
        out.append(document_xml[cursor:start])
        cursor = end
    out.append(document_xml[cursor:])
    return "".join(out)


def _apply_notice_exhibits(document_xml: str, field_map: dict, letras_con_evidencia: set[str]) -> str:
    """Recorta, en el párrafo NOTICE del cuerpo de la moción, la mención de
    cada Exhibit que se eliminó por falta de evidencia (ver
    _apply_missing_exhibit_dividers) — decisión explícita del usuario
    (2026-08-17): no basta con quitar la página divisoria, el NOTICE cita
    cada Exhibit por nombre en una sola oración y no debe seguir mencionando
    uno que ya no está adjunto.

    Cada entrada de field_map["notice_exhibits"] describe, EN EL ORDEN en
    que aparece en la oración, un ítem de esa lista:
    - "letra": la letra del Exhibit.
    - "removible": si es False, es un ítem fijo (ej. la Declaración propia
      del abogado) que nunca se quita ni se busca — solo cuenta para el
      orden. Debe traer "marcador_texto" para poder avanzar el cursor de
      búsqueda y, si hace falta, servir de destino del punto final.
    - "contenido_texto": texto literal (estable, no depende del caso) que
      ubica el run de "conector + contenido" de este ítem.
    - "marcador_texto": texto literal "(Exhibit X)" (o variante) que cierra
      el ítem; si vive en el MISMO run que "contenido_texto" se puede omitir.
    - "conector_run_separado": True si el conector (ej. una "," suelta) es
      su PROPIO run separado, inmediatamente antes del run de contenido
      (patrón de motion-withdraw-no-cooperation) en vez de venir pegado
      como prefijo de "contenido_texto" (patrón de motion-withdraw-cancelation).
    - "conector_prefijo": el prefijo literal (ej. ", " o ", and ") que hay
      que quitarle a "contenido_texto" si este ítem termina siendo el
      PRIMER sobreviviente de la lista (nunca lleva conector propio el
      primer ítem de una lista).
    - "marcador_solo_texto": texto exacto del marcador, usado solo para la
      corrección de punto final de abajo.
    - "termina_oracion": True si el texto de este ítem (removible) es el que
      trae el punto final de la oración completa (ej. "(Exhibit D)." en
      motion-withdraw-no-cooperation) — si se elimina, hay que ponerle punto
      al ítem que quede último.

    Esta función corre ANTES de merge_runs_in_document_xml (ver
    generar_documento) porque depende de que ciertos runs sigan separados
    tal como los trae la plantilla — fusionarlos antes le rompería los
    puntos de corte."""
    items = field_map.get("notice_exhibits") or []
    if not items:
        return document_xml

    if not any(it.get("removible") and it["letra"] not in letras_con_evidencia for it in items):
        return document_xml

    cursor = 0
    replacements: list[tuple[int, int, str]] = []
    primer_sobreviviente = None
    primer_span = None
    ultimo_sobreviviente = None
    ultimo_marker_text_end = None
    algun_terminal_eliminado = False

    for it in items:
        letra = it["letra"]
        removible = bool(it.get("removible"))
        span_start = span_end = None

        if removible:
            content_pos = document_xml.find(it["contenido_texto"], cursor)
            if content_pos == -1:
                raise FillEngineError(f"No se encontró el texto del Exhibit {letra} en el párrafo NOTICE")
            span_start, span_end = _find_enclosing_run(document_xml, content_pos)
            if it.get("conector_run_separado"):
                span_start, _ = _find_preceding_run(document_xml, span_start)
            marcador_texto = it.get("marcador_texto")
            if marcador_texto:
                marker_pos = document_xml.find(marcador_texto, span_end)
                if marker_pos == -1:
                    raise FillEngineError(f"No se encontró el marcador del Exhibit {letra} en el párrafo NOTICE")
                _, span_end = _find_enclosing_run(document_xml, marker_pos)
            cursor = span_end
        else:
            marcador_texto = it.get("marcador_texto")
            if marcador_texto:
                marker_pos = document_xml.find(marcador_texto, cursor)
                if marker_pos != -1:
                    _, cursor = _find_enclosing_run(document_xml, marker_pos)

        sobrevive = (not removible) or (letra in letras_con_evidencia)
        if sobrevive:
            if primer_sobreviviente is None:
                primer_sobreviviente = it
                primer_span = (span_start, content_pos) if removible else None
            ultimo_sobreviviente = it
            marker_run_end = span_end if removible else cursor
            # el punto final debe quedar DENTRO del <w:t> del marcador (justo
            # antes de su </w:t>), no después de </w:r> — insertarlo ahí
            # queda como texto suelto entre elementos y Word lo ignora.
            ultimo_marker_text_end = document_xml.rfind("</w:t>", 0, marker_run_end)
        else:
            replacements.append((span_start, span_end, ""))
            if it.get("termina_oracion"):
                algun_terminal_eliminado = True

    if primer_sobreviviente is not None and primer_sobreviviente.get("removible"):
        prefijo = primer_sobreviviente.get("conector_prefijo") or ""
        if prefijo:
            span_start, content_pos = primer_span
            if document_xml[content_pos:content_pos + len(prefijo)] == prefijo:
                replacements.append((content_pos, content_pos + len(prefijo), ""))
        elif primer_sobreviviente.get("conector_run_separado"):
            # el conector es un run aparte: ya quedó incluido en span_start
            # más arriba solo cuando el ítem SE ELIMINA; si sobrevive pero
            # queda primero, hay que quitar ESE run separado ahora.
            content_pos = primer_span[1]
            run_start, _ = _find_enclosing_run(document_xml, content_pos)
            conector_start, conector_end = _find_preceding_run(document_xml, run_start)
            replacements.append((conector_start, conector_end, ""))

    if algun_terminal_eliminado and ultimo_sobreviviente is not None and ultimo_marker_text_end is not None:
        marcador = ultimo_sobreviviente.get("marcador_solo_texto") or ultimo_sobreviviente.get("marcador_texto")
        ya_termina = bool(marcador) and marcador.rstrip().endswith(".")
        if marcador and not ya_termina:
            replacements.append((ultimo_marker_text_end, ultimo_marker_text_end, "."))

    replacements.sort(key=lambda r: (r[0], r[1]))
    out = []
    cur = 0
    for start, end, new_text in replacements:
        out.append(document_xml[cur:start])
        out.append(new_text)
        cur = max(cur, end)
    out.append(document_xml[cur:])
    return "".join(out)


def _apply_exhibits(document_xml: str, tab_groups: list[dict], plural: bool = False) -> str:
    tbl_start, tbl_end = _locate_tbl_by_markers(document_xml, ["TAB", "DESCRIPTION", "PAGES"])
    new_table = build_exhibit_table(tab_groups, plural=plural)
    document_xml = document_xml[:tbl_start] + new_table + document_xml[tbl_end:]

    div_start, div_end = _locate_divider_block(document_xml)
    new_dividers = build_dividers(tab_groups)
    document_xml = document_xml[:div_start] + new_dividers + document_xml[div_end:]

    return document_xml


def _apply_plural_riders(document_xml: str, field_map: dict) -> str:
    """Pluraliza los textos FIJOS de la plantilla (fuera de campos/SDT) que
    en singular dicen "Respondent"/"Respondent's" + su concordancia de verbo
    ("moves"->"move", "does not oppose"->"do not oppose", etc.) cuando el
    caso tiene riders (varios respondents, "et al").

    No es un reemplazo genérico de "Respondent" en todo el documento —eso
    pisaría el singular correcto que sí deben conservar ciertos bloques (ej.
    la tabla Form of Identity del I-589, que distingue por persona con
    "Respondent's" / "Rider's {nombre}" y nunca se pluraliza; o el SDT del
    caption "In the Matter of: {nombre}" cuyo placeholder es literalmente la
    palabra "Respondent")— sino una lista CURADA de frases exactas por
    plantilla, en field_map["plural_riders"]. Cada regla es
    {"buscar": <texto singular literal>, "reemplazar": <texto plural>}, y se
    aplica como reemplazo literal sobre el XML ya con los campos resueltos.

    El autor de cada regla es responsable de que "buscar" sea inequívoco:
    o una frase larga que solo aparece donde debe pluralizarse, o con los
    delimitadores de nodo de texto (">Respondent<") para forzar la palabra
    suelta y no un prefijo de "Respondent's". Si una regla no encuentra su
    "buscar" (p.ej. porque se editó a mano el texto de la plantilla), se
    avisa por consola pero NO se aborta la generación: la concordancia de
    plural es cosmética y nunca debe bloquear el armado de un escrito.

    Es texto de escritos legales redactado/revisado por el despacho; la
    lista de frases de cada plantilla vive en su field_map.json justamente
    para que un abogado pueda revisarla/ajustarla sin tocar código."""
    reglas = field_map.get("plural_riders") or []
    faltantes = []
    for regla in reglas:
        buscar = regla["buscar"]
        if buscar not in document_xml:
            faltantes.append(buscar)
            continue
        document_xml = document_xml.replace(buscar, regla["reemplazar"])
    if faltantes:
        print(
            "Aviso: no se pudo pluralizar (riders) las siguientes frases "
            f"—texto de plantilla cambiado?—: {faltantes}"
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


def _nombre_titulo(nombre: str | None) -> str | None:
    """Normaliza a Title Case (ej. "MENDEZ RODRIGUEZ, SHERARYN MILENY" ->
    "Mendez Rodriguez, Sheraryn Mileny") — el nombre del cliente en
    `case_store` puede haberse tipeado en cualquier combinación de
    mayúsculas/minúsculas; se usa en written-pleadings para el encabezado
    "Attorney for Respondent(s)" y la caja de caption "In the Matter of",
    que deben verse siempre en Title Case sin importar cómo se tipeó."""
    if not nombre:
        return None
    return nombre.title()


def _resolve_values(case: dict, document_instance: dict) -> dict[str, str]:
    from motor.case_store import a_number_para_documento, nombre_para_documento

    preparador = case.get("preparador")
    riders = case.get("riders") or []
    nombre_titulo = _nombre_titulo(case["cliente_nombre"])
    values = {
        "cliente_nombre": nombre_para_documento(case),
        # written-pleadings: el nombre del cliente cambia de forma según el
        # lugar del documento (ver plantillas/written-pleadings/field_map.json
        # → "_notas"). Sin riders los tres coinciden con "cliente_nombre".
        "cliente_nombre_mayus": nombre_para_documento(case).upper(),
        "cliente_nombre_lead_mayus": case["cliente_nombre"].upper(),
        # written-pleadings: encabezado "Attorney for Respondent(s)" y caja
        # de caption "In the Matter of" — siempre Title Case, sin importar
        # cómo se tipeó cliente_nombre en el caso (ver CLAUDE.md).
        "cliente_nombre_titulo": f"{nombre_titulo} et al" if riders else nombre_titulo,
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
        # written-pleadings: propios de esta corrida, no del caso (ver
        # plantillas/written-pleadings/field_map.json).
        "fecha_nta": document_instance.get("fecha_nta"),
        "alegaciones_admitidas": document_instance.get("alegaciones_admitidas"),
        "cargo_removibilidad": document_instance.get("cargo_removibilidad"),
        "designacion_pais_remocion": document_instance.get("designacion_pais_remocion"),
        "formas_alivio": document_instance.get("formas_alivio"),
        "horas_estimadas": document_instance.get("horas_estimadas"),
        "idioma_interprete": document_instance.get("idioma_interprete"),
        # opcional: si se deja vacío, no se incluye en `values` — el SDT
        # conserva su línea en blanco original ("___________") en vez de
        # quedar vacío (ver CLAUDE.md, "written-pleadings: dialecto...").
        "dialecto_interprete": document_instance.get("dialecto_interprete") or None,
        "traductor": document_instance.get("traductor"),
        "traductor_abreviado": document_instance.get("traductor_abreviado"),
        "documento_traducido": document_instance.get("documento_traducido"),
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

        if field_map.get("evidencia_exhibits"):
            # letras con evidencia adjunta en ESTA corrida (viene del mismo
            # dict que arma el merge de PDF a nivel de app.py, ver
            # exhibits_evidencia/motor.pdf_merge.combinar_portada_y_evidencia_exhibits)
            # — un Exhibit sin evidencia aquí pierde su página divisoria y su
            # mención en el NOTICE, ver _apply_missing_exhibit_dividers y
            # _apply_notice_exhibits. Corre ANTES de merge_runs_in_document_xml
            # a propósito: depende de que ciertos runs de la plantilla sigan
            # separados tal como los trae, fusionarlos antes rompería los
            # puntos de corte.
            exhibits_evidencia = document_instance.get("exhibits_evidencia") or {}
            letras_con_evidencia = {letra for letra, ids in exhibits_evidencia.items() if ids}
            pre_xml = doc_path.read_text(encoding="utf-8")
            pre_xml = _apply_missing_exhibit_dividers(pre_xml, field_map, letras_con_evidencia)
            pre_xml = _apply_notice_exhibits(pre_xml, field_map, letras_con_evidencia)
            doc_path.write_text(pre_xml, encoding="utf-8")

        merge_runs_in_document_xml(doc_path)

        tiene_riders = bool(case.get("riders"))

        document_xml = doc_path.read_text(encoding="utf-8")
        document_xml = _apply_field_values(document_xml, field_map, values)

        if field_map.get("tiene_tabla_exhibits") and document_instance.get("exhibits"):
            document_xml = _apply_exhibits(document_xml, document_instance["exhibits"], plural=tiene_riders)

        document_xml = _apply_firmas_imagen(document_xml, tmp_path, field_map, values)

        # Pluraliza los textos fijos "Respondent(...)" cuando hay riders,
        # según la lista curada field_map["plural_riders"] de cada plantilla
        # (cada plantilla tiene su propia redacción, por eso las frases van
        # en su field_map, no hardcodeadas aquí). Plantillas sin esa clave
        # (o casos sin riders) no cambian nada.
        if tiene_riders:
            document_xml = _apply_plural_riders(document_xml, field_map)

        doc_path.write_text(document_xml, encoding="utf-8")

        # el .dotx original es una plantilla; el resultado debe ser un .docx normal
        content_types_path = tmp_path / "[Content_Types].xml"
        ct = content_types_path.read_text(encoding="utf-8")
        ct = ct.replace(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        )
        content_types_path.write_text(ct, encoding="utf-8")

        cliente = _sanitize_output_name_part(case["cliente_nombre"])
        a_num = re.sub(r"\D", "", case["a_number"])
        tipo = _sanitize_output_name_part(_tipo_tab_label(document_instance))
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
        if tab_group.get("titulo"):
            instancia_tab["titulo"] = tab_group["titulo"]
        resultados.append(generar_documento(case, instancia_tab, plantillas_dir, output_dir, verificar_pdf))
    return resultados
