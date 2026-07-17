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
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session

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
    # Competências (mes, ano) ESTRITAMENTE anteriores à âncora que esta
    # importação criou (via parcelas históricas). É o conjunto que delimita
    # quais faturas passadas o commit aceita marcar como pagas (B.5).
    competencias_passadas: set[tuple[int, int]] = field(default_factory=set)


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
    ancora_ord = ancora_ano * 12 + ancora_mes
    res = ResultadoMaterializacao()

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
                ancora_ord, res,
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
    ancora_ord: int,
    res: ResultadoMaterializacao,
) -> None:
    n = t.parcela.total
    indice = t.parcela.indice

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
        if ano_j * 12 + mes_j < ancora_ord:
            res.competencias_passadas.add((mes_j, ano_j))

    session.flush()
