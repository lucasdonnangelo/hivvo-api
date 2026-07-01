"""API Batch 11b — cookies same-site (F-03) + token 30min (F-09).

Unidades sem rede: atributos de cookie condicionados por ambiente, checagem de
Origin (reforço CSRF) e os tempos de expiração dos tokens. O comportamento
same-site/refresh de fato só se valida no domínio real (deploy) — aqui garante-se
a lógica env-conditional e que dev não é afetado.
"""

import datetime as dt

import pytest
from fastapi import HTTPException, Response
from jose import jwt
from sqlmodel import select
from starlette.requests import Request

from app.core.auth import create_access_token, create_refresh_token
from app.core.config import Settings, settings
from app.core.csrf import verify_origin
from app.models.refresh_token import RefreshToken
from app.routers.auth import _clear_auth_cookies, _set_auth_cookie, _set_refresh_cookie


def _set_cookie_header(monkeypatch, environment: str) -> str:
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    resp = Response()
    _set_auth_cookie(resp, "tok-abc")
    return resp.headers["set-cookie"].lower()


# --------------------------------------------------------------------------- #
# F-03 — atributos de cookie por ambiente                                     #
# --------------------------------------------------------------------------- #
class TestCookieAtributos:
    def test_producao_tem_domain_secure_samesite_httponly(self, monkeypatch):
        cookie = _set_cookie_header(monkeypatch, "production")
        assert "domain=.hivvo.app" in cookie
        assert "secure" in cookie
        assert "samesite=lax" in cookie
        assert "httponly" in cookie

    def test_dev_sem_domain_sem_secure_mas_samesite_httponly(self, monkeypatch):
        cookie = _set_cookie_header(monkeypatch, "development")
        assert "domain=" not in cookie
        assert "secure" not in cookie
        assert "samesite=lax" in cookie
        assert "httponly" in cookie

    def test_refresh_cookie_segue_o_mesmo_padrao(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        resp = Response()
        _set_refresh_cookie(resp, "refresh-abc")
        cookie = resp.headers["set-cookie"].lower()
        assert "domain=.hivvo.app" in cookie and "secure" in cookie and "samesite=lax" in cookie

    def test_clear_em_producao_leva_domain(self, monkeypatch):
        # A limpeza precisa dos MESMOS atributos, senão o browser não casa o cookie.
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        resp = Response()
        _clear_auth_cookies(resp)
        cookies = "; ".join(resp.headers.getlist("set-cookie")).lower()
        assert cookies.count("domain=.hivvo.app") == 2  # access + refresh


# --------------------------------------------------------------------------- #
# F-03 — reforço de CSRF via Origin                                           #
# --------------------------------------------------------------------------- #
def _make_request(method: str, origin: str | None = None) -> Request:
    headers = [(b"origin", origin.encode())] if origin is not None else []
    return Request({"type": "http", "method": method, "headers": headers})


class TestVerifyOrigin:
    def test_get_nao_e_checado(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
        # GET com Origin alheio passa — método seguro não sofre CSRF.
        assert verify_origin(_make_request("GET", "https://evil.example")) is None

    def test_mutavel_origin_invalido_rejeita(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
        with pytest.raises(HTTPException) as exc:
            verify_origin(_make_request("POST", "https://evil.example"))
        assert exc.value.status_code == 403

    def test_mutavel_origin_dev_passa(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
        assert verify_origin(_make_request("DELETE", "http://localhost:5173")) is None

    def test_mutavel_origin_prod_passa(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.hivvo.app")
        assert verify_origin(_make_request("PUT", "https://app.hivvo.app")) is None

    def test_mutavel_sem_origin_passa(self, monkeypatch):
        # Cliente não-browser: sem Origin, cai na proteção SameSite do cookie.
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
        assert verify_origin(_make_request("POST", None)) is None


# --------------------------------------------------------------------------- #
# F-09 — access token curto, refresh longo                                    #
# --------------------------------------------------------------------------- #
class TestTokenExpiry:
    def test_default_access_30_refresh_longo(self):
        s = Settings(_env_file=None, DATABASE_URL="x", SECRET_KEY="y")
        assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 30
        assert s.REFRESH_TOKEN_EXPIRE_DAYS == 7  # dias — sessão longa, não encurtar

    def test_access_token_expira_em_30min(self, monkeypatch):
        monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 30)
        antes = dt.datetime.utcnow()
        token = create_access_token(1)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        exp = dt.datetime.utcfromtimestamp(payload["exp"])
        delta_min = (exp - antes).total_seconds() / 60
        assert 29 <= delta_min <= 31

    def test_refresh_token_mantem_vida_longa(self, session):
        antes = dt.datetime.utcnow()
        create_refresh_token(1, session)
        session.commit()
        rt = session.exec(select(RefreshToken).where(RefreshToken.usuario_id == 1)).first()
        dias = (rt.expires_at - antes).total_seconds() / 86400
        assert dias >= 6  # ~7 dias — muito maior que o access de 30min
