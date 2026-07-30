"""Corpora SINTÉTICOS para exercitar a tabela de regras de lojista em CI.

Os dumps reais (`scripts/spike_import/out/*.json`) são gitignored e devem
continuar sendo — são a fatura de uma pessoa. Estes corpora reproduzem os
FORMATOS que aparecem lá, com nomes inventados, para que o teste rode sem
carregar dado de ninguém.

Medição sobre dado real continua sendo `scripts/medir_auto_categoria.py`,
ad-hoc. Aqui é regressão, não medição: o número que vale é o de lá.
"""

# --- Linhas que NÃO são compra -------------------------------------------------
#
# A classe de defeito que isto trava: keyword curta casando dentro de linha que
# não é consumo. Descoberta com "posto" casando em "IMPOSTOS E ENCARGOS" — que
# nenhum teste pegaria e classificaria encargo de fatura como Transporte, em
# silêncio. A lista de linhas não-compra de uma fatura é curta e enumerável;
# exigir ZERO match contra ela transforma a auditoria manual em guarda.
#
# Toda keyword nova entra na tabela tendo que passar por aqui.
LINHAS_NAO_COMPRA = [
    "IMPOSTOS E ENCARGOS",
    "Encargos de imposto sobre operacao",
    "IOF",
    "IOF de transacoes internacionais",
    "JUROS DE MORA",
    "Juros do rotativo",
    "CREDITO ROTATIVO",
    "MULTA POR ATRASO",
    "ANUIDADE DIFERENCIADA",
    "Anuidade parcelada 3/12",
    "SEGURO PROTECAO PREMIADA",
    "Seguro de fatura protegida",
    "TARIFA DE AVALIACAO EMERGENCIAL",
    "PAGAMENTO EFETUADO",
    "Pagamento em 12 JUN",
    "PAGTO DEBITO AUTOMATICO",
    "SALDO ANTERIOR",
    "Saldo restante da fatura anterior",
    "AJUSTE A CREDITO",
    "AJUSTE DE SALDO",
    "ESTORNO DE COMPRA",
    "Estorno de anuidade",
    "PARCELAMENTO DE FATURA",
    "TOTAL DA FATURA ANTERIOR",
    "CREDITO DE ATRASO",
    "DESCONTO CONCEDIDO",
    "CONVERSAO DE MOEDA ESTRANGEIRA",
    "COMPRA INTERNACIONAL",
    # Respostas absurdas de modelo já vistas na suíte — o guarda-corpo do
    # /ai/suggest-category e do lote do extrato passa pela MESMA função.
    "Categoria Inventada",
    "Criptomoedas Exoticas",
    "Criptomoedas Exóticas",
    "Robotica educacional",
    "Servico caotico",
]

# --- Linhas de compra, nos formatos reais, com lojistas INVENTADOS -------------
#
# (descrição, categoria esperada). Formatos copiados da Itaú: prefixo de
# adquirente com "*", descrição colada sem espaço e truncada em ~20 chars, e o
# sufixo CATEGORIA.CIDADE que o banco às vezes imprime (ver #40).
LINHAS_COMPRA_SINTETICAS = [
    # adquirente de vertical conhecida
    ("IFD*99887766FULANOD", "Alimentação"),
    ("IFD *XPTOCOMERCIOLTDA", "Alimentação"),
    ("Kee*BELTRANOSNACKS", "Alimentação"),
    ("KEETABR*ZZCOMERCIODE", "Alimentação"),
    ("99Food*QQDELIVERYLT", "Alimentação"),
    ("ZIG*FESTADEXPTOLTDA", "Lazer"),
    ("Microsoft*Microsoft36", "Assinaturas"),
    # palavra-chave genérica, descrição colada
    ("SUPERMERCADOFULANO", "Alimentação"),
    ("HORTIFRUTIDOBELTRANO", "Alimentação"),
    ("PADARIAXPTO", "Alimentação"),
    ("LanchoneteZZZ", "Alimentação"),
    ("RESTAURANTEQQCOISA", "Alimentação"),
    ("MerceariaDoFulano", "Alimentação"),
    ("CENTROAUTOMOTIVOXPTO", "Transporte"),
    ("AUTOPOSTOBELTRANO", "Transporte"),
    ("PostoZZ", "Transporte"),
    ("LavaRapidoXPTO", "Transporte"),
    ("DROGARIAFULANO123", "Saúde"),
    ("CLINICABELTRANOLTDA", "Saúde"),
    ("ACADEMIAXPTOFIT", "Saúde"),
    ("PETSHOPDOFULANO", "Pets"),
    # com o sufixo CATEGORIA.CIDADE do banco (#40): o passe de substring pega a
    # palavra do banco antes das keywords — comportamento conhecido, não acidente
    ("SUPERMERCADOFULANO ALIMENTAÇÃO.CIDADEX", "Alimentação"),
    ("PostoZZ VEÍCULOS.CIDADEX", "Transporte"),
    # ilegíveis: o certo é NÃO sugerir (None), não chutar
    ("AVFULANODETAL", None),
    ("XPTOSHOP", None),
    ("MP*BELTRANODASILVA", None),  # adquirente HORIZONTAL, de propósito
]
