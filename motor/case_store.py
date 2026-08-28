"""Guarda/lee los datos de caso capturados por corrida (sección 4.1 y 5.3)."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CASE_STORE_DIR = BASE_DIR / "case_store"
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_DPAPI_PREFIX = b"EOIR-DPAPI-v1\x00"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def make_case_id(cliente_nombre: str, a_number: str) -> str:
    numero = re.sub(r"\D", "", a_number)
    nombre = slugify(cliente_nombre) or "caso"
    return f"{nombre}-{numero}"


def validate_case_id(case_id: str) -> str:
    """Acepta solo IDs de archivo simples; nunca rutas ni segmentos ``..``."""
    if not isinstance(case_id, str) or not _CASE_ID_RE.fullmatch(case_id):
        raise ValueError("El identificador del caso no es válido")
    return case_id


def _case_path(case_id: str, store_dir: Path) -> Path:
    store_dir = Path(store_dir).resolve()
    path = (store_dir / f"{validate_case_id(case_id)}.json").resolve()
    if not path.is_relative_to(store_dir):
        raise ValueError("La ruta del caso queda fuera de case_store")
    return path


def _encryption_enabled() -> bool:
    """Cifra datos personales con DPAPI por defecto en Windows.

    Los archivos JSON heredados siguen siendo legibles y se migran a formato
    cifrado en su siguiente guardado. EOIR_ENCRYPT_CASES=0 permite desactivar
    explícitamente esta protección para desarrollo o portabilidad.
    """
    return os.name == "nt" and os.environ.get("EOIR_ENCRYPT_CASES", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _encode_case(case: dict) -> bytes:
    plain = json.dumps(case, indent=2, ensure_ascii=False).encode("utf-8")
    if not _encryption_enabled():
        return plain
    try:
        import win32crypt
    except ImportError as e:
        raise RuntimeError("No se puede cifrar case_store: falta pywin32") from e
    return _DPAPI_PREFIX + win32crypt.CryptProtectData(plain, "EOIR case store", None, None, None, 0)


def _decode_case(raw: bytes) -> dict:
    if raw.startswith(_DPAPI_PREFIX):
        try:
            import win32crypt
        except ImportError as e:
            raise RuntimeError("No se puede descifrar case_store: falta pywin32") from e
        _, raw = win32crypt.CryptUnprotectData(raw[len(_DPAPI_PREFIX) :], None, None, None, 0)
    return json.loads(raw.decode("utf-8"))


def list_cases(store_dir: Path = CASE_STORE_DIR) -> list[dict]:
    store_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for f in sorted(store_dir.glob("*.json")):
        try:
            cases.append(_decode_case(f.read_bytes()))
        except (ValueError, UnicodeError, OSError, RuntimeError) as e:
            print(f"Aviso: no se pudo leer el caso '{f.name}': {e}")
            continue
    return cases


def load_case(case_id: str, store_dir: Path = CASE_STORE_DIR) -> dict | None:
    path = _case_path(case_id, store_dir)
    if not path.exists():
        return None
    return _decode_case(path.read_bytes())


def save_case(case: dict, store_dir: Path = CASE_STORE_DIR) -> dict:
    store_dir.mkdir(parents=True, exist_ok=True)
    if not case.get("id"):
        case["id"] = make_case_id(case["cliente_nombre"], case["a_number"])
    path = _case_path(case["id"], store_dir)
    payload = _encode_case(case)

    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))

    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return case


def delete_case(case_id: str, store_dir: Path = CASE_STORE_DIR) -> bool:
    path = _case_path(case_id, store_dir)
    removed = False
    for target in (path, path.with_suffix(".json.bak")):
        if target.exists():
            target.unlink()
            removed = True
    return removed


def siguiente_pagina(case: dict) -> int:
    """Próxima página disponible para numerar evidencia de este caso
    (continúa donde se quedó el último Tab con evidencia adjunta)."""
    return int(case.get("siguiente_pagina") or 1)


def nombre_para_documento(case: dict) -> str:
    """Nombre del cliente tal como debe escribirse en el documento. Si el
    caso trae "riders" (co-aplicantes/derivados, ej. cónyuge e hijos en un
    mismo expediente), se usa "NOMBRE DEL LÍDER et al" en vez del nombre
    del líder solo."""
    riders = case.get("riders") or []
    nombre = case["cliente_nombre"]
    if riders:
        return f"{nombre} et al"
    return nombre


def a_number_para_documento(case: dict) -> str:
    """A# tal como debe escribirse en el documento. Con riders, se arma
    "A# del líder/últimos 3 dígitos de cada rider" (ej. "A 123-456-789/321/654"),
    siguiendo el formato que usa el despacho para expedientes de varios
    A#."""
    riders = case.get("riders") or []
    a_number = case["a_number"]
    if not riders:
        return a_number
    partes = [a_number]
    for rider in riders:
        digitos = re.sub(r"\D", "", rider.get("a_number", ""))
        partes.append(digitos[-3:] if digitos else "")
    return "/".join(p for p in partes if p)


def next_tab_letra(ultimo: str | None) -> str:
    """Siguiente etiqueta de Tab en base-26 biyectiva (estilo columnas de
    Excel): A..Z, luego AA, AB, ... AZ, BA, ... ZZ, AAA. Antes solo sabía
    llegar hasta "AA" (Z->AA) y de ahí se quedaba pegado devolviendo la misma
    letra — se rompía en casos con 27+ exhibits."""
    if not ultimo:
        return "A"
    ultimo = ultimo.strip().upper()
    if not ultimo or any(c < "A" or c > "Z" for c in ultimo):
        return "A"
    # incrementa como un número base-26 con "acarreo": la última letra sube;
    # si era Z pasa a A y se acarrea a la anterior, etc.
    letras = list(ultimo)
    i = len(letras) - 1
    while i >= 0:
        if letras[i] != "Z":
            letras[i] = chr(ord(letras[i]) + 1)
            return "".join(letras)
        letras[i] = "A"
        i -= 1
    return "A" + "".join(letras)
