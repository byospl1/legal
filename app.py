"""Servidor local (Flask) que expone el sistema de llenado de Tabs EOIR a
través de una interfaz HTML con botones interactivos.

Uso:
    python app.py
    (abre http://127.0.0.1:5000 en el navegador)
"""

from __future__ import annotations

import json
import re
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from motor.case_store import CASE_STORE_DIR, list_cases, load_case, next_tab_letra, save_case, siguiente_pagina
from motor.exhibit_builder import (
    CATEGORY_ORDER,
    ITEMS_POR_CATEGORIA,
    TIPOS_DOCUMENTO_IDENTIDAD,
    TIPOS_SUPPLEMENTAL_EVIDENCE,
)
from motor.fill_engine import FillEngineError, generar_lote
from motor.pdf_merge import (
    PdfMergeError,
    combinar_portada_y_evidencia,
    contar_paginas,
    sugerir_anio,
    sugerir_pais,
    sugerir_tipo_fee,
    sugerir_titulo_noticia,
)
from motor.validate import ValidationError

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
INPUT_DIR = BASE_DIR / "input"
PLANTILLAS_DIR = BASE_DIR / "plantillas"
EVIDENCIA_DIR = OUTPUT_DIR / "_evidencia"

INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
CASE_STORE_DIR.mkdir(exist_ok=True)
EVIDENCIA_DIR.mkdir(parents=True, exist_ok=True)

# Registro en memoria de los PDFs de evidencia subidos en esta sesión del
# servidor (id -> ruta + número de páginas). Los archivos también quedan en
# disco (EVIDENCIA_DIR) para no perderlos, pero el número de páginas se
# recalcula si hace falta.
_EVIDENCIAS: dict[str, dict] = {}

app = Flask(__name__, static_folder="static", static_url_path="/static")


def _catalogos() -> dict:
    return json.loads((BASE_DIR / "catalogos.json").read_text(encoding="utf-8"))


def _registro_plantillas() -> dict:
    return json.loads((PLANTILLAS_DIR / "registro.json").read_text(encoding="utf-8"))


def _list_salidas() -> list[dict]:
    salidas = []
    for docx_path in sorted(OUTPUT_DIR.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True):
        pdf_path = docx_path.with_suffix(".pdf")
        preview_dir = OUTPUT_DIR / "_preview" / docx_path.stem
        previews = sorted(p.name for p in preview_dir.glob("*.jpg")) if preview_dir.exists() else []
        salidas.append(
            {
                "docx": docx_path.name,
                "pdf": pdf_path.name if pdf_path.exists() else None,
                "previews": previews,
                "preview_dir": docx_path.stem,
            }
        )
    return salidas


@app.get("/")
def index():
    return send_from_directory(BASE_DIR / "static", "index.html")


@app.get("/como-funciona")
def como_funciona():
    return send_from_directory(BASE_DIR / "static", "como-funciona.html")


@app.get("/api/init")
def api_init():
    return jsonify(
        {
            "catalogos": _catalogos(),
            "plantillas": _registro_plantillas()["plantillas"],
            "casos": list_cases(),
            "salidas": _list_salidas(),
            "items_por_categoria": ITEMS_POR_CATEGORIA,
            "tipos_documento_identidad": TIPOS_DOCUMENTO_IDENTIDAD,
            "tipos_supplemental_evidence": TIPOS_SUPPLEMENTAL_EVIDENCE,
        }
    )


@app.get("/api/casos/<case_id>")
def api_get_caso(case_id: str):
    case = load_case(case_id)
    if case is None:
        return jsonify({"error": "Caso no encontrado"}), 404
    return jsonify(case)


@app.post("/api/casos")
def api_save_caso():
    case = request.get_json(force=True)
    required = ["cliente_nombre", "a_number", "corte_sede", "juez", "proxima_audiencia", "abogado", "preparador"]
    faltantes = [campo for campo in required if not case.get(campo)]
    if faltantes:
        return jsonify({"error": f"Faltan campos requeridos: {', '.join(faltantes)}"}), 400
    if len(re.sub(r"\D", "", case["a_number"])) < 8:
        return jsonify({"error": "El A# no parece válido (debe traer al menos 8 dígitos, ej. A 248-003-356)"}), 400
    saved = save_case(case)
    return jsonify(saved)


@app.get("/api/casos/<case_id>/siguiente-letra")
def api_siguiente_letra(case_id: str):
    case = load_case(case_id)
    ultimo = case.get("ultimo_tab_letra") if case else None
    return jsonify({"siguiente_letra": next_tab_letra(ultimo)})


@app.get("/api/casos/<case_id>/siguiente-pagina")
def api_siguiente_pagina(case_id: str):
    case = load_case(case_id)
    return jsonify({"siguiente_pagina": siguiente_pagina(case) if case else 1})


@app.post("/api/evidencia")
def api_subir_evidencia():
    archivo = request.files.get("file")
    if archivo is None or not archivo.filename:
        return jsonify({"error": "No se recibió ningún archivo"}), 400
    if not archivo.filename.lower().endswith(".pdf"):
        return jsonify({"error": "El archivo de evidencia debe ser un PDF"}), 400

    # "tipo" identifica de qué documento se trata (ej. "country_reports",
    # "osac") — solo se usa para sugerir país/año por texto, es opcional.
    tipo = request.form.get("tipo") or ""

    EVIDENCIA_DIR.mkdir(parents=True, exist_ok=True)
    evidencia_id = uuid.uuid4().hex
    nombre_seguro = secure_filename(archivo.filename) or "evidencia.pdf"
    destino = EVIDENCIA_DIR / f"{evidencia_id}__{nombre_seguro}"
    archivo.save(destino)

    try:
        num_paginas = contar_paginas(destino)
    except PdfMergeError as e:
        destino.unlink(missing_ok=True)
        return jsonify({"error": str(e)}), 400

    _EVIDENCIAS[evidencia_id] = {"path": destino, "num_paginas": num_paginas, "nombre": archivo.filename}

    respuesta = {"evidencia_id": evidencia_id, "num_paginas": num_paginas, "nombre": archivo.filename}
    if tipo in ("country_reports", "osac"):
        try:
            respuesta["anio_sugerido"] = sugerir_anio(destino)
            respuesta["pais_sugerido"] = sugerir_pais(destino)
        except Exception:  # noqa: BLE001
            # la sugerencia es "mejor esfuerzo" — si falla, simplemente no se
            # sugiere nada, no debe tumbar la subida del archivo.
            respuesta["anio_sugerido"] = None
            respuesta["pais_sugerido"] = None
    elif tipo == "fee_receipt":
        try:
            respuesta["tipo_fee_sugerido"] = sugerir_tipo_fee(destino)
        except Exception:  # noqa: BLE001
            respuesta["tipo_fee_sugerido"] = None
    elif tipo == "news":
        try:
            respuesta["titulo_sugerido"] = sugerir_titulo_noticia(destino)
        except Exception:  # noqa: BLE001
            respuesta["titulo_sugerido"] = None

    return jsonify(respuesta)


def _resolver_paginas_evidencia(pagina_inicial_lote: int, exhibits: list[dict]) -> int:
    """Para cada Tab con documentos de evidencia adjuntos, calcula la
    página de inicio de cada documento en orden (categoría, luego ítem/
    persona dentro de la categoría), continuando desde
    `pagina_inicial_lote`. Sobrescribe tg['paginas'] con el rango
    calculado, tg['evidencias'] con la info resuelta de los ítems de
    catálogo fijo (ver motor.exhibit_builder.ITEMS_POR_CATEGORIA), y cada
    identidad de tg['identidades'] con su propia 'evidencia' resuelta
    (Form of Identity tiene un documento por persona, no un catálogo fijo).
    Devuelve la próxima página disponible después de este lote."""
    pagina = pagina_inicial_lote
    for tg in exhibits:
        evidencias_ids = tg.get("evidencias") or {}
        identidades = tg.get("identidades") or []
        documentos_se = tg.get("documentos_se") or []
        tiene_algo = (
            bool(evidencias_ids)
            or any(i.get("evidencia_id") for i in identidades)
            or any(d.get("evidencia_id") for d in documentos_se)
        )
        if not tiene_algo:
            continue
        categorias = tg.get("categorias") or []
        resueltas: dict[str, dict] = {}
        inicio_tab = None
        for categoria in CATEGORY_ORDER:
            if categoria not in categorias:
                continue
            if categoria == "form_of_identity":
                for ident in identidades:
                    evidencia_id = ident.get("evidencia_id")
                    ident["evidencia"] = None
                    if not evidencia_id:
                        continue
                    info = _EVIDENCIAS.get(evidencia_id)
                    if not info:
                        raise FillEngineError(
                            f"No se encontró el documento de identidad subido en el Tab {tg.get('letra', '?')} "
                            "— si reiniciaste el servidor después de subirlo, vuelve a subirlo e intenta de nuevo."
                        )
                    n = info["num_paginas"]
                    inicio = pagina
                    if inicio_tab is None:
                        inicio_tab = inicio
                    ident["evidencia"] = {"pagina_inicio": inicio, "num_paginas": n, "path": info["path"]}
                    pagina += n
                continue
            if categoria == "supplemental_evidence":
                for doc in documentos_se:
                    evidencia_id = doc.get("evidencia_id")
                    doc["evidencia"] = None
                    if not evidencia_id:
                        continue
                    info = _EVIDENCIAS.get(evidencia_id)
                    if not info:
                        raise FillEngineError(
                            f"No se encontró un documento de Supplemental Evidence subido en el Tab "
                            f"{tg.get('letra', '?')} — si reiniciaste el servidor después de subirlo, "
                            "vuelve a subirlo e intenta de nuevo."
                        )
                    n = info["num_paginas"]
                    inicio = pagina
                    if inicio_tab is None:
                        inicio_tab = inicio
                    doc["evidencia"] = {"pagina_inicio": inicio, "num_paginas": n, "path": info["path"]}
                    pagina += n
                continue
            for item in ITEMS_POR_CATEGORIA.get(categoria, []):
                evidencia_id = evidencias_ids.get(item["key"])
                if not evidencia_id:
                    continue
                info = _EVIDENCIAS.get(evidencia_id)
                if not info:
                    raise FillEngineError(
                        f"No se encontró el archivo subido para '{item['label']}' en el Tab "
                        f"{tg.get('letra', '?')} — si reiniciaste el servidor después de subirlo, "
                        "vuelve a subirlo e intenta de nuevo."
                    )
                n = info["num_paginas"]
                inicio = pagina
                if inicio_tab is None:
                    inicio_tab = inicio
                resueltas[item["key"]] = {"pagina_inicio": inicio, "num_paginas": n, "path": info["path"]}
                pagina += n
        tg["evidencias"] = resueltas
        tg["identidades"] = identidades
        tg["documentos_se"] = documentos_se
        if inicio_tab is not None:
            fin_tab = pagina - 1
            tg["paginas"] = str(inicio_tab) if inicio_tab == fin_tab else f"{inicio_tab}-{fin_tab}"
    return pagina


@app.post("/api/generar")
def api_generar():
    body = request.get_json(force=True)
    case_id = body.get("case_id")
    document_instance = body.get("document_instance")
    separar_por_tab = body.get("separar_por_tab", True)
    generar_pdf = body.get("generar_pdf", False)
    pagina_inicial_lote = body.get("pagina_inicial_lote")
    if not case_id or not document_instance:
        return jsonify({"error": "Se requiere case_id y document_instance"}), 400

    case = load_case(case_id)
    if case is None:
        return jsonify({"error": "Caso no encontrado"}), 404

    exhibits = document_instance.get("exhibits") or []
    tiene_evidencia = any(
        tg.get("evidencias")
        or any(i.get("evidencia_id") for i in (tg.get("identidades") or []))
        or any(d.get("evidencia_id") for d in (tg.get("documentos_se") or []))
        for tg in exhibits
    )
    if tiene_evidencia:
        # insertar evidencia requiere un PDF de portada, y requiere que cada
        # Tab sea su propio archivo (no se puede "insertar después de la
        # divisoria de este Tab" dentro de un documento combinado con varios
        # Tabs adentro).
        generar_pdf = True
        separar_por_tab = True
        if not isinstance(pagina_inicial_lote, int) or pagina_inicial_lote < 1:
            pagina_inicial_lote = siguiente_pagina(case)
        try:
            nueva_siguiente = _resolver_paginas_evidencia(pagina_inicial_lote, exhibits)
        except FillEngineError as e:
            return jsonify({"error": str(e)}), 400
        case["siguiente_pagina"] = nueva_siguiente

    try:
        resultados = generar_lote(
            case,
            document_instance,
            plantillas_dir=PLANTILLAS_DIR,
            output_dir=OUTPUT_DIR,
            separar_por_tab=separar_por_tab,
            verificar_pdf=generar_pdf,
        )
    except (FillEngineError, ValidationError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": f"Error inesperado generando el documento: {e}"}), 500

    if exhibits:
        case["ultimo_tab_letra"] = exhibits[-1]["letra"]
        save_case(case)

    # resultados[i] corresponde a exhibits[i] cuando separar_por_tab generó
    # un archivo por Tab (que es obligatorio si hay evidencia, ver arriba).
    tabs_por_resultado = exhibits if (separar_por_tab and len(resultados) == len(exhibits)) else [None] * len(resultados)

    documentos = []
    for result, tab_group in zip(resultados, tabs_por_resultado):
        preview_urls = [f"/output/_preview/{result.docx_path.stem}/{p.name}" for p in result.preview_images]
        entry = {
            "docx_url": f"/output/{result.docx_path.name}",
            "pdf_url": f"/output/{result.pdf_path.name}" if result.pdf_path else None,
            "preview_urls": preview_urls,
            "validation_ok": result.validation_ok,
            "validation_errors": result.validation_errors,
            "pdf_generado": result.pdf_path is not None,
            "evidencia_fusionada": False,
        }

        evidencias_resueltas = (tab_group or {}).get("evidencias") or {}
        identidades_resueltas = (tab_group or {}).get("identidades") or []
        documentos_se_resueltos = (tab_group or {}).get("documentos_se") or []
        docs_con_pagina = [(info["pagina_inicio"], info["path"]) for info in evidencias_resueltas.values()]
        docs_con_pagina += [
            (i["evidencia"]["pagina_inicio"], i["evidencia"]["path"]) for i in identidades_resueltas if i.get("evidencia")
        ]
        docs_con_pagina += [
            (d["evidencia"]["pagina_inicio"], d["evidencia"]["path"]) for d in documentos_se_resueltos if d.get("evidencia")
        ]
        if docs_con_pagina and result.pdf_path:
            docs_con_pagina.sort(key=lambda x: x[0])
            rutas = [ruta for _, ruta in docs_con_pagina]
            pagina_inicial_tab = docs_con_pagina[0][0]
            try:
                _out, _ultima, punto_encontrado = combinar_portada_y_evidencia(
                    result.pdf_path, rutas, pagina_inicial_tab, result.pdf_path
                )
                entry["evidencia_fusionada"] = True
                if not punto_encontrado:
                    entry["evidencia_error"] = (
                        "No se encontró la página 'PROOF OF SERVICE' en el PDF generado — la evidencia "
                        "quedó insertada al final del documento en vez de después de la divisoria. "
                        "Revísalo antes de usarlo."
                    )
            except PdfMergeError as e:
                entry["evidencia_error"] = str(e)

        documentos.append(entry)

    return jsonify({"documentos": documentos, "siguiente_pagina": case.get("siguiente_pagina", 1)})


@app.get("/output/<path:filename>")
def descargar_output(filename: str):
    target = (OUTPUT_DIR / filename).resolve()
    if not target.is_relative_to(OUTPUT_DIR.resolve()) or not target.is_file():
        return jsonify({"error": "Archivo no encontrado"}), 404
    return send_file(target)


if __name__ == "__main__":
    import webbrowser
    from threading import Timer

    Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
