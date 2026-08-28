#!/usr/bin/env bash
# Flujo Cero — instalacion y primera corrida. macOS / Linux.
#
#   bash ~/Downloads/setup.sh
#
# (El repositorio es privado: `curl | bash` desde raw.githubusercontent responde 404
#  sin autenticacion, asi que el archivo se guarda a mano la primera vez.)
#
# Equivalente a scripts/setup.ps1. NO contiene credenciales: el .env se llena aparte,
# porque este archivo esta versionado y los secretos no entran a un archivo versionado.

set -euo pipefail

REPO="https://github.com/acabreirav/PropInvest.git"
RAMA="claude/flujo-cero-subsidio-0j4hc6"
CARPETA="${HOME}/PropInvest"

titulo() { printf '\n\033[36m=== %s ===\033[0m\n' "$1"; }
ok()     { printf '\033[32m  OK  %s\033[0m\n' "$1"; }
aviso()  { printf '\033[33m  !!  %s\033[0m\n' "$1"; }
existe() { command -v "$1" >/dev/null 2>&1; }

titulo "1/5  Herramientas"
existe git || { aviso "git no esta: instalalo con 'xcode-select --install' (macOS) o tu gestor de paquetes"; exit 1; }
ok "git presente"

if existe uv; then
  ok "uv ya esta instalado"
else
  aviso "uv no esta. Instalando..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
  existe uv || { aviso "uv instalado pero no visible. Abre una terminal nueva y repite."; exit 1; }
  ok "uv instalado"
fi

titulo "2/5  Repositorio"
if [ -d "${CARPETA}/.git" ]; then
  cd "${CARPETA}"
  ok "ya existe en ${CARPETA} — actualizando"
  git fetch origin "${RAMA}"
  git checkout "${RAMA}"
  git pull origin "${RAMA}"
else
  git clone --branch "${RAMA}" "${REPO}" "${CARPETA}"
  cd "${CARPETA}"
fi
ok "rama $(git rev-parse --abbrev-ref HEAD), commit $(git rev-parse --short HEAD)"

titulo "3/5  Dependencias de Python"
uv sync
ok "instaladas"

titulo "4/5  Credenciales"
if [ -f .env ]; then
  ok ".env ya existe (no se toca)"
else
  cp .env.example .env
  aviso ".env creado desde la plantilla, pero VACIO de credenciales."
  aviso "Pega el bloque que te di en el chat y vuelve a correr este script."
fi
FALTAN=$(grep -E '^(MELI_CLIENT_ID|MELI_CLIENT_SECRET|MELI_REFRESH_TOKEN|CMF_APIKEY)=[[:space:]]*$' .env | cut -d= -f1 | paste -sd, - || true)
if [ -n "${FALTAN}" ]; then aviso "faltan credenciales: ${FALTAN}"; else ok "las cuatro credenciales estan puestas"; fi

titulo "5/5  Verificacion"
uv run pytest -q && ok "tests en verde"
uv run python -m flujocero.cli gates && ok "gates en verde"
uv run python -m flujocero.cli demo

titulo "Listo"
echo "Carpeta: ${CARPETA}"
if [ -n "${FALTAN}" ]; then
  aviso "SIGUIENTE: llena el .env y vuelve a correr este script."
else
  printf '\033[32mSIGUIENTE:\033[0m\n\n    cd %s\n    uv run python -m flujocero.cli ingest --desde 2024-01 --hasta 2026-08\n\nCopia toda la salida y pegamela en el chat.\n' "${CARPETA}"
fi
