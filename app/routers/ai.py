import logging
import re
from decimal import Decimal

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
from app.schemas.ai import ChatRequest, ChatResponse

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


def _build_prompt(mensagem: str, mes: int, ano: int, ctx: dict) -> str:
    top5 = "\n".join(
        f"  - {c.categoria}: R$ {c.total:,.2f} ({c.percentual}%)"
        for c in ctx["categorias"][:5]
    ) or "  (sem despesas registradas)"

    return f"""Você é o BeeFree, um assistente financeiro pessoal inteligente e objetivo.

DADOS FINANCEIROS DO USUÁRIO — {_MESES.get(mes, mes)}/{ano}:
- Receitas: R$ {ctx['receitas']:,.2f}
- Despesas: R$ {ctx['despesas']:,.2f}
- Saldo: R$ {ctx['saldo']:,.2f}
- Número de transações: {ctx['num_transacoes']}
- Total de parcelas no próximo mês: R$ {ctx['parcelas_proximo_mes']:,.2f}

TOP 5 CATEGORIAS DE DESPESA:
{top5}

REGRAS:
1. Baseie respostas APENAS nos dados acima.
2. Nunca invente números ou informações ausentes.
3. Se não houver dados suficientes, diga claramente.
4. Formate valores como R$ X.XXX,XX (vírgula para centavos).
5. Seja conciso (máximo 150 palavras).
6. Finalize com uma pergunta contextual curta.

PERGUNTA DO USUÁRIO:
{mensagem}"""


def _post_process(texto: str) -> str:
    texto = re.sub(r"R\$\s*(\d)", r"R$ \1", texto)
    texto = re.sub(r"\s+", " ", texto)
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

    ctx = {
        "receitas": receitas,
        "despesas": despesas,
        "saldo": receitas - despesas,
        "num_transacoes": len(transacoes),
        "categorias": _categorias(transacoes),
        "parcelas_proximo_mes": _total_parcelas_proximo_mes(
            session, current_user.id, body.mes, body.ano
        ),
    }

    prompt = _build_prompt(body.mensagem, body.mes, body.ano, ctx)

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(safety_settings=_SAFETY),
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
