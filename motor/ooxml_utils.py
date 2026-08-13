"""Utilidades OOXML de bajo nivel: (des)empaquetar .docx/.dotx y fusionar runs.

Vendorizado y simplificado a partir de las herramientas de la skill `docx`
(merge_runs.py + office/helpers) para que el sistema no dependa del entorno
de Claude Code — debe correr solo con las dependencias listadas en
requirements.txt.
"""

from __future__ import annotations

import os
import stat
import tempfile
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
        os.replace(tmp_out, out_path)
    finally:
        if tmp_out.exists():
            tmp_out.unlink()


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
