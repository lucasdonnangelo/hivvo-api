"""Algoritmo puro da recorrência (PLANO_PROJECAO §3.4).

Responde "esta recorrência gera uma ocorrência no mês (mes, ano)? qual valor?
em que data?" sem I/O de banco — recebe os objetos e computa. Reusável pela
projeção de fluxo (Fase 2b) e testável isolado.

A vigência decide SE gera e o VALOR; o dia_do_mes decide só a DATA da
ocorrência dentro do mês (clampado ao último dia — dia 31 em fevereiro → 28/29).
"""

import datetime as dt
from decimal import Decimal
from typing import Iterable, Optional

from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.services.faturas import clamp_dia_no_mes


def _vigencia_contem(vigencia: RecorrenciaVigencia, mes: int, ano: int) -> bool:
    """O período [início, fim] da vigência contém a competência (mes, ano)?

    Comparação por tupla (ano, mes) — cobre virada de ano. Fim NULL = vigência
    aberta: só checa o início.
    """
    if (ano, mes) < (vigencia.ano_inicio, vigencia.mes_inicio):
        return False
    if vigencia.ano_fim is None:
        return True
    return (ano, mes) <= (vigencia.ano_fim, vigencia.mes_fim)


def valor_no_mes(
    recorrencia: Recorrencia,
    vigencias: Iterable[RecorrenciaVigencia],
    mes: int,
    ano: int,
) -> Optional[Decimal]:
    """Valor da ocorrência da recorrência na competência (mes, ano), ou None.

    1. Acha a vigência cujo período contém (mes, ano) — pela invariante de
       não-sobreposição, no máximo uma casa (não pressupõe lista ordenada).
    2. Achou → o valor dessa vigência; nenhuma contém → None.

    A projeção depende SÓ das vigências (Fase 2c): recorrência encerrada tem a
    última vigência FECHADA no mês do encerramento — o passado continua gerando
    (vigências que cobrem meses passados ficam intactas) e o futuro para
    (nenhuma vigência cobre). `ativa` é flag de estado/listagem, NÃO de
    projeção. O parâmetro `recorrencia` permanece na assinatura para a extensão
    futura de `frequencia` (semanal/quinzenal).
    """
    for vigencia in vigencias:
        if _vigencia_contem(vigencia, mes, ano):
            return vigencia.valor
    return None


def dados_exibicao(
    recorrencia: Recorrencia,
    vigencias: Iterable[RecorrenciaVigencia],
    mes: int,
    ano: int,
) -> tuple[Optional[Decimal], Optional[int], Optional[int]]:
    """Dados a EXIBIR na gestão (Bug 1) — valor E início da MESMA vigência de
    exibição, num só cálculo (por construção não podem divergir):

    - VIGE na competência (mes, ano) → (valor de hoje, None, None): já está
      valendo, não há "a partir de".
    - NÃO vige, mas há vigência FUTURA mais próxima (menor (ano_inicio,
      mes_inicio) com início >= (ano, mes)) → (valor dela, mes_inicio dela,
      ano_inicio dela): a UI mostra "R$X · a partir de ago/2026".
    - ENCERRADA (só vigências passadas, nenhuma futura) → (None, None, None):
      continua "—" (não pega valor de vigência passada).

    Distinto de `valor_no_mes` (o "vige HOJE" estrito, base da projeção e de
    consumidores que dependem do None): aditivo, só para exibição. Fonte ÚNICA do
    trio de exibição — valor e início vêm SEMPRE da mesma vigência.
    """
    vigencias = list(vigencias)
    vigente = valor_no_mes(recorrencia, vigencias, mes, ano)
    if vigente is not None:
        return vigente, None, None
    futuras = [v for v in vigencias if (v.ano_inicio, v.mes_inicio) >= (ano, mes)]
    if not futuras:
        return None, None, None
    proxima = min(futuras, key=lambda v: (v.ano_inicio, v.mes_inicio))
    return proxima.valor, proxima.mes_inicio, proxima.ano_inicio


def data_ocorrencia(recorrencia: Recorrencia, mes: int, ano: int) -> dt.date:
    """Data da ocorrência dentro do mês: dia_do_mes clampado ao último dia."""
    return dt.date(ano, mes, clamp_dia_no_mes(recorrencia.dia_do_mes, ano, mes))
