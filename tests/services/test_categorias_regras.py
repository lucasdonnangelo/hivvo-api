"""A tabela de regras de lojista e os invariantes que a sustentam.

Testes PUROS (sem banco, sem rede): `casar_categoria_detalhado` é função pura
sobre (entrada, lista de nomes).

Dois deles não nasceram de uma feature, nasceram de DEFEITOS ENCONTRADOS, e
existem para que a classe do defeito não volte:

- `test_nenhuma_keyword_casa_linha_que_nao_e_compra`: "posto" casava dentro de
  "IMPOSTOS E ENCARGOS" — encargo de fatura virando Transporte, em silêncio,
  sem nenhum teste para pegar.
- `test_listas_padrao_so_compartilham_outros`: a verificação por mutação mostrou
  que o filtro de TIPO da camada 1 é hoje redundante com
  `validar_nome_categoria`. A redundância depende deste invariante — que era
  ASSUMIDO e agora é verificado.
"""

import pytest

from app.services.categorias import (
    ADQUIRENTES,
    CATEGORIA_NEUTRA,
    CATEGORIAS_PADRAO,
    KEYWORDS_GENERICAS,
    KEYWORDS_INICIO,
    KEYWORDS_REDES,
    casar_categoria_detalhado,
)
from tests.fixtures.faturas_sinteticas import (
    LINHAS_COMPRA_SINTETICAS,
    LINHAS_NAO_COMPRA,
)

NOMES_DESPESA = [c.nome for c in CATEGORIAS_PADRAO if c.tipo == "despesa"]
NOMES_RECEITA = [c.nome for c in CATEGORIAS_PADRAO if c.tipo == "receita"]

TODAS_AS_REGRAS = (
    [(f"adquirente:{k}", alvo) for k, alvo in ADQUIRENTES.items()]
    + [(f"keyword:{k}", alvo) for k, alvo in KEYWORDS_GENERICAS + KEYWORDS_REDES]
    + [(f"inicio:{k}", alvo) for k, alvo in KEYWORDS_INICIO]
)


# --- Invariantes da tabela ----------------------------------------------------


def test_listas_padrao_so_compartilham_outros():
    """As listas padrão de despesa e receita só têm "Outros" em comum.

    Não é curiosidade: é o que torna `validar_nome_categoria` capaz de barrar
    sozinho uma categoria do tipo errado — e, portanto, o que hoje deixa o
    filtro `tipo IN (...)` da camada 1 (import_fatura/enriquecimento) ser
    DEFESA EM PROFUNDIDADE em vez de a única barreira.

    No dia em que alguém puser um nome nas duas listas, este teste reclama —
    em vez de a redundância sumir em silêncio e o filtro virar a única coisa
    entre um histórico de receita e uma compra de cartão.
    """
    assert set(NOMES_DESPESA) & set(NOMES_RECEITA) == {CATEGORIA_NEUTRA}


@pytest.mark.parametrize("rotulo,alvo", TODAS_AS_REGRAS)
def test_toda_regra_aponta_para_categoria_que_existe(rotulo, alvo):
    """Alvo com typo é regra MORTA: `validar_nome_categoria` a rejeita e a linha
    cai em "Outros" sem nenhum sinal. A tabela é longa e escrita à mão."""
    assert alvo in NOMES_DESPESA, f"{rotulo} aponta para categoria inexistente: {alvo!r}"


@pytest.mark.parametrize("linha", LINHAS_NAO_COMPRA)
def test_nenhuma_keyword_casa_linha_que_nao_e_compra(linha):
    """ZERO match nas linhas que não são consumo.

    A classe de defeito: keyword curta casando DENTRO de uma palavra maior.
    Encontrada com "posto" ⊂ "IMPOSTOS E ENCARGOS" (→ Transporte) e "otica" ⊂
    "Exóticas" (→ Saúde). A primeira não tinha teste nenhum para pegá-la; a
    segunda só caiu porque um teste do EXTRATO passava pela mesma função.

    Toda keyword nova tem que passar por aqui. Se este teste ficar vermelho ao
    adicionar uma entrada, a entrada é curta demais — ou vira `KEYWORDS_INICIO`
    (ancorada), ou não entra.
    """
    categoria, passe = casar_categoria_detalhado(linha, NOMES_DESPESA)

    assert (categoria, passe) == (CATEGORIA_NEUTRA, None), (
        f"{linha!r} não é compra e casou {passe} -> {categoria}"
    )


# --- Corpus sintético de compras ----------------------------------------------


@pytest.mark.parametrize("descricao,esperada", LINHAS_COMPRA_SINTETICAS)
def test_corpus_sintetico_de_lojistas(descricao, esperada):
    """Os FORMATOS reais da fatura, com lojistas inventados.

    Regressão, não medição — o número de cobertura que vale sai de
    `scripts/medir_auto_categoria.py` sobre os dumps reais (gitignored).
    `esperada=None` significa "o certo é NÃO sugerir": chutar numa descrição
    ilegível é pior que admitir que não dá para saber.
    """
    categoria, passe = casar_categoria_detalhado(descricao, NOMES_DESPESA)

    if esperada is None:
        assert (categoria, passe) == (CATEGORIA_NEUTRA, None)
    else:
        assert passe is not None, f"{descricao!r} não casou regra nenhuma"
        assert categoria == esperada


# --- Ordem dos passes ---------------------------------------------------------


def test_exato_vence_regra():
    """Categoria CUSTOMIZADA do usuário nunca é sequestrada por uma keyword."""
    nomes = NOMES_DESPESA + ["Padaria"]

    assert casar_categoria_detalhado("Padaria", nomes) == ("Padaria", "exato")


def test_substring_vence_keyword():
    """Mesma proteção, por contenção: quem tem "Padaria" recebe "Padaria",
    não a "Alimentação" da regra genérica."""
    nomes = NOMES_DESPESA + ["Padaria"]

    assert casar_categoria_detalhado("PADARIA CENTRAL", nomes) == (
        "Padaria",
        "substring",
    )


def test_adquirente_vence_substring():
    """O passe de adquirente é o único ANTES do substring, e é seguro porque só
    dispara com "*" na entrada — nome de categoria não tem "*".

    Ele corrige o caso real em que o rótulo do banco (#40) contradiz o lojista:
    a Itaú imprime "EDUCAÇÃO." numa festa junina paga via ZIG.
    """
    assert casar_categoria_detalhado(
        "ZIG*FESTAJUNINA EDUCAÇÃO.SAOPAULO", NOMES_DESPESA
    ) == ("Lazer", "adquirente:zig")


def test_regra_de_despesa_nao_alcanca_lista_de_receita():
    """O alvo de toda regra é revalidado contra `nomes`: numa linha de receita,
    "Alimentação" não existe e a regra não vale. É o que mantém verde o
    test_categoria_de_despesa_sugerida_para_receita_cai_em_outros do extrato."""
    assert casar_categoria_detalhado("PADARIA CENTRAL", NOMES_RECEITA) == (
        CATEGORIA_NEUTRA,
        None,
    )


def test_adquirente_horizontal_nao_tem_regra():
    """MP*/PAG*/CIELO* processam qualquer coisa. Ausência DELIBERADA."""
    for horizontal in ("mp", "pag", "pagseguro", "cielo", "rede", "stone", "sumup"):
        assert horizontal not in ADQUIRENTES
