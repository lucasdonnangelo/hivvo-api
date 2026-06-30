"""Rate limiting (F-04) com slowapi.

Camada COMPLEMENTAR ao lockout por conta já existente (tentativas_login/
bloqueado_ate em auth.py) — não o substitui. Limites por IP nas rotas de auth e,
em /ai/chat, por usuário + por IP + cota diária (chamada de IA tem custo).

⚠️ LIMITAÇÃO CONHECIDA: o store é em MEMÓRIA do processo — NÃO sobrevive a
múltiplas instâncias. Ao escalar horizontalmente em produção, migrar para Redis
(storage_uri="redis://...") para o limite ser global entre réplicas.
"""

from fastapi import Request
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _user_or_ip_key(request: Request) -> str:
    """Chave por usuário autenticado (sub do JWT no cookie); fallback para IP.

    Permite limitar /ai/chat por usuário sem depender da resolução de
    dependências do FastAPI (key_func recebe só o request).
    """
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except JWTError:
            pass
    return get_remote_address(request)


limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
    storage_uri="memory://",
)
