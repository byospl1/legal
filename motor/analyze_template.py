"""Alta de plantillas nuevas — analiza un .dotx y genera field_map.json
(+ xml_fragments.json si tiene tabla de exhibits) para que fill_engine.py
pueda llenarlo sin conocer nada específico del documento de antemano.

Uso:
    python -m motor.analyze_template <archivo.dotx> --template-id i589-tab-cover

Sigue el algoritmo de la sección 5.1 de la especificación:
1. Desempaquetar + merge_runs.
2. Extraer todos los <w:sdt> de forma balanceada (con conteo de profundidad).
3. Cruzar bookmarks (NAME/ANUMBER/TYPE...) con campos REF para armar
   grupos maestro/mirror.
4. Detectar campos automáticos de Word (DATE, SEQ) → no tocar.
5. Detectar candidatos a sync_group manual (comboBox con el mismo catálogo
   de opciones apareciendo más de una vez, y que no es un grupo bookmark).
6. Si hay tabla de exhibits, capturar el XML literal de la tabla y de la
   página divisoria "EXHIBIT {letra}" en xml_fragments.json.

El resultado es un borrador: igual que dice la especificación, los grupos
sync_manual y los nombres semánticos de campos anidados/simples deben
confirmarse con un humano antes de usarse en producción (ver
plantillas/i589-tab-cover/field_map.json, que ya fue revisado a mano).
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

from motor.ooxml_utils import merge_runs_in_document_xml, unpack

SDT_OPEN = "<w:sdt>"
SDT_CLOSE = "</w:sdt>"
SDT_CONTENT_OPEN = "<w:sdtContent>"
SDT_CONTENT_CLOSE = "</w:sdtContent>"


class Sdt:
    def __init__(self, start: int, end: int, depth: int, xml: str):
        self.start = start
        self.end = end
        self.depth = depth
        self.xml = xml
        self.children: list["Sdt"] = []
        self.id = self._extract_id()
        self.content_start_offset, self.content_xml = self._extract_content()

    def _extract_id(self) -> str | None:
        m = re.search(r'<w:id w:val="(-?\d+)"', self.xml)
        return m.group(1) if m else None

    def _extract_content(self) -> tuple[int, str]:
        i = self.xml.find(SDT_CONTENT_OPEN)
        if i == -1:
            return -1, ""
        j = self._matching_content_close(i)
        content_start = i + len(SDT_CONTENT_OPEN)
        return content_start, self.xml[content_start:j]

    def _matching_content_close(self, open_idx: int) -> int:
        """Encuentra el </w:sdtContent> que cierra el que abre en open_idx,
        contando aperturas/cierres anidados (por los SDT internos)."""
        depth = 1
        pos = open_idx + len(SDT_CONTENT_OPEN)
        while depth > 0:
            next_open = self.xml.find(SDT_CONTENT_OPEN, pos)
            next_close = self.xml.find(SDT_CONTENT_CLOSE, pos)
            if next_close == -1:
                raise ValueError("sdtContent sin cierre correspondiente")
            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + len(SDT_CONTENT_OPEN)
            else:
                depth -= 1
                pos = next_close + len(SDT_CONTENT_CLOSE)
        return pos - len(SDT_CONTENT_CLOSE)

    @property
    def nivel(self) -> str:
        stripped = self.content_xml.lstrip()
        return "parrafo" if stripped.startswith("<w:p ") or stripped.startswith("<w:p>") else "inline"

    @property
    def tipo(self) -> str:
        if "<w:dropDownList" in self.xml[: self.content_start_offset]:
            return "dropdown"
        if "<w:comboBox" in self.xml[: self.content_start_offset]:
            return "combobox"
        if "<w:date " in self.xml[: self.content_start_offset] or "<w:date>" in self.xml[: self.content_start_offset]:
            return "date_picker"
        return "texto"

    @property
    def list_items(self) -> list[str]:
        return re.findall(r'<w:listItem w:displayText="([^"]*)"', self.xml[: self.content_start_offset])

    @property
    def placeholder_text(self) -> str:
        m = re.search(r"<w:t[^>]*>([^<]*)</w:t>", self.content_xml)
        return m.group(1) if m else ""


def extract_top_level_sdts(document_xml: str) -> list[Sdt]:
    """Recorrido con contador de profundidad — NO usar regex no-greedy simple,
    se rompe con SDT anidados (ver juez en el template de prueba)."""
    tokens = []
    for m in re.finditer(r"<w:sdt>|</w:sdt>", document_xml):
        tokens.append((m.start(), m.group()))

    top_level: list[Sdt] = []
    stack: list[int] = []  # start offsets

    for pos, tok in tokens:
        if tok == SDT_OPEN:
            stack.append(pos)
        else:  # </w:sdt>
            start = stack.pop()
            end = pos + len(SDT_CLOSE)
            if len(stack) == 0:
                xml = document_xml[start:end]
                sdt = Sdt(start, end, 0, xml)
                _attach_nested(sdt)
                top_level.append(sdt)
    return top_level


def _attach_nested(sdt: Sdt) -> None:
    """Encuentra los <w:sdt> hijos directos dentro del sdtContent de `sdt`
    (para armar campos_anidados como el del juez)."""
    inner_tokens = list(re.finditer(r"<w:sdt>|</w:sdt>", sdt.content_xml))
    depth = 0
    for m in inner_tokens:
        if m.group() == SDT_OPEN:
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = m.end()
                child_xml = sdt.content_xml[start:end]
                child = Sdt(start, end, 1, child_xml)
                sdt.children.append(child)


def find_bookmarks(document_xml: str) -> dict[str, int]:
    out = {}
    for m in re.finditer(r'<w:bookmarkStart w:id="(\d+)" w:name="([^"]+)"', document_xml):
        name = m.group(2)
        if name.startswith("_"):
            continue  # bookmarks internos de Word (_Hlk...), no relevantes
        out[name] = m.start()
    return out


def find_ref_fields(document_xml: str) -> dict[str, list[int]]:
    """Para cada `REF <BOOKMARK>`, devuelve la posición del <w:sdt> mirror
    que sigue (el resultado cacheado del campo)."""
    out: dict[str, list[int]] = {}
    for m in re.finditer(r"REF (\w+)", document_xml):
        name = m.group(1)
        sep = document_xml.find('<w:fldChar w:fldCharType="separate"', m.end())
        end = document_xml.find('<w:fldChar w:fldCharType="end"', m.end())
        if sep == -1 or end == -1:
            continue
        sdt_start = document_xml.find(SDT_OPEN, sep, end)
        if sdt_start == -1:
            continue
        out.setdefault(name, []).append(sdt_start)
    return out


def find_automatic_fields(document_xml: str) -> list[dict]:
    out = []
    for m in re.finditer(r"<w:instrText[^>]*>\s*(DATE|SEQ)\b([^<]*)</w:instrText>", document_xml):
        out.append({"tipo": m.group(1), "descripcion": f"Campo de Word autoactualizable ({m.group(1).strip()}{m.group(2)}), no tocar"})
    return out


def build_field_map(document_xml: str, template_id: str, archivo: str) -> dict:
    top_sdts = extract_top_level_sdts(document_xml)
    by_start = {s.start: s for s in top_sdts}

    bookmarks = find_bookmarks(document_xml)
    refs = find_ref_fields(document_xml)

    grupos_bookmark = []
    used_ids: set[str] = set()
    for name, bpos in bookmarks.items():
        # el maestro es el próximo sdt de nivel superior después del bookmark
        candidates = [s for s in top_sdts if s.start > bpos]
        if not candidates:
            continue
        master = min(candidates, key=lambda s: s.start)
        mirror_positions = refs.get(name, [])
        mirrors = []
        for mp in mirror_positions:
            # el mirror sdt puede no ser top-level exacto en offset si hay anidamiento;
            # buscamos el sdt de nivel superior cuyo rango lo contiene
            for s in top_sdts:
                if s.start <= mp < s.end:
                    mirrors.append(s.id)
                    used_ids.add(s.id)
                    break
        used_ids.add(master.id)
        grupos_bookmark.append({
            "bookmark": name,
            "nombre": name.lower(),
            "maestro": master.id,
            "mirrors": mirrors,
        })

    campos_anidados = []
    nested_outer_ids = set()
    for s in top_sdts:
        if s.children:
            nested_outer_ids.add(s.id)
            for child in s.children:
                campos_anidados.append({
                    "w_id_exterior": s.id,
                    "w_id_interior": child.id,
                    "nombre": None,
                    "tipo": child.tipo,
                    "opciones": child.list_items,
                })

    # candidatos a sync_group manual: comboBox con catálogo de opciones idéntico
    # repetido más de una vez, fuera de los grupos bookmark y de los anidados.
    remaining = [s for s in top_sdts if s.id not in used_ids and s.id not in nested_outer_ids]
    by_options: dict[tuple, list[Sdt]] = {}
    for s in remaining:
        if s.tipo == "combobox" and s.list_items:
            key = tuple(sorted(s.list_items))
            by_options.setdefault(key, []).append(s)

    grupos_sync_manual = []
    sync_ids = set()
    for key, sdts in by_options.items():
        if len(sdts) > 1:
            grupos_sync_manual.append({
                "nombre": None,
                "ids": [s.id for s in sdts],
                "tipo": "combobox",
                "opciones": list(key),
            })
            sync_ids.update(s.id for s in sdts)

    campos_simples = []
    for s in remaining:
        if s.id in sync_ids:
            continue
        campos_simples.append({
            "w_id": s.id,
            "nombre": None,
            "tipo": s.tipo,
            "nivel": s.nivel,
            "opciones": s.list_items,
            "placeholder_actual": s.placeholder_text,
        })

    campos_automaticos = find_automatic_fields(document_xml)

    tiene_tabla = bool(re.search(r">TAB<.*?>DESCRIPTION<.*?>PAGES<", document_xml, re.S)) or bool(
        re.search(r">DESCRIPTION<.*?>PAGES<", document_xml, re.S)
    )

    return {
        "template_id": template_id,
        "archivo": archivo,
        "campos_simples": campos_simples,
        "campos_anidados": campos_anidados,
        "grupos_bookmark": grupos_bookmark,
        "grupos_sync_manual": grupos_sync_manual,
        "campos_automaticos_no_tocar": campos_automaticos,
        "tiene_tabla_exhibits": tiene_tabla,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Analiza un .dotx y genera field_map.json")
    p.add_argument("dotx_path")
    p.add_argument("--template-id", required=True)
    p.add_argument("--out-dir", default=None, help="Directorio de salida (default: plantillas/<template-id>/)")
    args = p.parse_args()

    dotx_path = Path(args.dotx_path)
    out_dir = Path(args.out_dir) if args.out_dir else Path("plantillas") / args.template_id
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        unpack(dotx_path, tmp_path)
        doc_path = tmp_path / "word" / "document.xml"
        merge_runs_in_document_xml(doc_path)
        document_xml = doc_path.read_text(encoding="utf-8")

    field_map = build_field_map(document_xml, args.template_id, dotx_path.name)

    out_path = out_dir / "field_map.json"
    out_path.write_text(json.dumps(field_map, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"field_map.json escrito en {out_path}")
    print(f"  campos_simples: {len(field_map['campos_simples'])}")
    print(f"  campos_anidados: {len(field_map['campos_anidados'])}")
    print(f"  grupos_bookmark: {len(field_map['grupos_bookmark'])}")
    print(f"  grupos_sync_manual: {len(field_map['grupos_sync_manual'])}")
    print(f"  campos_automaticos_no_tocar: {len(field_map['campos_automaticos_no_tocar'])}")
    print(f"  tiene_tabla_exhibits: {field_map['tiene_tabla_exhibits']}")
    print("\nRevisa y completa los campos 'nombre: null' a mano antes de usar en producción.")


if __name__ == "__main__":
    main()
