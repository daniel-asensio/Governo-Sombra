"""Resumo diário em Markdown (e envio opcional por email)."""

from __future__ import annotations

import logging
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy.orm import Session

from .classify.rules import Classificador
from .config import DIR_VAR, definicoes
from .models import TIPOS_DOCUMENTO
from .web import queries

log = logging.getLogger("governo_sombra.digest")


def gerar_digest(s: Session, *, dia: date | None = None, guardar: bool = True) -> tuple[str, Path | None]:
    dia = dia or date.today()
    p = queries.perfil(s)
    c = Classificador.de_yaml()
    nomes_perfis = {pp.id: pp.nome for pp in c.perfis}
    desde = dia - timedelta(days=1)
    itens, _ = queries.filtrar_itens(s, desde=desde, ate=dia, limite=500)
    para_ti = [i for i in queries.para_ti(s, p, dias=2, limite=15)]
    eventos = queries.eventos_proximos(s, p, dias=14)
    linhas = [f"# Governo Sombra: resumo de {dia.strftime('%d/%m/%Y')}", ""]
    linhas.append(f"{len(itens)} itens recolhidos nas últimas 24 h.")
    linhas.append("")
    if para_ti:
        linhas.append("## Para ti")
        for i in para_ti:
            ent = i.entidade.sigla or i.entidade.nome if i.entidade else i.entidade_id
            linhas.append(f"- **{i.titulo}** ({ent}, {TIPOS_DOCUMENTO.get(i.tipo_documento, i.tipo_documento)})")
            if i.porque_importa:
                linhas.append(f"  - {i.porque_importa}")
            elif i.resumo:
                linhas.append(f"  - {i.resumo[:200]}")
            if i.impacto:
                linhas.append(f"  - afecta: {', '.join(nomes_perfis.get(x, x) for x in i.impacto[:4])}")
            if i.url:
                linhas.append(f"  - {i.url}")
        linhas.append("")
    datados = [ev for ev in eventos if ev["inicio"]]
    if datados:
        linhas.append("## Prazos nos próximos 14 dias")
        for ev in datados:
            quando = ev["inicio"].strftime("%d/%m") + (f" a {ev['fim'].strftime('%d/%m')}" if ev["fim"] != ev["inicio"] else "")
            extra = f" (a decorrer, faltam {ev['dias']} dias)" if ev["a_decorrer"] else ""
            linhas.append(f"- {quando}: {ev['evento'].titulo}{extra}")
        linhas.append("")
    por_min: dict[str, list] = {}
    for i in itens:
        chave = (i.ministerio.nome if i.ministerio else (i.entidade.nome if i.entidade else i.entidade_id))
        por_min.setdefault(chave, []).append(i)
    if por_min:
        linhas.append("## Por ministério / órgão")
        for nome, lista in sorted(por_min.items(), key=lambda kv: -len(kv[1])):
            linhas.append(f"### {nome} ({len(lista)})")
            for i in sorted(lista, key=lambda x: -x.relevancia)[:8]:
                linhas.append(f"- [{TIPOS_DOCUMENTO.get(i.tipo_documento, i.tipo_documento)}] {i.titulo}" + (f" — {i.url}" if i.url else ""))
            linhas.append("")
    texto = "\n".join(linhas)
    caminho = None
    if guardar:
        pasta = DIR_VAR / "digests"
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"{dia.isoformat()}.md"
        caminho.write_text(texto, encoding="utf-8")
    return texto, caminho


def enviar_email(assunto: str, corpo: str) -> bool:
    if not (definicoes.smtp_host and definicoes.email_destino):
        return False
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = definicoes.smtp_user or definicoes.email_destino
    msg["To"] = definicoes.email_destino
    msg.set_content(corpo)
    with smtplib.SMTP(definicoes.smtp_host, definicoes.smtp_port) as smtp:
        smtp.starttls()
        if definicoes.smtp_user and definicoes.smtp_password:
            smtp.login(definicoes.smtp_user, definicoes.smtp_password)
        smtp.send_message(msg)
    log.info("digest enviado para %s", definicoes.email_destino)
    return True
