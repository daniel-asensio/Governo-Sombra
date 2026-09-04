from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import __version__
from ..classify.rules import Classificador
from ..config import definicoes
from ..db import criar_esquema, sessao
from ..models import (
    TIPOS_DOCUMENTO,
    TIPOS_ENTIDADE,
    TIPOS_POSICAO,
    Alerta,
    Entidade,
    Execucao,
    Fonte,
    Item,
    MinistroSombra,
    Posicao,
    Tarefa,
)
from . import queries
from .auth import AutenticacaoBasica

log = logging.getLogger("governo_sombra.web")
DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(DIR / "templates"))


def _data(dt: datetime | date | None, fmt: str = "%d/%m/%Y") -> str:
    if not dt:
        return ""
    return dt.strftime(fmt)


def _data_hora(dt: datetime | None) -> str:
    return _data(dt, "%d/%m/%Y %H:%M")


_DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _data_extenso(dt: datetime | date | None) -> str:
    if not dt:
        return ""
    return f"{_DIAS_PT[dt.weekday()]}, {dt.day} de {_MESES_PT[dt.month - 1]} de {dt.year}"


def _relativa(dt: datetime | None) -> str:
    if not dt:
        return ""
    delta = datetime.utcnow() - dt
    seg = int(delta.total_seconds())
    if seg < 60:
        return "agora"
    if seg < 3600:
        return f"há {seg // 60} min"
    if seg < 86400:
        return f"há {seg // 3600} h"
    dias = seg // 86400
    if dias == 1:
        return "ontem"
    if dias < 30:
        return f"há {dias} dias"
    return dt.strftime("%d/%m/%Y")


templates.env.filters["data"] = _data
templates.env.filters["data_hora"] = _data_hora
templates.env.filters["data_extenso"] = _data_extenso
templates.env.filters["relativa"] = _relativa
templates.env.globals.update(
    TIPOS_DOCUMENTO=TIPOS_DOCUMENTO,
    TIPOS_ENTIDADE=TIPOS_ENTIDADE,
    TIPOS_POSICAO=TIPOS_POSICAO,
    versao=__version__,
)

_classificador: Classificador | None = None


def classificador() -> Classificador:
    global _classificador
    if _classificador is None:
        _classificador = Classificador.de_yaml()
    return _classificador


def get_db():
    s = sessao()
    try:
        yield s
    finally:
        s.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_esquema()
    from ..tarefas import limpar_interrompidas

    s = sessao()
    try:
        n = limpar_interrompidas(s)
        if n:
            log.info("%d tarefas interrompidas por reinício foram fechadas", n)
    finally:
        s.close()
    scheduler = None
    if definicoes.scheduler:
        from ..scheduler import iniciar

        scheduler = iniciar()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Governo Sombra", version=__version__, lifespan=lifespan)
app.add_middleware(AutenticacaoBasica)
app.mount("/static", StaticFiles(directory=str(DIR / "static")), name="static")


@app.get("/manifest.json")
def manifest():
    return JSONResponse(
        {
            "name": "Governo Sombra",
            "short_name": "GovSombra",
            "description": "O que se passa na administração pública portuguesa e o que te afecta",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#f6f5f1",
            "theme_color": "#0a5c4a",
            "lang": "pt-PT",
            "icons": [{"src": "/static/icone.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
        },
        media_type="application/manifest+json",
    )


def render(request: Request, nome: str, **ctx):
    ctx.setdefault("request", request)
    ctx.setdefault("agora", datetime.utcnow())
    return templates.TemplateResponse(request, nome, ctx)


# ---------------------------------------------------------------------------
# Página inicial: Hoje
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def hoje(request: Request, s: Session = Depends(get_db)):
    p = queries.perfil(s)
    contagens = queries.contagens_hoje(s)
    para_ti = queries.para_ti(s, p)
    ja_vistos = {i.id for i in para_ti}
    destaque, _ = queries.filtrar_itens(s, ordem="relevancia", limite=24)
    destaque = [i for i in destaque if i.id not in ja_vistos][:12]
    recentes, _ = queries.filtrar_itens(s, limite=20)
    return render(
        request,
        "hoje.html",
        perfil=p,
        contagens=contagens,
        para_ti=para_ti,
        destaque=destaque,
        recentes=recentes,
        eventos=queries.eventos_proximos(s, p, dias=30)[:8],
        posicoes=queries.ultimas_posicoes(s, 5),
        ultima_execucao=s.scalar(select(Execucao).order_by(Execucao.id.desc()).limit(1)),
        perfis_cfg={pp.id: pp for pp in classificador().perfis},
    )


# ---------------------------------------------------------------------------
# Feed / pesquisa
# ---------------------------------------------------------------------------
@app.get("/feed", response_class=HTMLResponse)
def feed(
    request: Request,
    q: str | None = None,
    entidade: str | None = None,
    ministerio: str | None = None,
    tipo: str | None = None,
    perfil: str | None = None,
    regiao: str | None = None,
    desde: date | None = None,
    ate: date | None = None,
    guardados: bool = False,
    ordem: str = "data",
    pagina: int = 1,
    s: Session = Depends(get_db),
):
    itens, total = queries.filtrar_itens(
        s, q=q, entidade=entidade, ministerio=ministerio, tipo=tipo, perfil_id=perfil, regiao=regiao, desde=desde, ate=ate, guardados=guardados, ordem=ordem, pagina=pagina
    )
    ministerios = list(s.scalars(select(Entidade).where(Entidade.tipo.in_(["ministerio", "orgao_soberania"])).order_by(Entidade.tipo.desc(), Entidade.ordem)))
    return render(
        request,
        "feed.html",
        itens=itens,
        total=total,
        pagina=pagina,
        filtros={"q": q or "", "entidade": entidade or "", "ministerio": ministerio or "", "tipo": tipo or "", "perfil": perfil or "", "regiao": regiao or "", "desde": desde, "ate": ate, "guardados": guardados, "ordem": ordem},
        ministerios=ministerios,
        perfis_cfg=classificador().perfis,
        regioes_cfg=classificador().regioes,
    )


@app.get("/item/{item_id}", response_class=HTMLResponse)
def ver_item(request: Request, item_id: int, s: Session = Depends(get_db)):
    item = s.get(Item, item_id, options=[selectinload(Item.posicoes).selectinload(Posicao.autor), selectinload(Item.entidade), selectinload(Item.fonte), selectinload(Item.ministerio)])
    if item is None:
        raise HTTPException(404)
    if not item.lido:
        item.lido = True
        s.commit()
    ministros = queries.gabinete(s)
    relacionados, _ = queries.filtrar_itens(s, entidade=item.entidade_id, limite=6)
    return render(
        request,
        "item.html",
        item=item,
        ministros=ministros,
        relacionados=[r for r in relacionados if r.id != item.id][:5],
        perfis_cfg={pp.id: pp for pp in classificador().perfis},
        regioes_cfg={r.id: r for r in classificador().regioes},
    )


@app.post("/item/{item_id}/guardar")
def guardar_item(item_id: int, s: Session = Depends(get_db)):
    item = s.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    item.guardado = not item.guardado
    s.commit()
    return RedirectResponse(f"/item/{item_id}", status_code=303)


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
@app.get("/estado", response_class=HTMLResponse)
def estado(request: Request, s: Session = Depends(get_db)):
    raizes = queries.arvore_estado(s)
    contagens = dict(s.execute(select(Item.entidade_id, func.count()).group_by(Item.entidade_id)).all())
    return render(request, "estado.html", raizes=raizes, contagens=contagens)


@app.get("/estado/{entidade_id}", response_class=HTMLResponse)
def ver_entidade(request: Request, entidade_id: str, pagina: int = 1, s: Session = Depends(get_db)):
    e = s.get(Entidade, entidade_id, options=[selectinload(Entidade.filhos), selectinload(Entidade.fontes), selectinload(Entidade.parent)])
    if e is None:
        raise HTTPException(404)
    itens, total = queries.filtrar_itens(s, entidade=entidade_id, limite=30, pagina=pagina)
    ministro = s.scalar(select(MinistroSombra).where(MinistroSombra.entidade_id == entidade_id))
    p = queries.perfil(s)
    return render(
        request,
        "entidade.html",
        e=e,
        itens=itens,
        total=total,
        pagina=pagina,
        ministro=ministro,
        posicoes=queries.ultimas_posicoes(s, 10, entidade=entidade_id),
        seguida=entidade_id in (p.entidades_seguidas or []),
    )


@app.post("/estado/{entidade_id}/seguir")
def seguir_entidade(entidade_id: str, s: Session = Depends(get_db)):
    p = queries.perfil(s)
    seguidas = list(p.entidades_seguidas or [])
    if entidade_id in seguidas:
        seguidas.remove(entidade_id)
    else:
        seguidas.append(entidade_id)
    p.entidades_seguidas = seguidas
    s.commit()
    return RedirectResponse(f"/estado/{entidade_id}", status_code=303)


# ---------------------------------------------------------------------------
# Governo sombra
# ---------------------------------------------------------------------------
@app.get("/sombra", response_class=HTMLResponse)
def sombra(request: Request, s: Session = Depends(get_db)):
    return render(request, "sombra.html", gabinete=queries.gabinete(s), posicoes=queries.ultimas_posicoes(s, 20), balanco=queries.balanco_sombra(s))


@app.get("/sombra/posicao/nova", response_class=HTMLResponse)
def nova_posicao_form(request: Request, item: int | None = None, entidade: str | None = None, s: Session = Depends(get_db)):
    it = s.get(Item, item) if item else None
    ent_id = entidade or (it.ministerio_id or it.entidade_id if it else None)
    return render(request, "posicao_form.html", item=it, entidade_id=ent_id, ministros=queries.gabinete(s), posicao=None)


@app.post("/sombra/posicao/nova")
def nova_posicao(
    titulo: str = Form(...),
    texto: str = Form(...),
    tipo: str = Form("comentario"),
    avaliacao: int = Form(0),
    entidade_id: str = Form(...),
    autor_id: int | None = Form(None),
    item_id: int | None = Form(None),
    s: Session = Depends(get_db),
):
    if tipo not in TIPOS_POSICAO:
        raise HTTPException(400, "tipo inválido")
    if s.get(Entidade, entidade_id) is None:
        raise HTTPException(400, "entidade inválida")
    pos = Posicao(titulo=titulo.strip()[:300], texto=texto.strip(), tipo=tipo, avaliacao=max(-2, min(2, avaliacao)), entidade_id=entidade_id, autor_id=autor_id or None, item_id=item_id or None)
    s.add(pos)
    s.commit()
    return RedirectResponse(f"/item/{item_id}" if item_id else f"/sombra/{entidade_id}", status_code=303)


@app.get("/sombra/posicao/{posicao_id}/editar", response_class=HTMLResponse)
def editar_posicao_form(request: Request, posicao_id: int, s: Session = Depends(get_db)):
    pos = s.get(Posicao, posicao_id, options=[selectinload(Posicao.item)])
    if pos is None:
        raise HTTPException(404)
    return render(request, "posicao_form.html", item=pos.item, entidade_id=pos.entidade_id, ministros=queries.gabinete(s), posicao=pos)


@app.post("/sombra/posicao/{posicao_id}/editar")
def editar_posicao(posicao_id: int, titulo: str = Form(...), texto: str = Form(...), tipo: str = Form("comentario"), avaliacao: int = Form(0), autor_id: int | None = Form(None), s: Session = Depends(get_db)):
    pos = s.get(Posicao, posicao_id)
    if pos is None:
        raise HTTPException(404)
    pos.titulo, pos.texto, pos.tipo, pos.avaliacao, pos.autor_id = titulo.strip()[:300], texto.strip(), tipo, max(-2, min(2, avaliacao)), autor_id or None
    s.commit()
    return RedirectResponse(f"/item/{pos.item_id}" if pos.item_id else f"/sombra/{pos.entidade_id}", status_code=303)


@app.post("/sombra/posicao/{posicao_id}/eliminar")
def eliminar_posicao(posicao_id: int, s: Session = Depends(get_db)):
    pos = s.get(Posicao, posicao_id)
    if pos is None:
        raise HTTPException(404)
    destino = f"/item/{pos.item_id}" if pos.item_id else f"/sombra/{pos.entidade_id}"
    s.delete(pos)
    s.commit()
    return RedirectResponse(destino, status_code=303)


@app.get("/sombra/ministro/{ministro_id}/editar", response_class=HTMLResponse)
def editar_ministro_form(request: Request, ministro_id: int, s: Session = Depends(get_db)):
    m = s.get(MinistroSombra, ministro_id)
    if m is None:
        raise HTTPException(404)
    return render(request, "ministro_form.html", m=m)


@app.post("/sombra/ministro/{ministro_id}/editar")
def editar_ministro(ministro_id: int, nome: str = Form(...), cargo: str = Form(...), bio: str = Form(""), prioridades: str = Form(""), s: Session = Depends(get_db)):
    m = s.get(MinistroSombra, ministro_id)
    if m is None:
        raise HTTPException(404)
    m.nome, m.cargo, m.bio = nome.strip(), cargo.strip(), bio.strip() or None
    m.prioridades = [l.strip("-• ").strip() for l in prioridades.splitlines() if l.strip("-• ").strip()]
    s.commit()
    return RedirectResponse(f"/sombra/{m.entidade_id}", status_code=303)


@app.get("/sombra/{entidade_id}", response_class=HTMLResponse)
def sombra_ministerio(request: Request, entidade_id: str, s: Session = Depends(get_db)):
    e = s.get(Entidade, entidade_id, options=[selectinload(Entidade.filhos)])
    if e is None:
        raise HTTPException(404)
    m = s.scalar(select(MinistroSombra).where(MinistroSombra.entidade_id == entidade_id))
    itens, _ = queries.filtrar_itens(s, ministerio=entidade_id, ordem="relevancia", limite=10)
    if not itens:
        itens, _ = queries.filtrar_itens(s, entidade=entidade_id, ordem="relevancia", limite=10)
    return render(request, "sombra_ministerio.html", e=e, m=m, posicoes=queries.ultimas_posicoes(s, 50, entidade=entidade_id), itens=itens)


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
@app.get("/alertas", response_class=HTMLResponse)
def alertas(request: Request, s: Session = Depends(get_db)):
    lista = list(s.scalars(select(Alerta).order_by(Alerta.id.desc())))
    entidades = list(s.scalars(select(Entidade).order_by(Entidade.nome)))
    return render(request, "alertas.html", alertas=lista, entidades=entidades)


@app.post("/alertas")
def criar_alerta(nome: str = Form(...), palavras: str = Form(""), entidades: list[str] = Form([]), tipos: list[str] = Form([]), s: Session = Depends(get_db)):
    a = Alerta(nome=nome.strip(), palavras=[p.strip() for p in palavras.replace("\n", ",").split(",") if p.strip()], entidades=entidades, tipos=tipos)
    s.add(a)
    s.commit()
    global _classificador
    _classificador = None
    return RedirectResponse("/alertas", status_code=303)


@app.post("/alertas/{alerta_id}/eliminar")
def eliminar_alerta(alerta_id: int, s: Session = Depends(get_db)):
    a = s.get(Alerta, alerta_id)
    if a:
        s.delete(a)
        s.commit()
    return RedirectResponse("/alertas", status_code=303)


@app.post("/alertas/{alerta_id}/alternar")
def alternar_alerta(alerta_id: int, s: Session = Depends(get_db)):
    a = s.get(Alerta, alerta_id)
    if a:
        a.activo = not a.activo
        s.commit()
    return RedirectResponse("/alertas", status_code=303)


# ---------------------------------------------------------------------------
# Perfil "afecta-me"
# ---------------------------------------------------------------------------
@app.get("/perfil", response_class=HTMLResponse)
def perfil(request: Request, s: Session = Depends(get_db)):
    p = queries.perfil(s)
    ministerios = list(s.scalars(select(Entidade).where(Entidade.tipo.in_(["ministerio", "orgao_soberania", "regulador", "instituto", "autoridade"])).order_by(Entidade.tipo, Entidade.nome)))
    return render(request, "perfil.html", p=p, perfis_cfg=classificador().perfis, regioes_cfg=classificador().regioes, entidades=ministerios)


@app.post("/perfil")
def guardar_perfil(nome: str = Form(""), perfis: list[str] = Form([]), regioes: list[str] = Form([]), entidades: list[str] = Form([]), palavras: str = Form(""), s: Session = Depends(get_db)):
    p = queries.perfil(s)
    validos = {pp.id for pp in classificador().perfis}
    p.nome = nome.strip() or None
    p.perfis = [x for x in perfis if x in validos]
    p.regioes = [x for x in regioes if x in {r.id for r in classificador().regioes}]
    p.entidades_seguidas = entidades
    p.palavras = [x.strip() for x in palavras.replace("\n", ",").split(",") if x.strip()]
    s.commit()
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------
@app.get("/calendario", response_class=HTMLResponse)
def calendario(request: Request, todos: bool = False, s: Session = Depends(get_db)):
    p = None if todos else queries.perfil(s)
    eventos = queries.eventos_proximos(s, p, dias=120)
    agenda, _ = queries.filtrar_itens(s, tipo="agenda", limite=30)
    return render(request, "calendario.html", eventos=eventos, agenda=agenda, todos=todos)


# ---------------------------------------------------------------------------
# Fontes (trabalho pesado corre em processos separados: ver tarefas.py)
# ---------------------------------------------------------------------------
from ..tarefas import lancar, tarefa_activa, ultima_tarefa  # noqa: E402


@app.get("/fontes", response_class=HTMLResponse)
def fontes(request: Request, todas: bool = False, s: Session = Depends(get_db)):
    lista = list(s.scalars(select(Fonte).options(selectinload(Fonte.entidade)).order_by(Fonte.activa.desc(), Fonte.prioridade.desc(), Fonte.nome)))
    execucoes = list(s.scalars(select(Execucao).order_by(Execucao.id.desc()).limit(10)))
    diag_a_correr = {tk.alvo for tk in s.scalars(select(Tarefa).where(Tarefa.tipo == "diagnostico", Tarefa.estado == "a_correr"))}
    recolha_a_correr = {tk.alvo for tk in s.scalars(select(Tarefa).where(Tarefa.tipo == "ingest", Tarefa.estado == "a_correr", Tarefa.alvo.isnot(None)))}
    return render(
        request,
        "fontes.html",
        fontes=lista,
        execucoes=execucoes,
        todas=todas,
        ingest_activa=tarefa_activa(s, "ingest"),
        ingest_ultima=ultima_tarefa(s, "ingest"),
        descoberta_activa=tarefa_activa(s, "descoberta"),
        descoberta_ultima=ultima_tarefa(s, "descoberta"),
        diag_a_correr=diag_a_correr,
        recolha_a_correr=recolha_a_correr,
    )


@app.post("/fontes/recolher")
def recolher_todas(s: Session = Depends(get_db)):
    lancar(s, "ingest", ["ingest"])
    return RedirectResponse("/fontes", status_code=303)


@app.post("/fontes/descobrir")
def descobrir_fontes(s: Session = Depends(get_db)):
    lancar(s, "descoberta", ["descobrir", "--aplicar", "--so-sem-fonte"])
    return RedirectResponse("/fontes", status_code=303)


@app.post("/fontes/{fonte_id}/recolher")
def recolher_uma(fonte_id: str, s: Session = Depends(get_db)):
    f = s.get(Fonte, fonte_id)
    if f is None:
        raise HTTPException(404)
    lancar(s, "ingest", ["ingest", "--fonte", fonte_id], alvo=fonte_id)
    return RedirectResponse("/fontes#" + fonte_id, status_code=303)


@app.post("/fontes/{fonte_id}/diagnosticar")
def diagnosticar_fonte(fonte_id: str, s: Session = Depends(get_db)):
    if s.get(Fonte, fonte_id) is None:
        raise HTTPException(404)
    lancar(s, "diagnostico", ["diagnosticar", fonte_id], alvo=fonte_id)
    return RedirectResponse("/fontes#" + fonte_id, status_code=303)


@app.post("/fontes/{fonte_id}/alternar")
def alternar_fonte(fonte_id: str, s: Session = Depends(get_db)):
    f = s.get(Fonte, fonte_id)
    if f is None:
        raise HTTPException(404)
    f.activa = not f.activa
    if f.activa:
        f.ultimo_erro = None
    s.commit()
    return RedirectResponse("/fontes#" + fonte_id, status_code=303)


@app.post("/fontes/{fonte_id}/url")
def alterar_url_fonte(fonte_id: str, url: str = Form(...), tipo: str | None = Form(None), s: Session = Depends(get_db)):
    f = s.get(Fonte, fonte_id)
    if f is None:
        raise HTTPException(404)
    f.url = url.strip()
    if tipo in ("rss", "html"):
        f.tipo = tipo
    f.ultimo_erro = None
    f.verificada = False
    f.activa = True
    cfg = dict(f.config or {})
    cfg.pop("diagnostico", None)
    cfg.pop("nota", None)
    f.config = cfg
    s.commit()
    lancar(s, "ingest", ["ingest", "--fonte", fonte_id], alvo=fonte_id)
    return RedirectResponse("/fontes#" + fonte_id, status_code=303)


# ---------------------------------------------------------------------------
# API JSON e RSS
# ---------------------------------------------------------------------------
def _item_json(i: Item) -> dict:
    return {
        "id": i.id,
        "titulo": i.titulo,
        "url": i.url,
        "resumo": i.resumo,
        "resumo_ia": i.resumo_ia,
        "porque_importa": i.porque_importa,
        "tipo_documento": i.tipo_documento,
        "entidade": i.entidade_id,
        "ministerio": i.ministerio_id,
        "fonte": i.fonte_id,
        "impacto": i.impacto or [],
        "regioes": i.regioes or [],
        "etiquetas": i.etiquetas or [],
        "relevancia": i.relevancia,
        "publicado_em": i.publicado_em.isoformat() if i.publicado_em else None,
        "recolhido_em": i.recolhido_em.isoformat() if i.recolhido_em else None,
    }


@app.get("/api/itens")
def api_itens(q: str | None = None, entidade: str | None = None, ministerio: str | None = None, tipo: str | None = None, perfil: str | None = None, desde: date | None = None, limite: int = 50, pagina: int = 1, s: Session = Depends(get_db)):
    itens, total = queries.filtrar_itens(s, q=q, entidade=entidade, ministerio=ministerio, tipo=tipo, perfil_id=perfil, desde=desde, limite=min(limite, 200), pagina=pagina)
    return {"total": total, "pagina": pagina, "itens": [_item_json(i) for i in itens]}


@app.get("/api/para-ti")
def api_para_ti(dias: int = 7, s: Session = Depends(get_db)):
    p = queries.perfil(s)
    return {"itens": [_item_json(i) for i in queries.para_ti(s, p, dias=dias)]}


@app.get("/api/entidades")
def api_entidades(s: Session = Depends(get_db)):
    return [
        {"id": e.id, "nome": e.nome, "sigla": e.sigla, "tipo": e.tipo, "url": e.url, "titular": e.titular, "parent": e.parent_id}
        for e in s.scalars(select(Entidade).order_by(Entidade.ordem))
    ]


@app.get("/api/fontes")
def api_fontes(s: Session = Depends(get_db)):
    return [
        {"id": f.id, "nome": f.nome, "tipo": f.tipo, "url": f.url, "entidade": f.entidade_id, "activa": f.activa, "verificada": f.verificada, "estado": f.estado, "ultima_recolha": f.ultima_recolha.isoformat() if f.ultima_recolha else None, "ultimo_erro": f.ultimo_erro, "total_itens": f.total_itens}
        for f in s.scalars(select(Fonte))
    ]


@app.get("/api/posicoes")
def api_posicoes(s: Session = Depends(get_db)):
    return [
        {"id": p.id, "titulo": p.titulo, "tipo": p.tipo, "avaliacao": p.avaliacao, "entidade": p.entidade_id, "item": p.item_id, "autor": p.autor.nome if p.autor else None, "texto": p.texto, "criado_em": p.criado_em.isoformat()}
        for p in queries.ultimas_posicoes(s, 200)
    ]


@app.post("/api/ingest")
def api_ingest(s: Session = Depends(get_db)):
    t = lancar(s, "ingest", ["ingest"])
    return JSONResponse({"iniciado": t is not None, "tarefa": t.id if t else None})


@app.get("/rss.xml")
def rss_pessoal(s: Session = Depends(get_db)):
    from xml.sax.saxutils import escape

    p = queries.perfil(s)
    itens = queries.para_ti(s, p, dias=14, limite=50)
    partes = ['<?xml version="1.0" encoding="UTF-8"?>', "<rss version=\"2.0\"><channel>", "<title>Governo Sombra: para ti</title>", "<link>/</link>", "<description>Actividade da administração pública que te afecta</description>"]
    for i in itens:
        partes.append("<item>")
        partes.append(f"<title>{escape(i.titulo)}</title>")
        if i.url:
            partes.append(f"<link>{escape(i.url)}</link>")
        partes.append(f"<guid isPermaLink=\"false\">gs-{i.id}</guid>")
        desc = i.porque_importa or i.resumo_ia or i.resumo or ""
        partes.append(f"<description>{escape(desc)}</description>")
        if i.data:
            partes.append(f"<pubDate>{i.data.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>")
        partes.append(f"<category>{escape(i.entidade.nome if i.entidade else i.entidade_id)}</category>")
        partes.append("</item>")
    partes.append("</channel></rss>")
    return Response("\n".join(partes), media_type="application/rss+xml")


@app.get("/saude")
def saude(s: Session = Depends(get_db)):
    return {"ok": True, "versao": __version__, "itens": s.scalar(select(Item.id).limit(1)) is not None}
