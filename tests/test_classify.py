from sqlalchemy import select

from governo_sombra.classify.rules import Classificador, normalizar
from governo_sombra.models import Alerta, Fonte, Item


def test_normalizar():
    assert normalizar("Orçamento  do ESTADO") == "orcamento do estado"


def test_impacto_e_tipo():
    c = Classificador.de_yaml()
    item = Item(titulo="Portaria aprova nova tabela de retenção na fonte de IRS para pensões", resumo=None, entidade_id="x", fonte_id="y", guid="g")
    c.classificar(item)
    assert item.tipo_documento == "despacho"
    assert "contribuinte" in item.impacto
    assert "reformado_pensionista" in item.impacto
    assert item.relevancia > 0


def test_regioes_e_ministerio_por_tema(bd_com_dados):
    with bd_com_dados.sessao_ctx() as s:
        rcm = s.scalar(select(Item).where(Item.titulo.like("Resolução do Conselho de Ministros%")))
        assert "algarve" in rcm.regioes
        assert "ambiente" in rcm.impacto
        assert rcm.ministerio_id == "ministerio-ambiente-energia"
        dl = s.scalar(select(Item).where(Item.titulo.like("Decreto-Lei%")))
        assert dl.ministerio_id == "ministerio-infraestruturas-habitacao"
        assert {"inquilino", "jovem"} <= set(dl.impacto)
        cm = s.scalar(select(Item).where(Item.fonte_id == "governo-comunicados-cm").order_by(Item.publicado_em.desc()))
        assert cm.tipo_documento == "conselho_ministros"
        assert cm.ministerio_id in ("ministerio-financas", "ministerio-ambiente-energia")


def test_alertas_etiquetam(bd):
    from governo_sombra.classify.rules import reclassificar_tudo
    from governo_sombra.ingest import recolher_tudo

    from .conftest import FIXTURES

    with bd.sessao_ctx() as s:
        s.add(Alerta(nome="Gripe", palavras=["vacinação contra a gripe"], entidades=[], tipos=[]))
        s.get(Fonte, "sns-noticias").activa = True
        s.commit()
        recolher_tudo(s, apenas=["sns-noticias"], dir_fixtures=FIXTURES)
        it = s.scalar(select(Item).where(Item.titulo.like("Vacinação%")))
        assert "alerta:Gripe" in it.etiquetas
        assert reclassificar_tudo(s) == 2
