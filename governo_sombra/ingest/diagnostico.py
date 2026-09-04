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
    if fonte.tipo in ("dre", "parlamento_iniciativas") or (fonte.config or {}).get("navegador"):
        from .navegador import disponivel, observar

        if disponivel():
            try:
                padrao = r"getfile|json|xml|iniciativ" if fonte.tipo == "parlamento_iniciativas" else r"detalhe|serie|sumario|diploma|pdf|rss|json"
                obs = observar(fonte.url, esperar="a[href*='getfile'], a[href*='json']" if fonte.tipo == "parlamento_iniciativas" else "a[href*='/dr/detalhe/']", padrao_ligacoes=padrao)
                d["navegador"] = {"esperou": obs["esperou"], "aviso": obs.get("aviso"), "texto": obs["texto"][:800], "n_ligacoes": obs["n_ligacoes"], "amostra": obs["amostra"], "interessantes": obs.get("interessantes") or []}
            except ErroFonte as e:
                d["navegador"] = {"erro": str(e)[:300]}
        else:
            d["navegador"] = {"erro": "mini-browser não instalado"}
    site = fonte.entidade.url if fonte.entidade else None
    if site:
        d["feeds_no_site"] = descobrir_feeds(site)[:5]
        if not corpo or d.get("parece") != "feed RSS/Atom":
            d["candidatas_site"] = ligacoes_candidatas(site)[:8]
            d["sondagem"] = sondar_site(site)
    return d


def sondar_site(site: str) -> dict:
    """Pistas sobre onde está o conteúdo: robots.txt, sitemap e caminhos habituais de API."""
    from urllib.parse import urljoin, urlparse

    base = f"{urlparse(site).scheme}://{urlparse(site).netloc}/"
    res: dict = {}
    try:
        robots = obter(urljoin(base, "robots.txt")).decode("utf-8", "ignore")
        linhas = [l.strip() for l in robots.splitlines() if l.strip() and not l.startswith("#")]
        res["robots"] = linhas[:25]
        mapas = [l.split(":", 1)[1].strip() for l in linhas if l.lower().startswith("sitemap:")]
    except ErroFonte:
        mapas = []
    for candidato in mapas + [urljoin(base, "sitemap.xml"), urljoin(base, "sitemap_index.xml")]:
        try:
            xml = obter(candidato).decode("utf-8", "ignore")
        except ErroFonte:
            continue
        soup = BeautifulSoup(xml, "xml")
        locs = [l.get_text(strip=True) for l in soup.find_all("loc")]
        if locs:
            res["sitemap"] = candidato
            res["sitemap_exemplos"] = locs[:12]
            res["sitemap_total"] = len(locs)
            break
    for caminho in ("api", "api/", "rss", "feed", "dr/rss", "dr/api"):
        try:
            corpo = obter(urljoin(base, caminho))
        except ErroFonte:
            continue
        res.setdefault("caminhos_que_respondem", []).append({"url": urljoin(base, caminho), "inicio": limpar_texto(corpo[:300].decode("utf-8", "ignore"), 160)})
    return res
