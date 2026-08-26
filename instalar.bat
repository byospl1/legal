@echo off
setlocal

echo ============================================
echo  Instalando Sistema de Tabs EOIR
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo No se encontro Python en el PATH.
    echo Instala Python 3.11 o superior desde https://www.python.org/downloads/
    echo IMPORTANTE: marca la casilla "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

if not exist venv (
    echo Creando entorno virtual...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Instalando dependencias de Python...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

echo.
where soffice >nul 2>nul
if errorlevel 1 (
    echo ADVERTENCIA: no se encontro LibreOffice ^(soffice^) en el PATH.
    echo   Se necesita para convertir los documentos a PDF de verificacion.
    echo   Descargalo de https://www.libreoffice.org/download/download/
    echo   e instalalo con las opciones por defecto ^(agrega soffice.exe al PATH automaticamente
    echo   o revisa la ruta tipica: C:\Program Files\LibreOffice\program^).
)

where pdftoppm >nul 2>nul
if errorlevel 1 (
    echo ADVERTENCIA: no se encontro Poppler ^(pdftoppm^) en el PATH.
    echo   Se necesita para generar las imagenes de verificacion pagina por pagina.
    echo   Descarga Poppler for Windows y agrega su carpeta "bin" al PATH.
    echo   Ver README.md para el enlace y los pasos exactos.
)

echo.
echo ============================================
echo  Instalacion terminada.
echo  Usa iniciar.bat para abrir el sistema.
echo ============================================
pause
