# docs/ — fonte única dos documentos do Hivvo

O Hivvo vive em dois repositórios (`hivvo-api` e `hivvo-web`) que compartilham
documentos de produto e de plano. **Esta pasta é a fonte canônica deles.**

## A regra

> **Edite sempre no `hivvo-api` e rode o sync. Nunca copie à mão.**

Cópia manual foi exatamente o que fez os docs divergirem: em 15/07/2026 três
compartilhados estavam com versões diferentes nos dois repos, e num deles
(`PLANO_PERFIL_CONFIG.md`) a cópia do web era **mais nova no mtime mas mais
velha no conteúdo** — uma cópia manual havia sobrescrito a versão corrigida com
a antiga. O mtime não protege ninguém; o script protege.

```bash
python scripts/sync-docs.py            # copia os compartilhados → hivvo-web/docs
python scripts/sync-docs.py --check    # não escreve; sai 1 se algo divergir
```

Destino padrão: `../hivvo-web/docs` (os repos são irmãos). Para outro caminho,
use `--dest ../caminho/docs` ou a variável `HIVVO_WEB_DOCS`.

## Docs COMPARTILHADOS (canônicos aqui, copiados para o hivvo-web)

Edite aqui. A cópia no `hivvo-web/docs` é gerada — qualquer edição feita lá é
perdida no próximo sync.

| Doc | Assunto |
|---|---|
| `DECISAO_A_PAGAR_SALDO.md` | Decisão de produto: "a pagar" vs saldo |
| `ESTADO_HIVVO_HANDOFF.md` | Estado geral do projeto / handoff entre sessões |
| `Hivvo_Referencia.md` | Referência do produto: visão, brand, telas, arquitetura dos dois repos |
| `PENDENCIAS_PRIORIZADAS.md` | Backlog priorizado (os dois repos) |
| `PLANO_3D_PAGAMENTO_FATURA.md` | Plano: pagamento de fatura |
| `PLANO_DASHBOARD_DOIS_BLOCOS.md` | Plano: dashboard em dois blocos |
| `PLANO_IMPORTACAO.md` | Plano: importação de dados |
| `PLANO_PERFIL_CONFIG.md` | Plano: separação Perfil vs Configurações |
| `PLANO_PROJECAO.md` | Plano: projeção |
| `PLANO_RESUMO.md` | Plano: tela de Resumo / análise |

A lista de verdade — a que o script obedece — é a constante `SHARED` em
[`scripts/sync-docs.py`](../scripts/sync-docs.py). Para tornar um doc
compartilhado, adicione-o lá **e** nesta tabela.

## Docs ESPECÍFICOS deste repo (não sincronizados)

Vivem só aqui e não têm contraparte no `hivvo-web`:

- `AUDITORIA_SEGURANCA.md` — auditoria de segurança do backend
- `AUDITORIA_TECNICA.md` — auditoria técnica do backend
- `DEPLOY_CRON.md` — checklist do painel do Railway para o serviço de cron do aviso de
  vencimento (#6). **Fica só aqui de propósito:** é configuração do serviço do backend, e
  mandá-la para o repo do frontend seria dar a alguém uma checklist que não é dele. Os docs
  compartilhados que o citam usam o caminho por extenso (`hivvo-api/docs/DEPLOY_CRON.md`),
  e não um link relativo que quebraria na cópia do `hivvo-web`.
- `PLANO_EXECUCAO_API.md` — plano de execução do backend (batches)
- `SESSAO_ATUAL_API.md` — diário de sessão do backend

O `hivvo-web` tem os seus (`AUDITORIA_FRONTEND.md`, `PLANO_EXECUCAO_WEB.md`,
`SESSAO_ATUAL_WEB.md`) — não os traga para cá.

Este `README.md` também é específico de repo: o `hivvo-web/docs/README.md` é um
aviso curto apontando para cá, e por isso nenhum dos dois entra no sync.
