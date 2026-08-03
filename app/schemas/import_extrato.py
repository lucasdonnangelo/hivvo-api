"""Contrato da importação de EXTRATO de conta: texto -> JSON estruturado (+ response da rota).

ExtratoExtraido é porte do spike validado (scripts/spike_extrato/schema.py) com
UM acréscimo de produção — o campo `rendimento` (o "Rendimento líquido" do RESUMO
do extrato, que NÃO é linha de movimentação). É usado duas vezes, igual à fatura:
1. Como response_schema do Gemini (força a resposta no shape certo).
2. Como validação local da resposta (cinto e suspensório).
NÃO altere campos ou validadores sem revalidar contra extratos reais.

Datas são `str` ISO (YYYY-MM-DD) e valores são `str` decimais — tipos primitivos
evitam surpresa na conversão Pydantic -> Schema da API Gemini; os validadores
garantem que o conteúdo parseia de verdade.

Decisão de sinal (do spike): a DIREÇÃO do dinheiro vem do `balde`, não do sinal do
valor. `valor` de linha é sempre MAGNITUDE positiva (casa com o CHECK `valor > 0`
da Transacao em produção — direção via `tipo`). Só os SALDOS e o rendimento
carregam sinal (cheque especial existe; rendimento é normalmente positivo).

O balance walk NÃO faz parte deste contrato de propósito: LLM não faz aritmética
confiável — o walk é calculado em Python (ver
app/services/import_extrato/reconciliacao.py) e devolvido em ReconciliacaoExtratoOut,
com decimais como string.

Pela MESMA razão (schema dual-use), o enriquecimento do Batch 2 (categoria
sugerida, fatura proposta, flag de recorrência) vive num array PARALELO
(EnriquecimentoLinha), alinhado a `linhas` por índice explícito — nunca dentro de
LinhaExtrato, que o Gemini preencheria.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


def normalizar_decimal(bruto: str) -> str:
    """Aceita '3.412,88', '3412.88', '-58,95', 'R$ 1.234,56' -> '3412.88' (PRESERVA sinal).

    Ver a extração vale mais do que punir formato: normaliza em vez de rejeitar
    duro. Só rejeita o que não parseia.
    Ambiguidade assumida: '3.412' sem vírgula é lido como 3.412 (o prompt pede
    ponto decimal, então ponto sozinho é tratado como decimal).
    """
    s = bruto.strip().replace("R$", "").replace(" ", "").replace("\xa0", "")
    if "," in s:
        # vírgula presente => separador decimal pt-BR; pontos são milhar
        s = s.replace(".", "").replace(",", ".")
    try:
        return str(Decimal(s))
    except InvalidOperation:
        raise ValueError(f"valor decimal não parseável: {bruto!r}")


def normalizar_magnitude(bruto: str) -> str:
    """Como normalizar_decimal, mas devolve a MAGNITUDE (sem sinal).

    A direção vem do balde; se o modelo mandar o sinal impresso do extrato
    (débito negativo), abate-se aqui em vez de rejeitar.
    """
    return str(abs(Decimal(normalizar_decimal(bruto))))


def _validar_data_iso(v: str) -> str:
    date.fromisoformat(v)  # levanta ValueError se não for YYYY-MM-DD válido
    return v


class Balde(StrEnum):
    receita = "receita"                    # entrada de caixa
    debito = "debito"                      # saída de caixa que É consumo
    pagamento_fatura = "pagamento_fatura"  # saída de caixa que NÃO é consumo


class Periodo(BaseModel):
    de: str
    ate: str

    _datas = field_validator("de", "ate")(_validar_data_iso)


class LinhaExtrato(BaseModel):
    data: str
    descricao: str
    valor: str  # MAGNITUDE positiva; a direção vem do balde
    balde: Balde
    # só pagamento_fatura: banco/cartão citado na linha; null se a linha não nomeia
    cartao_citado: str | None = None

    _data = field_validator("data")(_validar_data_iso)
    _valor = field_validator("valor")(
        classmethod(lambda cls, v: normalizar_magnitude(v))
    )

    @model_validator(mode="after")
    def _cartao_so_em_pagamento(self) -> "LinhaExtrato":
        # cartao_citado só faz sentido em pagamento_fatura: zera fora dele
        # (dado limpo) e normaliza string vazia -> None.
        if self.balde is not Balde.pagamento_fatura:
            self.cartao_citado = None
        elif self.cartao_citado is not None:
            self.cartao_citado = self.cartao_citado.strip() or None
        return self


class ExtratoExtraido(BaseModel):
    banco: str  # banco da CONTA (ex.: "Nubank")
    periodo: Periodo | None = None
    # saldos IMPRESSOS no extrato, COM sinal (negativo = conta negativa);
    # null quando o extrato não os imprime -> balance walk vira N/A
    saldo_inicial: str | None = None
    saldo_final: str | None = None
    # ACHADO 1 (produção): o "Rendimento líquido" do RESUMO do extrato — NÃO é
    # linha de movimentação. Entra no balance walk como crédito. Default "0.00"
    # quando o extrato não o imprime.
    rendimento: str = "0.00"
    linhas: list[LinhaExtrato]

    _saldos = field_validator("saldo_inicial", "saldo_final")(
        classmethod(lambda cls, v: None if v is None else normalizar_decimal(v))
    )
    _rendimento = field_validator("rendimento")(
        classmethod(lambda cls, v: normalizar_decimal(v))
    )


class ReconciliacaoExtratoOut(BaseModel):
    """Resultado do balance walk determinístico — decimais como string.

    `bate=False` NÃO é erro HTTP: a rota devolve 200 e o cliente decide.
    `aplicavel=False` quando o extrato não imprime saldo_inicial E saldo_final
    (walk N/A) — aí `bate` é sempre False (não há o que conferir).
    """

    aplicavel: bool
    saldo_inicial: str
    rendimento: str
    soma_receitas: str
    soma_debitos: str
    soma_pagamentos_fatura: str
    saldo_final_calc: str  # saldo_inicial + rendimento + receitas − debitos − pagamentos
    saldo_final_declarado: str
    diferenca: str  # saldo_final_calc − saldo_final_declarado
    bate: bool


class ItemCategoria(BaseModel):
    """Um item da resposta da categorização em LOTE (response_schema do Gemini).

    `indice` é o índice do PEDIDO enviado (não o da linha do extrato): o
    alinhamento é explícito, nunca por posição — o modelo pode devolver menos
    itens, fora de ordem ou repetidos sem desalinhar as demais linhas.
    """

    indice: int
    categoria: str


class CategorizacaoLote(BaseModel):
    """Resposta da chamada ÚNICA de categorização (ver services/import_extrato/gemini)."""

    itens: list[ItemCategoria]


class FaturaCandidataOut(BaseModel):
    """Uma fatura (cartão + competência) que PODE ser a quitada pela linha.

    O valor é sinal de CONFIANÇA, não filtro: `diferenca`/`valor_bate` anotam o
    quanto o pagamento cobre o total ATUAL da fatura (pagamento parcial/mínimo
    é real), mas nunca eliminam a candidata.
    """

    cartao_id: int
    cartao_nome: str
    fatura_mes: int
    fatura_ano: int
    total_fatura: str  # total ATUAL — fonte única da composição (services/faturas)
    diferenca: str  # valor da linha − total_fatura
    valor_bate: bool  # |diferenca| <= TOLERANCIA
    ja_paga: bool  # já existe PagamentoFatura pago=True nessa competência


class FaturaPropostaOut(BaseModel):
    """PROPOSTA de casamento pagamento↔fatura — o preview nunca decide.

    - `match_unico`: exatamente uma candidata (1 elemento em `candidatas`);
    - `ambiguo`: N candidatas (ex.: dois cartões do mesmo banco), ordenadas por
      confiança — a de valor exato vem primeiro, mas NÃO colapsa para match
      único (o sistema não sabe qual é; o usuário confirma na revisão);
    - `sem_match`: nenhuma (`motivo` diz se é emissor desconhecido ou fatura
      não importada — "importe a fatura").
    """

    status: Literal["match_unico", "ambiguo", "sem_match"]
    candidatas: list[FaturaCandidataOut] = []
    motivo: str | None = None


class RecorrenciaCasadaOut(BaseModel):
    """A recorrência que provavelmente já explica esta receita (armadilha do salário)."""

    id: uuid.UUID
    descricao: str
    categoria: str
    valor_vigente: str
    dia_do_mes: int
    competencia_mes: int
    competencia_ano: int


class EnriquecimentoLinha(BaseModel):
    """Enriquecimento de UMA linha, endereçado por `indice` em extrato.linhas.

    Vive FORA de LinhaExtrato de propósito: LinhaExtrato é o response_schema do
    Gemini de extração (ver topo do módulo) — engordá-la faria o modelo de
    extração tentar preencher o enriquecimento. Array paralelo, alinhado por
    índice EXPLÍCITO (não por posição).

    Cada campo só é preenchido no balde a que pertence:
    - `categoria_sugerida`: debito e receita (None = não foi possível sugerir —
      a chamada de categorização falhou; "Outros" é palpite, None é ausência);
    - `fatura_proposta`: pagamento_fatura;
    - `provavel_recorrencia`/`recorrencia_casada`: receita.
    - `data_suspeita`: TODOS os baldes — a data cai fora do período do documento
      (#46). Aqui o intervalo INTEIRO vale como limite (diferente da fatura, que
      só tem limite superior): o período do extrato é um intervalo REAL impresso
      no documento, sem parcela antiga esticando a faixa para trás.
    """

    indice: int
    categoria_sugerida: str | None = None
    fatura_proposta: FaturaPropostaOut | None = None
    provavel_recorrencia: bool = False
    recorrencia_casada: RecorrenciaCasadaOut | None = None
    # SINAL, não gate (ver services/import_extrato/enriquecimento.datas_suspeitas).
    # Os dois lados são valores DISTINTOS de propósito: a cópia da revisão difere
    # ("antes do período" ≠ "depois do período") e um bool obrigaria o front a
    # re-derivar qual — reimplementar a regra do lado errado. Default None →
    # aditivo.
    data_suspeita: Literal["antes_do_periodo", "depois_do_periodo"] | None = None


class ExtratoPreviewResponse(BaseModel):
    # Sem cartao_id: o extrato é da CONTA, não de um cartão.
    extrato: ExtratoExtraido
    reconciliacao: ReconciliacaoExtratoOut
    # Um item por linha de extrato.linhas, na mesma ordem (Batch 2). O
    # `rendimento` do RESUMO não entra: não é linha.
    enriquecimento: list[EnriquecimentoLinha] = []


# --- Batch 3: commit (materializa os três baldes + o rendimento) -------------
#
# O request reusa o contrato da extração por SUBCLASSE — herda campos e
# validadores de LinhaExtrato/ExtratoExtraido sem duplicá-los e sem tocar no
# schema que o Gemini consome (o mesmo padrão do TransacaoCommit da fatura). As
# adições são as DECISÕES da revisão: importar?, categoria, e o cartão +
# competência CONFIRMADOS para cada pagamento de fatura.


class LinhaCommit(LinhaExtrato):
    """Uma linha do extrato REVISADO — dado extraído + decisão do usuário.

    `importar` é TRI-ESTADO de propósito:
    - `True`/`False`: o usuário decidiu — vale sempre, sobrepõe tudo;
    - `None` (ausente): NÃO decidido → o servidor aplica o default seguro
      (services/import_extrato/persistencia.resolver_indecisos), que para
      RECEITA recomputa o casamento com recorrência (a armadilha do salário
      duplicado) e não importa quando casa. O default mora no BACKEND, não na
      confiança de que o front mandou a flag certa.

    `cartao_id`/`fatura_mes`/`fatura_ano` só existem no balde pagamento_fatura e
    são OBRIGATÓRIOS quando a linha vai ser importada: o casamento é PROPOSTO no
    preview e CONFIRMADO na revisão — o commit nunca adivinha qual fatura foi
    quitada. Fora do balde, são zerados (dado limpo, como cartao_citado).
    """

    importar: bool | None = None
    categoria: str = "Outros"  # revalidada contra as categorias DO USUÁRIO
    cartao_id: int | None = None
    fatura_mes: int | None = None
    fatura_ano: int | None = None

    @model_validator(mode="after")
    def _decisao_de_pagamento_completa(self) -> "LinhaCommit":
        if self.balde is not Balde.pagamento_fatura:
            self.cartao_id = None
            self.fatura_mes = None
            self.fatura_ano = None
            return self
        if self.importar is False:
            return self  # descartada: não precisa de confirmação
        faltando = [
            nome
            for nome in ("cartao_id", "fatura_mes", "fatura_ano")
            if getattr(self, nome) is None
        ]
        if faltando:
            raise ValueError(
                "pagamento de fatura sem confirmação de "
                f"{', '.join(faltando)} — confirme o cartão e a competência na "
                "revisão ou marque a linha como não importar"
            )
        if not 1 <= self.fatura_mes <= 12:
            raise ValueError(f"mês de fatura fora de 1..12: {self.fatura_mes}")
        if self.fatura_ano < 2000:
            raise ValueError(f"ano de fatura inválido: {self.fatura_ano}")
        return self


class ExtratoCommit(ExtratoExtraido):
    linhas: list[LinhaCommit]


class ExtratoCommitRequest(BaseModel):
    extrato: ExtratoCommit
    # O rendimento do RESUMO vira receita "Rendimentos" (ACHADO 1). É decisão da
    # revisão como qualquer linha — quem já acompanha o rendimento por fora
    # desmarca. Só materializa se > 0.
    importar_rendimento: bool = True


class ExtratoCommitResponse(BaseModel):
    """Recibo do commit — tudo que foi gravado, para o front conferir."""

    # Linhas do balde `receita` que viraram Transacao. NÃO inclui o rendimento
    # (que não é linha) — ele tem flag própria.
    receitas_criadas: int
    debitos_criados: int
    # PagamentoFatura gravados (pago=True) com o valor e a data REAIS do
    # extrato. Duas linhas para a MESMA (cartão, competência) somam num único
    # registro — contam 1 aqui.
    pagamentos_registrados: int
    # Subconjunto: competências que JÁ tinham pago=True (valor ASSUMIDO pelo
    # import de fatura, ou confirmação anterior) e cujo valor_pago foi
    # substituído pelo valor REAL do extrato — a fonte autoritativa (#9).
    pagamentos_sobrescritos: int
    rendimento_importado: bool
    # Linhas com decisão final "não importar" (explícita do usuário ou default
    # seguro do servidor).
    linhas_ignoradas: int
    # Subconjunto de linhas_ignoradas: receitas INDECISAS que casaram com uma
    # recorrência vigente e o servidor deixou de fora (armadilha do salário).
    receitas_puladas_recorrencia: int
    reconciliacao_bate: bool
