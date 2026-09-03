"""Consultas reutilizadas pelas rotas web e pela API."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from ..classify.rules import normalizar
from ..models import Entidade, EventoCalendario, Fonte, Item, MinistroSombra, Perfil, Posicao


def perfil(s: Session) -> Perfil:
    from ..seed import garantir_perfil

    return garantir_perfil(s)


def filtrar_itens(
    s: Session,
    *,
    q: str | None = None,
    entidade: str | None = None,
    ministerio: str | None = None,
    tipo: str | None = None,
    perfil_id: str | None = None,
    regiao: str | None = None,
    desde: date | None = None,
    ate: date | None = None,
    guardados: bool = False,
    ordem: str = "data",
    limite: int = 50,
    pagina: int = 1,
) -> tuple[list[Item], int]:
    stmt = select(Item).options(selectinload(Item.entidade), selectinload(Item.fonte), selectinload(Item.ministerio))
    if q:
        termo = normalizar(q)
        # FTS5: cada palavra com prefixo; aspas para evitar operadores
        palavras = [f'"{p}"*' for p in termo.replace('"', " ").split() if p]
        if palavras:
            ids = [
                r[0]
                for r in s.execute(text("SELECT rowid FROM itens_fts WHERE itens_fts MATCH :m LIMIT 5000"), {"m": " ".join(palavras)})
            ]
            stmt = stmt.where(Item.id.in_(ids)) if ids else stmt.where(Item.titulo.ilike(f"%{q}%"))
    if entidade:
        descendentes = ids_descendentes(s, entidade)
        stmt = stmt.where(or_(Item.entidade_id.in_(descendentes), Item.ministerio_id == entidade))
    if ministerio:
        stmt = stmt.where(Item.ministerio_id == ministerio)
    if tipo:
        stmt = stmt.where(Item.tipo_documento == tipo)
    if perfil_id:
        stmt = stmt.where(func.json_extract(Item.impacto, "$").like(f'%"{perfil_id}"%'))
    if regiao:
        stmt = stmt.where(func.json_extract(Item.regioes, "$").like(f'%"{regiao}"%'))
    if desde:
        stmt = stmt.where(func.coalesce(Item.publicado_em, Item.recolhido_em) >= datetime.combine(desde, datetime.min.time()))
    if ate:
        stmt = stmt.where(func.coalesce(Item.publicado_em, Item.recolhido_em) < datetime.combine(ate + timedelta(days=1), datetime.min.time()))
    if guardados:
        stmt = stmt.where(Item.guardado.is_(True))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if ordem == "relevancia":
        stmt = stmt.order_by(Item.relevancia.desc(), func.coalesce(Item.publicado_em, Item.recolhido_em).desc())
    else:
        stmt = stmt.order_by(func.coalesce(Item.publicado_em, Item.recolhido_em).desc(), Item.id.desc())
    stmt = stmt.limit(limite).offset((max(pagina, 1) - 1) * limite)
    return list(s.scalars(stmt)), total


def ids_descendentes(s: Session, raiz: str) -> list[str]:
    ids = [raiz]
    fila = [raiz]
    while fila:
        actual = fila.pop()
        filhos = list(s.scalars(select(Entidade.id).where(Entidade.parent_id == actual)))
        ids.extend(filhos)
        fila.extend(filhos)
    return ids


def para_ti(s: Session, p: Perfil, *, dias: int = 7, limite: int = 30) -> list[Item]:
    """Itens que tocam nos perfis, regiões, entidades seguidas ou palavras do utilizador."""
    desde = datetime.utcnow() - timedelta(days=dias)
    stmt = (
        select(Item)
        .options(selectinload(Item.entidade), selectinload(Item.ministerio))
        .where(func.coalesce(Item.publicado_em, Item.recolhido_em) >= desde)
        .order_by(Item.relevancia.desc(), func.coalesce(Item.publicado_em, Item.recolhido_em).desc())
        .limit(600)
    )
    perfis = set(p.perfis or [])
    regioes = set(p.regioes or [])
    seguidas = set(p.entidades_seguidas or [])
    palavras = [normalizar(x) for x in (p.palavras or []) if x]
    resultado = []
    for it in s.scalars(stmt):
        pontos = 0.0
        imp = set(it.impacto or [])
        pontos += 3 * len(imp & perfis)
        pontos += 2 * len(set(it.regioes or []) & regioes)
        if it.entidade_id in seguidas or it.ministerio_id in seguidas:
            pontos += 2
        if palavras:
            tn = normalizar(f"{it.titulo} {it.resumo or ''}")
            pontos += 3 * sum(1 for w in palavras if w in tn)
        if any((e or "").startswith("alerta:") for e in (it.etiquetas or [])):
            pontos += 4
        if pontos > 0:
            it.__dict__["_pontos"] = pontos + it.relevancia / 10
            resultado.append(it)
    resultado.sort(key=lambda i: -i.__dict__["_pontos"])
    return resultado[:limite]


def contagens_hoje(s: Session) -> dict:
    hoje = datetime.utcnow().date()
    inicio = datetime.combine(hoje, datetime.min.time())
    semana = inicio - timedelta(days=7)
    col_data = func.coalesce(Item.publicado_em, Item.recolhido_em)
    por_tipo = dict(
        s.execute(select(Item.tipo_documento, func.count()).where(col_data >= semana).group_by(Item.tipo_documento)).all()
    )
    por_ministerio = s.execute(
        select(Entidade.id, Entidade.nome, Entidade.sigla, func.count(Item.id))
        .join(Item, Item.ministerio_id == Entidade.id)
        .where(col_data >= semana)
        .group_by(Entidade.id)
        .order_by(func.count(Item.id).desc())
    ).all()
    return {
        "hoje": s.scalar(select(func.count()).where(col_data >= inicio)) or 0,
        "semana": s.scalar(select(func.count()).where(col_data >= semana)) or 0,
        "total": s.scalar(select(func.count(Item.id))) or 0,
        "por_tipo": por_tipo,
        "por_ministerio": por_ministerio,
        "fontes_erro": s.scalar(select(func.count()).where(Fonte.ultimo_erro.isnot(None), Fonte.activa.is_(True))) or 0,
        "fontes_ok": s.scalar(select(func.count()).where(Fonte.ultimo_sucesso.isnot(None), Fonte.activa.is_(True))) or 0,
        "fontes_total": s.scalar(select(func.count()).where(Fonte.activa.is_(True))) or 0,
    }


def eventos_proximos(s: Session, p: Perfil | None = None, *, dias: int = 45, hoje: date | None = None) -> list[dict]:
    hoje = hoje or date.today()
    limite = hoje + timedelta(days=dias)
    perfis = set(p.perfis or []) if p else set()
    res = []
    for ev in s.scalars(select(EventoCalendario).options(selectinload(EventoCalendario.entidade))):
        if ev.perfis and perfis and not (set(ev.perfis) & perfis):
            continue
        if ":" in ev.quando:
            res.append({"evento": ev, "inicio": None, "fim": None, "recorrente": ev.quando, "dias": None, "a_decorrer": False})
            continue
        for ano in (hoje.year, hoje.year + 1):
            iv = ev.intervalo(ano)
            if not iv:
                continue
            ini, fim = iv
            if fim < hoje or ini > limite:
                continue
            res.append({"evento": ev, "inicio": ini, "fim": fim, "recorrente": None, "dias": (fim - hoje).days, "a_decorrer": ini <= hoje <= fim})
            break
    res.sort(key=lambda r: (r["inicio"] is None, r["inicio"] or hoje))
    return res


def arvore_estado(s: Session) -> list[Entidade]:
    todas = list(s.scalars(select(Entidade).options(selectinload(Entidade.filhos)).order_by(Entidade.ordem)))
    return [e for e in todas if e.parent_id is None]


def ultimas_posicoes(s: Session, limite: int = 10, entidade: str | None = None) -> list[Posicao]:
    stmt = select(Posicao).options(selectinload(Posicao.autor), selectinload(Posicao.item), selectinload(Posicao.entidade)).order_by(Posicao.criado_em.desc())
    if entidade:
        stmt = stmt.where(Posicao.entidade_id == entidade)
    return list(s.scalars(stmt.limit(limite)))


def gabinete(s: Session) -> list[MinistroSombra]:
    return list(s.scalars(select(MinistroSombra).options(selectinload(MinistroSombra.entidade)).order_by(MinistroSombra.id)))


def balanco_sombra(s: Session) -> dict:
    linhas = s.execute(select(Posicao.tipo, func.count()).group_by(Posicao.tipo)).all()
    por_tipo = dict(linhas)
    media = s.scalar(select(func.avg(Posicao.avaliacao)).where(Posicao.item_id.isnot(None)))
    return {"por_tipo": por_tipo, "total": sum(por_tipo.values()), "media": round(media, 2) if media is not None else None}
