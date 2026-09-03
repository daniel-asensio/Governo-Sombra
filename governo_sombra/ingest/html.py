from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ItemBruto, interpretar_data, limpar_texto, obter

SELECTORES_OMISSAO = {
    "item": "article, .item, .list-item, .noticia, li.news, .card",
    "titulo": "h1, h2, h3, h4, .titulo, .title, a",
    "link": "a[href]",
    "data": "time, .data, .date, .published",
    "resumo": "p, .resumo, .summary, .lead",
}


def _primeiro(el, selector: str):
    for s in selector.split(","):
        s = s.strip()
        if not s:
            continue
        achado = el.select_one(s)
        if achado is not None:
            return achado
    return None


def extrair_itens(html: bytes | str, url_base: str, config: dict) -> list[ItemBruto]:
    sel = {**SELECTORES_OMISSAO, **(config.get("selectores") or {})}
    soup = BeautifulSoup(html, "lxml")
    itens: list[ItemBruto] = []
    vistos: set[str] = set()
    for bloco in soup.select(sel["item"]):
        t_el = _primeiro(bloco, sel["titulo"])
        titulo = limpar_texto(t_el.get_text(" ") if t_el else None, 600)
        if not titulo or len(titulo) < 8:
            continue
        a = t_el if t_el is not None and t_el.name == "a" and t_el.get("href") else _primeiro(bloco, sel["link"])
        href = a.get("href") if a is not None else None
        url = urljoin(url_base, href) if href else None
        chave = url or titulo
        if chave in vistos:
            continue
        vistos.add(chave)
        d_el = _primeiro(bloco, sel["data"])
        data_txt = None
        if d_el is not None:
            data_txt = d_el.get("datetime") or d_el.get_text(" ")
        r_el = _primeiro(bloco, sel["resumo"])
        resumo = limpar_texto(r_el.get_text(" ") if r_el else None)
        if resumo == titulo:
            resumo = None
        itens.append(
            ItemBruto(
                titulo=titulo,
                url=url,
                guid=url or titulo,
                resumo=resumo,
                publicado_em=interpretar_data(data_txt),
                tipo_documento=config.get("tipo_documento"),
            )
        )
        if len(itens) >= int(config.get("maximo", 100)):
            break
    return itens


class AdaptadorHTML:
    """Raspagem genérica configurável por selectores CSS."""

    def recolher(self, url: str, config: dict, corpo: bytes | None = None) -> list[ItemBruto]:
        corpo = corpo if corpo is not None else obter(url)
        return extrair_itens(corpo, url, config)
