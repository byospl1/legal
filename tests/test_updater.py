"""Pruebas aisladas del actualizador; solo usan la biblioteca estándar."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor import updater


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def make_package(version: str) -> bytes:
    content = {
        "app.py": b"print('ok')\n",
        "iniciar.bat": b"@echo off\n",
        "requirements.txt": b"Flask==3.1.3\n",
        "scripts/apply_update.ps1": b"Write-Host ok\n",
        "version.json": (json.dumps({"version": version}) + "\n").encode(),
    }
    files = sorted([*content, "update-files.json"])
    content["update-files.json"] = (
        json.dumps({"format": 1, "version": version, "files": files}) + "\n"
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in content.items():
            archive.writestr(name, body)
    return output.getvalue()


class UpdaterTests(unittest.TestCase):
    def test_version_actual(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "version.json").write_text('{"version":"abc-123"}', encoding="utf-8")
            self.assertEqual(updater.version_actual(root), "abc-123")
            (root / "version.json").write_text("{mal", encoding="utf-8")
            self.assertEqual(updater.version_actual(root), "desconocida")

    def test_buscar_actualizacion_pendiente(self):
        document = {
            "fields": {
                "version": {"stringValue": "new-123"},
                "sha256": {"stringValue": "a" * 64},
                "chunk_count": {"integerValue": "2"},
                "total_bytes": {"integerValue": "1234"},
                "required": {"booleanValue": True},
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "version.json").write_text('{"version":"old"}', encoding="utf-8")
            with mock.patch.object(
                updater.urllib.request,
                "urlopen",
                return_value=FakeResponse(json.dumps(document).encode()),
            ):
                info = updater.buscar_actualizacion("token", "project", base_dir=root)
        self.assertIsNotNone(info)
        self.assertEqual(info.version, "new-123")

    def test_firestore_sin_configuracion_no_bloquea(self):
        error = urllib.error.HTTPError("https://example", 403, "denied", {}, None)
        with mock.patch.object(updater.urllib.request, "urlopen", side_effect=error):
            self.assertIsNone(updater.buscar_actualizacion("token", "project"))

    def test_descarga_verificada_y_manifiesto(self):
        version = "commit-123"
        package = make_package(version)
        info = updater.UpdateInfo(
            version=version,
            sha256=hashlib.sha256(package).hexdigest(),
            chunk_count=1,
            total_bytes=len(package),
        )
        document = {
            "fields": {
                "data": {"bytesValue": base64.b64encode(package).decode("ascii")},
                "sha256": {"stringValue": hashlib.sha256(package).hexdigest()},
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(
                updater.urllib.request,
                "urlopen",
                return_value=FakeResponse(json.dumps(document).encode()),
            ) as mocked:
                payload = updater.descargar_y_preparar(
                    info, "token", project_id="project", base_dir=root
                )
            request = mocked.call_args.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer token")
            self.assertEqual(
                json.loads((payload / "version.json").read_text())["version"], version
            )
            self.assertTrue((payload / "scripts" / "apply_update.ps1").is_file())

    def test_sha_incorrecto_rechaza_paquete(self):
        package = make_package("v1")
        info = updater.UpdateInfo(
            version="v1",
            sha256="0" * 64,
            chunk_count=1,
            total_bytes=len(package),
        )
        document = {
            "fields": {
                "data": {"bytesValue": base64.b64encode(package).decode("ascii")},
                "sha256": {"stringValue": hashlib.sha256(package).hexdigest()},
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                updater.urllib.request,
                "urlopen",
                return_value=FakeResponse(json.dumps(document).encode()),
            ):
                with self.assertRaises(updater.UpdateError):
                    updater.descargar_y_preparar(
                        info, "token", project_id="project", base_dir=Path(directory)
                    )

    def test_fragmentos_se_reconstruyen_en_orden(self):
        version = "multi-1"
        package = make_package(version)
        cut = len(package) // 2
        chunks = [package[:cut], package[cut:]]
        responses = [
            FakeResponse(
                json.dumps(
                    {
                        "fields": {
                            "data": {"bytesValue": base64.b64encode(chunk).decode("ascii")},
                            "sha256": {"stringValue": hashlib.sha256(chunk).hexdigest()},
                        }
                    }
                ).encode()
            )
            for chunk in chunks
        ]
        info = updater.UpdateInfo(
            version,
            hashlib.sha256(package).hexdigest(),
            len(chunks),
            len(package),
        )
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                updater.urllib.request, "urlopen", side_effect=responses
            ) as mocked:
                payload = updater.descargar_y_preparar(
                    info, "token", project_id="project", base_dir=Path(directory)
                )
            self.assertTrue((payload / "app.py").is_file())
            first_url = mocked.call_args_list[0].args[0].full_url
            second_url = mocked.call_args_list[1].args[0].full_url
            self.assertTrue(first_url.endswith("/000000"))
            self.assertTrue(second_url.endswith("/000001"))

    def test_zip_traversal_rechazado(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "bad.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../escape.txt", "bad")
            with self.assertRaises(updater.UpdateError):
                updater._extract_verified_zip(package, root / "payload", "v1")

    def test_datos_y_configuracion_local_son_inmutables(self):
        protected = [
            "case_store/cliente.json",
            "output/documento.pdf",
            "firmas/abogados/firma.png",
            "venv/Scripts/python.exe",
            "firebase-api-key.txt",
            ".env",
        ]
        for path in protected:
            with self.subTest(path=path):
                with self.assertRaises(updater.UpdateError):
                    updater._assert_managed_path(path)


if __name__ == "__main__":
    unittest.main()
