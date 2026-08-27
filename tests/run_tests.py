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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor import exhibit_builder as eb  # noqa: E402
from motor.case_store import next_tab_letra  # noqa: E402
from motor.pdf_merge import _ANIO_RE  # noqa: E402

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
