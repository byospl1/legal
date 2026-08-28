"""Suite de tests de invariantes del sistema — SIN dependencias extra
(no usa pytest, se corre con `python3 tests/run_tests.py` en la misma
máquina del despacho, que solo tiene lo de requirements.txt).

Cubre justo la clase de bug que ya se repitió varias veces (ver el checklist
de CLAUDE.md):

1. Alineación columna a columna DESCRIPTION ↔ PAGES en la tabla de exhibits:
   en "modo evidencia" ambas columnas deben emitir EXACTAMENTE el mismo
   número de párrafos (Word alinea las celdas de una fila por altura, así
   que un desajuste de conteo desalinea los "Pgs. X-Y").
2. Biometrics Compliance: subtítulo repetido por persona + encadenado de
   páginas.
3. case_store.next_tab_letra: incremento base-26 más allá de la Z.
4. pdf_merge: rango de años de la sugerencia.

Cada test es una función `test_*`; el runner de abajo las corre todas,
reporta OK/FAIL y sale con código != 0 si alguna falla (usable en un
pre-commit o a mano)."""

from __future__ import annotations

import re
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor import exhibit_builder as eb
from motor.case_store import load_case, next_tab_letra, save_case
from motor.fill_engine import _tipo_tab_label, generar_documento
from motor.pdf_form_fill import generar_pdf_formulario
from motor.pdf_merge import (
    _A4_HEIGHT,
    _A4_WIDTH,
    _ANIO_RE,
    _normalizar_pagina_a4,
    combinar_portada_y_evidencia,
    combinar_portada_y_evidencia_exhibits,
)

SUBTITLE_BIOMETRICS = "Biometrics Compliance."


def _contar_parrafos(xml: str) -> int:
    """Número de <w:p> en un fragmento de celda (abren como '<w:p ' o '<w:p>')."""
    return len(re.findall(r"<w:p[ >]", xml))


def _ev(inicio: int, n: int) -> dict:
    return {"pagina_inicio": inicio, "num_paginas": n, "path": f"/fake/{inicio}.pdf"}


def _partir_parrafos_con_texto(xml: str) -> list[str]:
    """Lista de textos (uno por <w:p>, "" si el párrafo no tiene <w:t> con
    contenido — spacer/blank) en el orden en que aparecen."""
    parrafos = re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.DOTALL)
    out = []
    for p in parrafos:
        m = re.search(r"<w:t[^>]*>(.*?)</w:t>", p, flags=re.DOTALL)
        out.append(m.group(1) if m else "")
    return out


def _lineas_inicio_por_parrafo(textos: list[str]) -> list[int]:
    """Línea visual (1-based) donde EMPIEZA cada párrafo, contando cuántas
    líneas visuales ocupa cada uno al envolver (_estimar_lineas_visuales;
    un párrafo vacío = 1 línea). Modela cómo Word acumula altura en una
    celda: el párrafo i empieza en 1 + sum(líneas de los párrafos previos)."""
    inicios = []
    linea = 1
    for t in textos:
        inicios.append(linea)
        linea += eb._estimar_lineas_visuales(t) if t else 1
    return inicios


def _assert_supplemental_alineado(tg: dict) -> None:
    """Verifica la invariante REAL de la tabla (Word alinea las celdas de una
    fila por altura acumulada, no por conteo de párrafos): cada "Pgs. X-Y" de
    la columna PAGES debe caer en la MISMA línea visual en la que EMPIEZA el
    renglón del documento al que pertenece en DESCRIPTION — nunca en una
    línea envuelta (2da+) de un documento anterior. Reemplaza al viejo chequeo
    de "igual número de párrafos", que solo valía cuando ningún renglón
    envolvía (ver el bug de la captura del Tab D, 2026-08-26)."""
    desc = eb.build_description_cell_content(
        tg["categorias"], tg.get("pais"), tg.get("anio_cc"), tg.get("anio_osac"),
        tg.get("plural", False), tg.get("evidencias"), tg.get("tipo_fee"),
        tg.get("biometricos"), tg.get("identidades"), tg.get("documentos_se"),
        tg.get("declaraciones"),
    )
    pages = eb.build_pages_cell_content(
        tg["categorias"], tg.get("evidencias"), tg.get("paginas", "1-2"),
        tg.get("identidades"), tg.get("documentos_se"), tg.get("biometricos"),
        tg.get("declaraciones"), tg.get("plural", False),
    )
    desc_textos = _partir_parrafos_con_texto(desc)
    pages_textos = _partir_parrafos_con_texto(pages)
    # En PAGES cada párrafo (valor corto "Pgs." o blank) ocupa 1 línea visual,
    # así que el índice de párrafo == su línea visual (1-based).
    pgs_lineas = [k + 1 for k, t in enumerate(pages_textos) if t.startswith("Pgs.")]
    # Líneas donde EMPIEZA cada documento (párrafo) de DESCRIPTION.
    inicios_desc = set(_lineas_inicio_por_parrafo(desc_textos))
    for L in pgs_lineas:
        _assert(
            L in inicios_desc,
            f"un 'Pgs.' cae en la línea visual {L}, que no es el inicio de ningún "
            f"renglón de DESCRIPTION (cayó en una línea envuelta). "
            f"desc={desc_textos!r} pages={pages_textos!r}",
        )


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# 1. Invariante DESCRIPTION == PAGES (modo evidencia)
# ---------------------------------------------------------------------------

def _desc_pages(tg: dict) -> tuple[int, int]:
    desc = eb.build_description_cell_content(
        tg["categorias"], tg.get("pais"), tg.get("anio_cc"), tg.get("anio_osac"),
        tg.get("plural", False), tg.get("evidencias"), tg.get("tipo_fee"),
        tg.get("biometricos"), tg.get("identidades"), tg.get("documentos_se"),
        tg.get("declaraciones"),
    )
    pages = eb.build_pages_cell_content(
        tg["categorias"], tg.get("evidencias"), tg.get("paginas", "1-2"),
        tg.get("identidades"), tg.get("documentos_se"), tg.get("biometricos"),
        tg.get("declaraciones"),
    )
    return _contar_parrafos(desc), _contar_parrafos(pages)


def test_alineacion_fee_receipt_mas_biometricos():
    # fee_receipt con archivo, fbi SIN archivo (debe omitirse), biometrics de
    # 2 personas ambas con archivo.
    tg = {
        "categorias": ["fee"],
        "evidencias": {"fee_receipt": _ev(1, 2)},
        "biometricos": [
            {"persona_nombre": None, "fecha": "01/01/2020", "evidencia": _ev(3, 1)},
            {"persona_nombre": "Ana Rider", "fecha": "01/02/2020", "evidencia": _ev(4, 1)},
        ],
    }
    d, p = _desc_pages(tg)
    _assert(d == p, f"fee+biometrics: DESCRIPTION={d} != PAGES={p}")


def test_alineacion_biometricos_solo():
    # SOLO evidencia en biometrics (nada en fee_receipt/fbi) — el caso que
    # rompió en producción: fee_receipt/fbi NO deben aparecer.
    tg = {
        "categorias": ["fee"],
        "evidencias": {},
        "biometricos": [
            {"persona_nombre": None, "fecha": "01/01/2020", "evidencia": _ev(51, 2)},
            {"persona_nombre": "Ana", "fecha": "01/02/2020", "evidencia": _ev(53, 2)},
        ],
    }
    d, p = _desc_pages(tg)
    _assert(d == p, f"biometrics-solo: DESCRIPTION={d} != PAGES={p}")
    desc = eb.build_description_cell_content(["fee"], None, evidencias={}, biometricos=tg["biometricos"])
    _assert("Fee Receipt" not in desc, "Fee Receipt no debía aparecer sin archivo")
    _assert("FBI" not in desc, "FBI Fingerprint no debía aparecer sin archivo")


def test_alineacion_country_conditions_uno_solo():
    # solo Country Reports con evidencia — OSAC se descarta, solo se pide anio_cc.
    tg = {
        "categorias": ["country_conditions"],
        "pais": "Mexico",
        "anio_cc": "2024",
        "anio_osac": None,
        "evidencias": {"country_reports": _ev(1, 3)},
    }
    d, p = _desc_pages(tg)
    _assert(d == p, f"country_conditions parcial: DESCRIPTION={d} != PAGES={p}")


def test_alineacion_form_of_identity():
    tg = {
        "categorias": ["form_of_identity"],
        "pais": "Mexico",
        "identidades": [
            {"persona_nombre": None, "tipo_doc": "Passport", "evidencia": _ev(1, 1)},
            {"persona_nombre": "Ana", "tipo_doc": "ID", "evidencia": _ev(2, 1)},
        ],
    }
    d, p = _desc_pages(tg)
    _assert(d == p, f"form_of_identity: DESCRIPTION={d} != PAGES={p}")


def test_alineacion_supplemental_evidence():
    tg = {
        "categorias": ["supplemental_evidence"],
        "declaraciones": [{"persona_nombre": None, "evidencia": _ev(1, 3)}],
        "documentos_se": [
            {"tipo": "News", "titulo": "algo", "evidencia": None},
            {"tipo": "Psychological Report", "titulo": None, "evidencia": _ev(4, 2)},
        ],
    }
    _assert_supplemental_alineado(tg)


def test_declaraciones_por_rider():
    # líder + 2 riders, todos con su propia declaración adjunta -> los 3
    # deben quedar incluidos, con texto distinto para cada uno, y cada "Pgs."
    # alineado con la primera línea del renglón de su documento.
    tg = {
        "categorias": ["supplemental_evidence"],
        "declaraciones": [
            {"persona_nombre": None, "evidencia": _ev(1, 2)},
            {"persona_nombre": "Rider Uno", "evidencia": _ev(3, 2)},
            {"persona_nombre": "Rider Dos", "evidencia": _ev(5, 2)},
        ],
        "documentos_se": [],
    }
    _assert_supplemental_alineado(tg)
    desc = eb.build_description_cell_content(
        tg["categorias"], None, documentos_se=[], declaraciones=tg["declaraciones"]
    )
    # DESCRIPTION: 1 párrafo por documento, sin separadores.
    _assert(len(_partir_parrafos_con_texto(desc)) == 3, "se esperaban 3 párrafos en DESCRIPTION (1 por declaración)")
    _assert("Rider’s Rider Uno Declaration" in desc, "falta la declaración de Rider Uno")
    _assert("Rider’s Rider Dos Declaration" in desc, "falta la declaración de Rider Dos")
    _assert("Respondent’s Declaration" in desc, "falta la declaración del líder")


def test_declaraciones_omite_sin_evidencia():
    # modo evidencia (Psychological Report con archivo) + un rider SIN su
    # propia declaración adjunta -> ese rider se omite, sin error.
    tg = {
        "categorias": ["supplemental_evidence"],
        "declaraciones": [
            {"persona_nombre": None, "evidencia": _ev(1, 2)},
            {"persona_nombre": "Rider Uno", "evidencia": None},
        ],
        "documentos_se": [{"tipo": "Psychological Report", "titulo": None, "evidencia": _ev(3, 1)}],
    }
    _assert_supplemental_alineado(tg)
    desc = eb.build_description_cell_content(
        tg["categorias"], None, documentos_se=tg["documentos_se"], declaraciones=tg["declaraciones"]
    )
    _assert("Rider Uno" not in desc, "Rider Uno no debía aparecer sin su propia evidencia")
    _assert("Respondent’s Declaration" in desc, "la declaración del líder sí debía incluirse")


def test_declaraciones_modo_manual():
    # nada subido en ninguna parte de supplemental_evidence -> se incluyen
    # las declaraciones de TODAS las personas del caso (líder + riders).
    tg = {
        "categorias": ["supplemental_evidence"],
        "declaraciones": [
            {"persona_nombre": None, "evidencia": None},
            {"persona_nombre": "Rider Uno", "evidencia": None},
        ],
        "documentos_se": [],
    }
    desc = eb.build_description_cell_content(
        tg["categorias"], None, documentos_se=[], declaraciones=tg["declaraciones"]
    )
    _assert("Respondent’s Declaration" in desc, "modo manual: falta la declaración del líder")
    _assert("Rider’s Rider Uno Declaration" in desc, "modo manual: falta la declaración de Rider Uno")


def test_declaraciones_multi_tipo_por_persona():
    # una persona puede subir más de un documento, cada uno con su propio
    # tipo (Declaration / Psychological Report / News) -> mismo patrón que
    # Form of Identity (identidades), ahora aplicado a Supplemental Evidence.
    tg = {
        "categorias": ["supplemental_evidence"],
        "declaraciones": [
            {"persona_nombre": None, "tipo": "Declaration", "evidencia": _ev(1, 1)},
            {"persona_nombre": "Rider Uno", "tipo": "Psychological Report", "evidencia": _ev(2, 1)},
            {"persona_nombre": "Rider Uno", "tipo": "News", "titulo": "amenazas", "evidencia": _ev(3, 1)},
        ],
        "documentos_se": [],
    }
    _assert_supplemental_alineado(tg)
    desc = eb.build_description_cell_content(
        tg["categorias"], None, documentos_se=[], declaraciones=tg["declaraciones"]
    )
    _assert(len(_partir_parrafos_con_texto(desc)) == 3, "se esperaban 3 párrafos en DESCRIPTION (1 por documento)")
    _assert("Rider’s Rider Uno Psychological Report." in desc, "falta el Psychological Report de Rider Uno")
    _assert("Rider’s Rider Uno News about amenazas." in desc, "falta la News de Rider Uno")


def test_declaraciones_pgs_alineado_con_su_propio_parrafo():
    # Caso real reportado por el usuario (2026-08-26, captura Tab D): líder +
    # 1 rider, ambos con declaración adjunta. El texto del líder ("Respondent's
    # Declaration for Support of Asylum Withholding of Removal and Relief Under
    # CAT.") es fijo y envuelve a 2 líneas visuales; el del rider (nombre
    # largo) a 3. Word alinea las celdas por altura acumulada, así que:
    #   DESCRIPTION: [líder (líneas 1-2), rider (líneas 3-5)]  -> 2 párrafos
    #   PAGES:       [Pgs.46-52 (línea 1), blank (línea 2, compensa el wrap del
    #                 líder), Pgs.53-59 (línea 3), blank, blank]  -> 5 párrafos
    # Antes del fix (sin compensación), "Pgs. 53-59" caía en la línea visual 2,
    # que es la 2da línea envuelta del renglón del líder — no junto al rider.
    tg = {
        "categorias": ["supplemental_evidence"],
        "declaraciones": [
            {"persona_nombre": None, "evidencia": _ev(46, 7)},
            {"persona_nombre": "MORALES-ZUNIGA, YORLENY SARAHI", "evidencia": _ev(53, 7)},
        ],
        "documentos_se": [],
    }
    desc = eb.build_description_cell_content(
        tg["categorias"], None, documentos_se=[], declaraciones=tg["declaraciones"]
    )
    pages = eb.build_pages_cell_content(
        tg["categorias"], None, "1-2", documentos_se=[], declaraciones=tg["declaraciones"]
    )
    desc_textos = _partir_parrafos_con_texto(desc)
    pages_textos = _partir_parrafos_con_texto(pages)
    # DESCRIPTION: exactamente 2 párrafos (1 por documento, SIN línea en blanco
    # entre ellos — como pidió el usuario).
    _assert(len(desc_textos) == 2, f"DESCRIPTION debía tener 2 párrafos, tiene {len(desc_textos)}: {desc_textos!r}")
    _assert("Respondent" in desc_textos[0], f"párrafo 0 de DESCRIPTION debía ser el líder: {desc_textos[0]!r}")
    _assert("MORALES-ZUNIGA" in desc_textos[1], f"párrafo 1 de DESCRIPTION debía ser el rider: {desc_textos[1]!r}")
    # Confirmar que el estimador ve al líder como 2 líneas y al rider como 3
    # (si esto cambia, la aritmética de abajo hay que recalibrarla).
    _assert(eb._estimar_lineas_visuales(desc_textos[0]) == 2, "el renglón del líder debía estimarse en 2 líneas")
    _assert(eb._estimar_lineas_visuales(desc_textos[1]) == 3, "el renglón del rider debía estimarse en 3 líneas")
    # PAGES: valor del líder + 1 blank (wrap del líder) + valor del rider + 2
    # blanks (wrap del rider) = 5 párrafos.
    _assert(
        pages_textos == ["Pgs. 46-52", "", "Pgs. 53-59", "", ""],
        f"PAGES no quedó con la compensación esperada: {pages_textos!r}",
    )
    # Y la invariante general por línea visual.
    _assert_supplemental_alineado(tg)


def test_alineacion_multi_categoria():
    tg = {
        "categorias": ["country_conditions", "form_of_identity", "fee"],
        "pais": "Honduras",
        "anio_cc": "2023",
        "anio_osac": "2023",
        "evidencias": {"country_reports": _ev(1, 2), "osac": _ev(3, 2)},
        "identidades": [
            {"persona_nombre": None, "tipo_doc": "Passport", "evidencia": _ev(5, 1)},
        ],
        "biometricos": [
            {"persona_nombre": None, "fecha": "05/05/2022", "evidencia": _ev(6, 1)},
            {"persona_nombre": "Rider Uno", "fecha": "05/06/2022", "evidencia": _ev(7, 1)},
            {"persona_nombre": "Rider Dos", "fecha": "05/07/2022", "evidencia": None},
        ],
    }
    d, p = _desc_pages(tg)
    _assert(d == p, f"multi-categoria: DESCRIPTION={d} != PAGES={p}")


# ---------------------------------------------------------------------------
# 2. Biometrics: subtítulo repetido por persona
# ---------------------------------------------------------------------------

def test_biometrics_subtitulo_por_persona():
    for n in (1, 2, 3):
        bios = [
            {"persona_nombre": None if i == 0 else f"Rider {i}", "fecha": f"0{i+1}/01/2020", "evidencia": _ev(i + 1, 1)}
            for i in range(n)
        ]
        desc = eb.build_description_cell_content(["fee"], None, evidencias={}, biometricos=bios)
        reps = desc.count(f">{SUBTITLE_BIOMETRICS}<")
        _assert(reps == n, f"biometrics n={n}: subtítulo aparece {reps} veces, se esperaban {n}")


def test_biometrics_fecha_obligatoria():
    try:
        eb._build_biometrics_compliance_description([{"persona_nombre": None, "fecha": None}])
    except ValueError:
        return
    raise AssertionError("se esperaba ValueError cuando falta la fecha de un biometrico")


# ---------------------------------------------------------------------------
# 3. next_tab_letra base-26
# ---------------------------------------------------------------------------

def test_next_tab_letra():
    casos = [
        (None, "A"), ("", "A"), ("A", "B"), ("Y", "Z"), ("Z", "AA"),
        ("AA", "AB"), ("AZ", "BA"), ("AY", "AZ"), ("ZZ", "AAA"), ("z", "AA"),
        ("  m  ", "N"),
    ]
    for entrada, esperado in casos:
        got = next_tab_letra(entrada)
        _assert(got == esperado, f"next_tab_letra({entrada!r}) = {got!r}, se esperaba {esperado!r}")


def test_nombre_de_salida_agrega_categoria_del_tab():
    _assert(
        _tipo_tab_label({"exhibits": [{"letra": "A", "categorias": ["fee"]}]}) == "TabA_fee",
        "el nombre del Tab de fee no incluye su categoría",
    )
    _assert(
        _tipo_tab_label({"exhibits": [{"letra": "B", "categorias": ["fee", "form_of_identity"]}]})
        == "TabB_form_of_identity_fee",
        "las categorías del Tab no quedan en el orden estable esperado",
    )


# ---------------------------------------------------------------------------
# 4. Rango de años de la sugerencia
# ---------------------------------------------------------------------------

def test_sugerir_anio_rango():
    for anio in ("1998", "2024", "2039", "2045", "2099"):
        m = _ANIO_RE.search(f"Human Rights Report {anio} edition")
        _assert(m is not None and m.group(0) == anio, f"no reconoció el año {anio}")
    # 2100 queda fuera a propósito (no es un año de reporte plausible)
    _assert(_ANIO_RE.search("year 2100") is None, "2100 no debería reconocerse")


def _fake_firebase_urlopen(status_body=None, http_error_code=None, url_error=False):
    """Devuelve un reemplazo de urllib.request.urlopen que simula la respuesta
    de Firebase sin tocar internet."""
    import io
    import json as _json
    import urllib.error

    def _fake(req, timeout=None):  # noqa: ARG001
        if url_error:
            raise urllib.error.URLError("sin conexión simulada")
        if http_error_code is not None:
            raise urllib.error.HTTPError(
                "url", http_error_code, "err", {}, io.BytesIO(b"{}")
            )

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return _json.dumps(status_body or {}).encode("utf-8")

        return _Resp()

    return _fake


def test_firebase_login_ok():
    from motor import auth

    orig = auth.urllib.request.urlopen
    auth.urllib.request.urlopen = _fake_firebase_urlopen(
        status_body={"email": "juan@kostiv.com", "displayName": "Juan Perez"}
    )
    try:
        info = auth.verify_login_firebase("juan@kostiv.com", "clave", api_key="fake")
    finally:
        auth.urllib.request.urlopen = orig
    _assert(info == {"usuario": "juan@kostiv.com", "nombre": "Juan Perez"}, f"info inesperado: {info}")


def test_firebase_login_credenciales_malas():
    from motor import auth

    orig = auth.urllib.request.urlopen
    auth.urllib.request.urlopen = _fake_firebase_urlopen(http_error_code=400)
    try:
        info = auth.verify_login_firebase("x@y.com", "mala", api_key="fake")
    finally:
        auth.urllib.request.urlopen = orig
    _assert(info is None, "credenciales malas deben dar None (401), no dict")


def test_firebase_login_sin_internet_lanza_red():
    from motor import auth

    orig = auth.urllib.request.urlopen
    auth.urllib.request.urlopen = _fake_firebase_urlopen(url_error=True)
    lanzo = False
    try:
        auth.verify_login_firebase("x@y.com", "clave", api_key="fake")
    except auth.AuthRedError:
        lanzo = True
    finally:
        auth.urllib.request.urlopen = orig
    _assert(lanzo, "un fallo de red debe lanzar AuthRedError, no devolver None")


def test_device_binding_primera_vez_ata():
    from motor import auth

    og, oc = auth._firestore_get, auth._firestore_create_if_absent
    auth._firestore_get = lambda *a, **k: None  # no existe binding
    auth._firestore_create_if_absent = lambda *a, **k: True  # se creó
    try:
        estado = auth.verificar_o_atar_dispositivo("uid1", "tok", "DEV-1", project_id="proj")
    finally:
        auth._firestore_get, auth._firestore_create_if_absent = og, oc
    _assert(estado == "ok", f"primera vez debe atar y dar ok, dio {estado}")


def test_device_binding_misma_maquina():
    from motor import auth

    og = auth._firestore_get
    auth._firestore_get = lambda *a, **k: {"device_id": "DEV-1"}
    try:
        estado = auth.verificar_o_atar_dispositivo("uid1", "tok", "DEV-1", project_id="proj")
    finally:
        auth._firestore_get = og
    _assert(estado == "ok", f"misma máquina debe dar ok, dio {estado}")


def test_device_binding_otra_maquina():
    from motor import auth

    og = auth._firestore_get
    auth._firestore_get = lambda *a, **k: {"device_id": "DEV-2"}
    try:
        estado = auth.verificar_o_atar_dispositivo("uid1", "tok", "DEV-1", project_id="proj")
    finally:
        auth._firestore_get = og
    _assert(estado == "otro_dispositivo", f"otra máquina debe rechazar, dio {estado}")


def test_device_binding_carrera_pierde():
    from motor import auth

    og, oc = auth._firestore_get, auth._firestore_create_if_absent
    llamadas = {"n": 0}

    def get_racing(*a, **k):
        # 1ra lectura: no existe; 2da (tras perder la carrera): la ganó otra máquina
        llamadas["n"] += 1
        return None if llamadas["n"] == 1 else {"device_id": "DEV-2"}

    auth._firestore_get = get_racing
    auth._firestore_create_if_absent = lambda *a, **k: False  # perdió la carrera
    try:
        estado = auth.verificar_o_atar_dispositivo("uid1", "tok", "DEV-1", project_id="proj")
    finally:
        auth._firestore_get, auth._firestore_create_if_absent = og, oc
    _assert(estado == "otro_dispositivo", f"al perder la carrera debe rechazar, dio {estado}")


def test_device_binding_habilitado_segun_config():
    from motor import auth

    oa, op = auth.FIREBASE_API_KEY, auth.FIREBASE_PROJECT_ID
    try:
        auth.FIREBASE_API_KEY, auth.FIREBASE_PROJECT_ID = "k", ""
        _assert(auth.device_binding_habilitado() is False, "sin project id no debe estar el candado")
        auth.FIREBASE_API_KEY, auth.FIREBASE_PROJECT_ID = "k", "proj"
        _assert(auth.device_binding_habilitado() is True, "con api key + project id sí")
    finally:
        auth.FIREBASE_API_KEY, auth.FIREBASE_PROJECT_ID = oa, op


def test_firebase_habilitado_segun_api_key():
    from motor import auth

    orig = auth.FIREBASE_API_KEY
    try:
        auth.FIREBASE_API_KEY = ""
        _assert(auth.firebase_habilitado() is False, "sin API key debe estar deshabilitado")
        auth.FIREBASE_API_KEY = "AIzaSyFake"
        _assert(auth.firebase_habilitado() is True, "con API key debe estar habilitado")
    finally:
        auth.FIREBASE_API_KEY = orig
def test_evidencia_se_normaliza_a_a4_sin_recorte():
    """Toda evidencia pasa a A4 conservando proporción y orientación visual."""
    from pypdf._page import PageObject

    for width, height in ((612, 792), (792, 612), (400, 1000)):
        original = PageObject.create_blank_page(width=width, height=height)
        resultado = _normalizar_pagina_a4(original)
        _assert(abs(float(resultado.mediabox.width) - _A4_WIDTH) < 0.01, "el ancho no quedó en A4")
        _assert(abs(float(resultado.mediabox.height) - _A4_HEIGHT) < 0.01, "el alto no quedó en A4")


def test_todos_los_flujos_de_fusion_normalizan_evidencia_a_a4():
    """Tabs y exhibits con ancla deben convertir la evidencia a A4 también sin numerarla."""
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        evidencia = base / "evidencia-horizontal.pdf"
        c = canvas.Canvas(str(evidencia), pagesize=(792, 612))
        c.drawString(40, 40, "Evidence")
        c.save()

        portada = base / "portada.pdf"
        c = canvas.Canvas(str(portada))
        c.drawString(40, 700, "COVER")
        c.showPage()
        c.drawString(40, 700, "PROOF OF SERVICE")
        c.save()
        final_tabs = base / "tabs.pdf"
        combinar_portada_y_evidencia(portada, [evidencia], 1, final_tabs)
        pagina_tabs = PdfReader(str(final_tabs)).pages[1]

        portada_exhibits = base / "portada-exhibits.pdf"
        c = canvas.Canvas(str(portada_exhibits))
        c.drawString(40, 700, "EXHIBIT A")
        c.save()
        final_exhibits = base / "exhibits.pdf"
        combinar_portada_y_evidencia_exhibits(
            portada_exhibits, {"A": [evidencia]}, 1, final_exhibits, numerar=False
        )
        pagina_exhibits = PdfReader(str(final_exhibits)).pages[1]

        for pagina in (pagina_tabs, pagina_exhibits):
            _assert(abs(float(pagina.mediabox.width) - _A4_WIDTH) < 0.01, "evidencia no quedó en A4")
            _assert(abs(float(pagina.mediabox.height) - _A4_HEIGHT) < 0.01, "evidencia no quedó en A4")


# ---------------------------------------------------------------------------
# 5. Seguridad de almacenamiento y API
# ---------------------------------------------------------------------------

def _caso_base() -> dict:
    return {
        "id": "persona-prueba-123456789",
        "cliente_nombre": "PERSONA PRUEBA, NOMBRE",
        "a_number": "123-456-789",
        "corte_sede": "LOS ANGELES IMMIGRATION COURT",
        "juez": "APELLIDO COMPUESTO MUY LARGO, NOMBRE",
        "proxima_audiencia": "December 31, 2027 at 11:59 PM, Individual Hearing",
        "abogado": "John Negron, Esq. (SBN 21806)",
        "preparador": "Bruno Briz",
        "riders": [],
        "siguiente_pagina": 1,
    }


def test_case_store_bloquea_path_traversal_y_es_atomico():
    with tempfile.TemporaryDirectory() as temp:
        store = Path(temp) / "case_store"
        outside = Path(temp) / "catalogos.json"
        outside.write_text("intacto", encoding="utf-8")
        caso = _caso_base()
        save_case(caso, store)
        caso["siguiente_pagina"] = 9
        save_case(caso, store)
        _assert(load_case(caso["id"], store)["siguiente_pagina"] == 9, "no guardó la versión nueva")
        _assert((store / f"{caso['id']}.json.bak").exists(), "no creó el respaldo atómico")
        _assert(outside.read_text(encoding="utf-8") == "intacto", "se alteró un archivo fuera de case_store")
        try:
            save_case({**caso, "id": "../catalogos"}, store)
        except ValueError:
            pass
        else:
            raise AssertionError("se aceptó un identificador con path traversal")


def test_api_rechaza_solicitudes_externas_y_json_malformado():
    import app as app_module

    client = app_module.app.test_client()
    response = client.post("/api/casos", json={})
    _assert(response.status_code == 403, f"sin cabecera local devolvió {response.status_code}")
    response = client.post(
        "/api/generar",
        json={"case_id": "caso-valido", "document_instance": "no-es-objeto"},
        headers={"X-EOIR-Request": "1"},
    )
    _assert(response.status_code == 400, f"document_instance malformado devolvió {response.status_code}")


def test_login_y_logout_incluyen_proteccion_local():
    import app as app_module

    originales = app_module.auth.firebase_habilitado, app_module.auth.verify_login
    try:
        app_module.auth.firebase_habilitado = lambda: False
        app_module.auth.verify_login = lambda usuario, _password: {
            "usuario": usuario,
            "nombre": "Usuario de prueba",
        }
        client = app_module.app.test_client()
        response = client.post(
            "/api/login",
            json={"usuario": "prueba", "password": "clave"},
            headers={"X-EOIR-Request": "1"},
        )
        _assert(response.status_code == 200, f"login protegido devolvió {response.status_code}")
        response = client.post("/api/logout", headers={"X-EOIR-Request": "1"})
        _assert(response.status_code == 200, f"logout protegido devolvió {response.status_code}")
    finally:
        app_module.auth.firebase_habilitado, app_module.auth.verify_login = originales


def test_login_firebase_aplica_actualizacion_obligatoria():
    import app as app_module

    original = {
        "firebase_habilitado": app_module.auth.firebase_habilitado,
        "firebase_signin": app_module.auth.firebase_signin,
        "device_binding_habilitado": app_module.auth.device_binding_habilitado,
        "project_id": app_module.auth.FIREBASE_PROJECT_ID,
        "updater_habilitado": app_module.updater.habilitado,
        "buscar": app_module.updater.buscar_actualizacion,
        "descargar": app_module.updater.descargar_y_preparar,
        "iniciar": app_module.updater.iniciar_actualizacion,
        "cerrar": app_module.updater.programar_cierre,
    }
    calls = []
    try:
        app_module.auth.firebase_habilitado = lambda: True
        app_module.auth.firebase_signin = lambda *_args: {
            "usuario": "prueba@example.com",
            "nombre": "Prueba",
            "id_token": "token",
            "uid": "uid",
        }
        app_module.auth.device_binding_habilitado = lambda: False
        app_module.auth.FIREBASE_PROJECT_ID = "project"
        app_module.updater.habilitado = lambda: True
        pending = app_module.updater.UpdateInfo(
            "version-nueva", "a" * 64, 1, 100
        )
        app_module.updater.buscar_actualizacion = lambda *_args: pending
        app_module.updater.descargar_y_preparar = lambda *_args, **_kwargs: Path("payload")
        app_module.updater.iniciar_actualizacion = lambda payload, version: calls.append((payload, version))
        app_module.updater.programar_cierre = lambda: calls.append("cierre")

        response = app_module.app.test_client().post(
            "/api/login",
            json={"usuario": "prueba@example.com", "password": "clave"},
            headers={"X-EOIR-Request": "1"},
        )
        data = response.get_json()
        _assert(response.status_code == 426, f"actualización obligatoria devolvió {response.status_code}")
        _assert(data["actualizando"] is True, "no informó que la actualización está en curso")
        _assert(calls == [(Path("payload"), "version-nueva"), "cierre"], "no inició actualización y cierre")
    finally:
        app_module.auth.firebase_habilitado = original["firebase_habilitado"]
        app_module.auth.firebase_signin = original["firebase_signin"]
        app_module.auth.device_binding_habilitado = original["device_binding_habilitado"]
        app_module.auth.FIREBASE_PROJECT_ID = original["project_id"]
        app_module.updater.habilitado = original["updater_habilitado"]
        app_module.updater.buscar_actualizacion = original["buscar"]
        app_module.updater.descargar_y_preparar = original["descargar"]
        app_module.updater.iniciar_actualizacion = original["iniciar"]
        app_module.updater.programar_cierre = original["cerrar"]


def test_paginas_de_autenticacion_respetan_csp():
    static_dir = Path(__file__).resolve().parent.parent / "static"
    login_html = (static_dir / "login.html").read_text(encoding="utf-8")
    ayuda_html = (static_dir / "como-funciona.html").read_text(encoding="utf-8")
    _assert('<script src="/static/login.js"></script>' in login_html, "login conserva JavaScript inline")
    _assert(
        '<script src="/static/como-funciona.js"></script>' in ayuda_html,
        "la ayuda conserva JavaScript inline",
    )
    _assert("X-EOIR-Request" in (static_dir / "login.js").read_text(encoding="utf-8"), "login omite cabecera local")
    _assert(
        "X-EOIR-Request" in (static_dir / "como-funciona.js").read_text(encoding="utf-8"),
        "logout de ayuda omite cabecera local",
    )
    _assert("response.status === 426" in (static_dir / "login.js").read_text(encoding="utf-8"), "login no maneja actualización obligatoria")


def test_estado_no_avanza_si_falla_merge_de_evidencia():
    import app as app_module

    caso = _caso_base()
    caso["ultimo_tab_letra"] = "A"
    original = {
        "load_case": app_module.load_case,
        "save_case": app_module.save_case,
        "generar_lote": app_module.generar_lote,
        "combinar": app_module.combinar_portada_y_evidencia_exhibits,
    }
    evidence_id = "a" * 32
    old_evidence = dict(app_module._EVIDENCIAS)
    saved: list[dict] = []
    try:
        app_module.load_case = lambda _case_id: dict(caso)
        app_module.save_case = lambda value: saved.append(dict(value)) or value
        app_module.generar_lote = lambda *_args, **_kwargs: [
            SimpleNamespace(
                docx_path=Path("portada.docx"), pdf_path=Path("portada.pdf"),
                preview_images=[], validation_ok=True, validation_errors=[]
            )
        ]
        app_module.combinar_portada_y_evidencia_exhibits = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            app_module.PdfMergeError("fallo deliberado")
        )
        app_module._EVIDENCIAS[evidence_id] = {
            "path": Path("evidencia.pdf"), "num_paginas": 1, "nombre": "evidencia.pdf",
            "created_at": 9999999999,
        }
        response = app_module.app.test_client().post(
            "/api/generar",
            json={
                "case_id": caso["id"],
                "generar_pdf": True,
                "document_instance": {
                    "template_id": "motion-withdraw-cancelation",
                    "titulo": "MOTION TO WITHDRAW",
                    "direccion_anterior": "Anterior",
                    "direccion_actual": "Actual",
                    "fecha_cancelacion": "March 3, 2026",
                    "exhibits_evidencia": {"A": [evidence_id]},
                },
            },
            headers={"X-EOIR-Request": "1"},
        )
        data = response.get_json()
        _assert(response.status_code == 200, f"la generación simulada devolvió {response.status_code}: {data}")
        _assert(data["estado_caso_guardado"] is False, "reportó el estado como guardado tras fallar el merge")
        _assert(not saved, "avanzó el estado persistido después de fallar el merge")
    finally:
        app_module.load_case = original["load_case"]
        app_module.save_case = original["save_case"]
        app_module.generar_lote = original["generar_lote"]
        app_module.combinar_portada_y_evidencia_exhibits = original["combinar"]
        app_module._EVIDENCIAS.clear()
        app_module._EVIDENCIAS.update(old_evidence)


# ---------------------------------------------------------------------------
# 6. Integración de plantillas y EOIR-33
# ---------------------------------------------------------------------------

def test_todas_las_plantillas_word_generan_y_proxima_audiencia_no_se_recorta():
    case = _caso_base()
    common = {"titulo": "SUPPLEMENTAL EVIDENCE", "exhibits": []}
    extras = {
        "written-pleadings": {
            "fecha_nta": "March 4, 2024", "alegaciones_admitidas": "1 through 4",
            "cargo_removibilidad": "INA 212(a)(6)(A)(i)",
            "designacion_pais_remocion": "respectfully declines to designate a country of removal",
            "formas_alivio": "I-589 Asylum, Withholding of Removal, and CAT", "horas_estimadas": "2",
            "idioma_interprete": "Spanish", "dialecto_interprete": "", "traductor": "Bruno Briz",
            "traductor_abreviado": "BB", "documento_traducido": "DECLARATION OF PLEADINGS",
        },
        "motion-withdraw-cancelation": {
            "direccion_anterior": "Dirección anterior", "direccion_actual": "Dirección actual",
            "fecha_cancelacion": "March 3, 2026", "exhibits_evidencia": {},
        },
        "motion-withdraw-location-known": {"direccion_conocida": "Dirección conocida", "exhibits_evidencia": {}},
        "motion-withdraw-no-cooperation": {
            "direccion_conocida": "Dirección conocida", "telefono_conocido": "555-0100",
            "exhibits_evidencia": {},
        },
    }
    template_ids = [
        "i589-tab-cover", "webex-motion", "written-pleadings", "motion-withdraw-cancelation",
        "motion-withdraw-location-known", "motion-withdraw-no-cooperation",
    ]
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp)
        for template_id in template_ids:
            instance = {**common, "template_id": template_id, **extras.get(template_id, {})}
            result = generar_documento(case, instance, output_dir=out, verificar_pdf=False)
            _assert(result.validation_ok and result.docx_path.exists(), f"falló la plantilla {template_id}")
            with zipfile.ZipFile(result.docx_path) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
            _assert("Next " in xml and "Hearing: " in xml, f"{template_id} no contiene la audiencia ajustada")
            _assert("<w:br" in xml, f"{template_id} no separó juez y audiencia en dos líneas")
            _assert('w:jc w:val="left"' in xml, f"{template_id} no alineó juez y audiencia a la izquierda")


def test_eoir33_llena_corte_contacto_y_servicio_condicional():
    from pypdf import PdfReader

    case = _caso_base()
    instance = {
        "template_id": "eoir-33-change-address", "direccion_anterior": "100 OLD ST",
        "ciudad_anterior": "OLD CITY, CA 90001", "direccion_actual": "200 NEW ST",
        "ciudad_actual": "LOS ANGELES, CA 90012", "telefono_anterior": "555-0101",
        "email_anterior": "old@example.com", "telefono_actual": "555-0102",
        "email_actual": "new@example.com",
        "direccion_corte": "LOS ANGELES IMMIGRATION COURT, 606 S OLIVE ST, LOS ANGELES, CA 90014",
        "servicio_ecas": False, "direccion_servicio_1": "OPLA LOS ANGELES",
        "direccion_servicio_2": "300 N LOS ANGELES ST, LOS ANGELES, CA 90012",
    }
    with tempfile.TemporaryDirectory() as temp:
        result = generar_pdf_formulario(case, instance, output_dir=Path(temp))
        _assert(result.validation_ok, f"EOIR-33 no pasó validación: {result.validation_errors}")
        fields = PdfReader(result.pdf_path).get_fields()
        court_value = str(fields["CourtAddress"].get("/V"))
        court_normalized = " ".join(court_value.split())
        _assert("NEWARK" not in court_normalized.upper(), "conservó la corte predeterminada")
        _assert(
            all(
                fragment in court_normalized
                for fragment in ("LOS ANGELES IMMIGRATION COURT", "606 S OLIVE ST", "90014")
            ),
            "la dirección de corte quedó incompleta",
        )
        _assert(str(fields["No Service Needed"].get("/V")) == "/Off", "marcó servicio ECAS cuando era falso")
        _assert(str(fields["email address - current"].get("/V")) == "new@example.com", "omitió el correo actual")


def test_ui_declaraciones_por_lider_y_riders_se_regenera():
    """Contrato mínimo de UI para no volver a ocultar las declaraciones
    individuales al guardar o editar un rider.

    La prueba funcional de navegador confirma el flujo completo; este chequeo
    sin dependencias mantiene cubierto el punto de regresión en la suite que
    corre el despacho localmente.
    """
    source = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    _assert('class="declaraciones-tab"' in source, "falta el contenedor de declaraciones por Tab")
    _assert("function renderDeclaracionesUploads(card)" in source, "falta el render de declaraciones por persona")
    _assert(
        "renderIdentidadesUploads(card);\n    renderBiometricosUploads(card);\n    renderDeclaracionesUploads(card);" in source,
        "la actualización de personas no refresca declaraciones",
    )


def test_ui_busqueda_de_casos_por_nombre_y_a_number():
    """La búsqueda de casos debe cubrir texto de nombre y los dígitos del A#."""
    source = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    html = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8")
    _assert('id="buscarCaso"' in html, "falta el campo de búsqueda de casos")
    _assert("function casosQueCoinciden(query)" in source, "falta el filtro de casos")
    _assert("nombre.includes(texto)" in source, "la búsqueda no contempla el nombre")
    _assert('aNumber.replace(/\\D/g, "").includes(digitos)' in source, "la búsqueda no contempla dígitos de A#")
    _assert("configurarBusquedaCasos();" in source, "la búsqueda no se inicializa")


def test_ui_cambio_de_caso_reinicia_generador():
    """No debe quedar estado de la sección 2 al cargar otro expediente."""
    source = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    _assert("function resetDocumentFormForCase()" in source, "falta el reinicio del generador")
    _assert('$("#resultado").innerHTML = "";' in source, "el resultado anterior no se limpia")
    _assert("MOTION_EXHIBITS_EVIDENCIA = {};" in source, "la evidencia de motions queda ligada al caso anterior")
    _assert("const loadVersion = ++CASE_LOAD_VERSION;\n  resetDocumentFormForCase();" in source, "cargar otro caso no reinicia la sección 2")
    _assert("if (loadVersion !== CASE_LOAD_VERSION) return;" in source, "una carga anterior puede sobrescribir el caso nuevo")
    _assert(
        "CURRENT_CASE_RIDERS = saved.riders || [];\n    actualizarPersonasDeCasoEnTabs();" in source,
        "guardarCaso no actualiza declaraciones tras persistir riders",
    )
    _assert(
        "input.addEventListener(\"blur\", actualizarRidersEnTabs);" in source,
        "editar un rider no refresca las declaraciones abiertas",
    )


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fallos = 0
    for t in tests:
        try:
            t()
            print(f"  OK   {t.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            fallos += 1
            print(f"  ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - fallos}/{len(tests)} tests OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
