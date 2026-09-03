from sqlalchemy import select

from governo_sombra.models import Entidade, Fonte, MinistroSombra


def test_seed_carrega_arvore(bd):
    with bd.sessao_ctx() as s:
        mf = s.get(Entidade, "ministerio-financas")
        assert mf.parent_id == "governo"
        assert any(f.id == "autoridade-tributaria" for f in mf.filhos)
        at = s.get(Entidade, "autoridade-tributaria")
        assert at.ministerio().id == "ministerio-financas"
        assert [e.id for e in at.caminho()] == ["governo", "ministerio-financas", "autoridade-tributaria"]


def test_fontes_apontam_para_entidades_existentes(bd):
    with bd.sessao_ctx() as s:
        for f in s.scalars(select(Fonte)):
            assert s.get(Entidade, f.entidade_id) is not None, f.id


def test_seed_e_idempotente(bd):
    from governo_sombra.seed import seed_tudo

    with bd.sessao_ctx() as s:
        m = s.scalar(select(MinistroSombra).where(MinistroSombra.entidade_id == "ministerio-saude"))
        m.nome = "Alguém"
        s.commit()
        r1 = seed_tudo(s)
        r2 = seed_tudo(s)
        assert r1 == r2
        assert s.scalar(select(MinistroSombra).where(MinistroSombra.entidade_id == "ministerio-saude")).nome == "Alguém"
