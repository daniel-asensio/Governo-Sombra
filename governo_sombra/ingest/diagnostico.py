"""Diagnóstico de uma fonte: o que o servidor vê quando vai buscar o URL."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..models import Fonte, agora
from .base import ErroFonte, limpar_texto, obter
from .descobrir import descobrir_feeds, e_feed, ligacoes_candidatas
from .html import extrair_itens, extrair_ligacoes_heuristico


def diagnosticar(fonte: Fonte) -> dict:
    d: dict = {"quando": agora().isoformat(timespec="minutes"), "url": fonte.url}
    corpo = None
    try:
        corpo = obter(fonte.url)
        d["estado"] = "ok"
        d["tamanho"] = len(corpo)
    except ErroFonte as e:
        d["estado"] = "erro"
        d["erro"] = str(e)[:300]
    if corpo:
        if e_feed(corpo):
            d["parece"] = "feed RSS/Atom"
        else:
            soup = BeautifulSoup(corpo, "lxml")
            d["parece"] = "página HTML"
            titulo = soup.title.get_text(" ") if soup.title else ""
            d["titulo_pagina"] = limpar_texto(titulo, 120)
            d["ligacoes"] = len(soup.select("a[href]"))
            try:
                d["itens_selectores"] = len(extrair_itens(corpo, fonte.url, fonte.config or {}))
                d["itens_heuristico"] = len(extrair_ligacoes_heuristico(corpo, fonte.url, fonte.config or {}))
            except Exception as e:  # pragma: no cover
                d["erro_extraccao"] = str(e)[:200]
            if d.get("ligacoes", 0) < 5:
                d["nota"] = "Quase sem ligações: a página é provavelmente construída por JavaScript e o leitor não a consegue ver. Procurar um feed RSS ou uma página alternativa."
            d["candidatas"] = ligacoes_candidatas(fonte.url, corpo)[:8]
    site = fonte.entidade.url if fonte.entidade else None
    if site:
        d["feeds_no_site"] = descobrir_feeds(site)[:5]
        if not corpo or d.get("parece") != "feed RSS/Atom":
            d["candidatas_site"] = ligacoes_candidatas(site)[:8]
    return d
