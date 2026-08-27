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

REM Modo de login:
REM  - Si existe firebase-api-key.txt, se valida por internet contra Firebase
REM    (las cuentas se administran en el panel de Firebase). Ver README.
REM  - Si no, se usa el login local (usuarios en usuarios/usuarios.json,
REM    administrados con gestionar-usuarios.bat).
set "FIREBASE_API_KEY="
if exist firebase-api-key.txt set /p FIREBASE_API_KEY=<firebase-api-key.txt

if not "%FIREBASE_API_KEY%"=="" (
    echo Login: se validara por internet contra Firebase.
    goto arrancar
)

REM --- Login local: verificar que exista al menos un usuario ---
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

:arrancar
echo Iniciando el sistema... se abrira el navegador en unos segundos.
echo (Deja esta ventana abierta mientras uses el sistema. Cierrala para apagarlo.)
python app.py
pause
