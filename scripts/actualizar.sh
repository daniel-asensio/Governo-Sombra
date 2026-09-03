#!/usr/bin/env bash
# Actualiza a aplicação no servidor para a versão mais recente do GitHub.
#   bash ~/governo-sombra/scripts/actualizar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# Memória de reserva em disco: evita que a máquina fique a arrastar-se quando a RAM enche.
if [ ! -f /swapfile ] && [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1; then
  echo "-- a criar 2 GB de swap"
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

git pull --ff-only
if [ -f .env ] && grep -q '^GS_DOMINIO=.\+' .env; then
  sudo docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
else
  sudo docker compose up -d --build
fi
echo "Actualizado."
