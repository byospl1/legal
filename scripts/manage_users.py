#!/usr/bin/env python3
"""CLI para crear/listar/borrar usuarios del login (sin UI a propósito, ver
`motor/auth.py`). Se corre en el servidor:

    python3 scripts/manage_users.py create lorenzo "contraseña-segura" "Lorenzo Bracamontes"
    python3 scripts/manage_users.py set-password lorenzo "otra-contraseña"
    python3 scripts/manage_users.py list
    python3 scripts/manage_users.py delete lorenzo

Dentro de Docker:
    docker compose exec app python3 scripts/manage_users.py create ...
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor import auth  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    comando = sys.argv[1]

    if comando == "create":
        if len(sys.argv) < 4:
            print("Uso: manage_users.py create <usuario> <password> [nombre]")
            return 1
        usuario, password = sys.argv[2], sys.argv[3]
        nombre = sys.argv[4] if len(sys.argv) > 4 else usuario
        auth.create_user(usuario, password, nombre)
        print(f"Usuario '{usuario}' creado.")
        return 0

    if comando == "set-password":
        if len(sys.argv) < 4:
            print("Uso: manage_users.py set-password <usuario> <password>")
            return 1
        ok = auth.set_password(sys.argv[2], sys.argv[3])
        print("Contraseña actualizada." if ok else f"Usuario '{sys.argv[2]}' no existe.")
        return 0 if ok else 1

    if comando == "delete":
        if len(sys.argv) < 3:
            print("Uso: manage_users.py delete <usuario>")
            return 1
        ok = auth.delete_user(sys.argv[2])
        print("Usuario borrado." if ok else f"Usuario '{sys.argv[2]}' no existe.")
        return 0 if ok else 1

    if comando == "list":
        usuarios = auth.list_users()
        if not usuarios:
            print("No hay usuarios creados todavía.")
        for u in usuarios:
            print(f"  {u['usuario']}  ({u['nombre']})")
        return 0

    print(f"Comando desconocido: {comando}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
