"""T-27 — data de negócio "hoje" no fuso do produto (America/Sao_Paulo).

data_pagamento auto-preenchida ao marcar parcela como paga deve vir do
helper app.core.dates.hoje (mockável) — não do relógio local do servidor.
"""

import datetime as dt

from sqlmodel import select

from app.models.installment import Parcela

from .test_transactions_router import post_parcelada

HOJE_FIXO = dt.date(2026, 6, 10)


def test_marcar_pago_preenche_data_pagamento_com_hoje_do_produto(
    session, users, as_user, mocker
):
    mocker.patch("app.routers.installments.hoje", return_value=HOJE_FIXO)
    client = as_user(users[0])
    transacao_id = post_parcelada(client).json()["id"]
    parcela = session.exec(select(Parcela).where(Parcela.transacao_id == transacao_id)).first()

    response = client.put(f"/installments/{parcela.id}", json={"pago": True})
    assert response.status_code == 200
    assert response.json()["data_pagamento"] == HOJE_FIXO.isoformat()
