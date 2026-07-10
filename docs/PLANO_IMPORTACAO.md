# Hivvo — Design da Importação de Fatura/Extrato (feature futura)

> Status: **EM DESENHO.** Insumo inicial: uma fatura real do Nubank (07/07/2026).
> Filosofia: o Hivvo é planejador — o usuário traz o passado (fatos na mesa) para planejar o
> futuro. A importação é o que torna o "Cenário 1" (usuário com histórico) viável em escala, sem
> digitação manual de 7 extratos. Sem ela, quase todo usuário novo cai no Cenário 2 (sem histórico).

## Por que esta feature existe
Público-alvo: high-income multi-cartão (ex.: 7 cartões em 5 bancos). Digitar tudo à mão é
inviável — mata o onboarding. A importação transforma a fatura exportada do banco em transações
modeladas (com parcelamento reconstruído e distribuído nas faturas certas por cartão), alimentando
a projeção de fluxo futuro que é o core do produto.

## FATURA vs EXTRATO (distinção crítica — decidir)
- **Fatura** (o exemplo Nubank): transações de UM ciclo de fechamento (ex.: 06 jun a 06 jul,
  vence 13 jul). Já vem organizada por ciclo — ALINHADA com o modelo do Hivvo (fatura_mes/ano).
- **Extrato**: movimentação da conta/cartão ao longo do tempo, sem o recorte de ciclo.
- **Inclinação:** pedir a FATURA (por ciclo), porque casa com o modelo (competência de fatura) e
  já traz o recorte de fechamento pronto. DECISÃO PENDENTE — confirmar com Lucas.

## O QUE A FATURA DO NUBANK REVELA (formato real)
Estrutura observada:
- Cabeçalho: titular, "FATURA 13 JUL 2026", "EMISSÃO 06 JUL 2026", período "DE 06 JUN A 06 JUL".
- Agrupamento por portador/cartão (final 6042, 9493 — múltiplos finais na mesma fatura!).
- Linhas de transação: `DATA | (ícone) final | descrição | valor`.
- Seção separada "Pagamentos e Financiamentos" (pagamentos da fatura, saldo anterior).

### Padrões que o parser PRECISA tratar:
1. **PARCELAMENTO — formato "X/Y" na descrição.** Ex.: "Blacktag - Parcela 4/7 · R$105,26".
   - A fatura mostra a PARCELA do mês (R$105,26) + o índice (4/7), NÃO o valor total nem o início.
   - O parser deve: detectar o padrão `Parcela X/Y` (ou variações), inferir que faltam (Y-X)
     parcelas, e criar as futuras nas próximas faturas (competência += 1 mês cada). O valor de cada
     parcela restante = o valor mostrado (assumindo parcelas iguais).
   - CUIDADO: o índice diz onde estamos (4/7 = já pagou 3, faltam 3 após esta). A projeção só deve
     criar as FUTURAS (5/7, 6/7, 7/7), não recriar as passadas (a menos que o usuário queira o
     histórico — decisão de escopo).
2. **IOF — linhas de taxa, não-compra.** Ex.: "IOF de Anthropic R$0,72", "IOF de Cloudflare R$2,69".
   - Decisão: importar como despesa própria (categoria "Taxas/IOF")? Agregar à compra-mãe? Ignorar?
     PENDENTE.
3. **Conversão de moeda (compras internacionais).** Ex.: "Anthropic BRL 20.00 = USD 3.86 ...";
   "Cloudflare USD 14.20 · Conversão USD 1 = R$5,40". O valor em R$ (o que importa pra fatura) está
   na linha principal; a conversão é detalhe. Parser usa o valor em R$; a conversão pode ser
   ignorada ou guardada como metadado. PENDENTE.
4. **Seção "Pagamentos e Financiamentos" — IGNORAR (ou tratar à parte).** Ex.: "Pagamento em 12 JUN
   -R$58,95" (verde, negativo — é ABATIMENTO da fatura, não gasto); "Saldo restante da fatura
   anterior R$0,00". Se importadas como despesa, invertem o sinal e poluem. Parser DEVE reconhecer
   e excluir esta seção da importação de transações.
5. **Múltiplos finais de cartão na mesma fatura** (6042, 9493). Uma fatura Nubank pode ter cartões
   adicionais (portadores). Decisão: tratar todos como o mesmo cartão (a fatura é uma só), ou
   separar por final? Provavelmente: mesma fatura = mesmo cartão no Hivvo (o final é só o portador
   físico). PENDENTE.

## DECISÕES DE PRODUTO PENDENTES (resolver antes do código do parser)
1. **Formato de entrada:** PDF direto (complexo — parsing de layout) OU pedir CSV (usuário exporta/
   converte)? Lucas inclinou: "ideal seria PDF, mas se aumentar muito a complexidade, pedir pra
   converter." → PROVÁVEL: começar por um formato estruturado (CSV/texto) e avaliar PDF depois.
   A fatura de exemplo é PDF/imagem — se o alvo é PDF, o parsing de layout é 🔴 alto.
2. **Fatura vs extrato:** confirmar que o usuário exporta FATURA (por ciclo).
3. **Bancos-alvo:** quais primeiro? (Nubank é o exemplo; teu público usa quais outros?) Cada banco
   tem formato próprio — começar por 1 (Nubank?) e estender.
4. **IOF / conversão / internacional:** como modelar (ver itens 2-3 acima).
5. **Escopo do passado:** importar só as parcelas FUTURAS (o que projeta) ou também o histórico
   completo de gastos passados? (Planejador → o que importa é o futuro; mas Lucas quer "fatos na
   mesa" — talvez o histórico também, pra contexto.)
6. **Cartão obrigatório:** ao importar, o sistema EXIGE que o cartão já exista (a fatura é "para"
   um cartão com ciclo de fechamento conhecido). Lucas confirmou: "o sistema precisa exigir a
   criação de um cartão para condizer com esses dados." → o fluxo é: cadastra cartão → importa a
   fatura DELE.
7. **Revisão/edição:** Lucas confirmou "o usuário precisa conseguir editar ou corrigir." → após o
   parse, tela de REVISÃO onde o usuário vê as N transações detectadas, corrige (categoria, valor,
   parcelamento) e confirma antes de gravar. Importação nunca é perfeita — a revisão é obrigatória.

## COMPLEXIDADE / FATIAMENTO (para quando implementar)
- **Parser de formato** (extrair linhas estruturadas): 🟡 (trabalhoso, mas mecânico) — SE for
  CSV/texto. Se for PDF, o parsing de layout é 🔴.
- **Detecção de parcelamento ("X/Y" → criar futuras):** 🔴 — o pedaço de maior valor e maior
  cuidado. Precisa de VÁRIOS exemplos de fatura (não só um) para cobrir os formatos de "Parcela
  X/Y" dos diferentes bancos. Este é o candidato a modelo potente — mas com múltiplos exemplos reais.
- **Filtro de não-compras** (IOF, pagamentos, saldos): 🟡.
- **Modelagem → transações/parcelas no banco** (distribuir nas faturas por cartão): 🟡-🔴 (reusa o
  modelo de parcela/fatura que já existe).
- **Tela de revisão/edição:** 🟡 frontend.
- **NÃO cabe num único dia de modelo potente bem-feito.** É feature de várias sessões.

## PRÓXIMOS PASSOS (quando retomar a importação)
1. Fechar as decisões pendentes acima (formato, bancos, IOF, escopo do passado).
2. Coletar MAIS exemplos de fatura reais (vários bancos, com parcelamentos variados) — insumo
   essencial para a detecção de "X/Y" robusta.
3. Só então implementar: parser → detecção de parcela (🔴, potente, com os exemplos) → modelagem →
   revisão.

## NÃO fazer hoje
A importação NÃO é o uso ideal do modelo potente hoje (feature imatura — decisões abertas, um só
exemplo de fatura). O potente hoje vai para a LÓGICA DO MÊS DEFAULT (especificada, complexa,
pronta). A importação se desenha aqui e se implementa nas próximas sessões.
