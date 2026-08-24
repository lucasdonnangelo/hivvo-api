"""T-28 — hard switch: rotas de negócio sob /api/v1, /health na RAIZ.

Guarda a topologia de roteamento sem depender de DB/auth:
- toda rota de negócio começa com /api/v1;
- /health continua na raiz (health check do load balancer) e NÃO sob /api/v1;
- a rota antiga na raiz responde 404 (não há dual-mount), enquanto a mesma
  rota sob /api/v1 existe (401 sem token — não 404).

Os dois primeiros leem o SCHEMA OpenAPI; o terceiro exercita o roteamento de
verdade via TestClient. Nenhum deles lê `app.routes` — o porquê está em
_paths_publicados().
"""

from fastapi.testclient import TestClient

from main import app

# /health é a ÚNICA rota fora do prefixo de negócio que o schema publica: as
# utilitárias (/docs, /redoc, /openapi.json, /docs/oauth2-redirect) nascem com
# include_in_schema=False e por isso nem aparecem em app.openapi(). Enquanto
# esta lista era filtrada contra app.routes, ela precisava nomear as quatro.
_ROTAS_FORA_DO_PREFIXO = {"/health"}


def _paths_publicados() -> set[str]:
    """Os paths do contrato OpenAPI do app.

    Duas decisões aqui, cada uma com um motivo — não "simplifique" nenhuma:

    1. LER O SCHEMA, NÃO `app.routes`. `app.routes` é estrutura INTERNA do
       FastAPI e muda entre versões. Até a 0.136 o `include_router` achatava as
       sub-rotas ali dentro (64 objetos, todos com `.path` real); da 0.141 em
       diante ele anexa um `_IncludedRouter` por router incluído, com
       `path=None` e sem expor `.routes` (18 objetos, 13 deles opacos). O
       ROTEAMENTO não mudou — só a introspecção. Foi assim que este arquivo
       ficou vermelho no CI enquanto passava na máquina do dev, que ainda tinha
       a versão antiga instalada. O schema OpenAPI é contrato público e
       versionado: os mesmos 48 paths e 60 operações nas DUAS versões, diff
       byte a byte vazio.

    2. CHAMAR `app.openapi()` DIRETO, nunca `GET /openapi.json` via TestClient.
       main.py faz `openapi_url=None if _IS_PRODUCTION else "/openapi.json"`:
       em produção o ENDPOINT não existe e uma chamada HTTP tomaria 404. O
       MÉTODO não some — monta o schema a partir das rotas de qualquer jeito.
    """
    return set(app.openapi()["paths"])


def _rotas_de_negocio():
    for path in sorted(_paths_publicados()):
        if path in _ROTAS_FORA_DO_PREFIXO:
            continue
        yield path


def test_toda_rota_de_negocio_esta_sob_api_v1():
    rotas = list(_rotas_de_negocio())
    assert rotas, "esperava rotas de negócio publicadas no schema"
    fora = [p for p in rotas if not p.startswith("/api/v1")]
    assert fora == [], f"rotas de negócio fora de /api/v1: {fora}"


def test_health_permanece_na_raiz():
    paths = _paths_publicados()
    assert "/health" in paths
    assert "/api/v1/health" not in paths


def test_hard_switch_rota_antiga_404_e_nova_existe():
    client = TestClient(app)
    # raiz antiga não está mais montada -> 404 (não há dual-mount)
    assert client.get("/auth/me").status_code == 404
    # sob /api/v1 a rota existe: sem token o guard de auth responde 401, não 404
    assert client.get("/api/v1/auth/me").status_code == 401
