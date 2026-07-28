"""POST /import/extrato/commit — a primeira escrita do fluxo de EXTRATO.

Materializa os três baldes do extrato revisado (receita e débito viram
Transacao; pagamento de fatura vira PagamentoFatura com valor e data REAIS) mais
o rendimento do resumo, numa transação única. Idempotência pelo UNIQUE do lote
(409 atômico); tudo-ou-nada com rollback total.

SQLite in-memory isolado do conftest — NUNCA o banco do .env. Money via
Decimal(str(x)) (SQLite coage Numeric por float). Extrato SINTÉTICO
(tests/fixtures/extratos_validados.EXTRATO_COMMIT): o out/ do spike de extrato é
gitignored por PII de contraparte.
"""

import copy
import datetime as dt
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.card import Cartao
from app.models.import_extrato_lote import ImportExtratoLote
from app.models.pagamento_fatura import PagamentoFatura
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao
from app.routers import import_extrato
from tests.fixtures.extratos_validados import EXTRATO_COMMIT

# Competência que os testes usam como fatura quitada pelo extrato.
FATURA_MES, FATURA_ANO = 6, 2026
TOTAL_FATURA = Decimal("350.00")  # > 200,00 pago: cobertura parcial de propósito


@pytest.fixture()
def cartoes(session, users):
    user_a, user_b = users
    cartao_a = Cartao(
        usuario_id=user_a.id, nome="Nubank", tipo="Crédito",
        dia_vencimento=13, dia_fechamento=6, mes_offset_vencimento=1,
    )
    cartao_b = Cartao(usuario_id=user_b.id, nome="Itaú", tipo="Crédito")
    session.add(cartao_a)
    session.add(cartao_b)
    session.commit()
    session.refresh(cartao_a)
    session.refresh(cartao_b)
    return cartao_a, cartao_b


@pytest.fixture()
def fatura_junho(session, users, cartoes):
    """Fatura 06/2026 do cartão A com total 350,00 — o que o extrato quita.

    Uma avulsa de cartão faturada na competência: a MESMA composição que
    services/faturas usa (fatura_existe/total_fatura_cartao).
    """
    session.add(
        Transacao(
            usuario_id=users[0].id, tipo="despesa", data=dt.date(2026, 5, 20),
            descricao="Compra no crédito", valor=TOTAL_FATURA, categoria="Outros",
            forma_pagamento="Crédito", cartao_id=cartoes[0].id,
            fatura_mes=FATURA_MES, fatura_ano=FATURA_ANO,
        )
    )
    session.commit()


def _payload(cartao_id=None, *, extrato=EXTRATO_COMMIT, decisoes=None,
             importar_rendimento=True, categorias=None):
    """Extrato REVISADO + decisões, como a tela de revisão mandaria.

    `decisoes`/`categorias` são {indice_da_linha: valor}; `cartao_id` confirma o
    casamento do pagamento com (cartão, 06/2026). `importar` fica AUSENTE onde o
    teste não decide — é o tri-estado que deixa o default seguro no servidor.
    """
    ex = copy.deepcopy(extrato)
    for i, linha in enumerate(ex["linhas"]):
        if linha["balde"] == "pagamento_fatura" and cartao_id is not None:
            linha.update(
                {"cartao_id": cartao_id, "fatura_mes": FATURA_MES, "fatura_ano": FATURA_ANO}
            )
        if decisoes and i in decisoes:
            linha["importar"] = decisoes[i]
        if categorias and i in categorias:
            linha["categoria"] = categorias[i]
    return {"extrato": ex, "importar_rendimento": importar_rendimento}


def _commit(client, cartao_id=None, **kwargs):
    return client.post("/import/extrato/commit", json=_payload(cartao_id, **kwargs))


def _importadas(session):
    """Só o que o COMMIT criou — a compra da fixture `fatura_junho` é manual."""
    return session.exec(
        select(Transacao).where(Transacao.origem == "importacao")
    ).all()


def _recorrencia_salario(session, uid, valor="5000.00", dia=5):
    rec = Recorrencia(
        usuario_id=uid, tipo="receita", categoria="Salário",
        forma_pagamento="Pix", dia_do_mes=dia, descricao="Salário ACME",
    )
    session.add(rec)
    session.flush()
    session.add(
        RecorrenciaVigencia(
            recorrencia_id=rec.id, valor=Decimal(valor), mes_inicio=1, ano_inicio=2026
        )
    )
    session.commit()


# --- Caminho feliz: os três baldes + o rendimento ----------------------------

def test_commit_feliz_recibo(as_user, users, cartoes, fatura_junho):
    resp = _commit(as_user(users[0]), cartoes[0].id)
    assert resp.status_code == 200
    recibo = resp.json()
    assert recibo["receitas_criadas"] == 2
    assert recibo["debitos_criados"] == 2
    assert recibo["pagamentos_registrados"] == 1
    assert recibo["pagamentos_sobrescritos"] == 0
    assert recibo["rendimento_importado"] is True
    assert recibo["linhas_ignoradas"] == 0
    assert recibo["receitas_puladas_recorrencia"] == 0
    # walk: 1000 + 4,56 + 5777 − 80 − 200 = 6501,56 == saldo_final declarado
    assert recibo["reconciliacao_bate"] is True


def test_receita_materializa_como_transacao(session, as_user, users, cartoes, fatura_junho):
    _commit(as_user(users[0]), cartoes[0].id)
    receita = session.exec(
        select(Transacao).where(Transacao.descricao == "Salario ACME LTDA")
    ).one()
    assert receita.tipo == "receita"
    assert Decimal(str(receita.valor)) == Decimal("5000.00")
    assert receita.data == dt.date(2026, 6, 5)
    assert receita.categoria == "Outros"  # default do request, revalidado
    assert receita.origem == "importacao"
    assert receita.parcelado is False
    assert receita.cartao_id is None


def test_debito_materializa_como_despesa_de_caixa(
    session, as_user, users, cartoes, fatura_junho
):
    _commit(as_user(users[0]), cartoes[0].id)
    debitos = session.exec(
        select(Transacao).where(
            Transacao.tipo == "despesa", Transacao.origem == "importacao"
        )
    ).all()
    assert len(debitos) == 2
    assert sum((Decimal(str(d.valor)) for d in debitos), Decimal("0")) == Decimal("80.00")
    for d in debitos:
        assert d.forma_pagamento == "Débito"
        # O CORAÇÃO do balde 2: "já saiu". Sem cartão e sem competência de
        # fatura — não é crédito, o dinheiro saiu na data.
        assert d.cartao_id is None
        assert d.fatura_mes is None and d.fatura_ano is None


def test_pagamento_fatura_nao_vira_lancamento(session, as_user, users, cartoes, fatura_junho):
    # A linha de 200,00 é quitação, não consumo: não pode existir Transacao dela
    # (senão o extrato contaria em dobro o que a fatura já capturou).
    _commit(as_user(users[0]), cartoes[0].id)
    assert (
        session.exec(
            select(Transacao).where(Transacao.descricao == "Pagamento de fatura Nubank")
        ).all()
        == []
    )


def test_rendimento_vira_receita_rendimentos(session, as_user, users, cartoes, fatura_junho):
    _commit(as_user(users[0]), cartoes[0].id)
    rendimento = session.exec(
        select(Transacao).where(Transacao.categoria == "Rendimentos")
    ).one()
    assert rendimento.tipo == "receita"
    assert Decimal(str(rendimento.valor)) == Decimal("4.56")
    assert rendimento.data == dt.date(2026, 6, 30)  # fim do período, não uma linha


def test_rendimento_zero_nao_materializa(session, as_user, users, cartoes, fatura_junho):
    extrato = copy.deepcopy(EXTRATO_COMMIT)
    extrato["rendimento"] = "0.00"
    resp = _commit(as_user(users[0]), cartoes[0].id, extrato=extrato)
    assert resp.json()["rendimento_importado"] is False
    assert session.exec(
        select(Transacao).where(Transacao.categoria == "Rendimentos")
    ).all() == []


def test_rendimento_pode_ser_recusado_na_revisao(session, as_user, users, cartoes, fatura_junho):
    resp = _commit(as_user(users[0]), cartoes[0].id, importar_rendimento=False)
    assert resp.json()["rendimento_importado"] is False
    assert session.exec(
        select(Transacao).where(Transacao.categoria == "Rendimentos")
    ).all() == []


# --- Balde 2 é CAIXA QUE JÁ SAIU, não dívida ---------------------------------

def test_debito_nao_entra_no_a_pagar(session, as_user, users, mocker):
    """A asserção que PROVA o balde 2: consumo realizado, nunca "a pagar".

    Extrato só de débitos → o mês fecha com as despesas somadas, TUDO realizado
    e `a_pagar` ZERO. MUTAÇÃO-alvo: derivar fatura_mes/fatura_ano no débito
    (como faz a avulsa de CRÉDITO) o tiraria da Fonte 3 e o jogaria na Fonte 2 —
    lá, com o vencimento da competência ainda à frente, ele viraria dívida a
    pagar e sairia do realizado: o oposto do balde.

    Por isso o relógio fica DENTRO da competência (20/06, antes do vencimento
    de 30/06): depois do vencimento a Fonte 2 também daria a_pagar=0 e a
    mutação passaria despercebida.
    """
    mocker.patch("app.services.estatisticas.hoje", return_value=dt.date(2026, 6, 20))
    extrato = copy.deepcopy(EXTRATO_COMMIT)
    extrato["linhas"] = [l for l in extrato["linhas"] if l["balde"] == "debito"]
    extrato["rendimento"] = "0.00"

    assert _commit(as_user(users[0]), extrato=extrato).status_code == 200

    body = as_user(users[0]).get(
        "/statistics/monthly", params={"mes": 6, "ano": 2026}
    ).json()
    assert Decimal(str(body["despesas"])) == Decimal("80.00")
    assert Decimal(str(body["a_pagar"])) == Decimal("0.00")
    # À vista já ocorreu por definição (§1.3.2) — nada fica "a vir".
    assert Decimal(str(body["realizado"]["despesas"])) == Decimal("80.00")


# --- Pagamento de fatura: valor e data REAIS (sinergia #9) -------------------

def test_pagamento_grava_valor_e_data_reais(session, as_user, users, cartoes, fatura_junho):
    _commit(as_user(users[0]), cartoes[0].id)
    pag = session.exec(select(PagamentoFatura)).one()
    assert (pag.cartao_id, pag.fatura_mes, pag.fatura_ano) == (
        cartoes[0].id, FATURA_MES, FATURA_ANO,
    )
    assert pag.pago is True
    # O valor REAL do extrato — NÃO o total da fatura (350,00).
    assert Decimal(str(pag.valor_pago)) == Decimal("200.00")
    # A data REAL do extrato — nem None (import de fatura) nem hoje() (PUT).
    assert pag.data_pagamento == dt.date(2026, 6, 10)


def test_cobertura_parcial_reflete_no_status_da_fatura(
    as_user, users, cartoes, fatura_junho
):
    # Ponta a ponta do #9: pago 200 de 350 → `paga_parcial`, e a diferença volta
    # ao "A pagar" pela descoberta. Se o commit gravasse o total assumido, o
    # status seria `paga` e a descoberta sumiria.
    client = as_user(users[0])
    _commit(client, cartoes[0].id)
    detalhe = client.get(f"/cards/{cartoes[0].id}/invoices/{FATURA_ANO}/{FATURA_MES}").json()
    assert detalhe["status"] == "paga_parcial"


def test_valor_real_do_extrato_prevalece_sobre_o_assumido(
    session, as_user, users, cartoes, fatura_junho
):
    """Fatura já paga pelo import de FATURA (valor ASSUMIDO = total) → o extrato
    manda. MUTAÇÃO-alvo: trocar o valor da linha por total_fatura_cartao mata
    esta asserção."""
    session.add(
        PagamentoFatura(
            usuario_id=users[0].id, cartao_id=cartoes[0].id,
            fatura_mes=FATURA_MES, fatura_ano=FATURA_ANO,
            pago=True, valor_pago=TOTAL_FATURA, data_pagamento=None,  # o que o import grava
        )
    )
    session.commit()

    resp = _commit(as_user(users[0]), cartoes[0].id)
    assert resp.status_code == 200
    assert resp.json()["pagamentos_sobrescritos"] == 1

    pag = session.exec(select(PagamentoFatura)).one()  # continua UM registro
    assert Decimal(str(pag.valor_pago)) == Decimal("200.00")
    assert pag.data_pagamento == dt.date(2026, 6, 10)


def test_duas_linhas_para_a_mesma_fatura_somam(
    session, as_user, users, cartoes, fatura_junho
):
    # Pagar a fatura em duas transferências é real: soma num único
    # PagamentoFatura, com a data da ÚLTIMA (só aí a fatura foi quitada).
    extrato = copy.deepcopy(EXTRATO_COMMIT)
    extrato["linhas"].append(
        {
            "data": "2026-06-12", "descricao": "Pagamento de fatura Nubank",
            "valor": "150.00", "balde": "pagamento_fatura", "cartao_citado": "Nubank",
        }
    )
    resp = _commit(as_user(users[0]), cartoes[0].id, extrato=extrato)
    assert resp.status_code == 200
    assert resp.json()["pagamentos_registrados"] == 1

    pag = session.exec(select(PagamentoFatura)).one()
    assert Decimal(str(pag.valor_pago)) == Decimal("350.00")
    assert pag.data_pagamento == dt.date(2026, 6, 12)


def test_pagamento_de_fatura_inexistente_422_e_desfaz(session, as_user, users, cartoes):
    # SEM a fixture fatura_junho: competência sem lançamento. PagamentoFatura ali
    # seria fantasma (status_fatura devolve "vazia" e o pagamento some da UI).
    resp = _commit(as_user(users[0]), cartoes[0].id)
    assert resp.status_code == 422
    assert "importe a fatura" in resp.json()["detail"]
    # atômico: o 422 desfaz o lote e os lançamentos já materializados
    assert session.exec(select(Transacao)).all() == []
    assert session.exec(select(ImportExtratoLote)).all() == []


def test_pagamento_sem_confirmacao_de_fatura_422(as_user, users, cartoes, fatura_junho):
    # A linha de pagamento sem cartão/competência confirmados (o front não
    # decidiu) é rejeitada na validação do schema — o commit nunca adivinha.
    resp = as_user(users[0]).post("/import/extrato/commit", json=_payload(None))
    assert resp.status_code == 422


# --- Receita × recorrência: o default seguro mora no servidor ----------------

def test_receita_indecisa_que_casa_recorrencia_nao_e_criada(
    session, as_user, users, cartoes, fatura_junho
):
    """A armadilha do salário: a recorrência já conta os 5000 como realizados —
    importar de novo duplicaria. `importar` AUSENTE → o servidor recomputa o
    casamento e deixa de fora."""
    _recorrencia_salario(session, users[0].id)

    resp = _commit(as_user(users[0]), cartoes[0].id)
    recibo = resp.json()
    assert recibo["receitas_criadas"] == 1  # só o Pix de 777,00
    assert recibo["receitas_puladas_recorrencia"] == 1
    assert recibo["linhas_ignoradas"] == 1

    assert session.exec(
        select(Transacao).where(Transacao.descricao == "Salario ACME LTDA")
    ).all() == []


def test_usuario_pode_sobrepor_e_importar_a_receita_recorrente(
    session, as_user, users, cartoes, fatura_junho
):
    # O explícito vence o default: `importar: true` na linha do salário.
    _recorrencia_salario(session, users[0].id)
    resp = _commit(as_user(users[0]), cartoes[0].id, decisoes={0: True})
    assert resp.json()["receitas_criadas"] == 2
    assert resp.json()["receitas_puladas_recorrencia"] == 0
    assert session.exec(
        select(Transacao).where(Transacao.descricao == "Salario ACME LTDA")
    ).one()


def test_linha_recusada_na_revisao_nao_e_criada(session, as_user, users, cartoes, fatura_junho):
    resp = _commit(as_user(users[0]), cartoes[0].id, decisoes={1: False})
    assert resp.json()["debitos_criados"] == 1
    assert resp.json()["linhas_ignoradas"] == 1
    assert resp.json()["receitas_puladas_recorrencia"] == 0  # recusa do usuário, não default
    assert session.exec(
        select(Transacao).where(Transacao.descricao == "Compra no debito PADARIA CENTRAL")
    ).all() == []


# --- Re-validação server-side ------------------------------------------------

def test_categoria_desconhecida_cai_em_outros(session, as_user, users, cartoes, fatura_junho):
    # O front pode ter mandado categoria adulterada/apagada: o guarda-corpo é o
    # mesmo do preview (casar_categoria contra a lista DO USUÁRIO).
    _commit(as_user(users[0]), cartoes[0].id, categorias={1: "Categoria Inventada"})
    debito = session.exec(
        select(Transacao).where(
            Transacao.descricao == "Compra no debito PADARIA CENTRAL"
        )
    ).one()
    assert debito.categoria == "Outros"


def test_categoria_valida_do_usuario_e_preservada(
    session, as_user, users, cartoes, fatura_junho
):
    _commit(as_user(users[0]), cartoes[0].id, categorias={1: "Alimentação"})
    debito = session.exec(
        select(Transacao).where(
            Transacao.descricao == "Compra no debito PADARIA CENTRAL"
        )
    ).one()
    assert debito.categoria == "Alimentação"


def test_periodo_ausente_422(session, as_user, users, cartoes, fatura_junho):
    extrato = copy.deepcopy(EXTRATO_COMMIT)
    extrato["periodo"] = None
    resp = _commit(as_user(users[0]), cartoes[0].id, extrato=extrato)
    assert resp.status_code == 422
    assert "período" in resp.json()["detail"]
    assert session.exec(select(ImportExtratoLote)).all() == []


def test_periodo_invertido_422(session, as_user, users, cartoes, fatura_junho):
    # Barrado ANTES do flush do lote: o CHECK de ordem levantaria IntegrityError
    # no mesmo flush do UNIQUE e viraria um 409 mentiroso ("já importado").
    extrato = copy.deepcopy(EXTRATO_COMMIT)
    extrato["periodo"] = {"de": "2026-06-30", "ate": "2026-06-01"}
    resp = _commit(as_user(users[0]), cartoes[0].id, extrato=extrato)
    assert resp.status_code == 422
    assert "Período inválido" in resp.json()["detail"]
    assert session.exec(select(ImportExtratoLote)).all() == []


# --- Idempotência (guard atômico pelo UNIQUE do lote) ------------------------

def test_reimportar_mesmo_extrato_409(session, as_user, users, cartoes, fatura_junho):
    client = as_user(users[0])
    assert _commit(client, cartoes[0].id).status_code == 200

    antes_tx = len(session.exec(select(Transacao)).all())
    antes_pag = len(session.exec(select(PagamentoFatura)).all())

    resp = _commit(client, cartoes[0].id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Esse extrato já foi importado."

    # MUTAÇÃO-alvo: sem o UNIQUE ou sem inserir o lote PRIMEIRO, o 2º commit
    # duplicaria os lançamentos e não daria 409 — o banco mantém a contagem do 1º.
    assert len(session.exec(select(Transacao)).all()) == antes_tx
    assert len(session.exec(select(PagamentoFatura)).all()) == antes_pag
    assert len(session.exec(select(ImportExtratoLote)).all()) == 1


def test_nome_do_banco_normalizado_no_guard(as_user, users, cartoes, fatura_junho):
    # O nome do banco vem de texto livre do LLM: caixa/espaço não podem furar o
    # guard do mesmo extrato.
    client = as_user(users[0])
    assert _commit(client, cartoes[0].id).status_code == 200

    extrato = copy.deepcopy(EXTRATO_COMMIT)
    extrato["banco"] = "  NUBANK "
    assert _commit(client, cartoes[0].id, extrato=extrato).status_code == 409


def test_periodo_diferente_do_mesmo_banco_importa(as_user, users, cartoes, fatura_junho):
    client = as_user(users[0])
    assert _commit(client, cartoes[0].id).status_code == 200

    extrato = copy.deepcopy(EXTRATO_COMMIT)
    extrato["periodo"] = {"de": "2026-07-01", "ate": "2026-07-31"}
    assert _commit(client, cartoes[0].id, extrato=extrato).status_code == 200


# --- Atomicidade (falha forçada no meio) -------------------------------------

def test_falha_no_meio_rollback_total(session, as_user, users, cartoes, fatura_junho, monkeypatch):
    def _explode(*args, **kwargs):
        raise RuntimeError("falha simulada no meio da materialização")

    monkeypatch.setattr(import_extrato, "materializar_extrato", _explode)

    with pytest.raises(RuntimeError):
        _commit(as_user(users[0]), cartoes[0].id)

    # o lote foi flushado ANTES da falha; o rollback do endpoint o desfaz junto
    # (a compra da fixture `fatura_junho` é pré-existente: origem="manual").
    assert _importadas(session) == []
    assert session.exec(select(PagamentoFatura)).all() == []
    assert session.exec(select(ImportExtratoLote)).all() == []


# --- Isolamento entre usuários (anti-enumeração) -----------------------------

def test_cartao_de_outro_usuario_404_e_desfaz(session, as_user, users, cartoes, fatura_junho):
    resp = _commit(as_user(users[0]), cartoes[1].id)  # cartão do user_b
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Cartão não encontrado"
    # o 404 acontece DEPOIS da materialização das receitas/débitos — o rollback
    # tem de desfazer tudo, inclusive o lote.
    assert _importadas(session) == []
    assert session.exec(select(ImportExtratoLote)).all() == []


def test_cartao_inexistente_404(as_user, users, cartoes, fatura_junho):
    assert _commit(as_user(users[0]), 99999).status_code == 404


def test_mesmo_extrato_de_outro_usuario_importa(session, as_user, users, cartoes):
    # O UNIQUE do lote inclui usuario_id: o extrato de A não bloqueia o de B, e
    # nada de A vaza para B.
    session.add(
        Transacao(
            usuario_id=users[1].id, tipo="despesa", data=dt.date(2026, 5, 20),
            descricao="Compra no crédito", valor=TOTAL_FATURA, categoria="Outros",
            forma_pagamento="Crédito", cartao_id=cartoes[1].id,
            fatura_mes=FATURA_MES, fatura_ano=FATURA_ANO,
        )
    )
    session.commit()

    assert _commit(as_user(users[0]), extrato={**EXTRATO_COMMIT,
                   "linhas": [l for l in EXTRATO_COMMIT["linhas"] if l["balde"] != "pagamento_fatura"]}
                   ).status_code == 200
    assert _commit(as_user(users[1]), cartoes[1].id).status_code == 200

    lotes = session.exec(select(ImportExtratoLote)).all()
    assert {l.usuario_id for l in lotes} == {users[0].id, users[1].id}
    pag = session.exec(select(PagamentoFatura)).one()
    assert pag.usuario_id == users[1].id
