from datetime import datetime

from sqlalchemy import select

from governo_sombra.ingest.base import interpretar_data
from governo_sombra.ingest.dre import classificar_diploma
from governo_sombra.models import Fonte, Item

from .conftest import FIXTURES


def test_interpretar_datas():
    assert interpretar_data("2026-09-03T10:15:00") == datetime(2026, 9, 3, 10, 15)
    assert interpretar_data("Wed, 02 Sep 2026 10:00:00 +0100") == datetime(2026, 9, 2, 9, 0)
    assert interpretar_data("03/09/2026") == datetime(2026, 9, 3)
    assert interpretar_data("3 de setembro de 2026") == datetime(2026, 9, 3)
    assert interpretar_data("sem data") is None


def test_classificar_diploma():
    assert classificar_diploma("Decreto-Lei n.º 55/2026") == ("legislacao", "Decreto-Lei")
    assert classificar_diploma("Portaria n.º 300/2026") == ("despacho", "Portaria")
    assert classificar_diploma("Resolução do Conselho de Ministros n.º 90/2026")[0] == "conselho_ministros"
    assert classificar_diploma("Pesquisa avançada") == ("outro", None)


def test_ingest_fixtures_cria_itens(bd_com_dados):
    with bd_com_dados.sessao_ctx() as s:
        itens = list(s.scalars(select(Item)))
        assert len(itens) == 2 + 1 + 3 + 2 + 2
        por_fonte = {}
        for i in itens:
            por_fonte.setdefault(i.fonte_id, []).append(i)
        assert len(por_fonte["dre-serie-1"]) == 3
        dl = next(i for i in por_fonte["dre-serie-1"] if i.titulo.startswith("Decreto-Lei"))
        assert dl.tipo_documento == "legislacao"
        assert dl.url.startswith("https://diariodarepublica.pt/")
        assert "Presidência do Conselho de Ministros" in (dl.extra or {}).get("emissor", "")
        assert dl.publicado_em == datetime(2026, 9, 3)
        ini = por_fonte["ar-iniciativas"]
        assert any("Projeto de Lei 412" in i.titulo for i in ini)
        assert all(i.tipo_documento == "iniciativa" for i in ini)
        f = s.get(Fonte, "sns-noticias")
        assert f.ultimo_erro is None and f.total_itens == 2 and f.verificada


def test_ingest_e_idempotente(bd_com_dados):
    from governo_sombra.ingest import recolher_tudo

    with bd_com_dados.sessao_ctx() as s:
        antes = s.scalar(select(Item.id).order_by(Item.id.desc()).limit(1))
        ex = recolher_tudo(s, apenas=["sns-noticias", "dre-serie-1"], dir_fixtures=FIXTURES)
        assert ex.novos == 0
        assert s.scalar(select(Item.id).order_by(Item.id.desc()).limit(1)) == antes


def test_fonte_com_erro_regista_erro(bd):
    from governo_sombra.ingest import recolher_tudo

    with bd.sessao_ctx() as s:
        f = s.get(Fonte, "sns-noticias")
        f.url = "http://127.0.0.1:9/nao-existe"
        f.activa = True
        s.commit()
        ex = recolher_tudo(s, apenas=["sns-noticias"])
        assert ex.erros == 1
        assert s.get(Fonte, "sns-noticias").ultimo_erro


def test_rss_datas_invalidas_nao_rebentam():
    from governo_sombra.ingest.rss import AdaptadorRSS

    itens = AdaptadorRSS().recolher("https://x", {}, corpo=(FIXTURES / "data-invalida.xml").read_bytes())
    assert len(itens) == 2
    assert itens[0].publicado_em is None
    assert itens[1].publicado_em == datetime(2026, 9, 3, 9, 0)
    assert len(AdaptadorRSS().recolher("https://x", {"maximo": 1}, corpo=(FIXTURES / "data-invalida.xml").read_bytes())) == 1
