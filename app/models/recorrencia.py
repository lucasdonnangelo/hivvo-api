import datetime as dt
import uuid
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel, Column
from sqlalchemy import CheckConstraint, Numeric

from app.core.dates import agora


class Recorrencia(SQLModel, table=True):
    """Cabeçalho estável de uma receita/despesa recorrente (PLANO_PROJECAO §3.4).

    É a identidade ("meu salário") — NÃO guarda valor; o valor vive nas
    vigências (RecorrenciaVigencia), versionadas ao longo do tempo.
    `ativa=False` é soft delete. `frequencia` só aceita 'mensal' hoje, mas o
    campo existe para extensão futura (semanal/quinzenal) sem refazer o modelo.
    """

    __tablename__ = "recorrencias"
    __table_args__ = (
        CheckConstraint("tipo IN ('receita', 'despesa')", name="ck_recorrencias_tipo_valido"),
        CheckConstraint("dia_do_mes BETWEEN 1 AND 31", name="ck_recorrencias_dia_do_mes_valido"),
        CheckConstraint("frequencia = 'mensal'", name="ck_recorrencias_frequencia_valida"),
    )

    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    tipo: str  # "receita" | "despesa"
    categoria: str
    forma_pagamento: str  # sempre à vista/PIX — recorrência não passa por cartão (§3.4)
    frequencia: str = "mensal"
    dia_do_mes: int  # 1–31; clampado ao último dia do mês na ocorrência
    descricao: str
    ativa: bool = True
    data_criacao: dt.datetime = Field(default_factory=agora)


class RecorrenciaVigencia(SQLModel, table=True):
    """Uma versão de valor da recorrência, válida num período de competências.

    Período fechado em (ano_inicio, mes_inicio)..(ano_fim, mes_fim), comparado
    por tupla (ano, mes). mes_fim/ano_fim NULL = vigência aberta ("sem fim") —
    os dois nulos juntos ou ambos preenchidos (CHECK). Uma recorrência tem 1+
    vigências SEM sobreposição de períodos (invariante garantida na escrita —
    CRUD, Fase 2c).
    """

    __tablename__ = "recorrencia_vigencias"
    __table_args__ = (
        CheckConstraint("valor > 0", name="ck_rec_vigencias_valor_positivo"),
        CheckConstraint("mes_inicio BETWEEN 1 AND 12", name="ck_rec_vigencias_mes_inicio_valido"),
        CheckConstraint(
            "mes_fim IS NULL OR (mes_fim BETWEEN 1 AND 12)",
            name="ck_rec_vigencias_mes_fim_valido",
        ),
        CheckConstraint(
            "(mes_fim IS NULL) = (ano_fim IS NULL)", name="ck_rec_vigencias_fim_consistente"
        ),
    )

    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    recorrencia_id: uuid.UUID = Field(foreign_key="recorrencias.id", index=True)

    valor: Decimal = Field(sa_column=Column(Numeric(15, 2), nullable=False))
    mes_inicio: int
    ano_inicio: int
    mes_fim: Optional[int] = None
    ano_fim: Optional[int] = None
