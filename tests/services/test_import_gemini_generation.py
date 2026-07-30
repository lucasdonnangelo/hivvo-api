"""A config de GERAÇÃO da importação vem da fonte única (app/core/gemini_generation)
e chega ao SDK nos DOIS módulos — fatura e extrato.

Contexto: a Itaú real de 6 páginas / 95 transações estourava o timeout de 60s
SEMPRE, com finish_reason=STOP e reconciliação 0.00 — não era volume nem
truncamento, era o thinking sem teto (63,9-88,6s, ±39% de variação entre
execuções idênticas). O conserto tem três parâmetros (thinking, timeout, retry) e
DOIS consumidores espelhados; o risco real é um deles ficar de fora, como já
aconteceu com o safety no F-06. É isso que este arquivo trava.

Um arquivo para os dois módulos de propósito: o assunto É a fonte única. Separar
em dois esconderia exatamente a regressão que interessa (um módulo configurado e
o outro não).

Sem rede: `_get_client` é trocado por um fake que captura os kwargs de
generate_content. Os testes de timeout constroem o client REAL (só o objeto —
genai.Client não abre conexão no __init__) e leem o valor de volta.

VERIFICAÇÃO POR MUTAÇÃO — conferida com a saída colada no relato do batch:
  1. remover a exclusão do DEADLINE_EXCEEDED do retry (fatura ou extrato)
     -> TestRetryPorStatus::test_deadline_exceeded_nao_e_retentado falha
  2. remover o thinking_config do módulo do EXTRATO
     -> os 3 casos de extrato de TestThinkingChegaAoSDK falham e os de fatura
        PASSAM — a prova de que a fonte única está ligada nos dois pontos, e não
        só na fatura.
"""

import pytest
from fastapi import HTTPException
from google.genai import errors as genai_errors

import app.services.import_extrato.gemini as gemini_extrato
import app.services.import_fatura.gemini as gemini_fatura
from app.core.config import settings
from app.core.gemini_generation import (
    STATUS_SEM_RETRY,
    THINKING_BUDGET,
    THINKING_CONFIG,
    http_options,
)

# Pior caso MEDIDO com o thinking limitado (fatura Itaú, 95 transações), em ms —
# a base da derivação do timeout. Ver o comentário em Settings.
PIOR_CASO_MEDIDO_MS = 35600

_LOTE_VAZIO = '{"itens": []}'


# --- Fakes -----------------------------------------------------------------


def _fake_client(captura: dict, texto: str = "{}"):
    class _Models:
        def generate_content(self, **kwargs):
            captura.update(kwargs)

            class _Resposta:
                text = texto

            return _Resposta()

    class _Client:
        models = _Models()

    return _Client()


def _client_que_levanta(exc: BaseException, contador: dict):
    class _Models:
        def generate_content(self, **kwargs):
            contador["n"] = contador.get("n", 0) + 1
            raise exc

    class _Client:
        models = _Models()

    return _Client()


class _FakeServerError(genai_errors.ServerError):
    """Mesmo padrão de test_import_fatura_gemini_erros.py: evita o __init__ real
    (exige response), mas com code/status — o status é o que decide o retry."""

    def __init__(self, code=503, status="UNAVAILABLE", message="upstream caiu"):
        self.code = code
        self.status = status
        self.message = message


@pytest.fixture()
def sem_sleep(monkeypatch):
    monkeypatch.setattr(gemini_fatura.time, "sleep", lambda *_: None)
    monkeypatch.setattr(gemini_extrato.time, "sleep", lambda *_: None)


def _pedido():
    return gemini_extrato.PedidoCategoria(
        indice=0, descricao="Compra no debito PADARIA", valor="50.00", tipo="despesa"
    )


# Os 3 pontos de chamada ao Gemini na importação. A categorização em lote entra
# porque ela também paga o thinking — e passa pelo mesmo _gerar.
def _chamada_fatura(monkeypatch, captura):
    monkeypatch.setattr(gemini_fatura, "_get_client", lambda: _fake_client(captura))
    gemini_fatura.extrair_fatura("texto redigido da fatura")


def _chamada_extrato(monkeypatch, captura):
    monkeypatch.setattr(gemini_extrato, "_get_client", lambda: _fake_client(captura))
    gemini_extrato.extrair_extrato("texto redigido do extrato")


def _chamada_categorizacao(monkeypatch, captura):
    monkeypatch.setattr(
        gemini_extrato, "_get_client", lambda: _fake_client(captura, _LOTE_VAZIO)
    )
    gemini_extrato.categorizar_linhas([_pedido()], ["Alimentação"], ["Salário"])


TODAS_AS_CHAMADAS = [
    pytest.param(_chamada_fatura, id="fatura"),
    pytest.param(_chamada_extrato, id="extrato"),
    pytest.param(_chamada_categorizacao, id="extrato_categorizacao"),
]


# --- Thinking ---------------------------------------------------------------


class TestThinkingChegaAoSDK:
    @pytest.mark.parametrize("chamada", TODAS_AS_CHAMADAS)
    def test_thinking_config_e_passado(self, monkeypatch, chamada):
        """«MUTAÇÃO» — sem o thinking_config, o módulo roda no orçamento default
        (sem teto): 63,9-88,6s na Itaú, contra 31,5s com 1024."""
        captura: dict = {}
        chamada(monkeypatch, captura)

        tc = captura["config"].thinking_config
        assert tc is not None, (
            "módulo não passou thinking_config — o raciocínio fica SEM TETO e "
            "atravessa o deadline sozinho"
        )
        assert tc.thinking_budget == THINKING_BUDGET

    @pytest.mark.parametrize("chamada", TODAS_AS_CHAMADAS)
    def test_usa_a_constante_compartilhada(self, monkeypatch, chamada):
        """Fonte única: não é "um 1024 igual", é O mesmo objeto de config."""
        captura: dict = {}
        chamada(monkeypatch, captura)

        assert captura["config"].thinking_config == THINKING_CONFIG

    def test_budget_nao_e_zero(self):
        """O 0 foi igualmente rápido (35,6s vs 31,5s) e PERDEU o campo `periodo`
        na Itaú — e é `periodo` que infere o ano de cada transação. Este teste
        existe para o próximo leitor não "simplificar" o 1024 para 0."""
        assert THINKING_BUDGET > 0


# --- Timeout ---------------------------------------------------------------


class TestTimeoutChegaAoSDK:
    def test_http_options_vem_do_settings(self):
        assert http_options().timeout == settings.GEMINI_IMPORT_TIMEOUT_MS

    @pytest.mark.parametrize(
        "modulo",
        [pytest.param(gemini_fatura, id="fatura"), pytest.param(gemini_extrato, id="extrato")],
    )
    def test_client_real_nasce_com_o_timeout_compartilhado(self, monkeypatch, modulo):
        """O timeout NÃO passa por generate_content: ele vive no client. Então
        aqui o `_get_client` real roda (com chave fake e singleton zerado) e o
        valor é lido de volta de dentro do client — é o único jeito de provar que
        o número chega ao SDK. genai.Client não abre conexão no __init__."""
        monkeypatch.setattr(modulo.settings, "GEMINI_IMPORT_API_KEY", "chave-de-teste")
        monkeypatch.setattr(modulo, "_client", None)

        client = modulo._get_client()

        assert client._api_client._http_options.timeout == settings.GEMINI_IMPORT_TIMEOUT_MS

    def test_timeout_cobre_o_pior_caso_medido_com_folga(self):
        """Trava do item 3: o 60000 antigo cortava a Itaú sempre. Se alguém
        reduzir isso para baixo do pior caso medido, o bug volta inteiro."""
        assert settings.GEMINI_IMPORT_TIMEOUT_MS >= 2 * PIOR_CASO_MEDIDO_MS


# --- Retry por status ------------------------------------------------------


_MODULOS_RETRY = [
    pytest.param(gemini_fatura, "extrair_fatura", id="fatura"),
    pytest.param(gemini_extrato, "extrair_extrato", id="extrato"),
]


def _roda_com_erro(monkeypatch, modulo, funcao, exc) -> dict:
    contador: dict = {}
    monkeypatch.setattr(
        modulo, "_get_client", lambda: _client_que_levanta(exc, contador)
    )
    with pytest.raises(HTTPException):
        getattr(modulo, funcao)("texto redigido")
    return contador


class TestRetryPorStatus:
    @pytest.mark.parametrize("modulo,funcao", _MODULOS_RETRY)
    def test_deadline_exceeded_nao_e_retentado(self, monkeypatch, sem_sleep, modulo, funcao):
        """«MUTAÇÃO» — removendo a exclusão, isto vira len(WAITS)+1 chamadas.

        O relógio já estourou quando o DEADLINE_EXCEEDED chega: retentar dobra a
        espera do usuário e o custo por uma chance baixa."""
        contador = _roda_com_erro(
            monkeypatch, modulo, funcao,
            _FakeServerError(code=504, status="DEADLINE_EXCEEDED"),
        )
        assert contador["n"] == 1

    @pytest.mark.parametrize("modulo,funcao", _MODULOS_RETRY)
    def test_unavailable_continua_retentando(self, monkeypatch, sem_sleep, modulo, funcao):
        """A outra metade da separação: sobrecarga real do provedor é justamente
        o caso em que esperar 2s resolve. Se este teste cair junto com o de cima,
        a mudança virou "não retenta 5xx" — que não é o pedido."""
        contador = _roda_com_erro(
            monkeypatch, modulo, funcao, _FakeServerError(status="UNAVAILABLE")
        )
        assert contador["n"] == len(settings.GEMINI_RETRY_WAITS) + 1

    @pytest.mark.parametrize("modulo,funcao", _MODULOS_RETRY)
    def test_deadline_exceeded_ainda_devolve_503(self, monkeypatch, sem_sleep, modulo, funcao):
        """Sair do retry não muda o contrato de status com o front."""
        monkeypatch.setattr(
            modulo, "_get_client",
            lambda: _client_que_levanta(
                _FakeServerError(code=504, status="DEADLINE_EXCEEDED"), {}
            ),
        )
        with pytest.raises(HTTPException) as exc:
            getattr(modulo, funcao)("texto redigido")
        assert exc.value.status_code == 503

    def test_a_politica_de_retry_e_a_mesma_nos_dois_modulos(self):
        """Fonte única do item 4: os dois módulos consultam O MESMO conjunto."""
        assert gemini_fatura.STATUS_SEM_RETRY is STATUS_SEM_RETRY
        assert gemini_extrato.STATUS_SEM_RETRY is STATUS_SEM_RETRY
        assert "DEADLINE_EXCEEDED" in STATUS_SEM_RETRY
        assert "UNAVAILABLE" not in STATUS_SEM_RETRY


# --- Log -------------------------------------------------------------------


class TestLog:
    @pytest.mark.parametrize("modulo,funcao", _MODULOS_RETRY)
    def test_log_do_deadline_nao_carrega_o_conteudo(self, monkeypatch, sem_sleep, caplog, modulo, funcao):
        """Invariante dos dois módulos: o texto importado não vai para log — nem
        pelo caminho novo. (No extrato, nem a `message` da API vai.)"""
        segredo = "COMPRA SUPERMERCADO XPTO 1234"
        monkeypatch.setattr(
            modulo, "_get_client",
            lambda: _client_que_levanta(
                _FakeServerError(code=504, status="DEADLINE_EXCEEDED"), {}
            ),
        )
        with caplog.at_level("DEBUG"):
            with pytest.raises(HTTPException):
                getattr(modulo, funcao)(segredo)

        assert segredo not in caplog.text
        assert "status=DEADLINE_EXCEEDED" in caplog.text
        # O diagnóstico do próximo timeout depende de saber contra qual teto ele
        # bateu — sem isso, "estourou" não diz se o teto está errado.
        assert str(settings.GEMINI_IMPORT_TIMEOUT_MS) in caplog.text
