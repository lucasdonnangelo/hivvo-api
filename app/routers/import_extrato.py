"""Importação de EXTRATO de conta — preview STATELESS (Batches 1 e 2) + commit (Batch 3).

POST /import/extrato/preview: PDF de extrato de conta -> JSON extraído (schema
portado do spike, com o achado do rendimento) + bloco de reconciliação (balance
walk) + ENRIQUECIMENTO por linha (Batch 2: categoria sugerida, fatura proposta,
flag de recorrência — ver services/import_extrato/enriquecimento.py). NADA é
persistido — nem o arquivo, nem o resultado: processa em memória e descarta; o
enriquecimento só LÊ o banco. SEM cartao_id (o extrato é da CONTA, não de um
cartão).

POST /import/extrato/commit (Batch 3): a ÚNICA rota do fluxo que ESCREVE.
Materializa o extrato revisado — receitas e débitos viram Transacao, pagamento
de fatura vira PagamentoFatura com valor e data REAIS, o rendimento do resumo
vira receita "Rendimentos" — numa transação única, com o lote de idempotência
inserido primeiro (409 no reimport). Ver services/import_extrato/persistencia.py.

Espelha o preview de fatura (app/routers/import_fatura.py) e reusa o encanamento
validado: o extrator de PDF (extracao_pdf), o client Gemini com
GEMINI_IMPORT_API_KEY + SAFETY_SETTINGS, e o padrão de reconciliação em Decimal.

PII/logs: o texto do extrato NUNCA vai para log — apenas metadados (bytes,
páginas, chars, nº de linhas, aplicavel, bate). Reconciliação NÃO bater não é
erro HTTP: devolve 200 com bate=false e o cliente decide.
"""

import datetime as dt
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.core.rate_limit import _user_or_ip_key, limiter
from app.models.card import Cartao
from app.models.import_extrato_lote import ImportExtratoLote
from app.models.pagamento_fatura import PagamentoFatura
from app.models.user import Usuario
from app.schemas.import_extrato import (
    ExtratoCommitRequest,
    ExtratoCommitResponse,
    ExtratoExtraido,
    ExtratoPreviewResponse,
    ReconciliacaoExtratoOut,
)
from app.core.scrub import curto
from app.services.faturas import fatura_existe
from app.services.import_extrato import enriquecimento, gemini, redacao
from app.services.import_extrato.persistencia import (
    agrupar_pagamentos,
    materializar_extrato,
    normalizar_banco,
    resolver_indecisos,
    validar_categorias,
)
from app.services.import_extrato.reconciliacao import TOLERANCIA, reconciliar

# Reúso do extrator de PDF da fatura — é infra genérica (extração da camada de
# texto, sem OCR), não tem nada de fatura. Um lugar só (ver PENDENCIAS: promover
# para módulo neutro é polimento, não bloqueia).
from app.services.import_fatura import extracao_pdf

logger = logging.getLogger(__name__)

# Teto do nome de banco em log (#39). Menor que o MAX_TEXTO_LOG de mensagem de
# API: nome de instituição real cabe folgado em 40, então o corte é sinal de que
# veio outra coisa no campo — ver o comentário de resíduo no commit.
MAX_BANCO_LOG = 40

router = APIRouter(prefix="/import", tags=["import"])

_DETAIL_ARQUIVO_INVALIDO = "Arquivo inválido: envie um PDF de extrato de conta."


def _get_card_for_user(session: Session, card_id: int, usuario_id: int) -> Cartao:
    # Mesmo contrato de routers/invoices.py e do commit de fatura: inexistente
    # OU de outro usuário -> 404 (anti-enumeração; nunca 403).
    card = session.get(Cartao, card_id)
    if not card or card.usuario_id != usuario_id:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    return card


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
        "sem_match=%d flag_recorrencia=%d datas_suspeitas=%d",
        len(dados), paginas, len(texto), len(extrato.linhas), rec.aplicavel, rec.bate,
        sum(1 for e in enriquecido if e.categoria_sugerida is not None),
        len(propostas),
        sum(1 for p in propostas if p.status == "match_unico"),
        sum(1 for p in propostas if p.status == "ambiguo"),
        sum(1 for p in propostas if p.status == "sem_match"),
        sum(1 for e in enriquecido if e.provavel_recorrencia),
        # Só a CONTAGEM: a data de uma linha é conteúdo do extrato e não vai para
        # log, como a descrição e o valor.
        sum(1 for e in enriquecido if e.data_suspeita is not None),
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


@router.post("/extrato/commit", response_model=ExtratoCommitResponse)
# Não chama o Gemini (mais barato que o preview), mas ESCREVE no banco — mesmos
# limites do preview, por simetria e para conter reenvios acidentais.
@limiter.limit("10/minute")
@limiter.limit("5/minute", key_func=_user_or_ip_key)
@limiter.limit("150/day", key_func=_user_or_ip_key)
def commit_extrato(
    request: Request,
    body: ExtratoCommitRequest,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Grava o extrato revisado: receitas + débitos + pagamentos de fatura (+ rendimento).

    ATÔMICO — tudo numa transação de banco; qualquer falha = rollback total
    (nada de extrato meio-gravado). Idempotência pela inserção do lote PRIMEIRO:
    reimportar o mesmo (banco, período) = 409. Espelha o commit de fatura.

    O request traz o extrato REVISADO e as decisões por linha, e o servidor
    REVALIDA tudo (não confia no que o front editou): categoria contra a lista
    do usuário, cartão contra a propriedade, competência contra a existência da
    fatura, e o default "não importar" da receita recorrente recomputado aqui.
    """
    extrato = body.extrato

    # O período é a CHAVE do lote de idempotência — sem ele não há guard, então
    # o commit exige o que o preview tolera ausente (o preview só perde o
    # balance walk). Mensagem própria em vez do 422 cru do Pydantic: o front
    # mostra `detail` e o usuário pode digitar as datas na revisão.
    if extrato.periodo is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "O extrato não traz o período (de/até) — informe o período para "
                "importar."
            ),
        )
    periodo_de = dt.date.fromisoformat(extrato.periodo.de)
    periodo_ate = dt.date.fromisoformat(extrato.periodo.ate)
    # Antes do flush do lote: o CHECK de ordem do período levantaria
    # IntegrityError no MESMO flush do UNIQUE e viraria um 409 mentiroso.
    if periodo_de > periodo_ate:
        raise HTTPException(
            status_code=422, detail="Período inválido: a data inicial é posterior à final."
        )

    # Revalida o balance walk NO SERVIDOR (o front pode ter editado) — NÃO é
    # gate: o preview já avisou se não fecha. Entra só no recibo/log.
    rec = reconciliar(extrato, TOLERANCIA)

    # GUARD DE IDEMPOTÊNCIA (airtight): insere o lote ANTES de qualquer
    # lançamento, na mesma transação. O UNIQUE(usuario, banco, periodo) é o
    # mecanismo — reimportar levanta IntegrityError no flush → 409. Um EXISTS
    # pré-checado NÃO fecharia a corrida de duplo-clique; o UNIQUE fecha.
    session.add(
        ImportExtratoLote(
            usuario_id=current_user.id,
            banco=normalizar_banco(extrato.banco),
            periodo_de=periodo_de,
            periodo_ate=periodo_ate,
        )
    )
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Esse extrato já foi importado.")

    # A partir daqui é tudo-ou-nada: qualquer falha (cartão alheio, competência
    # sem fatura, erro de banco no meio da materialização) desfaz o lote JÁ
    # flushado e os lançamentos. O rollback é explícito porque nos testes o
    # get_session é sobrescrito e não faz o unwind sozinho.
    try:
        decisoes, puladas = resolver_indecisos(session, current_user.id, extrato.linhas)
        categorias = validar_categorias(
            session, current_user.id, extrato.linhas, decisoes
        )
        res = materializar_extrato(
            session, current_user.id, extrato, decisoes, categorias,
            body.importar_rendimento,
        )
        res.receitas_puladas_recorrencia = puladas

        # Pagamentos de fatura: o extrato é a fonte AUTORITATIVA do pagamento —
        # valor_pago = o valor REAL da linha (não o total ASSUMIDO da fatura) e
        # data_pagamento = a data REAL (não None, não hoje()). É a sinergia #9:
        # se o real cobre menos que o total, status_fatura passa a
        # `paga_parcial` e a descoberta volta ao "A pagar" — verdade de caixa
        # vencendo presunção, que é o ponto.
        for (cartao_id, mes, ano), (valor, data_pagamento) in agrupar_pagamentos(
            extrato.linhas, decisoes
        ).items():
            _get_card_for_user(session, cartao_id, current_user.id)
            # Só fatura que EXISTE (tem lançamento) pode ser quitada — mesma
            # regra do PUT de pagamento. PagamentoFatura numa competência vazia
            # é fantasma: status_fatura devolve "vazia" e o pagamento fica
            # invisível na UI.
            if not fatura_existe(session, current_user.id, cartao_id, mes, ano):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Não há fatura em {mes:02d}/{ano} nesse cartão — importe "
                        "a fatura antes de registrar o pagamento."
                    ),
                )
            pagamento = session.exec(
                select(PagamentoFatura).where(
                    PagamentoFatura.usuario_id == current_user.id,
                    PagamentoFatura.cartao_id == cartao_id,
                    PagamentoFatura.fatura_mes == mes,
                    PagamentoFatura.fatura_ano == ano,
                )
            ).first()
            if pagamento is None:
                pagamento = PagamentoFatura(
                    usuario_id=current_user.id,
                    cartao_id=cartao_id,
                    fatura_mes=mes,
                    fatura_ano=ano,
                )
            elif pagamento.pago:
                res.pagamentos_sobrescritos += 1
            pagamento.pago = True
            pagamento.valor_pago = valor
            pagamento.data_pagamento = data_pagamento
            session.add(pagamento)
            res.pagamentos_registrados += 1

        session.commit()
    except Exception:
        session.rollback()
        raise

    # `banco` é o ÚNICO conteúdo de documento que este módulo loga, e fica de
    # propósito: é componente da chave de idempotência e o dado que a #33 (nomes
    # estruturalmente distintos para o mesmo banco) precisa para ser diagnosticada.
    #
    # RESÍDUO, com precisão: `normalizar_banco` limita o CHARSET (casefold, sem
    # acento, só alfanumérico), não o CONTEÚDO. Se o modelo confundir o campo e
    # trouxer o titular no lugar da instituição, "JOAO DA SILVA CPF 12345678901"
    # vira alfanumérico e continua sendo o nome de uma pessoa. O truncamento
    # abaixo limita o TAMANHO do vazamento, não a NATUREZA dele. O scrub do
    # Sentry pega o que tiver forma (o CPF); o nome não tem forma e passa.
    logger.info(
        "[import] commit extrato: banco=%s periodo=%s..%s receitas=%d debitos=%d "
        "pagamentos=%d sobrescritos=%d rendimento=%s ignoradas=%d recorrencia=%d bate=%s",
        curto(normalizar_banco(extrato.banco), MAX_BANCO_LOG), periodo_de, periodo_ate,
        res.receitas_criadas, res.debitos_criados, res.pagamentos_registrados,
        res.pagamentos_sobrescritos, res.rendimento_importado, res.linhas_ignoradas,
        res.receitas_puladas_recorrencia, rec.bate,
    )
    return ExtratoCommitResponse(
        receitas_criadas=res.receitas_criadas,
        debitos_criados=res.debitos_criados,
        pagamentos_registrados=res.pagamentos_registrados,
        pagamentos_sobrescritos=res.pagamentos_sobrescritos,
        rendimento_importado=res.rendimento_importado,
        linhas_ignoradas=res.linhas_ignoradas,
        receitas_puladas_recorrencia=res.receitas_puladas_recorrencia,
        reconciliacao_bate=rec.bate,
    )
