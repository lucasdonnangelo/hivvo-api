"""Aviso de vencimento de fatura por e-mail (#6, Batch 1).

Três módulos porque são três preocupações que se testam separado:

- `consulta`  — QUEM recebe O QUÊ. Só leitura, sem e-mail, sem transação.
- `email`     — como o aviso fica escrito. Só string.
- `envio`     — o ciclo guard → envia → commita, com a idempotência.

O agendador (Railway cron) e a tela de preferência são o Batch 2. Aqui o
ciclo roda por comando: scripts/avisar_vencimento.py.
"""
