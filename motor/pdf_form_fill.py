"""Llenado de formularios PDF con AcroForm reales — a diferencia del resto
del sistema (motor.fill_engine), que llena plantillas .docx manipulando
content controls OOXML.

Primer y único caso hasta ahora: EOIR-33 (Change of Address/Contact
Information Form). Es un PDF oficial de EOIR con campos de formulario
reales (Name, A-Number, direcciones, etc.), no un documento de Word. Los
dos "SIGN HERE" del formulario son campos de firma digital (tipo /Sig) que
no aceptan texto plano vía AcroForm, así que se dibujan encima como un
overlay — la misma técnica que motor.pdf_merge usa para numerar páginas de
evidencia.
"""

from __future__ import annotations

import datetime
import io
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject

from motor.ooxml_utils import png_dimensions

BASE_DIR = Path(__file__).resolve().parent.parent
FIRMAS_DIR = BASE_DIR / "firmas"


class PdfFormFillError(Exception):
    pass


@dataclass
class PdfFormFillResult:
    pdf_path: Path
    preview_images: list[Path]
    validation_ok: bool
    validation_errors: list[str]


def _sanitize_filename_part(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", text)


def _iniciales_nombre_primero(cliente_nombre: str) -> str:
    """Convierte el nombre del cliente tal como se captura en el sistema
    ("APELLIDOS, Nombres", ver static/index.html) a las iniciales en orden
    NOMBRE PRIMERO, ej. "MONCADA SAUCEDA, GABRIEL ELEDIN" -> "G.E.M.S." —
    es la firma abreviada que el despacho usa en la línea SIGN HERE de la
    declaración del EOIR-33."""
    nombre = re.sub(r"\s+et al\s*$", "", cliente_nombre, flags=re.IGNORECASE).strip()
    partes = [p.strip() for p in nombre.split(",", 1)]
    if len(partes) == 2:
        apellidos, nombres = partes
    else:
        apellidos, nombres = "", partes[0]
    orden = f"{nombres} {apellidos}".strip()
    # un apellido compuesto con guión (ej. "AMPIE-ACEVEDO") cuenta como DOS
    # iniciales, una por cada parte -> "L.M.A.A." para "Ampie-Acevedo, Luz
    # Marina", no "L.M.A." (el guión separa igual que un espacio).
    palabras = [w for w in re.split(r"[\s-]+", orden) if w]
    if not palabras:
        return ""
    return "".join(f"{w[0].upper()}." for w in palabras)


def _firma_paralegal_path(preparador: str | None) -> Path | None:
    if not preparador:
        return None
    path = FIRMAS_DIR / "preparadores" / f"{_sanitize_filename_part(preparador)}.png"
    return path if path.is_file() else None


def _wrap_court_address(value: str) -> str:
    """Aprovecha el AcroForm multilínea para que la dirección no se corte."""
    return "\n".join(
        textwrap.wrap(value, width=38, break_long_words=False, break_on_hyphens=False)
    )


def _rect_de_campo(reader: PdfReader, nombre_campo: str) -> tuple[float, float, float, float] | None:
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/T") == nombre_campo:
                rect = obj.get("/Rect")
                if rect:
                    return tuple(float(x) for x in rect)
    return None


def _overlay_texto(width: float, height: float, x: float, y: float, texto: str) -> PageObject:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setFont("Helvetica-Oblique", 13)
    c.drawString(x, y, texto)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _overlay_imagen(width: float, height: float, x: float, y: float, w: float, h: float, image_path: Path) -> PageObject:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.drawImage(str(image_path), x, y, width=w, height=h, mask="auto", preserveAspectRatio=True, anchor="sw")
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _resolve_values(case: dict, document_instance: dict) -> dict[str, str | bool]:
    from motor.case_store import a_number_para_documento, nombre_para_documento

    hoy = datetime.datetime.now(datetime.timezone.utc).date().strftime("%m/%d/%Y")
    return {
        "cliente_nombre": nombre_para_documento(case),
        "a_number": a_number_para_documento(case),
        "preparador": case.get("preparador") or "",
        "fecha_hoy": hoy,
        "direccion_anterior": (document_instance.get("direccion_anterior") or "").strip(),
        "ciudad_anterior": (document_instance.get("ciudad_anterior") or "").strip(),
        "direccion_actual": (document_instance.get("direccion_actual") or "").strip(),
        "ciudad_actual": (document_instance.get("ciudad_actual") or "").strip(),
        "telefono_anterior": (document_instance.get("telefono_anterior") or "").strip(),
        "email_anterior": (document_instance.get("email_anterior") or "").strip(),
        "telefono_actual": (document_instance.get("telefono_actual") or "").strip(),
        "email_actual": (document_instance.get("email_actual") or "").strip(),
        "direccion_servicio_1": (document_instance.get("direccion_servicio_1") or "").strip(),
        "direccion_servicio_2": (document_instance.get("direccion_servicio_2") or "").strip(),
        "direccion_corte": _wrap_court_address((document_instance.get("direccion_corte") or "").strip()),
        "servicio_ecas": bool(document_instance.get("servicio_ecas")),
    }


def generar_pdf_formulario(
    case: dict,
    document_instance: dict,
    plantillas_dir: Path | str = BASE_DIR / "plantillas",
    output_dir: Path | str = BASE_DIR / "output",
) -> PdfFormFillResult:
    plantillas_dir = Path(plantillas_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    template_id = document_instance["template_id"]
    template_dir = plantillas_dir / template_id
    field_map = json.loads((template_dir / "field_map.json").read_text(encoding="utf-8"))
    pdf_path = template_dir / field_map["archivo"]
    if not pdf_path.exists():
        raise PdfFormFillError(f"No se encontró la plantilla: {pdf_path}")

    values = _resolve_values(case, document_instance)

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.append(reader)

    datos_pdf = {}
    for campo_pdf, nombre_valor in (field_map.get("campos_texto") or {}).items():
        datos_pdf[campo_pdf] = values.get(nombre_valor) or ""

    casilla = field_map.get("casilla_no_service_needed")
    if casilla:
        if isinstance(casilla, str):
            campo_casilla, valor_casilla = casilla, True
        else:
            campo_casilla = casilla["campo_pdf"]
            valor_casilla = bool(values.get(casilla["valor"]))
        datos_pdf[campo_casilla] = "/Yes" if valor_casilla else "/Off"

    for page in writer.pages:
        writer.update_page_form_field_values(page, datos_pdf, auto_regenerate=False)

    acroform = writer._root_object.get("/AcroForm")
    if acroform is not None:
        acroform.get_object()[NameObject("/NeedAppearances")] = BooleanObject(False)

    firma_cliente = field_map.get("firma_cliente_iniciales")
    if firma_cliente:
        iniciales = _iniciales_nombre_primero(values["cliente_nombre"])
        rect = _rect_de_campo(reader, firma_cliente["campo_pdf"])
        if iniciales and rect:
            pagina_idx = firma_cliente.get("pagina", 0)
            page = writer.pages[pagina_idx]
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            x0, y0, _x1, y1 = rect
            overlay = _overlay_texto(w, h, x0 + 4, y0 + (y1 - y0 - 13) / 2 + 2, iniciales)
            page.merge_page(overlay)

    firma_paralegal = field_map.get("firma_paralegal_imagen")
    if firma_paralegal:
        img = _firma_paralegal_path(values["preparador"])
        rect = _rect_de_campo(reader, firma_paralegal["campo_pdf"])
        if img and rect:
            pagina_idx = firma_paralegal.get("pagina", 0)
            page = writer.pages[pagina_idx]
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            x0, y0, x1, y1 = rect
            # la firma se asienta sobre la línea (como una firma real), con
            # poco margen porque arriba de la caja está pegado el texto del
            # checkbox "No service needed..." — no hay espacio para una
            # firma mucho más alta que la caja sin encimarse con ese texto.
            alto = (y1 - y0) * 1.15
            img_w, img_h = png_dimensions(img)
            ancho = min((x1 - x0) * 0.65, alto * (img_w / img_h))
            overlay = _overlay_imagen(w, h, x0 + 10, y0, ancho, alto, img)
            page.merge_page(overlay)

    cliente = (
        _sanitize_filename_part(case.get("cliente_nombre") or "caso")
        .replace(" ", "_")
        .replace(",", "")[:30]
        .rstrip("._-")
    ) or "caso"
    a_num = re.sub(r"\D", "", case.get("a_number") or "")
    base_name = f"{cliente}_{a_num}_EOIR33"
    salida = output_dir / f"{base_name}.pdf"
    contador = 1
    while salida.exists():
        contador += 1
        salida = output_dir / f"{base_name}_{contador}.pdf"

    with open(salida, "wb") as f:
        writer.write(f)

    ok, errores = _validar_pdf(salida, len(reader.pages), datos_pdf)

    from motor.pdf_tools import PdfToolsError, rasterize

    preview_images: list[Path] = []
    try:
        preview_images = rasterize(salida, output_dir / "_preview" / salida.stem)
    except PdfToolsError as e:
        # no bloquea la generación del PDF, pero se reporta: sin esto nadie
        # revisó el documento página por página (mismo criterio que
        # motor.fill_engine.generar_documento).
        print(f"Aviso: no se pudo generar la vista previa del EOIR-33: {e}")

    return PdfFormFillResult(
        pdf_path=salida,
        preview_images=preview_images,
        validation_ok=ok,
        validation_errors=errores,
    )


def _validar_pdf(
    pdf_path: Path, paginas_esperadas: int, valores_esperados: dict[str, str] | None = None
) -> tuple[bool, list[str]]:
    errores = []
    try:
        reader = PdfReader(str(pdf_path))
        if len(reader.pages) != paginas_esperadas:
            errores.append(
                f"El PDF generado tiene {len(reader.pages)} página(s), se esperaban {paginas_esperadas}."
            )
        fields = reader.get_fields() or {}
        for nombre, esperado in (valores_esperados or {}).items():
            field = fields.get(nombre)
            if field is None:
                errores.append(f"Falta el campo AcroForm '{nombre}' en el PDF generado.")
                continue
            actual = str(field.get("/V") or "")
            if actual != str(esperado):
                errores.append(f"El campo '{nombre}' quedó como {actual!r}; se esperaba {str(esperado)!r}.")

        widgets_por_nombre = {}
        for page in reader.pages:
            for annot in page.get("/Annots") or []:
                obj = annot.get_object()
                if obj.get("/Subtype") != "/Widget":
                    continue
                parent_ref = obj.get("/Parent")
                parent = parent_ref.get_object() if parent_ref else None
                nombre = obj.get("/T") or (parent.get("/T") if parent else None)
                if nombre:
                    widgets_por_nombre.setdefault(nombre, []).append(obj)
        for nombre in (valores_esperados or {}):
            widgets = widgets_por_nombre.get(nombre) or []
            if not widgets:
                errores.append(f"El campo '{nombre}' no tiene widget visible.")
            elif not any((w.get("/AP") or {}).get("/N") for w in widgets):
                errores.append(f"El campo '{nombre}' no tiene una apariencia visual actualizada.")
    except Exception as e:  # noqa: BLE001
        errores.append(f"El PDF generado no se pudo volver a abrir: {e}")
    return (not errores, errores)
