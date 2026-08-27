@echo off
cd /d "%~dp0"

if not exist venv (
    echo No se encontro el entorno virtual. Corre instalar.bat primero.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

REM Control de accesos: el login es OBLIGATORIO para entrar al sistema.
set EOIR_LOGIN=1

REM Si no hay ningun usuario creado todavia, nadie podria iniciar sesion:
REM avisar y mandar a crear el primero antes de arrancar.
set "NUSERS=1"
for /f %%c in ('python -c "from motor import auth; print(len(auth.list_users()))"') do set "NUSERS=%%c"
if "%NUSERS%"=="0" (
    echo.
    echo No hay ningun usuario creado todavia, asi que nadie podria entrar.
    echo Primero crea al menos un usuario con:  gestionar-usuarios.bat
    echo.
    pause
    exit /b 1
)

echo Iniciando el sistema... se abrira el navegador en unos segundos.
echo (Deja esta ventana abierta mientras uses el sistema. Cierrala para apagarlo.)
python app.py
pause
