"""O caminho --dry-run é COMPROVADAMENTE de leitura (#6, Batch 1).

Por que este teste existe: o `--dry-run` foi feito para conferir a consulta
contra o banco de PRODUÇÃO, e a regra do projeto é categórica sobre não subir
nada local contra aquele `.env`. A regra existe porque o app ESCREVE — um
caminho de leitura é outra coisa, mas SÓ se for provado, e não "de leitura
porque foi escrito assim".

Mesma técnica (e mesmo idioma) do `test_preview_nao_escreve_nada_no_banco` do
extrato: cinto e suspensórios — um listener de `before_flush`, que só dispara
com estado pendente de verdade, E a contagem de linhas de TODAS as tabelas.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import event, func
from sqlalchemy import select as sa_select
from sqlmodel import SQLModel

from app.models.card import Cartao
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.services.notificacoes.envio import executar

HOJE = dt.date(2026, 8, 14)
ALVO = dt.date(2026, 8, 17)


@pytest.fixture()
def resend_proibido(mocker):
    """Qualquer chamada ao Resend no dry-run é falha do teste, não do duplo."""
    return mocker.patch(
        "app.services.notificacoes.envio.resend.Emails.send",
        side_effect=AssertionError("o dry-run tentou ENVIAR e-mail"),
    )


def _contagens(session) -> dict[str, int]:
    return {
        tabela.name: session.execute(
            sa_select(func.count()).select_from(tabela)
        ).scalar()
        for tabela in SQLModel.metadata.sorted_tables
    }


def _cenario(session) -> Usuario:
    """Um usuário com fatura a vencer no alvo — há o que enviar."""
    usuario = Usuario(
        email="ana@hivvo.test",
        username="ana",
        senha_hash="x",
        nome_completo="Ana Souza",
    )
    session.add(usuario)
    session.commit()
    session.refresh(usuario)

    cartao = Cartao(
        usuario_id=usuario.id,
        nome="Nubank",
        tipo="Crédito",
        dia_vencimento=ALVO.day,
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
            valor=Decimal("100.00"),
            categoria="Outros",
            forma_pagamento="Crédito",
            cartao_id=cartao.id,
            fatura_mes=ALVO.month,
            fatura_ano=ALVO.year,
        )
    )
    session.commit()
    return usuario


def test_dry_run_nao_escreve_nada_no_banco(session, resend_proibido):
    """ZERO escrita: nem add, nem flush, nem commit no caminho --dry-run."""
    _cenario(session)

    escritas: list[tuple] = []

    def _guarda(sessao, flush_context, instances):
        escritas.append(
            (list(sessao.new), list(sessao.dirty), list(sessao.deleted))
        )

    antes = _contagens(session)
    event.listen(session, "before_flush", _guarda)
    try:
        resultado, avisos = executar(session, HOJE, dry_run=True)
    finally:
        event.remove(session, "before_flush", _guarda)

    # O cenário TEM o que enviar — senão o teste passaria por vacuidade.
    assert len(avisos) == 1
    assert avisos[0].faturas[0].restante == Decimal("100.00")

    assert escritas == [], f"o dry-run tentou escrever: {escritas}"
    assert _contagens(session) == antes
    assert resend_proibido.call_count == 0
    assert resultado.enviados == 0


def test_dry_run_nao_consome_o_direito_ao_aviso(session, resend_proibido, mocker):
    """Rodar o dry-run antes não impede o envio real depois.

    Se o dry-run gravasse o guard, conferir a consulta CANCELARIA o aviso do
    dia — o inverso do que a conferência serve para fazer.
    """
    _cenario(session)
    executar(session, HOJE, dry_run=True)

    enviado = mocker.patch(
        "app.services.notificacoes.envio.resend.Emails.send",
        return_value={"id": "fake"},
    )
    resultado, _ = executar(session, HOJE)

    assert resultado.enviados == 1
    assert enviado.call_count == 1
