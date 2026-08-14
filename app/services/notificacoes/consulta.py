"""Quem recebe o aviso de vencimento, e com que valor (#6, Batch 1).

SÓ LEITURA. Nenhum `add`, `flush` ou `commit` passa por aqui — é o que
permite o `--dry-run` do script apontar para o banco de PRODUÇÃO sem risco,
e o que `test_notificacoes_dry_run.py` prova com um listener de `before_flush`
(mesma técnica do preview do extrato).

## Como se acha "fatura que vence em D+3" sem fatura materializada

Fatura não é linha no banco — é derivada. Mas isso NÃO vira varredura, porque
a data de vencimento tem forma fechada: `vencimento_avulsa` (services/faturas)
define que `fatura_mes`/`fatura_ano` JÁ SÃO o mês de vencimento e que só falta
o DIA, que vem do `dia_vencimento` do cartão (clampado ao último dia do mês).

Logo uma fatura vence em `alvo` se e somente se:
  (a) sua competência é (alvo.month, alvo.year) — uma só, não N; e
  (b) o `dia_vencimento` do cartão clampa exatamente em `alvo.day`.

O SQL filtra por (b) com um `IN` de dias candidatos — isso é só para não
carregar todo cartão do banco. Quem DECIDE é `vencimento_avulsa(...) == alvo`,
em Python: a fonte única continua sendo ela, e um dia que a regra de
vencimento mude, este módulo acompanha sem saber.

## O que fica de fora, e por quê

- **Cartão sem `dia_vencimento`**: fora. O fallback "último dia do mês" de
  `vencimento_avulsa` está CERTO num agregado (não esconder dívida a vencer)
  e ERRADO numa afirmação ao usuário — viraria uma data inventada no e-mail.
- **Cartão inativo**: DENTRO. `totais_fatura_por_cartao` não filtra `ativo`,
  então a fatura dele aparece na tela 3d; avisar é o coerente. (`cards.py`
  filtra `ativo` só na listagem de cartões.)
- **Usuário inativo ou com a preferência desligada**: fora, no SQL.
- **Status**: ver `_STATUS_QUE_AVISA`.
- **Restante <= 0**: fora. Um estorno maior que as despesas dá total negativo;
  "sua fatura de -R$ 50,00 vence" é pior que silêncio.
"""

import calendar
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, select

from app.models.card import Cartao
from app.models.pagamento_fatura import PagamentoFatura
from app.models.user import Usuario
from app.services.faturas import (
    status_fatura,
    totais_fatura_por_cartao,
    vencimento_avulsa,
)

# 3 dias, FIXO (decisão de produto): sem "quantos dias" configurável e sem
# variação por cartão. A preferência é só ligar/desligar.
DIAS_DE_ANTECEDENCIA = 3

# `atrasada` não aparece nesta lista porque é IMPOSSÍVEL aqui: o vencimento
# considerado é hoje + 3, sempre no futuro.
#
# - `a_vencer`     : o caso normal.
# - `paga_parcial` : entra COM O RESTANTE (ver `_restante`). Avisar o total
#                    cheio de uma fatura parcialmente paga destrói a confiança
#                    na primeira mensagem que a pessoa recebe.
# - `aberta`       : vence em 3 dias mas AINDA ACEITA COMPRAS. Não é caso de
#                    borda: basta o vencimento cair até 3 dias depois do
#                    fechamento (fecha 10, vence 12, offset 0 — par que
#                    `fechamento_vencimento_coerentes` ACEITA, já que exige
#                    apenas vencimento > fechamento). No dia 9, essa fatura
#                    vence em 3 dias E está aberta. O dinheiro vence de todo
#                    jeito; deixar de avisar seria um silêncio invisível para
#                    todo cartão com essa folga curta.
#
# `paga` e `vazia` ficam de fora — não há o que avisar.
_STATUS_QUE_AVISA = frozenset({"a_vencer", "paga_parcial", "aberta"})


@dataclass(frozen=True)
class FaturaAvisada:
    """Uma fatura que vence no alvo, do jeito que entra no e-mail."""

    cartao_id: int
    cartao_nome: str
    vencimento: dt.date
    restante: Decimal
    status: str


@dataclass(frozen=True)
class AvisoUsuario:
    """Um destinatário e TODAS as faturas dele que vencem no alvo.

    Um e-mail por usuário por dia: três cartões vencendo no mesmo dia são um
    aviso com três linhas, não três avisos.
    """

    usuario_id: int
    email: str
    nome_completo: str
    faturas: list[FaturaAvisada]


def _dias_candidatos(alvo: dt.date) -> list[int]:
    """Valores de `dia_vencimento` que PODEM clampar em `alvo`.

    Fora do fim do mês é só `alvo.day`. No último dia do mês, todo dia MAIOR
    também clampa ali (dia 31 num mês de 30 vence no 30) — é o filtro grosso
    do SQL; `vencimento_avulsa` confirma um a um depois.
    """
    ultimo_dia = calendar.monthrange(alvo.year, alvo.month)[1]
    if alvo.day == ultimo_dia:
        return list(range(alvo.day, 32))
    return [alvo.day]


def _restante(status: str, total: Decimal, pagamento: PagamentoFatura | None) -> Decimal:
    """O que FALTA pagar — nunca o total cheio de uma fatura já parcial.

    Amarrado ao STATUS DERIVADO, não a um `if pagamento.pago` próprio: quem
    decide se a fatura está paga é `status_fatura` (fonte única), e o dia em
    que a regra de cobertura do #9 mudar, isto acompanha sozinho em vez de
    discordar da tela em silêncio.
    """
    if status == "paga_parcial" and pagamento is not None and pagamento.valor_pago is not None:
        return total - pagamento.valor_pago
    return total


def faturas_a_vencer(session: Session, hoje: dt.date) -> list[AvisoUsuario]:
    """Avisos a enviar HOJE, um por usuário, ordenados por usuario_id.

    `hoje` é PARÂMETRO EXPLÍCITO (idioma de `status_fatura(..., today, ...)`):
    o chamador resolve a data no fuso do produto (core.dates.hoje) e os testes
    congelam o dia sem precisar de patch. Lista vazia = ninguém a avisar, e
    nesse caso NENHUM e-mail sai (decisão: nunca enviar e-mail vazio).
    """
    alvo = hoje + dt.timedelta(days=DIAS_DE_ANTECEDENCIA)

    # `IN` de inteiros nunca casa NULL, então cartão sem dia_vencimento já sai
    # aqui — o filtro grosso e a regra "sem dia_vencimento fica fora" são a
    # mesma cláusula.
    candidatos = [
        cartao
        for cartao in session.exec(
            select(Cartao).where(
                Cartao.dia_vencimento.in_(_dias_candidatos(alvo))  # type: ignore[attr-defined]
            )
        ).all()
        # A DECISÃO é da fonte única, não do IN acima.
        if vencimento_avulsa(cartao, alvo.month, alvo.year) == alvo
    ]
    if not candidatos:
        return []

    usuarios = session.exec(
        select(Usuario).where(
            Usuario.id.in_({c.usuario_id for c in candidatos}),  # type: ignore[attr-defined]
            Usuario.ativo == True,  # noqa: E712
            Usuario.notificar_vencimento == True,  # noqa: E712
        )
    ).all()

    avisos: list[AvisoUsuario] = []
    for usuario in sorted(usuarios, key=lambda u: u.id):
        # Composição da fatura pela FONTE ÚNICA (2 queries), a mesma da lente
        # 3d e do detalhe por cartão. Cartão sem lançamento na competência não
        # aparece no dict → fatura `vazia`.
        totais = totais_fatura_por_cartao(session, usuario.id, alvo.month, alvo.year)
        pagamentos = {
            p.cartao_id: p
            for p in session.exec(
                select(PagamentoFatura).where(
                    PagamentoFatura.usuario_id == usuario.id,
                    PagamentoFatura.fatura_mes == alvo.month,
                    PagamentoFatura.fatura_ano == alvo.year,
                )
            )
        }

        faturas: list[FaturaAvisada] = []
        for cartao in candidatos:
            if cartao.usuario_id != usuario.id:
                continue
            total = totais.get(cartao.id)
            pagamento = pagamentos.get(cartao.id)
            status = status_fatura(
                cartao,
                alvo.month,
                alvo.year,
                pagamento,
                hoje,
                total if total is not None else Decimal("0.00"),
                vazia=total is None,
            )
            if status not in _STATUS_QUE_AVISA:
                continue
            restante = _restante(status, total, pagamento)  # type: ignore[arg-type]
            if restante <= 0:
                continue
            faturas.append(
                FaturaAvisada(
                    cartao_id=cartao.id,
                    cartao_nome=cartao.nome,
                    vencimento=alvo,
                    restante=restante,
                    status=status,
                )
            )

        if not faturas:
            continue
        # Ordem determinística no e-mail: maior primeiro, desempate por nome.
        faturas.sort(key=lambda f: (-f.restante, f.cartao_nome))
        avisos.append(
            AvisoUsuario(
                usuario_id=usuario.id,
                email=usuario.email,
                nome_completo=usuario.nome_completo,
                faturas=faturas,
            )
        )

    return avisos
