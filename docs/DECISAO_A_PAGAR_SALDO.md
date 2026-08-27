# Decisão — "A pagar" e "Saldo" no Dashboard (novo eixo: já saiu vs a vencer)

> Para incorporar ao PLANO_PROJECAO.md (seção do modelo de fluxo). Origem: teste E2E do Claude Code
> revelou que "A pagar" incluía saídas à vista JÁ PAGAS (aluguel via PIX aparecia como "a pagar").
> Diagnóstico confirmou: o cálculo de fluxo não tem eixo "já saiu do caixa" vs "ainda vai sair".

## O PROBLEMA
"A pagar" (hoje = `despesas` do topo/integral) soma indistintamente:
- crédito/parcela/fatura que VENCE no futuro (isso é "a pagar" de verdade), E
- à vista / PIX / débito que JÁ SAIU no ato (isso NÃO é "a pagar" — já foi pago).
E "Saldo" (= Receitas − A pagar) acerta o caixa por acidente, herdando o erro.

## A DECISÃO (Caminho B COMPLETO — Lucas escolheu B completo de uma vez)
Introduzir um eixo explícito **"saída já ocorrida" × "saída a ocorrer"**, combinando forma de
pagamento + vencimento (não só data pura, que tem furos):

### "A PAGAR" = só o que VENCE e ainda NÃO saiu
- **À vista (Débito / Dinheiro / PIX):** saída JÁ OCORRIDA no dia da compra → NÃO entra em "A pagar"
  (independe de data; já saiu).
- **Crédito (parcela + avulsa de fatura):** saída A OCORRER no vencimento → entra em "A pagar" SSE
  o vencimento é no mês e NÃO passou (data_vencimento > hoje, ou fatura do mês ainda não paga).
- **Recorrência:** é à vista por definição (§ recorrência não passa por cartão) → tratar como à
  vista (já ocorre na data_ocorrencia; a_vir se ocorrência > hoje).
- Chave primária = **forma_pagamento** (à vista = já saiu; crédito = a vencer), refinada por data/
  vencimento. NÃO usar `a_vir` puro por data como "A pagar" — ele tem o furo da Fonte 2 (crédito
  avulso é sempre `realizado` por falta de dia de vencimento → esconderia crédito a vencer, o que é
  PIOR para o Hivvo, cujo core é cartão de crédito).

### "SALDO" = caixa PROJETADO de fim de mês
- Saldo = Receitas − (TODAS as saídas de fluxo do mês: à vista já pago + a vencer). "Como termino o
  mês." NÃO é "Receitas − A pagar" (que ignoraria o à vista já pago).
- No caso de teste (jul): Receitas 7k − aluguel pago 3k − 0 a vencer = **4k**.

## B COMPLETO — os furos a corrigir (Lucas: B completo de uma vez)
Do diagnóstico §6:
1. **Fonte 2 (avulsa de cartão) sem dia de vencimento:** hoje é sempre `realizado=True` porque a
   Transacao não guarda o vencimento da fatura. B completo: dar à Fonte 2 um dia de vencimento REAL
   derivado do `dia_vencimento` do CARTÃO (o cartão tem esse dado) + o mês/ano de fatura. Assim uma
   fatura de crédito a vencer cai corretamente em "a pagar" com o dia certo. [É o furo que mais
   distorce para quem usa crédito — prioridade dentro do B.]
2. **Presunção "vencido = pago" por data, sem consultar `Parcela.pago`:** parcela com vencimento ≤
   hoje mas não paga (atrasada) hoje some de "a pagar". B completo: reincorporar `Parcela.pago` /
   `data_pagamento` para tratar atraso (parcela vencida E não paga = ainda "a pagar"). CUIDADO: isso
   reintroduz `pago` como sinal — alinhar com a regra de que `pago` não governa a PROJEÇÃO integral,
   só a distinção pago/a-pagar do mês corrente. Documentar a fronteira.
3. **À vista com data futura no mês:** borda rara (à vista futura é estranha) — à vista é sempre
   "já saiu" por definição; se dia > hoje, tratar como já saiu mesmo assim (ou impedir no cadastro,
   já listado como item separado no §1.3.2).

## EXPOR NO BACKEND
- Campo dedicado **`a_pagar`** (saídas a ocorrer) em MensalResponse, em vez de reusar `despesas` do
  topo. O front lê `a_pagar` no card "A pagar".
- **`saldo`** do card = caixa projetado fim de mês (receitas − todas saídas de fluxo). Confirmar se
  o `saldo` do topo já é isso ou precisa ajuste.
- Manter `despesas` (consumo) e realizado/a_vir intactos (aditivo).

## PROJEÇÃO (Bloco 2) — decisão relacionada (mesma leva)
O destaque/início da projeção = **primeiro mês FUTURO (≥ corrente+1) com fluxo**; NUNCA o mês
corrente (esse é o Bloco 1, evita duplicação). Fallback: mês seguinte se não há fluxo à frente.
= o `mes_default` EXCLUINDO o mês corrente do resultado. Ajuste no /projection.

## IMPACTO / TESTES
- Mexe no coração do cálculo de fluxo (_lancamentos_mes, Fonte 2, schema). É 🔴 — modelo potente.
- Testes: à vista pago fora de "a pagar"; crédito a vencer DENTRO de "a pagar" (com dia de
  vencimento da Fonte 2); parcela atrasada (vencida não paga) ainda em "a pagar"; saldo = caixa fim
  de mês; consistência com realizado/a_vir; o caso de teste de referência (jul: a_pagar=0, saldo=4k).
- Aditivo onde possível; `despesas`/consumo/realizado/a_vir preservados.
