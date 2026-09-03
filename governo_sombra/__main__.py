"""Linha de comandos: python -m governo_sombra <comando>."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import select

from .config import definicoes
from .db import criar_esquema, sessao_ctx


def cmd_init(_):
    criar_esquema()
    print("base de dados pronta:", definicoes.database_url)


def cmd_seed(_):
    from .seed import seed_tudo

    criar_esquema()
    with sessao_ctx() as s:
        r = seed_tudo(s)
    print("carregado:", r)


def cmd_ingest(args):
    from .ingest import recolher_tudo
    from .tarefas import iniciar_registo, terminar

    criar_esquema()
    with sessao_ctx() as s:
        tarefa = iniciar_registo(s, args.tarefa, "ingest")
        try:
            ex = recolher_tudo(s, apenas=args.fonte or None, dir_fixtures=Path(args.fixtures) if args.fixtures else None)
        except Exception as e:
            terminar(s, tarefa, erro=f"{type(e).__name__}: {e}")
            raise
        terminar(s, tarefa, fontes=ex.fontes, novos=ex.novos, erros=ex.erros)
        print(f"fontes: {ex.fontes} · novos: {ex.novos} · erros: {ex.erros}")
        for fid, d in (ex.detalhes or {}).items():
            estado = f"erro: {d['erro'][:100]}" if d.get("erro") else f"{d['novos']} novos"
            print(f"  {fid:32s} {estado}")


def cmd_reclassificar(_):
    from .classify.rules import reclassificar_tudo

    with sessao_ctx() as s:
        print("reclassificados:", reclassificar_tudo(s))


def cmd_resumir(args):
    from .classify import llm

    if not llm.disponivel():
        print("IA indisponível: instala `anthropic` e define ANTHROPIC_API_KEY.", file=sys.stderr)
        sys.exit(2)
    with sessao_ctx() as s:
        print("resumidos:", llm.resumir_pendentes(s, limite=args.limite, relevancia_minima=args.minimo, modelo=args.modelo))


def cmd_digest(args):
    from .digest import enviar_email, gerar_digest

    with sessao_ctx() as s:
        texto, caminho = gerar_digest(s)
    print(texto)
    if caminho:
        print(f"\n(guardado em {caminho})", file=sys.stderr)
    if args.email:
        print("email:", "enviado" if enviar_email("Governo Sombra: resumo diário", texto) else "não configurado (GS_SMTP_HOST, GS_EMAIL_DESTINO)", file=sys.stderr)


def cmd_descobrir(args):
    from .ingest.descobrir import descobrir_feeds
    from .models import Entidade, Fonte
    from .tarefas import iniciar_registo, terminar

    criar_esquema()
    with sessao_ctx() as s:
        tarefa = iniciar_registo(s, args.tarefa, "descoberta")
        entidades = list(s.scalars(select(Entidade).where(Entidade.url.isnot(None), Entidade.activa.is_(True))))
        if args.entidade:
            entidades = [e for e in entidades if e.id in args.entidade]
        elif args.so_sem_fonte:
            com_sucesso = {f.entidade_id for f in s.scalars(select(Fonte).where(Fonte.ultimo_sucesso.isnot(None), Fonte.total_itens > 0))}
            entidades = [e for e in entidades if e.id not in com_sucesso]
        urls_usados = {f.url.rstrip("/").lower() for f in s.scalars(select(Fonte))}
        encontrados = []
        for n, e in enumerate(entidades, 1):
            feeds = [u for u in descobrir_feeds(e.url) if u.rstrip("/").lower() not in urls_usados]
            if tarefa is not None:
                tarefa.detalhes = {**(tarefa.detalhes or {}), "vistas": n, "total": len(entidades), "encontrados": encontrados}
                s.commit()
            if not feeds:
                print(f"{e.id:36s} sem feed detectado")
                continue
            print(f"{e.id:36s} {feeds[0]}" + (f" (+{len(feeds) - 1})" if len(feeds) > 1 else ""))
            if args.aplicar:
                urls_usados.add(feeds[0].rstrip("/").lower())
                fid = f"{e.id}-rss-auto"
                if s.get(Fonte, fid) is None:
                    s.add(Fonte(id=fid, entidade_id=e.id, nome=f"{e.sigla or e.nome} - RSS (descoberto)", tipo="rss", url=feeds[0], config={}, verificada=False, prioridade=4))
                    s.commit()
                encontrados.append([e.nome, feeds[0]])
        terminar(s, tarefa, vistas=len(entidades), total=len(entidades), encontrados=encontrados)
        if args.aplicar:
            print(f"{len(encontrados)} fontes adicionadas")
            if encontrados and not args.sem_recolha:
                from .ingest import recolher_tudo

                recolher_tudo(s, apenas=[f"{fid}" for fid in (f.id for f in s.scalars(select(Fonte).where(Fonte.id.like("%-rss-auto"), Fonte.ultima_recolha.is_(None))))])


def cmd_diagnosticar(args):
    from .ingest.diagnostico import diagnosticar
    from .models import Fonte
    from .tarefas import iniciar_registo, terminar

    criar_esquema()
    with sessao_ctx() as s:
        tarefa = iniciar_registo(s, args.tarefa, "diagnostico", args.fonte)
        f = s.get(Fonte, args.fonte)
        if f is None:
            terminar(s, tarefa, erro="fonte não existe")
            sys.exit(1)
        try:
            resultado = diagnosticar(f)
        except Exception as e:
            terminar(s, tarefa, erro=f"{type(e).__name__}: {e}")
            raise
        f.config = {**(f.config or {}), "diagnostico": resultado}
        s.commit()
        terminar(s, tarefa)
        import json

        print(json.dumps(resultado, ensure_ascii=False, indent=2))


def cmd_serve(args):
    import uvicorn

    criar_esquema()
    import os

    porta = args.port or int(os.environ.get("PORT", 0) or 0) or definicoes.port
    uvicorn.run("governo_sombra.web.app:app", host=args.host or definicoes.host, port=porta, reload=args.reload, proxy_headers=True, forwarded_allow_ips="*")


def cmd_estado(_):
    from .models import Entidade

    with sessao_ctx() as s:
        raizes = list(s.scalars(select(Entidade).where(Entidade.parent_id.is_(None)).order_by(Entidade.ordem)))

        def imprimir(e, nivel=0):
            print("  " * nivel + f"- {e.nome}" + (f" [{e.sigla}]" if e.sigla else "") + (f" — {e.titular}" if e.titular else ""))
            for f in e.filhos:
                imprimir(f, nivel + 1)

        for r in raizes:
            imprimir(r)


def main(argv: list[str] | None = None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="governo-sombra", description="Observatório da administração pública portuguesa")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="criar a base de dados").set_defaults(fn=cmd_init)
    sub.add_parser("seed", help="carregar entidades, fontes, calendário e governo sombra de data/").set_defaults(fn=cmd_seed)
    pi = sub.add_parser("ingest", help="recolher fontes")
    pi.add_argument("--fonte", action="append", help="id de fonte (repetível)")
    pi.add_argument("--fixtures", help="pasta com ficheiros <fonte>.xml|html|json em vez de rede")
    pi.add_argument("--tarefa", type=int, help=argparse.SUPPRESS)
    pi.set_defaults(fn=cmd_ingest)
    sub.add_parser("reclassificar", help="voltar a aplicar regras de impacto/alertas a todos os itens").set_defaults(fn=cmd_reclassificar)
    pr = sub.add_parser("resumir", help="resumir itens relevantes com IA (requer ANTHROPIC_API_KEY)")
    pr.add_argument("--limite", type=int, default=20)
    pr.add_argument("--minimo", type=float, default=3.0, help="relevância mínima")
    pr.add_argument("--modelo", default=None)
    pr.set_defaults(fn=cmd_resumir)
    pd = sub.add_parser("digest", help="gerar o resumo diário em Markdown")
    pd.add_argument("--email", action="store_true")
    pd.set_defaults(fn=cmd_digest)
    pdesc = sub.add_parser("descobrir", help="detectar feeds RSS nos sites das entidades")
    pdesc.add_argument("--entidade", action="append")
    pdesc.add_argument("--aplicar", action="store_true", help="adicionar os feeds encontrados como fontes")
    pdesc.add_argument("--so-sem-fonte", action="store_true", help="só entidades sem nenhuma fonte a funcionar")
    pdesc.add_argument("--sem-recolha", action="store_true", help="não recolher os feeds novos no fim")
    pdesc.add_argument("--tarefa", type=int, help=argparse.SUPPRESS)
    pdesc.set_defaults(fn=cmd_descobrir)
    pdiag = sub.add_parser("diagnosticar", help="diagnosticar uma fonte (o que o servidor vê no URL)")
    pdiag.add_argument("fonte")
    pdiag.add_argument("--tarefa", type=int, help=argparse.SUPPRESS)
    pdiag.set_defaults(fn=cmd_diagnosticar)
    ps = sub.add_parser("serve", help="arrancar a interface web")
    ps.add_argument("--host")
    ps.add_argument("--port", type=int)
    ps.add_argument("--reload", action="store_true")
    ps.set_defaults(fn=cmd_serve)
    sub.add_parser("estado", help="imprimir a árvore do Estado").set_defaults(fn=cmd_estado)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
