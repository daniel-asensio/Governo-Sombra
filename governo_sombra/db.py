from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import definicoes

_engine = None
_SessionLocal = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = definicoes.database_url
        if url.startswith("sqlite:///"):
            caminho = url.removeprefix("sqlite:///")
            if caminho and caminho != ":memory:":
                Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True, connect_args={"check_same_thread": False, "timeout": 60} if url.startswith("sqlite") else {})
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _pragmas(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=60000")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine(url: str | None = None) -> None:
    """Usado em testes para apontar para outra base de dados."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if url:
        definicoes.database_url = url


def sessao() -> Session:
    engine()
    return _SessionLocal()


@contextmanager
def sessao_ctx():
    s = sessao()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def criar_esquema() -> None:
    from . import models  # noqa: F401

    eng = engine()
    models.Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS itens_fts USING fts5("
                "titulo, resumo, conteudo, content='itens', content_rowid='id', tokenize='unicode61 remove_diacritics 2')"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS itens_ai AFTER INSERT ON itens BEGIN "
                "INSERT INTO itens_fts(rowid, titulo, resumo, conteudo) VALUES (new.id, new.titulo, new.resumo, new.conteudo); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS itens_ad AFTER DELETE ON itens BEGIN "
                "INSERT INTO itens_fts(itens_fts, rowid, titulo, resumo, conteudo) VALUES ('delete', old.id, old.titulo, old.resumo, old.conteudo); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS itens_au AFTER UPDATE ON itens BEGIN "
                "INSERT INTO itens_fts(itens_fts, rowid, titulo, resumo, conteudo) VALUES ('delete', old.id, old.titulo, old.resumo, old.conteudo); "
                "INSERT INTO itens_fts(rowid, titulo, resumo, conteudo) VALUES (new.id, new.titulo, new.resumo, new.conteudo); END"
            )
        )
