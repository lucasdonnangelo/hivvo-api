#!/usr/bin/env python3
"""
populate_db.py — Popula o banco Hivvo com dados realistas de teste.

Usuário-alvo : lucasjrdonnangelo@gmail.com
Período      : outubro/2025 → junho/2026
Idempotente  : verifica (usuario_id, descricao, data, valor) antes de inserir.

Uso:
    python populate_db.py
"""

import sys
import calendar
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dotenv import load_dotenv

# Script vive em scripts/ — a raiz do projeto (.env, pacote app/) está um nível acima
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import os
from sqlmodel import create_engine, Session, select

# sys.path garante importação dos models quando rodado de qualquer diretório
sys.path.insert(0, str(PROJECT_ROOT))

# T-06: nunca rodar seed contra o banco de produção
if os.environ.get("ENVIRONMENT") == "production":
    sys.exit("Abortado: populate_db.py não roda com ENVIRONMENT=production (script de seed de desenvolvimento).")

from app.models.user import Usuario
from app.models.card import Cartao
from app.models.transaction import Transacao
from app.models.installment import Parcela
# T-06: helpers de fatura consolidados em app/services (eram cópias locais idênticas).
# _criar_parcelas permanece local de propósito: diverge para marcar parcela passada como paga.
from app.services.faturas import _add_months, _data_vencimento_parcela, _fatura_cartao_avulso

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL não encontrado no .env")

engine = create_engine(DATABASE_URL, echo=False)

TARGET_EMAIL = "lucasjrdonnangelo@gmail.com"
TODAY = dt.date(2026, 6, 5)


def _criar_parcelas(session: Session, transacao: Transacao, card: Cartao | None) -> int:
    total = transacao.total_parcelas
    valor_base = (transacao.valor / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    valor_ultima = (transacao.valor - valor_base * (total - 1)).quantize(Decimal("0.01"))

    for i in range(1, total + 1):
        valor_parcela = valor_ultima if i == total else valor_base
        data_venc = _data_vencimento_parcela(transacao.data, i, card)

        parcela = Parcela(
            usuario_id=transacao.usuario_id,
            transacao_id=transacao.id,
            numero_parcela=i,
            total_parcelas=total,
            valor_parcela=valor_parcela,
            data_vencimento=data_venc,
            fatura_mes=data_venc.month,
            fatura_ano=data_venc.year,
            descricao=f"{transacao.descricao} ({i}/{total})",
            categoria=transacao.categoria,
            cartao_id=transacao.cartao_id,
        )
        session.add(parcela)

    session.commit()
    return total


# ── Definição dos cartões ─────────────────────────────────────────────────────

CARDS_DATA = [
    {
        "nome": "Nubank Roxo",
        "tipo": "Crédito",
        "limite": Decimal("8000.00"),
        "dia_vencimento": 10,
        "dia_fechamento": 3,
    },
    {
        "nome": "Itaú Personnalité",
        "tipo": "Crédito",
        "limite": Decimal("15000.00"),
        "dia_vencimento": 20,
        "dia_fechamento": 13,
    },
    {
        "nome": "Inter Gold",
        "tipo": "Crédito",
        "limite": Decimal("5000.00"),
        "dia_vencimento": 5,
        "dia_fechamento": 28,
    },
]


# ── Construção das transações ─────────────────────────────────────────────────

MONTHS = [
    (2025, 10), (2025, 11), (2025, 12),
    (2026, 1),  (2026, 2),  (2026, 3),
    (2026, 4),  (2026, 5),  (2026, 6),
]


def build_transactions(uid: int, cards: dict[str, int]) -> list[dict]:
    nubank = cards["Nubank Roxo"]
    itau   = cards["Itaú Personnalité"]
    inter  = cards["Inter Gold"]

    txns: list[dict] = []

    def add(tipo, data, descricao, valor, categoria, forma_pagamento,
            tipo_gasto="Variável", cartao_id=None, parcelado=False, total_parcelas=None):
        if data > TODAY:
            return  # não cria transações futuras
        txns.append({
            "tipo": tipo,
            "data": data,
            "descricao": descricao,
            "valor": Decimal(str(valor)),
            "categoria": categoria,
            "forma_pagamento": forma_pagamento,
            "tipo_gasto": tipo_gasto,
            "cartao_id": cartao_id,
            "parcelado": parcelado,
            "total_parcelas": total_parcelas,
        })

    # ── Recorrentes mensais ───────────────────────────────────────────────────
    for year, month in MONTHS:
        last = calendar.monthrange(year, month)[1]

        add("receita", dt.date(year, month, 5),  "Salário",           "12000.00", "Outros",      "Pix",    "Fixo")
        add("despesa", dt.date(year, month, 10), "Aluguel",           "2800.00",  "Moradia",     "Débito", "Fixo")
        add("despesa", dt.date(year, month, 10), "Condomínio",        "450.00",   "Moradia",     "Débito", "Fixo")
        add("despesa", dt.date(year, month, 8),  "Supermercado",      "380.00",   "Alimentação", "Débito")
        add("despesa", dt.date(year, month, min(22, last)), "Supermercado", "290.00", "Alimentação", "Débito")
        add("despesa", dt.date(year, month, 15), "Netflix",           "55.90",    "Assinaturas", "Crédito", "Fixo", nubank)
        add("despesa", dt.date(year, month, 15), "Spotify",           "21.90",    "Assinaturas", "Crédito", "Fixo", nubank)
        add("despesa", dt.date(year, month, 5),  "Academia Smart Fit","120.00",   "Saúde",       "Débito", "Fixo")
        add("despesa", dt.date(year, month, 1),  "Plano de Saúde Amil","380.00",  "Saúde",       "Débito", "Fixo")

    # ── Uber/99 ───────────────────────────────────────────────────────────────
    uber_rides = [
        (2025,10, 3,"28.50"), (2025,10, 9,"34.00"), (2025,10,17,"22.00"), (2025,10,28,"41.50"),
        (2025,11, 5,"19.50"), (2025,11,14,"32.00"), (2025,11,28,"38.50"),
        (2025,12, 4,"25.00"), (2025,12,12,"18.50"), (2025,12,19,"45.00"), (2025,12,30,"29.00"),
        (2026, 1, 7,"31.50"), (2026, 1,18,"27.00"), (2026, 1,26,"44.00"),
        (2026, 2, 3,"23.00"), (2026, 2,12,"36.50"), (2026, 2,22,"28.00"), (2026, 2,26,"19.00"),
        (2026, 3, 4,"33.50"), (2026, 3,16,"26.00"), (2026, 3,29,"40.00"),
        (2026, 4, 2,"21.50"), (2026, 4,13,"35.00"), (2026, 4,21,"29.50"), (2026, 4,30,"43.00"),
        (2026, 5, 8,"38.00"), (2026, 5,19,"24.50"), (2026, 5,29,"31.00"),
        (2026, 6, 2,"27.50"),
    ]
    for y, m, d, v in uber_rides:
        add("despesa", dt.date(y, m, d), "Uber", v, "Transporte", "Débito")

    # ── Transações avulsas variadas ───────────────────────────────────────────
    # Formato: (ano, mês, dia, descricao, valor, categoria, forma_pagamento, cartao_id)
    # Receitas extras: adicionar "receita" como 9º elemento
    avulsas = [
        # Outubro 2025
        (2025,10, 7,"Restaurante Outback",     "125.00","Alimentação","Crédito", nubank),
        (2025,10,14,"iFood",                    "67.90","Alimentação","Débito",  None),
        (2025,10, 9,"Farmácia Drogasil",        "89.00","Saúde",      "Débito",  None),
        (2025,10,11,"Posto Ipiranga",           "210.00","Transporte", "Débito",  None),
        (2025,10,25,"Posto Shell",              "195.00","Transporte", "Débito",  None),
        (2025,10,18,"Zara",                     "320.00","Compras",   "Crédito", nubank),
        (2025,10,26,"Bar do Zé",                "85.00","Lazer",      "Débito",  None),
        (2025,10,19,"Cinema Cinemark",          "54.00","Lazer",      "Débito",  None),
        (2025,10,28,"Freelance Design",        "2500.00","Outros",    "Pix",     None, "receita"),

        # Novembro 2025
        (2025,11, 8,"Restaurante Outback",     "156.00","Alimentação","Crédito", itau),
        (2025,11,16,"iFood",                    "78.50","Alimentação","Débito",  None),
        (2025,11, 6,"Farmácia Drogasil",        "45.00","Saúde",      "Débito",  None),
        (2025,11,12,"Posto Ipiranga",           "235.00","Transporte", "Débito",  None),
        (2025,11,27,"Posto Shell",              "220.00","Transporte", "Débito",  None),
        (2025,11,23,"Nike Store",               "480.00","Compras",   "Crédito", itau),
        (2025,11,22,"Happy Hour Central",       "110.00","Lazer",     "Pix",     None),
        (2025,11,18,"Livro Clean Code",          "89.90","Educação",  "Crédito", nubank),

        # Dezembro 2025
        (2025,12, 6,"Restaurante Fogo de Chão","145.00","Alimentação","Crédito", nubank),
        (2025,12,21,"iFood",                    "92.00","Alimentação","Débito",  None),
        (2025,12, 4,"Farmácia Droga Raia",      "112.00","Saúde",     "Débito",  None),
        (2025,12,10,"Posto Ipiranga",           "245.00","Transporte", "Débito",  None),
        (2025,12,23,"Posto Shell",              "230.00","Transporte", "Débito",  None),
        (2025,12,15,"Shopping — presente natal","540.00","Compras",   "Crédito", itau),
        (2025,12,28,"Bar réveillon",            "145.00","Lazer",     "Débito",  None),
        (2025,12,20,"Cinema Cinemark",           "68.00","Lazer",     "Débito",  None),
        (2025,12,16,"Reembolso empresa",        "850.00","Outros",    "Pix",     None, "receita"),

        # Janeiro 2026
        (2026, 1,11,"Restaurante Ki-Sushi",     "133.00","Alimentação","Crédito", inter),
        (2026, 1,19,"iFood",                     "58.90","Alimentação","Débito",  None),
        (2026, 1,13,"Farmácia Drogasil",         "75.00","Saúde",     "Débito",  None),
        (2026, 1, 8,"Posto Ipiranga",            "188.00","Transporte","Débito",  None),
        (2026, 1,24,"Posto Shell",               "202.00","Transporte","Débito",  None),
        (2026, 1,17,"Adidas Store",              "289.00","Compras",  "Crédito", nubank),
        (2026, 1,25,"Cinema Cinemark",            "44.00","Lazer",    "Débito",  None),
        (2026, 1,22,"Udemy",                     "149.90","Educação", "Crédito", nubank),

        # Fevereiro 2026
        (2026, 2,14,"Restaurante italiano",     "168.00","Alimentação","Crédito", itau),
        (2026, 2,20,"iFood",                     "71.50","Alimentação","Débito",  None),
        (2026, 2, 9,"Farmácia Droga Raia",       "98.00","Saúde",     "Débito",  None),
        (2026, 2, 7,"Posto Ipiranga",            "215.00","Transporte","Débito",  None),
        (2026, 2,21,"Posto Shell",               "198.00","Transporte","Débito",  None),
        (2026, 2,15,"Arezzo sapatos",            "399.00","Compras",  "Crédito", nubank),
        (2026, 2,28,"Bar do Thiago",              "75.00","Lazer",    "Pix",     None),
        (2026, 2,11,"Livro Atomic Habits",        "62.90","Educação", "Crédito", nubank),

        # Março 2026
        (2026, 3, 7,"Restaurante Fogo de Chão", "178.00","Alimentação","Crédito", itau),
        (2026, 3,18,"iFood",                     "85.00","Alimentação","Débito",  None),
        (2026, 3,14,"Farmácia Drogasil",         "55.00","Saúde",     "Débito",  None),
        (2026, 3, 9,"Posto Ipiranga",            "225.00","Transporte","Débito",  None),
        (2026, 3,22,"Posto Shell",               "212.00","Transporte","Débito",  None),
        (2026, 3,21,"Renner",                    "245.00","Compras",  "Crédito", nubank),
        (2026, 3,27,"Happy Hour",                 "95.00","Lazer",    "Débito",  None),
        (2026, 3,15,"Freelance Dev",            "3200.00","Outros",   "Pix",     None, "receita"),

        # Abril 2026
        (2026, 4, 5,"Restaurante Coco Bambu",   "142.00","Alimentação","Crédito", inter),
        (2026, 4,17,"iFood",                     "64.90","Alimentação","Débito",  None),
        (2026, 4,11,"Farmácia Droga Raia",       "108.00","Saúde",    "Débito",  None),
        (2026, 4, 8,"Posto Ipiranga",            "240.00","Transporte","Débito",  None),
        (2026, 4,22,"Posto Shell",               "218.00","Transporte","Débito",  None),
        (2026, 4,19,"C&A jaqueta",               "520.00","Compras",  "Crédito", itau),
        (2026, 4,12,"Cinema Cinemark",            "48.00","Lazer",    "Débito",  None),
        (2026, 4,26,"Bar happy hour",            "130.00","Lazer",    "Pix",     None),
        (2026, 4, 3,"Alura assinatura anual",    "299.00","Educação", "Crédito", nubank),

        # Maio 2026
        (2026, 5,10,"Restaurante Outback",       "115.00","Alimentação","Crédito", nubank),
        (2026, 5,22,"iFood",                      "73.00","Alimentação","Débito",  None),
        (2026, 5,16,"Farmácia Drogasil",          "67.00","Saúde",    "Débito",  None),
        (2026, 5, 6,"Posto Ipiranga",            "230.00","Transporte","Débito",  None),
        (2026, 5,20,"Posto Shell",               "205.00","Transporte","Débito",  None),
        (2026, 5,14,"Netshoes tênis",            "389.00","Compras",  "Crédito", itau),
        (2026, 5,24,"Happy hour",                 "88.00","Lazer",    "Débito",  None),
        (2026, 5, 3,"Amazon Prime",               "59.90","Assinaturas","Crédito",nubank),

        # Junho 2026 (até dia 05)
        (2026, 6, 2,"iFood",                      "89.00","Alimentação","Débito", None),
        (2026, 6, 3,"Posto Shell",               "195.00","Transporte", "Débito", None),
        (2026, 6, 4,"Farmácia Drogasil",          "48.00","Saúde",     "Débito", None),
        (2026, 6, 4,"Reembolso médico",          "450.00","Outros",    "Pix",    None, "receita"),
    ]

    for item in avulsas:
        if len(item) == 8:
            y, m, d, desc, val, cat, forma, cid = item
            tipo = "despesa"
        else:
            y, m, d, desc, val, cat, forma, cid, tipo = item
        add(tipo, dt.date(y, m, d), desc, val, cat, forma, cartao_id=cid)

    # ── Parcelamentos ─────────────────────────────────────────────────────────
    parcelados = [
        # MacBook Pro 12x R$1.000 — Itaú — compra: 20/11/2025 (após fechamento dia 13)
        # → fatura a partir de jan/2026; parcelas 1-5 pagas, 6-12 futuras
        dict(data=dt.date(2025,11,20), descricao="MacBook Pro M3",      valor="12000.00", n=12, cid=itau,  cat="Compras"),
        # iPhone 15 6x R$1.000 — Nubank — compra: 15/10/2025 (após fechamento dia 3)
        # → fatura a partir de dez/2025; todas as 6 parcelas pagas
        dict(data=dt.date(2025,10,15), descricao="iPhone 15",           valor="6000.00",  n=6,  cid=nubank, cat="Compras"),
        # TV Samsung 9x R$500 — Inter — compra: 10/12/2025 (antes fechamento dia 28)
        # → fatura a partir de jan/2026; parcelas 1-5 pagas, 6-9 futuras
        dict(data=dt.date(2025,12,10), descricao='Televisão Samsung 65"', valor="4500.00", n=9, cid=inter, cat="Compras"),
        # Curso de Inglês 12x R$200 — Nubank — compra: 20/01/2026 (após fechamento dia 3)
        # → fatura a partir de mar/2026; parcelas 1-3 pagas, 4-12 futuras
        dict(data=dt.date(2026, 1,20), descricao="Curso de Inglês",     valor="2400.00",  n=12, cid=nubank, cat="Educação"),
        # Viagem Buenos Aires 4x R$800 — Itaú — compra: 05/03/2026 (antes fechamento dia 13)
        # → fatura a partir de abr/2026; parcelas 1-2 pagas, 3-4 futuras
        dict(data=dt.date(2026, 3, 5), descricao="Viagem Buenos Aires", valor="3200.00",  n=4,  cid=itau,  cat="Lazer"),
        # Notebook Dell 3x R$1.200 — Itaú — compra: 15/04/2026 (após fechamento dia 13)
        # → fatura a partir de jun/2026; todas futuras
        dict(data=dt.date(2026, 4,15), descricao="Notebook Dell XPS",   valor="3600.00",  n=3,  cid=itau,  cat="Compras"),
    ]

    for p in parcelados:
        add(
            "despesa", p["data"], p["descricao"], p["valor"], p["cat"],
            "Crédito", cartao_id=p["cid"],
            parcelado=True, total_parcelas=p["n"],
        )

    return txns


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    with Session(engine) as session:

        # 1. Buscar usuário
        user = session.exec(
            select(Usuario).where(Usuario.email == TARGET_EMAIL)
        ).first()
        if not user:
            sys.exit(
                f"\nUsuário '{TARGET_EMAIL}' não encontrado.\n"
                "Crie a conta pelo app antes de rodar este script."
            )
        uid = user.id
        print(f"[OK] Usuario: {user.nome_completo} <{user.email}> (id={uid})")

        # 2. Criar / localizar cartões
        card_ids: dict[str, int] = {}
        print("\nCartoes:")
        for c in CARDS_DATA:
            existing = session.exec(
                select(Cartao).where(
                    Cartao.usuario_id == uid,
                    Cartao.nome == c["nome"],
                )
            ).first()
            if existing:
                card_ids[c["nome"]] = existing.id
                print(f"  - '{c['nome']}' ja existe (id={existing.id})")
            else:
                card = Cartao(usuario_id=uid, **c)
                session.add(card)
                session.commit()
                session.refresh(card)
                card_ids[c["nome"]] = card.id
                print(f"  + '{c['nome']}' criado (id={card.id})")

        # 3. Gerar lista de transações
        all_txns = build_transactions(uid, card_ids)

        # 4. Inserir transações (idempotente)
        created = skipped = total_parcelas_criadas = 0
        card_totals: dict[int, Decimal] = {}

        print(f"\nInserindo {len(all_txns)} transações...")

        for t in all_txns:
            exists = session.exec(
                select(Transacao).where(
                    Transacao.usuario_id  == uid,
                    Transacao.descricao   == t["descricao"],
                    Transacao.data        == t["data"],
                    Transacao.valor       == t["valor"],
                )
            ).first()
            if exists:
                skipped += 1
                continue

            card = None
            if t["cartao_id"]:
                card = session.get(Cartao, t["cartao_id"])

            fatura_mes = fatura_ano = None
            if not t["parcelado"] and card and card.dia_vencimento:
                fatura_mes, fatura_ano = _fatura_cartao_avulso(t["data"], card)

            transacao = Transacao(
                usuario_id      = uid,
                tipo            = t["tipo"],
                data            = t["data"],
                descricao       = t["descricao"],
                valor           = t["valor"],
                categoria       = t["categoria"],
                forma_pagamento = t["forma_pagamento"],
                tipo_gasto      = t["tipo_gasto"],
                origem          = "manual",
                cartao_id       = t["cartao_id"],
                parcelado       = t["parcelado"],
                total_parcelas  = t["total_parcelas"],
                fatura_mes      = fatura_mes,
                fatura_ano      = fatura_ano,
            )
            session.add(transacao)
            session.commit()
            session.refresh(transacao)
            created += 1

            if t["cartao_id"] and t["tipo"] == "despesa":
                cid = t["cartao_id"]
                card_totals[cid] = card_totals.get(cid, Decimal("0")) + t["valor"]

            if t["parcelado"]:
                n = _criar_parcelas(session, transacao, card)
                total_parcelas_criadas += n

        # 5. Resumo final
        print()
        print("=" * 58)
        print("  RESUMO DA POPULAÇÃO DO BANCO")
        print("=" * 58)
        print(f"  Transações criadas : {created}")
        print(f"  Transações puladas : {skipped}  (já existiam)")
        print(f"  Parcelas criadas   : {total_parcelas_criadas}")
        print()
        print("  Despesas no cartão (soma das transações criadas):")
        for nome, cid in card_ids.items():
            total = card_totals.get(cid, Decimal("0"))
            print(f"    {nome:<22} R$ {total:>10,.2f}")
        print("=" * 58)


if __name__ == "__main__":
    main()
