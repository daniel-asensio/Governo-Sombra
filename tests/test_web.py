from sqlalchemy import select

from governo_sombra.models import Item, Posicao


def test_pagina_inicial(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "Para ti" in r.text
    assert "Vacinação contra a gripe" in r.text or "Decreto-Lei" in r.text


def test_feed_filtros_e_pesquisa(cliente):
    assert cliente.get("/feed").status_code == 200
    r = cliente.get("/feed", params={"tipo": "legislacao"})
    assert "Decreto-Lei n.º 55/2026" in r.text
    assert "Vacinação" not in r.text
    r = cliente.get("/feed", params={"q": "arrendamento"})
    assert "Decreto-Lei n.º 55/2026" in r.text
    r = cliente.get("/feed", params={"perfil": "utente_sns"})
    assert "taxas moderadoras" in r.text
    r = cliente.get("/feed", params={"ministerio": "ministerio-saude"})
    assert "Vacinação" in r.text


def test_item_e_posicao_sombra(cliente, bd_com_dados):
    with bd_com_dados.sessao_ctx() as s:
        item = s.scalar(select(Item).where(Item.titulo.like("Decreto-Lei%")))
        iid = item.id
    r = cliente.get(f"/item/{iid}")
    assert r.status_code == 200 and "Comentar como governo sombra" in r.text
    r = cliente.post("/sombra/posicao/nova", data={"titulo": "Limite de 2% é insuficiente", "texto": "Propomos indexar ao IPC com tecto de 1,5%.", "tipo": "alternativa", "avaliacao": "-1", "entidade_id": "ministerio-infraestruturas-habitacao", "item_id": str(iid)}, follow_redirects=False)
    assert r.status_code == 303
    r = cliente.get(f"/item/{iid}")
    assert "Limite de 2% é insuficiente" in r.text
    r = cliente.get("/sombra/ministerio-infraestruturas-habitacao")
    assert "Limite de 2%" in r.text
    assert cliente.get("/sombra").status_code == 200
    with bd_com_dados.sessao_ctx() as s:
        assert s.scalar(select(Posicao)).item_id == iid


def test_estado_e_entidade(cliente):
    r = cliente.get("/estado")
    assert "Ministério das Finanças" in r.text and "Autoridade Tributária" in r.text
    r = cliente.get("/estado/ministerio-saude")
    assert r.status_code == 200 and "Vacinação" in r.text
    assert cliente.get("/estado/nao-existe").status_code == 404


def test_perfil_altera_para_ti(cliente):
    r = cliente.post("/perfil", data={"perfis": ["estudante"], "palavras": "propinas"}, follow_redirects=False)
    assert r.status_code == 303
    r = cliente.get("/api/para-ti")
    titulos = [i["titulo"] for i in r.json()["itens"]]
    assert any("propinas" in t.lower() for t in titulos)


def test_alertas_calendario_fontes_api_rss(cliente):
    assert cliente.get("/alertas").status_code == 200
    r = cliente.post("/alertas", data={"nome": "Habitação", "palavras": "renda, arrendamento"}, follow_redirects=False)
    assert r.status_code == 303
    assert "Habitação" in cliente.get("/alertas").text
    assert cliente.get("/calendario").status_code == 200
    assert "IRS" in cliente.get("/calendario?todos=true").text
    r = cliente.get("/fontes")
    assert r.status_code == 200 and "sns-noticias" not in r.text or "SNS - Notícias" in r.text
    api = cliente.get("/api/itens", params={"tipo": "iniciativa"}).json()
    assert api["total"] == 2
    assert cliente.get("/api/entidades").json()[0]["id"] == "presidencia-republica"
    rss = cliente.get("/rss.xml")
    assert rss.status_code == 200 and rss.text.startswith("<?xml")
    assert cliente.get("/saude").json()["ok"] is True


def test_digest(bd_com_dados):
    from datetime import date

    from governo_sombra.digest import gerar_digest

    with bd_com_dados.sessao_ctx() as s:
        texto, _ = gerar_digest(s, dia=date(2026, 9, 4), guardar=False)
    assert texto.startswith("# Governo Sombra")
    assert "Por ministério" in texto


def test_manifest_e_senha(cliente, monkeypatch):
    from governo_sombra.config import definicoes

    assert cliente.get("/manifest.json").json()["name"] == "Governo Sombra"
    monkeypatch.setattr(definicoes, "password", "segredo")
    assert cliente.get("/").status_code == 401
    assert cliente.get("/saude").status_code == 200
    assert cliente.get("/", auth=("eu", "segredo")).status_code == 200
    assert cliente.get("/", auth=("eu", "errada")).status_code == 401


def test_diagnostico_e_alterar_url(cliente, bd_com_dados):
    from governo_sombra.ingest.diagnostico import diagnosticar
    from governo_sombra.models import Fonte

    r = cliente.post("/fontes/sns-noticias/url", data={"url": "http://127.0.0.1:9/x", "tipo": "html"}, follow_redirects=False)
    assert r.status_code == 303
    with bd_com_dados.sessao_ctx() as s:
        f = s.get(Fonte, "sns-noticias")
        assert f.tipo == "html" and f.url == "http://127.0.0.1:9/x"
        d = diagnosticar(f)
        assert d["estado"] == "erro"
    assert cliente.post("/fontes/sns-noticias/diagnosticar", follow_redirects=False).status_code == 303
    assert cliente.get("/fontes").status_code == 200


def test_html_heuristico():
    from governo_sombra.ingest.html import AdaptadorHTML

    html = """<html><body><nav><a href='/'>Início</a></nav><div class='xyz'>
    <a href='/n/1'>Governo aprova novo regime de apoio ao arrendamento jovem</a> <span>02-09-2026</span>
    <a href='/n/2'>Abertas candidaturas ao programa de bolsas de investigação</a>
    <a href='https://outro.site/x'>Ligação externa com um título comprido também</a>
    <a href='/n/3'>Ver mais</a></div></body></html>""".encode("utf-8")
    itens = AdaptadorHTML().recolher("https://exemplo.gov.pt/noticias", {"selectores": {"item": ".nada"}}, corpo=html)
    assert [i.url for i in itens] == ["https://exemplo.gov.pt/n/1", "https://exemplo.gov.pt/n/2"]
    assert itens[0].publicado_em.year == 2026
