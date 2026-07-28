import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.core.dates import hoje


class ImportExtratoLote(SQLModel, table=True):
    """Guard de idempotência da importação de EXTRATO — Batch 3.

    Um registro por extrato importado, na chave natural
    (usuario_id, banco, periodo_de, periodo_ate). O commit INSERE o lote
    PRIMEIRO, na mesma transação de banco: a violação do UNIQUE é o mecanismo
    atômico que bloqueia reimportar o mesmo extrato (409) — fecha a corrida de
    duplo-clique/retry que um EXISTS pré-checado deixaria aberta. Mesmo padrão
    de ImportFaturaLote; o que muda é a chave (o extrato é da CONTA, não de um
    cartão — por isso NÃO há cartao_id aqui, e o período é quem identifica).

    `banco` é gravado NORMALIZADO (services/import_extrato/persistencia.
    normalizar_banco): o nome vem de texto livre extraído pelo LLM, e sem
    normalizar "Nubank"/"nubank "/"NuBank" furariam o UNIQUE. Resíduo conhecido
    (documentado em PENDENCIAS): se o modelo devolver nomes de banco
    ESTRUTURALMENTE distintos entre dois exports do mesmo extrato ("Nubank" vs
    "Nu Pagamentos S.A."), o guard escapa — o período é o sinal forte da chave.

    O lote só BLOQUEIA; o link transacao→lote (para o "substituir" futuro) fica
    para uma batch seguinte, como no lote de fatura.
    """

    __tablename__ = "import_extrato_lote"
    __table_args__ = (
        UniqueConstraint(
            "usuario_id", "banco", "periodo_de", "periodo_ate",
            name="uq_import_extrato_lote_periodo",
        ),
        CheckConstraint(
            "periodo_de <= periodo_ate", name="ck_import_extrato_lote_periodo_ordenado"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    banco: str
    periodo_de: dt.date
    periodo_ate: dt.date

    criada_em: dt.date = Field(default_factory=hoje)
