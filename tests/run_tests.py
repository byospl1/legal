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
    )
    pages = eb.build_pages_cell_content(
        tg["categorias"], tg.get("evidencias"), tg.get("paginas", "1-2"),
        tg.get("identidades"), tg.get("documentos_se"), tg.get("biometricos"),
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
        "documentos_se": [
            {"tipo": "Declaration", "titulo": None, "evidencia": _ev(1, 3)},
            {"tipo": "News", "titulo": "algo", "evidencia": None},
            {"tipo": "Psychological Report", "titulo": None, "evidencia": _ev(4, 2)},
        ],
    }
    d, p = _desc_pages(tg)
    _assert(d == p, f"supplemental_evidence: DESCRIPTION={d} != PAGES={p}")


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
