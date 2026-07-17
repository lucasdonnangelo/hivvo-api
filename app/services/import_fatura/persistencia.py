"""Materialização da fatura importada em transações/parcelas — Batch 2.

A primeira escrita do fluxo de import. Princípio (B.0): ANCORA tudo na
competência que a FATURA declara (mês de vencimento), sem re-derivar do ciclo
do cartão — o documento é a verdade de "qual linha pertence a qual fatura", e
a config do cartão no nosso banco pode não bater com o ciclo real do emissor.
O cartão entra só para o DIA do vencimento de cada parcela (vencimento_avulsa).

Nada aqui commita: constrói na sessão e o boundary (router) commita tudo numa
transação única (atomicidade — T-41). Decimal sempre.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.schemas.import_fatura import FaturaCommit, TipoTransacao, TransacaoCommit
from app.services.faturas import _competencia_menos, vencimento_avulsa

# Proveniência: distingue o que veio do import (filtro/UX). `origem` é string
# livre no banco (sem CHECK) — valor novo não precisa de migration.
ORIGEM_IMPORT = "importacao"

# Só COMPRA e IOF são despesa a rastrear; pagamento/ajuste_saldo são
# liquidação/saldo (não viram lançamento).
_TIPOS_GASTO = (TipoTransacao.compra, TipoTransacao.iof)


@dataclass
class ResultadoMaterializacao:
    transacoes_criadas: int = 0
    parcelas_criadas: int = 0
    estornos_ignorados: int = 0
    # Parceladas puladas por dedup: a MESMA parcelada, já materializada por um
    # import ANTERIOR, reaparece nesta fatura (X/N vira (X+1)/N no mês seguinte).
    # O skip NUNCA é silencioso — vai no recibo, como estornos_ignorados
    # (MULTI-FATURA).
    parceladas_deduplicadas: int = 0


def ancora_competencia(fatura: FaturaCommit) -> tuple[int, int]:
    """(mes, ano) âncora da fatura.

    No sistema, competência = mês de VENCIMENTO (fatura_mes/ano dos lançamentos
    é o mês de vencimento — ver _fatura_cartao_avulso/_data_vencimento_parcela).
    Então a âncora = (vencimento.month, vencimento.year); fallback para a
    competência declarada quando a fatura não traz vencimento (Q1).
    """
    if fatura.vencimento:
        d = dt.date.fromisoformat(fatura.vencimento)
        return d.month, d.year
    return fatura.competencia.mes, fatura.competencia.ano


# --- Dedup de parcela entre importações (MULTI-FATURA) -----------------------

_CENTS = Decimal("0.01")

# Chave estável de uma parcelada: (descrição normalizada, total, origem
# implícita (mes, ano), valor da parcela em centavos). A MESMA compra tem a
# MESMA chave em qualquer fatura/ordem de import. O cartão fica implícito
# (o snapshot já é por cartão).
Identidade = tuple[str, int, int, int, str]


def _norm_descricao(descricao: str) -> str:
    """Descrição canônica para o match: colapsa espaços e casefold. NÃO tira
    acento — o mesmo lojista não troca acento entre faturas; o drift real é
    caixa/espaço."""
    return " ".join(descricao.split()).casefold()


def _identidade_parcelada(
    descricao: str, total: int, mes: int, ano: int, valor_parcela: Decimal
) -> Identidade:
    """Valor entra na chave: parceladas de mesma desc/total/origem mas valor
    distinto são compras DISTINTAS (desempate por valor)."""
    valor_cents = str(Decimal(str(valor_parcela)).quantize(_CENTS))
    return (_norm_descricao(descricao), total, mes, ano, valor_cents)


def _snapshot_identidades_parcelada(
    session: Session, usuario_id: int, cartao_id: int
) -> set[Identidade]:
    """Identidades das parceladas JÁ importadas deste cartão — tirado ANTES de
    qualquer insert desta materialização. Os skips decidem contra ESTE conjunto
    (imports ANTERIORES), nunca contra o que este request cria: duas linhas
    idênticas na MESMA fatura são duas compras e ambas materializam.

    A origem implícita mora na `Parcela` nº 1 (a materialização grava
    parcela j em âncora−(indice−j); para j=1 isso é âncora−(indice−1) = a
    origem). `UNIQUE(transacao_id, numero_parcela)` garante uma nº 1 por mãe.
    """
    rows = session.exec(
        select(
            Transacao.descricao,
            Transacao.total_parcelas,
            Parcela.fatura_mes,
            Parcela.fatura_ano,
            Parcela.valor_parcela,
        )
        .join(Parcela, Parcela.transacao_id == Transacao.id)
        .where(
            Transacao.usuario_id == usuario_id,
            Transacao.cartao_id == cartao_id,
            Transacao.parcelado == True,  # noqa: E712
            Transacao.origem == ORIGEM_IMPORT,
            Parcela.numero_parcela == 1,
        )
    ).all()
    return {
        _identidade_parcelada(desc, total, mes, ano, valor)
        for desc, total, mes, ano, valor in rows
    }


def competencias_passadas_com_lancamentos(
    session: Session, usuario_id: int, cartao_id: int, ancora_ord: int
) -> set[tuple[int, int]]:
    """Competências (mes, ano) ESTRITAMENTE antes da âncora que têm ALGUM
    lançamento EXISTENTE deste cartão — parcela ou avulsa, criado neste request
    ou por import anterior (autoflush enxerga ambos). É o conjunto que o commit
    aceita marcar como pago: passado real do cartão, nunca fatura arbitrária
    (MULTI-FATURA — confirmação de pagamento das passadas). Com dedup, a
    parcelada passada pode ter sido PULADA neste import e mesmo assim já existir
    de outro — por isso a fonte é o que EXISTE, não o que este request criou.
    """
    comps: set[tuple[int, int]] = set()
    fontes = (
        session.exec(
            select(Parcela.fatura_mes, Parcela.fatura_ano).where(
                Parcela.usuario_id == usuario_id,
                Parcela.cartao_id == cartao_id,
            )
        ).all(),
        session.exec(
            select(Transacao.fatura_mes, Transacao.fatura_ano).where(
                Transacao.usuario_id == usuario_id,
                Transacao.cartao_id == cartao_id,
            )
        ).all(),
    )
    for linhas in fontes:
        for mes, ano in linhas:
            if mes is None or ano is None:
                continue
            if ano * 12 + mes < ancora_ord:
                comps.add((mes, ano))
    return comps


def materializar_fatura(
    session: Session, usuario_id: int, card: Cartao, fatura: FaturaCommit
) -> ResultadoMaterializacao:
    """Cria transações/parcelas da fatura NA SESSÃO (sem commit).

    - compra/iof à vista (parcela=None, valor>0) → uma avulsa na âncora (B.1);
    - compra/iof parcelada (parcela X/N) → UMA transação parcelada + N parcelas
      distribuídas por competência a partir da âncora (B.2);
    - pagamento/ajuste_saldo → ignorados (não são despesa);
    - estorno (compra negativa, barrado pelo CHECK valor>0) → não gravado,
      contado em estornos_ignorados (B.3).
    """
    ancora_mes, ancora_ano = ancora_competencia(fatura)
    res = ResultadoMaterializacao()
    # SNAPSHOT das identidades já importadas ANTES de qualquer insert: todo skip
    # de dedup decide contra imports ANTERIORES, não contra o que ESTA fatura
    # cria. Duas linhas parceladas idênticas na mesma fatura = duas compras →
    # ambas materializam (contar a mais é corrigível na revisão; a menos, não).
    snapshot = _snapshot_identidades_parcelada(session, usuario_id, card.id)

    for t in fatura.transacoes:
        if t.tipo not in _TIPOS_GASTO:
            continue
        valor = Decimal(t.valor_brl)
        if valor <= 0:
            if valor < 0:  # estorno; valor==0 é linha degenerada, sai calado
                res.estornos_ignorados += 1
            continue

        if t.parcela is not None:
            _materializar_parcelada(
                session, usuario_id, card, t, valor, ancora_mes, ancora_ano,
                snapshot, res,
            )
        else:
            _materializar_avulsa(
                session, usuario_id, card, t, valor, ancora_mes, ancora_ano, res
            )

    return res


def _materializar_avulsa(
    session: Session,
    usuario_id: int,
    card: Cartao,
    t: TransacaoCommit,
    valor: Decimal,
    ancora_mes: int,
    ancora_ano: int,
    res: ResultadoMaterializacao,
) -> None:
    session.add(
        Transacao(
            usuario_id=usuario_id,
            tipo="despesa",
            data=dt.date.fromisoformat(t.data),
            descricao=t.descricao,
            valor=valor,
            categoria=t.categoria,
            forma_pagamento="Crédito",
            tipo_gasto="Variável",
            origem=ORIGEM_IMPORT,
            cartao_id=card.id,
            fatura_mes=ancora_mes,  # âncora do documento, NÃO re-derivo do ciclo
            fatura_ano=ancora_ano,
            parcelado=False,
            total_parcelas=None,
        )
    )
    res.transacoes_criadas += 1


def _materializar_parcelada(
    session: Session,
    usuario_id: int,
    card: Cartao,
    t: TransacaoCommit,
    valor_parcela: Decimal,
    ancora_mes: int,
    ancora_ano: int,
    snapshot: set[Identidade],
    res: ResultadoMaterializacao,
) -> None:
    n = t.parcela.total
    indice = t.parcela.indice

    # DEDUP: origem implícita = âncora − (indice − 1) = competência que a
    # materialização grava na parcela nº 1. Se essa identidade já veio de um
    # import ANTERIOR (snapshot) → o cronograma inteiro já existe, PULA.
    origem_ano, origem_mes = _competencia_menos(ancora_ano, ancora_mes, indice - 1)
    identidade = _identidade_parcelada(
        t.descricao, n, origem_mes, origem_ano, valor_parcela
    )
    if identidade in snapshot:
        res.parceladas_deduplicadas += 1
        return

    transacao = Transacao(
        usuario_id=usuario_id,
        tipo="despesa",
        data=dt.date.fromisoformat(t.data),  # origem back-datada (data impressa)
        descricao=t.descricao,
        valor=valor_parcela * n,  # parcelas iguais = valor mostrado × N
        categoria=t.categoria,
        forma_pagamento="Crédito",
        tipo_gasto="Variável",
        origem=ORIGEM_IMPORT,
        cartao_id=card.id,
        fatura_mes=None,  # competência mora nas parcelas (padrão do projeto)
        fatura_ano=None,
        parcelado=True,
        total_parcelas=n,
    )
    session.add(transacao)
    session.flush()  # obtém transacao.id sem commitar (T-41)
    res.transacoes_criadas += 1

    for j in range(1, n + 1):
        # Parcela #indice cai na âncora; as demais recuam (indice - j)
        # competências — negativo = avança (futuro). _competencia_menos é o
        # inverso de _add_months, então a distribuição casa com a materialização
        # manual de parcelas.
        ano_j, mes_j = _competencia_menos(ancora_ano, ancora_mes, indice - j)
        session.add(
            Parcela(
                usuario_id=usuario_id,
                transacao_id=transacao.id,
                numero_parcela=j,
                total_parcelas=n,
                valor_parcela=valor_parcela,
                # Dia do vencimento vem do cartão; sem dia_vencimento, cai no
                # fim do mês (vencimento_avulsa nunca retorna None).
                data_vencimento=vencimento_avulsa(card, mes_j, ano_j),
                descricao=f"{t.descricao} ({j}/{n})",
                categoria=t.categoria,
                cartao_id=card.id,
                fatura_mes=mes_j,
                fatura_ano=ano_j,
            )
        )
        res.parcelas_criadas += 1

    session.flush()
