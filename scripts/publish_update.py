"""Fragmenta el ZIP, lo publica en Firestore y activa su manifiesto al final."""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()

    package = args.package.resolve()
    package_bytes = package.read_bytes()
    digest = hashlib.sha256(package_bytes).hexdigest()
    token = subprocess.check_output(
        ["gcloud", "auth", "print-access-token"], text=True
    ).strip()
    published_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    chunk_size = 700 * 1024
    chunks = [package_bytes[offset : offset + chunk_size] for offset in range(0, len(package_bytes), chunk_size)]

    def patch_document(document_path: str, fields: dict) -> None:
        url = (
            "https://firestore.googleapis.com/v1/projects/"
            f"{urllib.parse.quote(args.project, safe='')}/databases/(default)/documents/"
            f"{urllib.parse.quote(document_path, safe='/')}"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps({"fields": fields}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="PATCH",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise SystemExit(f"Firestore respondió {exc.code}: {body}") from exc

    # Los fragmentos se escriben primero. El manifiesto obligatorio cambia al
    # final, así nunca apunta a un paquete incompleto.
    for index, chunk in enumerate(chunks):
        patch_document(
            f"app_updates/{args.version}/chunks/{index:06d}",
            {
                "index": {"integerValue": str(index)},
                "data": {"bytesValue": base64.b64encode(chunk).decode("ascii")},
                "sha256": {"stringValue": hashlib.sha256(chunk).hexdigest()},
            },
        )

    patch_document(
        f"app_updates/{args.version}",
        {
            "version": {"stringValue": args.version},
            "chunk_count": {"integerValue": str(len(chunks))},
            "total_bytes": {"integerValue": str(len(package_bytes))},
            "sha256": {"stringValue": digest},
            "published_at": {"timestampValue": published_at},
        },
    )
    payload = {
        "version": {"stringValue": args.version},
        "sha256": {"stringValue": digest},
        "chunk_count": {"integerValue": str(len(chunks))},
        "total_bytes": {"integerValue": str(len(package_bytes))},
        "required": {"booleanValue": True},
        "published_at": {"timestampValue": published_at},
    }
    patch_document("app_config/windows_update", payload)


if __name__ == "__main__":
    main()
