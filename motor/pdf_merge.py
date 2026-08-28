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

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject


# ISO 216 A4, en puntos PDF (1 punto = 1/72 pulgada). Las evidencias se
# escalan proporcionalmente y se centran: nunca se recorta contenido.
_A4_WIDTH = 595.2756
_A4_HEIGHT = 841.8898


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


def _normalizar_pagina_a4(page: PageObject) -> PageObject:
    """Devuelve una copia visual de ``page`` centrada en una hoja A4.

    La transformación ocurre solamente al armar el PDF final: el archivo
    de evidencia subido permanece intacto. Se conserva toda la página y su
    proporción, agregando márgenes blancos cuando sea necesario. También se
    aplica primero cualquier rotación declarada en el PDF, para que tanto la
    orientación como la numeración posterior usen coordenadas visuales reales.
    """
    page.transfer_rotation_to_content()
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    if width <= 0 or height <= 0:
        raise PdfMergeError("Una página de evidencia tiene dimensiones inválidas.")

    scale = min(_A4_WIDTH / width, _A4_HEIGHT / height)
    offset_x = (_A4_WIDTH - width * scale) / 2
    offset_y = (_A4_HEIGHT - height * scale) / 2
    a4_page = PageObject.create_blank_page(width=_A4_WIDTH, height=_A4_HEIGHT)
    a4_page.merge_transformed_page(
        page,
        Transformation().scale(scale).translate(offset_x, offset_y),
        over=True,
        expand=False,
    )
    return a4_page


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

    numero = pagina_inicial
    for evidencia_pdf in evidencias:
        try:
            reader = PdfReader(str(evidencia_pdf))
            lectores_evidencia.append(reader)
        except Exception as e:  # noqa: BLE001
            raise PdfMergeError(f"No se pudo leer el PDF de evidencia '{Path(evidencia_pdf).name}': {e}")
        for page in reader.pages:
            page = _normalizar_pagina_a4(page)
            width = _A4_WIDTH
            height = _A4_HEIGHT
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
            except Exception:  # nosec B110  # noqa: BLE001, S110 -- cierre defensivo de pypdf
                pass
        _replace_with_retry(tmp_path, out_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return out_path, ultima_pagina, punto_encontrado


def _solo_letras(texto: str) -> str:
    """Deja únicamente las letras A-Z en mayúscula. Sirve para reconocer una
    página divisoria sin depender de cómo el conversor extraiga las comillas
    tipográficas (“EXHIBIT A”), los espacios, la numeración de renglones del
    margen (1..28) ni el número de página del pie (-4-): todo eso son
    dígitos, signos o espacios y desaparece aquí."""
    return re.sub(r"[^A-Za-z]", "", texto).upper()


def _localizar_paginas_exhibits(portada_reader: PdfReader, letras: list[str]) -> dict[str, int]:
    """Para cada letra pedida, el índice (0-based) de su página divisoria
    "EXHIBIT {letra}" dentro del PDF de portada ya convertido — la evidencia
    de esa letra se inserta INMEDIATAMENTE DESPUÉS de esa página.

    El match es ESTRICTO: la página entera, quitándole dígitos y signos, debe
    ser exactamente "EXHIBITX". Un `in` por substring NO sirve aquí y es
    peligroso: el párrafo NOTICE del cuerpo de la moción cita los exhibits
    por nombre ("...(Exhibit A), Disengagement Letter (...as Exhibit B), y
    ...(Exhibit C)"), así que un substring hace que la primera coincidencia
    de A, B y C caiga en la página del NOTICE y toda la evidencia se
    inserte a media moción en vez de después de su divisoria.

    Si una letra no se encuentra, no se adivina: se reporta como faltante
    (ver combinar_portada_y_evidencia_exhibits) — en un documento que se
    presenta ante la corte, avisar es mejor que insertar en el lugar
    equivocado."""
    objetivos = {letra: _solo_letras(f"EXHIBIT{letra}") for letra in letras}
    encontrados: dict[str, int] = {}
    for i, page in enumerate(portada_reader.pages):
        if len(encontrados) == len(objetivos):
            break
        try:
            texto = _solo_letras(page.extract_text() or "")
        except Exception:  # nosec B112  # noqa: BLE001, S112 -- página sin texto; se revisan las demás
            continue
        for letra, objetivo in objetivos.items():
            if letra not in encontrados and texto == objetivo:
                encontrados[letra] = i
    return encontrados


def combinar_portada_y_evidencia_exhibits(
    portada_pdf: Path,
    evidencia_por_letra: dict[str, list[Path]],
    pagina_inicial: int,
    out_path: Path,
    numerar: bool = True,
) -> tuple[Path, int, list[str]]:
    """Como combinar_portada_y_evidencia, pero para plantillas con VARIOS
    puntos de inserción con nombre (un Exhibit por letra) en vez de un solo
    punto fijo antes de "PROOF OF SERVICE" — ej. Motion to Withdraw, que
    trae Exhibits A/B/C (o B/C/D) cada uno con su propia página divisoria
    "EXHIBIT {letra}".

    `evidencia_por_letra` es un dict {letra: [pdfs...]} — los PDFs de cada
    letra se insertan en ese orden, justo después de la página divisoria de
    esa letra. La numeración de página es continua a través de TODOS los
    exhibits, en el orden en que aparecen en el documento (no en el orden
    del dict).

    `numerar` controla si se dibuja el número de página en cada página de
    evidencia insertada — decisión explícita del usuario (2026-08-17): en
    Motion to Withdraw NO se numeran las páginas de evidencia (a diferencia
    de la regla general del resto del sistema, ver CLAUDE.md), así que
    quien llama esta función para MTW pasa `numerar=False`. Por defecto
    queda en True para no cambiar el comportamiento de otras plantillas que
    lleguen a usar este mismo mecanismo de exhibits con nombre.

    Devuelve (ruta_del_pdf_final, última_página_usada, letras_no_encontradas)
    — `letras_no_encontradas` son letras con evidencia pero sin página
    divisoria localizable en la portada (se avisa, no se bloquea)."""
    writer = PdfWriter()
    lectores_evidencia: list[PdfReader] = []

    try:
        portada_reader = PdfReader(str(portada_pdf))
        paginas_portada = list(portada_reader.pages)
    except Exception as e:  # noqa: BLE001
        raise PdfMergeError(f"No se pudo leer la portada generada '{Path(portada_pdf).name}': {e}")

    letras = [letra for letra, pdfs in evidencia_por_letra.items() if pdfs]
    anclas = _localizar_paginas_exhibits(portada_reader, letras)
    no_encontradas = [letra for letra in letras if letra not in anclas]
    anclas_por_pagina: dict[int, list[str]] = {}
    for letra, idx in anclas.items():
        anclas_por_pagina.setdefault(idx, []).append(letra)

    numero = pagina_inicial
    for i, page in enumerate(paginas_portada):
        writer.add_page(page)
        for letra in anclas_por_pagina.get(i, []):
            for evidencia_pdf in evidencia_por_letra[letra]:
                try:
                    reader = PdfReader(str(evidencia_pdf))
                    lectores_evidencia.append(reader)
                except Exception as e:  # noqa: BLE001
                    raise PdfMergeError(f"No se pudo leer el PDF de evidencia '{Path(evidencia_pdf).name}': {e}")
                for epage in reader.pages:
                    epage = _normalizar_pagina_a4(epage)
                    if numerar:
                        overlay = _pagina_numero_overlay(_A4_WIDTH, _A4_HEIGHT, numero)
                        epage.merge_page(overlay)
                    writer.add_page(epage)
                    numero += 1
    ultima_pagina = numero - 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=out_path.name + ".", suffix=".tmp", dir=out_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            writer.write(f)
        for reader in (portada_reader, *lectores_evidencia):
            try:
                reader.stream.close()
            except Exception:  # nosec B110  # noqa: BLE001, S110 -- cierre defensivo de pypdf
                pass
        _replace_with_retry(tmp_path, out_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return out_path, ultima_pagina, no_encontradas


# ---------------------------------------------------------------------------
# Detección heurística de país/año a partir del texto del PDF de evidencia
# (sugerencia editable — nunca se usa a ciegas sin que el usuario la vea).
# ---------------------------------------------------------------------------

# 1980-2099. Antes era 19[9]\d|20[0-3]\d (1990-2039), que dejaba de sugerir
# el año de reportes de país a partir de 2040 — bug de fecha latente.
_ANIO_RE = re.compile(r"\b(19[89]\d|20\d\d)\b")


def _extraer_texto_primeras_paginas(pdf_path: Path, max_paginas: int = 2) -> str:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:  # noqa: BLE001
        return ""
    texto = []
    for page in reader.pages[:max_paginas]:
        try:
            texto.append(page.extract_text() or "")
        except Exception:  # nosec B112  # noqa: BLE001, S112 -- extracción heurística opcional
            continue
    return "\n".join(texto)


def sugerir_anio(pdf_path: Path) -> str | None:
    texto = _extraer_texto_primeras_paginas(pdf_path)
    m = _ANIO_RE.search(texto)
    return m.group(0) if m else None


def sugerir_titulo_noticia(pdf_path: Path) -> str | None:
    """Sugerencia (editable) del título de una noticia: la primera línea
    no vacía del texto extraído de la página 1 — en la mayoría de los PDFs
    de artículos de prensa esa línea es el titular. No siempre acierta
    (depende de cómo esté armado el PDF), por eso queda como sugerencia,
    nunca se usa sin que el usuario la vea y pueda corregirla."""
    texto = _extraer_texto_primeras_paginas(pdf_path, max_paginas=1)
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea:
            return linea[:200]
    return None


_INITIAL_FEE_RE = re.compile(r"initial\s+application\s+fee", re.IGNORECASE)


def sugerir_tipo_fee(pdf_path: Path) -> str:
    """El recibo trae un campo "Filing Type: ... Initial Application Fee
    for Asylum..." cuando es la cuota inicial. Si esa frase específica
    aparece en el texto, es "Initial"; si no aparece, es "Annual" — regla
    exacta pedida por Hugo (buscar una palabra suelta "annual"/"initial"
    daba falsos positivos con instrucciones/boilerplate no relacionado)."""
    texto = _extraer_texto_primeras_paginas(pdf_path)
    return "Initial" if _INITIAL_FEE_RE.search(texto) else "Annual"


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
        if re.search(patron, texto_low) and (mejor is None or len(pais) > len(mejor)):
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
