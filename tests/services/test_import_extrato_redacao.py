"""Redação do extrato (ACHADO 2): CPF (titular e contraparte), agência e conta
são as garantias reais; nome do titular é best-effort; nome de contraparte é
resíduo documentado (não coberto)."""

from app.services.import_extrato.redacao import redigir


def test_cpf_titular_e_de_contraparte_sao_redigidos():
    texto = (
        "Titular CPF 123.456.789-01 | "
        "Pix enviado para doc 98765432109 | tel 1234567890"
    )
    redigido = redigir(texto, [])
    assert "123.456.789-01" not in redigido
    assert "98765432109" not in redigido
    assert redigido.count("[CPF]") == 2
    assert "1234567890" in redigido  # 10 dígitos não é CPF — intocado


def test_agencia_e_conta_redigidas_por_contexto():
    texto = "Ag: 0234-5 Conta corrente 000123456-7 destino do Pix"
    redigido = redigir(texto, [])
    assert "0234-5" not in redigido
    assert "000123456-7" not in redigido
    assert "[AGENCIA]" in redigido
    assert "[CONTA]" in redigido


def test_agencia_conta_nao_comem_valores_nem_datas():
    # números que NÃO são precedidos pelo rótulo ag/conta ficam intactos
    texto = "05 JUN Compra 1.234,56 em 2026 protocolo 55555"
    redigido = redigir(texto, [])
    assert "1.234,56" in redigido
    assert "2026" in redigido
    assert "55555" in redigido
    assert "[AGENCIA]" not in redigido
    assert "[CONTA]" not in redigido


def test_conta_com_palavras_entre_rotulo_e_numero_nao_casa():
    # "conta de luz 50,00" NÃO é conta bancária: há letras entre "conta" e o nº
    texto = "Pagamento de conta de luz 50,00"
    redigido = redigir(texto, [])
    assert "[CONTA]" not in redigido
    assert "50,00" in redigido


def test_nome_titular_redigido_best_effort_case_insensitive():
    redigido = redigir("Extrato de FULANO DA SILVA", ["Fulano da Silva"])
    assert "FULANO" not in redigido
    assert "[TITULAR]" in redigido


def test_nome_de_contraparte_e_residuo_documentado_nao_e_redigido():
    # Resíduo conhecido (docstring de redacao.py): sem a string do terceiro, o
    # nome de contraparte em Pix/TED NÃO é redigido. Este teste CRISTALIZA esse
    # limite — se um dia cobrirmos, ele muda de propósito conscientemente.
    redigido = redigir("Pix enviado - BELTRANO DE SOUZA", ["Fulano da Silva"])
    assert "BELTRANO DE SOUZA" in redigido
