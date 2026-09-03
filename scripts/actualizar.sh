#!/usr/bin/env bash
# Actualiza a aplicação no servidor para a versão mais recente do GitHub.
#   bash ~/governo-sombra/scripts/actualizar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
if [ -f .env ] && grep -q '^GS_DOMINIO=.\+' .env; then
  sudo docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
else
  sudo docker compose up -d --build
fi
echo "Actualizado."
