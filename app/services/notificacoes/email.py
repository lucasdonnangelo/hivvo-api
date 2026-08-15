"""Como o aviso de vencimento fica escrito (#6, Batch 1).

Só string — sem banco, sem rede. O que este módulo NÃO diz é tão decidido
quanto o que diz:

- **Não promete entrega.** Nada de "avisaremos sempre" ou "você será
  notificado": e-mail falha, o backend não garante isso, e uma promessa que o
  sistema não sustenta é pior que nenhuma.
- **Não manda o total quando falta menos.** O valor é sempre o RESTANTE, que
  vem pronto da consulta (`FaturaAvisada.restante`).
- **Não aponta para uma tela que não existe.** No Batch 1 a tela de
  preferência ainda não foi construída, então o opt-out oferecido é responder
  o e-mail — ver `envio.py`, que põe o `reply_to` numa caixa REAL. Quando a
  tela existir (Batch 2), a frase vira o link.

`html.escape` no nome do cartão pelo mesmo motivo do feedback: é texto livre
do usuário, e um "<" solto quebraria o e-mail que ele precisa ler.
"""

import html
from decimal import Decimal

from app.services.notificacoes.consulta import AvisoUsuario, FaturaAvisada


def formatar_brl(valor: Decimal) -> str:
    """1234.5 -> '1.234,50' (padrão brasileiro, sem o prefixo)."""
    return f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def assunto(aviso: AvisoUsuario) -> str:
    if len(aviso.faturas) == 1:
        return "Sua fatura vence em 3 dias"
    return "Suas faturas vencem em 3 dias"


def _linha_fatura(fatura: FaturaAvisada) -> str:
    # O "já pago" é o que impede um número CERTO de ser lido como errado:
    # "Itaú — R$ 250,00" para quem lembra de uma fatura de R$ 900,00 parece
    # engano do app. Segunda linha, menor e apagada, porque é explicação do
    # valor e não um segundo valor a comparar.
    explicacao = (
        f"<div style='font-size:12px;color:#777;font-weight:400;margin-top:2px'>"
        f"já pago: R$ {formatar_brl(fatura.ja_pago)}</div>"
        if fatura.ja_pago is not None
        else ""
    )
    return (
        "<tr>"
        f"<td style='padding:8px 12px 8px 0;vertical-align:top'>"
        f"{html.escape(fatura.cartao_nome)}</td>"
        f"<td style='padding:8px 0;text-align:right;white-space:nowrap;vertical-align:top'>"
        f"<strong>R$ {formatar_brl(fatura.restante)}</strong>{explicacao}</td>"
        "</tr>"
    )


def corpo_html(aviso: AvisoUsuario, opt_out: str) -> str:
    """Corpo do aviso. `opt_out` é a frase de como parar de receber.

    A frase entra por PARÂMETRO e não fixa no texto porque ela muda de
    mecanismo entre os batches (responder o e-mail agora, a tela depois) — e
    quem sabe qual mecanismo está no ar é quem envia, não quem formata.
    """
    primeiro_nome = html.escape(aviso.nome_completo.split(" ")[0])
    vencimento = aviso.faturas[0].vencimento.strftime("%d/%m/%Y")
    plural = len(aviso.faturas) > 1

    linhas = "".join(_linha_fatura(f) for f in aviso.faturas)
    total = sum((f.restante for f in aviso.faturas), Decimal("0.00"))
    rodape_total = (
        "<tr><td style='padding:12px 12px 0 0;border-top:1px solid #ddd'>Total</td>"
        f"<td style='padding:12px 0 0;text-align:right;border-top:1px solid #ddd'>"
        f"<strong>R$ {formatar_brl(total)}</strong></td></tr>"
        if plural
        else ""
    )

    # "em aberto" e não "a pagar": parte destes valores pode ser o restante de
    # uma fatura já parcialmente paga, e chamar isso de "sua fatura" cheia é
    # exatamente o erro que a decisão do restante evita.
    abertura = (
        f"{'Suas faturas vencem' if plural else 'Sua fatura vence'} em "
        f"<strong>{vencimento}</strong>. "
        f"{'Valores' if plural else 'Valor'} em aberto:"
    )

    return (
        # `max-width` porque cliente de e-mail em janela larga estica o
        # parágrafo pela tela inteira; a coluna curta é o que se lê.
        "<div style='font-family:sans-serif;font-size:15px;color:#222;max-width:520px'>"
        # A MARCA NO CORPO, e não só no remetente. Descoberto ao renderizar:
        # o corpo não dizia "Hivvo" em lugar nenhum. Um e-mail sobre dinheiro
        # a vencer, sem marca, com um valor e um pedido — é a forma de um
        # phishing, e o remetente é justamente a parte que o cliente de e-mail
        # colapsa ou que some quando a mensagem é encaminhada. Num aviso
        # recorrente, que a pessoa vai receber todo mês, é o corpo que precisa
        # se identificar sozinho.
        "<p style='font-size:13px;font-weight:600;color:#555;"
        "letter-spacing:0.04em;margin:0 0 20px'>HIVVO</p>"
        f"<p>Oi, {primeiro_nome}.</p>"
        f"<p>{abertura}</p>"
        "<table style='border-collapse:collapse;margin:16px 0'>"
        f"{linhas}{rodape_total}"
        "</table>"
        "<hr style='border:none;border-top:1px solid #ddd;margin:24px 0'>"
        f"<p style='font-size:13px;color:#555'>{html.escape(opt_out)}</p>"
        "</div>"
    )
