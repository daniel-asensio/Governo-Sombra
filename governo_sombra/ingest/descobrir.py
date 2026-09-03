"""Descoberta automática de feeds RSS/Atom nos sites das entidades."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ErroFonte, obter

CAMINHOS_COMUNS = ["/feed", "/feed/", "/rss", "/rss/", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/noticias/feed", "/pt/rss", "/pt/feed"]


def descobrir_feeds(url_site: str, *, tentar_caminhos: bool = True) -> list[str]:
    encontrados: list[str] = []
    try:
        html = obter(url_site)
    except ErroFonte:
        return encontrados
    soup = BeautifulSoup(html, "lxml")
    for link in soup.select('link[rel="alternate"]'):
        tipo = (link.get("type") or "").lower()
        if "rss" in tipo or "atom" in tipo or "xml" in tipo:
            href = link.get("href")
            if href:
                encontrados.append(urljoin(url_site, href))
    for a in soup.select("a[href]"):
        href = a["href"].lower()
        if href.endswith((".rss", ".xml")) or "/rss" in href or "/feed" in href:
            encontrados.append(urljoin(url_site, a["href"]))
    if tentar_caminhos and not encontrados:
        for c in CAMINHOS_COMUNS:
            candidato = urljoin(url_site, c)
            try:
                corpo = obter(candidato)
            except ErroFonte:
                continue
            inicio = corpo.lstrip()[:200].lower()
            if b"<rss" in inicio or b"<feed" in inicio or b"<?xml" in inicio:
                encontrados.append(candidato)
                break
    # Deduplicar mantendo ordem
    vistos = set()
    unicos = []
    for u in encontrados:
        if u not in vistos:
            vistos.add(u)
            unicos.append(u)
    return unicos
