@echo off
REM ==============================================================================
REM BioDelta - Lanzador 1-Clic para Windows
REM Comprueba Python, crea el entorno virtual si es necesario y arranca el servidor.
REM ==============================================================================

cd /d "%~dp0"
title BioDelta - Monitor de Salud

echo ============================================================
echo   Iniciando BioDelta...
echo ============================================================

REM Comprobar si existe python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] No se encontro Python en tu sistema.
    echo Por favor, instala Python 3 desde https://www.python.org/
    pause
    exit /b 1
)

REM Crear entorno virtual si no existe
if not exist ".venv" (
    echo Configurando el entorno local por primera vez...
    python -m venv .venv
    echo Instalando dependencias de BioDelta...
    call .venv\Scripts\pip install --upgrade pip
    call .venv\Scripts\pip install -r requirements.txt
    echo Entorno configurado correctamente.
)

echo Abriendo BioDelta en tu navegador (http://localhost:8000)...
call .venv\Scripts\python app.py
if %errorlevel% neq 0 (
    pause
)
