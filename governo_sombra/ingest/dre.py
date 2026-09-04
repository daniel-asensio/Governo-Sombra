"""Diário da República Eletrónico.

O site https://diariodarepublica.pt apresenta o sumário do dia por série. Esta
implementação raspa a página do sumário e tenta identificar cada diploma
(tipo, número, emissor). O DRE disponibiliza também web services oficiais
mediante registo; se tiveres credenciais, define `config.api_url` e o
adaptador usa JSON em vez de HTML.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .base import ItemBruto, interpretar_data, limpar_texto, obter

PADRAO_DIPLOMA = re.compile(
    r"^(Lei Orgânica|Lei|Decreto-Lei|Decreto Regulamentar|Decreto do Presidente da República|Decreto|"
    r"Resolução do Conselho de Ministros|Resolução da Assembleia da República|Resolução|Portaria|"
    r"Despacho Normativo|Despacho|Aviso|Declaração de Retificação|Declaração|Acórdão|Deliberação|"
    r"Regulamento|Edital|Anúncio|Contrato|Louvor|Parecer|Recomendação)\s*(?:n\.?º|n\.|nº)?\s*([\w/\-]+)?",
    re.IGNORECASE,
)


def classificar_diploma(titulo: str) -> tuple[str, str | None]:
    m = PADRAO_DIPLOMA.match(titulo.strip())
    if not m:
        return "outro", None
    tipo = m[1].lower()
    if tipo.startswith(("lei", "decreto")):
        return "legislacao", m[1]
    if tipo.startswith("resolução do conselho"):
        return "conselho_ministros", m[1]
    if tipo.startswith("acórdão"):
        return "acordao", m[1]
    if tipo.startswith(("anúncio", "edital")):
        return "concurso", m[1]
    if tipo.startswith("contrato"):
        return "contrato", m[1]
    return "despacho", m[1]


class AdaptadorDRE:
    def recolher(self, url: str, config: dict, corpo: bytes | None = None) -> list[ItemBruto]:
        api_url = config.get("api_url")
        if api_url and corpo is None:
            corpo = obter(api_url)
            return self._de_json(corpo, config)
        if corpo is None:
            # O site é uma aplicação OutSystems: sem JavaScript vem uma casca vazia.
            # Renderizar no mini-browser e esperar que apareça algum diploma.
            from .navegador import renderizar

            html = renderizar(url, esperar="a[href*='/dr/detalhe/']", tempo_extra_ms=int(config.get("tempo_extra_ms", 2500)))
            return self._de_html(html.encode("utf-8"), url, config)
        if corpo.lstrip().startswith(b"{") or corpo.lstrip().startswith(b"["):
            return self._de_json(corpo, config)
        return self._de_html(corpo, url, config)

    def _de_json(self, corpo: bytes, config: dict) -> list[ItemBruto]:
        dados = json.loads(corpo)
        lista = dados if isinstance(dados, list) else dados.get("resultados") or dados.get("items") or dados.get("data") or []
        itens = []
        for d in lista:
            titulo = limpar_texto(d.get("titulo") or d.get("title") or d.get("sumario") or "", 600)
            if not titulo:
                continue
            tipo, _ = classificar_diploma(titulo)
            itens.append(
                ItemBruto(
                    titulo=titulo,
                    url=d.get("url") or d.get("link"),
                    guid=str(d.get("id") or d.get("url") or titulo),
                    resumo=limpar_texto(d.get("resumo") or d.get("sumario") or d.get("descricao")),
                    publicado_em=interpretar_data(str(d.get("data") or d.get("dataPublicacao") or "")),
                    tipo_documento=tipo,
                    extra={"emissor": d.get("emissor"), "serie": config.get("serie")},
                )
            )
        return itens

    def _de_html(self, corpo: bytes, url: str, config: dict) -> list[ItemBruto]:
        soup = BeautifulSoup(corpo, "lxml")
        serie = config.get("serie")
        itens = []
        vistos = set()
        data_pagina = None
        cab = soup.select_one("h1, .data-publicacao, .dr-data, time")
        if cab is not None:
            data_pagina = interpretar_data(cab.get("datetime") or cab.get_text(" "))
        # Cada diploma no sumário aparece normalmente como uma ligação cujo texto
        # começa pelo tipo de acto ("Decreto-Lei n.º 12/2026").
        serie_pedida = str(serie) if serie else None
        for a in soup.select("a[href]"):
            texto = limpar_texto(a.get_text(" "), 600)
            if not texto:
                continue
            tipo, numero = classificar_diploma(texto)
            if numero is None:
                continue
            serie_item = _serie_do_contexto(a) or serie_pedida
            if serie_pedida and serie_item and serie_item != serie_pedida:
                continue
            href = a["href"]
            if not href.startswith("http"):
                from urllib.parse import urljoin

                href = urljoin(url, href)
            if href in vistos:
                continue
            vistos.add(href)
            # O sumário do DRE costuma ter o emissor e o sumário do diploma nos
            # elementos irmãos imediatos.
            emissor = None
            resumo = None
            pai = a.find_parent(["li", "div", "article", "tr"])
            if pai is not None:
                partes = [limpar_texto(p.get_text(" ")) for p in pai.find_all(["p", "span", "div"], recursive=False)]
                partes = [p for p in partes if p and p != texto]
                if partes:
                    emissor = partes[0] if len(partes[0]) < 120 else None
                    resumo = " ".join(partes[1:] if emissor else partes)[:4000] or None
            itens.append(
                ItemBruto(
                    titulo=texto,
                    url=href,
                    guid=href,
                    resumo=resumo,
                    publicado_em=data_pagina,
                    tipo_documento=tipo,
                    extra={"emissor": emissor, "serie": serie_item},
                )
            )
        return itens


def _serie_do_contexto(a) -> str | None:
    """Procura no cabeçalho mais próximo acima da ligação: "Série I" / "Série II" / "1.ª série"."""
    import re as _re

    padrao = _re.compile(r"(?:s[ée]rie\s*(i{1,2})\b|(\d)\.?[ªa]\s*s[ée]rie)")
    for cab in a.find_all_previous(["h1", "h2", "h3", "h4", "h5"], limit=30):
        m = padrao.search(cab.get_text(" ", strip=True)[:120].lower())
        if m:
            return str(len(m[1])) if m[1] else m[2]
    return None
