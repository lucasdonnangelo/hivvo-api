"""Gera as SEMENTES do harness do hivvo-web a partir de payloads REAIS.

O `dev/harness.tsx` do hivvo-web monta o AddTransactionPage de verdade e semeia
o cache do TanStack Query por queryKey (sem rede, sem axios). As sementes têm de
vir do que a API DEVOLVE, nunca da interface TypeScript: a interface é o que a
gente acha, o payload é o que é. Escrever o mock "pela interface" verifica
ficção com cara de verde — e aqui isso já ia acontecer: as categorias PADRÃO
voltam com `id: null` e `criado_em: null`, e um mock inventado teria posto ids.

Sobe o app real sobre o SQLite in-memory da suíte (o mesmo do conftest — NUNCA o
banco do .env, ver REGRAS PERMANENTES em docs/PENDENCIAS_PRIORIZADAS.md), semeia
dois cartões e duas transações, e grava o JSON de cada endpoint com a queryKey
correspondente no rótulo.

    PYTHONPATH=. venv/Scripts/python.exe scripts/capturar_sementes_harness.py

Reexecute quando o CONTRATO de um desses endpoints mudar — senão o harness passa
a verificar um payload que a API não devolve mais.
"""

import datetime as dt
import json
import os
from decimal import Decimal

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.models  # noqa: F401,E402
from app.core.auth import get_current_user  # noqa: E402
from app.core.database import get_session  # noqa: E402
from app.models.card import Cartao  # noqa: E402
from app.models.transaction import Transacao  # noqa: E402
from app.models.user import Usuario  # noqa: E402
from main import app  # noqa: E402

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
SQLModel.metadata.create_all(engine)
session = Session(engine)

user = Usuario(
    email="semente@hivvo.test", username="semente", senha_hash="x",
    nome_completo="Semente do harness",
)
session.add(user)
session.commit()
session.refresh(user)

session.add(
    Cartao(
        usuario_id=user.id, nome="Nubank", tipo="Crédito",
        dia_vencimento=13, dia_fechamento=6, mes_offset_vencimento=1,
    )
)
session.add(
    Cartao(
        usuario_id=user.id, nome="Itaú Visa Infinite", tipo="Ambos",
        dia_vencimento=8, dia_fechamento=1, mes_offset_vencimento=0,
    )
)
# Um mês com movimento, para o /statistics/monthly não vir todo zero (o preview
# do AddTransactionPage mostra "Saldo estimado após transação" só com saldo != null).
session.add(
    Transacao(
        usuario_id=user.id, tipo="receita", data=dt.date(2026, 8, 5),
        descricao="Salário", valor=Decimal("6200.00"), categoria="Salário",
        forma_pagamento="PIX",
    )
)
session.add(
    Transacao(
        usuario_id=user.id, tipo="despesa", data=dt.date(2026, 8, 7),
        descricao="Mercado", valor=Decimal("432.10"), categoria="Alimentação",
        forma_pagamento="Débito",
    )
)
session.commit()

app.dependency_overrides[get_session] = lambda: session
app.dependency_overrides[get_current_user] = lambda: user
client = TestClient(app, base_url="http://testserver/api/v1")

capturas = {
    "['cards']  <- GET /cards": client.get("/cards"),
    "['categories','despesa']  <- GET /categories?tipo=despesa":
        client.get("/categories", params={"tipo": "despesa"}),
    "['categories','receita']  <- GET /categories?tipo=receita":
        client.get("/categories", params={"tipo": "receita"}),
    "['statistics','monthly',8,2026]  <- GET /statistics/monthly?mes=8&ano=2026":
        client.get("/statistics/monthly", params={"mes": 8, "ano": 2026}),
}

import pathlib  # noqa: E402

# destino: o dev/ do repo IRMÃO (o harness vive lá; este script vive aqui
# porque só daqui dá para subir a API).
saida = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "hivvo-web" / "dev" / "sementes-capturadas.json"
)
saida.write_text(
    json.dumps(
        {rotulo: resp.json() for rotulo, resp in capturas.items()},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print("status:", {r.split("<-")[0].strip(): resp.status_code for r, resp in capturas.items()})
print("escrito em", saida)
