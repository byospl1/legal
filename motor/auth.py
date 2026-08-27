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


def firebase_signin(
    email: str, password: str, api_key: str | None = None, timeout: float = 10.0
) -> dict | None:
    """Valida email + contraseña contra Firebase Authentication (REST API
    `accounts:signInWithPassword`). Devuelve un dict con {"usuario", "nombre",
    "id_token", "uid"} si son correctas (el id_token y el uid se usan después
    para el candado por dispositivo en Firestore), None si Firebase las
    rechaza (email inexistente o contraseña mala). Lanza `AuthRedError` si no
    se pudo llegar a Firebase (sin internet, timeout, servicio caído) — eso
    NO es un rechazo de credenciales."""
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
    return {
        "usuario": correo,
        "nombre": nombre,
        "id_token": data.get("idToken", ""),
        "uid": data.get("localId", ""),
    }


def verify_login_firebase(
    email: str, password: str, api_key: str | None = None, timeout: float = 10.0
) -> dict | None:
    """Igual que `firebase_signin` pero devuelve solo {"usuario", "nombre"}
    (sin el id_token/uid internos) — para el caso simple sin candado por
    dispositivo. `app.py` usa `firebase_signin` directamente cuando el
    candado está activo."""
    info = firebase_signin(email, password, api_key, timeout)
    if info is None:
        return None
    return {"usuario": info["usuario"], "nombre": info["nombre"]}


# --- Candado por dispositivo (1 cuenta = 1 computadora) vía Firestore -------
# Cuando además de FIREBASE_API_KEY se define FIREBASE_PROJECT_ID, el login
# ata cada cuenta a la primera computadora donde entra: se guarda en Firestore
# un documento `device_bindings/{uid}` con el device_id de esa máquina. Si la
# misma cuenta intenta entrar desde otra computadora (device_id distinto), se
# rechaza. El admin "libera" la cuenta borrando ese documento desde la consola
# de Firebase. Es un mecanismo pensado para instalaciones LOCALES (una por
# máquina) — NO se activa en la nube (ahí todos comparten un solo servidor).
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
_FIRESTORE_DOC_URL = (
    "https://firestore.googleapis.com/v1/projects/{project}"
    "/databases/(default)/documents/{collection}/{doc}"
)
_DEVICE_BINDINGS_COLLECTION = "device_bindings"


def device_binding_habilitado() -> bool:
    """True si hay API key Y project id → se aplica el candado por
    dispositivo. Sin project id, el login por Firebase funciona igual pero
    sin candado."""
    return bool(FIREBASE_API_KEY and FIREBASE_PROJECT_ID)


def _firestore_valores_simples(fields: dict) -> dict:
    """Aplana los `fields` de un documento Firestore ({"k": {"stringValue":
    ...}}) a un dict plano {"k": valor}. Solo maneja los tipos que usamos
    (string/timestamp)."""
    out = {}
    for k, v in (fields or {}).items():
        if "stringValue" in v:
            out[k] = v["stringValue"]
        elif "timestampValue" in v:
            out[k] = v["timestampValue"]
    return out


def _firestore_get(project_id: str, doc_id: str, id_token: str, timeout: float = 10.0) -> dict | None:
    """Lee `device_bindings/{doc_id}`. Devuelve el dict plano de campos si
    existe, None si no existe (404). Lanza `AuthRedError` ante cualquier otro
    error (red/permisos/servicio)."""
    url = _FIRESTORE_DOC_URL.format(
        project=project_id, collection=_DEVICE_BINDINGS_COLLECTION, doc=doc_id
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {id_token}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return _firestore_valores_simples(data.get("fields", {}))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise AuthRedError(f"Firestore GET respondió {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise AuthRedError(str(e)) from e


def _firestore_create_if_absent(
    project_id: str, doc_id: str, fields: dict, id_token: str, timeout: float = 10.0
) -> bool:
    """Crea `device_bindings/{doc_id}` SOLO si no existe (precondición
    `currentDocument.exists=false`, atómica del lado de Firestore). Devuelve
    True si lo creó, False si ya existía (carrera con otra máquina). Lanza
    `AuthRedError` ante error de red/servicio."""
    url = (
        _FIRESTORE_DOC_URL.format(
            project=project_id, collection=_DEVICE_BINDINGS_COLLECTION, doc=doc_id
        )
        + "?currentDocument.exists=false"
    )
    payload = json.dumps({"fields": fields}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {id_token}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError as e:
        # La precondición fallida (ya existía) puede venir como 409/412, o como
        # 400 FAILED_PRECONDITION según el endpoint. En esos casos NO es error:
        # significa que otra máquina ganó la carrera y ya lo creó.
        if e.code in (409, 412):
            return False
        if e.code == 400:
            try:
                cuerpo = e.read().decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                cuerpo = ""
            if "FAILED_PRECONDITION" in cuerpo or "already exists" in cuerpo.lower():
                return False
        raise AuthRedError(f"Firestore create respondió {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AuthRedError(str(e)) from e


def verificar_o_atar_dispositivo(
    uid: str,
    id_token: str,
    device_id: str,
    hostname: str = "",
    project_id: str | None = None,
    timeout: float = 10.0,
) -> str:
    """Aplica el candado: si la cuenta (uid) no está atada a ninguna máquina,
    la ata a `device_id` (devuelve "ok"); si ya está atada a ESTA máquina,
    "ok"; si está atada a OTRA, "otro_dispositivo". Lanza `AuthRedError` si no
    se pudo consultar Firestore."""
    import datetime

    project = (project_id or FIREBASE_PROJECT_ID).strip()
    if not project:
        raise AuthRedError("FIREBASE_PROJECT_ID no configurada")

    existing = _firestore_get(project, uid, id_token, timeout)
    if existing is None:
        fields = {
            "device_id": {"stringValue": device_id},
            "hostname": {"stringValue": hostname},
            "bound_at": {
                "timestampValue": datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            },
        }
        if _firestore_create_if_absent(project, uid, fields, id_token, timeout):
            return "ok"
        # Perdió la carrera: alguien lo creó en el ínterin — releer para
        # comparar contra lo que quedó guardado.
        existing = _firestore_get(project, uid, id_token, timeout)

    if existing and existing.get("device_id") == device_id:
        return "ok"
    return "otro_dispositivo"


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
