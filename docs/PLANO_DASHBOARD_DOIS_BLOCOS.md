# Hivvo — Dashboard em dois blocos: PRESENTE vs PROJEÇÃO

> Status: **CONSTRUÍDO**, com REVOGAÇÃO PARCIAL em 25/08/2026 (ver o bloco 🔴 no BLOCO 1:
> os QUATRO CAMPOS e "o toggle morre" caíram; a linha de topo virou três cards que FECHAM).
> Original: **EM DESENHO** (conceito fechado, layout a detalhar). Evolução do modelo de projeção
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

> ## 🔴 REVOGADO EM 25/08/2026 — os QUATRO CAMPOS e a morte do TOGGLE
>
> **O que foi revogado:** os "QUATRO CAMPOS (Lucas confirmou)" abaixo, e a
> decisão "**O TOGGLE MORRE**" que os justificava. O texto original fica
> INTACTO logo abaixo — é o registro do que se acreditava, e apagá-lo apagaria
> o motivo de a revogação existir.
>
> **O MOTIVO — uma premissa derrubada sem revisitar o que dependia dela.**
> Este plano fixou `SALDO = RECEITAS − A PAGAR`. Sob AQUELA definição a linha de
> quatro cards FECHAVA: três dos quatro formavam uma cadeia visível e só
> DESPESAS (consumo) era o forasteiro. O `DECISAO_A_PAGAR_SALDO.md`,
> **posterior**, redefiniu o Saldo para "Receitas − TODAS as saídas de fluxo (à
> vista já pago + a vencer)", explicitamente **"NÃO é Receitas − A pagar"**.
> Isso tornou o número mais correto e **quebrou a premissa aritmética do
> layout**. Ninguém voltou ao layout. O código seguiu a decisão nova
> (`statistics.py`: `saldo = receitas - despesas`), a tela seguiu o plano velho,
> e o resultado ficou dois anos-luz de qualquer conta que o usuário consiga fazer.
>
> **A MEDIÇÃO que fechou o caso** (25/08/2026, dados reais):
>
> | card | valor |
> |---|---:|
> | Receitas | 7.400,00 |
> | Despesas *(consumo)* | 6.180,00 |
> | A pagar | 245,00 |
> | Saldo | **6.465,00** |
>
> `7.400 − 6.180 = 1.220` ✗ · `7.400 − 245 = 7.155` ✗
> **NENHUM par de números visíveis produzia o Saldo.** O subtraendo verdadeiro é
> `stats.despesas` (FLUXO) = **935,00**, que não estava na tela. O Saldo tinha
> um operando invisível.
>
> ### A LINHA NOVA — DECIDIDA
>
> ```
> Receitas 7.400,00 · Saídas do mês 935,00 · Saldo no fim do mês 6.465,00
>                         saiu 690,00 · ainda sai 245,00
> ```
>
> `7.400 − 935 = 6.465`. Fecha, com **tudo visível**.
>
> **Os rótulos, e cada palavra tem motivo:**
> - **"Saídas do mês", nunca "Despesas".** A palavra *Despesas* já significa
>   CONSUMO (6.180,00) na aba Análise e no donut. Mesma palavra para dois
>   valores é o defeito que criou o bug do limite do cartão (*usado* ×
>   *comprometido*) — não se repete.
> - **"Saldo no fim do mês", nunca "Saldo atual".** O app não tem entidade
>   Conta; este número é resultado do mês. "Atual" prometeria ESTOQUE e
>   entregaria FLUXO. **UM saldo só**: "Saldo até agora" é exatamente o número
>   que nasce quando Conta existir (ver `PLANO_SALDO_CONTAS`), e meia versão
>   dele agora é trabalho para refazer.
> - **"ainda sai", nunca "a pagar".** Ver a descoberta do eixo, abaixo. O termo
>   "a pagar" **continua** no Bloco 2, nos Cartões e na Análise — sai só da
>   linha de topo.
>
> ### 🔴 REVOGADO TAMBÉM: "O TOGGLE MORRE"
>
> A morte do toggle valia enquanto a linha ainda CARREGAVA o consumo. Não vale
> mais. A tese era que as duas lentes SIMULTÂNEAS, com rótulos explícitos,
> ensinariam o modelo pela diferença visível. **Foi tentada, foi medida, e
> produziu uma linha em que nenhum par de números visíveis produz o Saldo.** A
> simultaneidade não ensinou a diferença: ela convidou a uma subtração errada.
>
> No lugar dela, **cada aba PASSA A POSSUIR UMA PERGUNTA**:
> - **Visão geral** responde *"como estou de caixa?"* — lente FLUXO, só ela.
> - **Análise** responde *"no que eu gastei?"* — lente CONSUMO, com Resultado do
>   mês, donut com valores, destaques, gasto por cartão.
>
> Isto NÃO ressuscita o toggle: o toggle alternava a lente da MESMA tela,
> escondendo uma atrás da outra. Aqui as duas estão visíveis ao mesmo tempo, em
> abas que já eram NÍVEIS DE ZOOM diferentes (ver "DIVISÃO DE TRABALHO" abaixo).
> O que mudou é que cada nível agora tem UMA lente, em vez de a Visão geral ter
> duas e nenhuma fechar.
>
> ### 🔴 A lente CONSUMO DEIXA DE EXISTIR na Visão geral — de propósito
>
> Com "Despesas" virando "Saídas do mês" (fluxo) **e** o donut removido,
> `stats.consumo` e `stats.categorias_consumo` não são mais lidos em
> `OverviewPage.tsx` — **a Visão geral inteira não tem mais nenhum número de
> consumo.** Isso é DELIBERADO, não sobra de refatoração. Quem encontrar isso e
> achar que foi acidente: não foi, e "consertar" reintroduz o defeito medido
> acima. O consumo vive na Análise.
>
> **Donut removido da Visão geral.** Era idêntico ao da Análise, que é mais
> completo (`showValues`, `size="lg"` — mostra valores além de percentual).
> Critério: **níveis de zoom** — resumo × detalhe, a mesma divisão que este
> plano já aplicava ao Bloco 2 vs Resumo.
>
> ### 🔴 INVARIANTE (vale para qualquer mudança futura nesta linha)
>
> **A linha tem que FECHAR com números visíveis na tela.** Nenhum card pode
> exibir um operando cujo par não esteja à vista. As duas somas prometidas são:
>
> ```
> receitas − saidas === saldo
> saiu + aindaSai   === saidas
> ```
>
> Guardadas por teste, não por disciplina: a derivação foi EXTRAÍDA do
> componente para `hivvo-web/src/lib/linhaDoMes.ts` (função pura) e o portão é
> `src/lib/linhaDoMes.test.ts`, no teste *"🔴 a cadeia FECHA"*. O motivo de a
> regra sair do JSX: o hivvo-web não tem teste de componente nem runner de
> mutação, então regra dentro do componente é regra sem portão — foi essa
> topologia que deixou passar tanto este defeito quanto o do limite do cartão.
> Cada campo é lido da SUA fonte e **nenhum é recalculado a partir dos outros**.
> Não é preferência de estilo: se o `saldo` fosse derivado de `receitas −
> saidas`, o teste da cadeia fecharia sozinho — vira TAUTOLOGIA e para de
> guardar qualquer coisa.
>
> E a cadeia sozinha **não** tapa esse buraco: ela é satisfeita por construção
> justamente quando alguém deriva. Por isso existem dois testes com fixture
> DELIBERADAMENTE INCONSISTENTE (`saldo = 999,00` com receitas 7.400 e saídas
> 935,00; `despesas = 500,00` com realizado 690 + a_vir 245) — valores
> que a API nunca produz, e é exatamente por isso que servem: só um número que a
> aritmética NÃO gera distingue leitura de cálculo. ⚠️ Não "consertar" essas
> fixtures: consertar apaga o teste.
>
> Verificado à mão (o hivvo-web não tem runner de mutação), sobre 17 testes:
>
> | mutação | vermelhos |
> |---|---:|
> | `saidas` ← `consumo.despesas` | 10 |
> | `aindaSai` ← `a_pagar` | 11 |
> | `saldo` ← `receitas − saidas` (derivar) | **1** — só o teste da fixture inconsistente |
> | `saidas` ← `saiu + aindaSai` (derivar) | 4 |
>
> A linha do `saldo` derivado é a que prova o argumento: **sem o teste da
> fixture inconsistente, essa mutação sobreviveria inteira** — os outros 16,
> cadeia inclusa, ficavam verdes.
>
> ### 🔴 DESCOBERTA DO EIXO — vale além deste batch
>
> **`a_pagar` e `a_vir` são eixos DIFERENTES e não são intercambiáveis.**
>
> - `a_vir` — eixo **TEMPO-no-mês-corrente**: dia > hoje. `realizado + a_vir ==
>   despesas` **por construção** (`statistics.py` calcula `a_vir` como
>   `despesas − realizado`).
> - `a_pagar` — eixo **DÍVIDA-de-crédito**: crédito cuja saída não ocorreu,
>   válido para QUALQUER mês. À vista/PIX/recorrência nunca entram.
>
> Uma **parcela vencida e não confirmada paga** conta em `realizado` (o dia já
> passou) **E** em `a_pagar` (ainda é dívida) — contada duas vezes. Medido, com
> R$ 690,00 vencendo dia 10 e R$ 245,00 dia 25, em 15/07:
>
> ```
> despesas(fluxo)   =  935.00
> realizado         =  690.00
> a_vir             =  245.00
> a_pagar           =  935.00   ← a despesa INTEIRA
> realizado + a_vir   =  935.00  == despesas ✓
> realizado + a_pagar = 1625.00  != despesas ✗
> ```
>
> No dataset que originou o batch os dois COINCIDIAM (245,00), porque o que já
> tinha saído era à vista/PIX/recorrência, que nunca é `a_pagar`. **Coincidência
> de dataset, não invariante** — e foi ela que quase fez a sublinha nascer com o
> rótulo errado. Antes de usar um dos dois no lugar do outro, medir.
>
> ### Porta que o próprio plano deixou aberta — AGORA USADA
>
> O plano dizia: *"Decomposição realizado/a-vir (§1.3.1) encaixa AQUI se fizer
> sentido ('já saiu X, ainda sai Y este mês') — a definir no layout se entra e
> como."* **Entrou**: é exatamente a sublinha `saiu 690,00 · ainda sai 245,00`.
> O backend já entregava `realizado` e `a_vir` em `MensalResponse` desde a
> §1.3.1 e **o Dashboard não lia nenhum dos dois** — o dado existia, faltava a
> pergunta que ele responde. Quando o contrato vier sem a decomposição, a
> sublinha SOME em vez de mentir (o fallback põe tudo em `saiu`, o que seria
> falso num mês corrente).

- **Âncora: mês corrente, FIXO** (não navega). Responde "como estou em [mês atual]?". [P1 CONFIRMADO.]
- ~~**QUATRO CAMPOS** (Lucas confirmou):~~ 🔴 **REVOGADO 25/08/2026** — viraram TRÊS
  (Receitas · Saídas do mês · Saldo no fim do mês + sublinha). Motivo e medição no bloco acima.
  1. **RECEITAS** — o que entra no mês (salário, etc.).
  2. **DESPESAS** — o que o usuário GASTOU/comprou no mês (CONSUMO — valor cheio das compras feitas
     no mês; a compra parcelada de R$2.000 conta INTEIRA aqui). Responde "quanto comprometi?".
  3. **A PAGAR** — o que VENCE no mês (FLUXO — parcelas/contas que saem da conta no mês; a parcela
     1/10 se vence no mês conta aqui, não o valor cheio). Responde "quanto sai da conta?".
  4. ~~**SALDO** — **RECEITAS − A PAGAR**~~ 🔴 **REVOGADO** pelo DECISAO_A_PAGAR_SALDO (saldo =
     receitas − TODAS as saídas de fluxo). Foi ESTA revogação, não revisitada no layout, que
     quebrou a linha. Texto original: (fluxo/caixa real: o que efetivamente sobra na conta).
     NÃO é receitas − despesas; o saldo é sobre CAIXA (o que vence), não sobre o que se comprou.
     [Lucas confirmou: saldo = receitas − a pagar.]
- ~~**O TOGGLE MORRE** (Lucas confirmou).~~ 🔴 **REVOGADO 25/08/2026** — a simultaneidade das
  duas lentes foi tentada, medida, e produziu uma linha em que nenhum par de números visíveis
  produz o Saldo. Cada aba passa a possuir UMA pergunta; ver o bloco acima. Texto original: Em vez de alternar entre "gasto" e "a pagar", os DOIS
  aparecem SIMULTANEAMENTE como campos (DESPESAS = consumo, A PAGAR = fluxo). Isso é MAIS claro que
  o toggle: mostra as duas verdades lado a lado com rótulos explícitos, ensinando o modelo pela
  diferença visível ("comprei R$2.000, mas pago R$0 este mês") em vez de esconder uma atrás da
  outra. [Substitui o toggle do 3b — retrabalho consciente: o toggle construído será removido.]
- ✅ **USADA em 25/08/2026** (virou a sublinha `saiu X · ainda sai Y`). **Decomposição realizado/a-vir** (§1.3.1) encaixa AQUI se fizer sentido ("já saiu X, ainda sai Y
  este mês") — a definir no layout se entra e como.
- Primeiro contato: "magro" e honesto. No caso de teste (nada vence em julho): RECEITAS=salário,
  DESPESAS=compras de julho, A PAGAR=0, SALDO=salário. Conta a história certa ("gastei mas não pago
  ainda; o Bloco 2 mostra quando").

### BLOCO 2 — "Sua projeção" (FUTURO) — DECIDIDO
- **Âncora: os próximos meses**, começando pelo primeiro mês com fluxo (o MÊS DEFAULT já calculado),
  que aparece em **DESTAQUE**. [P4 confirmado: destaque no primeiro mês com fluxo.]
- **Cada mês mostra: RECEITAS projetadas · A PAGAR (fluxo) · SALDO previsto** (receitas − a pagar).
  [Lucas confirmou: receita, a pagar + saldo previsto por mês.] Sempre FLUXO (projeção é o que vem
  a pagar; consumo não se aplica ao futuro).
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
