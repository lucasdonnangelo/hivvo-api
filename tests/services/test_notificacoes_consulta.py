"""Quem entra no aviso de vencimento, e com que valor (#6, Batch 1).

Data CONGELADA em todos os testes: `hoje` é parâmetro explícito de
`faturas_a_vencer`, então nenhum teste depende do relógio nem precisa de
patch. O alvo é sempre `hoje + 3`.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.card import Cartao
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.services.notificacoes.consulta import faturas_a_vencer

HOJE = dt.date(2026, 8, 14)
ALVO = dt.date(2026, 8, 17)  # HOJE + 3


def _usuario(session, email="a@hivvo.test", **kwargs) -> Usuario:
    usuario = Usuario(
        email=email,
        username=email.split("@")[0],
        senha_hash="x",
        nome_completo="Ana Souza",
        **kwargs,
    )
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    return usuario


def _cartao(session, usuario, nome="Nubank", dia_vencimento=17, **kwargs) -> Cartao:
    cartao = Cartao(
        usuario_id=usuario.id,
        nome=nome,
        tipo="Crédito",
        dia_vencimento=dia_vencimento,
        dia_fechamento=kwargs.pop("dia_fechamento", 5),
        mes_offset_vencimento=kwargs.pop("mes_offset_vencimento", 0),
        **kwargs,
    )
    session.add(cartao)
    session.commit()
    session.refresh(cartao)
    return cartao


def _compra(session, usuario, cartao, valor, mes=ALVO.month, ano=ALVO.year) -> Transacao:
    """Uma avulsa de cartão na competência — a composição mais simples da fatura."""
    transacao = Transacao(
        usuario_id=usuario.id,
        tipo="despesa",
        data=dt.date(2026, 7, 20),
        descricao="Compra",
        valor=Decimal(valor),
        categoria="Outros",
        forma_pagamento="Crédito",
        cartao_id=cartao.id,
        fatura_mes=mes,
        fatura_ano=ano,
    )
    session.add(transacao)
    session.commit()
    return transacao


def _pagamento(session, usuario, cartao, valor_pago, mes=ALVO.month, ano=ALVO.year):
    pagamento = PagamentoFatura(
        usuario_id=usuario.id,
        cartao_id=cartao.id,
        fatura_mes=mes,
        fatura_ano=ano,
        pago=True,
        valor_pago=Decimal(valor_pago),
        data_pagamento=HOJE,
    )
    session.add(pagamento)
    session.commit()
    return pagamento


class TestJanelaDeTresDias:
    """D+3 entra; D+2 e D+4 não. É a regra inteira do 'quando'."""

    @pytest.mark.parametrize(
        "dia_vencimento,esperado",
        [(17, True), (16, False), (18, False)],
        ids=["D+3 entra", "D+2 fica de fora", "D+4 fica de fora"],
    )
    def test_so_o_terceiro_dia_avisa(self, session, dia_vencimento, esperado):
        usuario = _usuario(session)
        cartao = _cartao(session, usuario, dia_vencimento=dia_vencimento)
        # A competência é a do vencimento — para D+2/D+4 é o mesmo mês.
        _compra(session, usuario, cartao, "100.00")

        avisos = faturas_a_vencer(session, HOJE)

        assert bool(avisos) is esperado

    def test_o_vencimento_avisado_e_o_alvo(self, session):
        usuario = _usuario(session)
        cartao = _cartao(session, usuario)
        _compra(session, usuario, cartao, "100.00")

        (aviso,) = faturas_a_vencer(session, HOJE)

        assert aviso.faturas[0].vencimento == ALVO

    def test_clamp_de_fim_de_mes(self, session):
        """dia_vencimento 31 num mês de 30 vence no dia 30 — e é avisado lá.

        Sem o clamp, o cartão de dia 31 nunca seria avisado em abril, junho,
        setembro e novembro: o filtro procuraria um dia que não existe.
        """
        hoje = dt.date(2026, 9, 27)  # alvo = 30/09, último dia de setembro
        usuario = _usuario(session)
        cartao = _cartao(session, usuario, dia_vencimento=31)
        _compra(session, usuario, cartao, "100.00", mes=9, ano=2026)

        (aviso,) = faturas_a_vencer(session, hoje)

        assert aviso.faturas[0].vencimento == dt.date(2026, 9, 30)


class TestStatusDaFatura:
    def test_fatura_paga_nao_entra(self, session):
        usuario = _usuario(session)
        cartao = _cartao(session, usuario)
        _compra(session, usuario, cartao, "100.00")
        _pagamento(session, usuario, cartao, "100.00")

        assert faturas_a_vencer(session, HOJE) == []

    def test_paga_parcial_entra_com_o_restante(self, session):
        """O valor avisado é o que FALTA, nunca o total.

        Fatura de 100 com 60 pagos avisa 40. Avisar 100 seria cobrar de novo
        o que já foi pago, na primeira mensagem que a pessoa recebe.
        """
        usuario = _usuario(session)
        cartao = _cartao(session, usuario)
        _compra(session, usuario, cartao, "100.00")
        _pagamento(session, usuario, cartao, "60.00")

        (aviso,) = faturas_a_vencer(session, HOJE)

        (fatura,) = aviso.faturas
        assert fatura.status == "paga_parcial"
        assert fatura.restante == Decimal("40.00")

    def test_fatura_ainda_aberta_entra(self, session):
        """Vence em 3 dias mas ainda aceita compras — e mesmo assim avisa.

        Não é caso de borda: `fechamento_vencimento_coerentes` (schemas/card)
        só exige vencimento > fechamento com offset 0, então fechar dia 14 e
        vencer dia 17 é um cartão perfeitamente válido. Em 14/08 essa fatura
        está `aberta` E vence em 3 dias. Silenciar aqui esconderia o aviso de
        todo cartão com folga curta entre fechar e vencer.
        """
        usuario = _usuario(session)
        cartao = _cartao(session, usuario, dia_fechamento=14, dia_vencimento=17)
        _compra(session, usuario, cartao, "100.00")

        (aviso,) = faturas_a_vencer(session, HOJE)

        (fatura,) = aviso.faturas
        assert fatura.status == "aberta"
        assert fatura.restante == Decimal("100.00")

    def test_fatura_vazia_nao_entra(self, session):
        """Cartão vence no alvo mas não tem lançamento algum na competência."""
        usuario = _usuario(session)
        _cartao(session, usuario)

        assert faturas_a_vencer(session, HOJE) == []

    def test_restante_zero_nao_entra(self, session):
        """Estorno que zera a fatura: nada a cobrar, nada a avisar."""
        usuario = _usuario(session)
        cartao = _cartao(session, usuario)
        _compra(session, usuario, cartao, "100.00")
        estorno = Transacao(
            usuario_id=usuario.id,
            tipo="estorno",
            data=dt.date(2026, 7, 25),
            descricao="Devolução",
            valor=Decimal("100.00"),
            categoria="Outros",
            forma_pagamento="Crédito",
            cartao_id=cartao.id,
            fatura_mes=ALVO.month,
            fatura_ano=ALVO.year,
        )
        session.add(estorno)
        session.commit()

        assert faturas_a_vencer(session, HOJE) == []


class TestQuemRecebe:
    def test_preferencia_desligada_nao_entra(self, session):
        usuario = _usuario(session, notificar_vencimento=False)
        cartao = _cartao(session, usuario)
        _compra(session, usuario, cartao, "100.00")

        assert faturas_a_vencer(session, HOJE) == []

    def test_preferencia_nasce_ligada(self, session):
        """Opt-out, não opt-in: quem nunca tocou na config recebe."""
        usuario = _usuario(session)
        assert usuario.notificar_vencimento is True

        cartao = _cartao(session, usuario)
        _compra(session, usuario, cartao, "100.00")

        assert len(faturas_a_vencer(session, HOJE)) == 1

    def test_usuario_inativo_nao_entra(self, session):
        usuario = _usuario(session, ativo=False)
        cartao = _cartao(session, usuario)
        _compra(session, usuario, cartao, "100.00")

        assert faturas_a_vencer(session, HOJE) == []

    def test_cartao_sem_dia_vencimento_nao_entra(self, session):
        """O fallback 'fim do mês' serve a um agregado, não a uma afirmação.

        `vencimento_avulsa` devolve o último dia do mês para cartão sem
        dia_vencimento — conservador numa soma de 'a pagar', mas no e-mail
        viraria uma data inventada.
        """
        hoje = dt.date(2026, 8, 28)  # alvo = 31/08, último dia do mês
        usuario = _usuario(session)
        cartao = _cartao(session, usuario, dia_vencimento=None)
        _compra(session, usuario, cartao, "100.00", mes=8, ano=2026)

        assert faturas_a_vencer(session, hoje) == []

    def test_cartao_inativo_entra(self, session):
        """Coerente com a lente 3d, que também não filtra `ativo`.

        A fatura de um cartão desativado continua aparecendo na tela e
        continua tendo que ser paga.
        """
        usuario = _usuario(session)
        cartao = _cartao(session, usuario, ativo=False)
        _compra(session, usuario, cartao, "100.00")

        (aviso,) = faturas_a_vencer(session, HOJE)

        assert aviso.faturas[0].cartao_id == cartao.id

    def test_isolamento_entre_usuarios(self, session):
        """A fatura de um nunca aparece no aviso do outro."""
        ana = _usuario(session, email="ana@hivvo.test")
        bruno = _usuario(session, email="bruno@hivvo.test")
        cartao_ana = _cartao(session, ana, nome="Cartão da Ana")
        cartao_bruno = _cartao(session, bruno, nome="Cartão do Bruno")
        _compra(session, ana, cartao_ana, "100.00")
        _compra(session, bruno, cartao_bruno, "200.00")

        aviso_ana, aviso_bruno = faturas_a_vencer(session, HOJE)

        assert [f.cartao_nome for f in aviso_ana.faturas] == ["Cartão da Ana"]
        assert [f.cartao_nome for f in aviso_bruno.faturas] == ["Cartão do Bruno"]


def test_tres_cartoes_no_mesmo_dia_viram_um_aviso(session):
    """Três cartões vencendo no mesmo dia são UM aviso com três linhas.

    É a decisão de produto que separa "avisar" de "spammar": três e-mails no
    mesmo minuto ensinam a pessoa a ignorar o próximo.
    """
    usuario = _usuario(session)
    for nome, valor in [("Nubank", "100.00"), ("Inter", "300.00"), ("Itaú", "200.00")]:
        cartao = _cartao(session, usuario, nome=nome)
        _compra(session, usuario, cartao, valor)

    avisos = faturas_a_vencer(session, HOJE)

    assert len(avisos) == 1
    (aviso,) = avisos
    # Ordem determinística: maior restante primeiro.
    assert [(f.cartao_nome, f.restante) for f in aviso.faturas] == [
        ("Inter", Decimal("300.00")),
        ("Itaú", Decimal("200.00")),
        ("Nubank", Decimal("100.00")),
    ]
