#!/usr/bin/env bash
# ==============================================================================
# BioDelta - Acceso directo de 1-Clic para macOS Finder
# ==============================================================================
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec bash "$DIR/iniciar.sh"
