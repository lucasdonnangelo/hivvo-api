"""Importação de fatura de cartão — helpers puros portados do spike validado
em 17/07 (scripts/spike_import/, 2 faturas reais: Nubank e Itaú).

Nenhum módulo aqui toca banco ou persiste nada: o fluxo é stateless por
decisão de design (Batch 1). A orquestração vive no router
(app/routers/import_fatura.py), seguindo o padrão do projeto.
"""
