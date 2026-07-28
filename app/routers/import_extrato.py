"""Importação de EXTRATO de conta — preview STATELESS (Batches 1 e 2).

POST /import/extrato/preview: PDF de extrato de conta -> JSON extraído (schema
portado do spike, com o achado do rendimento) + bloco de reconciliação (balance
walk) + ENRIQUECIMENTO por linha (Batch 2: categoria sugerida, fatura proposta,
flag de recorrência — ver services/import_extrato/enriquecimento.py). NADA é
persistido — nem o arquivo, nem o resultado: processa em memória e descarta; o
enriquecimento só LÊ o banco. SEM cartao_id (o extrato é da CONTA, não de um
cartão). A revisão e o commit (materialização) são os batches seguintes.

Espelha o preview de fatura (app/routers/import_fatura.py) e reusa o encanamento
validado: o extrator de PDF (extracao_pdf), o client Gemini com
GEMINI_IMPORT_API_KEY + SAFETY_SETTINGS, e o padrão de reconciliação em Decimal.

PII/logs: o texto do extrato NUNCA vai para log — apenas metadados (bytes,
páginas, chars, nº de linhas, aplicavel, bate). Reconciliação NÃO bater não é
erro HTTP: devolve 200 com bate=false e o cliente decide.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlmodel import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.core.rate_limit import _user_or_ip_key, limiter
from app.models.user import Usuario
from app.schemas.import_extrato import ExtratoExtraido, ExtratoPreviewResponse, ReconciliacaoExtratoOut
from app.services.import_extrato import enriquecimento, gemini, redacao
from app.services.import_extrato.reconciliacao import TOLERANCIA, reconciliar

# Reúso do extrator de PDF da fatura — é infra genérica (extração da camada de
# texto, sem OCR), não tem nada de fatura. Um lugar só (ver PENDENCIAS: promover
# para módulo neutro é polimento, não bloqueia).
from app.services.import_fatura import extracao_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])

_DETAIL_ARQUIVO_INVALIDO = "Arquivo inválido: envie um PDF de extrato de conta."


def _ler_pdf(request: Request, arquivo: UploadFile) -> bytes:
    limite = settings.IMPORT_MAX_PDF_BYTES
    detail_413 = f"Arquivo excede o limite de {limite // (1024 * 1024)} MB."

    # Rejeição rápida pelo Content-Length (é o corpo multipart inteiro, então
    # com folga para o overhead) — mas o header não é confiável: o teto real é
    # confirmado lendo no máximo limite+1 bytes.
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > limite + 64 * 1024:
        raise HTTPException(status_code=413, detail=detail_413)

    dados = arquivo.file.read(limite + 1)
    if len(dados) > limite:
        raise HTTPException(status_code=413, detail=detail_413)
    # Magic bytes, não content-type (que o cliente pode mentir).
    if not dados.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail=_DETAIL_ARQUIVO_INVALIDO)
    return dados


@router.post("/extrato/preview", response_model=ExtratoPreviewResponse)
# Custo real (tier pago): mesmos limites do preview de fatura.
@limiter.limit("10/minute")
@limiter.limit("5/minute", key_func=_user_or_ip_key)
@limiter.limit("150/day", key_func=_user_or_ip_key)
def preview_extrato(
    request: Request,
    arquivo: UploadFile = File(...),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not settings.GEMINI_IMPORT_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Importação indisponível: GEMINI_IMPORT_API_KEY não configurada.",
        )

    dados = _ler_pdf(request, arquivo)

    try:
        texto, paginas = extracao_pdf.extrair_texto(
            dados, settings.IMPORT_MAX_PDF_PAGINAS
        )
    except extracao_pdf.PaginasDemaisError as e:
        raise HTTPException(
            status_code=422,
            detail=(
                f"PDF com {e.paginas} páginas — o limite é "
                f"{settings.IMPORT_MAX_PDF_PAGINAS}."
            ),
        )
    except Exception as e:
        # PDF corrompido/ilegível (pdfplumber/pdfminer levantam classes
        # variadas). Só a classe no log — nunca conteúdo.
        logger.warning("[import] PDF ilegível: %s", e.__class__.__name__)
        raise HTTPException(status_code=400, detail=_DETAIL_ARQUIVO_INVALIDO)

    if not extracao_pdf.tem_camada_de_texto(texto):
        raise HTTPException(
            status_code=422,
            detail=(
                "Extrato escaneado não é suportado — envie o PDF original "
                "emitido pelo banco."
            ),
        )

    # Redação best-effort (ver services/import_extrato/redacao.py): CPF e
    # agência/conta (titular e contraparte) são confiáveis; nome do titular é
    # best-effort; nome de contraparte vai como está (resíduo documentado).
    nomes = [n for n in (current_user.nome_completo, current_user.username) if n]
    texto_redigido = redacao.redigir(texto, nomes)

    raw = gemini.extrair_extrato(texto_redigido)  # 503 em falha de API/chave

    try:
        extrato = ExtratoExtraido.model_validate_json(raw)
    except ValidationError as e:
        # NUNCA logar a exceção inteira: o ValidationError embute os VALORES
        # rejeitados (descrições/valores do extrato). Só contagem e locs.
        locs = [".".join(str(p) for p in err["loc"]) for err in e.errors()[:5]]
        logger.warning(
            "[import] resposta do Gemini rejeitada pelo schema: %d erros (%s)",
            len(e.errors()),
            ", ".join(locs),
        )
        raise HTTPException(
            status_code=502,
            detail="A extração retornou dados inválidos. Tente novamente.",
        )

    rec = reconciliar(extrato, TOLERANCIA)

    # Batch 2 — enriquecimento por linha. Só LEITURA (o preview segue stateless).
    enriquecido = enriquecimento.enriquecer(session, current_user.id, extrato)

    propostas = [e.fatura_proposta for e in enriquecido if e.fatura_proposta is not None]
    logger.info(
        "[import] preview extrato: bytes=%d paginas=%d chars=%d linhas=%d "
        "aplicavel=%s bate=%s categorizadas=%d pagamentos=%d unico=%d ambiguo=%d "
        "sem_match=%d flag_recorrencia=%d",
        len(dados), paginas, len(texto), len(extrato.linhas), rec.aplicavel, rec.bate,
        sum(1 for e in enriquecido if e.categoria_sugerida is not None),
        len(propostas),
        sum(1 for p in propostas if p.status == "match_unico"),
        sum(1 for p in propostas if p.status == "ambiguo"),
        sum(1 for p in propostas if p.status == "sem_match"),
        sum(1 for e in enriquecido if e.provavel_recorrencia),
    )
    return ExtratoPreviewResponse(
        extrato=extrato,
        enriquecimento=enriquecido,
        reconciliacao=ReconciliacaoExtratoOut(
            aplicavel=rec.aplicavel,
            saldo_inicial=str(rec.saldo_inicial),
            rendimento=str(rec.rendimento),
            soma_receitas=str(rec.soma_receitas),
            soma_debitos=str(rec.soma_debitos),
            soma_pagamentos_fatura=str(rec.soma_pagamentos),
            saldo_final_calc=str(rec.saldo_final_calc),
            saldo_final_declarado=str(rec.saldo_final_declarado),
            diferenca=str(rec.diferenca),
            bate=rec.bate,
        ),
    )
