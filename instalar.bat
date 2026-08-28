@echo off
setlocal EnableExtensions

echo ============================================
echo  Instalando Sistema de Tabs EOIR
echo ============================================
echo.

call :asegurar_python
if errorlevel 1 goto :fallo
call :asegurar_libreoffice
if errorlevel 1 goto :fallo
call :asegurar_poppler
if errorlevel 1 goto :fallo

if not exist venv (
    echo Creando entorno virtual...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 goto :fallo
)
call venv\Scripts\activate.bat
if errorlevel 1 goto :fallo

echo Instalando dependencias de Python...
python -m pip install --upgrade pip
if errorlevel 1 goto :fallo
python -m pip install -r requirements.txt
if errorlevel 1 goto :fallo

echo.
echo ============================================
echo  Instalacion terminada y verificada.
echo  Usa iniciar.bat para abrir el sistema.
echo ============================================
goto :fin

:asegurar_python
set "PYTHON_CMD="
python --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if defined PYTHON_CMD exit /b 0
echo Python no esta instalado. Intentando instalarlo automaticamente...
call :winget_instalar "Python.Python.3.13" "Python 3"
if errorlevel 1 exit /b 1
py -3 --version >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    exit /b 0
)
echo ERROR: Python se instalo pero no quedo disponible en esta sesion.
echo Cierra esta ventana, abre instalar.bat otra vez y vuelve a intentarlo.
exit /b 1

:asegurar_libreoffice
call :soffice_disponible
if not errorlevel 1 exit /b 0
echo LibreOffice no esta instalado. Intentando instalarlo automaticamente...
call :winget_instalar "TheDocumentFoundation.LibreOffice" "LibreOffice"
if errorlevel 1 exit /b 1
call :soffice_disponible
if not errorlevel 1 exit /b 0
echo ERROR: no se pudo localizar soffice.exe despues de instalar LibreOffice.
exit /b 1

:asegurar_poppler
call :poppler_disponible
if not errorlevel 1 exit /b 0
echo Poppler no esta instalado. Intentando instalarlo automaticamente...
call :winget_instalar "oschwartz10612.Poppler" "Poppler"
if errorlevel 1 exit /b 1
call :poppler_disponible
if not errorlevel 1 exit /b 0
echo ERROR: no se pudo localizar pdftoppm.exe despues de instalar Poppler.
exit /b 1

:winget_instalar
where winget >nul 2>nul
if errorlevel 1 (
    echo ERROR: winget no esta disponible para instalar %~2 automaticamente.
    echo Actualiza App Installer desde Microsoft Store y vuelve a ejecutar este archivo.
    exit /b 1
)
echo Instalando %~2...
winget install --id %~1 --exact --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo ERROR: fallo la instalacion automatica de %~2.
    exit /b 1
)
exit /b 0

:soffice_disponible
where soffice >nul 2>nul
if not errorlevel 1 exit /b 0
for %%P in ("%ProgramFiles%\LibreOffice\program\soffice.exe" "%ProgramW6432%\LibreOffice\program\soffice.exe" "%ProgramFiles(x86)%\LibreOffice\program\soffice.exe") do if exist "%%~P" exit /b 0
exit /b 1

:poppler_disponible
where pdftoppm >nul 2>nul
if not errorlevel 1 exit /b 0
for /d %%P in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\oschwartz10612.Poppler*") do if exist "%%~P\Library\bin\pdftoppm.exe" exit /b 0
for /d %%P in ("C:\poppler*") do (
    if exist "%%~P\Library\bin\pdftoppm.exe" exit /b 0
    if exist "%%~P\bin\pdftoppm.exe" exit /b 0
)
exit /b 1

:fallo
echo.
echo La instalacion no termino. Revisa el mensaje anterior y vuelve a ejecutar instalar.bat.
pause
exit /b 1

:fin
pause
exit /b 0
