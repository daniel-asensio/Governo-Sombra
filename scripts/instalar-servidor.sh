#!/usr/bin/env bash
# Instala e arranca o Governo Sombra num servidor Linux acabado de criar
# (Ubuntu/Debian; testado com a VM "Always Free" da Oracle Cloud).
#
# Uso, já dentro do servidor (ssh ou "SSH no browser" do Google Cloud):
#   curl -fsSL https://raw.githubusercontent.com/daniel-asensio/Governo-Sombra/main/scripts/instalar-servidor.sh | bash
# ou, se já tiveres o código: bash scripts/instalar-servidor.sh
#
# Pergunta o nome para HTTPS (sugere um automático baseado no IP, via sslip.io)
# e a senha, instala o Docker, descarrega o código e arranca a aplicação com
# certificado automático (Caddy). No Google Cloud, marca "Permitir tráfego HTTP
# e HTTPS" ao criar a VM; noutros serviços abre as portas 80 e 443.
set -euo pipefail
exec < /dev/tty

RAMO="${GS_RAMO:-main}"
PASTA="$HOME/governo-sombra"

echo "== Governo Sombra: instalação no servidor =="
IP_PUBLICO="$(curl -s --max-time 5 ifconfig.me 2>/dev/null || curl -s --max-time 5 api.ipify.org 2>/dev/null || true)"
SUGESTAO=""
[ -n "$IP_PUBLICO" ] && SUGESTAO="${IP_PUBLICO//./-}.sslip.io"
echo "Para HTTPS é preciso um nome. Sem domínio próprio, o nome automático ${SUGESTAO:-<ip>.sslip.io} serve."
read -rp "Nome/domínio para HTTPS [${SUGESTAO:-vazio = só HTTP na porta 8000}]: " DOMINIO
DOMINIO="${DOMINIO:-$SUGESTAO}"
while true; do
  read -rsp "Senha de acesso à aplicação: " SENHA; echo
  [ "${#SENHA}" -ge 6 ] && break
  echo "A senha deve ter pelo menos 6 caracteres."
done

if ! command -v docker >/dev/null 2>&1; then
  echo "-- a instalar o Docker"
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
fi

if [ ! -d "$PASTA/.git" ]; then
  echo "-- a descarregar o código"
  sudo apt-get update -qq && sudo apt-get install -y -qq git >/dev/null
  git clone -b "$RAMO" https://github.com/daniel-asensio/Governo-Sombra.git "$PASTA"
fi
cd "$PASTA"

cat > .env <<ENV
GS_PASSWORD=$SENHA
GS_DOMINIO=$DOMINIO
ENV
chmod 600 .env

# Abrir as portas na firewall do próprio sistema (a da cloud abre-se na consola).
if command -v ufw >/dev/null 2>&1; then sudo ufw allow 80/tcp >/dev/null; sudo ufw allow 443/tcp >/dev/null; sudo ufw allow 8000/tcp >/dev/null || true; fi
if command -v iptables >/dev/null 2>&1; then
  for p in 80 443 8000; do sudo iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p tcp --dport "$p" -j ACCEPT; done
  sudo netfilter-persistent save >/dev/null 2>&1 || true
fi

if [ -n "$DOMINIO" ]; then
  sudo docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
  echo; echo "Pronto. Abre https://$DOMINIO (o certificado pode demorar um minuto na primeira vez)."
else
  sudo docker compose up -d --build
  echo; echo "Pronto. Abre http://$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):8000"
fi
echo "Actualizar mais tarde: cd $PASTA && git pull && sudo docker compose up -d --build"
