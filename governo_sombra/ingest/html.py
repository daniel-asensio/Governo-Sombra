from __future__ import annotations

from urllib.parse import urljoin, urlparse

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


PALAVRAS_NAVEGACAO = {"início", "inicio", "home", "contactos", "contacto", "pesquisa", "pesquisar", "entrar", "login", "mapa do site", "acessibilidade", "privacidade", "cookies", "termos", "ver mais", "saber mais", "ler mais", "seguinte", "anterior", "página", "pagina", "menu", "voltar", "topo", "partilhar", "imprimir", "english", "português"}


def extrair_ligacoes_heuristico(html: bytes | str, url_base: str, config: dict) -> list[ItemBruto]:
    """Quando os selectores não apanham nada: todas as ligações do mesmo site cujo
    texto pareça um título (comprido, com espaços, sem ser navegação)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    dominio = urlparse(url_base).netloc.lower().removeprefix("www.")
    itens: list[ItemBruto] = []
    vistos: set[str] = set()
    minimo = int(config.get("titulo_minimo", 25))
    for a in soup.select("a[href]"):
        texto = limpar_texto(a.get_text(" "), 600)
        if not texto or len(texto) < minimo or " " not in texto:
            continue
        if texto.lower() in PALAVRAS_NAVEGACAO or texto.lower().startswith(("ver ", "saber ", "ler ")):
            continue
        href = urljoin(url_base, a["href"])
        if href.startswith(("mailto:", "javascript:", "tel:")):
            continue
        dom = urlparse(href).netloc.lower().removeprefix("www.")
        if dom and dom != dominio and not dom.endswith("." + dominio):
            continue
        if href.rstrip("/") == url_base.rstrip("/") or href in vistos:
            continue
        vistos.add(href)
        pai = a.find_parent(["li", "article", "div", "tr"])
        data_txt = None
        resumo = None
        if pai is not None:
            t_el = pai.find("time")
            if t_el is not None:
                data_txt = t_el.get("datetime") or t_el.get_text(" ")
            else:
                data_txt = pai.get_text(" ")[:200]
            p_el = pai.find("p")
            if p_el is not None:
                resumo = limpar_texto(p_el.get_text(" "))
                if resumo == texto:
                    resumo = None
        itens.append(ItemBruto(titulo=texto, url=href, guid=href, resumo=resumo, publicado_em=interpretar_data(data_txt), tipo_documento=config.get("tipo_documento"), extra={"modo": "heuristico"}))
        if len(itens) >= int(config.get("maximo", 60)):
            break
    return itens


class AdaptadorHTML:
    """Raspagem genérica configurável por selectores CSS, com modo heurístico de reserva."""

    def recolher(self, url: str, config: dict, corpo: bytes | None = None) -> list[ItemBruto]:
        if corpo is None and config.get("navegador"):
            from .navegador import observar

            corpo = observar(url, esperar=config.get("esperar"), timeout_s=float(config.get("timeout_s", 120)))["html"].encode("utf-8")
        corpo = corpo if corpo is not None else obter(url)
        itens = extrair_itens(corpo, url, config)
        if not itens and config.get("heuristico", True):
            itens = extrair_ligacoes_heuristico(corpo, url, config)
        return itens
