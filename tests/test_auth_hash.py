"""F-23 — custo bcrypt explícito (rounds=12) sem quebrar hashes antigos."""

import bcrypt

from app.core.auth import hash_password, verify_password


def test_hash_novo_usa_rounds_12():
    h = hash_password("senha-forte-123")
    # Formato bcrypt: $2b$<cost>$... — o custo é o terceiro campo
    assert h.split("$")[2] == "12"


def test_verify_valida_o_proprio_hash_novo():
    h = hash_password("senha-forte-123")
    assert verify_password("senha-forte-123", h) is True
    assert verify_password("senha-errada", h) is False


def test_login_de_hash_pre_existente_de_custo_diferente_continua_validando():
    # Simula uma senha hasheada antes do F-23, com custo menor (10).
    # verify lê o custo do próprio hash — deve validar normalmente.
    hash_antigo = bcrypt.hashpw(b"senha-antiga", bcrypt.gensalt(rounds=10)).decode()
    assert hash_antigo.split("$")[2] == "10"
    assert verify_password("senha-antiga", hash_antigo) is True
