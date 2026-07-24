"""Importação de fatura — Batch 1: preview STATELESS.

POST /import/fatura/preview: PDF de fatura + cartao_id -> JSON extraído
(schema validado no spike de 17/07) + bloco de reconciliação. NADA é
persistido — nem o arquivo, nem o resultado: processa em memória e descarta.
Escrita em transacoes/parcelas, distribuição por fatura e frontend são
batches seguintes.

PII/logs: o texto da fatura NUNCA vai para log — apenas metadados (bytes,
páginas, chars, nº de transações, bate). Reconciliação NÃO bater não é erro
HTTP: devolve 200 com bate=false e o cliente decide.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.core.rate_limit import _user_or_ip_key, limiter
from app.models.card import Cartao
from app.models.import_fatura_lote import ImportFaturaLote
from app.models.pagamento_fatura import PagamentoFatura
from app.models.user import Usuario
from app.schemas.import_fatura import (
    FaturaCommitRequest,
    FaturaCommitResponse,
    FaturaExtraida,
    FaturaPassadaOut,
    FaturaPreviewResponse,
    ReconciliacaoOut,
)
from app.services.faturas import total_fatura_cartao
from app.services.import_fatura import extracao_pdf, gemini, redacao
from app.services.import_fatura.persistencia import (
    ancora_competencia,
    competencias_passadas_com_lancamentos,
    competencias_passadas_da_fatura,
    materializar_fatura,
)
from app.services.import_fatura.reconciliacao import TOLERANCIA, reconciliar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])

_DETAIL_ARQUIVO_INVALIDO = "Arquivo inválido: envie um PDF de fatura."


def _get_card_for_user(session: Session, card_id: int, usuario_id: int) -> Cartao:
    # Mesmo contrato de routers/invoices.py: inexistente OU de outro usuário
    # -> 404 (anti-enumeração; nunca 403).
    card = session.get(Cartao, card_id)
    if not card or card.usuario_id != usuario_id:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    return card


def _faturas_passadas(
    session: Session, usuario_id: int, cartao_id: int, fatura: FaturaExtraida
) -> list[FaturaPassadaOut]:
    """Competências passadas que o commit criará (cálculo DRY em persistencia) +
    flag `ja_paga` (leitura de PagamentoFatura). Só LEITURA — o preview segue
    stateless. Ordenado cronologicamente para a tela de revisão."""
    comps = competencias_passadas_da_fatura(fatura)
    pagas: set[tuple[int, int]] = set()
    if comps:
        linhas = session.exec(
            select(PagamentoFatura.fatura_mes, PagamentoFatura.fatura_ano).where(
                PagamentoFatura.usuario_id == usuario_id,
                PagamentoFatura.cartao_id == cartao_id,
                PagamentoFatura.pago == True,  # noqa: E712
            )
        ).all()
        pagas = {(m, a) for m, a in linhas} & comps
    return [
        FaturaPassadaOut(mes=mes, ano=ano, ja_paga=(mes, ano) in pagas)
        for mes, ano in sorted(comps, key=lambda c: (c[1], c[0]))
    ]


def _ler_pdf(request: Request, arquivo: UploadFile) -> bytes:
    limite = settings.IMPORT_MAX_PDF_BYTES
    detail_413 = f"Arquivo excede o limite de {limite // (1024 * 1024)} MB."

    # Rejeição rápida pelo Content-Length (é o corpo multipart inteiro, então
    # com folga para o overhead) — mas o header não é confiável: o teto real
    # é confirmado lendo no máximo limite+1 bytes.
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


@router.post("/fatura/preview", response_model=FaturaPreviewResponse)
# Custo real (tier pago): limites mais apertados que o chat, mesmos mecanismos.
@limiter.limit("10/minute")
@limiter.limit("5/minute", key_func=_user_or_ip_key)
@limiter.limit("150/day", key_func=_user_or_ip_key)
def preview_fatura(
    request: Request,
    arquivo: UploadFile = File(...),
    cartao_id: int = Form(...),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not settings.GEMINI_IMPORT_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Importação indisponível: GEMINI_IMPORT_API_KEY não configurada.",
        )

    cartao = _get_card_for_user(session, cartao_id, current_user.id)

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
                "Fatura escaneada não é suportada — envie o PDF original "
                "emitido pelo banco."
            ),
        )

    # Redação best-effort (ver services/import_fatura/redacao.py): CPF e
    # finais são confiáveis; nome é frágil e endereço vai como está.
    nomes = [n for n in (current_user.nome_completo, current_user.username) if n]
    texto_redigido, mapa_reverso = redacao.redigir(texto, nomes)

    raw = gemini.extrair_fatura(texto_redigido)  # 503 em falha de API/chave

    try:
        fatura = FaturaExtraida.model_validate_json(raw)
    except ValidationError as e:
        # NUNCA logar a exceção inteira: o ValidationError embute os VALORES
        # rejeitados (descrições/valores da fatura). Só contagem e locs.
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

    redacao.restaurar_finais(fatura, mapa_reverso)
    rec = reconciliar(fatura, TOLERANCIA)

    logger.info(
        "[import] preview: cartao=%s bytes=%d paginas=%d chars=%d transacoes=%d bate=%s",
        cartao.id, len(dados), paginas, len(texto), len(fatura.transacoes), rec.bate,
    )
    return FaturaPreviewResponse(
        cartao_id=cartao.id,
        fatura=fatura,
        reconciliacao=ReconciliacaoOut(
            ancora=str(rec.ancora),
            soma_gastos=str(rec.soma_gastos),
            excluidos=str(rec.excluidos),
            total_a_pagar=str(rec.total_a_pagar),
            diferenca=str(rec.diferenca),
            bate=rec.bate,
            diferenca_secundaria=str(rec.diferenca_secundaria),
            bate_secundario=rec.bate_secundario,
        ),
        faturas_passadas=_faturas_passadas(session, current_user.id, cartao.id, fatura),
    )


@router.post("/fatura/commit", response_model=FaturaCommitResponse)
# Não chama o Gemini (mais barato que o preview), mas ESCREVE no banco — mesmos
# limites do preview, por simetria e para conter reenvios acidentais.
@limiter.limit("10/minute")
@limiter.limit("5/minute", key_func=_user_or_ip_key)
@limiter.limit("150/day", key_func=_user_or_ip_key)
def commit_fatura(
    request: Request,
    body: FaturaCommitRequest,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Grava a fatura revisada: transações/parcelas + faturas passadas pagas.

    ATÔMICO — tudo numa transação de banco; qualquer falha = rollback total
    (nada de fatura meio-gravada). Ancora tudo na competência declarada pela
    fatura (não re-deriva do ciclo do cartão). Idempotência pela inserção do
    lote PRIMEIRO: reimportar a mesma (cartao, competência) = 409.
    """
    cartao = _get_card_for_user(session, body.cartao_id, current_user.id)
    fatura = body.fatura

    # Revalida a aritmética NO SERVIDOR (o front pode ter editado) — NÃO é gate:
    # o preview já avisou se não bate. Entra só no recibo/log.
    rec = reconciliar(fatura, TOLERANCIA)
    ancora_mes, ancora_ano = ancora_competencia(fatura)

    # GUARD DE IDEMPOTÊNCIA (airtight): insere o lote ANTES de qualquer
    # lançamento, na mesma transação. O UNIQUE(usuario, cartao, mes, ano) é o
    # mecanismo — reimportar levanta IntegrityError no flush → 409. Um EXISTS
    # pré-checado NÃO fecharia a corrida de duplo-clique; o UNIQUE fecha.
    session.add(
        ImportFaturaLote(
            usuario_id=current_user.id,
            cartao_id=cartao.id,
            fatura_mes=ancora_mes,
            fatura_ano=ancora_ano,
        )
    )
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Essa fatura já foi importada.")

    # A partir daqui é tudo-ou-nada: qualquer falha (validação da competência,
    # erro de banco no meio da materialização) desfaz o lote JÁ flushado e os
    # lançamentos — nada de fatura meio-gravada. O rollback é explícito porque
    # nos testes o get_session é sobrescrito e não faz o unwind sozinho.
    try:
        res = materializar_fatura(session, current_user.id, cartao, fatura)

        # Faturas passadas marcadas pagas: REVALIDA no servidor que cada
        # competência é passado REAL deste cartão (tem lançamento EXISTENTE
        # anterior à âncora — criado agora ou por outro import), nunca fatura
        # arbitrária. Com dedup, a parcelada passada pode ter sido PULADA neste
        # request e ainda assim ser marcável (MULTI-FATURA). data_pagamento=None
        # (histórico: hoje() seria data falsa — Q3; status só olha `pago`).
        competencias_pagas = {(c.mes, c.ano) for c in body.competencias_pagas}
        marcaveis = (
            competencias_passadas_com_lancamentos(
                session, current_user.id, cartao.id, ancora_ano * 12 + ancora_mes
            )
            if competencias_pagas
            else set()
        )
        for mes, ano in competencias_pagas:
            if (mes, ano) not in marcaveis:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Competência {mes:02d}/{ano} não faz parte do histórico "
                        "desta importação."
                    ),
                )
            pagamento = session.exec(
                select(PagamentoFatura).where(
                    PagamentoFatura.usuario_id == current_user.id,
                    PagamentoFatura.cartao_id == cartao.id,
                    PagamentoFatura.fatura_mes == mes,
                    PagamentoFatura.fatura_ano == ano,
                )
            ).first()
            if pagamento is None:
                pagamento = PagamentoFatura(
                    usuario_id=current_user.id,
                    cartao_id=cartao.id,
                    fatura_mes=mes,
                    fatura_ano=ano,
                )
            pagamento.pago = True
            pagamento.data_pagamento = None
            # Cobertura (#9): valor_pago = total da fatura MATERIALIZADA desta
            # competência (inclui lançamentos de imports anteriores) — fonte
            # única da composição; o autoflush do exec garante que os
            # lançamentos recém-criados nesta transação entram na soma.
            pagamento.valor_pago = total_fatura_cartao(
                session, current_user.id, cartao.id, mes, ano
            )
            session.add(pagamento)

        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info(
        "[import] commit: cartao=%s competencia=%d/%d transacoes=%d parcelas=%d "
        "pagas=%d dedup=%d estornos_importados=%d bate=%s",
        cartao.id, ancora_mes, ancora_ano, res.transacoes_criadas,
        res.parcelas_criadas, len(competencias_pagas), res.parceladas_deduplicadas,
        res.estornos_importados, rec.bate,
    )
    return FaturaCommitResponse(
        transacoes_criadas=res.transacoes_criadas,
        parcelas_criadas=res.parcelas_criadas,
        faturas_marcadas_pagas=len(competencias_pagas),
        parceladas_deduplicadas=res.parceladas_deduplicadas,
        estornos_importados=res.estornos_importados,
        reconciliacao_bate=rec.bate,
    )
