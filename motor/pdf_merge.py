"""Fusión de la portada del Tab (convertida a PDF) con el/los PDF(s) de
evidencia que se suben desde la interfaz web, más numeración automática de
página al pie derecho de cada página de evidencia.

Estructura del PDF de portada de un Tab (ya convertido desde el .docx):
  [portada + tabla de exhibits] + [divisoria "EXHIBIT {letra}"] + [PROOF OF SERVICE]

La evidencia va INSERTADA entre la divisoria y "PROOF OF SERVICE" — nunca
al final del documento. El punto de inserción se localiza buscando el
texto "PROOF OF SERVICE" en el PDF ya convertido (no se asume un número de
página fijo, porque el número de páginas de la portada puede variar).
"""

from __future__ import annotations

import io
import os
import re
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


def _localizar_punto_insercion(portada_reader: PdfReader) -> int:
    """Índice de página (0-based) ANTES del cual debe insertarse la
    evidencia: la primera página cuyo texto contiene "PROOF OF SERVICE".
    Si no se encuentra (estructura inesperada de la plantilla), cae a
    insertar al final — mejor que fallar, pero se reporta aparte."""
    for i, page in enumerate(portada_reader.pages):
        try:
            texto = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            texto = ""
        if "PROOF OF SERVICE" in texto.upper():
            return i
    return len(portada_reader.pages)


def combinar_portada_y_evidencia(
    portada_pdf: Path,
    evidencias: list[Path],
    pagina_inicial: int,
    out_path: Path,
) -> tuple[Path, int, bool]:
    """Devuelve (ruta_del_pdf_final, última_página_usada, punto_encontrado).

    `evidencias` es una lista de PDFs (uno por documento/ítem con archivo
    adjunto), insertados en ese orden, numerados de forma continua desde
    `pagina_inicial`, justo después de la divisoria "EXHIBIT {letra}" y
    antes de "PROOF OF SERVICE".

    Si `evidencias` está vacío, copia la portada tal cual.

    `punto_encontrado` es False si no se pudo ubicar "PROOF OF SERVICE" en
    el PDF de portada — en ese caso la evidencia quedó al final como
    respaldo, y quien llame debe avisarlo.

    Escribe primero a un archivo temporal y al final hace un reemplazo
    atómico sobre `out_path` — necesario porque `out_path` puede ser el
    mismo archivo que `portada_pdf`.
    """
    writer = PdfWriter()
    lectores_evidencia: list[PdfReader] = []

    try:
        portada_reader = PdfReader(str(portada_pdf))
        paginas_portada = list(portada_reader.pages)
    except Exception as e:  # noqa: BLE001
        raise PdfMergeError(f"No se pudo leer la portada generada '{Path(portada_pdf).name}': {e}")

    punto = _localizar_punto_insercion(portada_reader)
    punto_encontrado = punto < len(paginas_portada)

    for page in paginas_portada[:punto]:
        writer.add_page(page)

    ultima_pagina = pagina_inicial - 1
    numero = pagina_inicial
    for evidencia_pdf in evidencias:
        try:
            reader = PdfReader(str(evidencia_pdf))
            lectores_evidencia.append(reader)
        except Exception as e:  # noqa: BLE001
            raise PdfMergeError(f"No se pudo leer el PDF de evidencia '{Path(evidencia_pdf).name}': {e}")
        for page in reader.pages:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            overlay = _pagina_numero_overlay(width, height, numero)
            page.merge_page(overlay)
            writer.add_page(page)
            numero += 1
    ultima_pagina = numero - 1

    for page in paginas_portada[punto:]:
        writer.add_page(page)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=out_path.name + ".", suffix=".tmp", dir=out_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            writer.write(f)
        # libera el handle de lectura de los PDF fuente antes de reemplazar
        # out_path — si out_path es el mismo archivo que portada_pdf (caso
        # normal), Windows no deja reemplazar un archivo que sigue abierto.
        for reader in (portada_reader, *lectores_evidencia):
            try:
                reader.stream.close()
            except Exception:  # noqa: BLE001
                pass
        _replace_with_retry(tmp_path, out_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return out_path, ultima_pagina, punto_encontrado


# ---------------------------------------------------------------------------
# Detección heurística de país/año a partir del texto del PDF de evidencia
# (sugerencia editable — nunca se usa a ciegas sin que el usuario la vea).
# ---------------------------------------------------------------------------

_ANIO_RE = re.compile(r"\b(19[9]\d|20[0-3]\d)\b")


def _extraer_texto_primeras_paginas(pdf_path: Path, max_paginas: int = 2) -> str:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:  # noqa: BLE001
        return ""
    texto = []
    for page in reader.pages[:max_paginas]:
        try:
            texto.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(texto)


def sugerir_anio(pdf_path: Path) -> str | None:
    texto = _extraer_texto_primeras_paginas(pdf_path)
    m = _ANIO_RE.search(texto)
    return m.group(0) if m else None


def _buscar_pais(texto: str | None) -> str | None:
    from motor.paises import LISTA_PAISES

    if not texto:
        return None
    texto_low = texto.lower()
    mejor = None
    for pais in LISTA_PAISES:
        # "United States" casi siempre aparece porque estos reportes los
        # publica el gobierno de EE.UU. sobre OTRO país — nunca es el país
        # que realmente se busca aquí, así que se descarta como candidato.
        if pais == "United States":
            continue
        patron = r"\b" + re.escape(pais.lower()) + r"\b"
        if re.search(patron, texto_low):
            if mejor is None or len(pais) > len(mejor):
                mejor = pais
    return mejor


def sugerir_pais(pdf_path: Path) -> str | None:
    # el nombre del archivo suele traer el país de forma más limpia que el
    # texto (ej. "62451_HONDURAS-2024-HUMAN-RIGHTS-REPORT.pdf") — se
    # intenta primero ahí antes de recurrir al contenido del PDF.
    nombre = Path(pdf_path).stem.replace("_", " ").replace("-", " ")
    pais_de_nombre = _buscar_pais(nombre)
    if pais_de_nombre:
        return pais_de_nombre
    return _buscar_pais(_extraer_texto_primeras_paginas(pdf_path))
