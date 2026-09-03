from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

import httpx

from ..config import definicoes


@dataclass
class ItemBruto:
    """Um item tal como sai de uma fonte, antes de classificação."""

    titulo: str
    url: str | None = None
    guid: str | None = None
    resumo: str | None = None
    conteudo: str | None = None
    publicado_em: datetime | None = None
    tipo_documento: str | None = None
    extra: dict = field(default_factory=dict)

    def chave(self) -> str:
        base = self.guid or self.url or self.titulo
        return base.strip()[:600] if len(base) <= 600 else hashlib.sha1(base.encode("utf-8")).hexdigest()


class Adaptador(Protocol):
    def recolher(self, url: str, config: dict, corpo: bytes | None = None) -> list[ItemBruto]: ...


class ErroFonte(RuntimeError):
    pass


CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 " + definicoes.user_agent,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.5",
}


def obter(url: str, *, fixture: Path | None = None, verificar_tls: bool = True) -> bytes:
    """Descarrega o URL (ou lê um ficheiro local em modo fixture).

    Muitos sites do Estado têm cadeias de certificados incompletas; se a
    verificação TLS falhar, tenta uma segunda vez sem verificação (o conteúdo
    é público e só de leitura, o risco é baixo e fica registado no log).
    """
    if fixture is not None:
        return Path(fixture).read_bytes()

    def _pedir(verify: bool) -> bytes:
        with httpx.Client(headers=CABECALHOS, timeout=definicoes.http_timeout, follow_redirects=True, verify=verify) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.content

    try:
        return _pedir(verificar_tls)
    except httpx.ConnectError as e:
        if verificar_tls and "CERTIFICATE_VERIFY_FAILED" in str(e):
            logging.getLogger("governo_sombra.ingest").warning("%s: certificado inválido, a ler sem verificação TLS", url)
            try:
                return _pedir(False)
            except httpx.HTTPError as e2:
                raise ErroFonte(f"{type(e2).__name__}: {e2}") from e2
        raise ErroFonte(f"{type(e).__name__}: {e}") from e
    except httpx.HTTPError as e:
        raise ErroFonte(f"{type(e).__name__}: {e}") from e


_MESES_PT = {
    "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "março": 3, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4, "maio": 5, "mai": 5, "junho": 6, "jun": 6, "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8, "setembro": 9, "set": 9, "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12,
}


def interpretar_data(texto: str | None) -> datetime | None:
    """Tenta perceber datas em vários formatos comuns nos sites do Estado."""
    if not texto:
        return None
    t = texto.strip()
    if not t:
        return None
    # ISO 8601
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", t)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        h, mi, s = int(m[4] or 0), int(m[5] or 0), int(m[6] or 0)
        try:
            return datetime(y, mo, d, h, mi, s)
        except ValueError:
            return None
    # RFC 2822 (RSS)
    try:
        dt = parsedate_to_datetime(t)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (TypeError, ValueError, IndexError):
        pass
    # dd-mm-yyyy ou dd/mm/yyyy
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:\D+(\d{1,2}):(\d{2}))?", t)
    if m:
        try:
            return datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4] or 0), int(m[5] or 0))
        except ValueError:
            return None
    # "3 de setembro de 2026" / "3 set 2026"
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?([A-Za-zçÇ]+)\.?\s+(?:de\s+)?(\d{4})", t)
    if m and m[2].lower() in _MESES_PT:
        try:
            return datetime(int(m[3]), _MESES_PT[m[2].lower()], int(m[1]))
        except ValueError:
            return None
    return None


def limpar_texto(t: str | None, maximo: int = 4000) -> str | None:
    if t is None:
        return None
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:maximo] if t else None
