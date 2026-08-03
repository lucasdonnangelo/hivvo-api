"""#31 — o extrato tem o MESMO tratamento de erro e a MESMA telemetria da fatura,
porque executa o mesmo código (app/core/gemini_erros), não uma cópia dele.

Até 29/07 este módulo tinha um `except Exception` nu e nenhuma telemetria: seis
causas distintas devolviam a mesma string e o log guardava só a classe da
exceção. Pior, a config de geração dele tinha sido mudada (thinking_budget=1024)
EXTRAPOLANDO de medições feitas na fatura — comportamento alterado num módulo que
não se sabia observar. Estes testes são a metade "observar" desse conserto.

O arquivo espelha a COBERTURA de tests/services/test_import_fatura_gemini_erros.py
(o portão do #31, que passou intocado nesta mudança), com três acréscimos que só
fazem sentido aqui:
  * as 3 mensagens compartilhadas são O MESMO texto da fatura, e as 2 divergentes
    falam de EXTRATO — a regressão real é alguém copiar a string do módulo errado;
  * `categorizar_linhas` (o 2º ponto de chamada do extrato) passa pelo mesmo
    tratamento, porque também passa por `_gerar`;
  * o invariante de PII vale para PII de TERCEIROS, não só do titular.

Sem rede: `_get_client` é trocado por um fake que levanta a exceção do caso.
`time.sleep` é neutralizado para o retry de 5xx não custar segundos reais.

VERIFICAÇÃO POR MUTAÇÃO — os testes marcados com «MUTAÇÃO» foram conferidos com a
saída colada no relato do batch. As duas primeiras são a prova de que o handler é
UM SÓ: a mutação é feita em app/core/gemini_erros.py e cai NOS DOIS módulos.
  1. remover o branch `code == 429` do compartilhado
     -> cai aqui E em test_import_fatura_gemini_erros.py
  2. remover o try/except de `_log_telemetria` no compartilhado
     -> uma extração BEM-SUCEDIDA vira 503, aqui E na fatura
"""

import logging

import httpx
import pytest
from fastapi import HTTPException
from google.genai import errors as genai_errors

import app.services.import_extrato.gemini as gemini
import app.services.import_fatura.gemini as gemini_fatura

_LOTE_VAZIO = '{"itens": []}'


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
    """Mesmo padrão dos outros arquivos: evita o __init__ real (exige response),
    mas com code/status — o status é o que decide o retry."""

    def __init__(self, code=503, status="UNAVAILABLE", message="upstream caiu"):
        self.code = code
        self.status = status
        self.message = message


@pytest.fixture()
def sem_sleep(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda *_: None)


def _extrair(monkeypatch, client) -> HTTPException:
    """Roda extrair_extrato com o client fake e devolve a HTTPException."""
    monkeypatch.setattr(gemini, "_get_client", lambda: client)
    with pytest.raises(HTTPException) as exc:
        gemini.extrair_extrato("texto redigido do extrato")
    return exc.value


def _pedido():
    return gemini.PedidoCategoria(
        indice=0, descricao="Compra no debito PADARIA", valor="50.00", tipo="despesa"
    )


# --- Mapeamento causa -> mensagem ------------------------------------------


class TestMensagemPorCausa:
    def test_429_devolve_mensagem_de_quota(self, monkeypatch, sem_sleep):
        """«MUTAÇÃO» — removendo o branch 429 do módulo COMPARTILHADO, este teste
        e o gêmeo da fatura caem juntos. É a prova de que o handler é um só."""
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(429, "RESOURCE_EXHAUSTED")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MENSAGENS.quota
        assert "Limite de uso" in erro.detail
        # A regressão que importa: quota NÃO pode se passar por indisponibilidade
        # — que era literalmente o que o extrato fazia antes do #31.
        assert erro.detail != gemini._MENSAGENS.indisponivel

    def test_400_devolve_mensagem_de_entrada_rejeitada(self, monkeypatch, sem_sleep):
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(400, "INVALID_ARGUMENT")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_ENTRADA
        assert erro.detail != gemini._MENSAGENS.indisponivel

    @pytest.mark.parametrize("code,status", [(401, "UNAUTHENTICATED"), (403, "PERMISSION_DENIED")])
    def test_401_403_devolvem_mensagem_de_credencial(self, monkeypatch, sem_sleep, code, status):
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(code, status)))
        assert erro.status_code == 503
        assert erro.detail == gemini._MENSAGENS.credencial
        # Credencial errada não melhora com o tempo — a mensagem não pode mandar
        # o usuário tentar de novo em instantes.
        assert "instantes" not in erro.detail

    def test_4xx_nao_mapeado_cai_na_mensagem_generica(self, monkeypatch, sem_sleep):
        erro = _extrair(monkeypatch, _client_que_levanta(_erro_cliente(404, "NOT_FOUND")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MENSAGENS.indisponivel

    def test_server_error_preserva_a_mensagem_atual(self, monkeypatch, sem_sleep):
        """A string que o extrato JÁ devolvia para tudo antes do #31 — e que
        segue sendo a do 5xx. Contrato com o front; não muda neste batch."""
        erro = _extrair(monkeypatch, _client_que_levanta(_FakeServerError()))
        assert erro.status_code == 503
        assert erro.detail == (
            "Serviço de importação temporariamente indisponível. "
            "Tente novamente em instantes."
        )

    def test_deadline_exceeded_devolve_mensagem_de_timeout(self, monkeypatch, sem_sleep):
        """5xx com DEADLINE_EXCEEDED é um timeout — o servidor bateu no
        X-Server-Timeout derivado do NOSSO limite."""
        erro = _extrair(
            monkeypatch,
            _client_que_levanta(_FakeServerError(code=504, status="DEADLINE_EXCEEDED")),
        )
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_TIMEOUT
        assert erro.detail != gemini._MENSAGENS.indisponivel

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("read timeout"),
            httpx.ConnectTimeout("connect timeout"),
            httpx.ConnectError("connection refused"),
        ],
        ids=["read_timeout", "connect_timeout", "connect_error"],
    )
    def test_timeout_de_rede_devolve_mensagem_de_timeout(self, monkeypatch, sem_sleep, exc):
        erro = _extrair(monkeypatch, _client_que_levanta(exc))
        assert erro.status_code == 503
        assert erro.detail == gemini._MSG_TIMEOUT
        assert erro.detail != gemini._MENSAGENS.indisponivel

    def test_excecao_desconhecida_cai_na_rede_de_seguranca(self, monkeypatch, sem_sleep):
        erro = _extrair(monkeypatch, _client_que_levanta(RuntimeError("algo novo")))
        assert erro.status_code == 503
        assert erro.detail == gemini._MENSAGENS.indisponivel

    def test_todos_os_caminhos_mantem_503(self, monkeypatch, sem_sleep):
        """Mesma trava de contrato da fatura: o #31 mudou TEXTO e LOG, não
        STATUS. O dia em que 429/400 ganharem status próprio (#38), é para este
        teste e o gêmeo da fatura falharem juntos — a mudança é deliberada."""
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
        """O ponto do #31 para o extrato: uma string por causa. Antes eram CINCO
        nomes para a MESMA string."""
        m = gemini._MENSAGENS
        msgs = [m.indisponivel, m.quota, m.entrada, m.credencial, m.timeout]
        assert len(set(msgs)) == len(msgs)


# --- Fonte única do TEXTO (o que se compartilha e o que diverge) ------------


class TestTextoCompartilhadoEDivergente:
    def test_as_tres_genericas_sao_identicas_as_da_fatura(self):
        """Elas já falam de "importação", sem nomear o documento — copiar em vez
        de compartilhar é como o safety divergiu no F-06."""
        assert gemini._MENSAGENS.indisponivel == gemini_fatura._MSG_INDISPONIVEL
        assert gemini._MENSAGENS.quota == gemini_fatura._MSG_QUOTA
        assert gemini._MENSAGENS.credencial == gemini_fatura._MSG_CREDENCIAL

    def test_as_duas_especificas_falam_de_extrato_e_nao_de_fatura(self):
        """A regressão realista aqui é humana: copiar a string do módulo vizinho.
        O usuário que importa um extrato não pode ler "esta fatura"."""
        for msg in (gemini._MSG_ENTRADA, gemini._MSG_TIMEOUT):
            assert "extrato" in msg.lower()
            assert "fatura" not in msg.lower()

        assert gemini._MSG_ENTRADA != gemini_fatura._MSG_ENTRADA
        assert gemini._MSG_TIMEOUT != gemini_fatura._MSG_TIMEOUT


# --- Log: o que distingue cada causa ---------------------------------------


class TestLog:
    def test_429_loga_o_retry_delay_do_retryinfo(self, monkeypatch, sem_sleep, caplog):
        """A Gemini costuma mandar o delay em error.details[].retryDelay, não no
        header. É o número que dimensiona a cota — e o extrato não o tinha."""
        erro = _erro_cliente(
            429, "RESOURCE_EXHAUSTED",
            details=[{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "39s"}],
        )
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(erro))
        assert "retry_delay_pedido=39s" in caplog.text

    def test_400_loga_code_status_e_mensagem_da_api(self, monkeypatch, sem_sleep, caplog):
        """A EXCEÇÃO DELIBERADA do #38, agora valendo aqui: sem a `message`, um
        400 é indistinguível de um 429 em produção."""
        erro = _erro_cliente(400, "INVALID_ARGUMENT", message="token count exceeds the maximum")
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(erro))
        assert "status=INVALID_ARGUMENT" in caplog.text
        assert "token count exceeds the maximum" in caplog.text

    def test_mensagem_da_api_e_truncada(self, monkeypatch, sem_sleep, caplog):
        """O teto é o que sai do servidor: o extrato carrega dado de TERCEIRO
        (contraparte de Pix/TED) e a LoggingIntegration do Sentry manda a string
        do log como evento.

        Desde o #39 o `_before_send` varre `logentry`, mas isso NÃO substitui
        este teto: o scrub casa formato conhecido (CPF, e-mail, agência/conta) e
        um eco de payload da API é texto livre, que não tem forma para casar."""
        erro = _erro_cliente(400, "INVALID_ARGUMENT", message="x" * 5000)
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(erro))
        assert "…[truncado]" in caplog.text
        assert "x" * 201 not in caplog.text

    def test_log_nunca_carrega_o_texto_do_extrato(self, monkeypatch, sem_sleep, caplog):
        """Invariante do módulo — e aqui ele protege PII de TERCEIRO, não do
        titular: nome/CPF/agência/conta de quem recebeu o Pix."""
        segredo = "PIX ENVIADO MARIA SOUZA 123.456.789-00 AG 0001 CC 12345-6"
        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_levanta(RuntimeError("boom")))
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(HTTPException):
                gemini.extrair_extrato(segredo)
        assert segredo not in caplog.text
        assert "MARIA SOUZA" not in caplog.text
        assert "123.456.789-00" not in caplog.text

    def test_server_error_loga_status_por_tentativa(self, monkeypatch, sem_sleep, caplog):
        """DEADLINE_EXCEEDED vs UNAVAILABLE pedem correções OPOSTAS. O extrato já
        logava o status; o que ele NÃO tinha era code e decorrido — sem
        `decorrido` não dá para saber se estourou o nosso teto ou morreu antes."""
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

    def test_desconhecida_loga_classe_mensagem_e_traceback(
        self, monkeypatch, sem_sleep, caplog
    ):
        """Era o `except Exception` nu com só a CLASSE — o log que travou o
        diagnóstico do #38 na fatura, e que sobrou aqui até o #31.

        O #39 trocou o `%r` por classe + mensagem TRUNCADA: repr() de exceção
        despeja a tupla de args inteira, e este era o único sink do módulo fora
        do teto do #38. A garantia diagnóstica é a mesma."""
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(RuntimeError("causa nova")))
        assert "RuntimeError" in caplog.text       # a classe
        assert "causa nova" in caplog.text         # e a mensagem, não só a classe
        assert "Traceback" in caplog.text

    def test_desconhecida_tambem_respeita_o_teto(self, monkeypatch, sem_sleep, caplog):
        """O teto do #38 valia só para os handlers MAPEADOS. Este caminho é o
        `except Exception` — onde chega o não previsto, e por isso justamente
        onde uma exceção que carregue corpo de resposta apareceria.

        LIMITE DESTE TETO, que o teste mede de propósito: a asserção é sobre a
        MENSAGEM formatada, não sobre `caplog.text`. `logger.exception` anexa o
        traceback, e o traceback renderiza `RuntimeError: <mensagem inteira>` no
        fim — truncar o format string NÃO alcança o `exc_info`. No Sentry a
        mesma string reaparece em `exception.values[].value`. Quem cobre isso é
        o scrub de `core/observability` (#39), não o truncamento; por isso o
        scrub varre a exceção além do `logentry`."""
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(RuntimeError("x" * 500)))

        [msg] = [r.getMessage() for r in caplog.records if "falha inesperada" in r.getMessage()]
        assert "…[truncado]" in msg
        assert "x" * 201 not in msg

    def test_loga_sob_o_logger_do_extrato_e_nao_do_compartilhado(
        self, monkeypatch, sem_sleep, caplog
    ):
        """O logger vai INJETADO no runner compartilhado. O prefixo "[import]" é
        o mesmo nos dois módulos, então é o NOME do logger que diz qual
        importação falhou — um logger próprio de app.core.gemini_erros apagaria
        essa distinção em produção (e faria as linhas INFO de telemetria
        sumirem sob o nível herdado da raiz)."""
        with caplog.at_level(logging.ERROR, logger=gemini.logger.name):
            _extrair(monkeypatch, _client_que_levanta(_erro_cliente(400, "INVALID_ARGUMENT")))

        nomes = {r.name for r in caplog.records}
        assert nomes == {"app.services.import_extrato.gemini"}


# --- Retry: 5xx sim, 4xx não -----------------------------------------------


class TestRetry:
    def test_server_error_usa_o_orcamento_atual(self, monkeypatch, sem_sleep):
        contador: dict = {}
        _extrair(monkeypatch, _client_que_levanta(_FakeServerError(), contador))
        assert contador["n"] == len(gemini.settings.GEMINI_RETRY_WAITS) + 1

    @pytest.mark.parametrize("code", [429, 400, 401, 403])
    def test_4xx_nao_e_retentado(self, monkeypatch, sem_sleep, code):
        """Inclusive o 429: o usuário está esperando a request e a Gemini pede
        dezenas de segundos."""
        contador: dict = {}
        _extrair(
            monkeypatch,
            _client_que_levanta(_erro_cliente(code, "STATUS"), contador),
        )
        assert contador["n"] == 1


# --- O 2º ponto de chamada do extrato --------------------------------------


class TestCategorizacaoEmLote:
    """`categorizar_linhas` passa pelo mesmo `_gerar`, logo pelo mesmo runner.
    A fatura não tem equivalente — é cobertura que só existe deste lado."""

    def test_erro_de_api_recebe_o_mesmo_tratamento(self, monkeypatch, sem_sleep):
        monkeypatch.setattr(
            gemini, "_get_client",
            lambda: _client_que_levanta(_erro_cliente(429, "RESOURCE_EXHAUSTED")),
        )
        with pytest.raises(HTTPException) as exc:
            gemini.categorizar_linhas([_pedido()], ["Alimentação"], ["Salário"])

        assert exc.value.status_code == 503
        assert exc.value.detail == gemini._MENSAGENS.quota

    def test_4xx_nao_e_retentado_na_categorizacao(self, monkeypatch, sem_sleep):
        contador: dict = {}
        monkeypatch.setattr(
            gemini, "_get_client",
            lambda: _client_que_levanta(_erro_cliente(400, "INVALID_ARGUMENT"), contador),
        )
        with pytest.raises(HTTPException):
            gemini.categorizar_linhas([_pedido()], ["Alimentação"], ["Salário"])
        assert contador["n"] == 1

    def test_log_nao_carrega_a_descricao_da_linha(self, monkeypatch, sem_sleep, caplog):
        """A descrição das linhas vai ao modelo tanto quanto o texto do extrato —
        e carrega o mesmo PII de terceiro."""
        pedido = gemini.PedidoCategoria(
            indice=0, descricao="PIX ENVIADO JOAO DA SILVA", valor="50.00", tipo="despesa"
        )
        monkeypatch.setattr(
            gemini, "_get_client", lambda: _client_que_levanta(RuntimeError("boom"))
        )
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(HTTPException):
                gemini.categorizar_linhas([pedido], ["Alimentação"], ["Salário"])
        assert "JOAO DA SILVA" not in caplog.text

    def test_schema_rejeitado_continua_502_e_nao_vira_503(self, monkeypatch):
        """A validação do lote é do próprio módulo, não do runner: ela não pode
        ser engolida pelo mapeamento 503 do tratamento compartilhado."""
        monkeypatch.setattr(
            gemini, "_get_client", lambda: _client_que_devolve(_Resposta(text='{"itens": "nao"}'))
        )
        with pytest.raises(HTTPException) as exc:
            gemini.categorizar_linhas([_pedido()], ["Alimentação"], ["Salário"])
        assert exc.value.status_code == 502


# --- Telemetria ------------------------------------------------------------
#
# O extrato NÃO tinha nenhuma: a resposta era descartada inteira (só `.text` era
# lido). Era o ponto que tornava perigoso ter mexido no thinking_budget dele por
# extrapolação da fatura — um extrato que precisasse de mais raciocínio
# degradaria em silêncio (MAX_TOKENS -> JSON truncado -> 502 genérico do router)
# em vez de falhar. finish_reason no log é o que separa esses dois casos.


class _Uso:
    prompt_token_count = 21000
    candidates_token_count = 4000
    thoughts_token_count = 927
    total_token_count = 25927


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
            assert gemini.extrair_extrato("texto") == "{}"

        assert "finish_reason=STOP" in caplog.text
        assert "parts=2 thought=1 texto=1" in caplog.text
        assert "prompt_tokens=21000" in caplog.text
        assert "candidates_tokens=4000" in caplog.text
        assert "thoughts_tokens=927" in caplog.text
        assert "total_tokens=25927" in caplog.text

    def test_loga_max_tokens_quando_a_resposta_vem_truncada(self, monkeypatch, caplog):
        """O caso que este batch existe para tornar VISÍVEL: com o thinking
        limitado a 1024 por extrapolação da fatura, um extrato mais complexo
        truncaria — e truncamento vira o mesmo 502 do router que JSON malformado.
        Sem finish_reason no log, os dois são indistinguíveis."""
        resposta = _Resposta(text='{"linhas": [', finish_reason="MAX_TOKENS")
        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_devolve(resposta))
        with caplog.at_level(logging.INFO, logger=gemini.logger.name):
            gemini.extrair_extrato("texto")
        assert "finish_reason=MAX_TOKENS" in caplog.text

    def test_telemetria_da_categorizacao_tambem_e_logada(self, monkeypatch, caplog):
        """As DUAS chamadas do extrato pagam thinking, então as duas precisam ser
        observáveis — a categorização em lote passa pelo mesmo runner."""
        resposta = _Resposta(text=_LOTE_VAZIO)
        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_devolve(resposta))
        with caplog.at_level(logging.INFO, logger=gemini.logger.name):
            gemini.categorizar_linhas([_pedido()], ["Alimentação"], ["Salário"])
        assert "finish_reason=STOP" in caplog.text

    def test_telemetria_nunca_derruba_a_extracao(self, monkeypatch, caplog):
        """«MUTAÇÃO» — sem o try/except de `_log_telemetria` no COMPARTILHADO, a
        exceção sobe até o `except Exception` do runner (o return mora DENTRO do
        try) e uma extração BEM-SUCEDIDA vira 503. A mutação cai aqui e na
        fatura ao mesmo tempo."""

        class _RespostaHostil:
            # `candidates` deixa de ser sequência: candidatos[0] levanta
            # TypeError. É a falha REALISTA (mudança de shape do SDK) — um
            # AttributeError NÃO serviria: o `getattr(..., None)` da telemetria o
            # absorve por definição e o guard nem seria exercido.
            text = '{"ok": true}'
            usage_metadata = None
            candidates = object()

        monkeypatch.setattr(
            gemini, "_get_client", lambda: _client_que_devolve(_RespostaHostil())
        )
        with caplog.at_level(logging.WARNING, logger=gemini.logger.name):
            # O contrato: devolve o texto normalmente, NÃO levanta.
            assert gemini.extrair_extrato("texto") == '{"ok": true}'

        # E a falha do guard não é silenciosa (warning + exc_info, nunca `pass` —
        # senão o guard vira o novo ponto cego).
        assert "telemetria" in caplog.text
        assert "Traceback" in caplog.text

    def test_telemetria_aguenta_resposta_sem_candidates(self, monkeypatch, caplog):
        class _Vazia:
            text = None
            candidates = []
            usage_metadata = None

        monkeypatch.setattr(gemini, "_get_client", lambda: _client_que_devolve(_Vazia()))
        with caplog.at_level(logging.INFO, logger=gemini.logger.name):
            assert gemini.extrair_extrato("texto") == ""  # o `or ""` de produção
        assert "candidates=0" in caplog.text
        assert "Traceback" not in caplog.text  # caminho normal, não o guard
