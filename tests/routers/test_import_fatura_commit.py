"""POST /import/fatura/commit — a primeira escrita do fluxo de import.

Grava transações/parcelas a partir da fatura revisada, ancorando na
competência declarada (mês de vencimento), com a parcela histórica
distribuída por competência. Idempotência pelo UNIQUE do lote (409 atômico);
tudo-ou-nada com rollback total.

SQLite in-memory isolado do conftest — NUNCA o banco do .env. Money via
Decimal(str(x)) (SQLite coage Numeric por float). Reusa a fatura Nubank do
run validado do spike (Blacktag 4/7 → âncora 07/2026: parcelas em
04..10/2026, 3 passadas + âncora + 3 futuras).
"""

import copy
import datetime as dt
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.card import Cartao
from app.models.import_fatura_lote import ImportFaturaLote
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao
from app.routers import import_fatura
from tests.fixtures.faturas_validadas import NUBANK


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


def _payload(cartao_id, fatura=NUBANK, competencias_pagas=None):
    return {
        "cartao_id": cartao_id,
        "fatura": fatura,
        "competencias_pagas": competencias_pagas or [],
    }


def _commit(client, cartao_id, **kwargs):
    return client.post("/import/fatura/commit", json=_payload(cartao_id, **kwargs))


# --- Caminho feliz + distribuição da parcela histórica -----------------------

def test_commit_feliz_recibo(as_user, users, cartoes):
    resp = _commit(as_user(users[0]), cartoes[0].id)
    assert resp.status_code == 200
    recibo = resp.json()
    # 4 avulsas (IOF Anthropic, Anthropic, Cloudflare, IOF Cloudflare) + 1 parcelada
    assert recibo["transacoes_criadas"] == 5
    assert recibo["parcelas_criadas"] == 7
    assert recibo["faturas_marcadas_pagas"] == 0
    assert recibo["estornos_importados"] == 0  # Nubank não tem compra negativa
    assert recibo["reconciliacao_bate"] is True  # primário bate (206.06)


def test_parcelada_distribuida_por_competencia(session, as_user, users, cartoes):
    _commit(as_user(users[0]), cartoes[0].id)

    tx = session.exec(
        select(Transacao).where(Transacao.parcelado == True)  # noqa: E712
    ).one()
    assert tx.total_parcelas == 7
    assert tx.fatura_mes is None and tx.fatura_ano is None  # competência vive nas parcelas
    # soma = valor mostrado × N (105.26 * 7); MUTAÇÃO no sinal/valor mata isto
    assert Decimal(str(tx.valor)) == Decimal("736.82")

    parcelas = session.exec(
        select(Parcela)
        .where(Parcela.transacao_id == tx.id)
        .order_by(Parcela.numero_parcela)
    ).all()
    assert len(parcelas) == 7
    # Âncora 07/2026 (vencimento 2026-07-13). Parcela #indice(4) na âncora;
    # 1..3 no passado (04,05,06), 5..7 no futuro (08,09,10) — tudo em 2026.
    competencias = [(p.fatura_mes, p.fatura_ano) for p in parcelas]
    assert competencias == [
        (4, 2026), (5, 2026), (6, 2026),  # passadas
        (7, 2026),                        # âncora (indice 4)
        (8, 2026), (9, 2026), (10, 2026),  # futuras
    ]
    assert all(Decimal(str(p.valor_parcela)) == Decimal("105.26") for p in parcelas)
    # data_vencimento usa o dia do cartão (13) na competência da parcela
    p_ancora = parcelas[3]
    assert p_ancora.data_vencimento.isoformat() == "2026-07-13"


def test_avulsas_caem_na_ancora(session, as_user, users, cartoes):
    _commit(as_user(users[0]), cartoes[0].id)
    avulsas = session.exec(
        select(Transacao).where(Transacao.parcelado == False)  # noqa: E712
    ).all()
    assert len(avulsas) == 4
    for a in avulsas:
        assert (a.fatura_mes, a.fatura_ano) == (7, 2026)  # âncora, não re-derivado
        assert a.tipo == "despesa"
        assert a.forma_pagamento == "Crédito"
        assert a.origem == "importacao"
        # Categoria ausente no request → o servidor recomputou a auto-categoria
        # e nenhuma camada teve o que dizer ("Blacktag", "Anthropic",
        # "Cloudflare" não casam regra nenhuma e o usuário não tem histórico).
        assert a.categoria == "Outros"


def test_pagamento_e_ajuste_nao_viram_lancamento(session, as_user, users, cartoes):
    # Nubank tem 1 pagamento (-58.95) e 2 ajuste_saldo (0.00): nenhum vira linha.
    _commit(as_user(users[0]), cartoes[0].id)
    total = session.exec(select(Transacao)).all()
    assert len(total) == 5  # 4 avulsas + 1 parcelada, nada de pagamento/ajuste


# --- Estorno materializa como tipo="estorno" (compra negativa não é dropada) --

def test_estorno_materializa_e_aparece_no_recibo(session, as_user, users, cartoes):
    fatura = copy.deepcopy(NUBANK)
    fatura["transacoes"].append({
        "data": "2026-06-20", "descricao": "Estorno de Blacktag",
        "valor_brl": "-50.00", "tipo": "compra",
        "parcela": None, "portador_final": None, "internacional": None,
    })
    # O banco declara o consumo do ciclo JÁ líquido do estorno (202.65 − 50):
    # a linha negativa abate em soma_gastos e a reconciliação segue batendo —
    # materializar o estorno não toca o cheque (ele roda sobre as linhas).
    fatura["total_compras_periodo"] = "152.65"

    resp = _commit(as_user(users[0]), cartoes[0].id, fatura=fatura)
    assert resp.status_code == 200
    recibo = resp.json()
    assert recibo["estornos_importados"] == 1
    assert recibo["transacoes_criadas"] == 6  # 5 do run Nubank + o estorno
    assert recibo["reconciliacao_bate"] is True

    estorno = session.exec(
        select(Transacao).where(Transacao.tipo == "estorno")
    ).one()
    # Valor POSITIVO (CHECK valor>0 vale) — quem subtrai são as agregações.
    assert Decimal(str(estorno.valor)) == Decimal("50.00")
    assert (estorno.fatura_mes, estorno.fatura_ano) == (7, 2026)  # âncora
    assert estorno.parcelado is False
    assert estorno.forma_pagamento == "Crédito"
    assert estorno.origem == "importacao"
    # Sem categoria no request (a tela não dá seletor ao estorno) e sem regra
    # que case a descrição → o servidor cai no neutro. Ver
    # test_estorno_recebe_categoria_recomputada para o caso em que ele acha.
    assert estorno.categoria == "Outros"


def test_estorno_abate_o_total_da_fatura_importada(session, as_user, users, cartoes):
    # Composição líquida (fonte única): a fatura da âncora soma despesas e
    # SUBTRAI o estorno. MUTAÇÃO-alvo: sem o sinal do estorno na composição,
    # o total viria 50.00 maior.
    from app.services.faturas import total_fatura_cartao

    fatura = copy.deepcopy(NUBANK)
    fatura["transacoes"].append({
        "data": "2026-06-20", "descricao": "Estorno de Blacktag",
        "valor_brl": "-50.00", "tipo": "compra",
        "parcela": None, "portador_final": None, "internacional": None,
    })
    _commit(as_user(users[0]), cartoes[0].id, fatura=fatura)

    avulsas_despesa = session.exec(
        select(Transacao).where(
            Transacao.fatura_mes == 7,
            Transacao.fatura_ano == 2026,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo == "despesa",
        )
    ).all()
    parcela_ancora = Decimal("105.26")  # parcela 4/7 na âncora
    bruto = sum((Decimal(str(t.valor)) for t in avulsas_despesa), parcela_ancora)

    total = total_fatura_cartao(session, users[0].id, cartoes[0].id, 7, 2026)
    assert Decimal(str(total)) == bruto - Decimal("50.00")


# --- Idempotência (guard atômico pelo UNIQUE do lote) ------------------------

def test_reimportar_mesma_fatura_409(session, as_user, users, cartoes):
    client = as_user(users[0])
    assert _commit(client, cartoes[0].id).status_code == 200

    antes_tx = len(session.exec(select(Transacao)).all())
    antes_lote = len(session.exec(select(ImportFaturaLote)).all())

    resp = _commit(client, cartoes[0].id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Essa fatura já foi importada."

    # MUTAÇÃO-alvo: sem o UNIQUE ou sem inserir o lote PRIMEIRO, o 2º commit
    # duplicaria os lançamentos e não daria 409 — o banco mantém a contagem do 1º.
    assert len(session.exec(select(Transacao)).all()) == antes_tx
    assert len(session.exec(select(ImportFaturaLote)).all()) == antes_lote == 1


# --- Faturas passadas marcadas pagas (revalidação server-side) ---------------

def test_marca_competencia_passada_paga(session, as_user, users, cartoes):
    resp = _commit(
        as_user(users[0]), cartoes[0].id,
        competencias_pagas=[{"mes": 6, "ano": 2026}],  # está no passado (04..06)
    )
    assert resp.status_code == 200
    assert resp.json()["faturas_marcadas_pagas"] == 1

    pag = session.exec(select(PagamentoFatura)).one()
    assert (pag.fatura_mes, pag.fatura_ano) == (6, 2026)
    assert pag.pago is True
    assert pag.data_pagamento is None  # Q3: histórico, nunca data falsa


def test_marca_paga_grava_valor_pago_do_total_materializado(
    session, as_user, users, cartoes
):
    # Cobertura (#9): o import grava valor_pago = total da fatura
    # MATERIALIZADA da competência marcada. Esperado recomputado aqui por
    # soma direta no banco (aritmética independente da função de produção).
    resp = _commit(
        as_user(users[0]), cartoes[0].id,
        competencias_pagas=[{"mes": 6, "ano": 2026}],
    )
    assert resp.status_code == 200

    parcelas = session.exec(
        select(Parcela).where(
            Parcela.cartao_id == cartoes[0].id,
            Parcela.fatura_mes == 6,
            Parcela.fatura_ano == 2026,
            Parcela.cancelado == False,  # noqa: E712
        )
    ).all()
    avulsas = session.exec(
        select(Transacao).where(
            Transacao.cartao_id == cartoes[0].id,
            Transacao.fatura_mes == 6,
            Transacao.fatura_ano == 2026,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo == "despesa",
        )
    ).all()
    esperado = sum((p.valor_parcela for p in parcelas), Decimal("0")) + sum(
        (t.valor for t in avulsas), Decimal("0")
    )
    assert esperado > 0  # a competência passada tem lançamento materializado

    pag = session.exec(select(PagamentoFatura)).one()
    assert pag.pago is True
    assert Decimal(str(pag.valor_pago)) == Decimal(str(esperado))


def test_nao_sobrescreve_pagamento_ja_confirmado(session, as_user, users, cartoes):
    """O lado INVERSO da prevalência (#9): o import de fatura roda DEPOIS do
    extrato. O valor_pago daqui é ASSUMIDO (total materializado) e a data é
    None — sobrescrever apagaria o valor e a data REAIS que o extrato gravou.
    Real vence assumido independente da ORDEM.

    MUTAÇÃO-alvo: voltar o upsert incondicional faz esta asserção falhar.
    """
    session.add(
        PagamentoFatura(
            usuario_id=users[0].id, cartao_id=cartoes[0].id,
            fatura_mes=6, fatura_ano=2026,
            pago=True, valor_pago=Decimal("200.00"),  # valor REAL do extrato
            data_pagamento=dt.date(2026, 6, 10),
        )
    )
    session.commit()

    resp = _commit(
        as_user(users[0]), cartoes[0].id,
        competencias_pagas=[{"mes": 6, "ano": 2026}],
    )
    assert resp.status_code == 200
    assert resp.json()["faturas_marcadas_pagas"] == 0
    assert resp.json()["faturas_ja_confirmadas"] == 1

    pag = session.exec(select(PagamentoFatura)).one()
    assert Decimal(str(pag.valor_pago)) == Decimal("200.00")  # intocado
    assert pag.data_pagamento == dt.date(2026, 6, 10)


def test_competencia_paga_fora_do_historico_rejeita_e_desfaz(
    session, as_user, users, cartoes
):
    resp = _commit(
        as_user(users[0]), cartoes[0].id,
        competencias_pagas=[{"mes": 1, "ano": 2020}],  # não faz parte da importação
    )
    assert resp.status_code == 422
    assert "não faz parte" in resp.json()["detail"]
    # atômico: o 422 desfaz o lote e os lançamentos já materializados
    assert session.exec(select(Transacao)).all() == []
    assert session.exec(select(ImportFaturaLote)).all() == []


def test_competencia_futura_nao_e_marcavel(as_user, users, cartoes):
    # 08/2026 é futura (parcela 5) — só passadas são marcáveis.
    resp = _commit(
        as_user(users[0]), cartoes[0].id,
        competencias_pagas=[{"mes": 8, "ano": 2026}],
    )
    assert resp.status_code == 422


# --- Atomicidade (falha forçada no meio) -------------------------------------

def test_falha_no_meio_rollback_total(session, as_user, users, cartoes, monkeypatch):
    def _explode(*args, **kwargs):
        raise RuntimeError("falha simulada no meio da materialização")

    monkeypatch.setattr(import_fatura, "materializar_fatura", _explode)

    with pytest.raises(RuntimeError):
        _commit(as_user(users[0]), cartoes[0].id)

    # o lote foi flushado ANTES da falha; o rollback do endpoint o desfaz junto
    assert session.exec(select(Transacao)).all() == []
    assert session.exec(select(Parcela)).all() == []
    assert session.exec(select(ImportFaturaLote)).all() == []


# --- Isolamento entre usuários (anti-enumeração) -----------------------------

def test_cartao_de_outro_usuario_404(session, as_user, users, cartoes):
    resp = _commit(as_user(users[0]), cartoes[1].id)  # cartão do user_b
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Cartão não encontrado"
    # nada foi gravado (o 404 precede qualquer escrita)
    assert session.exec(select(ImportFaturaLote)).all() == []


def test_cartao_inexistente_404(as_user, users, cartoes):
    resp = _commit(as_user(users[0]), 99999)
    assert resp.status_code == 404
