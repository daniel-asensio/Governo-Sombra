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

    criar_esquema()
    with sessao_ctx() as s:
        ex = recolher_tudo(s, apenas=args.fonte or None, dir_fixtures=Path(args.fixtures) if args.fixtures else None)
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

    with sessao_ctx() as s:
        entidades = list(s.scalars(select(Entidade).where(Entidade.url.isnot(None))))
        if args.entidade:
            entidades = [e for e in entidades if e.id in args.entidade]
        for e in entidades:
            feeds = descobrir_feeds(e.url)
            if not feeds:
                print(f"{e.id:36s} sem feed detectado")
                continue
            print(f"{e.id:36s} {feeds[0]}" + (f" (+{len(feeds) - 1})" if len(feeds) > 1 else ""))
            if args.aplicar:
                fid = f"{e.id}-rss-auto"
                if s.get(Fonte, fid) is None:
                    s.add(Fonte(id=fid, entidade_id=e.id, nome=f"{e.sigla or e.nome} - RSS (auto)", tipo="rss", url=feeds[0], config={}, verificada=False, prioridade=4))
        if args.aplicar:
            print("fontes adicionadas; corre `ingest` para testar")


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
    pdesc.set_defaults(fn=cmd_descobrir)
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
