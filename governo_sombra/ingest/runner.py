from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..classify.rules import Classificador
from ..models import Execucao, Fonte, Item, agora
from .base import ErroFonte, ItemBruto, obter
from .registry import adaptador_para

log = logging.getLogger("governo_sombra.ingest")


def _fixture_para(fonte: Fonte, dir_fixtures: Path | None) -> Path | None:
    if dir_fixtures is None:
        return None
    for ext in ("xml", "html", "json", "txt"):
        p = dir_fixtures / f"{fonte.id}.{ext}"
        if p.exists():
            return p
    return None


def guardar_itens(s: Session, fonte: Fonte, brutos: list[ItemBruto], classificador: Classificador) -> int:
    existentes = set(s.scalars(select(Item.guid).where(Item.fonte_id == fonte.id)))
    novos = 0
    ministerio = fonte.entidade.ministerio()
    for b in brutos:
        chave = b.chave()
        if chave in existentes:
            continue
        existentes.add(chave)
        item = Item(
            fonte_id=fonte.id,
            entidade_id=fonte.entidade_id,
            ministerio_id=ministerio.id if ministerio else None,
            guid=chave,
            url=b.url,
            titulo=b.titulo[:600],
            resumo=b.resumo,
            conteudo=b.conteudo,
            publicado_em=b.publicado_em,
            recolhido_em=agora(),
            extra=b.extra or None,
        )
        classificador.classificar(item, fonte=fonte, tipo_sugerido=b.tipo_documento)
        s.add(item)
        novos += 1
    return novos


def recolher_fonte(s: Session, fonte: Fonte, *, dir_fixtures: Path | None = None, classificador: Classificador | None = None) -> tuple[int, str | None]:
    """Recolhe uma fonte. Devolve (novos, erro)."""
    classificador = classificador or Classificador.carregar(s)
    fonte.ultima_recolha = agora()
    try:
        adaptador = adaptador_para(fonte.tipo)
        fixture = _fixture_para(fonte, dir_fixtures)
        corpo = obter(fonte.url, fixture=fixture) if fixture else None
        brutos = adaptador.recolher(fonte.url, fonte.config or {}, corpo=corpo)
        novos = guardar_itens(s, fonte, brutos, classificador)
        fonte.ultimo_sucesso = agora()
        fonte.ultimo_erro = None
        fonte.total_itens = (fonte.total_itens or 0) + novos
        if novos or brutos:
            fonte.verificada = True
        s.commit()
        log.info("%s: %d novos (%d lidos)", fonte.id, novos, len(brutos))
        return novos, None
    except (ErroFonte, ValueError, OSError) as e:
        s.rollback()
        fonte.ultima_recolha = agora()
        fonte.ultimo_erro = str(e)[:2000]
        s.commit()
        log.warning("%s: erro %s", fonte.id, e)
        return 0, str(e)


def recolher_tudo(s: Session, *, apenas: list[str] | None = None, dir_fixtures: Path | None = None, intervalo_min: int | None = None) -> Execucao:
    q = select(Fonte).where(Fonte.activa.is_(True)).order_by(Fonte.prioridade.desc())
    if apenas:
        q = q.where(Fonte.id.in_(apenas))
    fontes = list(s.scalars(q))
    if intervalo_min:
        limite = agora() - timedelta(minutes=intervalo_min)
        fontes = [f for f in fontes if f.ultima_recolha is None or f.ultima_recolha < limite]
    execucao = Execucao(inicio=agora(), fontes=len(fontes), detalhes={})
    s.add(execucao)
    s.commit()
    classificador = Classificador.carregar(s)
    detalhes = {}
    for f in fontes:
        novos, erro = recolher_fonte(s, f, dir_fixtures=dir_fixtures, classificador=classificador)
        execucao.novos += novos
        if erro:
            execucao.erros += 1
        detalhes[f.id] = {"novos": novos, "erro": erro}
    execucao.fim = agora()
    execucao.detalhes = detalhes
    s.commit()
    return execucao
