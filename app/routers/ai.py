import logging
import re
from decimal import Decimal, InvalidOperation

from google import genai
from google.genai import types
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.models.installment import Parcela
from app.models.user import Usuario
from app.routers.statistics import _agregar, _buscar_mes, _categorias
from app.schemas.ai import ChatRequest, ChatResponse, HistoricoItem

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


def _build_system_instruction(mes: int, ano: int, ctx: dict, historico_anual: str = "") -> str:
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
12. Use o nome do usuário apenas quando soar natural — não em toda resposta.{historico_bloco}"""


def _build_contents(historico: list[HistoricoItem], mensagem: str) -> list[types.Content]:
    contents: list[types.Content] = []
    for item in historico:
        gemini_role = "model" if item.role == "assistant" else "user"
        contents.append(types.Content(role=gemini_role, parts=[types.Part(text=item.text)]))
    contents.append(types.Content(role="user", parts=[types.Part(text=mensagem)]))
    return contents


def _post_process(texto: str) -> str:
    # Fix spacing after R$ without collapsing newlines (markdown depends on them)
    texto = re.sub(r"R\$\s*(\d)", r"R$ \1", texto)
    texto = re.sub(r"[ \t]+", " ", texto)  # collapse only horizontal whitespace
    return texto.strip()


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
    system_instruction = _build_system_instruction(body.mes, body.ano, ctx, historico_anual)
    contents = _build_contents(body.historico, body.mensagem)

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Gemini request failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Serviço de IA temporariamente indisponível. Tente novamente em instantes.",
        )

    return ChatResponse(resposta=texto)
