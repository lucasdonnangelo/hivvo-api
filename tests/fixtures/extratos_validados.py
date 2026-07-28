"""Extrato SINTÉTICO para os testes do preview de extrato.

Ao contrário de faturas_validadas.py (números REAIS do run do spike), aqui o
extrato é SINTÉTICO — o out/ do spike de extrato é gitignored (PII de contraparte
em Pix/TED) e não pode virar fixture. Os números foram desenhados para exercitar
o balance walk com os três baldes E o rendimento do resumo (ACHADO 1).

EXTRATO_COM_RENDIMENTO — o walk fecha SOMENTE com o rendimento no cálculo:
    saldo_inicial 1000.00 + rendimento 4.56
        + receitas 500.00 − debitos 120.00 − pagamento_fatura 200.00
    = 1184.56  == saldo_final declarado  -> BATE
Sem o rendimento, daria 1180.00 (dif -4.56) -> NÃO BATE. É o alvo da mutação:
remover `+ rendimento` do walk quebra o teste que usa este fixture.
"""

EXTRATO_COM_RENDIMENTO: dict = {
    "banco": "Nubank",
    "periodo": {"de": "2026-06-01", "ate": "2026-06-30"},
    "saldo_inicial": "1000.00",
    "saldo_final": "1184.56",
    "rendimento": "4.56",  # "Rendimento líquido" do RESUMO — não é linha
    "linhas": [
        {
            "data": "2026-06-05",
            "descricao": "Pix recebido",
            "valor": "500.00",
            "balde": "receita",
            "cartao_citado": None,
        },
        {
            "data": "2026-06-10",
            "descricao": "Compra no debito MERCADO EXEMPLO",
            "valor": "120.00",
            "balde": "debito",
            "cartao_citado": None,
        },
        {
            "data": "2026-06-20",
            "descricao": "Pagamento de fatura Nubank",
            "valor": "200.00",
            "balde": "pagamento_fatura",
            "cartao_citado": "Nubank",
        },
    ],
}
