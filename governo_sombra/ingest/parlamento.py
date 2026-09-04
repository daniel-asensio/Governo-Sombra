"""Assembleia da República.

`parlamento_iniciativas` lê o ficheiro JSON de "Iniciativas" publicado em
Dados Abertos (https://www.parlamento.pt/Cidadania/Paginas/DadosAbertos.aspx).
A estrutura exacta muda entre legislaturas; o parser é tolerante: procura os
campos habituais (IniTitulo, IniNr, IniTipo, IniLinkTexto, DataInicioleg,
IniAutorGruposParlamentares, IniEventos[].Fase/DataFase).
"""

from __future__ import annotations

import json

from .base import ItemBruto, interpretar_data, limpar_texto, obter

TIPOS_INICIATIVA = {
    "J": "Projeto de Lei",
    "P": "Proposta de Lei",
    "R": "Projeto de Resolução",
    "S": "Proposta de Resolução",
    "D": "Projeto de Deliberação",
    "A": "Apreciação Parlamentar",
    "I": "Inquérito Parlamentar",
    "E": "Projeto de Revisão Constitucional",
}


def _resolver_ficheiro(url_pagina: str, config: dict) -> str:
    """Devolve o URL do ficheiro JSON: o guardado em config, ou procurado na página (com mini-browser se preciso)."""
    if config.get("url_ficheiro"):
        return config["url_ficheiro"]
    html = obter(url_pagina)
    encontrado = encontrar_ficheiro_iniciativas(html, url_pagina)
    if not encontrado:
        # A página geral de Dados Abertos remete para uma sub-página de recursos por tema.
        sub = encontrar_subpagina_iniciativas(html, url_pagina)
        if sub and sub != url_pagina:
            url_pagina = sub
            html = obter(url_pagina)
            encontrado = encontrar_ficheiro_iniciativas(html, url_pagina)
    obs = None
    if not encontrado:
        from .navegador import disponivel, observar

        if disponivel():
            obs = observar(url_pagina, esperar="a[href*='getfile'], a[href*='.json'], a[href*='json']", padrao_ligacoes=r"getfile|json|xml|iniciativ")
            encontrado = encontrar_ficheiro_iniciativas(obs["html"], url_pagina)
    if not encontrado:
        pista = ""
        if obs:
            exemplos = "; ".join(f"{tx} → {h[:90]}" for tx, h in (obs.get("interessantes") or [])[:5])
            pista = f" O mini-browser viu {obs['n_ligacoes']} ligações. Ligações com getfile/json/iniciativ: {exemplos or 'nenhuma'}."
        raise ValueError("Não encontrei o ficheiro JSON de Iniciativas na página de Dados Abertos." + pista + " Podes indicá-lo à mão em 'alterar URL' (usa 'diagnosticar' para ver as ligações).")
    return encontrado


def _lista_iniciativas(dados):
    if isinstance(dados, list):
        return dados
    if isinstance(dados, dict):
        for chave in ("Iniciativas", "iniciativas", "ArrayOfPt_gov_ar_objectos_iniciativas_DetalhePesquisaIniciativasOut", "items"):
            v = dados.get(chave)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, list):
                        return vv
        # Primeira lista encontrada
        for v in dados.values():
            if isinstance(v, list):
                return v
    return []


def _primeiro(d: dict, *chaves):
    for k in chaves:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


ROMANOS = {"I": 1, "V": 5, "X": 10, "L": 50}


def _romano(s: str) -> int:
    total, anterior = 0, 0
    for c in reversed(s.upper()):
        v = ROMANOS.get(c, 0)
        total = total - v if v < anterior else total + v
        anterior = max(anterior, v)
    return total


def encontrar_ficheiro_iniciativas(html: str | bytes, base: str) -> str | None:
    """Na página de Dados Abertos, escolhe a ligação ao JSON de Iniciativas da legislatura mais recente."""
    import re
    from urllib.parse import unquote, urljoin

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    candidatos = []
    for a in soup.select("a[href]"):
        href = a["href"]
        alvo = unquote(href + " " + a.get_text(" ")).lower()
        if "iniciativa" in alvo and "json" in alvo:
            m = re.search(r"iniciativas[_\s-]*([ivxl]+)", alvo)
            leg = _romano(m[1]) if m else 0
            candidatos.append((leg, urljoin(base, href)))
    if not candidatos:
        return None
    candidatos.sort(key=lambda c: -c[0])
    return candidatos[0][1]


def encontrar_subpagina_iniciativas(html: str | bytes, base: str) -> str | None:
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for a in soup.select("a[href]"):
        href = a["href"]
        if "dainiciativas" in href.lower():
            return urljoin(base, href)
    return None


class AdaptadorIniciativasAR:
    config_actualizada: dict | None = None

    def recolher(self, url: str, config: dict, corpo: bytes | None = None) -> list[ItemBruto]:
        if corpo is None and "DadosAbertos" in url:
            url = _resolver_ficheiro(url, config)
            self.config_actualizada = {"url_ficheiro": url}
        corpo = corpo if corpo is not None else obter(url)
        try:
            dados = json.loads(corpo)
        except ValueError:
            raise ValueError("A resposta não é JSON. Confirma que o URL é o do ficheiro de Iniciativas (JSON) e não a página web") from None
        itens = []
        for ini in _lista_iniciativas(dados):
            if not isinstance(ini, dict):
                continue
            titulo = limpar_texto(_primeiro(ini, "IniTitulo", "Titulo", "titulo"), 600)
            if not titulo:
                continue
            nr = _primeiro(ini, "IniNr", "Numero", "numero")
            tipo_cod = _primeiro(ini, "IniTipo", "Tipo", "tipo")
            tipo_nome = TIPOS_INICIATIVA.get(str(tipo_cod), str(tipo_cod or "Iniciativa"))
            leg = _primeiro(ini, "IniLeg", "Legislatura", "legislatura")
            sessao = _primeiro(ini, "IniSel", "Sessao", "sessao")
            link = _primeiro(ini, "IniLinkTexto", "Link", "link", "url")
            autores = []
            gp = _primeiro(ini, "IniAutorGruposParlamentares", "AutoresGruposParlamentares")
            if isinstance(gp, dict):
                gp = [gp]
            if isinstance(gp, list):
                for g in gp:
                    if isinstance(g, dict):
                        autores.append(str(_primeiro(g, "GP", "sigla", "Sigla") or ""))
                    else:
                        autores.append(str(g))
            outros = _primeiro(ini, "IniAutorOutros", "AutorOutros")
            if isinstance(outros, dict):
                autores.append(str(_primeiro(outros, "nome", "Nome", "sigla") or ""))
            eventos = _primeiro(ini, "IniEventos", "Eventos") or []
            if isinstance(eventos, dict):
                eventos = eventos.get("Pt_gov_ar_objectos_iniciativas_EventosOut") or list(eventos.values())
            ultima_fase, data_fase = None, None
            for ev in eventos if isinstance(eventos, list) else []:
                if isinstance(ev, dict):
                    ultima_fase = _primeiro(ev, "Fase", "fase") or ultima_fase
                    data_fase = _primeiro(ev, "DataFase", "dataFase", "Data") or data_fase
            data = interpretar_data(str(data_fase or _primeiro(ini, "DataInicioleg", "Data", "data") or ""))
            autores = [a for a in autores if a]
            resumo = f"{tipo_nome} {nr or ''}".strip()
            if autores:
                resumo += f" · Autores: {', '.join(autores)}"
            if ultima_fase:
                resumo += f" · Fase: {ultima_fase}"
            guid = f"{leg or ''}-{sessao or ''}-{tipo_cod or ''}-{nr or titulo}"
            itens.append(
                ItemBruto(
                    titulo=f"{tipo_nome} {nr}: {titulo}" if nr else titulo,
                    url=link,
                    guid=guid,
                    resumo=resumo,
                    publicado_em=data,
                    tipo_documento="iniciativa",
                    extra={"tipo": tipo_nome, "numero": nr, "autores": autores, "fase": ultima_fase, "legislatura": leg},
                )
            )
        return itens
