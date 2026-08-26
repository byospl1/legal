"""Utilidades OOXML de bajo nivel: (des)empaquetar .docx/.dotx y fusionar runs.

Vendorizado y simplificado a partir de las herramientas de la skill `docx`
(merge_runs.py + office/helpers) para que el sistema no dependa del entorno
de Claude Code — debe correr solo con las dependencias listadas en
requirements.txt.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
import time
import zipfile
from pathlib import Path

import defusedxml.minidom

WORDML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = " \t\r\n"


def safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Desempaqueta un zip evitando path traversal / symlinks maliciosos."""
    dest = dest.resolve()
    for m in zf.infolist():
        if stat.S_ISLNK(m.external_attr >> 16):
            raise ValueError(f"symlink no permitido en el archivo: {m.filename!r}")
        target = (dest / m.filename).resolve()
        if not target.is_relative_to(dest):
            raise ValueError(f"entrada insegura en el archivo: {m.filename!r}")
        zf.extract(m, dest)


def unpack(docx_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(docx_path) as zf:
        safe_extract(zf, dest_dir)


def rezip(src_dir: Path, out_path: Path) -> None:
    """Reempaqueta un directorio desempaquetado en un .docx/.dotx válido."""
    files = sorted(p for p in src_dir.rglob("*") if p.is_file())
    ct = src_dir / "[Content_Types].xml"
    fd, tmp_name = tempfile.mkstemp(prefix=out_path.name + ".", suffix=".tmp", dir=out_path.parent)
    tmp_out = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as zf:
                if ct.exists():
                    zf.write(ct, ct.relative_to(src_dir), compress_type=zipfile.ZIP_STORED)
                for f in files:
                    if f == ct:
                        continue
                    zf.write(f, f.relative_to(src_dir))
        if out_path.exists():
            mode = out_path.stat().st_mode & 0o777
        else:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp_out, mode)
        _replace_with_retry(tmp_out, out_path)
    finally:
        if tmp_out.exists():
            tmp_out.unlink()


def _replace_with_retry(tmp_out: Path, out_path: Path, attempts: int = 6) -> None:
    """os.replace() puede fallar en Windows con PermissionError (WinError 5)
    si el archivo destino está abierto en Word/antivirus en ese instante.
    Reintenta con backoff antes de rendirse con un mensaje claro."""
    delay = 0.3
    for i in range(attempts):
        try:
            os.replace(tmp_out, out_path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise PermissionError(
                    f"No se pudo guardar '{out_path.name}' porque otro programa lo tiene abierto "
                    "(muy probablemente Word, si lo dejaste abierto de una corrida anterior). "
                    "Cierra el archivo y vuelve a generar el documento."
                )
            time.sleep(delay)
            delay = min(delay * 2, 3)


# ---------------------------------------------------------------------------
# merge_runs: fusiona <w:r> adyacentes con formato idéntico en document.xml
# para que el texto quede buscable como cadena contigua.
# ---------------------------------------------------------------------------

def _is_element(node, tag: str) -> bool:
    name = node.localName or node.tagName
    return name == tag or name.endswith(f":{tag}")


def _find_elements(root, tag: str) -> list:
    results = []

    def traverse(node):
        if node.nodeType == node.ELEMENT_NODE:
            if _is_element(node, tag):
                results.append(node)
            for child in node.childNodes:
                traverse(child)

    traverse(root)
    return results


def _get_child(parent, tag: str):
    for child in parent.childNodes:
        if child.nodeType == child.ELEMENT_NODE and _is_element(child, tag):
            return child
    return None


def _get_children(parent, tag: str) -> list:
    return [c for c in parent.childNodes if c.nodeType == c.ELEMENT_NODE and _is_element(c, tag)]


def _is_adjacent(elem1, elem2) -> bool:
    node = elem1.nextSibling
    while node:
        if node == elem2:
            return True
        if node.nodeType == node.ELEMENT_NODE:
            return False
        if node.nodeType == node.TEXT_NODE and node.data.strip(XML_SPACE):
            return False
        node = node.nextSibling
    return False


def _remove_elements(root, tag: str):
    for elem in _find_elements(root, tag):
        if elem.parentNode:
            elem.parentNode.removeChild(elem)


def _strip_rsid_attrs(runs: list):
    for run in runs:
        for attr in list(run.attributes.values()):
            if "rsid" in attr.name.lower():
                run.removeAttribute(attr.name)


def _next_element_sibling(node):
    sibling = node.nextSibling
    while sibling:
        if sibling.nodeType == sibling.ELEMENT_NODE:
            return sibling
        sibling = sibling.nextSibling
    return None


def _next_sibling_run(node, run_names: set[str]):
    sibling = node.nextSibling
    while sibling:
        if sibling.nodeType == sibling.ELEMENT_NODE:
            if sibling.tagName in run_names:
                return sibling
        sibling = sibling.nextSibling
    return None


def _first_child_run(container, run_names: set[str]):
    for child in container.childNodes:
        if child.nodeType == child.ELEMENT_NODE and child.tagName in run_names:
            return child
    return None


def _can_merge(run1, run2) -> bool:
    rpr1 = _get_child(run1, "rPr")
    rpr2 = _get_child(run2, "rPr")
    if (rpr1 is None) != (rpr2 is None):
        return False
    if rpr1 is None:
        return True
    return rpr1.toxml() == rpr2.toxml()


def _merge_run_content(target, source):
    for child in list(source.childNodes):
        if child.nodeType == child.ELEMENT_NODE:
            name = child.localName or child.tagName
            if name != "rPr" and not name.endswith(":rPr"):
                target.appendChild(child)


def _rendered_text(elem) -> str:
    text = "".join(c.data for c in elem.childNodes if c.nodeType in (c.TEXT_NODE, c.CDATA_SECTION_NODE))
    preserve = elem.getAttribute("xml:space") == "preserve"
    return text if preserve else text.strip(XML_SPACE)


def _consolidate_text(run):
    for tag in ("t", "delText"):
        t_elements = _get_children(run, tag)
        for i in range(len(t_elements) - 1, 0, -1):
            curr, prev = t_elements[i], t_elements[i - 1]
            if not _is_adjacent(prev, curr):
                continue
            merged = _rendered_text(prev) + _rendered_text(curr)
            had_preserve = prev.getAttribute("xml:space") == "preserve" or curr.getAttribute("xml:space") == "preserve"
            new_text = run.ownerDocument.createTextNode(merged)
            for node in list(prev.childNodes):
                if node.nodeType in (node.TEXT_NODE, node.CDATA_SECTION_NODE):
                    prev.removeChild(node)
                else:
                    run.insertBefore(node, curr)
            prev.appendChild(new_text)
            for node in list(curr.childNodes):
                if node.nodeType not in (node.TEXT_NODE, node.CDATA_SECTION_NODE):
                    run.insertBefore(node, curr)
            if merged != merged.strip(XML_SPACE) or had_preserve:
                prev.setAttribute("xml:space", "preserve")
            elif prev.hasAttribute("xml:space"):
                prev.removeAttribute("xml:space")
            run.removeChild(curr)


def _merge_runs_in(container, run_names: set[str]) -> int:
    merge_count = 0
    run = _first_child_run(container, run_names)
    while run:
        while True:
            next_elem = _next_element_sibling(run)
            if next_elem is not None and next_elem.tagName in run_names and _can_merge(run, next_elem):
                _merge_run_content(run, next_elem)
                container.removeChild(next_elem)
                merge_count += 1
            else:
                break
        _consolidate_text(run)
        run = _next_sibling_run(run, run_names)
    return merge_count


def _run_tag_names(root) -> set[str]:
    names = set()
    for attr in root.attributes.values():
        if attr.value == WORDML_NS:
            if attr.name == "xmlns":
                names.add("r")
            elif attr.name.startswith("xmlns:"):
                names.add(attr.name.split(":", 1)[1] + ":r")
    return names or {"w:r", "r"}


def merge_runs_in_document_xml(document_xml_path: Path) -> int:
    """Fusiona runs adyacentes con formato idéntico en document.xml, in place."""
    dom = defusedxml.minidom.parseString(document_xml_path.read_text(encoding="utf-8"))
    root = dom.documentElement
    run_names = _run_tag_names(root)
    _remove_elements(root, "proofErr")
    runs = [e for e in _find_elements(root, "r") if e.tagName in run_names]
    _strip_rsid_attrs(runs)
    merge_count = 0
    for container in {run.parentNode for run in runs}:
        merge_count += _merge_runs_in(container, run_names)
    document_xml_path.write_bytes(dom.toxml(encoding="UTF-8"))
    return merge_count


# ---------------------------------------------------------------------------
# Inserción de imágenes (ej. firmas escaneadas): registra la imagen como
# relationship del paquete .docx desempaquetado y arma el <w:drawing> inline
# que va dentro de un <w:r> para mostrarla.
# ---------------------------------------------------------------------------

EMU_PER_PX = 9525  # a 96 DPI, 1 pulgada = 914400 EMU = 96 px


def png_dimensions(path: Path) -> tuple[int, int]:
    """Ancho/alto en píxeles leyendo el chunk IHDR — evita depender de
    Pillow solo para esto (mismo criterio "vendorizado" que el resto del
    módulo). Firma el formato: 8 bytes de cabecera PNG + IHDR con width/height
    como big-endian uint32 en los bytes [16:24)."""
    data = Path(path).read_bytes()[:26]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"'{Path(path).name}' no es un PNG válido (falta la cabecera IHDR)")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _next_relationship_id(rels_xml: str) -> str:
    ids = [int(m) for m in re.findall(r'Id="rId(\d+)"', rels_xml)]
    return f"rId{max(ids) + 1 if ids else 1}"


def _ensure_png_content_type(tmp_path: Path) -> None:
    """Garantiza que [Content_Types].xml declare la extensión "png" — no
    todas las plantillas traían una imagen desde el original (de donde
    Word hereda ese Default automáticamente), así que insertar una firma
    en una plantilla que nunca tuvo un PNG antes dejaba la parte sin
    content type, y Word/python-docx la rechazan como paquete inválido."""
    ct_path = tmp_path / "[Content_Types].xml"
    ct_xml = ct_path.read_text(encoding="utf-8")
    if 'Extension="png"' in ct_xml or 'Extension="PNG"' in ct_xml:
        return
    new_default = '<Default Extension="png" ContentType="image/png"/>'
    insert_at = ct_xml.index(">", ct_xml.index("<Types ")) + 1
    ct_xml = ct_xml[:insert_at] + new_default + ct_xml[insert_at:]
    ct_path.write_text(ct_xml, encoding="utf-8")


def add_image_relationship(tmp_path: Path, image_path: Path, media_name: str) -> str:
    """Copia `image_path` a word/media/{media_name} dentro del .docx
    desempaquetado en `tmp_path` y agrega su relationship a
    word/_rels/document.xml.rels. Devuelve el rId asignado."""
    _ensure_png_content_type(tmp_path)

    media_dir = tmp_path / "word" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    dest = media_dir / media_name
    dest.write_bytes(Path(image_path).read_bytes())

    rels_path = tmp_path / "word" / "_rels" / "document.xml.rels"
    rels_xml = rels_path.read_text(encoding="utf-8")
    rel_id = _next_relationship_id(rels_xml)
    new_rel = (
        f'<Relationship Id="{rel_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/{media_name}"/>'
    )
    rels_xml = rels_xml.replace("</Relationships>", new_rel + "</Relationships>")
    rels_path.write_text(rels_xml, encoding="utf-8")
    return rel_id


def build_inline_image_run(
    rel_id: str,
    width_px: int,
    height_px: int,
    doc_pr_id: int,
    max_width_px: int = 190,
    max_height_px: int = 60,
    name: str = "Firma",
) -> str:
    """XML de un <w:r> con un <w:drawing> inline mostrando la imagen ya
    registrada bajo `rel_id`, escalada (conservando proporción) para que
    quepa dentro de max_width_px x max_height_px."""
    scale = min(max_width_px / width_px, max_height_px / height_px, 1.0)
    cx = round(width_px * scale * EMU_PER_PX)
    cy = round(height_px * scale * EMU_PER_PX)
    return (
        "<w:r><w:drawing>"
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{doc_pr_id}" name="{name}"/>'
        "<wp:cNvGraphicFramePr>"
        '<a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
        "</wp:cNvGraphicFramePr>"
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:nvPicPr>"
        f'<pic:cNvPr id="{doc_pr_id}" name="{name}"/>'
        "<pic:cNvPicPr/>"
        "</pic:nvPicPr>"
        "<pic:blipFill>"
        f'<a:blip r:embed="{rel_id}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        "<a:stretch><a:fillRect/></a:stretch>"
        "</pic:blipFill>"
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr>"
        "</pic:pic>"
        "</a:graphicData>"
        "</a:graphic>"
        "</wp:inline>"
        "</w:drawing></w:r>"
    )
