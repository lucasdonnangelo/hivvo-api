from typing import Optional

from pydantic import BaseModel, Field, field_validator


class FeedbackContexto(BaseModel):
    """Contexto capturado pelo FRONT, sem o usuário digitar.

    É o que separa "está quebrado" de um relato investigável. Tudo aqui é
    metadado do cliente — nada de dado financeiro, nada que o usuário não
    tenha visto na própria tela.

    O que NÃO está aqui, de propósito:
      - identidade (id/e-mail/nome): vem do `current_user` no handler. Um
        usuario_id vindo do browser é forjável e, pior, seria só errado.
      - timestamp do cliente: o e-mail já tem header Date e o backend tem a
        hora da request; o relógio do cliente é o único que pode estar torto.
    """

    # Rota ANTERIOR, não a atual: o formulário mora em Configurações, então a
    # rota atual é sempre /settings e não diz nada. A anterior é PISTA de onde
    # o usuário estava — o e-mail a rotula como pista, nunca como fato.
    # Só o pathname: `search`/`hash` ficam de fora no front pelo mesmo motivo
    # que o _sanitizeUrl do observability.ts documenta (o ?token= do reset).
    rota_anterior: Optional[str] = Field(default=None, max_length=200)
    # `VITE_APP_VERSION` — a MESMA string que a seção "Sobre" mostra ao usuário,
    # para o que ele lê e o que chega aqui baterem. Só o cliente sabe qual
    # bundle está rodando; o backend não tem como derivar isto.
    versao: str = Field(max_length=100)
    viewport: str = Field(max_length=50)
    # mobile|desktop derivado do MESMO useBreakpoint('md') que o app usa para
    # escolher o layout. Vem resolvido de propósito: recalcular o breakpoint a
    # partir da largura crua é onde o erro acontece, e os bugs deste app moram
    # nesse eixo.
    layout: str = Field(max_length=20)
    user_agent: str = Field(max_length=400)


class FeedbackRequest(BaseModel):
    # ⚠️ O NOME DO CAMPO É CARGA, não escolha estética: `mensagem` casa o
    # _SENSITIVE_KEY_PATTERN de src/lib/observability.ts:31 (hivvo-web), e é
    # isso que mantém o texto do feedback FORA do que vai ao Sentry — o mesmo
    # nome viaja no payload do front. Renomear para `texto`, `conteudo` ou
    # `descricao` DESLIGA essa filtragem em silêncio: nada quebra, nada avisa,
    # e o relato do usuário passa a viajar para o Sentry. Se um dia precisar
    # mudar, mude o padrão lá primeiro.
    #
    # Sem `min_length` aqui de propósito: a mensagem vazia é rejeitada no
    # HANDLER, com 400 e texto próprio. Um min_length daria 422 com `detail`
    # em lista, e o extractDetail do front renderizaria "Value error, ..." na
    # cara do usuário. Ver o comentário do handler.
    mensagem: str = Field(max_length=4000)
    contexto: FeedbackContexto

    @field_validator("mensagem", mode="before")
    @classmethod
    def strip_espacos(cls, v):
        # mode="before": o max_length precisa medir o valor já aparado, mesmo
        # contrato do RegisterRequest/UpdateMeRequest.
        return v.strip() if isinstance(v, str) else v
