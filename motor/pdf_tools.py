"""Conversión a PDF (LibreOffice headless) y rasterizado (Poppler) para el
paso de verificación visual obligatorio (sección 5.2, paso 9 de la spec):
nunca dar un documento por bueno solo porque pasó validate.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class PdfToolsError(Exception):
    pass


def _program_files_dirs() -> list[Path]:
    dirs = []
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        val = os.environ.get(env_var)
        if val:
            dirs.append(Path(val))
    return dirs


def _find_soffice() -> str:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path

    # Instalador por defecto de LibreOffice en Windows no siempre agrega
    # soffice.exe al PATH — buscamos en las ubicaciones típicas.
    for base in _program_files_dirs():
        candidate = base / "LibreOffice" / "program" / "soffice.exe"
        if candidate.is_file():
            return str(candidate)
    for candidate in (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ):
        if Path(candidate).is_file():
            return candidate

    raise PdfToolsError(
        "No se encontró LibreOffice (soffice) ni en el PATH ni en las rutas "
        "típicas de instalación. Instálalo desde "
        "https://www.libreoffice.org/download/download/ — es requerido para "
        "convertir los .docx generados a PDF de verificación. Si ya lo "
        "instalaste y sigue sin encontrarse, revisa que exista "
        r"C:\Program Files\LibreOffice\program\soffice.exe"
        " (o la ruta equivalente donde lo instalaste)."
    )


def _find_pdftoppm() -> str:
    for name in ("pdftoppm",):
        path = shutil.which(name)
        if path:
            return path

    # Poppler for Windows se distribuye como .zip sin instalador; buscamos
    # en las ubicaciones donde la mayoría de los tutoriales sugieren
    # descomprimirlo.
    for base in [Path("C:/"), *_program_files_dirs()]:
        if not base.exists():
            continue
        for candidate in base.glob("poppler*/Library/bin/pdftoppm.exe"):
            if candidate.is_file():
                return str(candidate)
        for candidate in base.glob("poppler*/bin/pdftoppm.exe"):
            if candidate.is_file():
                return str(candidate)

    raise PdfToolsError(
        "No se encontró pdftoppm (Poppler) ni en el PATH ni en las rutas "
        "típicas. Descarga Poppler for Windows "
        "(https://github.com/oschwartz10612/poppler-windows/releases), "
        r"descomprímelo (ej. en C:\poppler) y agrega la carpeta "
        r"...\Library\bin de adentro al PATH del sistema — o simplemente "
        r"descomprímelo directo en C:\ (queda como C:\poppler-XX.XX.X\...) "
        "para que este programa lo encuentre solo."
    )


def convert_to_pdf(docx_path: Path, out_dir: Path) -> Path:
    soffice = _find_soffice()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [soffice, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    pdf_path = out_dir / (docx_path.stem + ".pdf")
    if result.returncode != 0 or not pdf_path.exists():
        raise PdfToolsError(f"Fallo al convertir a PDF: {result.stdout}\n{result.stderr}")
    return pdf_path


def rasterize(pdf_path: Path, out_dir: Path, dpi: int = 100) -> list[Path]:
    pdftoppm = _find_pdftoppm()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / pdf_path.stem
    subprocess.run(
        [pdftoppm, "-jpeg", "-r", str(dpi), str(pdf_path), str(prefix)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return sorted(out_dir.glob(f"{pdf_path.stem}-*.jpg"))
