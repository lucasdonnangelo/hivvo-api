#!/usr/bin/env python3
"""avisar_vencimento.py — envia o aviso de fatura a vencer em 3 dias (#6, Batch 1).

O agendador é o Batch 2. Aqui o ciclo roda POR COMANDO, para ser possível ver o
e-mail chegar antes de construir o agendamento em cima dele.

    python scripts/avisar_vencimento.py --dry-run
    python scripts/avisar_vencimento.py --data 2026-08-20 --dry-run
    python scripts/avisar_vencimento.py --usuario lucas@exemplo.com
    python scripts/avisar_vencimento.py

Saída: uma linha por destinatário, e um resumo. Exit 0 se nenhum envio falhou,
1 se algum falhou — cron verde com trabalho falhado é o pior tipo de portão.

═══════════════════════════════════════════════════════════════════════════════
🔴  ESTE SCRIPT RODA COMO CRON NO RAILWAY — ver a CHECKLIST DE DEPLOY
    do cron, na documentação operacional privada do projeto.
═══════════════════════════════════════════════════════════════════════════════

   Aquele doc tem a checklist do painel: env vars POR SERVIÇO, o Config file
   path, o Cron Schedule, e as três conferências do primeiro deploy — que só dá
   para fazer uma vez.

   O ponteiro está AQUI, e não só no handoff, porque quem for depurar "o cron
   não mandou nada" abre este arquivo, não um documento de 400 linhas. A defesa
   mora onde ela pode ser desfeita.

   O resumo do que pode dar errado silenciosamente:
     · sem `Config file path = /railway.cron.json`, o serviço herda o
       `railway.json` da raiz (roda `alembic upgrade head` de novo) E o
       `Procfile` (start = uvicorn, que NUNCA TERMINA → o Railway PULA toda
       execução seguinte, e o painel fica verde);
     · sem `SENTRY_DSN` no serviço de cron, `init_sentry()` é no-op calado —
       o mecanismo que existe para avisar de falha falha sem avisar.

═══════════════════════════════════════════════════════════════════════════════
⚠️  ORDEM DE DEPLOY — UMA REGRA SÓ
═══════════════════════════════════════════════════════════════════════════════

   SOBE PRIMEIRO O LADO QUE NÃO QUEBRA SOZINHO.
   QUEM CONSOME O CONTRATO NOVO SOBE POR ÚLTIMO.

   No #48 quem consumia era o front (mandava campo que o backend velho
   descartava). No #6 é o front de novo (lê `notificar_vencimento`, que o
   backend velho não devolve — o toggle ficaria desabilitado e mostrando
   DESLIGADO para um aviso que está LIGADO). Nos dois casos: **api → web**.

   ⚠️ Este bloco já esteve errado aqui. Ele dizia "Batch 1: sobe primeiro quem
   DECLARA" e "Batch 2: sobe primeiro quem OFERECE o controle", como se a regra
   alternasse. Não alternava: as duas eram racionalização do caso particular, e
   a segunda chegou a recomendar a ordem ERRADA (web antes de api) num batch em
   que o web era exatamente o consumidor. A restrição de Termos/Privacidade do
   Batch 1 é real, mas é OUTRA coisa — restrição de CONTEÚDO, não de contrato:

     · não enviar de verdade antes de a política declarar o envio (o texto
       precisa estar publicado; depois do primeiro e-mail não há como declarar
       retroativamente);
     · `--dry-run` pode rodar quando quiser, inclusive antes de tudo — não
       envia e não grava.

   Uma restrição diz QUANDO PODE ENVIAR. A outra diz QUEM SOBE PRIMEIRO. Tratar
   as duas como a mesma regra foi o erro.

═══════════════════════════════════════════════════════════════════════════════

SOBRE O --dry-run E O BANCO DE PRODUÇÃO

O `--dry-run` existe para conferir a consulta contra o banco de VERDADE: sem
ele, a primeira execução real seria também a primeira vez que alguém olha a
saída. Ele não envia e não escreve — nem `add`, nem `flush`, nem `commit`.

A regra do projeto de não rodar código local contra o Supabase de produção
existe porque o app ESCREVE. Um caminho comprovadamente de leitura é outra
coisa, e a prova é `tests/services/test_notificacoes_dry_run.py`, que instala
um listener de `before_flush` e falha se qualquer escrita for tentada (mesma
técnica que prova que o preview do extrato é stateless).

Ainda assim: `--dry-run` NÃO É `--read-only` do driver. Ele garante o caminho
deste comando, não o do processo inteiro.

SOBRE O E-MAIL NÃO CHEGAR EM DEV

Com o EMAIL_FROM sandbox, o Resend recusa destinatário que não seja o dono da
conta — ver o comentário em app/core/config.py. Para ver o envio local de
verdade, use um remetente de domínio verificado ou teste com o seu endereço.
"""

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.core.dates import hoje as hoje_produto  # noqa: E402
from app.core.observability import init_sentry  # noqa: E402
from app.models.user import Usuario  # noqa: E402
from app.services.notificacoes.consulta import DIAS_DE_ANTECEDENCIA  # noqa: E402
from app.services.notificacoes.email import formatar_brl  # noqa: E402
from app.services.notificacoes.envio import executar, montar_payload  # noqa: E402


logger = logging.getLogger("hivvo.aviso_vencimento")


def _flush_sentry() -> None:
    """Espera o Sentry despachar antes de o processo morrer.

    No-op quando o Sentry está inativo (sem DSN) ou o SDK não está instalado —
    import LAZY pelo mesmo motivo do `init_sentry`. O timeout existe para o job
    não ficar pendurado se o Sentry estiver fora: o aviso já foi enviado, e
    travar aqui faria a PRÓXIMA execução ser pulada pelo Railway.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.flush(timeout=5)


def _resolver_usuario(session: Session, referencia: str) -> Usuario:
    """Aceita id numérico ou e-mail. Erro ruidoso se não existir."""
    if referencia.isdigit():
        usuario = session.get(Usuario, int(referencia))
    else:
        usuario = session.exec(
            select(Usuario).where(Usuario.email == referencia)
        ).first()
    if usuario is None:
        raise SystemExit(f"usuário não encontrado: {referencia}")
    return usuario


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Envia o aviso de fatura a vencer em 3 dias.",
    )
    parser.add_argument(
        "--data",
        type=dt.date.fromisoformat,
        default=None,
        help=(
            "'hoje' da execução (YYYY-MM-DD). Default: hoje no fuso do produto "
            "(America/Sao_Paulo) — NUNCA a data do servidor."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="imprime quem receberia o quê. Não envia e não grava nada.",
    )
    parser.add_argument(
        "--usuario",
        default=None,
        help="restringe a um usuário (id ou e-mail).",
    )
    parser.add_argument(
        "--html-out",
        default=None,
        metavar="PASTA",
        help=(
            "salva o HTML de cada aviso em PASTA, para abrir no browser e "
            "conferir a peça renderizada. É o payload REAL (montar_payload), "
            "não uma reconstrução. Combine com --dry-run para não enviar."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Sentry ANTES de qualquer trabalho. O `exit 1` deixa o deploy vermelho no
    # painel, mas ninguém abre painel todo dia — e um cron que falha calado é o
    # pior portão possível, porque parece igual a um cron que não tinha o que
    # fazer. Com o Sentry ligado, a `LoggingIntegration` (default, ver
    # core/observability.py) transforma o `logger.error` de cada falha de envio
    # em EVENTO, sem código novo aqui.
    #
    # Sem SENTRY_DSN isto é no-op silencioso — e é justamente por isso que a
    # variável está na checklist de deploy (doc privada): o mecanismo que existe
    # para avisar de falha falharia sem avisar.
    init_sentry()

    # `hoje()` do produto, não date.today(): o servidor roda em UTC, e entre
    # 21h e meia-noite em Brasília a data do servidor já é o dia seguinte — o
    # job mandaria o aviso do dia errado, em silêncio.
    hoje = args.data or hoje_produto()
    alvo = hoje + dt.timedelta(days=DIAS_DE_ANTECEDENCIA)

    modo = "DRY-RUN (nada é enviado nem gravado)" if args.dry_run else "ENVIO REAL"
    print(f"[{modo}] hoje={hoje.isoformat()}  avisando vencimentos de {alvo.isoformat()}")

    # Session/engine explícitos e `dispose()` no fim: um job precisa TERMINAR e
    # fechar as conexões. No Railway, processo que não encerra faz as execuções
    # seguintes serem PULADAS — o job pararia sem erro nenhum.
    try:
        with Session(engine) as session:
            apenas = None
            if args.usuario:
                apenas = _resolver_usuario(session, args.usuario).id

            resultado, avisos = executar(
                session, hoje, dry_run=args.dry_run, apenas_usuario_id=apenas
            )

            if not avisos:
                print("nenhuma fatura a avisar — nenhum e-mail enviado.")

            destino = Path(args.html_out) if args.html_out else None
            if destino is not None:
                destino.mkdir(parents=True, exist_ok=True)

            for aviso in avisos:
                total = sum(f.restante for f in aviso.faturas)
                print(f"\n  {aviso.email} (usuario_id={aviso.usuario_id})")
                for fatura in aviso.faturas:
                    print(
                        f"    - {fatura.cartao_nome}: R$ {formatar_brl(fatura.restante)}"
                        f"  [{fatura.status}]"
                    )
                if len(aviso.faturas) > 1:
                    print(f"    total: R$ {formatar_brl(total)}")

                if destino is not None:
                    arquivo = destino / f"aviso-{aviso.usuario_id}.html"
                    arquivo.write_text(
                        montar_payload(aviso)["html"], encoding="utf-8"
                    )
                    print(f"    html: {arquivo}")

            print(
                f"\nresumo: {len(avisos)} usuário(s) elegível(is)"
                f" | enviados={resultado.enviados}"
                f" | já avisados hoje={resultado.ja_enviados}"
                f" | falhas={resultado.falhas}"
            )
    except Exception:
        # Falha CATASTRÓFICA (banco fora, config ausente, import quebrado): o
        # ciclo nem chegou a rodar. O `logger.error` do envio cobre a falha de
        # UM e-mail; isto cobre a execução inteira não ter acontecido — que é o
        # modo de falha que mais se parece com "não havia o que fazer".
        logger.exception("Aviso de vencimento abortou")
        _flush_sentry()
        engine.dispose()
        return 1
    finally:
        engine.dispose()

    if resultado.falhas:
        # Já foram logadas uma a uma (viram eventos pela LoggingIntegration);
        # esta linha é o resumo que o log do cron mostra primeiro.
        logger.error(
            "Aviso de vencimento terminou com %s falha(s) de envio", resultado.falhas
        )
    # ANTES do exit, sempre. O Sentry envia em BACKGROUND: num processo curto,
    # sair aqui mata a thread de envio antes de o evento partir, e a falha
    # desaparece exatamente no caminho construído para não deixá-la sumir.
    # Vale também no caminho de sucesso — a execução pode ter gerado eventos
    # de falha parcial e ainda retornar antes do flush.
    _flush_sentry()
    return 1 if resultado.falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
