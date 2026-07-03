import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

from sqlmodel import Session, select

from app.models.installment import Parcela
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao
from app.schemas.statistics import CategoriaStats
from app.services.recorrencias import valor_no_mes

_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class LancamentoFluxo:
    """Lançamento normalizado da visão FLUXO (a pagar por competência de fatura).

    Unifica as quatro fontes de :func:`_lancamentos_mes` (parcelas, avulsas de
    cartão faturadas, transações à vista/receitas e ocorrências de recorrência)
    num objeto simples com os campos que ``_agregar``/``_categorias`` consomem
    — sem expor se veio de uma Parcela, de uma Transacao ou de uma regra.

    ``recorrente=True`` marca ocorrência calculada de recorrência (Fase 2b) —
    a Fase 3 usa a flag para distinguir visualmente; a agregação a ignora.
    """

    tipo: str
    valor: Decimal
    categoria: str
    recorrente: bool = False


# _agregar/_categorias operam por duck typing em .tipo/.valor/.categoria — servem
# tanto LancamentoFluxo (fluxo mensal por competência) quanto Transacao cru
# (ainda usado por yearly_stats, que agrega por data da compra).
_Somavel = Union[Transacao, LancamentoFluxo]


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


def _agregar(itens: list[_Somavel]) -> tuple[Decimal, Decimal]:
    """Retorna (receitas, despesas) para uma lista de lançamentos."""
    receitas = sum((t.valor for t in itens if t.tipo == "receita"), _ZERO)
    despesas = sum((t.valor for t in itens if t.tipo == "despesa"), _ZERO)
    return receitas, despesas


def _categorias(itens: list[_Somavel]) -> list[CategoriaStats]:
    """Agrupa despesas por categoria com percentual do total."""
    despesas = [t for t in itens if t.tipo == "despesa"]
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


def _parcelas_competencia(
    session: Session, usuario_id: int, mes: int, ano: int
) -> list[Parcela]:
    """Parcelas cuja fatura vence na competência (mes, ano).

    Competência = fatura_mes/fatura_ano (materializados por VENCIMENTO). NÃO
    depende do campo `pago` (PLANO_PROJECAO §1.3: pago deixou de ser fonte de
    verdade) — só `cancelado`.
    """
    return session.exec(
        select(Parcela).where(
            Parcela.usuario_id == usuario_id,
            Parcela.fatura_mes == mes,
            Parcela.fatura_ano == ano,
            Parcela.cancelado == False,  # noqa: E712
        )
    ).all()


def _avulsas_cartao_competencia(
    session: Session, usuario_id: int, mes: int, ano: int
) -> list[Transacao]:
    """Despesas avulsas de cartão (não parceladas) faturadas na competência.

    Mesmo filtro das avulsas em invoices.py: parcelado=False, tipo='despesa',
    faturadas em (mes, ano) pela data de vencimento da compra.
    """
    return session.exec(
        select(Transacao).where(
            Transacao.usuario_id == usuario_id,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo == "despesa",
            Transacao.fatura_mes == mes,
            Transacao.fatura_ano == ano,
        )
    ).all()


def _recorrencias_com_vigencias(
    session: Session, usuario_id: int
) -> list[tuple[Recorrencia, list[RecorrenciaVigencia]]]:
    """Recorrências ATIVAS do usuário com suas vigências, em 2 queries fixas.

    Uma query para os cabeçalhos e uma para TODAS as vigências (IN sobre os
    ids), agrupadas em Python — sem N+1, reusável tanto pelo mensal quanto
    pelo anual (que aplica os 12 meses em memória). O filtro `ativa` evita
    carregar recorrências soft-deletadas; valor_no_mes segue como dupla guarda.
    """
    recorrencias = session.exec(
        select(Recorrencia).where(
            Recorrencia.usuario_id == usuario_id,
            Recorrencia.ativa == True,  # noqa: E712
        )
    ).all()
    if not recorrencias:
        return []  # evita IN () na query de vigências

    vigencias_por_rec: dict = {r.id: [] for r in recorrencias}
    for v in session.exec(
        select(RecorrenciaVigencia).where(
            RecorrenciaVigencia.recorrencia_id.in_(list(vigencias_por_rec))  # type: ignore[attr-defined]
        )
    ).all():
        vigencias_por_rec[v.recorrencia_id].append(v)

    return [(r, vigencias_por_rec[r.id]) for r in recorrencias]


def _ocorrencias_recorrentes(
    recs_com_vigencias: list[tuple[Recorrencia, list[RecorrenciaVigencia]]],
    mes: int,
    ano: int,
) -> list[LancamentoFluxo]:
    """Fonte 4 (pura, sem I/O): ocorrências de recorrência na competência (mes, ano).

    Recorrência não passa por fatura (PLANO §3.4) — conta por competência do
    MÊS direto, como a Fonte 3. Receita recorrente soma nas receitas, despesa
    nas despesas e no donut (via tipo/categoria); recorrente=True marca para a
    Fase 3.
    """
    lancamentos: list[LancamentoFluxo] = []
    for recorrencia, vigencias in recs_com_vigencias:
        valor = valor_no_mes(recorrencia, vigencias, mes, ano)
        if valor is not None:
            lancamentos.append(
                LancamentoFluxo(recorrencia.tipo, valor, recorrencia.categoria, recorrente=True)
            )
    return lancamentos


def _lancamentos_mes(
    session: Session, usuario_id: int, mes: int, ano: int
) -> list[LancamentoFluxo]:
    """Lançamentos da visão FLUXO ("a pagar neste mês") por competência de fatura.

    Une quatro fontes SEM dupla contagem (PLANO_PROJECAO §2 e §3.4):
      1. Parcelas com fatura em (mes, ano) — soma valor_parcela.
      2. Transações avulsas de cartão faturadas em (mes, ano).
      3. Transações à vista e receitas (não faturadas, não parceladas) por `data`.
      4. Ocorrências de recorrência ATIVA na competência (Fase 2b) — calculadas
         da regra (valor_no_mes), não materializadas; marcadas recorrente=True.

    Anti-dupla-contagem (§2.1): a transação-PAI de uma compra parcelada
    (parcelado=True, fatura_mes=None) e a avulsa já faturada NÃO somam na Fonte 3
    — quem soma são as parcelas (Fonte 1) e a avulsa na sua competência (Fonte 2).
    Resultado: o mês da compra deixa de mostrar o valor cheio (mostra a parcela
    daquele mês) e meses futuros deixam de ser zero.
    """
    lancamentos: list[LancamentoFluxo] = []

    # Fonte 3: à vista + receitas — não faturadas e não parceladas, pela data.
    for t in _buscar_mes(session, usuario_id, mes, ano):
        if t.parcelado or t.fatura_mes is not None:
            continue  # pai parcelada → Fonte 1; avulsa faturada → Fonte 2
        lancamentos.append(LancamentoFluxo(t.tipo, t.valor, t.categoria))

    # Fonte 1: parcelas na competência.
    for p in _parcelas_competencia(session, usuario_id, mes, ano):
        lancamentos.append(LancamentoFluxo("despesa", p.valor_parcela, p.categoria))

    # Fonte 2: avulsas de cartão faturadas na competência.
    for t in _avulsas_cartao_competencia(session, usuario_id, mes, ano):
        lancamentos.append(LancamentoFluxo(t.tipo, t.valor, t.categoria))

    # Fonte 4: ocorrências de recorrência na competência (Fase 2b).
    lancamentos.extend(
        _ocorrencias_recorrentes(_recorrencias_com_vigencias(session, usuario_id), mes, ano)
    )

    return lancamentos


def _lancamentos_ano(
    session: Session, usuario_id: int, ano: int
) -> dict[int, list[LancamentoFluxo]]:
    """Lançamentos da visão FLUXO do ano inteiro, agrupados por mês de competência.

    Mesma semântica de 4 fontes e anti-dupla-contagem de :func:`_lancamentos_mes`,
    mas escopada ao ano e resolvida em **5 queries fixas** (3 das fontes 1–3 + 2
    da recorrência) agrupadas em Python — evita o N+1 de chamar _lancamentos_mes
    12 vezes (usado por yearly_stats, o gráfico "Evolução mensal"). A recorrência
    é buscada UMA vez e valor_no_mes é aplicado aos 12 meses em memória.

    Uma compra parcelada que atravessa anos distribui corretamente: só as parcelas
    cuja fatura cai NESTE ano entram aqui (fatura_ano == ano).
    """
    por_mes: dict[int, list[LancamentoFluxo]] = {m: [] for m in range(1, 13)}

    # Fonte 3: à vista + receitas (não faturadas, não parceladas), pela data.
    inicio = dt.date(ano, 1, 1)
    fim = dt.date(ano + 1, 1, 1)
    for t in session.exec(
        select(Transacao).where(
            Transacao.usuario_id == usuario_id,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.fatura_mes == None,  # noqa: E711
            Transacao.data >= inicio,
            Transacao.data < fim,
        )
    ).all():
        por_mes[t.data.month].append(LancamentoFluxo(t.tipo, t.valor, t.categoria))

    # Fonte 1: parcelas com fatura no ano, agrupadas por fatura_mes.
    for p in session.exec(
        select(Parcela).where(
            Parcela.usuario_id == usuario_id,
            Parcela.fatura_ano == ano,
            Parcela.fatura_mes != None,  # noqa: E711
            Parcela.cancelado == False,  # noqa: E712
        )
    ).all():
        por_mes[p.fatura_mes].append(
            LancamentoFluxo("despesa", p.valor_parcela, p.categoria)
        )

    # Fonte 2: avulsas de cartão faturadas no ano, agrupadas por fatura_mes.
    for t in session.exec(
        select(Transacao).where(
            Transacao.usuario_id == usuario_id,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo == "despesa",
            Transacao.fatura_ano == ano,
            Transacao.fatura_mes != None,  # noqa: E711
        )
    ).all():
        por_mes[t.fatura_mes].append(LancamentoFluxo(t.tipo, t.valor, t.categoria))

    # Fonte 4: recorrências buscadas UMA vez; os 12 meses aplicados em memória.
    recs_com_vigencias = _recorrencias_com_vigencias(session, usuario_id)
    for m in range(1, 13):
        por_mes[m].extend(_ocorrencias_recorrentes(recs_com_vigencias, m, ano))

    return por_mes
