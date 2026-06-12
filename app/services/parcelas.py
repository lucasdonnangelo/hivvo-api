from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlmodel import Session

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.services.faturas import _data_vencimento_parcela


def _criar_parcelas(session: Session, transacao: Transacao, card: Optional[Cartao]) -> int:
    total = transacao.total_parcelas
    # Invariante: nenhuma parcela pode ficar <= 0 (T-33). Abaixo de 1 centavo
    # por parcela, a absorção da diferença pela última parcela a tornaria
    # zero ou negativa. A borda da API rejeita antes (422); este guard
    # protege qualquer outro chamador.
    if transacao.valor < total * Decimal("0.01"):
        raise ValueError(
            f"valor {transacao.valor} insuficiente para {total} parcelas: "
            "cada parcela deve ser de pelo menos R$ 0,01"
        )
    valor_base = (transacao.valor / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    valor_ultima = (transacao.valor - valor_base * (total - 1)).quantize(Decimal("0.01"))

    for i in range(1, total + 1):
        valor_parcela = valor_ultima if i == total else valor_base
        data_venc = _data_vencimento_parcela(transacao.data, i, card)

        parcela = Parcela(
            usuario_id=transacao.usuario_id,
            transacao_id=transacao.id,
            numero_parcela=i,
            total_parcelas=total,
            valor_parcela=valor_parcela,
            data_vencimento=data_venc,
            fatura_mes=data_venc.month,  # derivado da data_vencimento da parcela
            fatura_ano=data_venc.year,
            descricao=f"{transacao.descricao} ({i}/{total})",
            categoria=transacao.categoria,
            cartao_id=transacao.cartao_id,
        )
        session.add(parcela)

    # Sem commit aqui: o boundary (endpoint/chamador) commita — transação da
    # compra e parcelas persistem ou falham juntas (T-41)
    session.flush()
    return total
