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


# Extrato do BATCH 2 (enriquecimento), desenhado para exercitar os três blocos:
#   - 3 débitos, DOIS com a mesma descrição (alvo do dedup: 2 pedidos, não 3);
#   - 1 pagamento_fatura em 10/06 citando "Nubank" (vence 13/06 -> distância 3);
#   - 2 receitas: 5000,00 em 05/06 (casa o salário) e 777,00 em 18/06 (não casa).
# O walk fecha: 1000 + 5777 − 130 − 200 = 6447.
EXTRATO_ENRIQUECIMENTO: dict = {
    "banco": "Nubank",
    "periodo": {"de": "2026-06-01", "ate": "2026-06-30"},
    "saldo_inicial": "1000.00",
    "saldo_final": "6447.00",
    "rendimento": "0.00",
    "linhas": [
        {
            "data": "2026-06-05",
            "descricao": "Salario ACME LTDA",
            "valor": "5000.00",
            "balde": "receita",
            "cartao_citado": None,
        },
        {
            "data": "2026-06-08",
            "descricao": "Compra no debito PADARIA CENTRAL",
            "valor": "50.00",
            "balde": "debito",
            "cartao_citado": None,
        },
        {
            "data": "2026-06-09",
            "descricao": "Compra no debito PADARIA CENTRAL",
            "valor": "50.00",
            "balde": "debito",
            "cartao_citado": None,
        },
        {
            "data": "2026-06-10",
            "descricao": "Pagamento de fatura Nubank",
            "valor": "200.00",
            "balde": "pagamento_fatura",
            "cartao_citado": "Nubank",
        },
        {
            "data": "2026-06-15",
            "descricao": "UBER TRIP",
            "valor": "30.00",
            "balde": "debito",
            "cartao_citado": None,
        },
        {
            "data": "2026-06-18",
            "descricao": "Pix recebido de FULANO",
            "valor": "777.00",
            "balde": "receita",
            "cartao_citado": None,
        },
    ],
}
