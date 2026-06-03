import datetime as dt
import re
import uuid
from typing import Optional

import resend
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    rotate_refresh_token,
    verify_password,
)
from app.core.config import settings
from app.core.database import get_session
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import Usuario
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UpdateMeRequest,
    UserResponse,
)

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


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_ACCESS,
        value=token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_REFRESH,
        value=token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, response: Response, session: Session = Depends(get_session)):
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
def login(body: LoginRequest, response: Response, session: Session = Depends(get_session)):
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
            select(RefreshToken).where(RefreshToken.token == refresh_token)
        ).first()
        if token_record and not token_record.revogado:
            token_record.revogado = True
            session.add(token_record)
            session.commit()

    response.delete_cookie(_COOKIE_ACCESS)
    response.delete_cookie(_COOKIE_REFRESH)


@router.get("/me", response_model=UserResponse)
def me(current_user: Usuario = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.put("/me", response_model=UserResponse)
def update_me(
    body: UpdateMeRequest,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    existing = session.exec(
        select(Usuario).where(
            Usuario.username == body.username,
            Usuario.id != current_user.id
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username já em uso.")

    current_user.username = body.username
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return UserResponse.model_validate(current_user)


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
    session.commit()


@router.post("/forgot-password", status_code=200)
def forgot_password(body: ForgotPasswordRequest, session: Session = Depends(get_session)):
    user = session.exec(select(Usuario).where(Usuario.email == body.email)).first()

    if user:
        token_str = str(uuid.uuid4())
        reset_token = PasswordResetToken(
            usuario_id=user.id,
            token=token_str,
            expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=15),
        )
        session.add(reset_token)

        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": "Hivvo <onboarding@resend.dev>",
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

        session.commit()

    return {"message": "Se o e-mail estiver cadastrado, você receberá um link em breve."}


@router.post("/reset-password", status_code=204)
def reset_password(body: ResetPasswordRequest, session: Session = Depends(get_session)):
    reset_token = session.exec(
        select(PasswordResetToken).where(PasswordResetToken.token == body.token)
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
    session.commit()
