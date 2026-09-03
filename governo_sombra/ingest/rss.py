from __future__ import annotations

from datetime import datetime
from time import mktime

import feedparser

from .base import ItemBruto, interpretar_data, limpar_texto, obter


class AdaptadorRSS:
    """Feeds RSS/Atom: leitor incremental frugal; feedparser como reserva para feeds estranhos."""

    def recolher(self, url: str, config: dict, corpo: bytes | None = None) -> list[ItemBruto]:
        from .rss_leve import ler_feed_de_bytes, ler_feed_incremental

        maximo = int(config.get("maximo", 300))
        try:
            itens = ler_feed_de_bytes(corpo, maximo=maximo) if corpo is not None else ler_feed_incremental(url, maximo=maximo)
        except ValueError:
            itens = []
        if itens:
            tipo = config.get("tipo_documento")
            if tipo:
                for i in itens:
                    i.tipo_documento = tipo
            return itens
        corpo = corpo if corpo is not None else obter(url)
        feed = feedparser.parse(corpo)
        if feed.bozo and not feed.entries:
            raise ValueError(f"feed inválido: {getattr(feed, 'bozo_exception', 'desconhecido')}")
        itens = []
        maximo = int(config.get("maximo", 500))
        for e in feed.entries[:maximo]:
            titulo = limpar_texto(e.get("title"), 600)
            if not titulo:
                continue
            publicado = None
            for chave in ("published_parsed", "updated_parsed", "created_parsed"):
                st = e.get(chave)
                if st:
                    try:
                        publicado = datetime.fromtimestamp(mktime(st))
                    except (ValueError, OverflowError, OSError):
                        publicado = None
                    if publicado is not None and publicado.year >= 1990:
                        break
                    publicado = None
            if publicado is None:
                publicado = interpretar_data(e.get("published") or e.get("updated"))
            conteudo = None
            if e.get("content"):
                conteudo = limpar_texto(" ".join(c.get("value", "") for c in e["content"]), 20000)
            itens.append(
                ItemBruto(
                    titulo=titulo,
                    url=e.get("link"),
                    guid=e.get("id") or e.get("link") or titulo,
                    resumo=limpar_texto(e.get("summary")),
                    conteudo=conteudo,
                    publicado_em=publicado,
                    tipo_documento=config.get("tipo_documento"),
                    extra={"categorias": [t.get("term") for t in e.get("tags", []) if t.get("term")]},
                )
            )
        return itens
