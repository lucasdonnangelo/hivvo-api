import datetime as dt
import logging
import re
import uuid
from typing import Optional

import resend
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlmodel import Session, delete, select

from app.core.rate_limit import limiter

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    hash_token,
    revoke_all_refresh_tokens,
    rotate_refresh_token,
    verify_password,
)
from app.core.config import settings
from app.core.database import get_session
from app.core.scrub import curto
from app.models.card import Cartao
from app.models.category import CategoriaCustomizada
from app.models.chat import ChatMessage
from app.models.import_extrato_lote import ImportExtratoLote
from app.models.import_fatura_lote import ImportFaturaLote
from app.models.installment import Parcela
from app.models.notificacao_envio import NotificacaoEnvio
from app.models.pagamento_fatura import PagamentoFatura
from app.models.password_reset_token import PasswordResetToken
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.refresh_token import RefreshToken
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.schemas.auth import (
    ChangePasswordRequest,
    DeleteMeRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetDataRequest,
    ResetDataResponse,
    ResetPasswordRequest,
    UpdateMeRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

# F-18/T-31: api_key setada na inicialização do módulo, não a cada request.
resend.api_key = settings.RESEND_API_KEY

router = APIRouter(prefix="/auth", tags=["auth"])


def _generate_username(email: str, session: Session) -> str:
    prefix = email.split("@")[0]
    base = re.sub(r"[^a-z0-9]", "_", prefix).strip("_") or "user"
    candidate = base
    counter = 2
    while session.exec(select(Usuario).where(Usuario.username == candidate)).first():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate

_MAX_TENTATIVAS = 5
_BLOQUEIO_MINUTOS = 15
_COOKIE_ACCESS = "access_token"
_COOKIE_REFRESH = "refresh_token"
_COOKIE_DOMAIN = ".hivvo.app"


def _cookie_kwargs() -> dict:
    # F-03: atributos de cookie condicionados por ambiente, centralizados para
    # set e clear não divergirem (senão o browser não casa o cookie na limpeza).
    # PRODUÇÃO: Domain=.hivvo.app (o same-site vale entre app. e api.) + Secure
    # (HTTPS). DEV (localhost/http): sem Domain e sem Secure. SameSite=Lax +
    # HttpOnly em ambos — Lax preserva a defesa CSRF.
    is_prod = settings.ENVIRONMENT == "production"
    kwargs: dict = {"httponly": True, "secure": is_prod, "samesite": "lax", "path": "/"}
    if is_prod:
        kwargs["domain"] = _COOKIE_DOMAIN
    return kwargs


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_ACCESS,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **_cookie_kwargs(),
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_REFRESH,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **_cookie_kwargs(),
    )


def _clear_auth_cookies(response: Response) -> None:
    # Mesmos atributos do set (domínio/path/samesite/secure) — senão o browser
    # não casa o cookie para removê-lo.
    response.delete_cookie(_COOKIE_ACCESS, **_cookie_kwargs())
    response.delete_cookie(_COOKIE_REFRESH, **_cookie_kwargs())


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")  # F-04: por IP — trava criação de contas em massa
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    if session.exec(select(Usuario).where(Usuario.email == body.email)).first():
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")

    user = Usuario(
        email=body.email,
        username=_generate_username(body.email, session),
        nome_completo=body.nome_completo,
        senha_hash=hash_password(body.password),
    )
    session.add(user)
    session.flush()  # popula user.id antes de criar o refresh token

    refresh_token_str = create_refresh_token(user.id, session)
    session.commit()
    session.refresh(user)

    _set_auth_cookie(response, create_access_token(user.id))
    _set_refresh_cookie(response, refresh_token_str)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse)
@limiter.limit("10/minute")  # F-04: por IP — complementa o lockout por conta
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    user = session.exec(select(Usuario).where(Usuario.email == body.email)).first()

    if user is None:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    if not user.ativo:
        raise HTTPException(status_code=403, detail="Conta desativada")

    if user.bloqueado_ate and user.bloqueado_ate > dt.datetime.utcnow():
        raise HTTPException(status_code=429, detail="Conta temporariamente bloqueada. Tente novamente mais tarde.")

    if not verify_password(body.password, user.senha_hash):
        user.tentativas_login += 1
        if user.tentativas_login >= _MAX_TENTATIVAS:
            user.bloqueado_ate = dt.datetime.utcnow() + dt.timedelta(minutes=_BLOQUEIO_MINUTOS)
        session.add(user)
        session.commit()
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    user.tentativas_login = 0
    user.bloqueado_ate = None
    session.add(user)

    refresh_token_str = create_refresh_token(user.id, session)
    session.commit()
    session.refresh(user)

    _set_auth_cookie(response, create_access_token(user.id))
    _set_refresh_cookie(response, refresh_token_str)
    return UserResponse.model_validate(user)


@router.post("/refresh", response_model=UserResponse)
def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    session: Session = Depends(get_session),
):
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")

    user_id, new_refresh_str = rotate_refresh_token(refresh_token, session)
    session.commit()

    user = session.get(Usuario, user_id)
    if user is None or not user.ativo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inativo ou não encontrado")

    _set_auth_cookie(response, create_access_token(user_id))
    _set_refresh_cookie(response, new_refresh_str)
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    session: Session = Depends(get_session),
):
    if refresh_token is not None:
        token_record = session.exec(
            select(RefreshToken).where(RefreshToken.token == hash_token(refresh_token))
        ).first()
        if token_record and not token_record.revogado:
            token_record.revogado = True
            session.add(token_record)
            session.commit()

    _clear_auth_cookies(response)


@router.get("/me", response_model=UserResponse)
def me(current_user: Usuario = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.put("/me", response_model=UserResponse)
def update_me(
    body: UpdateMeRequest,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Atualiza o perfil — aplica só os campos que vieram (exclude_unset).

    A UI do Perfil manda apenas nome_completo; username segue aceito (interno,
    auto-gerado do e-mail) para um cliente futuro. O schema garante que ao menos
    um campo veio, e não-None.
    """
    campos = body.model_dump(exclude_unset=True)

    # Só consulta unicidade quando o username está mesmo mudando.
    if body.username is not None:
        existing = session.exec(
            select(Usuario).where(
                Usuario.username == body.username,
                Usuario.id != current_user.id
            )
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username já em uso.")

    for campo, valor in campos.items():
        if valor is not None:
            setattr(current_user, campo, valor)

    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return UserResponse.model_validate(current_user)


def _purgar_dados_do_usuario(uid: int, session: Session) -> dict[str, int]:
    """Apaga os DADOS do usuário (não a conta) — base do reset E do delete_me.

    UMA função porque o furo que ela corrige nasceu de dois lugares que deveriam
    ser um: o delete_me esquecia `recorrencias`/`recorrencia_vigencias` (só o ON
    DELETE CASCADE do Postgres salvava, e o teste não pegava — o SQLite da suíte
    não força FK sem PRAGMA). Um lugar para errar.

    ORDEM (confirmada nas migrations, não negociável): `parcelas.transacao_id` é
    CASCADE, então parcelas saem antes de transacoes; `transacoes.cartao_id` e
    `parcelas.cartao_id` são NO ACTION — o T-14 as deixou fora do cascade DE
    PROPÓSITO (soft delete de cartão) —, então o banco BLOQUEIA apagar cartão com
    compras e os deletes têm de ser explícitos nesta ordem. Nenhum cascade cobre
    o caminho de `cartoes`, e no reset o `usuario_id` sobrevive por definição:
    não dá para apoiar no banco.

    REGRA, porque já falhou duas vezes (lotes de importação, notificacao_envio):
    TODA tabela nova que sirva de GUARD DE IDEMPOTÊNCIA entra aqui no dia em que
    nasce. O ON DELETE CASCADE cobre o delete_me e NÃO cobre o reset — que
    preserva o usuario_id POR DEFINIÇÃO —, então o guard sobrevive e passa a
    bloquear em silêncio a operação que ele guarda (nenhum erro, só a coisa não
    acontecendo). E a chave nova tem de entrar TAMBÉM em ResetDataResponse: o
    Pydantic descarta chave extra sem reclamar e o recibo reportaria menos do
    que a purga apagou.

    NÃO commita — quem chama controla a transação (tudo-ou-nada num único
    commit). NÃO apaga: usuarios, categorias, refresh_tokens,
    password_reset_tokens.

    Devolve o rowcount por tabela (grátis: vem do próprio DELETE).
    """
    apagados: dict[str, int] = {}

    def _apagar(stmt, tabela: str) -> None:
        # synchronize_session=False: delete em massa não precisa reconciliar a
        # identity map (o chamador não reusa as instâncias apagadas), e o
        # delete por subquery não é avaliável em Python.
        result = session.exec(stmt.execution_options(synchronize_session=False))
        apagados[tabela] = result.rowcount

    _apagar(delete(Parcela).where(Parcela.usuario_id == uid), "parcelas")
    _apagar(delete(Transacao).where(Transacao.usuario_id == uid), "transacoes")
    _apagar(delete(PagamentoFatura).where(PagamentoFatura.usuario_id == uid), "pagamentos_fatura")
    # Guards de idempotência (lotes de importação e aviso já enviado no dia):
    # não são lançamentos, mas cada um deles de pé TRAVA EM SILÊNCIO a operação
    # que guarda — o 409 do lote impede REIMPORTAR o mesmo PDF para sempre, e a
    # linha de notificação faz o aviso daquele dia ser pulado sem erro nenhum.
    # Explícitos porque nenhum cascade os cobre no reset: o de EXTRATO e o de
    # notificação só dependem de `usuarios` (que o reset preserva por definição)
    # e o de fatura só sairia de carona no delete de `cartoes`.
    _apagar(delete(ImportFaturaLote).where(ImportFaturaLote.usuario_id == uid), "import_fatura_lote")
    _apagar(delete(ImportExtratoLote).where(ImportExtratoLote.usuario_id == uid), "import_extrato_lote")
    _apagar(delete(NotificacaoEnvio).where(NotificacaoEnvio.usuario_id == uid), "notificacao_envio")
    _apagar(delete(Cartao).where(Cartao.usuario_id == uid), "cartoes")
    # recorrencia_vigencias não tem usuario_id (liga por recorrencia_id) — daí a
    # subquery, e daí ela sair ANTES de recorrencias: depois, a subquery não
    # acharia mais as linhas-pai para casar.
    _apagar(
        delete(RecorrenciaVigencia).where(
            RecorrenciaVigencia.recorrencia_id.in_(
                select(Recorrencia.id).where(Recorrencia.usuario_id == uid)
            )
        ),
        "recorrencia_vigencias",
    )
    _apagar(delete(Recorrencia).where(Recorrencia.usuario_id == uid), "recorrencias")
    # chat_messages entra na purga: o histórico referencia lançamentos por texto —
    # zerar sem limpá-lo deixa a IA conversando sobre transações que não existem.
    _apagar(delete(ChatMessage).where(ChatMessage.usuario_id == uid), "chat_messages")

    return apagados


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    body: DeleteMeRequest,
    response: Response,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """F-07 / LGPD — exclusão total da conta do próprio usuário autenticado.

    Reautenticação obrigatória (senha atual): um cookie sozinho não pode
    deletar a conta. Apaga TODOS os dados do usuário numa ÚNICA transação
    (tudo ou nada): a purga compartilhada (dados) + o que ela preserva de
    propósito para o reset (categorias, tokens) + a própria conta. A ordem é
    a de _purgar_dados_do_usuario, correta no Postgres real, não só no SQLite.
    Em produção os cascades do T-14 são defesa em profundidade.
    """
    # Reautenticação: senha errada não apaga nada.
    if not verify_password(body.password, current_user.senha_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Senha incorreta.")

    uid = current_user.id

    _purgar_dados_do_usuario(uid, session)
    # O que a purga preserva de propósito (o reset mantém a conta utilizável) e
    # aqui precisa cair junto. Só apontam p/ usuarios — sem ordem entre si.
    session.exec(delete(CategoriaCustomizada).where(CategoriaCustomizada.usuario_id == uid))
    session.exec(delete(RefreshToken).where(RefreshToken.usuario_id == uid))
    session.exec(delete(PasswordResetToken).where(PasswordResetToken.usuario_id == uid))
    session.delete(current_user)
    session.commit()

    # Log de auditoria SEM PII — só id + evento (o timestamp vem do formatter).
    logger.info("conta_excluida usuario_id=%s", uid)

    # Sessão do próprio usuário já cai nos deletes; limpa os cookies na resposta.
    _clear_auth_cookies(response)


@router.post("/reset-data", response_model=ResetDataResponse)
def reset_data(
    body: ResetDataRequest,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """"Começar do zero" — zera os LANÇAMENTOS, mantém a conta.

    Reautenticação obrigatória (é irreversível, mesmo padrão do delete_me).
    Reset TOTAL, nunca seletivo: com `transacoes.cartao_id`/`parcelas.cartao_id`
    em NO ACTION, cada combinação seletiva abre um estado inconsistente
    diferente (ver _purgar_dados_do_usuario).

    PRESERVA o usuario_id (nunca deletar+recriar: o id novo quebraria tudo que o
    assume), as categorias customizadas (o usuário quer zerar os lançamentos, não
    reconstruir a taxonomia dele) e os tokens — o usuário CONTINUA LOGADO, então
    os cookies não são limpos.

    UM único commit: erro no meio faz rollback e nada é apagado. Commit em etapas
    deixaria estado parcial (usuário sem transações, mas com cartões).
    """
    if not verify_password(body.password, current_user.senha_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Senha incorreta.")

    apagados = _purgar_dados_do_usuario(current_user.id, session)
    session.commit()

    # Log de auditoria SEM PII — só id + evento.
    logger.info("dados_resetados usuario_id=%s", current_user.id)

    return ResetDataResponse(**apagados)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    response: Response,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Sair de TODOS os dispositivos — revoga todas as sessões do usuário.

    Limpa os cookies desta sessão também: revoke_all_refresh_tokens revoga
    TAMBÉM o refresh deste dispositivo, então manter o cookie deixaria o cliente
    segurando um token já morto, que falharia no próximo refresh — um limbo. Sai
    daqui junto: "você saiu; entre de novo".

    ATENÇÃO ao texto na UI — o rótulo é LITERAL: "Sair de todos os
    dispositivos", este INCLUÍDO. O que precisa de ressalva é o prazo dos
    outros: o access token é JWT stateless (vive até
    ACCESS_TOKEN_EXPIRE_MINUTES), então eles seguem funcionando até ele expirar
    — expulsão instantânea exigiria checar revogação a cada request. Redação:
    "Você sairá de todos os dispositivos, incluindo este. Outros dispositivos
    podem levar até 30 minutos."
    """
    revoke_all_refresh_tokens(current_user.id, session)
    session.commit()
    _clear_auth_cookies(response)


@router.put("/password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not verify_password(body.senha_atual, current_user.senha_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta.")

    current_user.senha_hash = hash_password(body.nova_senha)
    session.add(current_user)
    # F-10: troca de senha revoga todas as sessões na MESMA transação.
    revoke_all_refresh_tokens(current_user.id, session)
    session.commit()


@router.post("/forgot-password", status_code=200)
@limiter.limit("5/minute")  # F-04: por IP — trava enumeração/spam de e-mail
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    user = session.exec(select(Usuario).where(Usuario.email == body.email)).first()

    if user:
        token_str = str(uuid.uuid4())
        reset_token = PasswordResetToken(
            usuario_id=user.id,
            token=hash_token(token_str),  # F-24: persiste o hash; o cru vai no e-mail
            expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=15),
        )
        session.add(reset_token)
        # F-18/T-31: commitar o token ANTES do envio — a falha de e-mail não pode
        # impedir que o reset fique disponível.
        session.commit()

        try:
            resend.Emails.send({
                "from": settings.EMAIL_FROM,
                "to": [user.email],
                "subject": "Recuperação de senha — Hivvo",
                "html": (
                    f"<p>Olá, {user.nome_completo}!</p>"
                    f"<p>Clique no link abaixo para redefinir sua senha. "
                    f"O link expira em <strong>15 minutos</strong>.</p>"
                    f"<p><a href='{settings.FRONTEND_URL}/reset-password?token={token_str}'>"
                    f"Redefinir senha</a></p>"
                    f"<p>Se você não solicitou a recuperação, ignore este e-mail.</p>"
                ),
            })
        except Exception as e:
            # F-18: nunca derruba o request com 500; erro só no log (sem token/PII).
            # #39: o erro do Resend ECOA o endereço do destinatário, e ele vem no
            # COMEÇO da mensagem — truncar não alcança isso, só o padrão EMAIL do
            # scrub do Sentry alcança. Aqui limitamos o tamanho e damos a classe,
            # que é o que separa "chave inválida" de "endereço recusado"; a
            # redação do endereço é a camada de baixo, não esta.
            logger.error(
                "Falha ao enviar e-mail de recuperação de senha: %s: %s",
                e.__class__.__name__, curto(e),
            )

    return {"message": "Se o e-mail estiver cadastrado, você receberá um link em breve."}


@router.post("/reset-password", status_code=204)
def reset_password(body: ResetPasswordRequest, session: Session = Depends(get_session)):
    reset_token = session.exec(
        select(PasswordResetToken).where(PasswordResetToken.token == hash_token(body.token))
    ).first()

    if reset_token is None:
        raise HTTPException(status_code=404, detail="Token inválido.")

    if reset_token.usado:
        raise HTTPException(status_code=400, detail="Token já utilizado.")

    if reset_token.expires_at < dt.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token expirado.")

    user = session.get(Usuario, reset_token.usuario_id)
    user.senha_hash = hash_password(body.nova_senha)
    reset_token.usado = True
    session.add(user)
    session.add(reset_token)
    # F-10: reset de senha revoga todas as sessões na MESMA transação.
    revoke_all_refresh_tokens(user.id, session)
    session.commit()
