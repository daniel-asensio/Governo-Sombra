"""Descoberta automática de feeds RSS/Atom nos sites das entidades."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ErroFonte, obter

CAMINHOS_COMUNS = ["/feed", "/feed/", "/rss", "/rss/", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/noticias/feed", "/noticias/feed/", "/pt/rss", "/pt/feed", "/rss/noticias", "/pt/noticias/feed", "/?feed=rss2", "/feeds/posts/default"]
PALAVRAS_NOTICIAS = ("noticia", "notícia", "comunicado", "imprensa", "destaque", "novidade", "atualidade", "actualidade", "publicac", "avisos", "alerta", "agenda", "consulta")


def e_feed(corpo: bytes) -> bool:
    inicio = corpo.lstrip()[:400].lower()
    return b"<rss" in inicio or b"<feed" in inicio or (b"<?xml" in inicio and (b"rss" in inicio or b"atom" in inicio))


def ligacoes_candidatas(url_site: str, html: bytes | None = None) -> list[tuple[str, str]]:
    """Ligações no site que parecem páginas de notícias/comunicados: [(texto, url)]."""
    if html is None:
        try:
            html = obter(url_site)
        except ErroFonte:
            return []
    soup = BeautifulSoup(html, "lxml")
    res = []
    vistos = set()
    for a in soup.select("a[href]"):
        texto = (a.get_text(" ") or "").strip()
        href = urljoin(url_site, a["href"])
        alvo = (texto + " " + href).lower()
        if any(p in alvo for p in PALAVRAS_NOTICIAS) and href not in vistos and not href.startswith(("mailto:", "javascript:")):
            vistos.add(href)
            res.append((texto[:80] or href, href))
        if len(res) >= 15:
            break
    return res


def descobrir_feeds(url_site: str, *, tentar_caminhos: bool = True) -> list[str]:
    encontrados: list[str] = []
    try:
        html = obter(url_site)
    except ErroFonte:
        html = b""
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
    # Confirmar que o que encontrámos é mesmo um feed
    confirmados = []
    for u in encontrados[:6]:
        try:
            if e_feed(obter(u)):
                confirmados.append(u)
        except ErroFonte:
            continue
    encontrados = confirmados
    if tentar_caminhos and not encontrados:
        for c in CAMINHOS_COMUNS:
            candidato = urljoin(url_site, c)
            try:
                corpo = obter(candidato)
            except ErroFonte:
                continue
            if e_feed(corpo):
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
