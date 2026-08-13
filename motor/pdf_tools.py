"""Conversión a PDF y rasterizado (Poppler) para el paso de verificación
visual (sección 5.2, paso 9 de la spec): nunca dar un documento por bueno
solo porque pasó validate.py.

Motor de conversión: en Windows con Microsoft Word instalado, se usa Word
mismo (vía COM) — es el único motor que garantiza que el PDF se vea
IDÉNTICO al .docx, sin sustitución de fuentes (LibreOffice no siempre
resuelve igual las fuentes de tema del .dotx original, y eso desalinea
texto). Si Word no está disponible, cae a LibreOffice headless.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


class PdfToolsError(Exception):
    pass


class WordNotAvailableError(PdfToolsError):
    """Word/pywin32 no está disponible en esta máquina — se debe intentar
    con LibreOffice en su lugar, no es un error real de conversión."""


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


def _convert_with_word(docx_path: Path, out_dir: Path) -> Path:
    """Convierte usando Microsoft Word (COM). Fidelidad exacta — es el
    mismo motor de renderizado que ves al abrir el archivo en Word."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise WordNotAvailableError(f"pywin32 no está instalado: {e}")

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / (docx_path.stem + ".pdf")

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        try:
            word = win32com.client.DispatchEx("Word.Application")
        except Exception as e:  # noqa: BLE001
            raise WordNotAvailableError(f"No se pudo iniciar Microsoft Word (¿está instalado?): {e}")

        word.Visible = False
        word.DisplayAlerts = 0
        try:
            doc = word.Documents.Open(
                str(docx_path.resolve()),
                ReadOnly=True,
                AddToRecentFiles=False,
                ConfirmConversions=False,
            )
            wd_format_pdf = 17
            doc.SaveAs(str(pdf_path.resolve()), FileFormat=wd_format_pdf)
        except WordNotAvailableError:
            raise
        except Exception as e:  # noqa: BLE001
            raise PdfToolsError(f"Word abrió pero falló al convertir '{docx_path.name}' a PDF: {e}")
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:  # noqa: BLE001
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:  # noqa: BLE001
                pass
        pythoncom.CoUninitialize()

    if not pdf_path.exists():
        raise PdfToolsError("Word no generó el archivo PDF esperado.")
    return pdf_path


def _convert_with_libreoffice(docx_path: Path, out_dir: Path) -> Path:
    soffice = _find_soffice()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Usa un perfil de usuario de LibreOffice aislado y temporal en cada
    # conversión. Sin esto, si ya hay otra ventana/instancia de LibreOffice
    # abierta en la computadora (incluso minimizada, o solo el ícono en la
    # bandeja del sistema), soffice --headless intenta hablar con esa
    # instancia compartida y puede quedarse esperando indefinidamente en
    # vez de convertir y salir.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="loprofile_") as profile_dir:
        profile_uri = Path(profile_dir).as_uri()
        try:
            result = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    "--nodefault",
                    "--nofirststartwizard",
                    f"-env:UserInstallation={profile_uri}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out_dir),
                    str(docx_path),
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired as e:
            raise PdfToolsError(
                "La conversión a PDF tardó más de 90 segundos y se canceló. Esto casi "
                "siempre pasa porque hay otra ventana de LibreOffice abierta en la "
                "computadora (revisa también el ícono de LibreOffice junto al reloj, "
                "en la bandeja del sistema, y ciérralo) — ciérrala e intenta de nuevo. "
                f"Detalle: {e}"
            )

    pdf_path = out_dir / (docx_path.stem + ".pdf")
    if result.returncode != 0 or not pdf_path.exists():
        raise PdfToolsError(f"Fallo al convertir a PDF: {result.stdout}\n{result.stderr}")
    return pdf_path


def convert_to_pdf(docx_path: Path, out_dir: Path) -> Path:
    """En Windows con Word instalado, usa Word (fidelidad exacta, sin
    sustitución de fuentes). Si Word no está disponible, cae a LibreOffice."""
    if platform.system() == "Windows":
        try:
            return _convert_with_word(docx_path, out_dir)
        except WordNotAvailableError:
            pass  # sin Word instalado/registrado — se intenta con LibreOffice
    return _convert_with_libreoffice(docx_path, out_dir)


def rasterize(pdf_path: Path, out_dir: Path, dpi: int = 100) -> list[Path]:
    pdftoppm = _find_pdftoppm()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / pdf_path.stem
    try:
        result = subprocess.run(
            [pdftoppm, "-jpeg", "-r", str(dpi), str(pdf_path), str(prefix)],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired as e:
        raise PdfToolsError(f"pdftoppm tardó más de 90 segundos y se canceló. Detalle: {e}")
    if result.returncode != 0:
        raise PdfToolsError(f"Fallo al generar las imágenes de verificación: {result.stdout}\n{result.stderr}")
    return sorted(out_dir.glob(f"{pdf_path.stem}-*.jpg"))
