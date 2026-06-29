import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlmodel import Session, select

from app.models.transaction import Transacao
from app.schemas.statistics import CategoriaStats

_ZERO = Decimal("0.00")


def _variacao(atual: Decimal, anterior: Decimal) -> Optional[Decimal]:
    """Retorna variação percentual; None se não há dados anteriores.

    O denominador usa abs(anterior): com base negativa, o sinal da variação
    deve refletir melhora/piora (−100 → −50 é +50%), não inverter (T-38).
    """
    if anterior == _ZERO:
        return None
    return ((atual - anterior) / abs(anterior) * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _agregar(transacoes: list[Transacao]) -> tuple[Decimal, Decimal]:
    """Retorna (receitas, despesas) para uma lista de transações."""
    receitas = sum((t.valor for t in transacoes if t.tipo == "receita"), _ZERO)
    despesas = sum((t.valor for t in transacoes if t.tipo == "despesa"), _ZERO)
    return receitas, despesas


def _categorias(transacoes: list[Transacao]) -> list[CategoriaStats]:
    """Agrupa despesas por categoria com percentual do total."""
    despesas = [t for t in transacoes if t.tipo == "despesa"]
    total = sum((t.valor for t in despesas), _ZERO)
    if not total:
        return []

    grupos: dict[str, Decimal] = {}
    for t in despesas:
        grupos[t.categoria] = grupos.get(t.categoria, _ZERO) + t.valor

    return sorted(
        [
            CategoriaStats(
                categoria=cat,
                total=val,
                percentual=(val / total * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )
            for cat, val in grupos.items()
        ],
        key=lambda x: x.total,
        reverse=True,
    )


def _buscar_mes(session: Session, usuario_id: int, mes: int, ano: int) -> list[Transacao]:
    # T-10: range de datas (sargável) em vez de extract(month/year) — habilita o
    # índice (usuario_id, data). Mesmas linhas de antes: [1º dia do mês, 1º dia do
    # mês seguinte). Dezembro avança para janeiro do ano seguinte.
    inicio = dt.date(ano, mes, 1)
    fim = dt.date(ano + 1, 1, 1) if mes == 12 else dt.date(ano, mes + 1, 1)
    return session.exec(
        select(Transacao).where(
            Transacao.usuario_id == usuario_id,
            Transacao.data >= inicio,
            Transacao.data < fim,
        )
    ).all()
