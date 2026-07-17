"""Os NÚMEROS REAIS do run validado do spike (17/07/2026).

Espelham out/fatura_nubank_platinum.json e out/fatura_itau_platinum.json —
o run em que a reconciliação bateu nas duas faturas reais. NÃO substituir
por exemplos inventados: estes fixtures cristalizam a expectativa validada,
inclusive o cheque SECUNDÁRIO do Nubank que legitimamente NÃO bate
(pagamento de 12/06 pertence ao ciclo anterior).

Higiene (o out/ do spike é gitignored por conter PII): finais de cartão
trocados por sintéticos (1111/2222/3333) e a descrição com nome de pessoa
trocada por genérica. Valores, datas, tipos e totais são os reais.
"""

# Nubank 07/2026 — primário BATE (âncora 202.65 + 3.41 = 206.06);
# secundário NÃO bate (excluídos -58.95: pagamento do ciclo anterior).
NUBANK: dict = {
    "banco": "Nubank",
    "competencia": {"mes": 7, "ano": 2026},
    "periodo": {"de": "2026-06-06", "ate": "2026-07-06"},
    "emissao": "2026-07-06",
    "vencimento": "2026-07-13",
    "total_a_pagar": "206.06",
    "total_compras_periodo": "202.65",
    "total_iof_periodo": "3.41",
    "transacoes": [
        {
            "data": "2026-06-06",
            "descricao": "Blacktag",
            "valor_brl": "105.26",
            "tipo": "compra",
            "parcela": {"indice": 4, "total": 7},
            "portador_final": "1111",
            "internacional": None,
        },
        {
            "data": "2026-06-11",
            "descricao": "IOF de Anthropic",
            "valor_brl": "0.72",
            "tipo": "iof",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-11",
            "descricao": "Anthropic",
            "valor_brl": "20.67",
            "tipo": "compra",
            "parcela": None,
            "portador_final": "2222",
            "internacional": {"moeda_orig": "USD", "valor_orig": "3.86", "taxa": "5.35"},
        },
        {
            "data": "2026-07-02",
            "descricao": "Cloudflare",
            "valor_brl": "76.72",
            "tipo": "compra",
            "parcela": None,
            "portador_final": "2222",
            "internacional": {"moeda_orig": "USD", "valor_orig": "14.20", "taxa": "5.40"},
        },
        {
            "data": "2026-07-02",
            "descricao": "IOF de Cloudflare",
            "valor_brl": "2.69",
            "tipo": "iof",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-12",
            "descricao": "Pagamento em 12 JUN",
            "valor_brl": "-58.95",
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
    "total_compras_periodo": "93.95",
    "total_iof_periodo": "0.00",
    "transacoes": [
        {
            "data": "2026-06-16",
            "descricao": "Pagamento via conta",
            "valor_brl": "-93.95",
            "tipo": "pagamento",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-06-15",
            "descricao": "JIM.COM*ASSINATURA servicos SAOPAULO",
            "valor_brl": "93.95",
            "tipo": "compra",
            "parcela": None,
            "portador_final": "3333",
            "internacional": None,
        },
    ],
}
