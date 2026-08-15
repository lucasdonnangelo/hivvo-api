"""O ciclo do aviso de vencimento: guard → envia → commita (#6, Batch 1).

## A ordem, e por que ela é essa

    session.add(registro)   # o guard
    session.flush()         # <- é AQUI que o UNIQUE dispara
    resend.Emails.send(...)
    session.commit()

Inserir o guard PRIMEIRO e deixar o UNIQUE ser o mecanismo (padrão que a
importação já provou) — não um `EXISTS` pré-checado, que não fecha a corrida
entre duas execuções: entre ler "ainda não enviei" e escrever "enviei", outra
execução faz o mesmo e saem dois e-mails.

Commitar DEPOIS do envio, e fazer rollback quando o envio falha, é o que
garante a segunda metade: nada gravado, então a execução seguinte tenta de
novo. O contrário — commitar antes de enviar — consumiria o direito ao aviso
sem que o aviso saísse, e o usuário simplesmente não seria avisado, em
silêncio.

## A unidade transacional é UM USUÁRIO

Commit por usuário, não por leva. No Postgres um flush que falha envenena a
transação até o rollback; isolar por usuário impede que a falha de um mate o
aviso dos outros, e é o que faz `IntegrityError` significar "este usuário já
recebeu hoje" em vez de "a leva toda está perdida".
"""

import datetime as dt
import logging
from dataclasses import dataclass, field

import resend
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.config import settings
from app.core.scrub import curto
from app.models.notificacao_envio import NotificacaoEnvio
from app.services.notificacoes.consulta import AvisoUsuario, faturas_a_vencer
from app.services.notificacoes.email import assunto, corpo_html

logger = logging.getLogger(__name__)

# Mesmo motivo do feedback.py/auth.py: api_key na inicialização do módulo, não
# a cada envio. Repetida aqui para o módulo não depender de ordem de import.
resend.api_key = settings.RESEND_API_KEY

TIPO_VENCIMENTO = "vencimento_fatura"

# Batch 2: o opt-out passa a apontar a TELA, porque agora ela existe. No Batch 1
# a frase era "responda este e-mail", que era verdade enquanto o controle não
# existia — apontar para uma tela ausente teria sido prometer uma decisão que o
# usuário não podia tomar.
#
# ⚠️ ESTA FRASE E A TELA SOBEM JUNTAS, NESTA ORDEM: web primeiro (quem OFERECE o
# controle), api depois (quem o ANUNCIA). Invertido, o e-mail manda a pessoa a
# uma Configurações que ainda não tem o toggle — e a promessa vazia é
# exatamente o que a ordem do Batch 1 evitou, por outro motivo.
#
# O `reply_to` continua na caixa real de contato: não é anunciado, mas é a rede
# para quem responder assim mesmo.
_OPT_OUT = (
    "Não quer mais receber estes avisos? Desligue em Configurações › "
    "Notificações, no Hivvo."
)


@dataclass
class Resultado:
    """O que a execução fez — o que o script imprime e usa no exit code."""

    enviados: int = 0
    ja_enviados: int = 0  # o UNIQUE barrou: já recebeu o aviso de hoje
    falhas: int = 0
    destinatarios: list[str] = field(default_factory=list)


def montar_payload(aviso: AvisoUsuario) -> dict:
    """O payload EXATO que vai ao Resend.

    Função separada para que a prévia (`--html-out` do script) seja a MESMA
    peça que o envio — não uma reconstrução parecida. Um preview montado por
    conta própria diverge do enviado no dia em que alguém mexe num dos dois,
    e o preview passa a atestar um e-mail que ninguém recebe.
    """
    return {
        "from": settings.EMAIL_FROM,
        "to": [aviso.email],
        # É o que torna o "responda para parar" verdadeiro: a resposta cai numa
        # caixa que alguém lê, e não num noreply.
        "reply_to": [settings.FEEDBACK_TO],
        "subject": assunto(aviso),
        "html": corpo_html(aviso, _OPT_OUT),
    }


def _enviar(aviso: AvisoUsuario) -> None:
    """Costura com o Resend. Isolada para o teste poder trocá-la por um duplo."""
    resend.Emails.send(montar_payload(aviso))


def executar(
    session: Session,
    hoje: dt.date,
    *,
    dry_run: bool = False,
    apenas_usuario_id: int | None = None,
) -> tuple[Resultado, list[AvisoUsuario]]:
    """Roda o ciclo do dia `hoje` e devolve (resultado, avisos considerados).

    `dry_run=True` NÃO ESCREVE NADA: nem `add`, nem `flush`, nem `commit` — o
    caminho retorna logo depois da consulta, que é só leitura. Isso é o que
    torna seguro apontar o script para o banco de produção só para conferir a
    consulta; `tests/services/test_notificacoes_dry_run.py` prova a ausência
    de escrita com um listener de `before_flush`, em vez de a garantia ser
    "de leitura porque foi escrito assim".
    """
    avisos = faturas_a_vencer(session, hoje)
    if apenas_usuario_id is not None:
        avisos = [a for a in avisos if a.usuario_id == apenas_usuario_id]

    resultado = Resultado()
    if dry_run:
        return resultado, avisos

    for aviso in avisos:
        registro = NotificacaoEnvio(
            usuario_id=aviso.usuario_id,
            data_referencia=hoje,
            tipo=TIPO_VENCIMENTO,
        )
        session.add(registro)
        try:
            session.flush()
        except IntegrityError:
            # O UNIQUE (usuario_id, data_referencia, tipo) barrou: este usuário
            # já recebeu o aviso de hoje. Não é erro — é a idempotência
            # funcionando, inclusive contra duas execuções concorrentes.
            session.rollback()
            resultado.ja_enviados += 1
            continue

        try:
            _enviar(aviso)
        except Exception as e:
            # ROLLBACK, e não `continue` seco: o guard já foi flushado nesta
            # transação. Sem desfazê-lo, o registro entraria no commit de
            # alguém e o usuário ficaria marcado como avisado sem ter sido —
            # a falha viraria silêncio permanente em vez de "tenta amanhã".
            # Verificado por mutação (scripts/mutacoes/notificacao_vencimento.json).
            session.rollback()
            # Classe + `curto(e)`, nunca o texto inteiro: o erro do Resend ecoa
            # endereço de e-mail. Mesmo cuidado do feedback e do forgot_password.
            logger.error(
                "Falha ao enviar aviso de vencimento (usuario_id=%s): %s: %s",
                aviso.usuario_id,
                e.__class__.__name__,
                curto(e),
            )
            resultado.falhas += 1
            continue

        session.commit()
        resultado.enviados += 1
        resultado.destinatarios.append(aviso.email)

    return resultado, avisos
