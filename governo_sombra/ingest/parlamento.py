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


class AdaptadorIniciativasAR:
    def recolher(self, url: str, config: dict, corpo: bytes | None = None) -> list[ItemBruto]:
        corpo = corpo if corpo is not None else obter(url)
        dados = json.loads(corpo)
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
