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
