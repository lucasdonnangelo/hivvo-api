"""F-03 — reforço de CSRF por checagem de header Origin nos endpoints mutáveis.

Complementa a defesa primária (cookie `SameSite=Lax`): num POST/PUT/DELETE, se
o header `Origin` estiver presente e não bater com a origem do frontend
(`settings.FRONTEND_URL` — env-conditional: dev=localhost, prod=app.hivvo.app),
a requisição é rejeitada. `Origin` ausente (clientes não-browser) passa e cai na
proteção SameSite do cookie — por isso não trava dev nem chamadas server-to-server.

⚠️ INVARIANTE DE SEGURANÇA (não quebrar): deixar passar o `Origin` AUSENTE só é
seguro enquanto os cookies de auth forem `SameSite=Lax` (ou Strict) E a topologia
for same-site (`app.`/`api.hivvo.app` compartilham o site `hivvo.app`; SameSite é
escopado por site, não por origin). Nesse arranjo, um POST/PUT/DELETE cross-site
(o vetor de CSRF) NÃO carrega os cookies → chega sem sessão → 401, com ou sem
`Origin`. Se algum dia os cookies virarem `SameSite=None` (necessário só se o
deploy deixar de ser same-site), o browser passa a mandar os cookies cross-site e
este "passa sem Origin" VIRA um buraco de CSRF — nesse caso, endurecer aqui para
REJEITAR também o `Origin` ausente (ou adotar CSRF token double-submit). Ver o
item correspondente no CHECKLIST DE DEPLOY (documentação operacional privada).
"""

from fastapi import HTTPException, Request, status

from app.core.config import settings

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def allowed_origins() -> set[str]:
    # Origem explícita do frontend, dirigida por settings (env-conditional).
    return {settings.FRONTEND_URL}


def verify_origin(request: Request) -> None:
    if request.method not in _MUTATING_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in allowed_origins():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin não permitido",
        )
