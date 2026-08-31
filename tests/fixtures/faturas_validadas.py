"""As FORMAS validadas no run do spike (17/07/2026), com dados sintéticos.

Espelham a ESTRUTURA de out/fatura_nubank_platinum.json e
out/fatura_itau_platinum.json — o run em que a reconciliação bateu nas duas
faturas reais. O que estes fixtures cristalizam é a expectativa validada:
a forma das linhas, os tipos, a relação entre os totais, e o cheque
SECUNDÁRIO do Nubank que legitimamente NÃO bate (o pagamento de 12/06
pertence ao ciclo anterior). Nada disso depende de o número ser o real.

HIGIENE — por que nenhum dado aqui é de uma fatura de verdade. O out/ do
spike é gitignored por conter PII, mas estes fixtures nasceram copiando
dele: finais de cartão viraram sintéticos (1111/2222/3333) e a descrição
com nome de pessoa virou genérica, e o resto ficou real. Com os repos
públicos isso passou a ser o extrato financeiro de uma pessoa publicado em
dois lugares — lojista nomeado, valor exato, ciclo exato, parcela em curso.
Lojistas e valores foram trocados por sintéticos em 31/08/2026, mantendo a
aritmética que os testes exercitam:

    Nubank  compras 120,00 + 30,00 + 80,00 = 230,00
            IOF        1,05 +  2,80        =   3,85
            total a pagar                  = 233,85
            excluído (pagamento do ciclo anterior) = -60,00
            parcelada 4/7: 120,00 × 7      = 840,00
    Itaú    compra 88,40 · pagamento -88,40 · a pagar 0,00

As DATAS continuam as do run: o ciclo (06/06→06/07) e o vencimento são a
espinha de que a derivação de competência depende, e uma data sozinha não
identifica ninguém.
"""

# Nubank 07/2026 — primário BATE (âncora 230.00 + 3.85 = 233.85);
# secundário NÃO bate (excluídos -60.00: pagamento do ciclo anterior).
NUBANK: dict = {
    "banco": "Nubank",
    "competencia": {"mes": 7, "ano": 2026},
    "periodo": {"de": "2026-06-06", "ate": "2026-07-06"},
    "emissao": "2026-07-06",
    "vencimento": "2026-07-13",
    "total_a_pagar": "233.85",
    "total_compras_periodo": "230.00",
    "total_iof_periodo": "3.85",
    "transacoes": [
        {
            "data": "2026-06-06",
            "descricao": "Vexora",
            "valor_brl": "120.00",
            "tipo": "compra",
            "parcela": {"indice": 4, "total": 7},
            "portador_final": "1111",
            "internacional": None,
        },
        {
            "data": "2026-06-11",
            "descricao": "IOF de Quandril",
            "valor_brl": "1.05",
            "tipo": "iof",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-11",
            "descricao": "Quandril",
            "valor_brl": "30.00",
            "tipo": "compra",
            "parcela": None,
            "portador_final": "2222",
            "internacional": {"moeda_orig": "USD", "valor_orig": "6.00", "taxa": "5.00"},
        },
        {
            "data": "2026-07-02",
            "descricao": "Zentaro",
            "valor_brl": "80.00",
            "tipo": "compra",
            "parcela": None,
            "portador_final": "2222",
            "internacional": {"moeda_orig": "USD", "valor_orig": "16.00", "taxa": "5.00"},
        },
        {
            "data": "2026-07-02",
            "descricao": "IOF de Zentaro",
            "valor_brl": "2.80",
            "tipo": "iof",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-12",
            "descricao": "Pagamento em 12 JUN",
            "valor_brl": "-60.00",
            "tipo": "pagamento",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-15",
            "descricao": "Saldo restante da fatura anterior",
            "valor_brl": "0.00",
            "tipo": "ajuste_saldo",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-15",
            "descricao": "Saldo restante da fatura anterior",
            "valor_brl": "0.00",
            "tipo": "ajuste_saldo",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
    ],
}

# Itaú 07/2026 — IOF embutido no total de compras (total_iof_periodo "0.00"),
# fatura já quitada (total_a_pagar "0.00"): ancorar no "a pagar" daria falso
# NÃO BATE. Primário e secundário batem.
ITAU: dict = {
    "banco": "Itaú",
    "competencia": {"mes": 7, "ano": 2026},
    "periodo": {"de": "2026-05-29", "ate": "2026-06-28"},
    "emissao": "2026-06-28",
    "vencimento": "2026-07-06",
    "total_a_pagar": "0.00",
    "total_compras_periodo": "88.40",
    "total_iof_periodo": "0.00",
    "transacoes": [
        {
            "data": "2026-06-16",
            "descricao": "Pagamento via conta",
            "valor_brl": "-88.40",
            "tipo": "pagamento",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-15",
            "descricao": "JIM.COM*ASSINATURA servicos SAOPAULO",
            "valor_brl": "88.40",
            "tipo": "compra",
            "parcela": None,
            "portador_final": "3333",
            "internacional": None,
        },
    ],
}
