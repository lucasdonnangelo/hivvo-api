"""POST /auth/reset-data — "começar do zero" (PLANO_PERFIL_CONFIG).

Zera os LANÇAMENTOS preservando a conta: usuario_id, categorias customizadas e
tokens (o usuário continua logado). Usa a purga compartilhada com o delete_me —
os testes aqui cobrem o lado "preserva"; test_account_deletion cobre o lado
"apaga tudo".

O teste da ORDEM (cartão com compras) roda numa fixture com PRAGMA foreign_keys
ON: sem ela o SQLite não checa FK e o teste passaria com QUALQUER ordem — foi
esse ponto cego que deixou o furo do delete_me sobreviver.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 — registra TODOS os models em SQLModel.metadata
from app.core.auth import get_current_user, hash_password
from app.core.database import get_session
from app.models.card import Cartao
from app.models.category import CategoriaCustomizada
from app.models.chat import ChatMessage
from app.models.import_extrato_lote import ImportExtratoLote
from app.models.import_fatura_lote import ImportFaturaLote
from app.models.installment import Parcela
from app.models.notificacao_envio import NotificacaoEnvio
from app.models.pagamento_fatura import PagamentoFatura
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.refresh_token import RefreshToken
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.routers.auth import _purgar_dados_do_usuario
from main import app

SENHA = "senha-correta-1"


def _popular(session) -> Usuario:
    """Usuário com 1 linha em cada tabela que a purga apaga + as que preserva."""
    user = Usuario(
        email="reset@hivvo.test",
        username="reset_me",
        senha_hash=hash_password(SENHA),
        nome_completo="Para Zerar",
    )
    session.add(user)
    session.flush()

    cartao = Cartao(usuario_id=user.id, nome="Nubank", tipo="Crédito")
    session.add(cartao)
    session.flush()

    # Compra NO CARTÃO: é o caso que a FK NO ACTION (transacoes.cartao_id,
    # parcelas.cartao_id) bloqueia se a ordem da purga estiver errada.
    transacao = Transacao(
        usuario_id=user.id,
        tipo="despesa",
        data=dt.date(2026, 6, 1),
        descricao="Compra parcelada",
        valor=Decimal("300.00"),
        categoria="Outros",
        cartao_id=cartao.id,
    )
    session.add(transacao)
    session.flush()

    session.add(
        Parcela(
            usuario_id=user.id,
            transacao_id=transacao.id,
            numero_parcela=1,
            total_parcelas=3,
            valor_parcela=Decimal("100.00"),
            data_vencimento=dt.date(2026, 7, 10),
            descricao="Compra parcelada (1/3)",
            categoria="Outros",
            cartao_id=cartao.id,
            fatura_mes=7,
            fatura_ano=2026,
        )
    )
    session.add(
        PagamentoFatura(
            usuario_id=user.id,
            cartao_id=cartao.id,
            fatura_mes=7,
            fatura_ano=2026,
            pago=True,
            valor_pago=Decimal("100.00"),
        )
    )

    recorrencia = Recorrencia(
        usuario_id=user.id,
        tipo="despesa",
        categoria="Moradia",
        forma_pagamento="Pix",
        dia_do_mes=10,
        descricao="Aluguel",
    )
    session.add(recorrencia)
    session.flush()
    session.add(
        RecorrenciaVigencia(
            recorrencia_id=recorrencia.id,
            valor=Decimal("2500.00"),
            mes_inicio=1,
            ano_inicio=2026,
        )
    )

    # Guards de idempotência da importação: sem sair na purga, o usuário zera os
    # dados e nunca mais consegue reimportar os mesmos PDFs (409 eterno). O de
    # EXTRATO é o caso que NENHUM cascade cobre no reset — só depende de
    # `usuarios`, que o reset preserva por definição.
    session.add(
        ImportFaturaLote(
            usuario_id=user.id, cartao_id=cartao.id, fatura_mes=7, fatura_ano=2026
        )
    )
    session.add(
        ImportExtratoLote(
            usuario_id=user.id, banco="nubank",
            periodo_de=dt.date(2026, 6, 1), periodo_ate=dt.date(2026, 6, 30),
        )
    )

    # Guard do aviso de vencimento (#6): mesmo caso do lote de EXTRATO — só
    # aponta para `usuarios`, então nenhum cascade o cobre no reset. De pé, ele
    # faz o aviso do dia ser pulado EM SILÊNCIO (não é erro, é o e-mail que não
    # sai).
    session.add(
        NotificacaoEnvio(
            usuario_id=user.id,
            data_referencia=dt.date(2026, 7, 1),
            tipo="vencimento_fatura",
        )
    )

    session.add(ChatMessage(usuario_id=user.id, sessao_id=uuid.uuid4(), role="user", text="oi"))

    # PRESERVADOS pelo reset.
    session.add(CategoriaCustomizada(usuario_id=user.id, nome="Pets"))
    session.add(
        RefreshToken(
            usuario_id=user.id,
            token="refresh-hash-abc",
            expires_at=dt.datetime.utcnow() + dt.timedelta(days=7),
        )
    )

    session.commit()
    session.refresh(user)
    return user


def _authed(session, user):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, base_url="http://testserver/api/v1")


@pytest.fixture()
def authed_client(session):
    user = _popular(session)
    client = _authed(session, user)
    yield client, user
    app.dependency_overrides.clear()


@pytest.fixture()
def session_fk():
    """Sessão SQLite com FK REALMENTE checada (PRAGMA foreign_keys=ON).

    O conftest global não liga o PRAGMA — e no SQLite a checagem vem desligada
    por padrão. Sem isto, um teste de "a ordem não bate na FK" passaria com a
    ordem errada, provando nada.

    Detalhe que torna esta fixture MAIS rigorosa que a produção: os models não
    declaram `ondelete` (o CASCADE só existe nas migrations), então aqui TODAS as
    FKs são NO ACTION. Se a purga dependesse de cascade em vez de deletes
    explícitos na ordem certa, quebraria aqui.

    Local a este arquivo de propósito: ligar o PRAGMA global mexeria nos 474
    testes existentes, que não foram escritos sob FK enforcement.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _ligar_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _contar(session, uid: int) -> dict:
    """Linhas remanescentes por tabela. recorrencia_vigencias conta a tabela
    inteira: filtrar pelas recorrências do usuário daria 0 assim que elas
    saíssem, escondendo justamente a vigência órfã."""
    por_usuario = [
        Parcela, Transacao, PagamentoFatura, Cartao, Recorrencia, ChatMessage,
        NotificacaoEnvio,
    ]
    counts = {
        m.__tablename__: len(session.exec(select(m).where(m.usuario_id == uid)).all())
        for m in por_usuario
    }
    counts["recorrencia_vigencias"] = len(session.exec(select(RecorrenciaVigencia)).all())
    return counts


# --------------------------------------------------------------------------- #
# A purga: apaga os dados, preserva a conta                                    #
# --------------------------------------------------------------------------- #


class TestResetApagaEPreserva:
    def test_apaga_todos_os_lancamentos(self, authed_client, session):
        client, user = authed_client
        uid = user.id
        assert all(v >= 1 for v in _contar(session, uid).values())

        resp = client.post("/auth/reset-data", json={"password": SENHA})
        assert resp.status_code == 200, resp.text

        session.expire_all()
        depois = _contar(session, uid)
        assert depois == {k: 0 for k in depois}, depois

    def test_preserva_usuario_categorias_e_tokens(self, authed_client, session):
        client, user = authed_client
        uid = user.id

        resp = client.post("/auth/reset-data", json={"password": SENHA})
        assert resp.status_code == 200

        session.expire_all()
        # A conta continua: MESMO id (nunca deletar+recriar).
        assert session.get(Usuario, uid) is not None
        # A taxonomia do usuário sobrevive — ele quis zerar lançamentos.
        assert len(session.exec(select(CategoriaCustomizada).where(
            CategoriaCustomizada.usuario_id == uid)).all()) == 1
        # Continua logado: os tokens não são tocados.
        assert len(session.exec(select(RefreshToken).where(
            RefreshToken.usuario_id == uid)).all()) == 1

    def test_nao_limpa_os_cookies_da_sessao(self, authed_client):
        client, _ = authed_client
        resp = client.post("/auth/reset-data", json={"password": SENHA})
        assert resp.status_code == 200
        # Diferente do delete_me/logout-all: o usuário CONTINUA na conta.
        assert "set-cookie" not in {k.lower() for k in resp.headers}

    def test_resumo_traz_a_contagem_do_que_saiu(self, authed_client):
        client, _ = authed_client
        resp = client.post("/auth/reset-data", json={"password": SENHA})
        assert resp.json() == {
            "parcelas": 1,
            "transacoes": 1,
            "pagamentos_fatura": 1,
            "import_fatura_lote": 1,
            "import_extrato_lote": 1,
            "cartoes": 1,
            "notificacao_envio": 1,
            "recorrencia_vigencias": 1,
            "recorrencias": 1,
            "chat_messages": 1,
        }

    def test_apaga_a_notificacao_do_usuario_e_so_a_dele(self, authed_client, session):
        """O guard do aviso de vencimento sai — e o WHERE não pega o vizinho.

        Sem o delete, o registro de "já avisado hoje" sobrevive ao reset (nenhum
        cascade o cobre: ele só aponta para `usuarios`, que o reset preserva) e
        o aviso daquele dia é pulado em silêncio. Sem o `usuario_id ==` no
        WHERE, o reset de um usuário calaria o aviso de todos os outros — daí o
        vizinho com a MESMA (data_referencia, tipo), que é o par que um WHERE
        frouxo varreria junto.
        """
        client, user = authed_client

        vizinho = Usuario(
            email="vizinho@hivvo.test",
            username="vizinho",
            senha_hash=hash_password(SENHA),
            nome_completo="Não Mexa",
        )
        session.add(vizinho)
        session.flush()
        session.add(
            NotificacaoEnvio(
                usuario_id=vizinho.id,
                data_referencia=dt.date(2026, 7, 1),
                tipo="vencimento_fatura",
            )
        )
        session.commit()

        resp = client.post("/auth/reset-data", json={"password": SENHA})
        assert resp.status_code == 200, resp.text
        assert resp.json()["notificacao_envio"] == 1

        session.expire_all()
        assert session.exec(select(NotificacaoEnvio).where(
            NotificacaoEnvio.usuario_id == user.id)).all() == []
        assert len(session.exec(select(NotificacaoEnvio).where(
            NotificacaoEnvio.usuario_id == vizinho.id)).all()) == 1

    def test_reset_e_idempotente(self, authed_client):
        client, _ = authed_client
        client.post("/auth/reset-data", json={"password": SENHA})
        resp = client.post("/auth/reset-data", json={"password": SENHA})
        # Zerar o que já está zerado não é erro — só não apaga nada.
        assert resp.status_code == 200
        assert all(v == 0 for v in resp.json().values())


# --------------------------------------------------------------------------- #
# A ordem dos deletes vs. as FKs NO ACTION                                     #
# --------------------------------------------------------------------------- #


class TestOrdemDeExclusao:
    def test_cartao_com_compras_nao_bate_na_fk(self, session_fk):
        """O caso que a ordem errada quebraria, com FK checada de verdade.

        transacoes.cartao_id e parcelas.cartao_id são NO ACTION (T-14 as deixou
        fora do cascade de propósito: soft delete de cartão). Apagar `cartoes`
        antes das compras levanta IntegrityError.
        """
        user = _popular(session_fk)
        uid = user.id
        client = _authed(session_fk, user)
        try:
            resp = client.post("/auth/reset-data", json={"password": SENHA})
            assert resp.status_code == 200, resp.text
        finally:
            app.dependency_overrides.clear()

        session_fk.expire_all()
        depois = _contar(session_fk, uid)
        assert depois == {k: 0 for k in depois}, depois
        assert session_fk.get(Usuario, uid) is not None

    def test_a_fixture_realmente_checa_fk(self, session_fk):
        """Guarda da guarda: se o PRAGMA parar de valer, o teste acima vira
        teatro e ninguém percebe. Aqui a violação TEM de explodir."""
        from sqlalchemy.exc import IntegrityError

        session_fk.add(Cartao(usuario_id=999_999, nome="Órfão", tipo="Crédito"))
        with pytest.raises(IntegrityError):
            session_fk.commit()
        session_fk.rollback()


# --------------------------------------------------------------------------- #
# A regra da purga, checada pelo build em vez de lembrada                      #
# --------------------------------------------------------------------------- #


# O que o docstring de _purgar_dados_do_usuario já nomeia como preservado de
# propósito. `usuarios` é inerte aqui (identifica-se por `id`, não por
# usuario_id) e fica só para o conjunto bater 1:1 com o docstring.
ISENTAS_DELIBERADAS = {
    "usuarios",               # a conta em si: o reset existe para preservá-la
    "categorias",             # taxonomia do usuário, não lançamento
    "refresh_tokens",         # ele continua logado depois do reset
    "password_reset_tokens",  # idem, sessão intacta
}


class TestNenhumaTabelaFicaSemDecisao:
    def test_toda_tabela_com_usuario_id_esta_purgada_ou_isenta(self, session):
        """Fecha a regra que já falhou duas vezes (lotes, notificacao_envio).

        Até aqui a defesa era o docstring — exortação, que depende de alguém
        LEMBRAR. Isto para o build: quem criar a próxima tabela com usuario_id é
        obrigado a decidir, e a decisão fica escrita (na purga ou em
        ISENTAS_DELIBERADAS). Nenhum default silencioso.

        `purgadas` vem das chaves que a própria função devolve — o que ela
        EXECUTOU, não uma segunda lista para desincronizar. uid inexistente de
        propósito: só as chaves importam, não as contagens.

        Limite honesto: metadata só enxerga models importados, e quem entra em
        app/models/__init__.py está coberto. Um model fora dele também ficaria
        fora do create_all — quebraria bem antes e mais alto.
        """
        purgadas = set(_purgar_dados_do_usuario(999_999, session))
        com_usuario_id = {
            t.name for t in SQLModel.metadata.tables.values() if "usuario_id" in t.c
        }

        sem_decisao = com_usuario_id - purgadas - ISENTAS_DELIBERADAS
        assert sem_decisao == set(), (
            f"Tabela(s) com usuario_id sem decisão: {sorted(sem_decisao)}. "
            "Ou entra em _purgar_dados_do_usuario (+ chave em ResetDataResponse), "
            "ou entra em ISENTAS_DELIBERADAS com o motivo."
        )


# --------------------------------------------------------------------------- #
# Reautenticação e atomicidade                                                 #
# --------------------------------------------------------------------------- #


class TestGuardas:
    def test_senha_errada_nao_apaga_nada(self, authed_client, session):
        client, user = authed_client
        uid = user.id

        resp = client.post("/auth/reset-data", json={"password": "senha-errada"})
        assert resp.status_code == 401

        session.expire_all()
        assert all(v >= 1 for v in _contar(session, uid).values())

    def test_sem_autenticacao_401(self, session):
        _popular(session)
        app.dependency_overrides[get_session] = lambda: session
        try:
            client = TestClient(app, base_url="http://testserver/api/v1")
            resp = client.post("/auth/reset-data", json={"password": SENHA})
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_erro_no_meio_faz_rollback(self, authed_client, session, monkeypatch):
        """Atomicidade: um único commit no fim, nunca em etapas.

        Quebra o ÚLTIMO delete da ordem (chat_messages) — o ponto de máximo
        trabalho já feito. Com commits incrementais, o rollback não desfaria os
        anteriores e o usuário ficaria sem transações porém com cartões.

        Escopo honesto: aqui o rollback é explícito porque o teste injeta a
        própria sessão; em produção ele vem do `with Session(engine)` do
        get_session, fora do alcance deste teste. O que se prova é o invariante
        que nos cabe: a purga não commita no meio.
        """
        client, user = authed_client
        uid = user.id

        monkeypatch.setattr("app.routers.auth.ChatMessage", object())

        with pytest.raises(Exception):
            client.post("/auth/reset-data", json={"password": SENHA})

        session.rollback()
        session.expire_all()
        assert all(v >= 1 for v in _contar(session, uid).values())
