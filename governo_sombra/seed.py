"""Carrega os ficheiros YAML de data/ para a base de dados (idempotente)."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import DIR_DADOS
from .models import Alerta, EventoCalendario, Entidade, Fonte, MinistroSombra, Perfil


def _ler(nome: str, dir_dados: Path) -> dict:
    with open(dir_dados / nome, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def carregar_entidades(s: Session, dir_dados: Path = DIR_DADOS) -> int:
    dados = _ler("estado.yaml", dir_dados)
    n = 0

    def inserir(lista: list[dict], parent_id: str | None):
        nonlocal n
        for ordem, e in enumerate(lista):
            ent = s.get(Entidade, e["id"]) or Entidade(id=e["id"])
            ent.nome = e["nome"]
            ent.sigla = e.get("sigla")
            ent.tipo = e.get("tipo", "outro")
            ent.url = e.get("url")
            ent.titular = e.get("titular")
            ent.descricao = e.get("descricao")
            ent.areas = e.get("areas")
            ent.parent_id = parent_id
            ent.ordem = ordem
            ent.activa = e.get("activa", True)
            s.add(ent)
            n += 1
            inserir(e.get("filhos", []), e["id"])

    inserir(dados.get("entidades", []), None)
    s.flush()
    return n


def carregar_fontes(s: Session, dir_dados: Path = DIR_DADOS) -> int:
    dados = _ler("fontes.yaml", dir_dados)
    n = 0
    for f in dados.get("fontes", []):
        fonte = s.get(Fonte, f["id"]) or Fonte(id=f["id"])
        fonte.entidade_id = f["entidade"]
        fonte.nome = f["nome"]
        fonte.tipo = f["tipo"]
        fonte.url = f["url"]
        fonte.config = f.get("config") or {}
        fonte.verificada = bool(f.get("verificada", False))
        fonte.prioridade = int(f.get("prioridade", 5))
        if fonte.activa is None:
            fonte.activa = f.get("activa", True)
        elif f.get("activa") is False and not fonte.ultimo_sucesso:
            # O YAML diz que o URL está por confirmar e esta instalação nunca conseguiu lê-lo.
            fonte.activa = False
        if f.get("nota"):
            fonte.config = {**(fonte.config or {}), "nota": f["nota"]}
        s.add(fonte)
        n += 1
    s.flush()
    return n


def carregar_calendario(s: Session, dir_dados: Path = DIR_DADOS) -> int:
    dados = _ler("calendario.yaml", dir_dados)
    existentes = {(e.titulo, e.quando): e for e in s.scalars(select(EventoCalendario))}
    n = 0
    for ev in dados.get("eventos", []):
        chave = (ev["titulo"], str(ev["quando"]))
        e = existentes.get(chave) or EventoCalendario(titulo=ev["titulo"], quando=str(ev["quando"]))
        e.entidade_id = ev.get("entidade")
        e.perfis = ev.get("perfis") or []
        e.descricao = ev.get("descricao")
        s.add(e)
        n += 1
    s.flush()
    return n


def carregar_governo_sombra(s: Session, dir_dados: Path = DIR_DADOS) -> int:
    dados = _ler("governo_sombra.yaml", dir_dados)
    n = 0
    for g in dados.get("gabinete", []):
        m = s.scalar(select(MinistroSombra).where(MinistroSombra.entidade_id == g["entidade"]))
        if m is None:
            m = MinistroSombra(entidade_id=g["entidade"], nome=g["nome"], cargo=g.get("cargo", g["nome"]))
            m.bio = g.get("bio")
            m.prioridades = g.get("prioridades") or []
            s.add(m)
        else:
            # Não sobrescrever edições feitas na interface; só preencher lacunas.
            m.cargo = m.cargo or g.get("cargo", g["nome"])
            if not m.prioridades:
                m.prioridades = g.get("prioridades") or []
        n += 1
    s.flush()
    return n


def limpar_fontes_duplicadas(s: Session) -> int:
    """Quando várias fontes apontam para o mesmo URL (p. ex. feeds descobertos
    automaticamente), fica só uma: de preferência a definida em fontes.yaml e,
    entre as automáticas, a da entidade mais acima na hierarquia."""
    import json

    from .models import Item

    removidas = 0
    grupos: dict[str, list[Fonte]] = {}
    for f in list(s.scalars(select(Fonte))):
        if f.id.endswith("-rss-auto") and "comment" in f.url.lower():
            for item in s.scalars(select(Item).where(Item.fonte_id == f.id)):
                s.delete(item)
            s.delete(f)
            removidas += 1
            continue
        cfg = {k: v for k, v in (f.config or {}).items() if k not in ("diagnostico", "nota")}
        chave = f.url.rstrip("/").lower() + "|" + json.dumps(cfg, sort_keys=True)
        grupos.setdefault(chave, []).append(f)
    for lista in grupos.values():
        if len(lista) < 2:
            continue
        lista.sort(key=lambda f: (f.id.endswith("-rss-auto"), len(f.entidade.caminho()) if f.entidade else 9, f.id))
        for extra in lista[1:]:
            for item in s.scalars(select(Item).where(Item.fonte_id == extra.id)):
                s.delete(item)
            s.delete(extra)
            removidas += 1
    s.flush()
    return removidas


def garantir_perfil(s: Session) -> Perfil:
    p = s.get(Perfil, 1)
    if p is None:
        p = Perfil(id=1, perfis=["contribuinte"], regioes=[], entidades_seguidas=[], palavras=[])
        s.add(p)
        s.flush()
    return p


def garantir_alerta_exemplo(s: Session) -> None:
    if s.scalar(select(Alerta).limit(1)) is None:
        s.add(
            Alerta(
                nome="Orçamento do Estado",
                palavras=["orçamento do estado", "OE2027", "lei do orçamento"],
                entidades=["ministerio-financas", "assembleia-republica"],
                tipos=[],
            )
        )


def seed_tudo(s: Session, dir_dados: Path = DIR_DADOS) -> dict[str, int]:
    r = {
        "entidades": carregar_entidades(s, dir_dados),
        "fontes": carregar_fontes(s, dir_dados),
        "calendario": carregar_calendario(s, dir_dados),
        "governo_sombra": carregar_governo_sombra(s, dir_dados),
    }
    r["fontes_duplicadas_removidas"] = limpar_fontes_duplicadas(s)
    garantir_perfil(s)
    garantir_alerta_exemplo(s)
    s.commit()
    return r
