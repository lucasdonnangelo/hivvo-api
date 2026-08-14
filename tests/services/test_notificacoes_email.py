"""A peça que chega na caixa de entrada (#6, Batch 1).

Estes testes nasceram de RENDERIZAR o e-mail e olhar, não de ler o código: o
`--html-out` do script salva o payload real e o browser mostra o que os testes
de payload não mostram. Foi assim que a falta da marca no corpo apareceu.

O que cada um trava é uma coisa que só se vê na peça montada.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.services.notificacoes.consulta import AvisoUsuario, FaturaAvisada
from app.services.notificacoes.email import assunto, corpo_html, formatar_brl

VENCIMENTO = dt.date(2026, 8, 17)
OPT_OUT = "Responda este e-mail pedindo para parar."


def _fatura(nome: str, restante: str, status: str = "a_vencer") -> FaturaAvisada:
    return FaturaAvisada(
        cartao_id=1,
        cartao_nome=nome,
        vencimento=VENCIMENTO,
        restante=Decimal(restante),
        status=status,
    )


def _aviso(*faturas: FaturaAvisada, nome="Ana Souza") -> AvisoUsuario:
    return AvisoUsuario(
        usuario_id=1, email="ana@hivvo.test", nome_completo=nome, faturas=list(faturas)
    )


class TestFormatacaoDeValor:
    @pytest.mark.parametrize(
        "valor,esperado",
        [
            ("7.50", "7,50"),
            ("250.00", "250,00"),
            ("1240.55", "1.240,55"),
            ("12480.90", "12.480,90"),
            ("1234567.89", "1.234.567,89"),
        ],
    )
    def test_padrao_brasileiro(self, valor, esperado):
        """Ponto de milhar e vírgula decimal — o inverso do default do Python."""
        assert formatar_brl(Decimal(valor)) == esperado


class TestEscape:
    def test_nome_de_cartao_e_texto_livre_do_usuario(self):
        """O nome do cartão é digitado pelo usuário e vai PARA DENTRO do HTML.

        Sem escape, um `<script>` no nome do cartão viaja no corpo do e-mail, e
        um `<` solto já bastaria para quebrar a peça que a pessoa precisa ler.
        """
        html = corpo_html(
            _aviso(_fatura('<b>Nubank</b> & "Gold" <script>alert(1)</script>', "500.00")),
            OPT_OUT,
        )

        # Nenhuma tag do usuário sobrevive como TAG...
        assert "<script>" not in html
        assert "<b>" not in html
        # ...e todas sobrevivem como TEXTO, que é o que a pessoa deve ler.
        assert "&lt;b&gt;Nubank&lt;/b&gt; &amp; &quot;Gold&quot;" in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_nome_do_usuario_tambem_e_escapado(self):
        html = corpo_html(_aviso(_fatura("Nubank", "10.00"), nome="<i>Ana</i> Souza"), OPT_OUT)

        assert "Oi, &lt;i&gt;Ana&lt;/i&gt;." in html


class TestUmVersusTres:
    def test_um_cartao_no_singular_e_sem_linha_de_total(self):
        """Total de uma linha só repetiria o número logo acima."""
        aviso = _aviso(_fatura("Nubank", "1240.55"))

        assert assunto(aviso) == "Sua fatura vence em 3 dias"
        html = corpo_html(aviso, OPT_OUT)
        assert "Sua fatura vence em <strong>17/08/2026</strong>" in html
        assert "Valor em aberto" in html
        assert "Total" not in html

    def test_tres_cartoes_no_plural_e_com_total_somado(self):
        aviso = _aviso(
            _fatura("Nubank Ultravioleta", "12480.90"),
            _fatura("Itaú Personnalité", "250.00", status="paga_parcial"),
            _fatura("Inter", "7.50"),
        )

        assert assunto(aviso) == "Suas faturas vencem em 3 dias"
        html = corpo_html(aviso, OPT_OUT)
        assert "Suas faturas vencem em <strong>17/08/2026</strong>" in html
        assert "Valores em aberto" in html
        # 12480.90 + 250.00 + 7.50
        assert "R$ 12.738,40" in html


class TestConfiancaDaPeca:
    def test_o_corpo_se_identifica_sozinho(self):
        """A marca no CORPO, não só no remetente.

        Achado ao renderizar: o corpo não dizia "Hivvo" em lugar nenhum. Um
        e-mail sobre dinheiro a vencer, com um valor e sem marca, tem a forma
        de um phishing — e o remetente é justamente o que o cliente de e-mail
        colapsa e o que se perde no encaminhamento.
        """
        html = corpo_html(_aviso(_fatura("Nubank", "10.00")), OPT_OUT)

        assert "HIVVO" in html

    def test_diz_como_desligar_sem_prometer_entrega(self):
        """O e-mail oferece o controle e NÃO promete que sempre chegará.

        E-mail falha; o backend não garante entrega. Prometer o que o sistema
        não sustenta é pior que não prometer nada.
        """
        html = corpo_html(_aviso(_fatura("Nubank", "10.00")), OPT_OUT)

        assert OPT_OUT in html
        for promessa in ("avisaremos sempre", "você será notificado", "garantimos"):
            assert promessa not in html.lower()
