"""Auto-categoria da fatura — as três camadas, no preview e no commit.

SQLite in-memory isolado do conftest, Gemini SEMPRE mockado (a extração é
stubbada; a auto-categoria não chama modelo nenhum por design).

Cobre as regras que NÃO se negociam, cada uma com o alvo de mutação anotado:
- a camada 1 nunca aprende de "Outros" (mutação: tirar o filtro do WHERE);
- a camada 1 filtra por TIPO (mutação: aceitar qualquer tipo);
- empate no histórico cai para a camada 2 (mutação: desempatar por acaso);
- prefixo de adquirente casa (mutação: exigir descrição limpa);
- o commit RECOMPUTA quando a categoria vem ausente e REVALIDA quando vem;
- o preview não escreve nada.
"""

import copy
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlmodel import select

from app.core.config import settings
from app.models.card import Cartao
from app.models.category import CategoriaCustomizada
from app.models.transaction import Transacao
from app.services.import_fatura import gemini
from tests.fixtures.faturas_validadas import NUBANK

_PDF = (
    Path(__file__).resolve().parent.parent / "fixtures" / "fatura_texto_minimo.pdf"
).read_bytes()


def _fatura_com(descricoes: list[str]) -> dict:
    """A fatura Nubank validada, com as COMPRAS trocadas pelas descrições dadas.

    Reusa o cabeçalho/totais do run real (não reinventa fatura); só as linhas
    interessam para categorização. A reconciliação pode não bater — não é gate
    (a rota devolve 200 com bate=false por design).
    """
    fatura = copy.deepcopy(NUBANK)
    fatura["transacoes"] = [
        {
            "data": "2026-06-15",
            "descricao": descricao,
            "valor_brl": "50.00",
            "tipo": "compra",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        }
        for descricao in descricoes
    ]
    return fatura


@pytest.fixture()
def cartao(session, users):
    card = Cartao(
        usuario_id=users[0].id, nome="Nubank", tipo="Crédito",
        dia_vencimento=13, dia_fechamento=6, mes_offset_vencimento=1,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


@pytest.fixture()
def extracao(monkeypatch):
    """Instala o stub da extração e devolve um setter da fatura extraída."""
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "chave-de-teste")
    estado = {"fatura": NUBANK}
    monkeypatch.setattr(
        gemini, "extrair_fatura", lambda texto: json.dumps(estado["fatura"])
    )
    return estado


def _historico(session, usuario_id, descricao, categoria, *, tipo="despesa", quantas=1):
    for i in range(quantas):
        session.add(
            Transacao(
                usuario_id=usuario_id,
                tipo=tipo,
                data=dt.date(2026, 5, 1),
                descricao=descricao,
                valor=Decimal("10.00"),
                categoria=categoria,
                forma_pagamento="Crédito",
            )
        )
    session.commit()


def _preview(client, cartao_id):
    return client.post(
        "/import/fatura/preview",
        files={"arquivo": ("fatura.pdf", _PDF, "application/pdf")},
        data={"cartao_id": str(cartao_id)},
    )


def _sugestoes(resp) -> dict[int, tuple]:
    assert resp.status_code == 200, resp.text
    return {
        e["indice"]: (e["categoria_sugerida"], e["origem_sugestao"])
        for e in resp.json()["enriquecimento"]
    }


def _commit(client, cartao_id, fatura):
    return client.post(
        "/import/fatura/commit",
        json={"cartao_id": cartao_id, "fatura": fatura, "competencias_pagas": []},
    )


# --- Camada 1: histórico do usuário -------------------------------------------


def test_historico_do_usuario_vence_a_regra(session, as_user, users, cartao, extracao):
    """A camada 1 é a personalizada: ela decide ANTES da regra genérica.

    "PADARIA CENTRAL" casaria a keyword "padaria" -> Alimentação. O usuário já
    categorizou como Lazer; é o que ele vê de volta.
    """
    _historico(session, users[0].id, "PADARIA CENTRAL", "Lazer", quantas=2)
    extracao["fatura"] = _fatura_com(["PADARIA CENTRAL"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == ("Lazer", "historico")


def test_camada_1_nunca_aprende_de_outros(session, as_user, users, cartao, extracao):
    """MUTAÇÃO-ALVO: remover `categoria != CATEGORIA_NEUTRA` do WHERE de
    `categoria_do_historico` faz "Outros" (3 votos) ganhar de "Saúde" (1) e o
    teste falha com ('Outros', 'historico').

    "Outros" é o DEFAULT, não uma decisão — um histórico com "Outros" é
    indistinguível de "nunca categorizado". Aprender dele seria o sistema
    aprendendo o próprio silêncio.
    """
    _historico(session, users[0].id, "LOJA AMBIGUA", "Outros", quantas=3)
    _historico(session, users[0].id, "LOJA AMBIGUA", "Saúde", quantas=1)
    extracao["fatura"] = _fatura_com(["LOJA AMBIGUA"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == ("Saúde", "historico")


def test_camada_1_respeita_o_tipo(session, as_user, users, cartao, extracao):
    """MUTAÇÃO-ALVO: tirar o filtro `tipo IN (...)` faz a linha voltar
    ("Bônus", "historico") — histórico de RECEITA decidindo uma compra de cartão.

    O cenário precisa do nome existindo nos DOIS lados, senão a mutação
    sobrevive: `validar_nome_categoria` já barraria "Salário" (que não está na
    lista de despesa) e o teste passaria sem o filtro, provando nada. Aqui
    "Bônus" É categoria de despesa ATIVA do usuário — só o filtro de tipo
    impede o histórico de receita de alcançá-la.

    `Transacao.categoria` é string livre no banco: uma receita categorizada
    "Bônus" (categoria recriada com outro tipo, import de CSV, entrada manual
    antiga) é estado alcançável, não hipótese.
    """
    session.add(
        CategoriaCustomizada(usuario_id=users[0].id, nome="Bônus", tipo="despesa")
    )
    session.commit()
    _historico(session, users[0].id, "ACME LTDA", "Bônus", tipo="receita", quantas=5)
    extracao["fatura"] = _fatura_com(["ACME LTDA"])

    # Nada a dizer: o histórico é todo de receita e a descrição não casa regra.
    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == (None, None)


def test_historico_de_estorno_conta_como_despesa(
    session, as_user, users, cartao, extracao
):
    """Estorno é compra devolvida: a categoria dele É categoria de despesa."""
    _historico(session, users[0].id, "LOJA X", "Roupas", tipo="estorno", quantas=2)
    extracao["fatura"] = _fatura_com(["LOJA X"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == ("Roupas", "historico")


def test_empate_cai_para_a_camada_2(session, as_user, users, cartao, extracao):
    """MUTAÇÃO-ALVO: desempatar por ordem/id devolveria ("Lazer"|"Pets",
    "historico"). Empate entre duas não-"Outros" não se resolve por acaso —
    desce para a regra, que sabe o que é uma padaria.
    """
    _historico(session, users[0].id, "PADARIA CENTRAL", "Lazer", quantas=2)
    _historico(session, users[0].id, "PADARIA CENTRAL", "Pets", quantas=2)
    extracao["fatura"] = _fatura_com(["PADARIA CENTRAL"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == (
        "Alimentação",
        "regra",
    )


def test_historico_de_outro_usuario_nao_vaza(session, as_user, users, cartao, extracao):
    _historico(session, users[1].id, "LOJA AMBIGUA", "Pets", quantas=9)
    extracao["fatura"] = _fatura_com(["LOJA AMBIGUA"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == (None, None)


def test_historico_de_categoria_desativada_desce_para_a_regra(
    session, as_user, users, cartao, extracao
):
    """O usuário pode DESATIVAR a categoria depois de tê-la usado: o histórico
    aponta para um nome que o picker não oferece mais."""
    custom = CategoriaCustomizada(usuario_id=users[0].id, nome="Feira", tipo="despesa")
    session.add(custom)
    session.commit()
    _historico(session, users[0].id, "PADARIA CENTRAL", "Feira", quantas=3)
    custom.ativa = False
    session.add(custom)
    session.commit()

    extracao["fatura"] = _fatura_com(["PADARIA CENTRAL"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == (
        "Alimentação",
        "regra",
    )


# --- Camada 2: regra de lojista -----------------------------------------------


def test_prefixo_de_adquirente_casa(as_user, users, cartao, extracao):
    """MUTAÇÃO-ALVO: exigir descrição "limpa" (sem o sufixo do adquirente)
    devolveria (None, None) nas três — que é exatamente o lixo que a camada 2
    existe para resolver."""
    extracao["fatura"] = _fatura_com(
        ["IFD*40827151VICTORMA", "Kee*ARCOSDOURADOSC", "99Food*SGMDELIVERYL"]
    )

    sugestoes = _sugestoes(_preview(as_user(users[0]), cartao.id))
    assert sugestoes[0] == ("Alimentação", "regra")
    assert sugestoes[1] == ("Alimentação", "regra")
    assert sugestoes[2] == ("Alimentação", "regra")


def test_adquirente_horizontal_nao_vira_regra(as_user, users, cartao, extracao):
    """MP* (MercadoPago) processa qualquer coisa: sugerir seria adivinhar com
    cara de dado. Preferimos "Outros" honesto."""
    extracao["fatura"] = _fatura_com(["MP*MANOELPEREIRA"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == (None, None)


def test_keyword_nao_sequestra_categoria_customizada(
    session, as_user, users, cartao, extracao
):
    """A ordem (exato -> adquirente -> substring -> keyword) protege o
    vocabulário DO USUÁRIO: quem criou "Padaria" recebe "Padaria", não a
    Alimentação da regra genérica."""
    session.add(
        CategoriaCustomizada(usuario_id=users[0].id, nome="Padaria", tipo="despesa")
    )
    session.commit()
    extracao["fatura"] = _fatura_com(["PADARIA CENTRAL"])

    assert _sugestoes(_preview(as_user(users[0]), cartao.id))[0] == ("Padaria", "regra")


def test_linha_ilegivel_nao_recebe_sugestao(as_user, users, cartao, extracao):
    extracao["fatura"] = _fatura_com(["AVGUAPIRA", "ITAUSHOP"])

    sugestoes = _sugestoes(_preview(as_user(users[0]), cartao.id))
    assert sugestoes[0] == (None, None)
    assert sugestoes[1] == (None, None)


# --- Recorte e alinhamento ----------------------------------------------------


def test_so_linha_materializavel_recebe_item(as_user, users, cartao, extracao):
    """O join é por `indice` EXPLÍCITO: pagamento/ajuste_saldo não têm item e os
    índices das que têm continuam sendo os da lista ORIGINAL.

    MUTAÇÃO-ALVO: montar o array por posição (`enumerate` sobre os
    materializáveis) faria a sugestão pousar na linha errada. O cenário precisa
    da linha não-materializável ANTES das outras — com ela no fim, posição e
    índice coincidem e a mutação sobrevive sem ser vista.
    """
    fatura = _fatura_com(["Pagamento efetuado", "IFD*DUBARCOMEDORIAC", "PADARIA X"])
    fatura["transacoes"][0]["tipo"] = "pagamento"
    fatura["transacoes"][0]["valor_brl"] = "-100.00"
    extracao["fatura"] = fatura

    sugestoes = _sugestoes(_preview(as_user(users[0]), cartao.id))
    assert sorted(sugestoes) == [1, 2]  # a linha 0 (pagamento) não tem item
    assert sugestoes[1] == ("Alimentação", "regra")
    assert sugestoes[2] == ("Alimentação", "regra")


def test_linha_degenerada_nao_recebe_item(as_user, users, cartao, extracao):
    """Valor 0 não materializa (lixo de extração) — e portanto não tem categoria."""
    fatura = _fatura_com(["LINHA ZERADA", "IFD*DUBARCOMEDORIAC"])
    fatura["transacoes"][0]["valor_brl"] = "0.00"
    extracao["fatura"] = fatura

    assert sorted(_sugestoes(_preview(as_user(users[0]), cartao.id))) == [1]


def test_preview_nao_escreve_nada_no_banco(session, as_user, users, cartao, extracao):
    """STATELESS: a camada 1 LÊ o histórico; nada é gravado no caminho do
    preview (mesma garantia do enriquecimento do extrato)."""
    _historico(session, users[0].id, "PADARIA CENTRAL", "Lazer", quantas=2)
    extracao["fatura"] = _fatura_com(["PADARIA CENTRAL"])

    escritas: list[tuple] = []

    def _guarda(sessao, flush_context, instances):
        escritas.append((list(sessao.new), list(sessao.dirty), list(sessao.deleted)))

    event.listen(session, "before_flush", _guarda)
    try:
        resp = _preview(as_user(users[0]), cartao.id)
    finally:
        event.remove(session, "before_flush", _guarda)

    assert resp.status_code == 200
    assert escritas == [], f"o preview tentou escrever: {escritas}"


# --- Commit: o servidor decide de novo ----------------------------------------


def test_commit_sem_categoria_recomputa_no_servidor(
    session, as_user, users, cartao, extracao
):
    """MUTAÇÃO-ALVO: voltar `categoria: str = "Outros"` no schema (ou gravar
    `t.categoria` direto) faz a linha entrar como "Outros" — o estado de antes
    deste batch."""
    fatura = _fatura_com(["IFD*DUBARCOMEDORIAC"])  # sem chave "categoria"

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    tx = session.exec(select(Transacao)).one()
    assert tx.categoria == "Alimentação"


def test_commit_com_categoria_valida_e_preservada(
    session, as_user, users, cartao, extracao
):
    """Explícito VENCE — inclusive contra a sugestão. O usuário decidiu."""
    fatura = _fatura_com(["IFD*DUBARCOMEDORIAC"])
    fatura["transacoes"][0]["categoria"] = "Pets"

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    assert session.exec(select(Transacao)).one().categoria == "Pets"


def test_commit_com_outros_explicito_respeita_o_usuario(
    session, as_user, users, cartao, extracao
):
    """"Outros" MANDADO é decisão, não ausência: o servidor não o "corrige".

    É o que mantém o cliente antigo (que manda "Outros" em toda linha)
    funcionando exatamente como antes deste batch.
    """
    fatura = _fatura_com(["IFD*DUBARCOMEDORIAC"])
    fatura["transacoes"][0]["categoria"] = "Outros"

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    assert session.exec(select(Transacao)).one().categoria == "Outros"


def test_commit_com_categoria_desconhecida_cai_em_outros(
    session, as_user, users, cartao, extracao
):
    """Guarda-corpo NOVO: antes deste batch a fatura gravava a string do request
    sem revalidar (o extrato já revalidava)."""
    fatura = _fatura_com(["Blacktag"])
    fatura["transacoes"][0]["categoria"] = "Categoria Inventada"

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    assert session.exec(select(Transacao)).one().categoria == "Outros"


def test_commit_com_categoria_de_outro_usuario_cai_em_outros(
    session, as_user, users, cartao, extracao
):
    """Categoria customizada existe — mas é do OUTRO usuário."""
    session.add(
        CategoriaCustomizada(usuario_id=users[1].id, nome="Vinhos", tipo="despesa")
    )
    session.commit()
    fatura = _fatura_com(["Blacktag"])
    fatura["transacoes"][0]["categoria"] = "Vinhos"

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    assert session.exec(select(Transacao)).one().categoria == "Outros"


def test_commit_com_categoria_de_receita_cai_em_outros(
    session, as_user, users, cartao, extracao
):
    """Fatura é de crédito: o universo é DESPESA. "Salário" não é opção."""
    fatura = _fatura_com(["Blacktag"])
    fatura["transacoes"][0]["categoria"] = "Salário"

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    assert session.exec(select(Transacao)).one().categoria == "Outros"


def test_estorno_recebe_categoria_recomputada(
    session, as_user, users, cartao, extracao
):
    """O estorno é o caso que SÓ o tri-estado resolve: a tela o mostra na seção
    cinza sem seletor, então ele nunca tem categoria decidida. Antes deste batch
    ele era "Outros" para sempre."""
    fatura = _fatura_com(["IFD*DUBARCOMEDORIAC"])
    fatura["transacoes"][0]["valor_brl"] = "-50.00"

    resp = _commit(as_user(users[0]), cartao.id, fatura)
    assert resp.status_code == 200
    assert resp.json()["estornos_importados"] == 1

    estorno = session.exec(select(Transacao).where(Transacao.tipo == "estorno")).one()
    assert estorno.categoria == "Alimentação"


def test_parcelada_leva_a_categoria_para_as_parcelas(
    session, as_user, users, cartao, extracao
):
    from app.models.installment import Parcela

    fatura = _fatura_com(["IFD*DUBARCOMEDORIAC"])
    fatura["transacoes"][0]["parcela"] = {"indice": 1, "total": 3}

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    mae = session.exec(select(Transacao)).one()
    assert mae.categoria == "Alimentação"
    parcelas = session.exec(select(Parcela)).all()
    assert len(parcelas) == 3
    assert all(p.categoria == "Alimentação" for p in parcelas)


def test_commit_usa_o_historico_e_nao_so_a_regra(
    session, as_user, users, cartao, extracao
):
    """A recomputação do commit é a MESMA do preview — as duas camadas, não só
    a regra. MUTAÇÃO-ALVO: `resolver_categorias` chamando só
    `casar_categoria_detalhado` devolveria "Alimentação"."""
    _historico(session, users[0].id, "IFD*DUBARCOMEDORIAC", "Lazer", quantas=2)
    fatura = _fatura_com(["IFD*DUBARCOMEDORIAC"])

    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    tx = session.exec(
        select(Transacao).where(Transacao.origem == "importacao")
    ).one()
    assert tx.categoria == "Lazer"
