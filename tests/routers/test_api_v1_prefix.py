"""T-28 — hard switch: rotas de negócio sob /api/v1, /health na RAIZ.

Guarda a topologia de roteamento sem depender de DB/auth:
- toda rota de negócio começa com /api/v1;
- /health continua na raiz (health check do load balancer) e NÃO sob /api/v1;
- a rota antiga na raiz responde 404 (não há dual-mount), enquanto a mesma
  rota sob /api/v1 existe (401 sem token — não 404).
"""

from fastapi.testclient import TestClient

from main import app

# Rotas utilitárias que legitimamente vivem fora do prefixo de negócio.
_ROTAS_FORA_DO_PREFIXO = {
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}


def _rotas_de_negocio():
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None or path in _ROTAS_FORA_DO_PREFIXO:
            continue
        yield path


def test_toda_rota_de_negocio_esta_sob_api_v1():
    rotas = list(_rotas_de_negocio())
    assert rotas, "esperava rotas de negócio montadas"
    fora = [p for p in rotas if not p.startswith("/api/v1")]
    assert fora == [], f"rotas de negócio fora de /api/v1: {fora}"


def test_health_permanece_na_raiz():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in paths
    assert "/api/v1/health" not in paths


def test_hard_switch_rota_antiga_404_e_nova_existe():
    client = TestClient(app)
    # raiz antiga não está mais montada -> 404 (não há dual-mount)
    assert client.get("/auth/me").status_code == 404
    # sob /api/v1 a rota existe: sem token o guard de auth responde 401, não 404
    assert client.get("/api/v1/auth/me").status_code == 401
