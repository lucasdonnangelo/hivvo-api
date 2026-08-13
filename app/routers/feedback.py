"""Canal de feedback — formulário do app → e-mail, sem tabela.

Por que e-mail e não tabela: com a base atual, uma tabela sem tela de leitura é
dado que ninguém vê. O e-mail cai onde já se olha, e o `reply_to` com o endereço
do usuário torna o canal uma CONVERSA em vez de uma caixa de sugestões.

A consequência de não ter tabela é a regra dura deste arquivo: **falha de envio
não pode ser engolida**. O `forgot_password` loga e segue em frente porque lá o
token já foi persistido antes do envio — o reset continua disponível. Aqui não
há para onde o texto ir: engolir o erro PERDE a mensagem em silêncio. Então o
handler devolve erro, e a tela mostra o problema sem limpar o que foi digitado.
"""

import html
import logging

import resend
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.rate_limit import _user_or_ip_key, limiter
from app.core.scrub import curto
from app.models.user import Usuario
from app.schemas.feedback import FeedbackRequest

logger = logging.getLogger(__name__)

# Mesmo motivo do auth.py: api_key na inicialização do módulo, não a cada
# request. Repetida aqui (e não herdada da importação do auth) para o módulo não
# depender de ordem de import para funcionar.
resend.api_key = settings.RESEND_API_KEY

router = APIRouter(prefix="/feedback", tags=["feedback"])

_VAZIO = "Escreva sua mensagem antes de enviar."
_FALHA_ENVIO = "Não foi possível enviar sua mensagem agora. Tente de novo em instantes."


def _linha(rotulo: str, valor: str) -> str:
    return f"<p style='margin:2px 0'><strong>{rotulo}:</strong> {html.escape(valor)}</p>"


def _corpo_html(usuario: Usuario, body: FeedbackRequest) -> str:
    ctx = body.contexto
    # `html.escape` em TUDO que veio de fora: o texto é livre, e um "<" solto
    # quebraria o e-mail que você precisa ler. As quebras de linha viram <br>
    # DEPOIS do escape — antes, o próprio <br> seria escapado.
    mensagem = html.escape(body.mensagem).replace("\n", "<br>")
    return (
        f"<div style='font-family:sans-serif'>"
        f"<p style='white-space:pre-wrap;font-size:15px'>{mensagem}</p>"
        f"<hr style='border:none;border-top:1px solid #ddd;margin:20px 0'>"
        f"<div style='font-size:13px;color:#555'>"
        f"{_linha('De', f'{usuario.nome_completo} <{usuario.email}>')}"
        f"{_linha('Usuário', f'#{usuario.id}')}"
        f"{_linha('Versão', ctx.versao)}"
        # PISTA, e o e-mail diz isso na própria linha: a rota anterior sugere
        # onde ele estava antes de abrir Configurações, não onde o problema
        # aconteceu. Rotular evita que a pista seja lida como fato.
        f"{_linha('Vinha de', f'{ctx.rota_anterior} (pista, não confirmação)' if ctx.rota_anterior else 'não registrada')}"
        f"{_linha('Layout', f'{ctx.layout} · {ctx.viewport}')}"
        f"{_linha('Navegador', ctx.user_agent)}"
        f"</div></div>"
    )


@router.post("", status_code=200)
# 5/hora por usuário. O slowapi consome a cota na REQUISIÇÃO, não no sucesso:
# com um limite de 3, três falhas do Resend seguidas (que devolvem erro e pedem
# "tente de novo") gastariam a cota e matariam a mensagem. Com 5 sobra folga
# real, e 6 numa hora é abuso ou loop travado, não uso. Contar só o sucesso
# exigiria limiter próprio — não se paga nesta escala.
@limiter.limit("5/hour", key_func=_user_or_ip_key)
def enviar_feedback(
    body: FeedbackRequest,
    request: Request,
    current_user: Usuario = Depends(get_current_user),
):
    # Vazio/só espaço no HANDLER (400 com string limpa), e não como
    # `min_length` no schema: o 422 do Pydantic traz `detail` em LISTA, e o
    # extractDetail do front sabe ler string — a lista cairia num fallback
    # genérico ou num "Value error, ..." na cara do usuário. O schema já fez o
    # strip, então aqui basta testar o vazio.
    if not body.mensagem:
        raise HTTPException(status_code=400, detail=_VAZIO)

    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": [settings.FEEDBACK_TO],
            # O que faz disto uma conversa: responder no cliente de e-mail cai
            # direto no usuário, sem ninguém copiar endereço à mão.
            "reply_to": [current_user.email],
            "subject": f"Feedback Hivvo — {current_user.nome_completo}",
            "html": _corpo_html(current_user, body),
        })
    except Exception as e:
        # Mesmo cuidado do forgot_password ao logar erro de terceiro: classe +
        # `curto(e)`, nunca o texto inteiro (o erro do Resend ecoa endereço, e
        # o destinatário aqui é o reply_to do usuário). A mensagem do usuário
        # NUNCA entra no log — ela é o dado que este canal existe para carregar.
        logger.error(
            "Falha ao enviar e-mail de feedback: %s: %s", e.__class__.__name__, curto(e)
        )
        # 502 e não 500: quem falhou foi o provedor upstream. E não 200 com log
        # — ver o cabeçalho deste arquivo: sem tabela, 200 aqui é perda
        # silenciosa da única cópia da mensagem. Verificado por mutação: trocar
        # este raise por log-e-segue derruba test_falha_do_resend_nao_e_engolida.
        raise HTTPException(status_code=502, detail=_FALHA_ENVIO)

    return {"message": "Mensagem enviada."}
