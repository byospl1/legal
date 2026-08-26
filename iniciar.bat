@echo off
cd /d "%~dp0"

if not exist venv (
    echo No se encontro el entorno virtual. Corre instalar.bat primero.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
echo Iniciando el sistema... se abrira el navegador en unos segundos.
echo (Deja esta ventana abierta mientras uses el sistema. Cierrala para apagarlo.)
python app.py
pause
