"""Contrato da importação de fatura: texto -> JSON estruturado (+ response da rota).

FaturaExtraida é porte 1:1 do spike validado em 17/07 (scripts/spike_import/schema.py,
2 faturas reais: Nubank e Itaú) e é usado duas vezes:
1. Como response_schema do Gemini (força a resposta no shape certo).
2. Como validação local da resposta (cinto e suspensório).
NÃO altere campos ou validadores sem revalidar contra faturas reais.

Datas são `str` ISO (YYYY-MM-DD) e valores são `str` decimais — tipos
primitivos evitam surpresas na conversão Pydantic -> Schema da API Gemini.
Validadores garantem que o conteúdo parseia de verdade.

O bloco de reconciliação NÃO faz parte do contrato do Gemini de propósito:
LLM não faz aritmética confiável — a reconciliação é calculada em Python
(ver app/services/import_fatura/reconciliacao.py) e devolvida em
ReconciliacaoOut, com decimais como string.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, field_validator, model_validator


def normalizar_decimal(bruto: str) -> str:
    """Aceita '3.412,88', '3412.88', '-58,95', 'R$ 1.234,56' -> '3412.88'.

    Ver a extração vale mais do que punir formato: normaliza em vez de
    rejeitar duro. Só rejeita o que não parseia.
    Ambiguidade assumida: '3.412' sem vírgula é lido como 3.412 (o prompt
    pede ponto decimal, então ponto sozinho é tratado como decimal).
    """
    s = bruto.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if "," in s:
        # vírgula presente => separador decimal pt-BR; pontos são milhar
        s = s.replace(".", "").replace(",", ".")
    try:
        return str(Decimal(s))
    except InvalidOperation:
        raise ValueError(f"valor decimal não parseável: {bruto!r}")


def _validar_data_iso(v: str) -> str:
    date.fromisoformat(v)  # levanta ValueError se não for YYYY-MM-DD válido
    return v


class TipoTransacao(StrEnum):
    compra = "compra"
    iof = "iof"
    pagamento = "pagamento"
    ajuste_saldo = "ajuste_saldo"


class Competencia(BaseModel):
    mes: int
    ano: int

    @field_validator("mes")
    @classmethod
    def _mes_valido(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mês fora de 1..12: {v}")
        return v


class Periodo(BaseModel):
    de: str
    ate: str

    _datas = field_validator("de", "ate")(_validar_data_iso)


class ParcelaInfo(BaseModel):
    indice: int
    total: int

    @model_validator(mode="after")
    def _indice_dentro_do_total(self) -> "ParcelaInfo":
        if not 1 <= self.indice <= self.total:
            raise ValueError(f"parcela inconsistente: {self.indice}/{self.total}")
        return self


class Internacional(BaseModel):
    moeda_orig: str
    valor_orig: str
    taxa: str | None = None

    _valores = field_validator("valor_orig", "taxa")(
        classmethod(lambda cls, v: None if v is None else normalizar_decimal(v))
    )


class Transacao(BaseModel):
    data: str
    descricao: str
    valor_brl: str  # decimal string, COM o sinal impresso na fatura
    tipo: TipoTransacao
    parcela: ParcelaInfo | None = None
    portador_final: str | None = None
    internacional: Internacional | None = None

    _data = field_validator("data")(_validar_data_iso)
    _valor = field_validator("valor_brl")(
        classmethod(lambda cls, v: normalizar_decimal(v))
    )


class FaturaExtraida(BaseModel):
    banco: str
    competencia: Competencia
    periodo: Periodo | None = None
    emissao: str | None = None
    vencimento: str | None = None
    # líquido a pagar (embute saldo anterior e pagamentos) — informativo,
    # alimenta só o cheque SECUNDÁRIO da reconciliação
    total_a_pagar: str
    # soma de COMPRAS do ciclo DECLARADA pelo banco (o número impresso na
    # fatura, NÃO a soma calculada das linhas — senão o cheque é circular)
    total_compras_periodo: str
    # IOF do ciclo quando o banco mostra separado; "0.00" quando já está
    # embutido no total_compras_periodo
    total_iof_periodo: str
    transacoes: list[Transacao]

    _datas = field_validator("emissao", "vencimento")(
        classmethod(lambda cls, v: None if v is None else _validar_data_iso(v))
    )
    _totais = field_validator(
        "total_a_pagar", "total_compras_periodo", "total_iof_periodo"
    )(classmethod(lambda cls, v: normalizar_decimal(v)))


class ReconciliacaoOut(BaseModel):
    """Resultado da reconciliação determinística — decimais como string.

    `bate=False` NÃO é erro HTTP: a rota devolve 200 e o cliente decide.
    """

    ancora: str  # compras + IOF do ciclo, DECLARADOS pelo banco
    soma_gastos: str  # soma das linhas tipo {compra, iof}
    excluidos: str  # soma das linhas tipo {pagamento, ajuste_saldo}
    total_a_pagar: str
    diferenca: str  # soma_gastos - ancora (cheque primário)
    bate: bool
    diferenca_secundaria: str  # (soma_gastos + excluidos) - total_a_pagar
    bate_secundario: bool


class FaturaPreviewResponse(BaseModel):
    cartao_id: int
    fatura: FaturaExtraida
    reconciliacao: ReconciliacaoOut


# --- Batch 2: commit (grava transações/parcelas a partir da fatura revisada) ---
#
# O request reusa o contrato da extração por SUBCLASSE — herda campos e
# validadores de Transacao/FaturaExtraida sem duplicá-los, e sem tocar no
# schema que o Gemini consome. A ÚNICA adição é `categoria` por linha: ela é
# do request (a revisão no front categoriza), NUNCA da extração — default
# "Outros" quando ausente.


class TransacaoCommit(Transacao):
    categoria: str = "Outros"


class FaturaCommit(FaturaExtraida):
    transacoes: list[TransacaoCommit]


class FaturaCommitRequest(BaseModel):
    cartao_id: int
    fatura: FaturaCommit
    # Competências passadas a marcar como pagas (o commit cria PagamentoFatura
    # pago=True). NUNCA presume pago por data — só o que vier aqui. Revalidado
    # no servidor: cada uma tem que pertencer ao passado que ESTA importação
    # materializou (ver services/import_fatura/persistencia.py).
    competencias_pagas: list[Competencia] = []


class FaturaCommitResponse(BaseModel):
    """Recibo do commit — tudo que foi gravado, para o front conferir."""

    transacoes_criadas: int
    parcelas_criadas: int
    faturas_marcadas_pagas: int
    # Parceladas puladas por dedup: a MESMA parcelada, materializada por um
    # import ANTERIOR, reaparece nesta fatura (X/N → (X+1)/N). Visível para o
    # skip não sumir em silêncio (MULTI-FATURA).
    parceladas_deduplicadas: int
    # Estornos (compra negativa) NÃO são graváveis (CHECK valor>0); aparecem
    # aqui para não sumirem em silêncio. Netting contra a compra-mãe: adiado.
    estornos_ignorados: int
    reconciliacao_bate: bool
