"""Leitor de RSS/Atom incremental e frugal.

Alguns feeds oficiais têm anos de histórico (o do Governo passa dos 18 MB).
Carregá-los inteiros com feedparser gasta centenas de MB de memória, o que
numa máquina pequena arrasta tudo. Aqui descarrega-se o feed em blocos e
lê-se elemento a elemento, parando ao fim de `maximo` itens.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from ..config import definicoes
from .base import CABECALHOS, ErroFonte, ItemBruto, interpretar_data, limpar_texto

log = logging.getLogger("governo_sombra.ingest")
LIMITE_BYTES = 6 * 1024 * 1024


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _texto(el) -> str | None:
    return (el.text or "").strip() or None


def _item_de(el) -> ItemBruto | None:
    campos: dict[str, str] = {}
    link = None
    for filho in el:
        nome = _local(filho.tag)
        if nome == "link":
            href = filho.get("href")
            if href and (filho.get("rel") in (None, "alternate")):
                link = href
            elif not href and _texto(filho):
                link = _texto(filho)
        elif nome in ("title", "guid", "id", "pubdate", "published", "updated", "description", "summary", "content", "encoded", "date"):
            valor = _texto(filho)
            if valor and nome not in campos:
                campos[nome] = valor
    titulo = limpar_texto(campos.get("title"), 600)
    if not titulo:
        return None
    data_txt = campos.get("pubdate") or campos.get("published") or campos.get("updated") or campos.get("date")
    conteudo = campos.get("encoded") or campos.get("content")
    return ItemBruto(
        titulo=titulo,
        url=link,
        guid=campos.get("guid") or campos.get("id") or link or titulo,
        resumo=limpar_texto(campos.get("description") or campos.get("summary")),
        conteudo=limpar_texto(conteudo, 20000) if conteudo else None,
        publicado_em=interpretar_data(data_txt),
    )


def _iterar(fluxo, maximo: int) -> list[ItemBruto]:
    parser = ET.XMLPullParser(events=("start", "end"))
    itens: list[ItemBruto] = []
    profundidade_item = None
    try:
        for bloco in fluxo:
            parser.feed(bloco)
            for evento, el in parser.read_events():
                nome = _local(el.tag)
                if evento == "end" and nome in ("item", "entry"):
                    item = _item_de(el)
                    if item is not None:
                        itens.append(item)
                    el.clear()
                    if len(itens) >= maximo:
                        return itens
    except ET.ParseError as e:
        if not itens:
            raise ValueError(f"feed inválido: {e}") from e
        log.info("feed truncado depois de %d itens (%s)", len(itens), e)
    return itens


def ler_feed_incremental(url: str, *, maximo: int = 300, verificar_tls: bool = True, limite_bytes: int = LIMITE_BYTES) -> list[ItemBruto]:
    def gerador(verify: bool):
        lidos = 0
        with httpx.Client(headers=CABECALHOS, timeout=definicoes.http_timeout, follow_redirects=True, verify=verify) as c:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                for bloco in r.iter_bytes(64 * 1024):
                    lidos += len(bloco)
                    yield bloco
                    if lidos >= limite_bytes:
                        log.info("%s: parado aos %d bytes", url, lidos)
                        return

    try:
        return _iterar(gerador(verificar_tls), maximo)
    except httpx.ConnectError as e:
        if verificar_tls and "CERTIFICATE_VERIFY_FAILED" in str(e):
            return _iterar(gerador(False), maximo)
        raise ErroFonte(f"{type(e).__name__}: {e}") from e
    except httpx.HTTPError as e:
        raise ErroFonte(f"{type(e).__name__}: {e}") from e


def ler_feed_de_bytes(corpo: bytes, *, maximo: int = 300) -> list[ItemBruto]:
    return _iterar([corpo], maximo)
