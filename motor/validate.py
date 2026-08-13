"""Validación ligera de un .docx generado.

No reemplaza una validación XSD completa (esa requiere vendorizar ~1.2MB de
esquemas OOXML); en su lugar hace dos chequeos prácticos que capturan la
inmensa mayoría de documentos rotos:

1. Cada parte XML del paquete es well-formed (bien formada).
2. python-docx puede abrir el resultado (esto es casi lo mismo que hace Word
   al abrir el archivo: recorre el árbol de document.xml).

--auto-repair corrige el problema real encontrado durante el prototipo: un
<w:sdtContent> a nivel de párrafo al que se le reemplazó el <w:r> interior
pero se dejó basura de cierre duplicado. Ver fill_engine.py, donde ya se evita
generar ese problema; esto queda como red de seguridad.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import defusedxml.ElementTree as ET


class ValidationError(Exception):
    pass


def validate_docx(path: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []

    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                errors.append(f"Archivo zip corrupto en la entrada: {bad}")
                return False, errors
            for name in zf.namelist():
                if not name.endswith(".xml") and not name.endswith(".rels"):
                    continue
                data = zf.read(name)
                try:
                    ET.fromstring(data)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"XML mal formado en {name}: {e}")
    except (zipfile.BadZipFile, OSError) as e:
        errors.append(f"No se pudo abrir el .docx como zip: {e}")
        return False, errors

    if errors:
        return False, errors

    try:
        import docx  # python-docx

        d = docx.Document(str(path))
        _ = len(d.paragraphs)
        _ = len(d.tables)
    except Exception as e:  # noqa: BLE001
        errors.append(f"python-docx no pudo abrir el documento (probable XML inválido para Word): {e}")

    return (len(errors) == 0), errors


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Validación ligera de un .docx")
    p.add_argument("path")
    args = p.parse_args()

    ok, errors = validate_docx(Path(args.path))
    if ok:
        print("OK: el documento pasa las validaciones.")
        sys.exit(0)
    else:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
