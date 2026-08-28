"""Actualizador obligatorio para las instalaciones locales de Windows.

Después de autenticar al usuario con Firebase, consulta el documento
``app_config/windows_update`` de Firestore. Si la versión publicada difiere
de ``version.json``, descarga el ZIP privado en fragmentos desde Firestore
usando el mismo token del usuario, verifica SHA-256 y deja el reemplazo a un
proceso de PowerShell separado. El proceso externo permite cerrar Python antes
de tocar los archivos en uso y preserva los datos locales.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "version.json"
UPDATE_DIR = BASE_DIR / "_update"
UPDATE_COLLECTION = "app_config"
UPDATE_DOCUMENT = "windows_update"
MAX_UPDATE_BYTES = 600 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1_500 * 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
PROTECTED_ROOTS = {
    ".git",
    "_update",
    "case_store",
    "firmas",
    "input",
    "output",
    "usuarios",
    "venv",
}
PROTECTED_FILES = {"firebase-api-key.txt", "firebase-project-id.txt"}

_FIRESTORE_UPDATE_URL = (
    "https://firestore.googleapis.com/v1/projects/{project}"
    "/databases/(default)/documents/{collection}/{document}"
)
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(Exception):
    """La comprobación, descarga o preparación de la actualización falló."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    sha256: str
    chunk_count: int
    total_bytes: int
    required: bool = True


def version_actual(base_dir: Path = BASE_DIR) -> str:
    """Devuelve la versión instalada; un archivo ilegible se considera viejo."""
    try:
        data = json.loads((base_dir / "version.json").read_text(encoding="utf-8"))
        value = str(data.get("version", "")).strip()
        return value if _VERSION_RE.fullmatch(value) else "desconocida"
    except (OSError, json.JSONDecodeError, TypeError):
        return "desconocida"


def habilitado() -> bool:
    """El actualizador solo aplica a la instalación local de Windows."""
    value = os.environ.get("EOIR_AUTO_UPDATE", "1").strip().lower()
    return os.name == "nt" and value not in {"0", "false", "no"}


def _firestore_value(value: dict) -> object:
    if "stringValue" in value:
        return value["stringValue"]
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "integerValue" in value:
        try:
            return int(value["integerValue"])
        except (TypeError, ValueError):
            return value["integerValue"]
    if "timestampValue" in value:
        return value["timestampValue"]
    return None


def _parse_update_document(data: dict) -> UpdateInfo:
    fields = {key: _firestore_value(value) for key, value in (data.get("fields") or {}).items()}
    version = str(fields.get("version") or "").strip()
    sha256 = str(fields.get("sha256") or "").strip().lower()
    try:
        chunk_count = int(fields.get("chunk_count") or 0)
        total_bytes = int(fields.get("total_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise UpdateError("El tamaño publicado en Firebase no es válido") from exc
    required = fields.get("required", True) is not False

    if not _VERSION_RE.fullmatch(version):
        raise UpdateError("La versión publicada en Firebase no es válida")
    if not _SHA256_RE.fullmatch(sha256):
        raise UpdateError("El SHA-256 publicado para la actualización no es válido")
    if chunk_count < 1 or chunk_count > 2_000:
        raise UpdateError("La cantidad de fragmentos publicada no es válida")
    if total_bytes < 1 or total_bytes > MAX_UPDATE_BYTES:
        raise UpdateError("El tamaño publicado para la actualización no es válido")
    return UpdateInfo(version, sha256, chunk_count, total_bytes, required)


def buscar_actualizacion(
    id_token: str,
    project_id: str,
    *,
    base_dir: Path = BASE_DIR,
    timeout: float = 12.0,
) -> UpdateInfo | None:
    """Consulta Firebase y devuelve la actualización obligatoria pendiente.

    404 significa que el administrador todavía no publicó una versión. Un
    403 también se trata como sistema aún no activado para que desplegar el
    código antes de publicar las nuevas reglas no bloquee todas las PCs.
    """
    if not id_token or not project_id:
        return None
    url = _FIRESTORE_UPDATE_URL.format(
        project=urllib.parse.quote(project_id, safe=""),
        collection=UPDATE_COLLECTION,
        document=UPDATE_DOCUMENT,
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {id_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return None
        raise UpdateError(f"Firestore respondió {exc.code} al buscar actualizaciones") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise UpdateError("No se pudo comprobar la versión obligatoria por Internet") from exc

    info = _parse_update_document(data)
    if not info.required or info.version == version_actual(base_dir):
        return None
    return info


def _safe_destination(root: Path, archive_name: str) -> Path:
    normalized = archive_name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise UpdateError(f"Ruta insegura dentro del paquete: {archive_name}")
    destination = root.joinpath(*path.parts)
    try:
        destination.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise UpdateError(f"Ruta fuera del paquete: {archive_name}") from exc
    return destination


def _assert_managed_path(archive_name: str) -> None:
    path = PurePosixPath(archive_name.replace("\\", "/"))
    first = path.parts[0].lower() if path.parts else ""
    name = path.name.lower()
    if first in PROTECTED_ROOTS or name in PROTECTED_FILES or name.startswith(".env"):
        raise UpdateError(f"El paquete intenta modificar datos o configuración local: {archive_name}")


def _extract_verified_zip(zip_path: Path, payload_dir: Path, expected_version: str) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                raise UpdateError("El paquete contiene demasiados archivos")
            if sum(member.file_size for member in members) > MAX_EXTRACTED_BYTES:
                raise UpdateError("El paquete descomprimido excede el límite permitido")

            for member in members:
                destination = _safe_destination(payload_dir, member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UpdateError("El paquete contiene enlaces simbólicos no permitidos")
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError("El paquete descargado no es un ZIP válido") from exc

    try:
        version_data = json.loads((payload_dir / "version.json").read_text(encoding="utf-8"))
        manifest = json.loads((payload_dir / "update-files.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError("El paquete no contiene un manifiesto válido") from exc

    if version_data.get("version") != expected_version or manifest.get("version") != expected_version:
        raise UpdateError("La versión interna del paquete no coincide con Firebase")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise UpdateError("El manifiesto de actualización no contiene archivos")
    safe_files = set()
    for value in files:
        if not isinstance(value, str):
            raise UpdateError("El manifiesto contiene una ruta inválida")
        _assert_managed_path(value)
        destination = _safe_destination(payload_dir, value)
        if not destination.is_file():
            raise UpdateError(f"Falta un archivo declarado en el paquete: {value}")
        safe_files.add(value.replace("\\", "/"))

    actual_files = {
        path.relative_to(payload_dir).as_posix()
        for path in payload_dir.rglob("*")
        if path.is_file()
    }
    if actual_files != safe_files:
        raise UpdateError("El contenido del paquete no coincide con su manifiesto")
    for required in ("app.py", "iniciar.bat", "requirements.txt", "scripts/apply_update.ps1"):
        if required not in safe_files:
            raise UpdateError(f"El paquete está incompleto: falta {required}")


def descargar_y_preparar(
    info: UpdateInfo,
    id_token: str,
    *,
    project_id: str | None = None,
    base_dir: Path = BASE_DIR,
    timeout: float = 90.0,
) -> Path:
    """Descarga, valida y extrae el paquete; devuelve su carpeta payload."""
    project = (project_id or os.environ.get("FIREBASE_PROJECT_ID", "")).strip()
    if not project:
        raise UpdateError("FIREBASE_PROJECT_ID no está configurado")
    update_root = base_dir / "_update"
    stage_dir = update_root / f"{info.version}-{uuid.uuid4().hex[:10]}"
    payload_dir = stage_dir / "payload"
    package_path = stage_dir / "update.zip"
    stage_dir.mkdir(parents=True, exist_ok=False)

    digest = hashlib.sha256()
    total = 0
    try:
        with package_path.open("wb") as target:
            for index in range(info.chunk_count):
                document_path = f"app_updates/{info.version}/chunks/{index:06d}"
                url = (
                    "https://firestore.googleapis.com/v1/projects/"
                    f"{urllib.parse.quote(project, safe='')}"
                    "/databases/(default)/documents/"
                    f"{urllib.parse.quote(document_path, safe='/')}"
                )
                request = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Bearer {id_token}"},
                    method="GET",
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    document = json.loads(response.read().decode("utf-8"))
                encoded = (
                    (document.get("fields") or {}).get("data") or {}
                ).get("bytesValue")
                if not isinstance(encoded, str):
                    raise UpdateError(f"Falta el fragmento {index + 1} de la actualización")
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise UpdateError(f"El fragmento {index + 1} está dañado") from exc
                chunk_hash = str(
                    ((document.get("fields") or {}).get("sha256") or {}).get("stringValue") or ""
                ).lower()
                if chunk_hash and hashlib.sha256(chunk).hexdigest() != chunk_hash:
                    raise UpdateError(f"El fragmento {index + 1} no superó SHA-256")
                total += len(chunk)
                if total > MAX_UPDATE_BYTES:
                    raise UpdateError("El paquete de actualización excede el límite permitido")
                digest.update(chunk)
                target.write(chunk)
        if total != info.total_bytes:
            raise UpdateError("El tamaño descargado no coincide con el publicado")
        if digest.hexdigest() != info.sha256:
            raise UpdateError("La actualización no superó la verificación SHA-256")
        payload_dir.mkdir()
        _extract_verified_zip(package_path, payload_dir, info.version)
        return payload_dir
    except UpdateError:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    except urllib.error.HTTPError as exc:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise UpdateError(f"Firestore respondió {exc.code} al descargar") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise UpdateError("No se pudo descargar la actualización obligatoria") from exc


def iniciar_actualizacion(payload_dir: Path, version: str, *, base_dir: Path = BASE_DIR) -> None:
    """Lanza el actualizador externo que reemplazará los archivos al cerrar."""
    if os.name != "nt":
        raise UpdateError("La aplicación automática de actualizaciones solo está disponible en Windows")
    source_script = base_dir / "scripts" / "apply_update.ps1"
    if not source_script.is_file():
        raise UpdateError("No se encontró el aplicador de actualizaciones de Windows")
    launch_script = payload_dir.parent / "apply_update.ps1"
    shutil.copy2(source_script, launch_script)

    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "CREATE_NEW_CONSOLE", 0
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launch_script),
        "-ParentPid",
        str(os.getpid()),
        "-AppDir",
        str(base_dir),
        "-PayloadDir",
        str(payload_dir),
        "-Version",
        version,
    ]
    try:
        subprocess.Popen(command, cwd=base_dir, creationflags=creation_flags, close_fds=True)
    except OSError as exc:
        raise UpdateError("Windows no pudo iniciar el aplicador de la actualización") from exc


def programar_cierre(delay_seconds: float = 2.0) -> None:
    """Da tiempo a responder al navegador y luego termina el servidor local."""
    timer = threading.Timer(delay_seconds, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
