"""Guarda/lee los datos de caso capturados por corrida (sección 4.1 y 5.3)."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CASE_STORE_DIR = BASE_DIR / "case_store"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def make_case_id(cliente_nombre: str, a_number: str) -> str:
    numero = re.sub(r"\D", "", a_number)
    return f"{slugify(cliente_nombre)}-{numero}"


def list_cases(store_dir: Path = CASE_STORE_DIR) -> list[dict]:
    store_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for f in sorted(store_dir.glob("*.json")):
        try:
            cases.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return cases


def load_case(case_id: str, store_dir: Path = CASE_STORE_DIR) -> dict | None:
    path = store_dir / f"{case_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_case(case: dict, store_dir: Path = CASE_STORE_DIR) -> dict:
    store_dir.mkdir(parents=True, exist_ok=True)
    if not case.get("id"):
        case["id"] = make_case_id(case["cliente_nombre"], case["a_number"])
    path = store_dir / f"{case['id']}.json"
    path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
    return case


def next_tab_letra(ultimo: str | None) -> str:
    if not ultimo:
        return "A"
    ultimo = ultimo.strip().upper()
    if len(ultimo) == 1 and "A" <= ultimo < "Z":
        return chr(ord(ultimo) + 1)
    if ultimo == "Z":
        return "AA"
    return ultimo
