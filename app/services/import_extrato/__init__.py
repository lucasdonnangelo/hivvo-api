"""Importação de EXTRATO de conta — helpers puros portados do spike validado
(scripts/spike_extrato/), com os dois achados dobrados (rendimento no resumo;
PII de terceiros na redação).

Nenhum módulo aqui toca banco ou persiste nada: o fluxo é stateless por decisão
de design (Batch 1). O extrato é da CONTA, não de um cartão — não há cartao_id.
A orquestração vive no router (app/routers/import_extrato.py), seguindo o padrão
do projeto e espelhando o preview de fatura.

Reúso: o extrator de PDF (extracao_pdf) e os safety settings (gemini_safety) são
importados de infra compartilhada — não reimplementados aqui.
"""
