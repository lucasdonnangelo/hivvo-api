import datetime as dt
import logging
import re
import time
import uuid
from decimal import Decimal, InvalidOperation

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlmodel import Session, delete, select

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.models.chat import ChatMessage
from app.models.installment import Parcela
from app.models.user import Usuario
from app.services.estatisticas import _agregar, _buscar_mes, _categorias
from app.schemas.ai import ChatRequest, ChatResponse, HistoricoItem, HistoricoResponseItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

_ZERO = Decimal("0.00")
_MODEL = "gemini-2.5-flash"
_MESES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março",    4: "Abril",
    5: "Maio",    6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}
_SAFETY = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",        threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
]


def _total_parcelas_proximo_mes(session: Session, usuario_id: int, mes: int, ano: int) -> Decimal:
    prox_mes = mes % 12 + 1
    prox_ano = ano + 1 if mes == 12 else ano
    parcelas = session.exec(
        select(Parcela).where(
            Parcela.usuario_id == usuario_id,
            Parcela.fatura_mes == prox_mes,
            Parcela.fatura_ano == prox_ano,
            Parcela.pago == False,   # noqa: E712
            Parcela.cancelado == False,  # noqa: E712
        )
    ).all()
    return sum((p.valor_parcela for p in parcelas), _ZERO)


def _variacao_saldo_pct(session: Session, usuario_id: int, mes: int, ano: int, saldo_atual: Decimal) -> float | None:
    mes_ant = 12 if mes == 1 else mes - 1
    ano_ant = ano - 1 if mes == 1 else ano
    transacoes_ant = _buscar_mes(session, usuario_id, mes_ant, ano_ant)
    rec_ant, desp_ant = _agregar(transacoes_ant)
    saldo_ant = rec_ant - desp_ant
    if saldo_ant == _ZERO:
        return None
    try:
        return float((saldo_atual - saldo_ant) / abs(saldo_ant) * 100)
    except (InvalidOperation, ZeroDivisionError):
        return None


def _build_historico_anual(session: Session, usuario_id: int, mes: int, ano: int) -> str:
    linhas: list[str] = []
    m, a = mes, ano
    for _ in range(12):
        m -= 1
        if m == 0:
            m = 12
            a -= 1
        transacoes = _buscar_mes(session, usuario_id, m, a)
        if not transacoes:
            continue
        rec, desp = _agregar(transacoes)
        saldo = rec - desp
        cats = _categorias(transacoes)[:3]
        top = ", ".join(f"{c.categoria} {c.percentual:.0f}%" for c in cats) or "—"
        linhas.append(
            f"- {_MESES[m][:3]}/{a}: "
            f"Rec R$ {rec:,.0f} | Desp R$ {desp:,.0f} | Saldo R$ {saldo:,.0f} | Top: {top}"
        )
    if not linhas:
        return ""
    return "HISTÓRICO — ÚLTIMOS 12 MESES:\n" + "\n".join(linhas)


def _build_system_instruction(
    mes: int,
    ano: int,
    ctx: dict,
    historico_anual: str = "",
    primeira_vez: bool = False,
) -> str:
    top5 = "\n".join(
        f"  - {c.categoria}: R$ {c.total:,.2f} ({c.percentual:.1f}%)"
        for c in ctx["categorias"][:5]
    ) or "  (sem despesas registradas)"

    alerta_saldo = "\n⚠️  SALDO NEGATIVO — veja regra 5 abaixo." if ctx["saldo_negativo"] else ""

    variacao_linha = ""
    if ctx.get("variacao_saldo_pct") is not None:
        sinal = "+" if ctx["variacao_saldo_pct"] >= 0 else ""
        variacao_linha = f"\n- Variação do saldo vs mês anterior: {sinal}{ctx['variacao_saldo_pct']:.1f}%"

    nome_linha = f"\n- Usuário: {ctx['usuario_nome']}" if ctx.get("usuario_nome") else ""

    historico_bloco = f"\n\n{historico_anual}" if historico_anual else ""

    if primeira_vez:
        apresentacao_bloco = (
            "\n\nCOMPORTAMENTO NESTA MENSAGEM — PRIMEIRA VEZ:\n"
            "É a primeira vez que este usuário usa o Assistente Hivvo. "
            "Apresente-se como Assistente Hivvo, explique brevemente o que você pode fazer "
            "(análise de gastos, parcelas, comparações, planejamento financeiro) "
            "e convide o usuário a fazer sua primeira pergunta. Seja caloroso mas conciso. "
            "Ignore as regras 1 e 8 apenas nesta mensagem — uma saudação breve é adequada."
        )
    else:
        apresentacao_bloco = (
            "\n\nCOMPORTAMENTO NESTA MENSAGEM — USUÁRIO RECORRENTE:\n"
            "Este usuário já usou o Assistente anteriormente. "
            "Não se apresente. Cumprimente brevemente apenas se o usuário cumprimentar. "
            "Vá direto ao ponto."
        )

    return f"""Você é o Hivvo, um analista financeiro pessoal direto e objetivo — não um assistente genérico.

DADOS FINANCEIROS — {_MESES.get(mes, mes)}/{ano}:{alerta_saldo}{nome_linha}
- Receitas:  R$ {ctx['receitas']:,.2f}
- Despesas:  R$ {ctx['despesas']:,.2f}
- Saldo:     R$ {ctx['saldo']:,.2f}{variacao_linha}
- Transações no mês: {ctx['num_transacoes']}
- Parcelas no próximo mês: R$ {ctx['parcelas_proximo_mes']:,.2f}

TOP 5 CATEGORIAS DE DESPESA:
{top5}

REGRAS DE COMPORTAMENTO:
1. NUNCA cumprimente ("Olá", "Oi", "Claro!", "Com certeza!" etc.) — vá direto ao ponto.
2. Baseie respostas APENAS nos dados acima e no histórico abaixo — nunca invente números ou extrapole.
3. Se não houver dados suficientes, diga claramente e de forma curta.
4. Se a pergunta não estiver relacionada às finanças do usuário, responda em 1-2 frases que você é especializado em análise financeira pessoal e redirecione para o contexto disponível — nunca recuse, nunca retorne vazio, nunca diga que não pode ajudar.
5. Formate valores monetários como R$ X.XXX,XX (padrão brasileiro).
6. Se despesas > receitas E a pergunta for sobre gastos, saldo ou situação financeira, abra a resposta com esse diagnóstico. Para perguntas sobre outros tópicos, mencione o saldo negativo ao final como observação.
7. Se uma categoria tiver mais de 50% das despesas totais, alerte explicitamente sobre essa concentração.
8. Tom: analista financeiro sênior. Sem elogios, sem frases de incentivo genéricas, sem condescendência.
9. Use markdown leve quando facilitar a leitura (negrito para valores, listas para múltiplos itens).
10. Seja conciso mas completo; prefira 3-5 frases diretas a listas longas.
11. Só faça uma pergunta ao usuário se a resposta permitir entregar uma análise concreta e diferente — exemplos válidos: "Quer ver por cartão ou por categoria?", "Prefere o período de 2025 ou 2026?". Nunca faça perguntas abertas sem ação possível ("Isso te preocupa?", "O que você acha?", "Você tem um plano?").
12. Use o nome do usuário apenas quando soar natural — não em toda resposta.
13. Quando o usuário iniciar a conversa com uma saudação simples (ex: "Oi", "Olá", "Boa tarde"), responda apenas com um cumprimento breve e aguarde a pergunta. Nunca retome assuntos ou dados de conversas anteriores sem que o usuário pergunte explicitamente.{apresentacao_bloco}{historico_bloco}"""


def _build_contents(historico: list[HistoricoItem], mensagem: str) -> list[types.Content]:
    # Inclui a mensagem atual no final para sanitizá-la junto com o histórico
    all_items = historico + [HistoricoItem(role="user", text=mensagem)]

    # Remove turns consecutivos do mesmo role — mantém o mais recente de cada sequência.
    # Processa em reverso: o primeiro encontrado (mais novo) vence; depois reverte.
    deduped: list[HistoricoItem] = []
    for item in reversed(all_items):
        if not deduped or deduped[-1].role != item.role:
            deduped.append(item)
    deduped.reverse()

    # Gemini exige que contents comece com role="user"
    while deduped and deduped[0].role != "user":
        deduped.pop(0)

    return [
        types.Content(
            role="model" if item.role == "assistant" else "user",
            parts=[types.Part(text=item.text)],
        )
        for item in deduped
    ]


def _post_process(texto: str) -> str:
    # Fix spacing after R$ without collapsing newlines (markdown depends on them)
    texto = re.sub(r"R\$\s*(\d)", r"R$ \1", texto)
    texto = re.sub(r"[ \t]+", " ", texto)  # collapse only horizontal whitespace
    return texto.strip()


@router.get("/historico", response_model=list[HistoricoResponseItem])
def get_historico(
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Busca a sessão mais recente do usuário e o timestamp da sua última mensagem
    row = session.execute(
        select(ChatMessage.sessao_id, func.max(ChatMessage.created_at).label("ultima"))
        .where(ChatMessage.usuario_id == current_user.id)
        .group_by(ChatMessage.sessao_id)
        .order_by(func.max(ChatMessage.created_at).desc())
        .limit(1)
    ).first()

    if not row:
        logger.info("[historico] nenhuma sessão encontrada para usuario_id=%s", current_user.id)
        return []

    logger.info("[historico] sessao_id mais recente: %s | ultima_msg: %s", row.sessao_id, row.ultima)

    if (dt.datetime.utcnow() - row.ultima) > dt.timedelta(hours=24):
        logger.info("[historico] sessão expirada (>24h) — retornando vazio")
        return []

    sessao_id_mais_recente = uuid.UUID(str(row.sessao_id))
    logger.info("[historico] buscando mensagens para sessao_id=%s (tipo=%s)", sessao_id_mais_recente, type(sessao_id_mais_recente))

    mensagens = session.exec(
        select(ChatMessage)
        .where(
            ChatMessage.usuario_id == current_user.id,
            ChatMessage.sessao_id == sessao_id_mais_recente,
        )
        .order_by(ChatMessage.created_at)
    ).all()

    logger.info("[historico] total de mensagens encontradas: %d", len(mensagens))
    for m in mensagens:
        logger.info("[historico]   role=%s | sessao_id=%s | text=%.60s", m.role, m.sessao_id, m.text)

    return [
        HistoricoResponseItem(role=m.role, text=m.text, created_at=m.created_at)
        for m in mensagens
    ]


@router.delete("/historico", status_code=204)
def delete_historico(
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    session.exec(delete(ChatMessage).where(ChatMessage.usuario_id == current_user.id))
    session.commit()
    return Response(status_code=204)


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Serviço de IA indisponível: GEMINI_API_KEY não configurada.",
        )

    sessao_uuid = uuid.UUID(body.sessao_id)

    # Busca as últimas 50 mensagens do banco (todas as sessões) para contexto da IA
    historico_db = session.exec(
        select(ChatMessage)
        .where(ChatMessage.usuario_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(50)
    ).all()
    historico_db = list(reversed(historico_db))  # ordena ASC para o Gemini

    # primeira_vez = nenhuma mensagem ainda nesta sessão
    count_sessao = session.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.usuario_id == current_user.id,
            ChatMessage.sessao_id == sessao_uuid,
        )
    ).scalar()
    primeira_vez = count_sessao == 0

    transacoes = _buscar_mes(session, current_user.id, body.mes, body.ano)
    receitas, despesas = _agregar(transacoes)

    saldo = receitas - despesas
    ctx = {
        "receitas": receitas,
        "despesas": despesas,
        "saldo": saldo,
        "saldo_negativo": saldo < _ZERO,
        "num_transacoes": len(transacoes),
        "categorias": _categorias(transacoes),
        "parcelas_proximo_mes": _total_parcelas_proximo_mes(
            session, current_user.id, body.mes, body.ano
        ),
        "usuario_nome": current_user.username,
        "variacao_saldo_pct": _variacao_saldo_pct(
            session, current_user.id, body.mes, body.ano, saldo
        ),
    }

    historico_anual = _build_historico_anual(session, current_user.id, body.mes, body.ano)
    system_instruction = _build_system_instruction(
        body.mes, body.ano, ctx, historico_anual, primeira_vez
    )
    historico_items = [HistoricoItem(role=m.role, text=m.text) for m in historico_db]
    contents = _build_contents(historico_items, body.mensagem)

    _RETRY_WAITS = [2, 4, 6, 8, 10]  # backoff linear entre 5 tentativas

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    texto: str | None = None
    for attempt in range(1, 6):  # até 5 tentativas
        try:
            response = client.models.generate_content(
                model=_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    safety_settings=_SAFETY,
                ),
            )
            if not response.text:
                raise HTTPException(
                    status_code=503,
                    detail="A IA não gerou resposta. Tente reformular a pergunta.",
                )
            texto = _post_process(response.text)
            break
        except HTTPException:
            raise
        except genai_errors.ServerError as e:
            if attempt < 5:
                wait = _RETRY_WAITS[attempt - 1]
                logger.warning("[chat] Gemini 503, tentativa %d/5 — aguardando %ds", attempt, wait)
                time.sleep(wait)
                continue
            logger.exception("Gemini 503 após 5 tentativas: %s", e)
            raise HTTPException(
                status_code=503,
                detail="Serviço de IA temporariamente indisponível. Tente novamente em instantes.",
            )
        except Exception as e:
            logger.exception("Gemini request failed — traceback completo: %s", e)
            raise HTTPException(
                status_code=503,
                detail="Serviço de IA temporariamente indisponível. Tente novamente em instantes.",
            )

    # Salva user + assistant atomicamente — só persiste se o Gemini respondeu com sucesso
    session.add(ChatMessage(
        usuario_id=current_user.id,
        role="user",
        text=body.mensagem,
        sessao_id=sessao_uuid,
    ))
    session.add(ChatMessage(
        usuario_id=current_user.id,
        role="assistant",
        text=texto,
        sessao_id=sessao_uuid,
    ))
    session.commit()

    return ChatResponse(resposta=texto)
