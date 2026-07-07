import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

from sqlmodel import Session, and_, or_, select

from app.core.dates import hoje
from app.models.installment import Parcela
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao
from app.schemas.statistics import CategoriaStats
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
    (dia/vencimento <= hoje, fronteira inclusiva) — só as Fontes 1 (parcelas,
    por data_vencimento) e 4 (recorrência, por data_ocorrencia) são cortadas;
    Fontes 2/3 são sempre realizadas (§1.3.2). Em mês NÃO-corrente é sempre
    True (passado ocorreu; futuro é projeção integral — realizado == projeção,
    a_vir = 0). Invariante: projeção = realizado + a_vir, por construção
    (marcação, não filtro — a projeção agrega TODOS os lançamentos).
    """

    tipo: str
    valor: Decimal
    categoria: str
    recorrente: bool = False
    realizado: bool = True


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

    Corte por dia (§1.3.1): no mês CORRENTE, Fontes 1 e 4 marcam realizado por
    dia/vencimento <= hoje (marcação, não filtro — a lista completa é a
    projeção). Fontes 2/3 são sempre realizadas (§1.3.2).
    """
    h = hoje()
    corrente = (ano, mes) == (h.year, h.month)
    lancamentos: list[LancamentoFluxo] = []

    # Fonte 3: à vista + receitas — não faturadas e não parceladas, pela data.
    # Sempre realizada (§1.3.2: à vista já ocorreu por definição).
    for t in _buscar_mes(session, usuario_id, mes, ano):
        if t.parcelado or t.fatura_mes is not None:
            continue  # pai parcelada → Fonte 1; avulsa faturada → Fonte 2
        lancamentos.append(LancamentoFluxo(t.tipo, t.valor, t.categoria))

    # Fonte 1: parcelas na competência — realizado pelo VENCIMENTO real (dia
    # exato) no mês corrente, não pelo fatura_mes (§1.3.2).
    for p in _parcelas_competencia(session, usuario_id, mes, ano):
        realizado = (not corrente) or p.data_vencimento <= h
        lancamentos.append(
            LancamentoFluxo("despesa", p.valor_parcela, p.categoria, realizado=realizado)
        )

    # Fonte 2: avulsas de cartão faturadas na competência. Sempre realizada
    # (§1.3.2: falta o dia de vencimento na Transacao — refinamento posterior).
    for t in _avulsas_cartao_competencia(session, usuario_id, mes, ano):
        lancamentos.append(LancamentoFluxo(t.tipo, t.valor, t.categoria))

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
    for p in session.exec(
        select(Parcela).where(
            Parcela.usuario_id == usuario_id,
            Parcela.fatura_ano == ano,
            Parcela.fatura_mes != None,  # noqa: E711
            Parcela.cancelado == False,  # noqa: E712
        )
    ).all():
        realizado = (ano, p.fatura_mes) != (h.year, h.month) or p.data_vencimento <= h
        por_mes[p.fatura_mes].append(
            LancamentoFluxo("despesa", p.valor_parcela, p.categoria, realizado=realizado)
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

    mes, ano = corrente
    por_mes: dict[int, list[LancamentoFluxo]] = {}
    ano_carregado: Optional[int] = None
    for _ in range(HORIZONTE_MESES + 1):  # corrente + 60 à frente
        if ano != ano_carregado:
            por_mes = _lancamentos_ano(session, usuario_id, ano)
            ano_carregado = ano
        if por_mes[mes]:
            return (mes, ano), corrente
        mes, ano = _mes_seguinte(mes, ano)

    return _mes_seguinte(*corrente), corrente
