# Hivvo — Dashboard em dois blocos: PRESENTE vs PROJEÇÃO

> Status: **EM EXECUÇÃO** — conceito fechado; **Batch 1 (API do Bloco 2) ENTREGUE em 07/07/2026**
> e **REVISADO em 09/07/2026 pela leva "A pagar e Saldo"** (PLANO_PROJECAO §"Decisão — A pagar e
> Saldo"): `GET /statistics/projection?meses=12` →
> `{series: [{mes, ano, receitas, despesas, a_pagar, saldo}]}` — `despesas` = saídas integrais do
> mês (o que o contrato de 07/07 chamava `a_pagar`), `saldo = receitas − despesas` (caixa fim de
> mês) e `a_pagar` = ESTRITO (só crédito não saído, idêntico ao `/monthly`). `series[0]` = primeiro
> mês FUTURO com fluxo — NUNCA o corrente (esse é o Bloco 1); fallback mês seguinte. Meses sem
> fluxo com zeros, `meses` validado 1..60. `/yearly` e `/default-month` intocados; `/monthly`
> ganhou `a_pagar` (aditivo). Ver "Série de projeção (Bloco 2)" no SESSAO_ATUAL_API.md. Faltam os
> batches 2–3 (frontend). Evolução do modelo de projeção
> (PLANO_PROJECAO.md). Origem: ao testar como usuário de primeira vez, ficou claro que o Dashboard
> de "um mês genérico navegável + toggle" confunde — o usuário não distingue "como estou agora" de
> "o que vem". O mês default (já implementado) resolve METADE (qual mês destacar); a outra metade é
> SEPARAR visualmente presente de projeção. Sem essa separação, o mês default parece inútil.

## O PROBLEMA (diagnóstico)
Há DOIS EIXOS independentes que o Dashboard atual empilhou num controle só:
- **Eixo A — a lente:** fluxo ("a pagar") vs consumo ("gasto"). O que os números SIGNIFICAM.
- **Eixo B — o tempo:** qual mês. O toggle (Eixo A) e as setas (Eixo B) são coisas diferentes.

O usuário novo tem DUAS perguntas SIMULTÂNEAS que o Dashboard de mês-único força a alternar:
1. "Como estou AGORA?" (mês atual: receitas − despesas)
2. "O que devo ESPERAR nos próximos meses?" (projeção pra frente)

Mostrar um mês por vez obriga navegar entre as duas perguntas. A solução: mostrar as duas ao
mesmo tempo, em blocos conceitualmente separados.

## A SOLUÇÃO — dois blocos na mesma tela

### BLOCO 1 — "Seu mês" (PRESENTE) — DECIDIDO
- **Âncora: mês corrente, FIXO** (não navega). Responde "como estou em [mês atual]?". [P1 CONFIRMADO.]
- **QUATRO CAMPOS** (Lucas confirmou):
  1. **RECEITAS** — o que entra no mês (salário, etc.).
  2. **DESPESAS** — o que o usuário GASTOU/comprou no mês (CONSUMO — valor cheio das compras feitas
     no mês; a compra parcelada de R$2.000 conta INTEIRA aqui). Responde "quanto comprometi?".
  3. **A PAGAR** — o que VENCE no mês e ainda NÃO saiu (só CRÉDITO: parcela não paga + fatura a
     vencer; à vista/PIX/recorrência saem no ato e ficam FORA). Responde "quanto ainda vai sair da
     conta?". [REFINADO 09/07/2026 pela leva "A pagar e Saldo" — campo `a_pagar` do `/monthly`.]
  4. **SALDO** — caixa PROJETADO de fim de mês = **RECEITAS − TODAS as saídas de fluxo do mês**
     (à vista já pago + crédito a vencer + recorrência). Responde "como termino o mês".
     [SUPERSEDE o "receitas − a pagar" confirmado antes: a decisão de 09/07 (PLANO_PROJECAO
     §"Decisão — A pagar e Saldo") mostrou que receitas − a_pagar ignoraria o à vista já pago —
     ex. jul: 8k − aluguel 2k PIX = 6k, com a_pagar = 0. É o `saldo` do topo do `/monthly`.]
- **O TOGGLE MORRE** (Lucas confirmou). Em vez de alternar entre "gasto" e "a pagar", os DOIS
  aparecem SIMULTANEAMENTE como campos (DESPESAS = consumo, A PAGAR = fluxo). Isso é MAIS claro que
  o toggle: mostra as duas verdades lado a lado com rótulos explícitos, ensinando o modelo pela
  diferença visível ("comprei R$2.000, mas pago R$0 este mês") em vez de esconder uma atrás da
  outra. [Substitui o toggle do 3b — retrabalho consciente: o toggle construído será removido.]
- **Decomposição realizado/a-vir** (§1.3.1) encaixa AQUI se fizer sentido ("já saiu X, ainda sai Y
  este mês") — a definir no layout se entra e como.
- Primeiro contato: "magro" e honesto. No caso de teste (nada vence em julho): RECEITAS=salário,
  DESPESAS=compras de julho, A PAGAR=0, SALDO=salário. Conta a história certa ("gastei mas não pago
  ainda; o Bloco 2 mostra quando").

### BLOCO 2 — "Sua projeção" (FUTURO) — DECIDIDO
- **Âncora: os próximos meses**, começando pelo **primeiro mês FUTURO com fluxo** (≥ corrente+1 —
  NUNCA o corrente, que é o Bloco 1; fallback mês seguinte), que aparece em **DESTAQUE**.
  [Refinado 09/07/2026 — antes era o mês default, que podia ser o corrente e duplicaria o Bloco 1.]
- **Cada mês mostra: RECEITAS projetadas · saídas do mês (`despesas`) · SALDO previsto**
  (receitas − despesas). O `a_pagar` estrito (só crédito) também vem na série, idêntico ao
  `/monthly` do mesmo mês — o front escolhe o rótulo/campo a destacar. Sempre FLUXO (projeção é o
  que vem; consumo não se aplica ao futuro).
- **Horizonte: 12 MESES** por padrão. [Lucas: "12 meses é ideal — muita gente parcela até 12x,
  acima é raro."] Uma compra em 12x aparece inteira na projeção (o usuário vê o fim do compromisso).
  O backend tem HORIZONTE_MESES=60, mas o Bloco 2 EXIBE 12; navegação além é opcional/futuro.
- **Formato: CARDS/LINHAS por mês** (valores claros e acionáveis). [Lucas aceitou a recomendação.]
  O gráfico de evolução fica no Resumo (3c), não no Bloco 2 — ver divisão abaixo.
- Caso de teste: agosto (1ª parcela da Roupa + Mercado que vence em ago), setembro (parcela 2/10),
  ... — a projeção real se desenhando pelos 12 meses.

## DIVISÃO DE TRABALHO — Dashboard vs Resumo vs 3d (evita duplicar) — DECIDIDO
[Lucas confirmou a divisão.]
- **Bloco 2 do Dashboard:** projeção RESUMIDA — os próximos 12 meses com receitas/a-pagar/saldo,
  visão rápida "como estarei". Cards por mês, primeiro-com-fluxo em destaque. O essencial pra
  planejar.
- **Resumo (3c):** a ANÁLISE — gráfico de evolução mensal, comparações, categorias, mês a mês
  detalhado. Pra explorar. (A mesma separação presente/projeção pode valer aqui — a confirmar no 3c.)
- **3d:** o DETALHE POR CARTÃO — "dezembro: Itaú R$A, Nubank R$B". A lente micro.
- Cada um é um NÍVEL DE ZOOM diferente; não se duplicam.

## COMO O MÊS DEFAULT SE REENCAIXA (não foi desperdiçado)
Antes: "mês default = onde o Dashboard abre". Agora: "mês default = qual mês a PROJEÇÃO (Bloco 2)
destaca/começa". A lógica é a mesma (tem histórico → corrente; senão → primeiro mês com fluxo;
fallback mês seguinte), só o CONSUMO dela muda: em vez de fixar o mês da tela inteira, alimenta o
Bloco 2. O Bloco 1 é sempre o mês corrente. As duas peças se encaixam.

## DECISÕES (P1-P4) — a confirmar/ajustar com Lucas
- **P1 — Bloco 1 é o mês corrente FIXO** (não navega). [Proposto; confirmar.]
- **P2 — Bloco 2 é uma SEQUÊNCIA de meses** à frente (plural: "próximos meses"). [Confirmado por
  Lucas: "o que devo esperar nos próximos meses".]
- **P3 — Toggle fluxo/consumo só no Bloco 1** (presente); Bloco 2 é sempre fluxo. [Proposto;
  confirmar.]
- **P4 — Primeiro contato:** presente magro + projeção formando-se. [Confirmado por Lucas: "não
  teria nada a pagar em julho, mas é visão mais limpa".]

## O QUE PRECISA SER REFORMULADO/RECOLOCADO (não jogado fora)
- **Toggle atual** (troca a lente do Dashboard inteiro) → passa a viver só no Bloco 1.
- **Navegação de mês (setas no topo)** → sai do topo (presente é fixo); pode virar navegação DENTRO
  do Bloco 2 (avançar na projeção). A definir no layout.
- **Card "Projeção de [mês]" atual** → vira o Bloco 2 (a projeção), reorganizado como sequência.
- **Decomposição realizado/a-vir** → encaixa no Bloco 1 (presente).
- **Mês default (frontend)** → muda o consumo: alimenta o Bloco 2, não o mês da tela inteira.
- Possível impacto no **Resumo (3c)** — a mesma separação presente/projeção pode valer lá.

## PENDÊNCIAS DE LAYOUT (próximo passo do desenho)
- Disposição dos dois blocos (empilhados? lado a lado no desktop, empilhados no mobile via
  MobileLayout/DesktopLayout?).
- Como a sequência de meses do Bloco 2 se apresenta (cards por mês? mini-gráfico? lista?).
- Onde vai o gráfico "Evolução mensal" (já existe no Resumo) — Bloco 2 do Dashboard também?
- Navegação/horizonte do Bloco 2 (quantos meses mostra; como avança).
- O que acontece com o "Gastos por categoria" (donut) atual — presente, projeção, ou ambos?

## MÉTODO
Fechar P1 e P3 (P2/P4 já confirmados) → detalhar o layout → registrar no PLANO_PROJECAO.md →
fatiar em batches (provável: começar pela reorganização estrutural do Dashboard em dois blocos,
depois refinar cada um). Reorganização de Dashboard é trabalho a NÃO refazer — conceito e layout
travados ANTES do código.
