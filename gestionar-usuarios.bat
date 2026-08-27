@echo off
cd /d "%~dp0"

if not exist venv (
    echo No se encontro el entorno virtual. Corre instalar.bat primero.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:menu
cls
echo ==================================================
echo    Gestion de usuarios - Control de accesos
echo ==================================================
echo.
echo    1. Crear un usuario nuevo
echo    2. Ver la lista de usuarios
echo    3. Cambiar la contrasena de un usuario
echo    4. Borrar un usuario
echo    5. Salir
echo.
set "op="
set /p "op=Elige una opcion (1-5): "

if "%op%"=="1" goto crear
if "%op%"=="2" goto listar
if "%op%"=="3" goto pass
if "%op%"=="4" goto borrar
if "%op%"=="5" exit /b 0
goto menu

:crear
echo.
echo --- Crear usuario nuevo ---
echo (Evita comillas y el simbolo %% en la contrasena.)
set "u="
set "n="
set "p="
set /p "u=Usuario (con lo que iniciara sesion): "
set /p "n=Nombre completo (como se mostrara): "
set /p "p=Contrasena: "
python scripts\manage_users.py create "%u%" "%p%" "%n%"
echo.
pause
goto menu

:listar
echo.
echo --- Usuarios registrados ---
python scripts\manage_users.py list
echo.
pause
goto menu

:pass
echo.
echo --- Cambiar contrasena ---
set "u="
set "p="
set /p "u=Usuario: "
set /p "p=Nueva contrasena: "
python scripts\manage_users.py set-password "%u%" "%p%"
echo.
pause
goto menu

:borrar
echo.
echo --- Borrar usuario ---
set "u="
set /p "u=Usuario a borrar: "
python scripts\manage_users.py delete "%u%"
echo.
pause
goto menu
