"""Classificação por regras: tipo de documento, perfis de impacto, regiões, alertas."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DIR_DADOS
from ..models import Alerta, Entidade, Fonte, Item


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


PADROES_TIPO: list[tuple[str, re.Pattern]] = [
    ("conselho_ministros", re.compile(r"\b(conselho de ministros|resolucao do conselho de ministros)\b")),
    ("legislacao", re.compile(r"\b(lei organica|lei n|decreto-lei|decreto lei|decreto regulamentar|decreto n|lei do orcamento)\b")),
    ("iniciativa", re.compile(r"\b(projeto de lei|projecto de lei|proposta de lei|projeto de resolucao|projecto de resolucao|proposta de resolucao|apreciacao parlamentar)\b")),
    ("votacao", re.compile(r"\b(votacao|votacoes|aprovado na generalidade|aprovada na generalidade|votacao final global|chumbado|chumbada|rejeitado|rejeitada)\b")),
    ("consulta_publica", re.compile(r"\b(consulta publica|consultas publicas|discussao publica|participacao publica|audicao publica|contributos ate)\b")),
    ("concurso", re.compile(r"\b(concurso|concursos|candidatura|candidaturas|aviso de abertura|procedimento concursal|bolsa de estudo|bolsas|apoio a|incentivo|aviso n)\b")),
    ("contrato", re.compile(r"\b(contrato publico|contratos publicos|adjudicacao|ajuste direto|ajuste directo)\b")),
    ("nomeacao", re.compile(r"\b(nomeacao|nomeado|nomeada|exoneracao|exonerado|exonerada|designacao|tomada de posse|tomou posse|demissao)\b")),
    ("estatistica", re.compile(r"\b(estatistica|estatisticas|ine divulga|inflacao|taxa de desemprego|indice de precos|pib|destaque estatistico|inquerito)\b")),
    ("alerta", re.compile(r"\b(alerta|aviso vermelho|aviso laranja|aviso amarelo|estado de alerta|estado de emergencia|estado de calamidade|recolha do mercado|rutura|ruptura)\b")),
    ("acordao", re.compile(r"\b(acordao|acordaos|decisao do tribunal|inconstitucional|inconstitucionalidade)\b")),
    ("agenda", re.compile(r"\b(agenda|reuniao plenaria|sessao plenaria|ordem do dia|audicao|audiencia|debate)\b")),
    ("relatorio", re.compile(r"\b(relatorio|auditoria|parecer|boletim)\b")),
    ("despacho", re.compile(r"\b(despacho|portaria|aviso|declaracao de retificacao|deliberacao|regulamento|circular|oficio)\b")),
    ("comunicado", re.compile(r"\b(comunicado|nota a imprensa|nota de imprensa|esclarecimento)\b")),
]

PESO_TIPO = {
    "legislacao": 4, "conselho_ministros": 4, "consulta_publica": 4, "votacao": 3, "iniciativa": 2,
    "despacho": 2, "concurso": 2, "alerta": 3, "estatistica": 1, "nomeacao": 1, "acordao": 2,
    "comunicado": 1, "agenda": 1, "relatorio": 1, "contrato": 1, "noticia": 0, "outro": 0,
}


@dataclass
class Perfil:
    id: str
    nome: str
    peso: int
    palavras: list[str]
    descricao: str | None = None
    _regex: re.Pattern | None = field(default=None, repr=False)

    def regex(self) -> re.Pattern:
        if self._regex is None:
            termos = sorted({normalizar(p) for p in self.palavras if p}, key=len, reverse=True)
            self._regex = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(t) for t in termos) + r")(?![a-z0-9])")
        return self._regex


@dataclass
class Regiao:
    id: str
    nome: str
    palavras: list[str]
    _regex: re.Pattern | None = field(default=None, repr=False)

    def regex(self) -> re.Pattern:
        if self._regex is None:
            termos = sorted({normalizar(p) for p in self.palavras if p}, key=len, reverse=True)
            self._regex = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(t) for t in termos) + r")(?![a-z0-9])")
        return self._regex


class Classificador:
    def __init__(self, perfis: list[Perfil], regioes: list[Regiao], alertas: list[Alerta] | None = None, areas_ministerios: dict[str, list[str]] | None = None):
        self.perfis = perfis
        self.regioes = regioes
        self.alertas = alertas or []
        self.areas_ministerios = areas_ministerios or {}
        self._regex_ministerios: dict[str, re.Pattern] = {}

    @classmethod
    def de_yaml(cls, caminho: Path = DIR_DADOS / "impacto.yaml") -> "Classificador":
        with open(caminho, encoding="utf-8") as f:
            d = yaml.safe_load(f)
        perfis = [Perfil(id=p["id"], nome=p["nome"], peso=int(p.get("peso", 1)), palavras=p.get("palavras", []), descricao=p.get("descricao")) for p in d.get("perfis", [])]
        regioes = [Regiao(id=r["id"], nome=r["nome"], palavras=r.get("palavras", [])) for r in d.get("regioes", [])]
        areas = {mid: [normalizar(p) for p in palavras] for mid, palavras in (d.get("ministerios") or {}).items()}
        return cls(perfis, regioes, areas_ministerios=areas)

    @classmethod
    def carregar(cls, s: Session | None = None) -> "Classificador":
        c = cls.de_yaml()
        if s is not None:
            c.alertas = list(s.scalars(select(Alerta).where(Alerta.activo.is_(True))))
            # As áreas declaradas em estado.yaml complementam as palavras de impacto.yaml.
            for e in s.scalars(select(Entidade).where(Entidade.tipo == "ministerio")):
                extra = [normalizar(a).replace("_", " ") for a in (e.areas or [])]
                c.areas_ministerios[e.id] = list(dict.fromkeys(c.areas_ministerios.get(e.id, []) + extra))
            c._regex_ministerios = {}
        return c

    # ---- detecção ----------------------------------------------------
    def tipo_documento(self, texto_norm: str, sugerido: str | None = None) -> str:
        if sugerido:
            return sugerido
        for tipo, padrao in PADROES_TIPO:
            if padrao.search(texto_norm):
                return tipo
        return "noticia"

    def impacto(self, texto_norm: str) -> list[tuple[str, int]]:
        """Devolve [(perfil_id, n_ocorrencias)] ordenado por relevância."""
        res = []
        for p in self.perfis:
            n = len(p.regex().findall(texto_norm))
            if n:
                res.append((p.id, n))
        res.sort(key=lambda x: -x[1])
        return res

    def regioes_de(self, texto_norm: str) -> list[str]:
        return [r.id for r in self.regioes if r.regex().search(texto_norm)]

    def alertas_de(self, item: Item, texto_norm: str) -> list[str]:
        disparados = []
        for a in self.alertas:
            if a.entidades and item.entidade_id not in a.entidades and item.ministerio_id not in a.entidades:
                continue
            if a.tipos and item.tipo_documento not in a.tipos:
                continue
            palavras = [normalizar(p) for p in (a.palavras or []) if p]
            if palavras and not any(p in texto_norm for p in palavras):
                continue
            if not palavras and not a.entidades and not a.tipos:
                continue
            disparados.append(a.nome)
        return disparados

    def _regex_ministerio(self, mid: str) -> re.Pattern | None:
        if mid not in self._regex_ministerios:
            termos = sorted({t for t in self.areas_ministerios.get(mid, []) if t}, key=len, reverse=True)
            self._regex_ministerios[mid] = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(t) for t in termos) + r")(?![a-z0-9])") if termos else None
        return self._regex_ministerios[mid]

    def ministerio_por_tema(self, texto_norm: str) -> str | None:
        """Para fontes transversais (DR, AR, Governo) atribui o ministério com mais palavras-chave no texto."""
        melhor, pontos = None, 0
        for mid in self.areas_ministerios:
            rx = self._regex_ministerio(mid)
            if rx is None:
                continue
            n = len(rx.findall(texto_norm))
            if n > pontos:
                melhor, pontos = mid, n
        return melhor

    # ---- classificação completa --------------------------------------
    def classificar(self, item: Item, *, fonte: Fonte | None = None, tipo_sugerido: str | None = None) -> Item:
        texto = " ".join(x for x in (item.titulo, item.resumo, (item.conteudo or "")[:3000]) if x)
        tn = normalizar(texto)
        item.tipo_documento = self.tipo_documento(tn, tipo_sugerido)
        imp = self.impacto(tn)
        item.impacto = [p for p, _ in imp]
        item.regioes = self.regioes_de(tn)
        etiquetas = list(item.etiquetas or [])
        for nome in self.alertas_de(item, tn):
            etiquetas.append(f"alerta:{nome}")
        item.etiquetas = etiquetas or None
        transversal = fonte is not None and fonte.entidade.tipo in ("orgao_soberania", "governo", "outro") and fonte.entidade_id in ("diario-republica", "assembleia-republica", "governo", "consultalex", "participa", "base-gov")
        if transversal or item.ministerio_id in (None, "governo"):
            m = self.ministerio_por_tema(tn)
            if m:
                item.ministerio_id = m
        pesos = {p.id: p.peso for p in self.perfis}
        pontos = PESO_TIPO.get(item.tipo_documento, 0) + sum(min(n, 3) * pesos.get(pid, 1) for pid, n in imp)
        pontos += 3 * len([e for e in etiquetas if e.startswith("alerta:")])
        if fonte is not None:
            pontos += (fonte.prioridade or 5) / 5
        item.relevancia = round(float(pontos), 2)
        return item


def reclassificar_tudo(s: Session) -> int:
    c = Classificador.carregar(s)
    n = 0
    for item in s.scalars(select(Item)):
        c.classificar(item, fonte=item.fonte)
        n += 1
    s.commit()
    return n
