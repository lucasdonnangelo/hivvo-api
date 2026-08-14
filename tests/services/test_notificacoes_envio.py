"""Idempotência e falha de envio do aviso de vencimento (#6, Batch 1).

O que estes testes protegem é a ORDEM: insere o guard → envia → commita. Cada
teste aqui mata uma forma de errá-la.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlmodel import func, select

from app.models.card import Cartao
from app.models.notificacao_envio import NotificacaoEnvio
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.services.notificacoes.envio import TIPO_VENCIMENTO, executar

HOJE = dt.date(2026, 8, 14)
ALVO = dt.date(2026, 8, 17)


@pytest.fixture()
def enviado(mocker):
    """Resend trocado por um duplo — nenhum teste manda e-mail de verdade."""
    return mocker.patch(
        "app.services.notificacoes.envio.resend.Emails.send", return_value={"id": "fake"}
    )


def _usuario(session, email="ana@hivvo.test") -> Usuario:
    usuario = Usuario(
        email=email,
        username=email.split("@")[0],
        senha_hash="x",
        nome_completo="Ana Souza",
    )
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    return usuario


def _fatura(session, usuario, nome="Nubank", valor="100.00", vencimento=ALVO.day) -> Cartao:
    cartao = Cartao(
        usuario_id=usuario.id,
        nome=nome,
        tipo="Crédito",
        dia_vencimento=vencimento,
        dia_fechamento=5,
        mes_offset_vencimento=0,
    )
    session.add(cartao)
    session.commit()
    session.refresh(cartao)
    session.add(
        Transacao(
            usuario_id=usuario.id,
            tipo="despesa",
            data=dt.date(2026, 7, 20),
            descricao="Compra",
            valor=Decimal(valor),
            categoria="Outros",
            forma_pagamento="Crédito",
            cartao_id=cartao.id,
            fatura_mes=ALVO.month,
            fatura_ano=ALVO.year,
        )
    )
    session.commit()
    return cartao


def _registros(session) -> int:
    return session.exec(
        select(func.count()).select_from(NotificacaoEnvio)
    ).one()


class TestIdempotencia:
    def test_primeira_execucao_envia_e_grava(self, session, enviado):
        usuario = _usuario(session)
        _fatura(session, usuario)

        resultado, _ = executar(session, HOJE)

        assert resultado.enviados == 1
        assert enviado.call_count == 1
        assert _registros(session) == 1

        registro = session.exec(select(NotificacaoEnvio)).one()
        assert registro.usuario_id == usuario.id
        assert registro.data_referencia == HOJE
        assert registro.tipo == TIPO_VENCIMENTO

    def test_segunda_execucao_no_mesmo_dia_nao_reenvia(self, session, enviado):
        """O UNIQUE é o mecanismo — não um EXISTS lido antes de escrever."""
        usuario = _usuario(session)
        _fatura(session, usuario)

        executar(session, HOJE)
        resultado, _ = executar(session, HOJE)

        assert resultado.enviados == 0
        assert resultado.ja_enviados == 1
        assert enviado.call_count == 1  # continua sendo UM e-mail
        assert _registros(session) == 1

    def test_dia_seguinte_avisa_de_novo(self, session, enviado):
        """A chave é (usuario, DIA, tipo): amanhã é outro aviso, não um bloqueio.

        Dois cartões vencendo em dias seguidos (18 e 19) dão um aviso em 15/08
        e outro em 16/08 — o guard de ontem não pode barrar o de hoje.
        """
        usuario = _usuario(session)
        _fatura(session, usuario, nome="Vence 18", vencimento=18)
        _fatura(session, usuario, nome="Vence 19", vencimento=19)

        executar(session, dt.date(2026, 8, 15))
        resultado, _ = executar(session, dt.date(2026, 8, 16))

        assert resultado.enviados == 1
        assert resultado.ja_enviados == 0
        assert enviado.call_count == 2
        assert _registros(session) == 2


class TestFalhaDeEnvio:
    def test_falha_do_resend_faz_rollback(self, session, mocker):
        """Nada gravado quando o e-mail não sai.

        Se o guard sobrevivesse à falha, o usuário ficaria marcado como
        avisado sem ter sido — a falha viraria silêncio PERMANENTE, porque a
        execução de amanhã veria o registro de hoje e pularia.
        """
        usuario = _usuario(session)
        _fatura(session, usuario)
        mocker.patch(
            "app.services.notificacoes.envio.resend.Emails.send",
            side_effect=Exception("Resend fora do ar"),
        )

        resultado, _ = executar(session, HOJE)

        assert resultado.falhas == 1
        assert resultado.enviados == 0
        assert _registros(session) == 0

    def test_execucao_seguinte_tenta_de_novo(self, session, mocker):
        """A consequência do rollback: a falha é recuperável sozinha."""
        usuario = _usuario(session)
        _fatura(session, usuario)
        mocker.patch(
            "app.services.notificacoes.envio.resend.Emails.send",
            side_effect=Exception("Resend fora do ar"),
        )
        executar(session, HOJE)

        enviado = mocker.patch(
            "app.services.notificacoes.envio.resend.Emails.send",
            return_value={"id": "fake"},
        )
        resultado, _ = executar(session, HOJE)

        assert resultado.enviados == 1
        assert enviado.call_count == 1
        assert _registros(session) == 1

    def test_falha_de_um_usuario_nao_derruba_o_outro(self, session, mocker):
        """Unidade transacional é UM usuário: a leva não morre junto."""
        ana = _usuario(session, email="ana@hivvo.test")
        bruno = _usuario(session, email="bruno@hivvo.test")
        _fatura(session, ana)
        _fatura(session, bruno)

        def _falha_so_para_ana(payload):
            if payload["to"] == ["ana@hivvo.test"]:
                raise Exception("Resend recusou")
            return {"id": "fake"}

        mocker.patch(
            "app.services.notificacoes.envio.resend.Emails.send",
            side_effect=_falha_so_para_ana,
        )

        resultado, _ = executar(session, HOJE)

        assert resultado.falhas == 1
        assert resultado.enviados == 1
        assert resultado.destinatarios == ["bruno@hivvo.test"]
        registro = session.exec(select(NotificacaoEnvio)).one()
        assert registro.usuario_id == bruno.id


class TestUmEmailPorUsuario:
    def test_tres_cartoes_um_email_com_os_tres(self, session, enviado):
        usuario = _usuario(session)
        _fatura(session, usuario, nome="Nubank", valor="100.00")
        _fatura(session, usuario, nome="Inter", valor="300.00")
        _fatura(session, usuario, nome="Itaú", valor="200.00")

        resultado, _ = executar(session, HOJE)

        assert resultado.enviados == 1
        assert enviado.call_count == 1

        payload = enviado.call_args[0][0]
        assert payload["to"] == ["ana@hivvo.test"]
        assert payload["subject"] == "Suas faturas vencem em 3 dias"
        for nome in ("Nubank", "Inter", "Itaú"):
            assert nome in payload["html"]
        assert "600,00" in payload["html"]  # o total das três
        assert _registros(session) == 1

    def test_sem_fatura_a_vencer_nenhum_email_sai(self, session, enviado):
        """Nunca enviar e-mail vazio: sem fatura, sem envio e sem registro."""
        _usuario(session)

        resultado, avisos = executar(session, HOJE)

        assert avisos == []
        assert resultado.enviados == 0
        assert enviado.call_count == 0
        assert _registros(session) == 0

    def test_opt_out_esta_no_corpo(self, session, enviado):
        """O e-mail diz como parar de receber — sem prometer entrega."""
        usuario = _usuario(session)
        _fatura(session, usuario)

        executar(session, HOJE)

        payload = enviado.call_args[0][0]
        assert "Responda este e-mail" in payload["html"]
        # A resposta cai numa caixa REAL, senão o opt-out oferecido é falso.
        assert payload["reply_to"] == ["contato@hivvo.app"]
