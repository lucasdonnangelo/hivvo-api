import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.core.dates import hoje


class ImportFaturaLote(SQLModel, table=True):
    """Guard de idempotência da importação de fatura — Batch 2.

    Um registro por fatura importada, na chave natural
    (usuario_id, cartao_id, fatura_mes, fatura_ano) onde a competência é a
    ÂNCORA da fatura (mês de vencimento). O commit INSERE o lote PRIMEIRO,
    na mesma transação de banco: a violação do UNIQUE é o mecanismo atômico
    que bloqueia reimportar a mesma fatura (409) — fecha a corrida de
    duplo-clique/retry que um EXISTS pré-checado deixaria aberta.

    Nesta batch o lote só BLOQUEIA; o link transacao→lote (para o
    "substituir" futuro) fica para uma batch seguinte.
    """

    __tablename__ = "import_fatura_lote"
    __table_args__ = (
        UniqueConstraint(
            "usuario_id", "cartao_id", "fatura_mes", "fatura_ano",
            name="uq_import_fatura_lote_competencia",
        ),
        CheckConstraint(
            "fatura_mes BETWEEN 1 AND 12", name="ck_import_fatura_lote_mes_valido"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    cartao_id: int = Field(foreign_key="cartoes.id")

    fatura_mes: int
    fatura_ano: int

    criada_em: dt.date = Field(default_factory=hoje)
