import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def bd(tmp_path):
    from governo_sombra import db

    db.reset_engine(f"sqlite:///{tmp_path / 'teste.db'}")
    db.criar_esquema()
    from governo_sombra.seed import seed_tudo

    with db.sessao_ctx() as s:
        seed_tudo(s)
    yield db
    db.reset_engine()


@pytest.fixture()
def bd_com_dados(bd):
    from governo_sombra.ingest import recolher_tudo

    from governo_sombra.models import Fonte

    ids = ["sns-noticias", "ine-destaques", "dre-serie-1", "governo-comunicados-cm", "ar-iniciativas"]
    with bd.sessao_ctx() as s:
        for fid in ids:
            f = s.get(Fonte, fid)
            f.activa = True
            if fid == "governo-comunicados-cm":
                f.tipo = "html"  # a fixture é HTML
        recolher_tudo(s, apenas=ids, dir_fixtures=FIXTURES)
    return bd


@pytest.fixture()
def cliente(bd_com_dados):
    from fastapi.testclient import TestClient

    from governo_sombra.web.app import app

    with TestClient(app) as c:
        yield c
