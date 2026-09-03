from __future__ import annotations

from .dre import AdaptadorDRE
from .html import AdaptadorHTML
from .parlamento import AdaptadorIniciativasAR
from .rss import AdaptadorRSS

ADAPTADORES = {
    "rss": AdaptadorRSS,
    "atom": AdaptadorRSS,
    "html": AdaptadorHTML,
    "dre": AdaptadorDRE,
    "parlamento_iniciativas": AdaptadorIniciativasAR,
    "json": AdaptadorDRE,  # leitor JSON genérico (mesmos campos tolerantes)
}


def adaptador_para(tipo: str):
    try:
        return ADAPTADORES[tipo]()
    except KeyError:
        raise ValueError(f"tipo de fonte desconhecido: {tipo}") from None
