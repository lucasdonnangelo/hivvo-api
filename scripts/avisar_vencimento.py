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
⚠️  DUAS RESTRIÇÕES OPERACIONAIS QUE NÃO MORAM NO CÓDIGO
═══════════════════════════════════════════════════════════════════════════════

1. O OPT-OUT OFERECIDO É HONRADO À MÃO. ATÉ O BATCH 2, É TRABALHO SEU.

   O e-mail diz "responda este e-mail pedindo para parar, e desligamos", e a
   resposta cai em contato@hivvo.app (settings.FEEDBACK_TO). Quem recebe esse
   pedido é o LUCAS, não um handler: desligar é um UPDATE MANUAL no Supabase.

       update usuarios set notificar_vencimento = false where email = '...';

   Isso é aceitável com 3 usuários — mas SÓ ENQUANTO FOR DE FATO HONRADO.
   Oferecer "responda para parar" e não agir é pior que não oferecer: some o
   controle e sobra a promessa. Se os pedidos passarem a acumular, isso é o
   sinal de que o Batch 2 (tela de preferência) virou urgente, não opcional.

   A ação mora FORA do código. É por isso que está escrita aqui, e não só num
   documento de planejamento que ninguém abre na hora de rodar o comando.

2. NÃO ENVIE DE VERDADE ANTES DO TEXTO ESTAR NO AR.

   Este é um envio recorrente novo, com padrão LIGADO. Termos e Política de
   Privacidade (hivvo-web) precisam DECLARAR o aviso periódico antes que ele
   exista para um usuário real. A restrição é precisa:

       --dry-run      → pode rodar quando quiser. Não envia e não grava nada.
       envio real     → só depois do DEPLOY do hivvo-web com o texto novo.

   A ordem aqui é o INVERSO da regra do #48. Lá sobe primeiro quem ACEITA (o
   backend passa a aceitar o campo antes de a tela mandá-lo). Aqui sobe
   primeiro quem DECLARA: a política tem que estar publicada antes do primeiro
   e-mail, porque depois do envio não há como declarar retroativamente.

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
from app.models.user import Usuario  # noqa: E402
from app.services.notificacoes.consulta import DIAS_DE_ANTECEDENCIA  # noqa: E402
from app.services.notificacoes.email import formatar_brl  # noqa: E402
from app.services.notificacoes.envio import executar, montar_payload  # noqa: E402


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

    # `hoje()` do produto, não date.today(): o servidor roda em UTC, e entre
    # 21h e meia-noite em Brasília a data do servidor já é o dia seguinte — o
    # job mandaria o aviso do dia errado, em silêncio.
    hoje = args.data or hoje_produto()
    alvo = hoje + dt.timedelta(days=DIAS_DE_ANTECEDENCIA)

    modo = "DRY-RUN (nada é enviado nem gravado)" if args.dry_run else "ENVIO REAL"
    print(f"[{modo}] hoje={hoje.isoformat()}  avisando vencimentos de {alvo.isoformat()}")

    # Session/engine explícitos e `dispose()` no fim: um job precisa TERMINAR e
    # fechar as conexões. No Railway (Batch 2), processo que não encerra faz as
    # execuções seguintes serem PULADAS — o job pararia sem erro nenhum.
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
    finally:
        engine.dispose()

    return 1 if resultado.falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
