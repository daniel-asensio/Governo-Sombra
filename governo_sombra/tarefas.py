"""Trabalho em segundo plano num processo separado.

Recolha, descoberta e diagnóstico demoram minutos e consomem CPU. Se corressem
dentro do servidor web, as páginas ficavam lentas (Python só executa uma
thread de cada vez). Cada tarefa corre num processo próprio e regista o seu
estado na tabela `tarefas`, que a interface lê.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Tarefa, agora

MINUTOS_ATE_CONSIDERAR_MORTA = 45


def tarefa_activa(s: Session, tipo: str, alvo: str | None = None) -> Tarefa | None:
    limite = agora() - timedelta(minutes=MINUTOS_ATE_CONSIDERAR_MORTA)
    q = select(Tarefa).where(Tarefa.tipo == tipo, Tarefa.estado == "a_correr", Tarefa.inicio >= limite)
    if alvo is not None:
        q = q.where(Tarefa.alvo == alvo)
    return s.scalar(q.order_by(Tarefa.id.desc()).limit(1))


def ultima_tarefa(s: Session, tipo: str, alvo: str | None = None) -> Tarefa | None:
    q = select(Tarefa).where(Tarefa.tipo == tipo)
    if alvo is not None:
        q = q.where(Tarefa.alvo == alvo)
    return s.scalar(q.order_by(Tarefa.id.desc()).limit(1))


def lancar(s: Session, tipo: str, argv: list[str], alvo: str | None = None) -> Tarefa | None:
    """Arranca `python -m governo_sombra <argv>` em segundo plano, se não houver já uma igual a correr."""
    if tarefa_activa(s, tipo, alvo) is not None:
        return None
    t = Tarefa(tipo=tipo, alvo=alvo, estado="a_correr", inicio=agora(), detalhes={})
    s.add(t)
    s.commit()
    from .config import RAIZ, definicoes

    cmd = [sys.executable, "-m", "governo_sombra", *argv, "--tarefa", str(t.id)]
    env = {**os.environ, "GS_DATABASE_URL": definicoes.database_url}
    subprocess.Popen(cmd, cwd=str(RAIZ), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return t


def iniciar_registo(s: Session, tarefa_id: int | None, tipo: str, alvo: str | None = None) -> Tarefa | None:
    """Usado pelos comandos da CLI: devolve a tarefa a actualizar (cria uma se não vier id)."""
    if tarefa_id is None:
        return None
    t = s.get(Tarefa, tarefa_id)
    if t is None:
        t = Tarefa(id=tarefa_id, tipo=tipo, alvo=alvo, estado="a_correr", inicio=agora(), detalhes={})
        s.add(t)
        s.commit()
    return t


def terminar(s: Session, t: Tarefa | None, *, erro: str | None = None, **detalhes) -> None:
    if t is None:
        return
    t.estado = "erro" if erro else "ok"
    t.fim = agora()
    t.detalhes = {**(t.detalhes or {}), **detalhes, **({"erro": erro[:500]} if erro else {})}
    s.commit()
