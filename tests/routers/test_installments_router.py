"""PUT /installments/{id} — o write de `pago` MORREU na Leva 2.

Pagamento agora é por FATURA (PUT /invoices/{cartao_id}/{ano}/{mes}/pagamento,
PagamentoFatura); mandar `pago`/`data_pagamento` na parcela vira 422 explícito
(extra="forbid" no ParcelaUpdate — as colunas foram dropadas na Fase 2 do #8).
Os campos restantes (cancelado, data_vencimento) seguem funcionando.
"""

from sqlmodel import select

from app.models.installment import Parcela

from .test_transactions_router import post_parcelada


def _primeira_parcela(session, client):
    transacao_id = post_parcelada(client).json()["id"]
    return session.exec(
        select(Parcela).where(Parcela.transacao_id == transacao_id)
    ).first()


def test_put_com_pago_rejeitado_422(session, users, as_user):
    client = as_user(users[0])
    parcela = _primeira_parcela(session, client)

    response = client.put(f"/installments/{parcela.id}", json={"pago": True})
    assert response.status_code == 422


def test_put_com_data_pagamento_rejeitado_422(session, users, as_user):
    client = as_user(users[0])
    parcela = _primeira_parcela(session, client)

    response = client.put(
        f"/installments/{parcela.id}", json={"data_pagamento": "2026-06-10"}
    )
    assert response.status_code == 422


def test_campos_restantes_seguem_editaveis(session, users, as_user):
    # cancelado e data_vencimento ficaram no ParcelaUpdate (rota viva).
    client = as_user(users[0])
    parcela = _primeira_parcela(session, client)

    response = client.put(
        f"/installments/{parcela.id}", json={"data_vencimento": "2026-09-05"}
    )
    assert response.status_code == 200
    assert response.json()["data_vencimento"] == "2026-09-05"

    response = client.put(f"/installments/{parcela.id}", json={"cancelado": True})
    assert response.status_code == 200
    assert response.json()["cancelado"] is True
