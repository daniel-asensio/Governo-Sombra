"""Resumos e classificação assistida por Claude (opcional).

Requer `pip install anthropic` e ANTHROPIC_API_KEY no ambiente. Cada item é
resumido em linguagem corrente, com uma explicação de porque importa e a que
perfis afecta. Usa structured outputs para garantir JSON válido.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import definicoes
from ..models import Item

SISTEMA = (
    "És um analista de políticas públicas portuguesas. Recebes um documento ou notícia "
    "de uma entidade da administração pública portuguesa e explicas, em português europeu, "
    "claro e sem jargão, o que é, o que muda e quem é afectado. Sê concreto: datas, valores, "
    "prazos, obrigações novas. Se o texto for apenas um título sem substância, diz isso."
)


class AnaliseItem(BaseModel):
    resumo: str = Field(description="Resumo em 2 a 4 frases, português europeu, linguagem corrente.")
    porque_importa: str = Field(description="Uma ou duas frases sobre o efeito prático no dia-a-dia das pessoas. 'Sem efeito prático directo' se aplicável.")
    perfis_afectados: list[str] = Field(description="Ids de perfis afectados, escolhidos apenas da lista fornecida.")
    tipo_documento: str = Field(description="Um dos tipos de documento fornecidos.")
    urgencia: int = Field(ge=0, le=3, description="0 informativo, 1 convém saber, 2 exige atenção ou tem prazo, 3 muda obrigações ou direitos já.")


def disponivel() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def analisar_item(item: Item, perfis_ids: list[str], tipos: list[str], modelo: str | None = None) -> AnaliseItem:
    import anthropic

    client = anthropic.Anthropic()
    texto = "\n\n".join(x for x in (f"Título: {item.titulo}", f"Entidade: {item.entidade.nome}" if item.entidade else None, f"Resumo: {item.resumo}" if item.resumo else None, f"Conteúdo: {(item.conteudo or '')[:12000]}" if item.conteudo else None, f"URL: {item.url}" if item.url else None) if x)
    pedido = (
        f"Perfis possíveis: {', '.join(perfis_ids)}\n"
        f"Tipos de documento possíveis: {', '.join(tipos)}\n\n"
        f"Documento:\n{texto}"
    )
    resposta = client.messages.parse(
        model=modelo or definicoes.ia_modelo,
        max_tokens=2048,
        system=SISTEMA,
        messages=[{"role": "user", "content": pedido}],
        output_format=AnaliseItem,
    )
    if resposta.stop_reason == "refusal":
        raise RuntimeError("o modelo recusou analisar este item")
    return resposta.parsed_output


def resumir_pendentes(s: Session, *, limite: int = 20, relevancia_minima: float = 3.0, modelo: str | None = None) -> int:
    from .rules import Classificador

    c = Classificador.de_yaml()
    perfis_ids = [p.id for p in c.perfis]
    from ..models import TIPOS_DOCUMENTO

    tipos = list(TIPOS_DOCUMENTO)
    q = (
        select(Item)
        .where(Item.resumo_ia.is_(None), Item.relevancia >= relevancia_minima)
        .order_by(Item.relevancia.desc(), Item.recolhido_em.desc())
        .limit(limite)
    )
    n = 0
    for item in s.scalars(q):
        analise = analisar_item(item, perfis_ids, tipos, modelo)
        item.resumo_ia = analise.resumo
        item.porque_importa = analise.porque_importa
        validos = [p for p in analise.perfis_afectados if p in perfis_ids]
        if validos:
            item.impacto = sorted(set((item.impacto or []) + validos), key=lambda x: (x not in validos, x))
        if analise.tipo_documento in tipos and item.tipo_documento in ("noticia", "outro"):
            item.tipo_documento = analise.tipo_documento
        item.relevancia = round(item.relevancia + 2 * analise.urgencia, 2)
        s.commit()
        n += 1
    return n
