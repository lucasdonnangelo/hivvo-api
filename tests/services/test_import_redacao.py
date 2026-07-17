"""Redação de PII da importação: CPF e finais são as garantias reais; nome é
best-effort declarado (frágil por design — ver docstring de redacao.py)."""

from app.schemas.import_fatura import FaturaExtraida
from app.services.import_fatura.redacao import redigir, restaurar_finais


def test_cpf_formatado_e_corrido_sao_redigidos():
    texto = "Titular CPF 123.456.789-01 | doc 98765432109 | tel 1234567890"
    redigido, _ = redigir(texto, [])
    assert "123.456.789-01" not in redigido
    assert "98765432109" not in redigido
    assert redigido.count("[CPF]") == 2
    assert "1234567890" in redigido  # 10 dígitos não é CPF — intocado


def test_nome_redigido_best_effort_case_insensitive():
    redigido, _ = redigir("Fatura de FULANO DA SILVA", ["Fulano da Silva"])
    assert "FULANO" not in redigido
    assert "[TITULAR]" in redigido


def test_finais_pseudonimizados_por_contexto_sem_pegar_anos_nem_valores():
    texto = (
        "Cartao final 6042 | ano 2026 | valor 6.042,00 | "
        "protocolo 16042 | cartao **** 9493"
    )
    redigido, mapa = redigir(texto, [])

    # pseudonimização com mapa reversível, na ordem de aparição
    assert mapa == {"0001": "6042", "0002": "9493"}
    assert "final 0001" in redigido
    assert "**** 0002" in redigido

    # ano, valor e número maior que CONTÉM o final ficam intactos — o
    # boundary exige não-dígito dos dois lados (16042 não pode virar 10001)
    assert "2026" in redigido
    assert "6.042,00" in redigido
    assert "16042" in redigido


def test_restaurar_finais_em_portador_e_descricao():
    fatura = FaturaExtraida.model_validate(
        {
            "banco": "Sintético",
            "competencia": {"mes": 7, "ano": 2026},
            "total_a_pagar": "10.00",
            "total_compras_periodo": "10.00",
            "total_iof_periodo": "0.00",
            "transacoes": [
                {
                    "data": "2026-07-01",
                    "descricao": "Compra no cartao final 0001",
                    "valor_brl": "10.00",
                    "tipo": "compra",
                    "portador_final": "0001",
                }
            ],
        }
    )
    restaurar_finais(fatura, {"0001": "6042"})
    assert fatura.transacoes[0].portador_final == "6042"
    assert fatura.transacoes[0].descricao == "Compra no cartao final 6042"
