#!/usr/bin/env bash
# ==============================================================================
# BioDelta - Lanzador 1-Clic para Linux y macOS
# Comprueba Python, crea el entorno virtual si es necesario y arranca el servidor.
# ==============================================================================

set -e

# Situarse en el directorio del proyecto
cd "$(dirname "$0")"

echo "============================================================"
echo "  🚀 Iniciando BioDelta..."
echo "============================================================"

# Comprobar si existe python3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] No se encontró Python 3 en tu sistema."
    echo "Por favor, instala Python 3 desde https://www.python.org/"
    read -p "Presiona Enter para salir..."
    exit 1
fi

# Crear entorno virtual si no existe
if [ ! -d ".venv" ]; then
    echo "⚙️ Configurando el entorno local por primera vez..."
    python3 -m venv .venv
    echo "📦 Instalando dependencias de BioDelta..."
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
    echo "✅ Entorno configurado correctamente."
fi

# Arrancar el servidor local
echo "🌐 Abriendo BioDelta en tu navegador (http://localhost:8000)..."
.venv/bin/python app.py
