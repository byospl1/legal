"""Login individual por usuario (sección de despliegue en la nube).

Mismo patrón que `case_store.py`: persistencia simple en un JSON, sin base
de datos ni dependencias nuevas (usa `werkzeug.security`, que ya viene con
Flask). Un archivo de usuarios (`usuarios/usuarios.json`, gitignored igual
que `case_store/*.json` — son credenciales, no código) con contraseñas
SIEMPRE guardadas hasheadas, nunca en texto plano.

No hay UI de administración de usuarios a propósito (no se pidió) — se
gestionan con `scripts/manage_users.py` desde la línea de comandos del
servidor. Si en el futuro se pide una pantalla de administración, agregar
rutas nuevas que llamen a las funciones de este módulo, no duplicar la
lógica.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent.parent
USERS_STORE_DIR = BASE_DIR / "usuarios"
USERS_FILE = USERS_STORE_DIR / "usuarios.json"

# --- Backend opcional de login por Firebase Authentication -----------------
# Si se define FIREBASE_API_KEY (la Web API key del proyecto de Firebase, que
# NO es secreta — es la misma que llevaría cualquier app cliente), el login se
# valida por internet contra Firebase Auth en vez de contra el JSON local. Las
# cuentas se administran desde el panel de Firebase (Authentication → Users),
# no con `scripts/manage_users.py`. Ver README (sección Firebase) para el
# alta del proyecto. Sin esa variable, el login sigue siendo el local de este
# mismo módulo (`verify_login`).
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "").strip()
_FIREBASE_SIGNIN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={key}"
)


class AuthRedError(Exception):
    """Falló la validación por un problema de red (sin internet, timeout,
    Firebase caído), NO porque las credenciales sean incorrectas. Se maneja
    aparte para poder avisarle al usuario "no hay conexión" en vez de
    "usuario o contraseña incorrectos"."""

# Registro de generación de documentos por usuario (auditoría mínima: quién
# generó qué, cuándo). Un archivo de líneas JSON (append-only), no una base
# de datos — mismo criterio de simplicidad que el resto del proyecto.
AUDIT_LOG_FILE = BASE_DIR / "case_store" / "_audit.log"


def _load_users(store_file: Path = USERS_FILE) -> dict[str, dict]:
    if not store_file.exists():
        return {}
    try:
        return json.loads(store_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_users(users: dict[str, dict], store_file: Path = USERS_FILE) -> None:
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def list_users(store_file: Path = USERS_FILE) -> list[dict]:
    """Lista de usuarios SIN el hash de contraseña (para mostrar/loguear)."""
    users = _load_users(store_file)
    return [{"usuario": u, "nombre": info.get("nombre", u)} for u, info in sorted(users.items())]


def create_user(usuario: str, password: str, nombre: str = "", store_file: Path = USERS_FILE) -> None:
    usuario = usuario.strip().lower()
    if not usuario or not password:
        raise ValueError("usuario y password son obligatorios")
    users = _load_users(store_file)
    users[usuario] = {"nombre": nombre or usuario, "password_hash": generate_password_hash(password)}
    _save_users(users, store_file)


def delete_user(usuario: str, store_file: Path = USERS_FILE) -> bool:
    usuario = usuario.strip().lower()
    users = _load_users(store_file)
    if usuario not in users:
        return False
    del users[usuario]
    _save_users(users, store_file)
    return True


def set_password(usuario: str, password: str, store_file: Path = USERS_FILE) -> bool:
    usuario = usuario.strip().lower()
    users = _load_users(store_file)
    if usuario not in users:
        return False
    users[usuario]["password_hash"] = generate_password_hash(password)
    _save_users(users, store_file)
    return True


def verify_login(usuario: str, password: str, store_file: Path = USERS_FILE) -> dict | None:
    """Devuelve {"usuario": ..., "nombre": ...} si las credenciales son
    correctas, None si no. No distingue "usuario no existe" de "contraseña
    incorrecta" en la respuesta — evita filtrar qué usuarios existen."""
    usuario = usuario.strip().lower()
    users = _load_users(store_file)
    info = users.get(usuario)
    if not info or not check_password_hash(info["password_hash"], password):
        return None
    return {"usuario": usuario, "nombre": info.get("nombre", usuario)}


def firebase_habilitado() -> bool:
    """True si hay una FIREBASE_API_KEY configurada → el login se valida
    contra Firebase por internet en vez de contra el JSON local."""
    return bool(FIREBASE_API_KEY)


def verify_login_firebase(
    email: str, password: str, api_key: str | None = None, timeout: float = 10.0
) -> dict | None:
    """Valida email + contraseña contra Firebase Authentication (REST API
    `accounts:signInWithPassword`). Devuelve {"usuario", "nombre"} si son
    correctas, None si Firebase las rechaza (email inexistente o contraseña
    mala). Lanza `AuthRedError` si no se pudo llegar a Firebase (sin internet,
    timeout, servicio caído) — eso NO es un rechazo de credenciales."""
    email = email.strip()
    key = (api_key or FIREBASE_API_KEY).strip()
    if not key:
        raise AuthRedError("FIREBASE_API_KEY no configurada")
    if not email or not password:
        return None

    payload = json.dumps(
        {"email": email, "password": password, "returnSecureToken": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        _FIREBASE_SIGNIN_URL.format(key=key),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 400 = credenciales inválidas (EMAIL_NOT_FOUND / INVALID_PASSWORD /
        # INVALID_LOGIN_CREDENTIALS / USER_DISABLED). Cualquier otro código
        # (403 API key mala, 5xx) es un problema de configuración/servicio,
        # no del usuario → se trata como error de red para no decirle
        # "contraseña incorrecta" cuando el problema es del lado del sistema.
        if e.code == 400:
            return None
        raise AuthRedError(f"Firebase respondió {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise AuthRedError(str(e)) from e

    correo = data.get("email", email)
    nombre = data.get("displayName") or correo
    return {"usuario": correo, "nombre": nombre}


def registrar_auditoria(usuario: str, evento: str, detalle: dict, log_file: Path = AUDIT_LOG_FILE) -> None:
    """Agrega una línea al log de auditoría. Nunca lanza excepción — un
    fallo de auditoría no debe bloquear la generación real del documento."""
    import datetime

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        linea = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "usuario": usuario,
            "evento": evento,
            **detalle,
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except OSError:
        pass
