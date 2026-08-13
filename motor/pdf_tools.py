"""Conversión a PDF (LibreOffice headless) y rasterizado (Poppler) para el
paso de verificación visual obligatorio (sección 5.2, paso 9 de la spec):
nunca dar un documento por bueno solo porque pasó validate.py.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PdfToolsError(Exception):
    pass


def _find_soffice() -> str:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    raise PdfToolsError(
        "No se encontró LibreOffice (soffice) en el PATH. Instálalo desde "
        "https://www.libreoffice.org/download/download/ — es requerido para "
        "convertir los .docx generados a PDF de verificación."
    )


def _find_pdftoppm() -> str:
    path = shutil.which("pdftoppm")
    if not path:
        raise PdfToolsError(
            "No se encontró pdftoppm (Poppler) en el PATH. En Windows: instala "
            "Poppler for Windows y agrega su carpeta bin al PATH."
        )
    return path


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
