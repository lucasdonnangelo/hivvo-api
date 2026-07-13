"""Batch 6 / T-11 — guarda de nome no create_category (índice parcial WHERE ativa).

A regra real, dado o soft delete, é "não duas categorias ATIVAS com o mesmo nome"
(normalizado por lower(trim)). O POST: 409 se já há ativa; reativa a MESMA linha se
só há inativa; insere se não há nenhuma.
"""

from sqlmodel import select

from app.models.category import CategoriaCustomizada


def post_cat(client, nome, icone="🍔", tipo="despesa"):
    return client.post("/categories", json={"nome": nome, "icone": icone, "tipo": tipo})


def _rows(session, usuario_id):
    return session.exec(
        select(CategoriaCustomizada).where(CategoriaCustomizada.usuario_id == usuario_id)
    ).all()


class TestCreateCategoryGuard:
    def test_nome_novo_insere(self, session, users, as_user):
        client = as_user(users[0])
        r = post_cat(client, "Pets")
        assert r.status_code == 201
        assert r.json()["nome"] == "Pets"
        assert len(_rows(session, users[0].id)) == 1

    def test_nome_ja_ativo_retorna_409(self, session, users, as_user):
        client = as_user(users[0])
        assert post_cat(client, "Pets").status_code == 201
        r = post_cat(client, "Pets")
        assert r.status_code == 409
        assert r.json()["detail"] == "Já existe uma categoria ativa com esse nome"
        assert len(_rows(session, users[0].id)) == 1  # não inseriu 2ª

    def test_recriar_nome_inativo_reativa_mesma_linha(self, session, users, as_user):
        client = as_user(users[0])
        cid = post_cat(client, "Pets").json()["id"]
        assert client.delete(f"/categories/{cid}").status_code == 204

        r = post_cat(client, "Pets")
        assert r.status_code == 201
        assert r.json()["id"] == cid  # MESMA linha, não uma 2ª
        assert r.json()["ativa"] is True
        assert len(_rows(session, users[0].id)) == 1

    def test_reativacao_atualiza_icone_e_tipo(self, session, users, as_user):
        client = as_user(users[0])
        cid = post_cat(client, "Pets", icone="🍔", tipo="despesa").json()["id"]
        client.delete(f"/categories/{cid}")

        r = post_cat(client, "Pets", icone="🐾", tipo="receita")
        assert r.status_code == 201
        assert r.json()["id"] == cid
        assert r.json()["icone"] == "🐾"
        assert r.json()["tipo"] == "receita"

    def test_case_e_espaco_tratados(self, session, users, as_user):
        client = as_user(users[0])
        assert post_cat(client, "Uber Eats").status_code == 201
        r = post_cat(client, "  uber eats ")  # mesmo nome normalizado
        assert r.status_code == 409
        assert len(_rows(session, users[0].id)) == 1

    def test_mesmo_nome_usuarios_distintos_passa(self, session, users, as_user):
        # O índice/guarda é por usuário — nomes iguais entre usuários coexistem
        assert post_cat(as_user(users[0]), "Pets").status_code == 201
        assert post_cat(as_user(users[1]), "Pets").status_code == 201
        assert len(_rows(session, users[0].id)) == 1
        assert len(_rows(session, users[1].id)) == 1


class TestListCategoriesFilter:
    """GET /categories?tipo= — filtro opcional aplicado a padrão + customizadas."""

    def test_sem_param_retorna_tudo(self, session, users, as_user):
        client = as_user(users[0])
        nomes = [c["nome"] for c in client.get("/categories").json()]
        # padrão tem despesa e receita; sem filtro, ambos os "Outros" aparecem
        assert "Salário" in nomes  # receita
        assert "Alimentação" in nomes  # despesa
        assert {c["tipo"] for c in client.get("/categories").json()} == {
            "receita",
            "despesa",
        }

    def test_tipo_despesa_so_despesa(self, session, users, as_user):
        client = as_user(users[0])
        body = client.get("/categories", params={"tipo": "despesa"}).json()
        assert all(c["tipo"] == "despesa" for c in body)
        assert "Alimentação" in [c["nome"] for c in body]
        # o "Outros" de despesa entra; nenhuma receita (ex. Salário) aparece
        assert "Salário" not in [c["nome"] for c in body]
        assert any(c["nome"] == "Outros" for c in body)

    def test_tipo_receita_so_receita(self, session, users, as_user):
        client = as_user(users[0])
        body = client.get("/categories", params={"tipo": "receita"}).json()
        assert all(c["tipo"] == "receita" for c in body)
        assert "Salário" in [c["nome"] for c in body]
        assert "Alimentação" not in [c["nome"] for c in body]
        # o "Outros" de receita entra
        assert any(c["nome"] == "Outros" for c in body)

    def test_customizada_respeita_filtro(self, session, users, as_user):
        client = as_user(users[0])
        assert post_cat(client, "Dividendos", icone="📈", tipo="receita").status_code == 201

        receita_nomes = [
            c["nome"] for c in client.get("/categories", params={"tipo": "receita"}).json()
        ]
        despesa_nomes = [
            c["nome"] for c in client.get("/categories", params={"tipo": "despesa"}).json()
        ]
        assert "Dividendos" in receita_nomes
        assert "Dividendos" not in despesa_nomes

    def test_tipo_invalido_retorna_422(self, session, users, as_user):
        client = as_user(users[0])
        assert client.get("/categories", params={"tipo": "xpto"}).status_code == 422
