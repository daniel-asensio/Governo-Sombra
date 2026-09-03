"""Recolha periódica com APScheduler (activada com GS_SCHEDULER=1)."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import definicoes
from .db import sessao

log = logging.getLogger("governo_sombra.scheduler")


def _tarefa_ingest():
    from .ingest import recolher_tudo

    s = sessao()
    try:
        ex = recolher_tudo(s, intervalo_min=definicoes.ingest_interval_min)
        log.info("recolha periódica: %d fontes, %d novos, %d erros", ex.fontes, ex.novos, ex.erros)
    finally:
        s.close()


def _tarefa_digest():
    from .digest import gerar_digest, enviar_email

    s = sessao()
    try:
        texto, caminho = gerar_digest(s)
        log.info("digest guardado em %s", caminho)
        enviar_email("Governo Sombra: resumo diário", texto)
    finally:
        s.close()


def iniciar() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="Europe/Lisbon")
    sched.add_job(_tarefa_ingest, "interval", minutes=definicoes.ingest_interval_min, id="ingest", max_instances=1, coalesce=True)
    sched.add_job(_tarefa_digest, "cron", hour=7, minute=30, id="digest")
    sched.start()
    log.info("agendador iniciado: recolha a cada %d min, digest às 07:30", definicoes.ingest_interval_min)
    return sched
