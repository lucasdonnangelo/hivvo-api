import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint

from app.core.dates import hoje


class NotificacaoEnvio(SQLModel, table=True):
    """Registro de envio de notificação — guard de idempotência (#6, Batch 1).

    Uma linha por (usuário, dia, tipo). É o que responde "este usuário já
    recebeu o aviso de hoje?" sem que a resposta dependa de o job rodar uma
    vez só: o UNIQUE é o mecanismo, não um EXISTS pré-checado. Mesmo padrão
    que a importação já provou (:class:`ImportExtratoLote`) e pelo mesmo
    motivo — um EXISTS lido antes do INSERT deixa aberta a janela entre a
    leitura e a escrita, e duas execuções simultâneas mandariam dois e-mails.

    A ordem em services/notificacoes/envio.py é INSERE (flush, sem commit) →
    ENVIA → COMMITA. Falha no envio faz rollback: nada fica gravado, e a
    execução seguinte tenta de novo. O contrário (commitar antes de enviar)
    consumiria o direito ao aviso sem que o aviso saísse.

    `data_referencia` é o "hoje" DA EXECUÇÃO no fuso do produto (core.dates.
    hoje), não a data de vencimento avisada — o alvo é derivável dela
    (hoje + DIAS_DE_ANTECEDENCIA) e a regra de negócio é "um e-mail por
    usuário POR DIA", que é exatamente esta coluna.

    `tipo` é String e não Enum de propósito: o aviso de FECHAMENTO de fatura
    (adiado por decisão de produto) entra como outro valor, sem migration.
    """

    __tablename__ = "notificacao_envio"
    __table_args__ = (
        UniqueConstraint(
            "usuario_id", "data_referencia", "tipo",
            name="uq_notificacao_envio_usuario_dia_tipo",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    data_referencia: dt.date
    tipo: str

    criado_em: dt.date = Field(default_factory=hoje)
