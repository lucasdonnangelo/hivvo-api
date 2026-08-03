"""Validação de data da importação (#46) — as duas regras PURAS, sem banco e sem rede.

O bug: duas extrações do MESMO PDF (fatura Itaú, mesma config) devolveram a mesma
compra ora em 2026-06-29, ora em 2026-07-29 — um mês de diferença. A fatura foi
EMITIDA em 2026-07-25, então 07-29 é impossível: compra quatro dias depois da
emissão não existe naquele documento. **A reconciliação passou nas duas** (dif
0.00, bate=True): ela soma VALORES, e o valor estava certo. Uma linha um mês fora
entra na FATURA ERRADA — a data da compra deriva a competência pelo fechamento do
cartão — e "A pagar" e a projeção de 12 meses herdam o erro sem nenhum sinal.

Duas regras, de propósito assimétricas:
- FATURA: só o limite SUPERIOR (`data > emissao`). `periodo.de` NÃO serve de
  limite inferior — é a data de ORIGEM da parcela mais antiga, não o início do
  ciclo; usá-lo seria circular e flagaria parcelamento longo legítimo.
- EXTRATO: o intervalo INTEIRO. Ali o período é um intervalo real do documento e
  não tem parcela esticando a faixa.

VERIFICAÇÃO POR MUTAÇÃO (`scripts/mutacoes/data_suspeita.json`): inverter o
comparador da emissão (`>` -> `>=`) derruba `test_fatura_limite_exato_nao_flaga`.

Higiene: as descrições aqui são GENÉRICAS. O dump que revelou o bug é gitignored
por conter PII, e o lojista da linha errada é um serviço de saúde — o que a
evidência precisa é a DATA e a ÂNCORA, não o nome.
"""

import pytest

from app.schemas.import_extrato import ExtratoExtraido
from app.schemas.import_fatura import FaturaExtraida
from app.services.import_extrato.enriquecimento import (
    datas_suspeitas as datas_suspeitas_extrato,
)
from app.services.import_fatura.enriquecimento import (
    datas_suspeitas as datas_suspeitas_fatura,
    indices_materializaveis,
)

# --- Fatura -------------------------------------------------------------------

# Os números REAIS do documento que expôs o bug: emissão 2026-07-25, período
# 2025-11-28 -> 2026-07-24 (o `de` é a origem de uma parcelada 8/11, NÃO o início
# do ciclo — é exatamente por isso que ele não vira limite inferior).
_EMISSAO = "2026-07-25"


def _fatura(
    datas: list[str],
    *,
    emissao: str | None = _EMISSAO,
    tipo: str = "compra",
    periodo: tuple[str, str] = ("2025-11-28", "2026-07-24"),
):
    return FaturaExtraida.model_validate(
        {
            "banco": "Itau",
            "competencia": {"mes": 7, "ano": 2026},
            "periodo": {"de": periodo[0], "ate": periodo[1]},
            "emissao": emissao,
            "vencimento": "2026-08-01",
            "total_a_pagar": "100.00",
            "total_compras_periodo": "100.00",
            "total_iof_periodo": "0.00",
            "transacoes": [
                {
                    "data": data,
                    "descricao": f"Lojista {i}",
                    "valor_brl": "10.00",
                    "tipo": tipo,
                    "parcela": None,
                    "portador_final": None,
                    "internacional": None,
                }
                for i, data in enumerate(datas)
            ],
        }
    )


def _suspeitas_fatura(fatura) -> dict[int, str]:
    return datas_suspeitas_fatura(fatura, indices_materializaveis(fatura))


def test_fatura_posterior_a_emissao_flaga():
    """A EVIDÊNCIA: 2026-07-29 numa fatura emitida em 2026-07-25."""
    fatura = _fatura(["2026-07-29"])
    assert _suspeitas_fatura(fatura) == {0: "posterior_a_emissao"}


def test_fatura_limite_exato_nao_flaga():
    """`data == emissao` é LEGÍTIMO — compra no próprio dia da emissão existe.

    ALVO DA MUTAÇÃO: trocar `>` por `>=` faz este teste cair.
    """
    assert _suspeitas_fatura(_fatura([_EMISSAO])) == {}


def test_fatura_mesma_linha_na_data_certa_nao_flaga():
    """O contrafactual da evidência: as outras 3 extrações do mesmo PDF trazem
    esta compra em 2026-06-29, e a regra fica calada nelas."""
    assert _suspeitas_fatura(_fatura(["2026-06-29"])) == {}


def test_fatura_parcelamento_longo_legitimo_nao_flaga():
    """A razão de NÃO existir limite inferior — nas DUAS formas que o período assume.

    (a) CIRCULAR: o `de` extraído é a data de ORIGEM da parcelada mais antiga, e
        não o início do ciclo. É o que a Itaú real devolveu — `periodo.de`
        2025-11-28 é exatamente a data da linha da parcela 8/11. Um limite
        inferior tirado dali nasce do próprio dado que ele validaria.
    (b) CICLO: o `de` é o início do ciclo impresso (a forma bem-comportada). A
        Itaú põe na linha a data de ORIGEM da parcela, então a 6/11 comprada em
        fevereiro cai LEGITIMAMENTE antes do início do ciclo de julho — e um
        limite inferior a flagaria. É esta metade que mata a mutação; a (a) é
        cega a ela por construção, que foi como a mutação sobreviveu da 1ª vez.

    A forma (b) é montada aqui (as duas propriedades vêm de documentos reais, a
    combinação não foi capturada num dump) — é o caso que a regra tem de suportar.
    """
    circular = _fatura(
        ["2025-11-28", "2026-07-01"], periodo=("2025-11-28", "2026-07-24")
    )
    assert _suspeitas_fatura(circular) == {}

    ciclo = _fatura(["2026-02-15", "2026-07-01"], periodo=("2026-07-01", "2026-07-24"))
    assert _suspeitas_fatura(ciclo) == {}


def test_fatura_emissao_nula_nao_flaga_e_nao_levanta():
    """`emissao` é opcional no contrato (str | None). Sem âncora o check não roda,
    e isso NÃO é erro — nem para a linha que seria flagada com âncora."""
    assert _suspeitas_fatura(_fatura(["2026-07-29"], emissao=None)) == {}


def test_fatura_flaga_por_INDICE_nao_por_posicao():
    """Índice 1 é o único materializável flagado; o índice 0 (pagamento) não tem
    item nenhum. Se a função devolvesse posição no array de itens, viria 0."""
    fatura = _fatura(["2026-07-01", "2026-07-29", "2026-07-02"])
    fatura.transacoes[0].tipo = "pagamento"
    assert _suspeitas_fatura(fatura) == {1: "posterior_a_emissao"}


def test_fatura_nao_flaga_linha_nao_materializavel():
    """Pagamento com data impossível NÃO é flagado: ele não vira Transacao, então
    a data dele não deriva competência nenhuma."""
    fatura = _fatura(["2026-07-29"], tipo="pagamento")
    assert _suspeitas_fatura(fatura) == {}


# --- Extrato ------------------------------------------------------------------


def _extrato(datas: list[str], *, de: str | None = "2026-06-01", ate: str = "2026-06-30"):
    return ExtratoExtraido.model_validate(
        {
            "banco": "Nubank",
            "periodo": None if de is None else {"de": de, "ate": ate},
            "saldo_inicial": "1000.00",
            "saldo_final": "1000.00",
            "rendimento": "0.00",
            "linhas": [
                {
                    "data": data,
                    "descricao": f"Compra no debito LOJA {i}",
                    "valor": "10.00",
                    "balde": "debito",
                    "cartao_citado": None,
                }
                for i, data in enumerate(datas)
            ],
        }
    )


def test_extrato_flaga_os_DOIS_lados_do_intervalo():
    suspeitas = datas_suspeitas_extrato(
        _extrato(["2026-05-31", "2026-06-15", "2026-07-01"])
    )
    assert suspeitas == {0: "antes_do_periodo", 2: "depois_do_periodo"}


@pytest.mark.parametrize("data", ["2026-06-01", "2026-06-30"])
def test_extrato_limites_exatos_nao_flagam(data):
    """Os dois extremos do intervalo pertencem ao período."""
    assert datas_suspeitas_extrato(_extrato([data])) == {}


def test_extrato_periodo_nulo_nao_flaga_e_nao_levanta():
    """`periodo` é opcional no preview (o commit é que exige)."""
    assert datas_suspeitas_extrato(_extrato(["2020-01-01"], de=None)) == {}


def test_extrato_periodo_invertido_degrada_em_silencio():
    """Âncora incoerente não opina. Sem esta guarda, `de > ate` flagaria TODAS as
    linhas — o falso positivo mais barulhento possível. O preview não rejeita
    período invertido; só o commit o faz."""
    extrato = _extrato(["2026-06-10", "2026-06-20"], de="2026-06-30", ate="2026-06-01")
    assert datas_suspeitas_extrato(extrato) == {}


def test_extrato_flaga_todos_os_baldes():
    """Diferente da fatura, aqui não há recorte: toda linha importada vira
    lançamento com a data dela."""
    extrato = _extrato(["2026-07-05", "2026-07-06", "2026-07-07"])
    extrato.linhas[0].balde = "receita"
    extrato.linhas[1].balde = "pagamento_fatura"
    assert datas_suspeitas_extrato(extrato) == {
        0: "depois_do_periodo",
        1: "depois_do_periodo",
        2: "depois_do_periodo",
    }
