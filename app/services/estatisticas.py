import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

from sqlmodel import Session, and_, or_, select

from app.core.dates import hoje
from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao
from app.schemas.statistics import CategoriaStats
from app.services.faturas import vencimento_avulsa
from app.services.recorrencias import data_ocorrencia, valor_no_mes

_ZERO = Decimal("0.00")

# Horizonte de exibição futuro (PLANO §6.5): a busca do "primeiro mês com
# fluxo" do mês default varre no máximo o corrente + 60 meses à frente.
HORIZONTE_MESES = 60


@dataclass(frozen=True)
class LancamentoFluxo:
    """Lançamento normalizado da visão FLUXO (a pagar por competência de fatura).

    Unifica as quatro fontes de :func:`_lancamentos_mes` (parcelas, avulsas de
    cartão faturadas, transações à vista/receitas e ocorrências de recorrência)
    num objeto simples com os campos que ``_agregar``/``_categorias`` consomem
    — sem expor se veio de uma Parcela, de uma Transacao ou de uma regra.

    ``recorrente=True`` marca ocorrência calculada de recorrência (Fase 2b) —
    a Fase 3 usa a flag para distinguir visualmente; a agregação a ignora.

    ``realizado`` (§1.3.1): no MÊS CORRENTE, True se a ocorrência já aconteceu
    (dia/vencimento <= hoje, fronteira inclusiva) — as Fontes 1 (parcelas, por
    data_vencimento), 2 (avulsas, por vencimento derivado do cartão) e 4
    (recorrência, por data_ocorrencia) são cortadas; a Fonte 3 é sempre
    realizada (§1.3.2: à vista já ocorreu por definição). Em mês NÃO-corrente
    é sempre True (passado ocorreu; futuro é projeção integral — realizado ==
    projeção, a_vir = 0). Invariante: projeção = realizado + a_vir, por
    construção (marcação, não filtro — a projeção agrega TODOS os lançamentos).

    ``a_pagar`` (§"A pagar e Saldo" — eixo saída-já-ocorrida × a-ocorrer):
    True só para CRÉDITO que ainda não saiu do caixa. Desde a Leva 2
    (PLANO_3D_PAGAMENTO_FATURA), a fonte é a FATURA: um lançamento de cartão
    (Fonte 1 parcela e Fonte 2 avulsa) está pago ⇔ a fatura dele
    (cartao_id + fatura_mes/ano) tem PagamentoFatura com pago=True — senão
    conta em a_pagar, esteja a vencer OU atrasada (a presunção "avulsa
    vencida = paga" morreu; Parcela.pago está OBSOLETO e não é mais lido).
    Parcela SEM cartão (carnê) não tem fatura confirmável → presunção por
    vencimento (data_vencimento > hoje). À vista/receitas (Fonte 3) e
    recorrência (Fonte 4, à vista por definição) saem no ato → nunca a_pagar.
    Eixo INDEPENDENTE do `realizado` (tempo-no-mês-corrente ≠ dívida-de-
    crédito) e regra única por lançamento, sem olhar se o mês é corrente.
    FRONTEIRA do pagamento: a marcação a_pagar é o ÚNICO consumidor de
    PagamentoFatura em toda a projeção — topo, realizado/a_vir, anual, série
    e consumo derivam exclusivamente de data/competência (§1.3: pagamento
    não governa a projeção).
    """

    tipo: str
    valor: Decimal
    categoria: str
    recorrente: bool = False
    realizado: bool = True
    a_pagar: bool = False


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


def _soma_a_pagar(itens: list[LancamentoFluxo]) -> Decimal:
    """Total "A pagar" do mês: só crédito cuja saída ainda não ocorreu."""
    return sum((l.valor for l in itens if l.a_pagar), _ZERO)


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


def _cartoes_por_id(session: Session, usuario_id: int) -> dict[int, Cartao]:
    """Cartões do usuário indexados por id — 1 query, para a Fonte 2 derivar
    o vencimento das avulsas sem N+1. Só é chamada quando há avulsas."""
    return {
        c.id: c
        for c in session.exec(select(Cartao).where(Cartao.usuario_id == usuario_id))
    }


def _faturas_pagas_mes(
    session: Session, usuario_id: int, mes: int, ano: int
) -> set[int]:
    """cartao_ids com fatura CONFIRMADA PAGA (PagamentoFatura.pago=True) na
    competência — 1 query, só chamada quando há lançamentos de cartão."""
    return set(
        session.exec(
            select(PagamentoFatura.cartao_id).where(
                PagamentoFatura.usuario_id == usuario_id,
                PagamentoFatura.fatura_mes == mes,
                PagamentoFatura.fatura_ano == ano,
                PagamentoFatura.pago == True,  # noqa: E712
            )
        ).all()
    )


def _faturas_pagas_ano(
    session: Session, usuario_id: int, ano: int
) -> dict[int, set[int]]:
    """{fatura_mes: {cartao_ids pagos}} do ano — a variante anual de
    _faturas_pagas_mes, em 1 query fixa (padrão do _lancamentos_ano)."""
    pagas: dict[int, set[int]] = {m: set() for m in range(1, 13)}
    for mes, cartao_id in session.exec(
        select(PagamentoFatura.fatura_mes, PagamentoFatura.cartao_id).where(
            PagamentoFatura.usuario_id == usuario_id,
            PagamentoFatura.fatura_ano == ano,
            PagamentoFatura.pago == True,  # noqa: E712
        )
    ).all():
        pagas[mes].add(cartao_id)
    return pagas


def _parcela_a_pagar(parcela: Parcela, pagas: set[int], h) -> bool:
    """Regra a_pagar da Fonte 1 (Leva 2): COM cartão, segue a fatura
    (não confirmada = a_pagar, a vencer ou atrasada); SEM cartão (carnê,
    sem fatura confirmável), presunção por vencimento."""
    if parcela.cartao_id is not None:
        return parcela.cartao_id not in pagas
    return parcela.data_vencimento > h


def _recorrencias_com_vigencias(
    session: Session, usuario_id: int
) -> list[tuple[Recorrencia, list[RecorrenciaVigencia]]]:
    """Recorrências do usuário com suas vigências, em 2 queries fixas.

    Uma query para os cabeçalhos e uma para TODAS as vigências (IN sobre os
    ids), agrupadas em Python — sem N+1, reusável tanto pelo mensal quanto
    pelo anual (que aplica os 12 meses em memória).

    NÃO filtra `ativa` (Fase 2c): a projeção depende só das vigências —
    recorrência encerrada tem a vigência fechada no encerramento, então o
    passado continua gerando e o futuro para sozinho. `ativa` é flag de
    estado/listagem (routers), não de projeção.
    """
    recorrencias = session.exec(
        select(Recorrencia).where(Recorrencia.usuario_id == usuario_id)
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
    limite_realizado: Optional[dt.date] = None,
) -> list[LancamentoFluxo]:
    """Fonte 4 (pura, sem I/O): ocorrências de recorrência na competência (mes, ano).

    Recorrência não passa por fatura (PLANO §3.4) — conta por competência do
    MÊS direto, como a Fonte 3. Receita recorrente soma nas receitas, despesa
    nas despesas e no donut (via tipo/categoria); recorrente=True marca para a
    Fase 3.

    `limite_realizado` (§1.3.1): setado APENAS quando (mes, ano) é o mês
    corrente — marca realizado = data_ocorrencia (dia clampado) <= hoje.
    None (mês não-corrente) = tudo realizado. NÃO filtra: a ocorrência entra
    na lista de qualquer forma (a projeção é integral).
    """
    lancamentos: list[LancamentoFluxo] = []
    for recorrencia, vigencias in recs_com_vigencias:
        valor = valor_no_mes(recorrencia, vigencias, mes, ano)
        if valor is not None:
            realizado = (
                limite_realizado is None
                or data_ocorrencia(recorrencia, mes, ano) <= limite_realizado
            )
            lancamentos.append(
                LancamentoFluxo(
                    recorrencia.tipo,
                    valor,
                    recorrencia.categoria,
                    recorrente=True,
                    realizado=realizado,
                )
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
      4. Ocorrências de recorrência na competência (Fase 2b) — calculadas da
         regra (valor_no_mes, só vigências), não materializadas; marcadas
         recorrente=True.

    Anti-dupla-contagem (§2.1): a transação-PAI de uma compra parcelada
    (parcelado=True, fatura_mes=None) e a avulsa já faturada NÃO somam na Fonte 3
    — quem soma são as parcelas (Fonte 1) e a avulsa na sua competência (Fonte 2).
    Resultado: o mês da compra deixa de mostrar o valor cheio (mostra a parcela
    daquele mês) e meses futuros deixam de ser zero.

    Corte por dia (§1.3.1): no mês CORRENTE, Fontes 1, 2 e 4 marcam realizado
    por dia/vencimento <= hoje (marcação, não filtro — a lista completa é a
    projeção). A Fonte 3 é sempre realizada (§1.3.2).

    Eixo a_pagar (§"A pagar e Saldo", regra da Leva 2): lançamento de cartão
    (Fonte 1 e 2) segue a FATURA — a_pagar enquanto a fatura não tem
    PagamentoFatura pago=True (atrasada CONTINUA a pagar; confirmada sai,
    inclusive antecipada). Parcela sem cartão: presunção por vencimento.
    Fontes 3/4 nunca (saem no ato). Parcela.pago está OBSOLETO — não é lido.
    """
    h = hoje()
    corrente = (ano, mes) == (h.year, h.month)
    lancamentos: list[LancamentoFluxo] = []

    # Fonte 3: à vista + receitas — não faturadas e não parceladas, pela data.
    # Sempre realizada (§1.3.2: à vista já ocorreu por definição, mesmo com
    # data futura) e nunca a_pagar.
    for t in _buscar_mes(session, usuario_id, mes, ano):
        if t.parcelado or t.fatura_mes is not None:
            continue  # pai parcelada → Fonte 1; avulsa faturada → Fonte 2
        lancamentos.append(LancamentoFluxo(t.tipo, t.valor, t.categoria))

    parcelas = _parcelas_competencia(session, usuario_id, mes, ano)
    avulsas = _avulsas_cartao_competencia(session, usuario_id, mes, ano)
    # Pagamentos confirmados da competência — 1 query, só quando há
    # lançamento de cartão para marcar (ÚNICO ponto da projeção que lê
    # PagamentoFatura — fronteira, ver LancamentoFluxo).
    tem_cartao = bool(avulsas) or any(p.cartao_id is not None for p in parcelas)
    pagas = _faturas_pagas_mes(session, usuario_id, mes, ano) if tem_cartao else set()

    # Fonte 1: parcelas na competência — realizado pelo VENCIMENTO real (dia
    # exato) no mês corrente, não pelo fatura_mes (§1.3.2); a_pagar enquanto
    # a fatura não está confirmada paga (sem cartão: vencimento).
    for p in parcelas:
        realizado = (not corrente) or p.data_vencimento <= h
        lancamentos.append(
            LancamentoFluxo(
                "despesa",
                p.valor_parcela,
                p.categoria,
                realizado=realizado,
                a_pagar=_parcela_a_pagar(p, pagas, h),
            )
        )

    # Fonte 2: avulsas de cartão faturadas na competência — vencimento REAL
    # derivado do dia_vencimento do cartão corta o realizado no mês corrente;
    # a_pagar segue a fatura (não confirmada = a_pagar, mesmo vencida).
    cartoes = _cartoes_por_id(session, usuario_id) if avulsas else {}
    for t in avulsas:
        venc = vencimento_avulsa(cartoes.get(t.cartao_id), mes, ano)
        lancamentos.append(
            LancamentoFluxo(
                t.tipo,
                t.valor,
                t.categoria,
                realizado=(not corrente) or venc <= h,
                a_pagar=t.cartao_id not in pagas if t.cartao_id is not None
                else venc > h,
            )
        )

    # Fonte 4: ocorrências de recorrência na competência (Fase 2b); no mês
    # corrente, realizado por data_ocorrencia <= hoje.
    lancamentos.extend(
        _ocorrencias_recorrentes(
            _recorrencias_com_vigencias(session, usuario_id),
            mes,
            ano,
            limite_realizado=h if corrente else None,
        )
    )

    return lancamentos


def _lancamentos_consumo_mes(
    session: Session, usuario_id: int, mes: int, ano: int
) -> list[LancamentoFluxo]:
    """Lançamentos da visão CONSUMO ("gastei neste mês") pela DATA da compra.

    PLANO_PROJECAO §1.1 e §"Fase 3b": a compra parcelada conta INTEIRA no mês da
    COMPRA (transação-PAI pelo valor cheio), não fatiada por competência de
    fatura. Une duas fontes SEM dupla contagem:
      C1. TODAS as transações do mês por `data` — a pai parcelada pelo valor
          cheio, a avulsa de cartão pela data (não pela fatura), à vista e
          receitas. Cada Transacao conta UMA vez; as parcelas (fatias de fluxo)
          NÃO entram → sem dupla contagem. Reusa `_buscar_mes` SEM o `continue`
          de pai-parcelada/faturada que a Fonte 3 do fluxo aplica.
      C4. Ocorrências de recorrência na competência do mês — IDÊNTICA ao fluxo
          (recorrência não passa por fatura, §3.4); reusa a Fonte 4.

    Diferença para :func:`_lancamentos_mes` (fluxo): aqui NÃO há Fonte 1
    (parcelas por fatura) nem a competência-de-fatura da Fonte 2. Consumo é
    INTEGRAL (§Fase 3b D2): sem realizado/a_vir — `realizado` fica no default e
    é ignorado. Receita coincide entre as visões; só a despesa com fatura
    (parcelada + avulsa de cartão) muda de mês.

    Limitação (Opção A, §Fase 3b): não reflete cancelamento por-parcela
    (`Parcela.cancelado`) — a pai não tem flag de cancelado. A invariante
    Σparcelas==consumo vale no caso limpo e sob DELETE da compra inteira (pai +
    parcelas somem juntas); diverge só sob cancelamento de parcela individual.
    ⚠️ Se cancelamento por-parcela virar operação de usuário (UI + rota viva),
    revisitar (Opção B) — ver §Fase 3b.
    """
    lancamentos: list[LancamentoFluxo] = [
        LancamentoFluxo(t.tipo, t.valor, t.categoria)
        for t in _buscar_mes(session, usuario_id, mes, ano)
    ]
    lancamentos.extend(
        _ocorrencias_recorrentes(
            _recorrencias_com_vigencias(session, usuario_id), mes, ano
        )
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

    Corte por dia (§1.3.1): a MESMA marcação de realizado do mensal se aplica ao
    mês corrente dentro do ano — as flags não divergem entre card e gráfico. A
    série anual continua sendo a PROJEÇÃO integral (agrega todos os lançamentos).
    """
    h = hoje()
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
    parcelas = session.exec(
        select(Parcela).where(
            Parcela.usuario_id == usuario_id,
            Parcela.fatura_ano == ano,
            Parcela.fatura_mes != None,  # noqa: E711
            Parcela.cancelado == False,  # noqa: E712
        )
    ).all()

    # Fonte 2: avulsas de cartão faturadas no ano, agrupadas por fatura_mes —
    # mesmas marcações do mensal (vencimento derivado do cartão), para as
    # flags nunca divergirem entre card e gráfico/série.
    avulsas = session.exec(
        select(Transacao).where(
            Transacao.usuario_id == usuario_id,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo == "despesa",
            Transacao.fatura_ano == ano,
            Transacao.fatura_mes != None,  # noqa: E711
        )
    ).all()

    # Pagamentos confirmados do ano — 1 query fixa, só quando há lançamento
    # de cartão (mesma regra a_pagar do mensal: as flags nunca divergem).
    tem_cartao = bool(avulsas) or any(p.cartao_id is not None for p in parcelas)
    pagas_ano = (
        _faturas_pagas_ano(session, usuario_id, ano)
        if tem_cartao
        else {m: set() for m in range(1, 13)}
    )

    for p in parcelas:
        realizado = (ano, p.fatura_mes) != (h.year, h.month) or p.data_vencimento <= h
        por_mes[p.fatura_mes].append(
            LancamentoFluxo(
                "despesa",
                p.valor_parcela,
                p.categoria,
                realizado=realizado,
                a_pagar=_parcela_a_pagar(p, pagas_ano[p.fatura_mes], h),
            )
        )

    cartoes = _cartoes_por_id(session, usuario_id) if avulsas else {}
    for t in avulsas:
        venc = vencimento_avulsa(cartoes.get(t.cartao_id), t.fatura_mes, ano)
        realizado = (ano, t.fatura_mes) != (h.year, h.month) or venc <= h
        por_mes[t.fatura_mes].append(
            LancamentoFluxo(
                t.tipo,
                t.valor,
                t.categoria,
                realizado=realizado,
                a_pagar=t.cartao_id not in pagas_ano[t.fatura_mes]
                if t.cartao_id is not None
                else venc > h,
            )
        )

    # Fonte 4: recorrências buscadas UMA vez; os 12 meses aplicados em memória.
    # O limite de realizado só vale para o mês corrente dentro deste ano.
    recs_com_vigencias = _recorrencias_com_vigencias(session, usuario_id)
    for m in range(1, 13):
        limite = h if (ano, m) == (h.year, h.month) else None
        por_mes[m].extend(
            _ocorrencias_recorrentes(recs_com_vigencias, m, ano, limite_realizado=limite)
        )

    return por_mes


def _mes_seguinte(mes: int, ano: int) -> tuple[int, int]:
    """Competência seguinte a (mes, ano), com virada dez → jan do ano seguinte."""
    if mes == 12:
        return 1, ano + 1
    return mes + 1, ano


def _tem_historico(session: Session, usuario_id: int, mes: int, ano: int) -> bool:
    """Existe lançamento de FLUXO com competência ANTERIOR a (mes, ano)?

    Usa a MESMA noção de competência das quatro fontes de _lancamentos_mes
    (PLANO §"Mês default do Dashboard"): parcelas (Fonte 1) e avulsas
    faturadas (Fonte 2) por fatura_mes/ano, à vista/receitas (Fonte 3) por
    data, recorrência (Fonte 4) pela vigência — vigência que COMEÇOU em
    competência passada gerou ocorrência lá (o início é a primeira competência
    gerada; fim >= início por invariante). A transação-PAI parcelada não conta
    (§2.1 — quem conta são as parcelas). 4 consultas de existência (LIMIT 1),
    com curto-circuito no primeiro achado.
    """
    inicio_mes = dt.date(ano, mes, 1)

    # Fonte 3: à vista + receitas, pela data.
    fonte3 = select(Transacao.id).where(
        Transacao.usuario_id == usuario_id,
        Transacao.parcelado == False,  # noqa: E712
        Transacao.fatura_mes == None,  # noqa: E711
        Transacao.data < inicio_mes,
    )
    # Fontes 1 e 2: competência de fatura < (ano, mes), por tupla.
    fonte1 = select(Parcela.id).where(
        Parcela.usuario_id == usuario_id,
        Parcela.cancelado == False,  # noqa: E712
        Parcela.fatura_mes != None,  # noqa: E711
        or_(
            Parcela.fatura_ano < ano,
            and_(Parcela.fatura_ano == ano, Parcela.fatura_mes < mes),
        ),
    )
    fonte2 = select(Transacao.id).where(
        Transacao.usuario_id == usuario_id,
        Transacao.parcelado == False,  # noqa: E712
        Transacao.tipo == "despesa",
        Transacao.fatura_mes != None,  # noqa: E711
        or_(
            Transacao.fatura_ano < ano,
            and_(Transacao.fatura_ano == ano, Transacao.fatura_mes < mes),
        ),
    )
    # Fonte 4: vigência de recorrência iniciada em competência passada.
    fonte4 = (
        select(RecorrenciaVigencia.id)
        .join(Recorrencia, Recorrencia.id == RecorrenciaVigencia.recorrencia_id)  # type: ignore[arg-type]
        .where(
            Recorrencia.usuario_id == usuario_id,
            or_(
                RecorrenciaVigencia.ano_inicio < ano,
                and_(
                    RecorrenciaVigencia.ano_inicio == ano,
                    RecorrenciaVigencia.mes_inicio < mes,
                ),
            ),
        )
    )
    return any(
        session.exec(q.limit(1)).first() is not None
        for q in (fonte3, fonte1, fonte2, fonte4)
    )


def mes_default(
    session: Session, usuario_id: int
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Mês em que o Dashboard ABRE por padrão — ((mes, ano) fluxo, (mes, ano) consumo).

    Regra do FLUXO (PLANO §"Mês default do Dashboard"):
      1. TEM HISTÓRICO (lançamento com competência < mês corrente) → corrente.
      2. Senão → PRIMEIRO mês, do corrente até corrente + HORIZONTE_MESES, que
         TEM FLUXO. Reusa _lancamentos_ano ano a ano — a MESMA projeção, zero
         drift de definição; multi-cartão sai de graça (cada compra já está na
         fatura certa via fatura_mes). Todo lançamento tem valor > 0 (CHECK no
         banco), então "tem fluxo" == lista não-vazia. Só usuários SEM
         histórico chegam aqui (base pequena por definição — custo trivial).
      3. Sem fluxo em lugar nenhum → mês seguinte (fallback neutro).

    CONSUMO: sempre o mês corrente (o gasto do mês é sempre relevante). Um
    único hoje() de referência para as duas visões. Isto define só onde a
    tela abre — a navegação segue livre.
    """
    h = hoje()
    corrente = (h.month, h.year)
    if _tem_historico(session, usuario_id, h.month, h.year):
        return corrente, corrente

    achado = _primeiro_mes_com_fluxo(
        session, usuario_id, h.month, h.year, HORIZONTE_MESES + 1
    )  # corrente + 60 à frente
    return achado or _mes_seguinte(*corrente), corrente


def _primeiro_mes_com_fluxo(
    session: Session, usuario_id: int, mes: int, ano: int, limite: int
) -> Optional[tuple[int, int]]:
    """Primeiro mês, de (mes, ano) em diante, que TEM FLUXO — ou None.

    Varre no máximo `limite` competências reusando _lancamentos_ano ano a ano
    (a MESMA projeção, zero drift de definição); "tem fluxo" == lista
    não-vazia (todo lançamento tem valor > 0 por CHECK no banco). Compartilhado
    por mes_default (a partir do corrente) e inicio_projecao (a partir do
    seguinte).
    """
    por_mes: dict[int, list[LancamentoFluxo]] = {}
    ano_carregado: Optional[int] = None
    for _ in range(limite):
        if ano != ano_carregado:
            por_mes = _lancamentos_ano(session, usuario_id, ano)
            ano_carregado = ano
        if por_mes[mes]:
            return mes, ano
        mes, ano = _mes_seguinte(mes, ano)
    return None


def inicio_projecao(session: Session, usuario_id: int) -> tuple[int, int]:
    """(mes, ano) em que a série do Bloco 2 COMEÇA — o destaque da projeção.

    PLANO §"PROJEÇÃO (Bloco 2)": o primeiro mês FUTURO (>= corrente + 1) com
    fluxo — NUNCA o mês corrente (esse é o Bloco 1, evita duplicação) e
    independe de haver histórico. Fallback: o mês seguinte, se não há fluxo
    em nenhum dos HORIZONTE_MESES à frente.
    """
    h = hoje()
    seguinte = _mes_seguinte(h.month, h.year)
    achado = _primeiro_mes_com_fluxo(
        session, usuario_id, *seguinte, HORIZONTE_MESES
    )
    return achado or seguinte
