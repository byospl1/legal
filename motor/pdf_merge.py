"""Fusión de la portada del Tab (convertida a PDF) con el PDF de evidencia
que se sube desde la interfaz web, más numeración automática de página al
pie derecho de cada página de evidencia.

Flujo por Tab: [páginas de portada + tabla de exhibits + divisoria
"EXHIBIT X" (ya vienen del .docx convertido a PDF)] + [páginas de
evidencia subidas por el usuario, cada una estampada con su número de
página, continuando la numeración desde donde se quedó el Tab anterior
del mismo caso].
"""

from __future__ import annotations

import io
import os
import tempfile
import time
from pathlib import Path

from pypdf import PdfReader, PdfWriter


class PdfMergeError(Exception):
    pass


def contar_paginas(pdf_path: Path) -> int:
    try:
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception as e:  # noqa: BLE001
        raise PdfMergeError(f"No se pudo leer '{Path(pdf_path).name}' como PDF: {e}")


def _pagina_numero_overlay(width: float, height: float, numero: int):
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setFont("Times-Roman", 11)
    margen_derecho = 40
    margen_inferior = 28
    c.drawRightString(width - margen_derecho, margen_inferior, str(numero))
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _replace_with_retry(tmp_path: Path, out_path: Path, attempts: int = 6) -> None:
    """Igual que motor.ooxml_utils._replace_with_retry: en Windows,
    reemplazar un archivo abierto en un lector de PDF falla con
    PermissionError — reintenta con backoff antes de rendirse."""
    delay = 0.3
    for i in range(attempts):
        try:
            os.replace(tmp_path, out_path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise PermissionError(
                    f"No se pudo guardar '{out_path.name}' porque otro programa lo tiene abierto "
                    "(ciérralo, ej. si lo tienes abierto en un lector de PDF, e intenta de nuevo)."
                )
            time.sleep(delay)
            delay = min(delay * 2, 3)


def combinar_portada_y_evidencia(
    portada_pdf: Path,
    evidencia_pdf: Path | None,
    pagina_inicial: int,
    out_path: Path,
) -> tuple[Path, int]:
    """Devuelve (ruta_del_pdf_final, última_página_usada).

    Si no hay evidencia, simplemente copia la portada tal cual y la última
    página usada es `pagina_inicial - 1` (no consume numeración).

    Escribe primero a un archivo temporal y al final hace un reemplazo
    atómico sobre `out_path` — necesario porque `out_path` puede ser el
    mismo archivo que `portada_pdf` (se sobreescribe la portada "sola" con
    la versión final ya con evidencia incluida).
    """
    writer = PdfWriter()
    evidencia_reader = None

    try:
        portada_reader = PdfReader(str(portada_pdf))
        for page in portada_reader.pages:
            writer.add_page(page)
    except Exception as e:  # noqa: BLE001
        raise PdfMergeError(f"No se pudo leer la portada generada '{Path(portada_pdf).name}': {e}")

    ultima_pagina = pagina_inicial - 1

    if evidencia_pdf is not None:
        try:
            evidencia_reader = PdfReader(str(evidencia_pdf))
            paginas_evidencia = list(evidencia_reader.pages)
        except Exception as e:  # noqa: BLE001
            raise PdfMergeError(f"No se pudo leer el PDF de evidencia '{Path(evidencia_pdf).name}': {e}")

        numero = pagina_inicial
        for page in paginas_evidencia:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            overlay = _pagina_numero_overlay(width, height, numero)
            page.merge_page(overlay)
            writer.add_page(page)
            numero += 1
        ultima_pagina = numero - 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=out_path.name + ".", suffix=".tmp", dir=out_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            writer.write(f)
        # libera el handle de lectura de los PDF fuente antes de reemplazar
        # out_path — si out_path es el mismo archivo que portada_pdf (caso
        # normal), Windows no deja reemplazar un archivo que sigue abierto.
        for reader in (portada_reader, evidencia_reader):
            if reader is not None:
                try:
                    reader.stream.close()
                except Exception:  # noqa: BLE001
                    pass
        _replace_with_retry(tmp_path, out_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return out_path, ultima_pagina
