"""Servidor local (Flask) que expone el sistema de llenado de Tabs EOIR a
través de una interfaz HTML con botones interactivos.

Uso:
    python app.py
    (abre http://127.0.0.1:5000 en el navegador)
"""

from __future__ import annotations

import json
import os
import re
import secrets
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_file, send_from_directory, session

from werkzeug.utils import secure_filename

from motor import auth
from motor.case_store import CASE_STORE_DIR, list_cases, load_case, next_tab_letra, save_case, siguiente_pagina
from motor.exhibit_builder import (
    CATEGORY_ORDER,
    ITEMS_POR_CATEGORIA,
    TIPOS_DOCUMENTO_IDENTIDAD,
    TIPOS_DOCUMENTO_PERSONA_SE,
    TIPOS_SUPPLEMENTAL_EVIDENCE,
)
from motor.fill_engine import FillEngineError, generar_lote
from motor.pdf_merge import (
    PdfMergeError,
    combinar_portada_y_evidencia,
    combinar_portada_y_evidencia_exhibits,
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

# SECRET_KEY firma la cookie de sesión del login — en producción (Docker) se
# fija por variable de entorno (ver docker-compose.yml) para que la sesión
# sobreviva a un redeploy del contenedor; en uso local (`python app.py`)
# genera una al vuelo, total no hay usuarios reales fuera de localhost.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# El login solo tiene sentido cuando la app queda expuesta a internet (varios
# usuarios, reverse proxy). En uso local en una sola máquina del despacho
# (`python app.py` vía iniciar.bat) es fricción innecesaria y dejaría al
# usuario trabado en la pantalla de login sin ningún usuario creado. Por eso
# está APAGADO por defecto: solo se activa cuando corre en la nube, donde
# docker-compose.yml setea EOIR_LOGIN=1. Con el login apagado, todas las
# rutas quedan accesibles sin sesión, igual que antes de agregar el login.
LOGIN_HABILITADO = os.environ.get("EOIR_LOGIN", "").strip() == "1"

# Rutas accesibles SIN login — la propia pantalla de login (+ su endpoint de
# API), assets estáticos, y el health check que usa el reverse proxy/orquestador.
_RUTAS_PUBLICAS = {"login", "api_login", "static", "healthz"}


@app.before_request
def _exigir_login():
    if not LOGIN_HABILITADO:
        return None
    if request.endpoint is None:
        return None
    if request.endpoint in _RUTAS_PUBLICAS or request.endpoint.startswith("static"):
        return None
    if session.get("usuario"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "No autenticado"}), 401
    return redirect("/login")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.get("/login")
def login():
    if not LOGIN_HABILITADO or session.get("usuario"):
        return redirect("/")
    return send_from_directory(BASE_DIR / "static", "login.html")


@app.post("/api/login")
def api_login():
    body = request.get_json(force=True, silent=True) or {}
    usuario = str(body.get("usuario", "")).strip()
    password = str(body.get("password", ""))
    info = auth.verify_login(usuario, password)
    if info is None:
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
    session.clear()
    session["usuario"] = info["usuario"]
    session["nombre"] = info["nombre"]
    session.permanent = True
    return jsonify({"usuario": info["usuario"], "nombre": info["nombre"]})


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


def _catalogos() -> dict:
    return json.loads((BASE_DIR / "catalogos.json").read_text(encoding="utf-8"))


def _con_evidencia_exhibits(entry: dict) -> dict:
    """Adjunta `evidencia_exhibits` (letra + descripción de cada Exhibit
    que acepta un PDF subido, ej. Motion to Withdraw) leyéndolo del
    field_map.json de la plantilla — vive ahí como única fuente de verdad
    en vez de duplicarse en registro.json."""
    field_map_rel = entry.get("field_map")
    if not field_map_rel:
        return entry
    field_map_path = PLANTILLAS_DIR / field_map_rel
    if not field_map_path.exists():
        return entry
    field_map = json.loads(field_map_path.read_text(encoding="utf-8"))
    if field_map.get("evidencia_exhibits"):
        entry = {**entry, "evidencia_exhibits": field_map["evidencia_exhibits"]}
    return entry


def _registro_plantillas() -> dict:
    registro = json.loads((PLANTILLAS_DIR / "registro.json").read_text(encoding="utf-8"))
    plantillas = []
    for entry in registro["plantillas"]:
        if "variantes" in entry:
            entry = {**entry, "variantes": [_con_evidencia_exhibits(v) for v in entry["variantes"]]}
        else:
            entry = _con_evidencia_exhibits(entry)
        plantillas.append(entry)
    registro["plantillas"] = plantillas
    return registro


def _list_salidas() -> list[dict]:
    salidas = []
    pdfs_con_docx = set()
    for docx_path in OUTPUT_DIR.glob("*.docx"):
        pdf_path = docx_path.with_suffix(".pdf")
        pdfs_con_docx.add(pdf_path.name)
        preview_dir = OUTPUT_DIR / "_preview" / docx_path.stem
        previews = sorted(p.name for p in preview_dir.glob("*.jpg")) if preview_dir.exists() else []
        salidas.append(
            {
                "docx": docx_path.name,
                "pdf": pdf_path.name if pdf_path.exists() else None,
                "previews": previews,
                "preview_dir": docx_path.stem,
                "mtime": docx_path.stat().st_mtime,
            }
        )
    # plantillas tipo "pdf_form" (ej. EOIR-33) no generan .docx — su PDF es
    # el archivo principal, no un derivado de verificación.
    for pdf_path in OUTPUT_DIR.glob("*.pdf"):
        if pdf_path.name in pdfs_con_docx:
            continue
        preview_dir = OUTPUT_DIR / "_preview" / pdf_path.stem
        previews = sorted(p.name for p in preview_dir.glob("*.jpg")) if preview_dir.exists() else []
        salidas.append(
            {
                "docx": None,
                "pdf": pdf_path.name,
                "previews": previews,
                "preview_dir": pdf_path.stem,
                "mtime": pdf_path.stat().st_mtime,
            }
        )
    salidas.sort(key=lambda s: s["mtime"], reverse=True)
    for s in salidas:
        del s["mtime"]
    return salidas


@app.get("/")
def index():
    return send_from_directory(BASE_DIR / "static", "index.html")


@app.get("/como-funciona")
def como_funciona():
    return send_from_directory(BASE_DIR / "static", "como-funciona.html")


@app.get("/api/init")
def api_init():
    usuario = (
        {"usuario": session.get("usuario"), "nombre": session.get("nombre")}
        if LOGIN_HABILITADO
        else None
    )
    return jsonify(
        {
            "login_habilitado": LOGIN_HABILITADO,
            "usuario": usuario,
            "catalogos": _catalogos(),
            "plantillas": _registro_plantillas()["plantillas"],
            "casos": list_cases(),
            "salidas": _list_salidas(),
            "items_por_categoria": ITEMS_POR_CATEGORIA,
            "tipos_documento_identidad": TIPOS_DOCUMENTO_IDENTIDAD,
            "tipos_supplemental_evidence": TIPOS_SUPPLEMENTAL_EVIDENCE,
            "tipos_documento_persona_se": TIPOS_DOCUMENTO_PERSONA_SE,
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
    case = request.get_json(force=True, silent=True)
    if not isinstance(case, dict):
        return jsonify({"error": "El cuerpo de la petición no es JSON válido"}), 400
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


def _ruta_evidencia(evidencia_id: str) -> Path:
    info = _EVIDENCIAS.get(evidencia_id)
    if not info:
        raise FillEngineError(
            "No se encontró uno de los PDFs de evidencia subidos — si reiniciaste el servidor después de "
            "subirlo, vuelve a subirlo e intenta de nuevo."
        )
    return info["path"]


def _resolver_paginas_evidencia(pagina_inicial_lote: int, exhibits: list[dict]) -> int:
    """Para cada Tab con documentos de evidencia adjuntos, calcula la
    página de inicio de cada documento en orden (categoría, luego ítem/
    persona dentro de la categoría), continuando desde
    `pagina_inicial_lote`. Sobrescribe tg['paginas'] con el rango
    calculado, tg['evidencias'] con la info resuelta de los ítems de
    catálogo fijo (ver motor.exhibit_builder.ITEMS_POR_CATEGORIA), y cada
    identidad de tg['identidades'] con su propia 'evidencia' resuelta
    (Form of Identity tiene un documento por persona, no un catálogo fijo).
    Igual para cada entrada de tg['biometricos'] (Biometrics Compliance
    también es un documento por persona, dentro de la categoría "fee") y
    de tg['declaraciones'] (Declaration también es un documento por
    persona, dentro de la categoría "supplemental_evidence").
    Devuelve la próxima página disponible después de este lote."""
    pagina = pagina_inicial_lote
    for tg in exhibits:
        evidencias_ids = tg.get("evidencias") or {}
        identidades = tg.get("identidades") or []
        documentos_se = tg.get("documentos_se") or []
        biometricos = tg.get("biometricos") or []
        declaraciones = tg.get("declaraciones") or []
        tiene_algo = (
            bool(evidencias_ids)
            or any(i.get("evidencia_id") for i in identidades)
            or any(d.get("evidencia_id") for d in documentos_se)
            or any(b.get("evidencia_id") for b in biometricos)
            or any(d.get("evidencia_id") for d in declaraciones)
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
                for decl in declaraciones:
                    evidencia_id = decl.get("evidencia_id")
                    decl["evidencia"] = None
                    if not evidencia_id:
                        continue
                    info = _EVIDENCIAS.get(evidencia_id)
                    if not info:
                        raise FillEngineError(
                            f"No se encontró el documento de Declaration subido en el Tab "
                            f"{tg.get('letra', '?')} — si reiniciaste el servidor después de subirlo, "
                            "vuelve a subirlo e intenta de nuevo."
                        )
                    n = info["num_paginas"]
                    inicio = pagina
                    if inicio_tab is None:
                        inicio_tab = inicio
                    decl["evidencia"] = {"pagina_inicio": inicio, "num_paginas": n, "path": info["path"]}
                    pagina += n
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
            if categoria == "fee":
                for bio in biometricos:
                    evidencia_id = bio.get("evidencia_id")
                    bio["evidencia"] = None
                    if not evidencia_id:
                        continue
                    info = _EVIDENCIAS.get(evidencia_id)
                    if not info:
                        raise FillEngineError(
                            f"No se encontró el documento de Biometrics Compliance subido en el Tab "
                            f"{tg.get('letra', '?')} — si reiniciaste el servidor después de subirlo, "
                            "vuelve a subirlo e intenta de nuevo."
                        )
                    n = info["num_paginas"]
                    inicio = pagina
                    if inicio_tab is None:
                        inicio_tab = inicio
                    bio["evidencia"] = {"pagina_inicio": inicio, "num_paginas": n, "path": info["path"]}
                    pagina += n
        tg["evidencias"] = resueltas
        tg["identidades"] = identidades
        tg["documentos_se"] = documentos_se
        tg["biometricos"] = biometricos
        tg["declaraciones"] = declaraciones
        if inicio_tab is not None:
            fin_tab = pagina - 1
            tg["paginas"] = str(inicio_tab) if inicio_tab == fin_tab else f"{inicio_tab}-{fin_tab}"
    return pagina


def _es_plantilla_pdf_form(template_id: str | None) -> bool:
    """Las plantillas .docx se llenan manipulando content controls OOXML
    (motor.fill_engine); EOIR-33 es un PDF oficial con campos de formulario
    reales (AcroForm) y sigue un camino de generación distinto — ver
    motor.pdf_form_fill."""
    if not template_id:
        return False
    field_map_path = PLANTILLAS_DIR / template_id / "field_map.json"
    if not field_map_path.exists():
        return False
    return json.loads(field_map_path.read_text(encoding="utf-8")).get("tipo") == "pdf_form"


@app.post("/api/generar")
def api_generar():
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "El cuerpo de la petición no es JSON válido"}), 400
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

    if _es_plantilla_pdf_form(document_instance.get("template_id")):
        from motor.pdf_form_fill import PdfFormFillError, generar_pdf_formulario

        try:
            resultado = generar_pdf_formulario(case, document_instance, PLANTILLAS_DIR, OUTPUT_DIR)
        except PdfFormFillError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return jsonify({"error": f"Error inesperado generando el documento: {e}"}), 500

        documento = {
            "docx_url": None,
            "pdf_url": f"/output/{resultado.pdf_path.name}",
            "preview_urls": [f"/output/_preview/{resultado.pdf_path.stem}/{p.name}" for p in resultado.preview_images],
            "validation_ok": resultado.validation_ok,
            "validation_errors": resultado.validation_errors,
            "pdf_generado": True,
            "evidencia_fusionada": False,
        }
        auth.registrar_auditoria(
            session.get("usuario", "?"),
            "generar_documento",
            {"case_id": case_id, "template_id": document_instance.get("template_id"), "archivos": [documento["pdf_url"]]},
        )
        return jsonify({"documentos": [documento], "siguiente_pagina": case.get("siguiente_pagina", 1)})

    exhibits = document_instance.get("exhibits") or []
    tiene_evidencia = any(
        tg.get("evidencias")
        or any(i.get("evidencia_id") for i in (tg.get("identidades") or []))
        or any(d.get("evidencia_id") for d in (tg.get("documentos_se") or []))
        or any(b.get("evidencia_id") for b in (tg.get("biometricos") or []))
        or any(d.get("evidencia_id") for d in (tg.get("declaraciones") or []))
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

    # Motion to Withdraw (y cualquier plantilla sin tabla de exhibits): un
    # PDF de evidencia por Exhibit con nombre (letra), en vez de los Tabs
    # dinámicos de arriba — ver _resolver_exhibits_evidencia.
    exhibits_evidencia_ids = document_instance.get("exhibits_evidencia") or {}
    exhibits_evidencia_ids = {letra: ids for letra, ids in exhibits_evidencia_ids.items() if ids}
    if exhibits_evidencia_ids:
        generar_pdf = True
        try:
            exhibits_evidencia_rutas = {
                letra: [_ruta_evidencia(eid) for eid in ids] for letra, ids in exhibits_evidencia_ids.items()
            }
        except FillEngineError as e:
            return jsonify({"error": str(e)}), 400

    try:
        resultados = generar_lote(
            case,
            document_instance,
            plantillas_dir=PLANTILLAS_DIR,
            output_dir=OUTPUT_DIR,
            separar_por_tab=separar_por_tab,
            verificar_pdf=generar_pdf,
        )
    except (FillEngineError, ValidationError, ValueError) as e:
        # ValueError lo lanza motor.exhibit_builder cuando falta un dato
        # requerido de la tabla de exhibits (país, año de Country Reports/
        # OSAC, fecha de Biometrics Compliance) — es un error de datos del
        # usuario, no un fallo interno, así que se devuelve como 400 con su
        # mensaje en vez de un 500 opaco.
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
        biometricos_resueltos = (tab_group or {}).get("biometricos") or []
        declaraciones_resueltas = (tab_group or {}).get("declaraciones") or []
        docs_con_pagina = [(info["pagina_inicio"], info["path"]) for info in evidencias_resueltas.values()]
        docs_con_pagina += [
            (i["evidencia"]["pagina_inicio"], i["evidencia"]["path"]) for i in identidades_resueltas if i.get("evidencia")
        ]
        docs_con_pagina += [
            (d["evidencia"]["pagina_inicio"], d["evidencia"]["path"]) for d in documentos_se_resueltos if d.get("evidencia")
        ]
        docs_con_pagina += [
            (b["evidencia"]["pagina_inicio"], b["evidencia"]["path"]) for b in biometricos_resueltos if b.get("evidencia")
        ]
        docs_con_pagina += [
            (d["evidencia"]["pagina_inicio"], d["evidencia"]["path"]) for d in declaraciones_resueltas if d.get("evidencia")
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

        if exhibits_evidencia_ids and result.pdf_path:
            pagina_inicial_exhibits = document_instance.get("pagina_inicial_exhibits")
            if not isinstance(pagina_inicial_exhibits, int) or pagina_inicial_exhibits < 1:
                pagina_inicial_exhibits = 1
            try:
                _out, _ultima, no_encontradas = combinar_portada_y_evidencia_exhibits(
                    result.pdf_path, exhibits_evidencia_rutas, pagina_inicial_exhibits, result.pdf_path,
                    numerar=False,
                )
                entry["evidencia_fusionada"] = True
                if no_encontradas:
                    entry["evidencia_error"] = (
                        "No se encontró la página divisoria de estos Exhibits en el PDF generado, así que su "
                        f"evidencia no se pudo insertar: {', '.join(no_encontradas)}. Revísalo antes de usarlo."
                    )
            except PdfMergeError as e:
                entry["evidencia_error"] = str(e)

        documentos.append(entry)

    auth.registrar_auditoria(
        session.get("usuario", "?"),
        "generar_documento",
        {
            "case_id": case_id,
            "template_id": document_instance.get("template_id"),
            "archivos": [d["docx_url"] or d["pdf_url"] for d in documentos],
        },
    )
    return jsonify({"documentos": documentos, "siguiente_pagina": case.get("siguiente_pagina", 1)})


@app.get("/output/<path:filename>")
def descargar_output(filename: str):
    target = (OUTPUT_DIR / filename).resolve()
    if not target.is_relative_to(OUTPUT_DIR.resolve()) or not target.is_file():
        return jsonify({"error": "Archivo no encontrado"}), 404
    return send_file(target)


def _limpiar_evidencia_huerfana() -> None:
    """Borra los PDFs de evidencia subidos en sesiones ANTERIORES del
    servidor. Al arrancar un proceso nuevo, el índice en memoria
    `_EVIDENCIAS` está vacío, así que cualquier archivo que haya quedado en
    EVIDENCIA_DIR de una corrida previa ya es inalcanzable (no hay id que lo
    referencie) y solo ocupa disco — se acumulaban sin límite. NO toca los
    entregables de `output/` (esos son los .docx/.pdf finales que el usuario
    puede no haber descargado todavía)."""
    if not EVIDENCIA_DIR.exists():
        return
    for f in EVIDENCIA_DIR.glob("*"):
        if f.is_file():
            try:
                f.unlink()
            except OSError:
                pass


# Corre siempre al cargar el módulo (no solo bajo `python app.py`) para que
# también se ejecute cuando gunicorn importa `app:app` en producción — un
# proceso de gunicorn se reinicia en cada redeploy igual que uno local, y
# sin esto la evidencia huérfana nunca se limpiaría en el servidor.
_limpiar_evidencia_huerfana()

if __name__ == "__main__":
    import webbrowser
    from threading import Timer

    Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
