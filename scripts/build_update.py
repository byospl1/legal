"""Construye el ZIP firmado por SHA-256 que consumen las PCs Windows."""

from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {
    ".git",
    ".github",
    "_update",
    "case_store",
    "firmas",
    "input",
    "output",
    "usuarios",
    "venv",
}
EXCLUDED_FILES = {
    ".dockerignore",
    ".env",
    ".env.example",
    "Caddyfile",
    "Caddyfile.sin-dominio",
    "DEPLOY.md",
    "Dockerfile",
    "docker-compose.yml",
    "firebase-api-key.txt",
    "firebase-project-id.txt",
    "version.json",
    "update-files.json",
}


def _tracked_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    result = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = Path(relative)
        if path.parts and path.parts[0] in EXCLUDED_DIRS:
            continue
        if relative in EXCLUDED_FILES:
            continue
        if len(path.parts) == 1 and path.suffix.lower() == ".zip":
            continue
        if (ROOT / path).is_file():
            result.append(path.as_posix())
    return sorted(set(result))


def build(version: str, output: Path) -> None:
    if not version or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in version):
        raise SystemExit("Versión inválida")
    files = _tracked_files()
    files.extend(["update-files.json", "version.json"])
    files = sorted(set(files))
    manifest = {"format": 1, "version": version, "files": files}
    version_data = {"version": version}

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            if relative == "update-files.json":
                archive.writestr(relative, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            elif relative == "version.json":
                archive.writestr(relative, json.dumps(version_data, ensure_ascii=False, indent=2) + "\n")
            else:
                archive.write(ROOT / relative, relative)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.version, args.output.resolve())


if __name__ == "__main__":
    main()
