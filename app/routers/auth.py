import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from app.core.auth import create_access_token, get_current_user, hash_password, verify_password
from app.core.config import settings
from app.core.database import get_session
from app.models.user import Usuario
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_MAX_TENTATIVAS = 5
_BLOQUEIO_MINUTOS = 15
_COOKIE_NAME = "access_token"


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, response: Response, session: Session = Depends(get_session)):
    if session.exec(select(Usuario).where(Usuario.email == body.email)).first():
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")
    if session.exec(select(Usuario).where(Usuario.username == body.username)).first():
        raise HTTPException(status_code=400, detail="Username já em uso")

    user = Usuario(
        email=body.email,
        username=body.username,
        nome_completo=body.nome_completo,
        senha_hash=hash_password(body.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    _set_auth_cookie(response, create_access_token(user.id))
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse)
def login(body: LoginRequest, response: Response, session: Session = Depends(get_session)):
    user = session.exec(select(Usuario).where(Usuario.email == body.email)).first()

    if user is None:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    if not user.ativo:
        raise HTTPException(status_code=403, detail="Conta desativada")

    # Rate limiting
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
    session.commit()
    session.refresh(user)

    _set_auth_cookie(response, create_access_token(user.id))
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(_COOKIE_NAME)


@router.get("/me", response_model=UserResponse)
def me(current_user: Usuario = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
