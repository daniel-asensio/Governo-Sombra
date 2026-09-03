from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "data"
DIR_VAR = RAIZ / "var"


class Definicoes(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GS_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{DIR_VAR / 'governo_sombra.db'}"
    scheduler: bool = False
    ingest_interval_min: int = 60
    user_agent: str = "GovernoSombra/0.1 (+https://github.com/daniel-asensio/Governo-Sombra)"
    http_timeout: float = 30.0
    ia_modelo: str = "claude-opus-5"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_destino: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    password: str | None = None  # GS_PASSWORD: protege a aplicação quando está na internet


definicoes = Definicoes()
