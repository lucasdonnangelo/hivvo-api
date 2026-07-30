"""Limpeza da descrição de lojista impressa pela fatura (#40).

A Itaú imprime, colado na descrição, a CATEGORIA do lojista segundo o emissor e
a CIDADE da compra:

    "SUPERMERCADOSBERG ALIMENTAÇÃO.SAOPAULO"
    "PostoDe VEÍCULOS.SAOPAULO"

e a extração às vezes mantém esse rabo, às vezes corta — MEDIDO em 4 execuções
do MESMO PDF: 2 de cada lado. O rabo não é dado do usuário, é layout do
documento; e a instabilidade dele CORROMPE dado:

    A identidade de dedup de uma parcelada é
    (descrição normalizada, total, competência de origem, valor da parcela).
    Julho extrai "SUPERMERCADOSBERG" na parcela 1/2, agosto extrai
    "SUPERMERCADOSBERG ALIMENTAÇÃO.SAOPAULO" na 2/2 → as identidades não casam
    → o import de agosto não reconhece o cronograma já existente e cria OUTRO
    → a parcela é contada em DOBRO na projeção.

    Silencioso: a reconciliação de cada fatura, isolada, continua batendo — o
    erro mora ENTRE importações. E não-determinístico: ~moeda a cada import.

Por que remover no SERVIDOR e não pedir o campo separado ao modelo: um campo
`categoria_emissor` no schema PEDE que o modelo ponha a categoria noutro lugar,
mas não GARANTE que a descrição venha limpa — a nondeterminância voltaria pela
mesma porta. Já "remover se houver" é IDEMPOTENTE: dá o mesmo resultado com o
rabo presente ou ausente, que é exatamente a propriedade que a identidade
precisa. O campo próprio continua valendo como SINAL de categorização (o rótulo
do banco acerta na maioria das linhas), mas isso é enhancement, não este fix.

Não toca o PROMPT nem o que é EXIBIDO/gravado: `Transacao.descricao` continua
sendo o texto extraído. A limpeza vale só onde a descrição vira CHAVE.
"""

from __future__ import annotations

import re

# " CATEGORIA.CIDADE" no FIM da string.
#
# - a categoria é o sinal confiável: bloco de 4+ letras MAIÚSCULAS (com acento)
#   seguido de ponto. O mínimo de 4 evita comer sigla legítima ("LOJA S.A");
#   as reais são todas longas (SAÚDE, HOBBY, DIVERSOS, VEÍCULOS, VESTUÁRIO,
#   ALIMENTAÇÃO, EDUCAÇÃO, TURISMOEENTRETENIM).
# - a cidade pode vir em qualquer caixa ("SAOPAULO", "SaoPaulo", "SAOCAETANOD")
#   ou VAZIA ("ALIMENTAÇÃO.") — por isso `*` e não `+`.
_RABO_CATEGORIA_CIDADE = re.compile(r"\s+[A-ZÀ-Ü]{4,}\.[A-Za-zÀ-ü]*\s*$")


def limpar_rabo_do_emissor(descricao: str) -> str:
    """Remove o " CATEGORIA.CIDADE" que o emissor cola na descrição, se houver.

    IDEMPOTENTE por construção — é o ponto todo:

        limpar("SUPERMERCADOSBERG")                        -> "SUPERMERCADOSBERG"
        limpar("SUPERMERCADOSBERG ALIMENTAÇÃO.SAOPAULO")   -> "SUPERMERCADOSBERG"
        limpar("IFD *KAMIAFITLTDA ALIMENTAÇÃO.")           -> "IFD *KAMIAFITLTDA"

    LIMITE CONHECIDO: a Itaú às vezes imprime só a CIDADE, sem categoria e sem
    ponto ("VICEMALOTERIASLTDA SaoPaulo"). Sem o ponto não há sinal que
    distinga cidade de nome de lojista, e uma regra de "corta a última palavra
    maiúscula" comeria "LOJA CENTRO". 4 ocorrências em ~380 linhas medidas;
    fica de fora deliberadamente — resgatar essas 4 custaria falso positivo em
    lojista legítimo, e o erro aqui é pior nessa direção (identidade que colide
    a mais faz o import PULAR uma compra de verdade).
    """
    return _RABO_CATEGORIA_CIDADE.sub("", descricao)


def chave_descricao(descricao: str) -> str:
    """A descrição em forma CANÔNICA, para usar como CHAVE.

    Fonte única de "duas descrições se referem ao mesmo lançamento?", usada
    pela identidade de dedup de parcelada (persistencia) e pelo casamento com o
    histórico do usuário (enriquecimento) — que sofriam do mesmo drift.

    Tira o rabo do emissor, colapsa espaço e aplica casefold. NÃO tira acento:
    o mesmo lojista não troca acento entre faturas; o drift real é caixa,
    espaço e o rabo.
    """
    return " ".join(limpar_rabo_do_emissor(descricao).split()).casefold()
