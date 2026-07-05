"""Fase 2c — CRUD de recorrência (endpoints + lógica de vigência).

Mês corrente congelado em 15/07/2026 via patch de app.routers.recorrencias.hoje
(regra do conftest: nenhum teste depende do relógio real). A projeção é
verificada direto em _lancamentos_mes (a Fonte 4 da 2b) com a mesma session.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.services.estatisticas import _agregar, _lancamentos_mes

HOJE = dt.date(2026, 7, 15)  # mês corrente dos testes: julho/2026
_ZERO = Decimal("0.00")


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


@pytest.fixture(autouse=True)
def clock(mocker):
    mocker.patch("app.routers.recorrencias.hoje", return_value=HOJE)


def _payload(**over):
    base = dict(
        tipo="receita",
        valor="10000.00",
        categoria="Salário",
        forma_pagamento="Pix",
        # dia 20 > dia de hoje (15) → default início = mês corrente (regra do
        # dia, Fase 3a-backend). Mantém a intenção "começa no mês corrente" dos
        # testes de CRUD sem eles precisarem enviar mes_inicio explícito.
        dia_do_mes=20,
        descricao="Salário CLT",
    )
    base.update(over)
    return base


def _semear_recorrencia_passada(session, uid, valor="10000.00"):
    """Monta direto no banco uma recorrência aberta desde jan/2026 (passado vs.
    hoje=15/07/2026). O POST agora barra início no passado (Bug 2 — piso no mês
    corrente), mas esse ESTADO é legítimo: é como fica uma recorrência criada
    meses atrás e ainda vigente. Os testes de editar/encerrar/corrigir precisam
    desse passado, então montam o estado direto — não via POST (que é o endpoint
    guardado; sua cobertura de sucesso vive em TestCriar e TestPisoInicioNoPassado)."""
    rec = Recorrencia(
        usuario_id=uid,
        tipo="receita",
        categoria="Salário",
        forma_pagamento="Pix",
        dia_do_mes=20,
        descricao="Salário CLT",
    )
    session.add(rec)
    session.flush()
    session.add(
        RecorrenciaVigencia(
            recorrencia_id=rec.id, valor=Decimal(valor), mes_inicio=1, ano_inicio=2026
        )
    )
    session.commit()
    session.refresh(rec)
    return str(rec.id)


def _vigencias_db(session):
    return session.exec(
        select(RecorrenciaVigencia).order_by(
            RecorrenciaVigencia.ano_inicio, RecorrenciaVigencia.mes_inicio
        )
    ).all()


def _periodo(v):
    return (v.mes_inicio, v.ano_inicio, v.mes_fim, v.ano_fim)


def _receitas(session, uid, mes, ano):
    return _agregar(_lancamentos_mes(session, uid, mes, ano))[0]


class TestCriar:
    def test_cria_cabecalho_e_vigencia_aberta(self, session, users, as_user):
        resp = as_user(users[0]).post("/recorrencias", json=_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["ativa"] is True
        assert body["frequencia"] == "mensal"
        assert _q(body["valor_vigente"]) == Decimal("10000.00")
        assert len(body["vigencias"]) == 1
        vig = body["vigencias"][0]
        # sem mes_inicio no payload → começa no mês corrente (jul/2026), aberta
        assert (vig["mes_inicio"], vig["ano_inicio"]) == (7, 2026)
        assert vig["mes_fim"] is None and vig["ano_fim"] is None

        assert len(session.exec(select(Recorrencia)).all()) == 1
        assert len(_vigencias_db(session)) == 1

    def test_aparece_na_listagem_com_valor_vigente(self, session, users, as_user):
        client = as_user(users[0])
        client.post("/recorrencias", json=_payload())

        itens = client.get("/recorrencias").json()
        assert len(itens) == 1
        assert itens[0]["descricao"] == "Salário CLT"
        assert _q(itens[0]["valor_vigente"]) == Decimal("10000.00")

    def test_reflete_na_projecao_fonte_4(self, session, users, as_user):
        as_user(users[0]).post("/recorrencias", json=_payload())
        uid = users[0].id

        assert _q(_receitas(session, uid, 7, 2026)) == Decimal("10000.00")  # corrente
        assert _q(_receitas(session, uid, 3, 2028)) == Decimal("10000.00")  # futuro
        assert _receitas(session, uid, 6, 2026) == _ZERO  # antes do início

    def test_inicio_informado_respeitado(self, session, users, as_user):
        as_user(users[0]).post(
            "/recorrencias", json=_payload(mes_inicio=1, ano_inicio=2027)
        )
        uid = users[0].id
        assert _receitas(session, uid, 12, 2026) == _ZERO
        assert _q(_receitas(session, uid, 1, 2027)) == Decimal("10000.00")

    @pytest.mark.parametrize(
        "campos",
        [
            {"tipo": "investimento"},
            {"valor": "0.00"},
            {"valor": "-10.00"},
            {"dia_do_mes": 0},
            {"dia_do_mes": 32},
            {"mes_inicio": 1},  # sem ano_inicio — pareamento obrigatório
        ],
    )
    def test_validacoes_422(self, users, as_user, campos):
        resp = as_user(users[0]).post("/recorrencias", json=_payload(**campos))
        assert resp.status_code == 422


class TestPisoInicioNoPassado:
    """Bug 2 — o POST barra override com início ANTERIOR ao mês corrente (o
    passado é verdade histórica, §3.1.2; não se inventa recorrência retroativa).
    hoje congelado em 15/07/2026 (fixture clock). Corrente e futuro passam; o
    default (regra do dia) nunca resolve para o passado e fica intacto."""

    def test_override_mes_passado_422(self, users, as_user):
        resp = as_user(users[0]).post(
            "/recorrencias", json=_payload(mes_inicio=6, ano_inicio=2026)
        )
        assert resp.status_code == 422
        assert "anterior ao mês corrente" in resp.json()["detail"]

    def test_override_ano_passado_422(self, users, as_user):
        resp = as_user(users[0]).post(
            "/recorrencias", json=_payload(mes_inicio=12, ano_inicio=2025)
        )
        assert resp.status_code == 422

    def test_override_mes_corrente_ok(self, users, as_user):
        resp = as_user(users[0]).post(
            "/recorrencias", json=_payload(mes_inicio=7, ano_inicio=2026)
        )
        assert resp.status_code == 201
        vig = resp.json()["vigencias"][0]
        assert (vig["mes_inicio"], vig["ano_inicio"]) == (7, 2026)

    def test_override_mes_futuro_ok(self, users, as_user):
        resp = as_user(users[0]).post(
            "/recorrencias", json=_payload(mes_inicio=9, ano_inicio=2026)
        )
        assert resp.status_code == 201
        vig = resp.json()["vigencias"][0]
        assert (vig["mes_inicio"], vig["ano_inicio"]) == (9, 2026)

    def test_default_dia_futuro_mes_corrente_ok(self, users, as_user):
        # sem mes_inicio: regra do dia. dia 20 > hoje 15 → mês corrente (o piso
        # não toca o default — ele nunca resolve para o passado).
        resp = as_user(users[0]).post("/recorrencias", json=_payload(dia_do_mes=20))
        assert resp.status_code == 201
        vig = resp.json()["vigencias"][0]
        assert (vig["mes_inicio"], vig["ano_inicio"]) == (7, 2026)

    def test_default_dia_passado_mes_seguinte_ok(self, users, as_user):
        # dia 10 < hoje 15 → mês seguinte (agosto). Default intacto.
        resp = as_user(users[0]).post("/recorrencias", json=_payload(dia_do_mes=10))
        assert resp.status_code == 201
        vig = resp.json()["vigencias"][0]
        assert (vig["mes_inicio"], vig["ano_inicio"]) == (8, 2026)


class TestRegraDiaDefaultInicio:
    """Fase 3a-backend: o mês de início DEFAULT depende do dia da recorrência
    vs. hoje (lógica de negócio). hoje congelado em 15/07/2026 (fixture clock);
    a regra só vale quando o cliente NÃO envia mes_inicio/ano_inicio."""

    def _inicio(self, client, **over):
        vig = client.post("/recorrencias", json=_payload(**over)).json()["vigencias"][0]
        return (vig["mes_inicio"], vig["ano_inicio"])

    def test_dia_futuro_comeca_no_mes_corrente(self, users, as_user):
        # dia 20 > hoje 15 → a ocorrência ainda acontece este mês
        assert self._inicio(as_user(users[0]), dia_do_mes=20) == (7, 2026)

    def test_dia_passado_comeca_no_mes_seguinte(self, users, as_user):
        # dia 10 < hoje 15 → o dia já passou; primeira ocorrência no próximo mês
        assert self._inicio(as_user(users[0]), dia_do_mes=10) == (8, 2026)

    def test_dia_igual_hoje_comeca_no_mes_corrente(self, users, as_user):
        # borda: dia == hoje → a ocorrência ainda ocorre hoje
        assert self._inicio(as_user(users[0]), dia_do_mes=15) == (7, 2026)

    def test_virada_de_ano(self, mocker, users, as_user):
        # dezembro, dia 10 já passou → janeiro do ANO SEGUINTE
        mocker.patch("app.routers.recorrencias.hoje", return_value=dt.date(2026, 12, 15))
        assert self._inicio(as_user(users[0]), dia_do_mes=10) == (1, 2027)

    def test_override_explicito_ignora_regra_do_dia(self, users, as_user):
        # cliente envia início → usa o enviado, mesmo com dia passado (10 < 15)
        inicio = self._inicio(
            as_user(users[0]), dia_do_mes=10, mes_inicio=9, ano_inicio=2026
        )
        assert inicio == (9, 2026)

    def test_regra_reflete_na_projecao(self, session, users, as_user):
        # dia 10 (passado) → começa agosto: julho (corrente) fica zero, agosto gera
        as_user(users[0]).post("/recorrencias", json=_payload(dia_do_mes=10))
        uid = users[0].id
        assert _receitas(session, uid, 7, 2026) == _ZERO
        assert _q(_receitas(session, uid, 8, 2026)) == Decimal("10000.00")


class TestEditarValor:
    def test_fecha_antiga_e_abre_nova_sem_gap_nem_sobreposicao(
        self, session, users, as_user
    ):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)

        resp = client.patch(f"/recorrencias/{rec_id}", json={"valor": "12000.00"})
        assert resp.status_code == 200

        vigs = _vigencias_db(session)
        assert len(vigs) == 2
        # antiga: jan/2026 até jun/2026 (mês ANTERIOR ao corrente); nova: jul/2026 aberta
        assert _periodo(vigs[0]) == (1, 2026, 6, 2026)
        assert _q(vigs[0].valor) == Decimal("10000.00")
        assert _periodo(vigs[1]) == (7, 2026, None, None)
        assert _q(vigs[1].valor) == Decimal("12000.00")

        # projeção: passado mantém o antigo; corrente/futuro usam o novo
        uid = users[0].id
        assert _q(_receitas(session, uid, 6, 2026)) == Decimal("10000.00")
        assert _q(_receitas(session, uid, 7, 2026)) == Decimal("12000.00")
        assert _q(_receitas(session, uid, 1, 2027)) == Decimal("12000.00")

    def test_editar_duas_vezes_no_mes_nao_cria_degenerada(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)
        client.patch(f"/recorrencias/{rec_id}", json={"valor": "12000.00"})
        client.patch(f"/recorrencias/{rec_id}", json={"valor": "13000.00"})

        vigs = _vigencias_db(session)
        assert len(vigs) == 2  # não virou 3 — a aberta do mês foi substituída
        assert _periodo(vigs[0]) == (1, 2026, 6, 2026)
        assert _q(vigs[0].valor) == Decimal("10000.00")  # histórico intacto
        assert _periodo(vigs[1]) == (7, 2026, None, None)
        assert _q(vigs[1].valor) == Decimal("13000.00")

        uid = users[0].id
        assert _q(_receitas(session, uid, 6, 2026)) == Decimal("10000.00")
        assert _q(_receitas(session, uid, 7, 2026)) == Decimal("13000.00")

    def test_editar_no_mes_da_criacao_substitui_in_place(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = client.post("/recorrencias", json=_payload()).json()["id"]  # início jul/2026

        client.patch(f"/recorrencias/{rec_id}", json={"valor": "12000.00"})

        vigs = _vigencias_db(session)
        assert len(vigs) == 1  # substituída, não versionada
        assert _periodo(vigs[0]) == (7, 2026, None, None)
        assert _q(vigs[0].valor) == Decimal("12000.00")

    def test_editar_recorrencia_de_inicio_futuro_preserva_o_inicio(
        self, session, users, as_user
    ):
        client = as_user(users[0])
        rec_id = client.post(
            "/recorrencias", json=_payload(mes_inicio=1, ano_inicio=2027)
        ).json()["id"]

        client.patch(f"/recorrencias/{rec_id}", json={"valor": "12000.00"})

        vigs = _vigencias_db(session)
        assert len(vigs) == 1
        assert _periodo(vigs[0]) == (1, 2027, None, None)  # início futuro intacto
        assert _q(vigs[0].valor) == Decimal("12000.00")


class TestEditarMetadados:
    def test_retroativo_no_cabecalho_vigencias_intactas(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)

        resp = client.patch(
            f"/recorrencias/{rec_id}",
            json={"descricao": "Salário PJ", "categoria": "Renda", "dia_do_mes": 10},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["descricao"] == "Salário PJ"
        assert body["categoria"] == "Renda"
        assert body["dia_do_mes"] == 10

        vigs = _vigencias_db(session)
        assert len(vigs) == 1  # metadado NÃO versiona
        assert _periodo(vigs[0]) == (1, 2026, None, None)
        # projeção histórica de VALOR inalterada
        assert _q(_receitas(session, users[0].id, 3, 2026)) == Decimal("10000.00")


class TestDelete:
    def test_preserva_passado_e_para_o_futuro(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)

        resp = client.delete(f"/recorrencias/{rec_id}")
        assert resp.status_code == 204

        vigs = _vigencias_db(session)
        assert len(vigs) == 1  # nenhuma linha apagada
        assert _periodo(vigs[0]) == (1, 2026, 7, 2026)  # fechada no mês corrente

        uid = users[0].id
        assert _q(_receitas(session, uid, 6, 2026)) == Decimal("10000.00")  # passado
        assert _q(_receitas(session, uid, 7, 2026)) == Decimal("10000.00")  # corrente
        assert _receitas(session, uid, 8, 2026) == _ZERO  # futuro parou

        # listagem padrão esconde; incluir_encerradas mostra com ativa=False
        assert client.get("/recorrencias").json() == []
        encerradas = client.get("/recorrencias", params={"incluir_encerradas": True}).json()
        assert len(encerradas) == 1
        assert encerradas[0]["ativa"] is False
        # detalhe continua acessível (histórico)
        assert client.get(f"/recorrencias/{rec_id}").status_code == 200

    def test_delete_de_inicio_futuro_nunca_gera(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = client.post(
            "/recorrencias", json=_payload(mes_inicio=1, ano_inicio=2027)
        ).json()["id"]
        client.delete(f"/recorrencias/{rec_id}")

        # intervalo fechado antes de começar (fim jul/2026 < início jan/2027):
        # vazio — não gera em mês nenhum
        uid = users[0].id
        for mes, ano in [(12, 2026), (1, 2027), (7, 2026)]:
            assert _receitas(session, uid, mes, ano) == _ZERO

    def test_escrita_em_encerrada_da_404(self, users, as_user):
        client = as_user(users[0])
        rec_id = client.post("/recorrencias", json=_payload()).json()["id"]
        client.delete(f"/recorrencias/{rec_id}")

        assert client.delete(f"/recorrencias/{rec_id}").status_code == 404
        assert (
            client.patch(f"/recorrencias/{rec_id}", json={"valor": "1.00"}).status_code
            == 404
        )


class TestIsolamento:
    def test_usuario_nao_ve_nem_escreve_recorrencia_alheia(self, session, users, as_user):
        user_a, user_b = users
        rec_id = as_user(user_a).post("/recorrencias", json=_payload()).json()["id"]

        client_b = as_user(user_b)
        assert client_b.get("/recorrencias").json() == []
        assert client_b.get(f"/recorrencias/{rec_id}").status_code == 404
        assert (
            client_b.patch(f"/recorrencias/{rec_id}", json={"valor": "1.00"}).status_code
            == 404
        )
        assert client_b.delete(f"/recorrencias/{rec_id}").status_code == 404

        # nada mudou na recorrência do A
        rec = session.get(Recorrencia, uuid.UUID(rec_id))
        assert rec.ativa is True
        assert _q(_vigencias_db(session)[0].valor) == Decimal("10000.00")


class TestHardDelete:
    """§3.1.2 — "foi um erro": DELETE /{id}/permanente apaga recorrência E
    vigências do banco (some do histórico e da projeção). Distinto do DELETE
    /{id} (encerrar), que preserva o passado e não apaga linhas."""

    def test_apaga_linhas_e_some_da_projecao_passada(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)
        uid = users[0].id
        assert _q(_receitas(session, uid, 3, 2026)) == Decimal("10000.00")  # antes

        resp = client.delete(f"/recorrencias/{rec_id}/permanente")
        assert resp.status_code == 204

        # linhas somem do banco (cabeçalho E vigências)
        assert session.exec(select(Recorrencia)).all() == []
        assert _vigencias_db(session) == []
        # some da projeção inclusive no PASSADO (contraste com o soft delete)
        assert _receitas(session, uid, 3, 2026) == _ZERO
        assert _receitas(session, uid, 7, 2026) == _ZERO
        # e do contrato de leitura
        assert client.get(f"/recorrencias/{rec_id}").status_code == 404
        assert client.get("/recorrencias", params={"incluir_encerradas": True}).json() == []

    def test_funciona_em_recorrencia_encerrada(self, session, users, as_user):
        # encerrou por engano → ainda dá para apagar permanentemente
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)
        client.delete(f"/recorrencias/{rec_id}")  # soft: encerra
        assert len(_vigencias_db(session)) == 1  # soft NÃO apagou

        assert client.delete(f"/recorrencias/{rec_id}/permanente").status_code == 204
        assert session.exec(select(Recorrencia)).all() == []
        assert _vigencias_db(session) == []

    def test_soft_delete_segue_sem_apagar_linhas(self, session, users, as_user):
        # contraste explícito: o DELETE normal (encerrar) preserva as linhas
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)
        client.delete(f"/recorrencias/{rec_id}")

        assert len(session.exec(select(Recorrencia)).all()) == 1
        assert len(_vigencias_db(session)) == 1
        assert _q(_receitas(session, users[0].id, 3, 2026)) == Decimal("10000.00")

    def test_isolamento_404_e_nada_apagado(self, session, users, as_user):
        user_a, user_b = users
        rec_id = _semear_recorrencia_passada(session, user_a.id)

        resp = as_user(user_b).delete(f"/recorrencias/{rec_id}/permanente")
        assert resp.status_code == 404
        assert len(session.exec(select(Recorrencia)).all()) == 1
        assert len(_vigencias_db(session)) == 1


class TestCorrigirValor:
    """§3.1.2 — "foi um erro": PATCH /{id}/corrigir-valor reescreve o valor em
    todos os meses, SÓ com vigência única (erro fresco). Distinto do PATCH
    /{id} (alterar), que versiona."""

    def test_vigencia_unica_reescreve_in_place_e_corrige_o_passado(
        self, session, users, as_user
    ):
        client = as_user(users[0])
        # criada com valor ERRADO (digitou 100000, era 10000)
        rec_id = _semear_recorrencia_passada(session, users[0].id, valor="100000.00")
        id_vigencia_original = _vigencias_db(session)[0].id
        uid = users[0].id
        assert _q(_receitas(session, uid, 3, 2026)) == Decimal("100000.00")  # errado

        resp = client.patch(
            f"/recorrencias/{rec_id}/corrigir-valor", json={"valor": "10000.00"}
        )
        assert resp.status_code == 200
        assert _q(resp.json()["valor_vigente"]) == Decimal("10000.00")

        vigs = _vigencias_db(session)
        assert len(vigs) == 1  # NÃO versionou — nenhuma vigência nova
        assert vigs[0].id == id_vigencia_original  # a MESMA linha, reescrita
        assert _periodo(vigs[0]) == (1, 2026, None, None)  # período intacto
        assert _q(vigs[0].valor) == Decimal("10000.00")
        # o passado reflete o valor corrigido, não o errado
        assert _q(_receitas(session, uid, 3, 2026)) == Decimal("10000.00")
        assert _q(_receitas(session, uid, 12, 2027)) == Decimal("10000.00")

    def test_multiplas_vigencias_409_e_nada_muda(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id, valor="100000.00")
        client.patch(f"/recorrencias/{rec_id}", json={"valor": "12000.00"})  # versiona
        antes = [(v.id, _q(v.valor), _periodo(v)) for v in _vigencias_db(session)]
        assert len(antes) == 2

        resp = client.patch(
            f"/recorrencias/{rec_id}/corrigir-valor", json={"valor": "10000.00"}
        )
        assert resp.status_code == 409
        assert "Correção retroativa indisponível" in resp.json()["detail"]
        depois = [(v.id, _q(v.valor), _periodo(v)) for v in _vigencias_db(session)]
        assert depois == antes  # vigências intactas

    def test_encerrada_404(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id, valor="100000.00")
        client.delete(f"/recorrencias/{rec_id}")  # encerra (soft)

        resp = client.patch(
            f"/recorrencias/{rec_id}/corrigir-valor", json={"valor": "10000.00"}
        )
        assert resp.status_code == 404

    def test_isolamento_404(self, session, users, as_user):
        user_a, user_b = users
        rec_id = _semear_recorrencia_passada(session, user_a.id, valor="100000.00")

        resp = as_user(user_b).patch(
            f"/recorrencias/{rec_id}/corrigir-valor", json={"valor": "10000.00"}
        )
        assert resp.status_code == 404
        assert _q(_vigencias_db(session)[0].valor) == Decimal("100000.00")

    @pytest.mark.parametrize("valor", ["0.00", "-10.00"])
    def test_valor_invalido_422(self, session, users, as_user, valor):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id, valor="100000.00")

        resp = client.patch(f"/recorrencias/{rec_id}/corrigir-valor", json={"valor": valor})
        assert resp.status_code == 422


class TestValorExibicao:
    """Bug 1 — a gestão precisa de um valor não-nulo para recorrência de início
    FUTURO (valor_vigente é null quando nada vige hoje). valor_exibicao cai para
    a vigência futura mais próxima; ENCERRADA (só passado) permanece null. hoje
    congelado em 15/07/2026 (fixture clock). valor_vigente fica intocado."""

    def test_inicio_mes_seguinte_expoe_valor_futuro(self, users, as_user):
        client = as_user(users[0])
        # dia 10 < hoje 15 → default começa agosto/2026 (futuro): nada vige em julho
        body = client.post("/recorrencias", json=_payload(dia_do_mes=10)).json()
        assert body["valor_vigente"] is None
        assert _q(body["valor_exibicao"]) == Decimal("10000.00")

        # a mesma regra na LISTA (não só no detalhe do POST)
        item = client.get("/recorrencias").json()[0]
        assert item["valor_vigente"] is None
        assert _q(item["valor_exibicao"]) == Decimal("10000.00")

    def test_vigente_hoje_exibicao_igual_vigente(self, users, as_user):
        client = as_user(users[0])
        # dia 20 > hoje 15 → começa julho (corrente): vige hoje
        body = client.post("/recorrencias", json=_payload(dia_do_mes=20)).json()
        assert _q(body["valor_vigente"]) == Decimal("10000.00")
        assert _q(body["valor_exibicao"]) == _q(body["valor_vigente"])

    def test_encerrada_so_passado_exibicao_null(self, session, users, as_user):
        # Borda crítica: vigência fechada em mar/2026 (passado), ativa=False. Nada
        # vige hoje E não há vigência futura → valor_exibicao NÃO pode pegar o
        # valor passado; deve ser null (continua "—", correto — está encerrada).
        rec = Recorrencia(
            usuario_id=users[0].id,
            tipo="receita",
            categoria="Salário",
            forma_pagamento="Pix",
            dia_do_mes=20,
            descricao="Salário CLT",
            ativa=False,
        )
        session.add(rec)
        session.flush()
        session.add(
            RecorrenciaVigencia(
                recorrencia_id=rec.id,
                valor=Decimal("10000.00"),
                mes_inicio=1,
                ano_inicio=2026,
                mes_fim=3,
                ano_fim=2026,
            )
        )
        session.commit()

        detail = as_user(users[0]).get(f"/recorrencias/{rec.id}").json()
        assert detail["valor_vigente"] is None
        assert detail["valor_exibicao"] is None

        # na lista (incluir_encerradas) também permanece null
        item = as_user(users[0]).get(
            "/recorrencias", params={"incluir_encerradas": True}
        ).json()[0]
        assert item["valor_exibicao"] is None

    def test_inicio_futuro_distante_pega_primeira_vigencia(self, users, as_user):
        client = as_user(users[0])
        # override futuro out/2026 (3 meses à frente; permitido pelo piso do Bug 2)
        body = client.post(
            "/recorrencias", json=_payload(mes_inicio=10, ano_inicio=2026)
        ).json()
        assert body["valor_vigente"] is None
        assert _q(body["valor_exibicao"]) == Decimal("10000.00")

    def test_multiplas_vigencias_uma_vigente_hoje(self, session, users, as_user):
        client = as_user(users[0])
        rec_id = _semear_recorrencia_passada(session, users[0].id)  # jan/2026 aberta
        client.patch(f"/recorrencias/{rec_id}", json={"valor": "12000.00"})  # versiona

        # duas vigências: jan–jun/2026 (10000) e jul/2026 aberta (12000, vige hoje)
        detail = client.get(f"/recorrencias/{rec_id}").json()
        assert _q(detail["valor_vigente"]) == Decimal("12000.00")
        assert _q(detail["valor_exibicao"]) == _q(detail["valor_vigente"])
