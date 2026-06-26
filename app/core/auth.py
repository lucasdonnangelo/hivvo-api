import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import get_session


def hash_token(token: str) -> str:
    # F-24: refresh/reset tokens são uuid4 de alta entropia (~122 bits), então
    # SHA-256 sem salt basta e preserva a busca por índice. O valor CRU vai ao
    # cliente; o banco guarda só o hash (criação E lookup precisam casar).
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    # F-23: custo bcrypt explícito (12). Afeta só hashes novos — verify lê o
    # custo do próprio hash, então senhas antigas continuam validando.
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def create_refresh_token(user_id: int, session: Session) -> str:
    from app.models.refresh_token import RefreshToken

    token_str = str(uuid.uuid4())
    token = RefreshToken(
        usuario_id=user_id,
        token=hash_token(token_str),  # F-24: persiste o hash; o cru vai ao cliente
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    session.add(token)
    return token_str


def revoke_all_refresh_tokens(user_id: int, session: Session) -> None:
    # F-10: revoga TODAS as sessões ativas do usuário (troca/reset de senha).
    # O chamador commita — fica na mesma transação da troca de senha.
    from app.models.refresh_token import RefreshToken

    tokens = session.exec(
        select(RefreshToken).where(
            RefreshToken.usuario_id == user_id,
            RefreshToken.revogado == False,  # noqa: E712 — comparação SQL
        )
    ).all()
    for token in tokens:
        token.revogado = True
        session.add(token)


def rotate_refresh_token(old_token_str: str, session: Session) -> tuple[int, str]:
    from app.models.refresh_token import RefreshToken

    token = session.exec(
        select(RefreshToken).where(RefreshToken.token == hash_token(old_token_str))
    ).first()

    if token is None or token.revogado or token.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido ou expirado",
        )

    token.revogado = True
    session.add(token)

    new_token_str = create_refresh_token(token.usuario_id, session)
    return token.usuario_id, new_token_str


def get_current_user(
    access_token: Optional[str] = Cookie(default=None),
    session: Session = Depends(get_session),
):
    from app.models.user import Usuario

    if access_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")

    try:
        payload = jwt.decode(access_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise JWTError()
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    user = session.get(Usuario, int(user_id))
    if user is None or not user.ativo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inativo ou não encontrado")

    return user
