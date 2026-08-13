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
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from motor.case_store import CASE_STORE_DIR, list_cases, load_case, next_tab_letra, save_case
from motor.fill_engine import FillEngineError, generar_lote
from motor.validate import ValidationError

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
INPUT_DIR = BASE_DIR / "input"
PLANTILLAS_DIR = BASE_DIR / "plantillas"

INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
CASE_STORE_DIR.mkdir(exist_ok=True)

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


@app.get("/api/init")
def api_init():
    return jsonify(
        {
            "catalogos": _catalogos(),
            "plantillas": _registro_plantillas()["plantillas"],
            "casos": list_cases(),
            "salidas": _list_salidas(),
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


@app.post("/api/generar")
def api_generar():
    body = request.get_json(force=True)
    case_id = body.get("case_id")
    document_instance = body.get("document_instance")
    separar_por_tab = body.get("separar_por_tab", True)
    if not case_id or not document_instance:
        return jsonify({"error": "Se requiere case_id y document_instance"}), 400

    case = load_case(case_id)
    if case is None:
        return jsonify({"error": "Caso no encontrado"}), 404

    try:
        resultados = generar_lote(
            case,
            document_instance,
            plantillas_dir=PLANTILLAS_DIR,
            output_dir=OUTPUT_DIR,
            separar_por_tab=separar_por_tab,
        )
    except (FillEngineError, ValidationError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": f"Error inesperado generando el documento: {e}"}), 500

    exhibits = document_instance.get("exhibits") or []
    if exhibits:
        case["ultimo_tab_letra"] = exhibits[-1]["letra"]
        save_case(case)

    documentos = []
    for result in resultados:
        preview_urls = [f"/output/_preview/{result.docx_path.stem}/{p.name}" for p in result.preview_images]
        documentos.append(
            {
                "docx_url": f"/output/{result.docx_path.name}",
                "pdf_url": f"/output/{result.pdf_path.name}" if result.pdf_path else None,
                "preview_urls": preview_urls,
                "validation_ok": result.validation_ok,
                "validation_errors": result.validation_errors,
                "pdf_generado": result.pdf_path is not None,
            }
        )

    return jsonify({"documentos": documentos})


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
