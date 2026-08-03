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
from typing import Literal

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


class FaturaPassadaOut(BaseModel):
    """Competência passada que ESTA importação vai CRIAR — dado de EXIBIÇÃO da
    tela de revisão (a "armadilha do histórico").

    Vem da distribuição da parcela (âncora−(indice−j)): ao importar uma
    parcelada X/N, o commit materializa as parcelas anteriores em faturas
    passadas do cartão. O front lista essas competências para o usuário marcar
    as já pagas — ele NÃO recomputa a regra (fica no backend).

    `ja_paga`: já existe PagamentoFatura(pago=True) para (cartao, mes, ano) —
    a UI pré-marca/oculta. Só cálculo/leitura: o preview segue STATELESS.
    """

    mes: int
    ano: int
    ja_paga: bool


class EnriquecimentoFaturaLinha(BaseModel):
    """Auto-categoria de UMA linha, endereçada por `indice` em fatura.transacoes.

    Vive FORA de Transacao de propósito, exatamente como o EnriquecimentoLinha do
    extrato vive fora de LinhaExtrato: `FaturaExtraida` é o response_schema do
    Gemini de EXTRAÇÃO, e engordá-la faria o modelo tentar preencher o
    enriquecimento. Array paralelo, alinhado por índice EXPLÍCITO — nunca por
    posição.

    Só linha que MATERIALIZA recebe item: compra/iof com valor != 0 (inclusive
    valor negativo, que vira Transacao(tipo="estorno") e leva categoria).
    Pagamento e ajuste_saldo não viram lançamento e não têm categoria.

    - `categoria_sugerida`: None = nenhuma camada teve o que dizer (a tela mostra
      "Outros", o neutro). É NOME, não id: `Transacao.categoria` é string.
    - `origem_sugestao`: qual camada carregou o peso. Instrumentação, não
      decoração — é como vamos medir depois onde investir.
    - `data_suspeita`: a data da linha é impossível para ESTE documento (#46).
      None = nada a dizer (o caso normal, e também o caso "não deu para checar").

    Consequência do recorte por linha MATERIALIZÁVEL: uma `pagamento` ou
    `ajuste_saldo` com data errada NÃO é flagada. É deliberado — elas não viram
    `Transacao`, então a data delas nunca deriva competência e não pode
    contaminar fatura nenhuma.
    """

    indice: int
    categoria_sugerida: str | None = None
    origem_sugestao: Literal["historico", "regra"] | None = None
    # SINAL, não gate: compra DEPOIS da emissão da fatura não existe naquele
    # documento (ver services/import_fatura/enriquecimento.datas_suspeitas). O
    # servidor NUNCA corrige a data — não sabemos qual é a certa, e inventá-la
    # seria pior que o erro. Default None → aditivo.
    data_suspeita: Literal["posterior_a_emissao"] | None = None


class FaturaPreviewResponse(BaseModel):
    cartao_id: int
    fatura: FaturaExtraida
    reconciliacao: ReconciliacaoOut
    # Competências ESTRITAMENTE antes da âncora que o commit vai preencher com
    # parcelas desta fatura — para a revisão marcar as já pagas. Vazia quando a
    # fatura não tem parcelada que recue para o passado.
    faturas_passadas: list[FaturaPassadaOut] = []
    # Um item por linha MATERIALIZÁVEL, ordenado por índice. Default [] →
    # aditivo: cliente que não conhece o campo continua funcionando.
    enriquecimento: list[EnriquecimentoFaturaLinha] = []


# --- Batch 2: commit (grava transações/parcelas a partir da fatura revisada) ---
#
# O request reusa o contrato da extração por SUBCLASSE — herda campos e
# validadores de Transacao/FaturaExtraida sem duplicá-los, e sem tocar no
# schema que o Gemini consome. A ÚNICA adição é `categoria` por linha: ela é
# do request (a revisão no front categoriza), NUNCA da extração.


class TransacaoCommit(Transacao):
    """Uma linha da fatura REVISADA — dado extraído + decisão do usuário.

    `categoria` é TRI-ESTADO, a mesma forma do `importar` do extrato:
    - string (INCLUSIVE "Outros"): o usuário decidiu — vale sempre, e só passa
      pelo guarda-corpo de "esta categoria existe para você, neste tipo?";
    - None (ausente): NÃO decidido → o servidor RECOMPUTA a própria sugestão
      (services/import_fatura/enriquecimento.resolver_categorias), com o mesmo
      matcher do preview. O default mora no BACKEND, não na confiança de que o
      front mandou a categoria certa.

    Retrocompatível: cliente que manda "Outros" explícito continua gravando
    "Outros" — explícito vence, como no `importar`.
    """

    categoria: str | None = None


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
    # Competências que ESTE commit confirmou como pagas (valor_pago = total
    # materializado, um valor ASSUMIDO).
    faturas_marcadas_pagas: int
    # Competências pedidas em `competencias_pagas` que JÁ estavam confirmadas e
    # foram PRESERVADAS: o import nunca sobrescreve com o total assumido o valor
    # REAL do extrato (#9) nem a confirmação explícita do usuário. Default 0 →
    # retrocompatível.
    faturas_ja_confirmadas: int = 0
    # Parceladas puladas por dedup: a MESMA parcelada, materializada por um
    # import ANTERIOR, reaparece nesta fatura (X/N → (X+1)/N). Visível para o
    # skip não sumir em silêncio (MULTI-FATURA).
    parceladas_deduplicadas: int
    # Estornos (compra negativa na fatura) materializados como transação
    # tipo="estorno" (valor positivo, categoria da revisão/default "Outros") —
    # as agregações de consumo/fatura os SUBTRAEM. Também contam em
    # transacoes_criadas; aqui é o subconjunto, destacado.
    estornos_importados: int
    reconciliacao_bate: bool
