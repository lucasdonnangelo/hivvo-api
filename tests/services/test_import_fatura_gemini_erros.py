"""#38 — cada CAUSA de falha do Gemini tem mensagem e log próprios.

Antes, seis falhas distintas (quota, entrada rejeitada, credencial, 5xx, timeout
e o desconhecido) devolviam a MESMA string e logavam só a classe da exceção —
indistinguíveis em produção. Estes testes travam o mapeamento classe → mensagem.

O contrato de STATUS não mudou: tudo segue 503 (ver test_todos_os_caminhos_...).
Se algum dia 429/400 ganharem status próprio, é ESTE arquivo que tem que falhar.

Sem rede: `_get_client` é trocado por um fake que levanta a exceção do caso.
`time.sleep` é neutralizado para o retry de 5xx não custar segundos reais.

VERIFICAÇÃO POR MUTAÇÃO — os três testes marcados com «MUTAÇÃO» foram conferidos
removendo o handler correspondente do módulo e vendo o teste FALHAR:
  1. remover o branch `code == 429`      -> test_429_...quota falha
  2. remover o `except (httpx.Timeout...)` -> test_read_timeout_... falha
  3. remover o try/except de _log_telemetria -> test_telemetria_nunca_derruba... falha
"""

import logging

import httpx
import pytest
from fastapi import HTTPException
from google.genai import errors as genai_errors

import app.services.import_fatura.gemini as gemini


# --- Fakes -----------------------------------------------------------------


def _client_que_levanta(exc: BaseException, contador: dict | None = None):
    """Client fake cujo generate_content sempre levanta `exc`."""

    class _Models:
        def generate_content(self, **kwargs):
            if contador is not None:
                contador["n"] = contador.get("n", 0) + 1
            raise exc

    class _Client:
        models = _Models()

    return _Client()


def _client_que_devolve(resposta):
    class _Models:
        def generate_content(self, **kwargs):
            return resposta

    class _Client:
        models = _Models()

    return _Client()


def _erro_cliente(code: int, status: str, message: str = "detalhe da API", details=None):
    """ClientError REAL (não um dublê): passa pelo __init__ do SDK, então
    `code`/`status`/`message` são derivados como em produção."""
    corpo = {"error": {"code": code, "status": status, "message": message}}
    if details is not None:
        corpo["error"]["details"] = details
    return genai_errors.ClientError(code, corpo, None)


class _FakeServerError(genai_errors.ServerError):
    """Mesmo padrão de tests/routers/test_ai_resiliencia.py: evita o __init__
    real (exige response) — mas com code/status, que é o que o batch loga."""

    def __init__(self, code=503, status="UNAVAILABLE", message="upstream caiu"):
        self.code = code
        self.status = status
        self.message = message


@pytest.fixture()
def sem_sleep(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda *_: None)


def _extrair(monkeypatch, client) -> HTTPException:
    """Roda extrair_fatura com o client fake e devolve a HTTPException."""
    monkeypatch.setattr(gemini, "_get_client", lambda: client)
    with pytest.raises(HTTPException) as exc:
        gemini.extrair_fatura("texto redigido da fatura")
    return exc.value


# --- Mapeamento causa -> mensagem ------------------------------------------


class TestMensagemPorCausa:
    def test_429_devolve_mensagem_de_quota(self, monkeypatch, sem_sleep):
        """«MUTAÇÃO» — sem o branch 429, cai no genérico e a mensagem some."""
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(429, "RESOURCE_EXHAUSTED")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_QUOTA
        assert "Limite de uso" in erro.detail
        # A regressão que importa: quota NÃO pode se passar por indisponibilidade.
        assert erro.detail != gemini._MSG_INDISPONIVEL

    def test_400_devolve_mensagem_de_entrada_rejeitada(self, monkeypatch, sem_sleep):
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(400, "INVALID_ARGUMENT")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_ENTRADA
        assert erro.detail != gemini._MSG_INDISPONIVEL

    @pytest.mark.parametrize("code,status", [(401, "UNAUTHENTICATED"), (403, "PERMISSION_DENIED")])
    def test_401_403_devolvem_mensagem_de_credencial(self, monkeypatch, sem_sleep, code, status):
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(code, status)))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_CREDENCIAL
        # Credencial errada não melhora com o tempo — a mensagem não pode
        # mandar o usuário tentar de novo em instantes.
        assert "instantes" not in erro.detail

    def test_4xx_nao_mapeado_cai_na_mensagem_generica(self, monkeypatch, sem_sleep):
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(404, "NOT_FOUND")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_INDISPONIVEL

    def test_server_error_preserva_a_mensagem_atual(self, monkeypatch, sem_sleep):
        """5xx é o ÚNICO caso em que 'tente novamente em instantes' é verdade —
        a string é contrato com o front e não pode mudar neste batch."""
        erro = _extrair(monkeypatch, _client_que_levanta(_FakeServerError()))
        assert erro.status_code == 503
        assert erro.detail == (
            "Serviço de importação temporariamente indisponível. "
            "Tente novamente em instantes."
        )

    def test_deadline_exceeded_devolve_mensagem_de_timeout(self, monkeypatch, sem_sleep):
        """5xx com DEADLINE_EXCEEDED é um timeout — o servidor bateu no
        X-Server-Timeout derivado do NOSSO limite. Reusa a mensagem do timeout de
        rede em vez de mandar "tente em instantes": a causa é a mesma que o
        usuário percebe, e o retry dela saiu (ver test_import_gemini_generation)."""
        erro = _extrair(
            monkeypatch,
            _client_que_levanta(_FakeServerError(code=504, status="DEADLINE_EXCEEDED")),
        )
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_TIMEOUT
        assert erro.detail != gemini._MSG_INDISPONIVEL

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("read timeout"),
            httpx.ConnectTimeout("connect timeout"),
            httpx.ConnectError("connection refused"),
        ],
        ids=["read_timeout", "connect_timeout", "connect_error"],
    )
    def test_read_timeout_devolve_mensagem_de_timeout(self, monkeypatch, sem_sleep, exc):
        """«MUTAÇÃO» — sem o handler de httpx, isto cai no `except Exception`."""
        erro = _extrair(monkeypatch, _client_que_levanta(exc))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_TIMEOUT
        assert erro.detail != gemini._MSG_INDISPONIVEL

    def test_excecao_desconhecida_cai_na_rede_de_seguranca(self, monkeypatch, sem_sleep):
        erro = _extrair(monkeypatch, _client_que_levanta(RuntimeError("algo novo")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_INDISPONIVEL

    def test_todos_os_caminhos_mantem_503(self, monkeypatch, sem_sleep):
        """Trava explícita do contrato: este batch mudou TEXTO, não STATUS.
        Se um dia 429 virar 429 (o que seria certo), este teste falha de
        propósito — a mudança é de contrato e precisa ser deliberada."""
        casos = [
            _erro_cliente(429, "RESOURCE_EXHAUSTED"),
            _erro_cliente(400, "INVALID_ARGUMENT"),
            _erro_cliente(401, "UNAUTHENTICATED"),
            _erro_cliente(403, "PERMISSION_DENIED"),
            _erro_cliente(404, "NOT_FOUND"),
            _FakeServerError(),
            _FakeServerError(code=504, status="DEADLINE_EXCEEDED"),
            httpx.ReadTimeout("x"),
            httpx.ConnectError("x"),
            RuntimeError("x"),
        ]
        for exc in casos:
            erro = _extrair(monkeypatch, _client_que_levanta(exc))
            assert erro.status_code == 503, f"{type(exc).__name__} mudou de status"

    def test_mensagens_sao_todas_distintas(self):
        """O ponto do batch: uma string por causa. Duas iguais reabrem o balde."""
        msgs = [
            gemini._MSG_INDISPONIVEL,
            gemini._MSG_QUOTA,
            gemini._MSG_ENTRADA,
            gemini._MSG_CREDENCIAL,
            gemini._MSG_TIMEOUT,
        ]
        assert len(set(msgs)) == len(msgs)


# --- Log: o que distingue cada causa ---------------------------------------


class TestLog:
    def test_429_loga_o_retry_delay_do_header(self, monkeypatch, sem_sleep, caplog):
        erro = _erro_cliente(429, "RESOURCE_EXHAUSTED")
        erro.response = httpx.Response(429, headers={"retry-after": "42"})
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(erro))
        assert "retry_delay_pedido=42" in caplog.text

    def test_429_loga_o_retry_delay_do_retryinfo(self, monkeypatch, sem_sleep, caplog):
        """A Gemini costuma mandar o delay em error.details[].retryDelay, não no
        header — a segunda fonte não é redundância, é o caso comum."""
        erro = _erro_cliente(
            429, "RESOURCE_EXHAUSTED",
            details=[{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "39s"}],
        )
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(erro))
        assert "retry_delay_pedido=39s" in caplog.text

    def test_429_sem_retry_delay_nao_quebra(self, monkeypatch, sem_sleep, caplog):
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(_erro_cliente(429, "RESOURCE_EXHAUSTED")))
        assert "retry_delay_pedido=None" in caplog.text

    def test_400_loga_code_status_e_mensagem_da_api(self, monkeypatch, sem_sleep, caplog):
        erro = _erro_cliente(400, "INVALID_ARGUMENT", message="token count exceeds the maximum")
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(erro))
        assert "status=INVALID_ARGUMENT" in caplog.text
        assert "token count exceeds the maximum" in caplog.text

    def test_mensagem_da_api_e_truncada(self, monkeypatch, sem_sleep, caplog):
        """A LoggingIntegration do Sentry manda a string do log como evento —
        o teto é o que sai do servidor, não estética de terminal."""
        erro = _erro_cliente(400, "INVALID_ARGUMENT", message="x" * 5000)
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(erro))
        assert "…[truncado]" in caplog.text
        assert "x" * (gemini._MAX_MSG_API + 1) not in caplog.text

    def test_log_nunca_carrega_o_texto_da_fatura(self, monkeypatch, sem_sleep, caplog):
        """Invariante do módulo: o conteúdo da fatura não vai para log — e agora
        também não vai para o Sentry via breadcrumb/evento."""
        segredo = "COMPRA SUPERMERCADO XPTO 1234"
        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_levanta(RuntimeError("boom")))
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(HTTPException):
                gemini.extrair_fatura(segredo)
        assert segredo not in caplog.text

    def test_server_error_loga_status_por_tentativa(self, monkeypatch, sem_sleep, caplog):
        """DEADLINE_EXCEEDED vs UNAVAILABLE pedem correções OPOSTAS — o status
        tem que aparecer, e em CADA tentativa (a 1ª só ia para warning sem ele).

        UNAVAILABLE, não DEADLINE_EXCEEDED: o status agora DECIDE o retry, e o
        DEADLINE sai dele na 1ª tentativa (uma linha só). Quem trava esse
        comportamento é tests/services/test_import_gemini_generation.py; aqui o
        que interessa é "o status aparece em toda tentativa que existir"."""
        with caplog.at_level(logging.DEBUG, logger=gemini.logger.name):
            _extrair(
                monkeypatch,
                _client_que_levanta(_FakeServerError(code=503, status="UNAVAILABLE")),
            )
        assert caplog.text.count("status=UNAVAILABLE") == (
            len(gemini.settings.GEMINI_RETRY_WAITS) + 1
        )
        assert "code=503" in caplog.text
        assert "decorrido=" in caplog.text

    def test_desconhecida_loga_repr_e_traceback(self, monkeypatch, sem_sleep, caplog):
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(RuntimeError("causa nova")))
        assert "RuntimeError('causa nova')" in caplog.text  # repr, não só a classe
        assert "Traceback" in caplog.text


# --- Retry: 5xx sim, 4xx não -----------------------------------------------


class TestRetry:
    def test_server_error_usa_o_orcamento_atual(self, monkeypatch, sem_sleep):
        contador: dict = {}
        _extrair(monkeypatch, _client_que_levanta(_FakeServerError(), contador))
        assert contador["n"] == len(gemini.settings.GEMINI_RETRY_WAITS) + 1

    @pytest.mark.parametrize("code", [429, 400, 401, 403])
    def test_4xx_nao_e_retentado(self, monkeypatch, sem_sleep, code):
        """Inclusive o 429: decisão explícita do batch — o usuário está
        esperando a request e a Gemini pede dezenas de segundos."""
        contador: dict = {}
        _extrair(
            monkeypatch,
            _client_que_levanta(_erro_cliente(code, "STATUS"), contador),
        )
        assert contador["n"] == 1


# --- Telemetria ------------------------------------------------------------


class _Uso:
    prompt_token_count = 41234
    candidates_token_count = 8000
    thoughts_token_count = 1500
    total_token_count = 50734


class _Parte:
    def __init__(self, thought=False, text="{}"):
        self.thought = thought
        self.text = text


class _Conteudo:
    def __init__(self, parts):
        self.parts = parts


class _Candidato:
    def __init__(self, finish_reason="STOP", parts=None):
        self.finish_reason = finish_reason
        self.content = _Conteudo(parts if parts is not None else [_Parte()])


class _Resposta:
    def __init__(self, text="{}", finish_reason="STOP", parts=None):
        self.text = text
        self.candidates = [_Candidato(finish_reason, parts)]
        self.usage_metadata = _Uso()


class TestTelemetria:
    def test_loga_finish_reason_parts_e_usage_no_sucesso(self, monkeypatch, caplog):
        resposta = _Resposta(parts=[_Parte(thought=True, text="pensando"), _Parte()])
        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_devolve(resposta))

        with caplog.at_level(logging.INFO, logger=gemini.logger.name):
            assert gemini.extrair_fatura("texto") == "{}"

        assert "finish_reason=STOP" in caplog.text
        assert "parts=2 thought=1 texto=1" in caplog.text
        assert "prompt_tokens=41234" in caplog.text
        assert "candidates_tokens=8000" in caplog.text
        assert "thoughts_tokens=1500" in caplog.text
        assert "total_tokens=50734" in caplog.text

    def test_loga_max_tokens_quando_a_resposta_vem_truncada(self, monkeypatch, caplog):
        """O caso que motivou o batch: truncamento vira 502 no router e era
        indistinguível de JSON malformado. Agora o finish_reason está no log."""
        resposta = _Resposta(text='{"transacoes": [', finish_reason="MAX_TOKENS")
        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_devolve(resposta))
        with caplog.at_level(logging.INFO, logger=gemini.logger.name):
            gemini.extrair_fatura("texto")
        assert "finish_reason=MAX_TOKENS" in caplog.text

    def test_telemetria_nunca_derruba_a_extracao(self, monkeypatch, caplog):
        """«MUTAÇÃO» — sem o try/except em _log_telemetria, a exceção sobe até o
        `except Exception` do chamador (o return mora DENTRO do try) e uma
        extração BEM-SUCEDIDA vira 503."""

        class _RespostaHostil:
            # `candidates` deixa de ser sequência: candidatos[0] levanta
            # TypeError. É a falha REALISTA (mudança de shape do SDK) — note que
            # um AttributeError NÃO serviria aqui: o `getattr(..., None)` da
            # telemetria o absorve por definição, e o guard nem seria exercido.
            text = '{"ok": true}'
            usage_metadata = None
            candidates = object()

        monkeypatch.setattr(
            gemini, "_get_client", lambda: _client_que_devolve(_RespostaHostil())
        )
        with caplog.at_level(logging.WARNING, logger=gemini.logger.name):
            # O contrato: devolve o texto normalmente, NÃO levanta.
            assert gemini.extrair_fatura("texto") == '{"ok": true}'

        # E a falha do guard não é silenciosa (decisão: warning + exc_info,
        # nunca `pass` — senão o guard vira o novo ponto cego).
        assert "telemetria" in caplog.text
        assert "Traceback" in caplog.text

    def test_telemetria_aguenta_resposta_sem_candidates(self, monkeypatch, caplog):
        class _Vazia:
            text = None
            candidates = []
            usage_metadata = None

        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_devolve(_Vazia()))
        with caplog.at_level(logging.INFO, logger=gemini.logger.name):
            assert gemini.extrair_fatura("texto") == ""  # o `or ""` de produção
        assert "candidates=0" in caplog.text
        assert "Traceback" not in caplog.text  # caminho normal, não o guard
