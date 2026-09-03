from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


TIPOS_ENTIDADE = {
    "orgao_soberania": "Órgão de soberania",
    "governo": "Governo",
    "ministerio": "Ministério",
    "secretaria_estado": "Secretaria de Estado",
    "direcao_geral": "Direção-Geral",
    "instituto": "Instituto público",
    "regulador": "Entidade reguladora",
    "autoridade": "Autoridade",
    "empresa_publica": "Empresa pública",
    "tribunal": "Tribunal",
    "inspecao": "Inspeção-Geral",
    "forca_seguranca": "Força de segurança",
    "outro": "Outra entidade",
}

TIPOS_DOCUMENTO = {
    "legislacao": "Legislação",
    "despacho": "Despacho / portaria / aviso",
    "comunicado": "Comunicado",
    "conselho_ministros": "Conselho de Ministros",
    "iniciativa": "Iniciativa legislativa",
    "agenda": "Agenda",
    "votacao": "Votação",
    "consulta_publica": "Consulta pública",
    "concurso": "Concurso / apoio / candidatura",
    "contrato": "Contrato público",
    "nomeacao": "Nomeação / exoneração",
    "estatistica": "Estatística",
    "alerta": "Alerta / aviso",
    "acordao": "Acórdão / decisão",
    "relatorio": "Relatório",
    "noticia": "Notícia",
    "outro": "Outro",
}

TIPOS_POSICAO = {
    "apoio": "Apoio",
    "critica": "Crítica",
    "alternativa": "Proposta alternativa",
    "pergunta": "Pergunta ao Governo",
    "comentario": "Comentário",
    "proposta": "Proposta própria",
}


class Entidade(Base):
    __tablename__ = "entidades"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    sigla: Mapped[str | None] = mapped_column(String(40))
    tipo: Mapped[str] = mapped_column(String(40), default="outro")
    url: Mapped[str | None] = mapped_column(String(500))
    titular: Mapped[str | None] = mapped_column(String(200))
    descricao: Mapped[str | None] = mapped_column(Text)
    areas: Mapped[list | None] = mapped_column(JSON)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("entidades.id"))
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped["Entidade | None"] = relationship(remote_side=[id], back_populates="filhos")
    filhos: Mapped[list["Entidade"]] = relationship(back_populates="parent", order_by="Entidade.ordem")
    fontes: Mapped[list["Fonte"]] = relationship(back_populates="entidade")

    def ministerio(self) -> "Entidade | None":
        """Sobe a árvore até encontrar o ministério (ou o órgão de topo)."""
        e = self
        while e is not None:
            if e.tipo in ("ministerio", "orgao_soberania", "governo") or e.parent is None:
                return e
            e = e.parent
        return None

    def caminho(self) -> list["Entidade"]:
        cadeia = []
        e = self
        while e is not None:
            cadeia.append(e)
            e = e.parent
        return list(reversed(cadeia))


class Fonte(Base):
    __tablename__ = "fontes"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    entidade_id: Mapped[str] = mapped_column(ForeignKey("entidades.id"))
    nome: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(800))
    config: Mapped[dict | None] = mapped_column(JSON)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    verificada: Mapped[bool] = mapped_column(Boolean, default=False)
    prioridade: Mapped[int] = mapped_column(Integer, default=5)
    ultima_recolha: Mapped[datetime | None] = mapped_column(DateTime)
    ultimo_sucesso: Mapped[datetime | None] = mapped_column(DateTime)
    ultimo_erro: Mapped[str | None] = mapped_column(Text)
    total_itens: Mapped[int] = mapped_column(Integer, default=0)

    entidade: Mapped[Entidade] = relationship(back_populates="fontes")
    itens: Mapped[list["Item"]] = relationship(back_populates="fonte")

    @property
    def estado(self) -> str:
        if not self.activa:
            return "inactiva"
        if self.ultima_recolha is None:
            return "nunca"
        if self.ultimo_erro:
            return "erro"
        return "ok"


class Item(Base):
    __tablename__ = "itens"
    __table_args__ = (UniqueConstraint("fonte_id", "guid", name="uq_item_fonte_guid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fonte_id: Mapped[str] = mapped_column(ForeignKey("fontes.id"))
    entidade_id: Mapped[str] = mapped_column(ForeignKey("entidades.id"))
    ministerio_id: Mapped[str | None] = mapped_column(ForeignKey("entidades.id"))
    guid: Mapped[str] = mapped_column(String(600))
    url: Mapped[str | None] = mapped_column(String(1000))
    titulo: Mapped[str] = mapped_column(String(600))
    resumo: Mapped[str | None] = mapped_column(Text)
    conteudo: Mapped[str | None] = mapped_column(Text)
    tipo_documento: Mapped[str] = mapped_column(String(40), default="outro")
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    recolhido_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    impacto: Mapped[list | None] = mapped_column(JSON)
    regioes: Mapped[list | None] = mapped_column(JSON)
    etiquetas: Mapped[list | None] = mapped_column(JSON)
    relevancia: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    resumo_ia: Mapped[str | None] = mapped_column(Text)
    porque_importa: Mapped[str | None] = mapped_column(Text)
    lido: Mapped[bool] = mapped_column(Boolean, default=False)
    guardado: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict | None] = mapped_column(JSON)

    fonte: Mapped[Fonte] = relationship(back_populates="itens")
    entidade: Mapped[Entidade] = relationship(foreign_keys=[entidade_id])
    ministerio: Mapped[Entidade | None] = relationship(foreign_keys=[ministerio_id])
    posicoes: Mapped[list["Posicao"]] = relationship(back_populates="item", cascade="all, delete-orphan")

    @property
    def data(self) -> datetime:
        return self.publicado_em or self.recolhido_em


class MinistroSombra(Base):
    __tablename__ = "ministros_sombra"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entidade_id: Mapped[str] = mapped_column(ForeignKey("entidades.id"), unique=True)
    nome: Mapped[str] = mapped_column(String(200))
    cargo: Mapped[str] = mapped_column(String(200))
    bio: Mapped[str | None] = mapped_column(Text)
    prioridades: Mapped[list | None] = mapped_column(JSON)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    entidade: Mapped[Entidade] = relationship()
    posicoes: Mapped[list["Posicao"]] = relationship(back_populates="autor")


class Posicao(Base):
    """Uma tomada de posição do governo sombra sobre um item ou um tema."""

    __tablename__ = "posicoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("itens.id", ondelete="CASCADE"))
    entidade_id: Mapped[str] = mapped_column(ForeignKey("entidades.id"))
    autor_id: Mapped[int | None] = mapped_column(ForeignKey("ministros_sombra.id"))
    tipo: Mapped[str] = mapped_column(String(30), default="comentario")
    titulo: Mapped[str] = mapped_column(String(300))
    texto: Mapped[str] = mapped_column(Text)
    avaliacao: Mapped[int] = mapped_column(Integer, default=0)  # -2 (muito mau) .. +2 (muito bom)
    estado: Mapped[str] = mapped_column(String(20), default="publicada")  # rascunho | publicada
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    actualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)

    item: Mapped[Item | None] = relationship(back_populates="posicoes")
    entidade: Mapped[Entidade] = relationship()
    autor: Mapped[MinistroSombra | None] = relationship(back_populates="posicoes")


class Alerta(Base):
    """Lista de vigilância: palavras-chave, entidades e tipos que interessam."""

    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(200))
    palavras: Mapped[list | None] = mapped_column(JSON)
    entidades: Mapped[list | None] = mapped_column(JSON)
    tipos: Mapped[list | None] = mapped_column(JSON)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Perfil(Base):
    """Perfil do utilizador (aplicação de utilizador único)."""

    __tablename__ = "perfil"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    nome: Mapped[str | None] = mapped_column(String(120))
    perfis: Mapped[list | None] = mapped_column(JSON, default=list)
    regioes: Mapped[list | None] = mapped_column(JSON, default=list)
    entidades_seguidas: Mapped[list | None] = mapped_column(JSON, default=list)
    palavras: Mapped[list | None] = mapped_column(JSON, default=list)


class EventoCalendario(Base):
    __tablename__ = "calendario"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    titulo: Mapped[str] = mapped_column(String(300))
    quando: Mapped[str] = mapped_column(String(60))
    entidade_id: Mapped[str | None] = mapped_column(ForeignKey("entidades.id"))
    perfis: Mapped[list | None] = mapped_column(JSON)
    descricao: Mapped[str | None] = mapped_column(Text)

    entidade: Mapped[Entidade | None] = relationship()

    def intervalo(self, ano: int) -> tuple[date, date] | None:
        """Devolve (inicio, fim) no ano dado, ou None para eventos semanais."""
        if ":" in self.quando:
            return None
        if ".." in self.quando:
            a, b = self.quando.split("..")
        else:
            a = b = self.quando
        ma, da = (int(x) for x in a.split("-"))
        mb, db = (int(x) for x in b.split("-"))
        return date(ano, ma, da), date(ano, mb, db)


class Execucao(Base):
    """Registo de cada corrida de ingestão."""

    __tablename__ = "execucoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, default=agora)
    fim: Mapped[datetime | None] = mapped_column(DateTime)
    fontes: Mapped[int] = mapped_column(Integer, default=0)
    novos: Mapped[int] = mapped_column(Integer, default=0)
    erros: Mapped[int] = mapped_column(Integer, default=0)
    detalhes: Mapped[dict | None] = mapped_column(JSON)


class Tarefa(Base):
    """Trabalho em segundo plano (recolha, descoberta, diagnóstico) e o seu estado."""

    __tablename__ = "tarefas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(30), index=True)
    alvo: Mapped[str | None] = mapped_column(String(80))
    estado: Mapped[str] = mapped_column(String(20), default="a_correr")  # a_correr | ok | erro
    inicio: Mapped[datetime] = mapped_column(DateTime, default=agora)
    fim: Mapped[datetime | None] = mapped_column(DateTime)
    detalhes: Mapped[dict | None] = mapped_column(JSON)
