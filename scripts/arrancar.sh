#!/bin/sh
# Arranque em contentor: prepara a base de dados, carrega os dados e serve.
set -e
python -m governo_sombra init
python -m governo_sombra seed
exec python -m governo_sombra serve --host "${GS_HOST:-0.0.0.0}"
