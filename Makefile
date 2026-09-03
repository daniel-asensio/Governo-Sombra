.PHONY: install init seed ingest serve test digest descobrir

install:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

init:
	python -m governo_sombra init

seed:
	python -m governo_sombra seed

ingest:
	python -m governo_sombra ingest

serve:
	python -m governo_sombra serve

test:
	python -m pytest -q

digest:
	python -m governo_sombra digest

descobrir:
	python -m governo_sombra descobrir
